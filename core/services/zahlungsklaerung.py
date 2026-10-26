"""Zahlungs-Cockpit V12: Sonderfälle im Zahlungseingang (26.10.2026).

Was hier liegt, ergänzt `zahlungszuordnung.py` (eine geparkte Zahlung → eine
Rechnung) um die Fälle, die im Alltag einer Verwaltung die Handarbeit machen:

- **Aufteilen** einer Zahlung auf mehrere offene Posten, auch verschiedener
  Verträge und Mieter (Sammelzahlung, Sozialdienst zahlt für zwei Mieter).
- **Zurücküberweisen** an den Absender: Fremdeingang (1190) oder Guthaben (2030).
- **Als Kaution erkennen**, wenn die Kaution auf dem Mietzinskonto statt auf dem
  Sperrkonto eingeht.
- **Rückbuchung** der Bank (Rücklastschrift, Rückweisung): Die ursprüngliche
  Zahlung wird storniert, die Rechnung ist wieder offen.
- **Guthaben automatisch verrechnen**, wenn es dafür vorgesehen ist.
- **Vorschläge** für einen Klärungsfall — nur Vorschläge, gebucht wird nichts.

WIE EINE AUFTEILUNG GEBUCHT WIRD (und warum so)

Jeder Teil ist ein eigener Zahlungseingang mit eigener Rechnung — so bleiben
OP-Status, Mieterkonto und Mahnwesen unverändert richtig. Der erste Teil ist
die geparkte Zahlung selbst (wie bei der Einzelzuordnung), jeder weitere trägt
die Bank-Referenz der Zahlung mit dem Zusatz `:teilN`, ein ungeklärter Rest
`:offen`, ein Guthaben-Rest `:rest`, ein zurücküberwiesener Rest `:zurueck`.
Die Stornierung (`stornieren`) findet alle Teile über diesen Präfix — und weil
die Bankbuchung an der ursprünglichen Zahlung hängt, wird eine Aufteilung nur
als Ganzes storniert: Ein einzelner Teil allein hinterliesse Geld auf 1190,
das keine Zeile mehr erklärt.

TILGUNGSREIHENFOLGE

Vorgeschlagen wird die älteste fällige Forderung zuerst (Art. 87 OR) — so
arbeitet schon die Sammelzuordnung. Nennt der Zahler in der Mitteilung, welche
Schuld er tilgt, gilt seine Erklärung (Art. 86 OR); deshalb ist der Vorschlag
nur vorbefüllt und lässt sich in der Oberfläche überschreiben.
"""
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext

from core.services.zahlungszuordnung import ZuordnungsFehler, _park_konto, offene_rechnungen

#: Bis zu diesem offenen Rest bietet die Teilzahlungsliste «Kleindifferenz
#: ausbuchen» an (z. B. von der Bank abgezogene Spesen). Gebucht wird über die
#: bestehende Abschreibung auf 3805 Debitorenverluste.
KLEINDIFFERENZ_CHF = Decimal('5.00')

#: Ab so vielen Tagen auf dem Durchlaufkonto bekommt ein Klärungsfall eine
#: Warnmarke und eine Pendenz: Dort liegt Geld, das jemandem gehört.
KLAERUNG_WARN_TAGE = 10

PARK_KONTEN = ('1190', '2030')
_TEIL = re.compile(r':(teil\d+|offen)$')


def betrag_aus(roh):
    """CHF-Eingabe («1'410.50», «1410,5») als Decimal, sonst None."""
    s = (roh or '').strip().replace("'", '').replace('’', '').replace(' ', '').replace(',', '.')
    if not s:
        return None
    try:
        d = Decimal(s).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None
    return d


def _referenz(zahlung):
    """Gemeinsame Referenz aller Teile. Manuell erfasste Zahlungen haben keine
    Bank-Referenz — sie bekommen `MAN<id>` (wie die Überzahlung im Bankabgleich)."""
    if not zahlung.bank_referenz:
        zahlung.bank_referenz = f"MAN{zahlung.pk}"
        zahlung.save(update_fields=['bank_referenz'])
    return zahlung.bank_referenz


def wurzel(zahlung):
    """Die ursprüngliche Zahlung einer Aufteilung (sich selbst, wenn keine)."""
    from finance.models import Zahlungseingang
    ref = zahlung.bank_referenz or ''
    while _TEIL.search(ref):
        ref = ref.rsplit(':', 1)[0]
        z = Zahlungseingang.objects.filter(bank_referenz=ref).first()
        if z is not None:
            zahlung = z
    return zahlung


def _lg(vertrag):
    return vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None


def _status_nachfuehren(rechnung):
    offen = rechnung.offener_betrag
    rechnung.status = 'bezahlt' if offen <= 0 else 'teilbezahlt'
    rechnung.save(update_fields=['status'])


def aufteilen(zahlung, teile, *, rest_ziel='offen', rest_vertrag=None, bank_nr='1020',
              user=None, heute=None):
    """Teilt eine geparkte Zahlung auf offene Posten auf.

    `teile`: Liste von (rechnung, betrag). `rest_ziel` für einen nicht verteilten
    Rest: 'offen' (bleibt ungeklärt auf 1190), 'guthaben' (Mieterguthaben 2030 von
    `rest_vertrag`) oder 'zurueck' (an den Absender zurück, Bank `bank_nr`).

    Erwartet gesperrte Objekte (select_for_update) und läuft atomar: Scheitert ein
    Teil (Periodensperre, fachlicher Fehler), wird nichts gebucht. Gibt ein dict
    mit 'teile', 'summe', 'rest', 'rest_ziel' zurück. Wirft ZuordnungsFehler oder
    PermissionError.
    """
    from finance.booking import buche
    from finance.models import Zahlungseingang
    from core.services import zahler as _zahler

    heute = heute or timezone.localdate()
    park_nr = zahlung.konto.nummer if zahlung.konto_id else ''
    if park_nr not in PARK_KONTEN or zahlung.status != 'verbucht':
        raise ZuordnungsFehler(_("Diese Zahlung liegt nicht auf dem Durchlauf- oder Guthabenkonto."))
    if rest_ziel not in ('offen', 'guthaben', 'zurueck'):
        raise ZuordnungsFehler(_("Unbekanntes Ziel für den Rest."))

    gesehen = set()
    summe = Decimal('0.00')
    for rechnung, betrag in teile:
        if rechnung.pk in gesehen:
            raise ZuordnungsFehler(_("Eine Rechnung ist doppelt ausgewählt."))
        gesehen.add(rechnung.pk)
        if betrag is None or betrag <= 0:
            raise ZuordnungsFehler(_("Jeder Teilbetrag muss grösser als 0 sein."))
        if rechnung.status not in ('offen', 'teilbezahlt') or not rechnung.vertrag_id:
            raise ZuordnungsFehler(_("«%(titel)s» ist nicht offen.") % {'titel': rechnung.titel})
        if betrag > rechnung.offener_betrag:
            raise ZuordnungsFehler(
                _("Auf «%(titel)s» sind nur CHF %(offen)s offen.")
                % {'titel': rechnung.titel, 'offen': rechnung.offener_betrag})
        # Ein Guthaben gehört einem Mieter — es tilgt nur dessen Forderungen.
        if zahlung.vertrag_id and rechnung.vertrag_id != zahlung.vertrag_id:
            raise ZuordnungsFehler(_("Dieses Guthaben gehört einem anderen Mieter und kann "
                                     "«%(titel)s» nicht tilgen.") % {'titel': rechnung.titel})
        summe += betrag
    if summe > zahlung.betrag:
        raise ZuordnungsFehler(_("Zugeteilt sind CHF %(summe)s, die Zahlung beträgt nur CHF %(betrag)s.")
                               % {'summe': summe, 'betrag': zahlung.betrag})
    rest = zahlung.betrag - summe
    if not teile and rest_ziel == 'offen':
        raise ZuordnungsFehler(_("Nichts zugeteilt."))
    if rest > 0 and rest_ziel == 'offen' and park_nr == '2030':
        raise ZuordnungsFehler(_("Ein Guthaben bleibt Guthaben — der Rest kann nicht «ungeklärt» werden."))
    if rest > 0 and rest_ziel == 'guthaben':
        if park_nr == '2030':
            rest_vertrag = zahlung.vertrag
        if rest_vertrag is None:
            raise ZuordnungsFehler(_("Für das Guthaben fehlt der Mieter."))

    ref = _referenz(zahlung)
    original_betrag = zahlung.betrag
    vertraege = {r.vertrag_id for r, _b in teile}
    verwendung = zahlung.guthaben_verwendung
    with transaction.atomic():
        for nr, (rechnung, betrag) in enumerate(teile, start=1):
            vertrag = rechnung.vertrag
            lg = _lg(vertrag)
            text = (f"Aufteilung {('Durchlaufkonto' if park_nr == '1190' else 'Guthaben')} → "
                    f"{vertrag.mieter} - {rechnung.titel}")
            if nr == 1:
                ziel = zahlung
                ziel.vertrag = vertrag
                ziel.debitoren_rechnung = rechnung
                ziel.konto = None
                ziel.betrag = betrag
                ziel.liegenschaft = lg or ziel.liegenschaft
                ziel.bemerkung = f"{ziel.bemerkung} → Teil 1: {rechnung.titel}"[:255]
                ziel.save()
            else:
                ziel = Zahlungseingang.objects.create(
                    vertrag=vertrag, debitoren_rechnung=rechnung, betrag=betrag,
                    datum_eingang=zahlung.datum_eingang, buchungs_monat=zahlung.buchungs_monat,
                    bemerkung=f"Teil {nr} aus Zahlung CHF {original_betrag}: {rechnung.titel}"[:255],
                    bank_referenz=f"{ref}:teil{nr}"[:140], liegenschaft=lg,
                    erstellt_von=user, status='verbucht')
            buche(park_nr, '1100', betrag, text, datum=heute, liegenschaft=lg, zahlung=ziel, user=user)
            _status_nachfuehren(rechnung)

        rest_zeile = None
        if rest > 0:
            if not teile:
                # Kein Teil: die Zahlung selbst wird zum Rest.
                rest_zeile = zahlung
            if rest_ziel == 'offen':
                rest_zeile = Zahlungseingang.objects.create(
                    betrag=rest, datum_eingang=zahlung.datum_eingang,
                    buchungs_monat=zahlung.buchungs_monat,
                    bemerkung=f"Ungeklärter Rest aus Zahlung CHF {original_betrag}"[:255],
                    bank_referenz=f"{ref}:offen"[:140], konto=_park_konto('1190'),
                    liegenschaft=zahlung.liegenschaft, erstellt_von=user, status='verbucht',
                    klaerung_notiz=zahlung.klaerung_notiz)
            elif rest_ziel == 'guthaben':
                lg = _lg(rest_vertrag)
                if rest_zeile is None:
                    rest_zeile = Zahlungseingang.objects.create(
                        vertrag=rest_vertrag, betrag=rest, datum_eingang=zahlung.datum_eingang,
                        buchungs_monat=zahlung.buchungs_monat,
                        bemerkung=f"Guthaben aus Zahlung CHF {original_betrag}"[:255],
                        bank_referenz=f"{ref}:rest"[:140], konto=_park_konto('2030'),
                        liegenschaft=lg, erstellt_von=user, status='verbucht',
                        guthaben_verwendung=verwendung if park_nr == '2030' else 'naechste_rechnung')
                else:
                    rest_zeile.vertrag = rest_vertrag
                    rest_zeile.konto = _park_konto('2030')
                    rest_zeile.liegenschaft = lg or rest_zeile.liegenschaft
                    rest_zeile.bemerkung = f"{rest_zeile.bemerkung} → Guthaben {rest_vertrag.mieter}"[:255]
                    rest_zeile.save()
                if park_nr == '1190':
                    buche('1190', '2030', rest, f"Guthaben {rest_vertrag.mieter} aus Zahlung CHF {original_betrag}",
                          datum=heute, liegenschaft=lg, zahlung=rest_zeile, user=user)
            else:  # zurueck
                if rest_zeile is None:
                    # Ohne Vertrag: Zurückerstattetes Geld ist kein Haben im Mieterkonto.
                    rest_zeile = Zahlungseingang.objects.create(
                        betrag=rest, datum_eingang=zahlung.datum_eingang,
                        buchungs_monat=zahlung.buchungs_monat,
                        bemerkung=f"Rest zurücküberwiesen {heute:%d.%m.%Y} (Zahlung CHF {original_betrag})"[:255],
                        bank_referenz=f"{ref}:zurueck"[:140], liegenschaft=zahlung.liegenschaft,
                        erstellt_von=user, status='verbucht')
                else:
                    rest_zeile.konto = None
                    rest_zeile.bemerkung = f"{rest_zeile.bemerkung} → zurücküberwiesen {heute:%d.%m.%Y}"[:255]
                    rest_zeile.save()
                buche(park_nr, bank_nr, rest, f"Rücküberweisung an Absender (Zahlung CHF {original_betrag})",
                      datum=heute, liegenschaft=zahlung.liegenschaft, zahlung=rest_zeile, user=user)

        # Absender nur lernen, wenn EIN Mieter gezahlt hat — bei mehreren
        # Verträgen wäre die Zuordnung beim nächsten Import geraten.
        gelernt = ''
        if len(vertraege) == 1 and teile:
            bew = zahlung.bankbewegungen.first()
            if bew is not None:
                gelernt, _r, _g = _zahler.aus_bewegung(bew.gegenpartei, bew.text)
                if gelernt:
                    _zahler.lerne(gelernt, teile[0][0].vertrag)
    return {'teile': len(teile), 'summe': summe, 'rest': rest, 'rest_ziel': rest_ziel,
            'gelernt': gelernt}


def zurueckueberweisen(zahlung, *, bank_nr='1020', valuta=None, user=None):
    """Geparktes Geld an den Absender zurück: Fremdeingang (1190) oder
    Mieterguthaben (2030). Gebucht wird Parkkonto an Bank; die Buchung hängt an
    der Zahlung, damit ein Storno sie mit aufhebt."""
    from finance.booking import buche
    valuta = valuta or timezone.localdate()
    park_nr = zahlung.konto.nummer if zahlung.konto_id else ''
    if zahlung.status != 'verbucht' or park_nr not in PARK_KONTEN:
        raise ZuordnungsFehler(_("Nur eine ungeklärte Zahlung oder ein Guthaben kann zurücküberwiesen werden."))
    if park_nr == '2030' and not zahlung.vertrag_id:
        raise ZuordnungsFehler(_("Dieses Guthaben hat keinen Mieter."))
    lg = _lg(zahlung.vertrag) if zahlung.vertrag_id else zahlung.liegenschaft
    with transaction.atomic():
        if park_nr == '2030':
            text = f"Rückerstattung Guthaben {zahlung.vertrag.mieter} [Z{zahlung.pk}]"
        else:
            text = f"Rücküberweisung Fremdeingang [Z{zahlung.pk}]"
        buche(park_nr, bank_nr, zahlung.betrag, text, datum=valuta, liegenschaft=lg,
              zahlung=zahlung, user=user)
        zahlung.konto = None
        zahlung.bemerkung = f"{zahlung.bemerkung} → zurückerstattet {valuta:%d.%m.%Y}"[:255]
        zahlung.save(update_fields=['konto', 'bemerkung'])
    return zahlung


def als_kaution(zahlung, vertrag, *, user=None):
    """Eine auf dem Mietzinskonto eingegangene Kaution erkennen.

    Gebucht wird 1190 an 2010 Kautionsverbindlichkeit mit dem Vertrags-Tag
    `Mietkaution [V<id>]` — dieselbe Marke, die `buche_kaution_einzahlung` und
    `_kaution_bilanziert` lesen: Die Kaution zählt damit für Freigabe und
    Rückzahlung, und eine spätere Bestätigung der Einzahlung bucht sie nicht
    ein zweites Mal. Das Geld liegt danach noch auf dem Mietzinskonto; eine
    Pendenz verlangt die Überweisung auf ein Sperrkonto auf den Namen des
    Mieters (Art. 257e Abs. 1 OR) — deren Belastung wird im Bank-Eingang auf
    1015 gebucht.
    """
    from core.models import Pendenz
    from core.views.fw._basis import _kaution_bilanziert
    from finance.booking import buche

    park_nr = zahlung.konto.nummer if zahlung.konto_id else ''
    if zahlung.status != 'verbucht' or park_nr != '1190':
        raise ZuordnungsFehler(_("Nur eine ungeklärte Zahlung (Konto 1190) kann als Kaution erkannt werden."))
    if vertrag.ist_kautionsversicherung:
        raise ZuordnungsFehler(_("Dieser Vertrag hat eine Kautionsversicherung — es gibt kein Kautionsgeld."))
    soll = vertrag.kautions_betrag or Decimal('0.00')
    if soll <= 0:
        raise ZuordnungsFehler(_("Im Vertrag ist keine Kaution vereinbart."))
    if _kaution_bilanziert(vertrag) > 0:
        raise ZuordnungsFehler(_("Für diesen Vertrag ist die Kaution bereits verbucht."))
    if zahlung.betrag != soll:
        raise ZuordnungsFehler(
            _("Die Zahlung (CHF %(betrag)s) entspricht nicht der vereinbarten Kaution (CHF %(soll)s). "
              "Einen Teil als Kaution zu verbuchen ist nicht vorgesehen — bitte mit dem Mieter klären.")
            % {'betrag': zahlung.betrag, 'soll': soll})
    lg = _lg(vertrag)
    with transaction.atomic():
        buche('1190', '2010', zahlung.betrag,
              f"Mietkaution [V{vertrag.pk}] {vertrag.mieter} — Eingang Mietzinskonto",
              datum=zahlung.datum_eingang, liegenschaft=lg, zahlung=zahlung, user=user)
        # Kein `vertrag` an der Zahlung: Eine Kaution ist kein Haben im
        # Mieterkonto — sie tilgt keine Miete.
        zahlung.konto = None
        zahlung.liegenschaft = lg or zahlung.liegenschaft
        zahlung.bemerkung = f"{zahlung.bemerkung} → Mietkaution {vertrag.mieter} [V{vertrag.pk}]"[:255]
        zahlung.save(update_fields=['konto', 'liegenschaft', 'bemerkung'])
        vertrag.kautions_art = 'sperrkonto'
        vertrag.kautions_einbezahlt_am = zahlung.datum_eingang
        vertrag.save(update_fields=['kautions_art', 'kautions_einbezahlt_am'])
        Pendenz.objects.get_or_create(
            quelle=f'auto:kaution-sperrkonto:{zahlung.pk}',
            defaults={
                'titel': f"Kaution CHF {zahlung.betrag:.2f} auf Sperrkonto überweisen – "
                         f"{vertrag.mieter.display_name}"[:200],
                'beschreibung': 'Die Kaution ist auf dem Mietzinskonto eingegangen. Sie gehört auf ein '
                                'Sperrkonto auf den Namen des Mieters (Art. 257e Abs. 1 OR). Die '
                                'Überweisung im Bank-Eingang auf Konto 1015 buchen.',
                'kategorie': 'finanzen', 'faellig_am': timezone.localdate(), 'vertrag': vertrag,
                'liegenschaft': lg})
    try:
        from core.services.mieterwechsel_fall import kaution_einbezahlt
        kaution_einbezahlt(vertrag, benutzer=user)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Kaution-Checkliste für Vertrag %s nicht nachgeführt',
                                            vertrag.pk, exc_info=True)
    return zahlung


def stornieren(zahlung, user=None):
    """Storniert eine Zahlung revisionssicher — samt aller Teile.

    Ist die Zahlung Teil einer Aufteilung, wird die ganze Aufteilung storniert
    (siehe Modulkopf). Gibt die stornierten Zahlungseingänge zurück. Erwartet
    eine laufende Transaktion; wirft PermissionError aus der Periodensperre.
    """
    from finance.models import Buchung, Zahlungseingang
    from finance.services import erstelle_storno_buchung

    zahlung = wurzel(zahlung)
    zahlung = Zahlungseingang.objects.select_for_update(of=('self',)).get(pk=zahlung.pk)
    if zahlung.status == 'storniert':
        return []
    zahlungen = [zahlung]
    if zahlung.bank_referenz:
        zahlungen += list(Zahlungseingang.objects.select_for_update().filter(
            bank_referenz__startswith=f"{zahlung.bank_referenz}:", status='verbucht')
            .exclude(id=zahlung.id))
    for zz in zahlungen:
        for b in Buchung.objects.filter(zahlungseingang=zz, ist_storno=False,
                                        storniert_am__isnull=True):
            erstelle_storno_buchung(b, benutzer=user)
        zz.status = 'storniert'
        zz.save(update_fields=['status'])
    # Status JEDER betroffenen Rechnung zurückrollen, nicht nur der ersten.
    for rech in {zz.debitoren_rechnung for zz in zahlungen if zz.debitoren_rechnung_id}:
        if rech.status in ('storniert', 'abgeschrieben'):
            continue
        offen = rech.offener_betrag
        rech.status = ('bezahlt' if offen <= 0
                       else 'offen' if offen >= rech.betrag else 'teilbezahlt')
        rech.save(update_fields=['status'])
    return zahlungen


def summe_mit_teilen(zahlung):
    """Ursprünglicher Bankbetrag einer (aufgeteilten) Zahlung."""
    from finance.models import Zahlungseingang
    total = zahlung.betrag
    if zahlung.bank_referenz:
        total += sum((z.betrag for z in Zahlungseingang.objects.filter(
            bank_referenz__startswith=f"{zahlung.bank_referenz}:", status='verbucht')
            .exclude(id=zahlung.id)), Decimal('0.00'))
    return total


def rueckbuchung(bewegung, zahlung, *, user=None):
    """Die Bank bucht eine Mieterzahlung zurück (Rücklastschrift, Rückweisung).

    Die ursprüngliche Zahlung samt aller Teile wird storniert: Die Gegenbuchung
    der Bankbuchung IST die Belastung auf dem Auszug — es entsteht keine zweite
    Buchung. Die Rechnungen sind danach wieder offen und laufen ins Mahnwesen.
    """
    from finance.models import Buchung

    if bewegung.status != 'offen' or bewegung.betrag >= 0:
        raise ZuordnungsFehler(_("Nur eine offene Belastung kann eine Rückbuchung sein."))
    zahlung = wurzel(zahlung)
    if zahlung.status != 'verbucht':
        raise ZuordnungsFehler(_("Diese Zahlung ist bereits storniert."))
    if not Buchung.objects.filter(zahlungseingang=zahlung, soll_konto=bewegung.konto,
                                  ist_storno=False, storniert_am__isnull=True).exists():
        raise ZuordnungsFehler(_("Diese Zahlung ist nicht über dieses Bankkonto eingegangen."))
    total = summe_mit_teilen(zahlung)
    if total != -bewegung.betrag:
        raise ZuordnungsFehler(_("Die Rückbuchung (CHF %(rueck)s) entspricht nicht der Zahlung (CHF %(total)s).")
                               % {'rueck': -bewegung.betrag, 'total': total})
    with transaction.atomic():
        stornieren(zahlung, user=user)
        bewegung.status = 'verbucht'
        bewegung.zahlung = zahlung
        bewegung.liegenschaft = zahlung.liegenschaft
        bewegung.bemerkung = f"Rückbuchung der Zahlung vom {zahlung.datum_eingang:%d.%m.%Y}"[:255]
        bewegung.save(update_fields=['status', 'zahlung', 'liegenschaft', 'bemerkung'])
    return zahlung


def guthaben_verrechnen(vertrag_ids=None, *, arten=('naechste_rechnung',), user=None):
    """Tilgt offene Rechnungen mit Mieterguthaben, die dafür vorgesehen sind.

    Läuft nach der Sollstellung (`naechste_rechnung`) und nach dem Verbuchen der
    Nebenkostenabrechnung (zusätzlich `nk_abrechnung`). Älteste Rechnung zuerst
    (Art. 87 OR), ältestes Guthaben zuerst. Eine gesperrte Periode lässt das
    Guthaben stehen, statt den Lauf abzubrechen. Gibt (anzahl, summe) zurück.
    """
    from core.services.zahlungszuordnung import zuordnen
    from finance.models import Zahlungseingang
    import logging

    qs = Zahlungseingang.objects.filter(status='verbucht', konto__nummer='2030',
                                        vertrag__isnull=False, guthaben_verwendung__in=arten)
    if vertrag_ids is not None:
        qs = qs.filter(vertrag_id__in=list(vertrag_ids))
    anzahl, summe = 0, Decimal('0.00')
    for vid in sorted(set(qs.values_list('vertrag_id', flat=True))):
        while True:
            with transaction.atomic():
                g = (Zahlungseingang.objects.select_for_update(of=('self',))
                     .filter(status='verbucht', konto__nummer='2030', vertrag_id=vid,
                             guthaben_verwendung__in=arten)
                     .select_related('konto', 'vertrag').order_by('datum_eingang', 'id').first())
                if g is None:
                    break
                offene = [r for r in offene_rechnungen(g.vertrag) if r.offener_betrag > 0]
                if not offene:
                    break
                try:
                    betrag, _rest, _n = zuordnen(g, offene[0], user=user)
                except (ZuordnungsFehler, PermissionError):
                    logging.getLogger(__name__).warning(
                        'Guthaben %s nicht verrechnet', g.pk, exc_info=True)
                    break
            anzahl += 1
            summe += betrag
    return anzahl, summe


def _tokens(s):
    # Auch an «/», «,», «-» trennen: «Miete Muster/Keller» nennt zwei Namen.
    return [t for t in re.split(r'[^\w]+', (s or '').lower()) if t]


def _name_passt(name, text):
    ziel, hay = _tokens(name), _tokens(text)
    if not ziel or not hay:
        return False
    n = len(ziel)
    return any(hay[i:i + n] == ziel for i in range(len(hay) - n + 1))


def offene_posten():
    from finance.models import DebitorenRechnung
    return (DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'], vertrag__isnull=False)
            .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft')
            .prefetch_related('zahlungseingaenge')
            .order_by('faellig_am', 'datum', 'id'))


def suche_posten(q, *, vertrag_ids=(), limit=40):
    """Offene Posten zur Suche: Mieter, Firma, Strasse, Ort, Objekt, Titel —
    oder eine Zahl: Betrag (offen oder Rechnungsbetrag) bzw. QR-Referenz.
    `vertrag_ids` nimmt die Posten dieser Verträge immer mit (Vorschläge)."""
    qs = offene_posten()
    q = (q or '').strip()
    treffer = []
    if q:
        if re.fullmatch(r"[\d'’ .,]+", q):
            b = betrag_aus(q)
            if b is not None:
                treffer += [r for r in qs[:2000] if r.offener_betrag == b or r.betrag == b]
            ziffern = re.sub(r'\D', '', q)
            if len(ziffern) >= 6:
                treffer += list(qs.filter(qr_referenz__contains=ziffern)[:limit])
        else:
            bedingung = Q()
            for w in q.split()[:4]:
                bedingung &= (Q(vertrag__mieter__nachname__icontains=w)
                              | Q(vertrag__mieter__vorname__icontains=w)
                              | Q(vertrag__mieter__firmen_name__icontains=w)
                              | Q(vertrag__einheit__liegenschaft__strasse__icontains=w)
                              | Q(vertrag__einheit__liegenschaft__ort__icontains=w)
                              | Q(vertrag__einheit__bezeichnung__icontains=w)
                              | Q(titel__icontains=w))
            treffer += list(qs.filter(bedingung)[:limit * 2])
    if vertrag_ids:
        treffer += list(qs.filter(vertrag_id__in=list(vertrag_ids)))
    gesehen, ergebnis = set(), []
    for r in treffer:
        if r.pk in gesehen or r.offener_betrag <= 0:
            continue
        gesehen.add(r.pk)
        ergebnis.append(r)
    return ergebnis[:limit]


def gruppiert(posten):
    """Offene Posten nach Mieter/Vertrag gruppiert, älteste Fälligkeit zuerst."""
    gruppen = {}
    for r in posten:
        v = r.vertrag
        g = gruppen.setdefault(v.id, {'vertrag': v, 'mieter': v.mieter.display_name if v.mieter_id else '—',
                                      'objekt': (f"{v.einheit.liegenschaft.strasse}, {v.einheit.bezeichnung}"
                                                 if v.einheit_id else ''),
                                      'posten': []})
        g['posten'].append({'r': r, 'offen': r.offener_betrag,
                            'teilbezahlt': r.status == 'teilbezahlt'})
    return list(gruppen.values())


def vorschlaege(zahlung, *, absender='', mitteilung='', referenz='', posten=None):
    """Bis zu drei Kandidaten für einen Klärungsfall, je mit Begründung.

    Nur Vorschläge — gebucht wird nichts. Reihenfolge der Kriterien: Referenz
    einer bekannten Rechnung, gelernter Absender, Name passt, Betrag passt
    genau, mehrere Posten eines Mieters ergeben zusammen den Betrag.
    """
    from finance.models import DebitorenRechnung
    from core.services import zahler as _zahler

    betrag = zahlung.betrag
    # `posten` einmal laden und für alle Klärungsfälle einer Seite weiterreichen.
    posten = posten if posten is not None else list(offene_posten()[:2000])
    vorschlag = {}

    def dazu(v, grund, rechnungen):
        if v.id in vorschlag:
            if grund not in vorschlag[v.id]['gruende']:
                vorschlag[v.id]['gruende'].append(grund)
            return
        vorschlag[v.id] = {'vertrag': v, 'mieter': v.mieter.display_name if v.mieter_id else '—',
                           'gruende': [grund], 'rechnungen': rechnungen}

    if referenz:
        r = (DebitorenRechnung.objects.filter(qr_referenz=re.sub(r'\D', '', referenz), vertrag__isnull=False)
             .select_related('vertrag__mieter').first())
        if r is not None:
            dazu(r.vertrag, _("Referenz gehört zu «%(titel)s»") % {'titel': r.titel},
                 [p for p in posten if p.vertrag_id == r.vertrag_id])
    if absender:
        v = _zahler.finde_vertrag(absender)
        if v is not None:
            dazu(v, _("Absender wurde schon diesem Mieter zugeordnet"),
                 [p for p in posten if p.vertrag_id == v.id])
    text = f"{absender} {mitteilung}"
    namens_treffer = set()
    for p in posten:
        v = p.vertrag
        if v.mieter_id and v.mieter.nachname and _name_passt(v.mieter.nachname, text):
            namens_treffer.add(v.id)
            dazu(v, _("Name «%(name)s» steht im Absender oder in der Mitteilung") % {'name': v.mieter.nachname},
                 [x for x in posten if x.vertrag_id == v.id])
    for p in posten:
        if p.offener_betrag == betrag:
            dazu(p.vertrag, _("Betrag passt genau auf «%(titel)s»") % {'titel': p.titel}, [p])
    je_vertrag = {}
    for p in posten:
        je_vertrag.setdefault(p.vertrag_id, []).append(p)
    for vid, liste in je_vertrag.items():
        if len(liste) > 1 and sum((p.offener_betrag for p in liste), Decimal('0')) == betrag:
            dazu(liste[0].vertrag, _("%(n)s offene Posten ergeben zusammen genau den Betrag")
                 % {'n': len(liste)}, liste)
    # Mehrere genannte Mieter, deren offene Posten zusammen genau den Betrag
    # ergeben: typisch für eine Zahlung des Sozialdienstes für zwei Mieter.
    genannt = [vorschlag[vid] for vid in namens_treffer if vid in vorschlag]
    if len(genannt) > 1:
        total = sum((r.offener_betrag for x in genannt for r in x['rechnungen']), Decimal('0'))
        if total == betrag:
            for x in genannt:
                x['gruende'].append(ngettext(
                    "zusammen mit %(n)s weiteren Mieter genau der Betrag — Sammelzahlung",
                    "zusammen mit %(n)s weiteren Mietern genau der Betrag — Sammelzahlung",
                    len(genannt) - 1) % {'n': len(genannt) - 1})
                x['zusammen'] = True
    rang = sorted(vorschlag.values(), key=lambda x: -len(x['gruende']))
    return rang[:3]


def tage_ungeklaert(zahlung, heute=None):
    heute = heute or timezone.localdate()
    return max(0, (heute - zahlung.datum_eingang).days)
