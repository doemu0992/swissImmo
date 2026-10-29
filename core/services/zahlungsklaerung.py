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
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext

from core.services.zahlungszuordnung import ZuordnungsFehler, _park_konto, offene_rechnungen
from core.utils.betrag import betrag_normalisieren

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
    s = betrag_normalisieren(roh)
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


def guthaben_verrechnen(vertrag_ids=None, *, arten=('naechste_rechnung',), rechnung_ids=None, user=None):
    """Tilgt mit einem dafür vorgesehenen Mieterguthaben die Rechnungen, die der
    aufrufende Lauf GERADE ERZEUGT hat (`rechnung_ids`).

    WARUM NUR DIESE (Korrektur 26.10.2026): «Mit nächster Rechnung verrechnen»
    ist eine Bestimmung, welche Schuld das Guthaben tilgt (Art. 86 OR) — die
    nächste Monatsmiete bzw. die NK-Nachzahlung. Die erste Fassung tilgte die
    ÄLTESTEN offenen Posten: Ein Rückstand samt Mahngebühr in der letzten
    Mahnstufe galt nach der Sollstellung als bezahlt und verschwand still aus
    dem Mahnwesen. Rückstände und Mahngebühren bleiben deshalb offen.

    Läuft nach der Sollstellung (`naechste_rechnung`) und nach dem Verbuchen der
    Nebenkostenabrechnung (zusätzlich `nk_abrechnung`). Jede Verrechnung steht im
    Logbuch und in der Bemerkung der Zahlung. Eine gesperrte Periode lässt das
    Guthaben stehen. Gibt (anzahl, summe) zurück.
    """
    from core.auth import log_aktion
    from core.services.zahlungszuordnung import zuordnen
    from finance.models import Zahlungseingang
    import logging

    if rechnung_ids is not None:
        rechnung_ids = set(rechnung_ids)
        if not rechnung_ids:
            return 0, Decimal('0.00')
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
                offene = [r for r in offene_rechnungen(g.vertrag) if r.offener_betrag > 0
                          and (rechnung_ids is None or r.pk in rechnung_ids)]
                if not offene:
                    break
                ziel = offene[0]
                try:
                    betrag, _rest, _n = zuordnen(g, ziel, user=user)
                except (ZuordnungsFehler, PermissionError):
                    logging.getLogger(__name__).warning(
                        'Guthaben %s nicht verrechnet', g.pk, exc_info=True)
                    break
                g.bemerkung = f"{g.bemerkung} (automatisch verrechnet)"[:255]
                g.save(update_fields=['bemerkung'])
            log_aktion(None, "Guthaben automatisch verrechnet", str(g.vertrag),
                       f"CHF {betrag} Guthaben (2030) auf {ziel.titel}", ziel=g.vertrag, user=user,
                       kategorie='finanzen')
            anzahl += 1
            summe += betrag
    return anzahl, summe


def _verrechnungsbuchungen(zahlung):
    """Aktive Buchungen 2030 an 1100 einer Zahlung: die Verrechnung eines Guthabens."""
    from finance.models import Buchung
    return Buchung.objects.filter(zahlungseingang=zahlung, soll_konto__nummer='2030',
                                  haben_konto__nummer='1100', ist_storno=False,
                                  storniert_am__isnull=True)


def verrechnung_rueckgaengig(zahlung, *, user=None):
    """Hebt NUR die Verrechnung eines Guthabens auf (Korrektur 26.10.2026).

    Ein Storno hebt alle Buchungen der Zahlung auf — auch den Geldeingang bzw.
    die NK-Gutschrift, aus der das Guthaben stammt. Hier wird nur die Buchung
    2030 an 1100 storniert: Die Rechnung ist wieder offen (mit ihrer Mahnstufe),
    der Betrag steht wieder als Guthaben auf 2030 — mit «offen lassen», damit
    der nächste Lauf ihn nicht gleich wieder verrechnet.
    """
    from finance.services import erstelle_storno_buchung
    buchungen = list(_verrechnungsbuchungen(zahlung))
    if zahlung.status != 'verbucht' or not buchungen or not zahlung.vertrag_id:
        raise ZuordnungsFehler(_("Diese Zahlung ist keine Verrechnung eines Guthabens."))
    rechnung = zahlung.debitoren_rechnung
    heute = timezone.localdate()
    with transaction.atomic():
        for b in buchungen:
            erstelle_storno_buchung(b, benutzer=user)
        zahlung.konto = _park_konto('2030')
        zahlung.debitoren_rechnung = None
        zahlung.guthaben_verwendung = 'offen'
        zahlung.bemerkung = f"{zahlung.bemerkung} → Verrechnung rückgängig {heute:%d.%m.%Y}"[:255]
        zahlung.save(update_fields=['konto', 'debitoren_rechnung', 'guthaben_verwendung', 'bemerkung'])
        if rechnung is not None and rechnung.status not in ('storniert', 'abgeschrieben'):
            offen = rechnung.offener_betrag
            rechnung.status = ('bezahlt' if offen <= 0
                               else 'offen' if offen >= rechnung.betrag else 'teilbezahlt')
            rechnung.save(update_fields=['status'])
    return rechnung


_FAMILIE = re.compile(r':(teil\d+|offen|rest|ueber|zurueck)$')


def _familie(zahlung):
    """Ursprüngliche Zahlung und alle aktiven Zeilen, die aus ihr entstanden
    sind (Teile, Rest, Überschuss, Rest eines Rests) — über den Präfix der
    Bank-Referenz."""
    from finance.models import Zahlungseingang
    ref = zahlung.bank_referenz or ''
    while _FAMILIE.search(ref):
        ref = ref.rsplit(':', 1)[0]
        z = Zahlungseingang.objects.filter(bank_referenz=ref).first()
        if z is not None:
            zahlung = z
    wurzel_z = Zahlungseingang.objects.select_for_update(of=('self',)).get(pk=zahlung.pk)
    familie = [wurzel_z]
    if wurzel_z.bank_referenz:
        familie += list(Zahlungseingang.objects.select_for_update(of=('self',)).filter(
            bank_referenz__startswith=f"{wurzel_z.bank_referenz}:", status='verbucht')
            .exclude(id=wurzel_z.id).order_by('id'))
    return wurzel_z, familie


def _ist_bank(konto):
    # 1015 ist das Mietkautions-Sperrkonto, keine Zahlungseingangsbank.
    return konto.nummer.startswith('10') and konto.nummer != '1015'


def zuordnung_aufheben(zahlung, *, user=None):
    """Legt eine falsch zugeordnete Bankzahlung zurück in die Klärungsfälle
    (Korrektur 26.10.2026).

    Anders als ein Storno bleibt der Geldeingang stehen — das Geld IST auf der
    Bank, nur nicht von diesem Mieter. Storniert wird jede Buchung, die aus der
    Zuordnung entstand (an 1100, Rest an 2030, dessen Verrechnung), samt aller
    Teile einer Aufteilung. Die Zahlung liegt danach als ungeklärt auf 1190,
    die Rechnungen sind wieder offen (Mahnstufe und 257d-Frist leben wieder auf,
    siehe `zahlungsverzug._wieder_oeffnen`), und der gelernte Absender wird
    vergessen, sonst bucht ihn der nächste Import gleich wieder auf denselben
    Mieter. Gibt (zahlung, anzahl_rechnungen, vergessener_absender) zurück.
    """
    from core.auth import log_aktion
    from finance.booking import buche
    from finance.models import Buchung
    from finance.services import erstelle_storno_buchung

    with transaction.atomic():
        wurzel_z, familie = _familie(zahlung)
        if wurzel_z.status != 'verbucht' or not any(z.vertrag_id for z in familie):
            raise ZuordnungsFehler(_("Diese Zahlung ist keinem Mieter zugeordnet."))
        buchungen = list(Buchung.objects.filter(zahlungseingang__in=familie, ist_storno=False,
                                                storniert_am__isnull=True)
                         .select_related('soll_konto', 'haben_konto'))
        if any(_ist_bank(b.haben_konto) or b.haben_konto.nummer in ('2010', '1015') for b in buchungen):
            raise ZuordnungsFehler(_("Ein Teil dieser Zahlung wurde zurücküberwiesen oder als Kaution "
                                     "gebucht — bitte zuerst diesen Teil stornieren."))
        eingaenge = [b for b in buchungen if _ist_bank(b.soll_konto)]
        if not eingaenge:
            raise ZuordnungsFehler(_("Nur eine Bankzahlung lässt sich zurück in die Klärung legen."))
        vertraege = {z.vertrag for z in familie if z.vertrag_id}
        rechnungen = {z.debitoren_rechnung for z in familie if z.debitoren_rechnung_id}
        mieter = ', '.join(sorted(str(v.mieter) for v in vertraege))
        heute = timezone.localdate()
        for b in buchungen:
            if b in eingaenge and b.haben_konto.nummer == '1190':
                continue  # Der Geldeingang auf dem Durchlaufkonto bleibt.
            erstelle_storno_buchung(b, benutzer=user)
            if b in eingaenge:
                # Direkt verbucht (z. B. gelernter Absender): neu auf 1190, am Tag des Eingangs.
                buche(b.soll_konto, '1190', b.betrag, f"Zuordnung aufgehoben: {b.beleg_text}"[:255],
                      datum=b.datum, liegenschaft=b.liegenschaft, zahlung=wurzel_z, user=user)
        for z in familie[1:]:
            z.status = 'storniert'
            z.save(update_fields=['status'])
        wurzel_z.konto = _park_konto('1190')
        wurzel_z.vertrag = None
        wurzel_z.debitoren_rechnung = None
        wurzel_z.betrag = sum((b.betrag for b in eingaenge), Decimal('0.00'))
        wurzel_z.bemerkung = f"{wurzel_z.bemerkung} → Zuordnung aufgehoben {heute:%d.%m.%Y}"[:255]
        wurzel_z.klaerung_notiz = (wurzel_z.klaerung_notiz or _("War irrtümlich %(mieter)s zugeordnet.")
                                   % {'mieter': mieter})[:255]
        wurzel_z.save(update_fields=['konto', 'vertrag', 'debitoren_rechnung', 'betrag', 'bemerkung',
                                     'klaerung_notiz'])
        for rech in rechnungen:
            rech.refresh_from_db()
            if rech.status in ('storniert', 'abgeschrieben'):
                continue
            offen = rech.offener_betrag
            rech.status = ('bezahlt' if offen <= 0
                           else 'offen' if offen >= rech.betrag else 'teilbezahlt')
            rech.save(update_fields=['status'])
        vergessen = _absender_vergessen(wurzel_z, vertraege)
    # Nach dem Commit: Frist und Fall sehen den wieder offenen Rückstand.
    from core.services.zahlungsverzug import pruefe_nach_zahlung
    for v in vertraege:
        pruefe_nach_zahlung(v)
        log_aktion(None, "Zuordnung aufgehoben", str(v),
                   f"CHF {wurzel_z.betrag} vom {wurzel_z.datum_eingang:%d.%m.%Y} zurück in die Klärungsfälle"
                   + (f"; Absender «{vergessen}» vergessen" if vergessen else ''),
                   ziel=v, user=user, kategorie='finanzen')
    return wurzel_z, len(rechnungen), vergessen


def _eingangsbuchungen_von(ids):
    from finance.models import Buchung
    return Buchung.objects.filter(
        Q(haben_konto__nummer='2030') & ~Q(soll_konto__nummer='2030')
        | Q(haben_konto__nummer='1190') & ~Q(soll_konto__nummer__in=PARK_KONTEN),
        zahlungseingang_id__in=ids, ist_storno=False)


def _eingangsbuchungen(zahlung):
    """Die ursprünglichen Buchungen, mit denen Geld auf ein Parkkonto kam — als
    Guthaben auf 2030 (Bank, 3020 bei einer NK-Gutschrift, 1190 als Rest) oder
    ungeklärt auf 1190 (Bank) —, storniert oder nicht."""
    return _eingangsbuchungen_von([zahlung.pk])


def _verwaiste_reste(zahlung):
    """Rest-Guthaben aus einer Verrechnung, die ein Storno nicht erreicht hat.

    Bis zur Korrektur bekam ein Rest nur dann die Referenz der Zahlung, wenn sie
    eine hatte. Eine NK-Gutschrift hat keine — ihr Rest («Rest-Guthaben aus
    Zuordnung (…)») blieb nach dem Storno stehen und hielt z. B. eine
    Mahngebühr als bezahlt. Die Kette wird über den Titel der vorher getilgten
    Rechnung nachverfolgt, wie `zuordnen` ihn schreibt.
    """
    from finance.models import Zahlungseingang
    kette, titel, nach_pk = [], (zahlung.debitoren_rechnung.titel if zahlung.debitoren_rechnung_id else None), zahlung.pk
    while titel:
        r = (Zahlungseingang.objects
             .filter(vertrag_id=zahlung.vertrag_id, status='verbucht', pk__gt=nach_pk,
                     bemerkung__startswith=f"Rest-Guthaben aus Zuordnung ({titel})"[:255])
             .select_related('debitoren_rechnung').order_by('pk').first())
        if r is None:
            break
        kette.append(r)
        titel = r.debitoren_rechnung.titel if r.debitoren_rechnung_id else None
        nach_pk = r.pk
    return kette


#: So lange nach einem Storno bietet das Cockpit «wiederherstellen» an.
WIEDERHERSTELLEN_TAGE = 60


def stornierte_guthaben():
    """Stornierte Zahlungen, die einem Mieter zugeordnet waren und deren
    Geldeingang mitstorniert wurde — noch nicht wiederhergestellt.

    Zwei Herkünfte: ein verrechnetes Mieterguthaben (2030) oder eine geparkte
    Bankzahlung (1190), die einem Posten zugeordnet war. In beiden Fällen
    hebt «Stornieren» auch den Eingang auf; wollte man nur die Zuordnung
    loswerden, fehlt jetzt Geld, das auf der Bank liegt.
    """
    from finance.models import Buchung, Zahlungseingang
    seit = timezone.now() - timedelta(days=WIEDERHERSTELLEN_TAGE)
    ids = set(Buchung.objects.filter(zahlungseingang__status='storniert', zahlungseingang__vertrag__isnull=False,
                                     soll_konto__nummer__in=PARK_KONTEN, haben_konto__nummer='1100',
                                     ist_storno=False, storniert_am__gte=seit)
              .values_list('zahlungseingang_id', flat=True))
    ids &= set(_eingangsbuchungen_von(ids).values_list('zahlungseingang_id', flat=True))
    schon = set()
    for bem in Zahlungseingang.objects.filter(status='verbucht', bemerkung__contains='[W').values_list('bemerkung', flat=True):
        schon.update(int(x) for x in re.findall(r'\[W(\d+)\]', bem))
    liste = list(Zahlungseingang.objects.filter(pk__in=ids - schon)
                 .select_related('vertrag__mieter', 'debitoren_rechnung').order_by('-datum_eingang', '-id'))
    for z in liste:
        eingaenge = list(_eingangsbuchungen(z).select_related('haben_konto'))
        z.wieder_betrag = sum((b.betrag for b in eingaenge), Decimal('0.00'))
        z.wieder_konto = eingaenge[0].haben_konto.nummer if eingaenge else '2030'
    return liste


def _absender_vergessen(zahlung, vertraege):
    """Löscht die gelernte Zuordnung «Absender → Vertrag», die aus einer
    Fehlzuordnung entstand. Gibt den Namen zurück oder ''."""
    from core.services import zahler as _zahler
    from finance.models import ZahlerZuordnung
    bew = zahlung.bankbewegungen.first()
    if bew is None:
        return ''
    name, _r, _g = _zahler.aus_bewegung(bew.gegenpartei, bew.text)
    schluessel = _zahler.normalisiere(name)
    if schluessel and ZahlerZuordnung.objects.filter(name_norm=schluessel[:160],
                                                     vertrag__in=list(vertraege)).delete()[0]:
        return name
    return ''


def guthaben_wiederherstellen(zahlung, *, user=None):
    """Stellt den Eingang einer Zahlung wieder her, die samt Zuordnung storniert
    wurde.

    Gebucht werden die ursprünglichen Eingangsbuchungen noch einmal, an einem
    neuen Zahlungseingang:

    - War es ein Guthaben (an 2030): wieder Guthaben des Mieters, «offen
      lassen». Verwaiste Reste derselben Verrechnung werden storniert, damit
      auch die Posten, die sie noch tilgten (z. B. eine Mahngebühr), wieder
      offen sind.
    - War es eine geparkte Bankzahlung (an 1190): wieder ein Klärungsfall ohne
      Mieter — sie war ja offenbar falsch zugeordnet. Der gelernte Absender
      wird vergessen, die Bankbewegung zeigt auf den neuen Eingang.
    """
    from finance.booking import buche
    from finance.models import Bankbewegung, Zahlungseingang
    if zahlung.status != 'storniert' or not zahlung.vertrag_id:
        raise ZuordnungsFehler(_("Nur eine stornierte Zahlung eines Mieters lässt sich wiederherstellen."))
    eingaenge = list(_eingangsbuchungen(zahlung).select_related('soll_konto', 'haben_konto'))
    if not eingaenge:
        raise ZuordnungsFehler(_("Diese Zahlung war kein Guthaben und keine geparkte Bankzahlung."))
    if Zahlungseingang.objects.filter(status='verbucht', bemerkung__contains=f"[W{zahlung.pk}]").exists():
        raise ZuordnungsFehler(_("Diese Zahlung ist bereits wiederhergestellt."))
    betrag = sum((b.betrag for b in eingaenge), Decimal('0.00'))
    ungeklaert = eingaenge[0].haben_konto.nummer == '1190'
    with transaction.atomic():
        if ungeklaert:
            neu = Zahlungseingang.objects.create(
                betrag=betrag, datum_eingang=zahlung.datum_eingang, buchungs_monat=zahlung.buchungs_monat,
                konto=_park_konto('1190'), liegenschaft=zahlung.liegenschaft, erstellt_von=user,
                status='verbucht',
                klaerung_notiz=(_("War irrtümlich %(mieter)s zugeordnet und wurde storniert.")
                                % {'mieter': zahlung.vertrag.mieter})[:255],
                bemerkung=f"Zahlung wiederhergestellt [W{zahlung.pk}] — {zahlung.bemerkung}"[:255])
        else:
            for rest in _verwaiste_reste(zahlung):
                stornieren(rest, user=user)
            neu = Zahlungseingang.objects.create(
                vertrag=zahlung.vertrag, betrag=betrag, datum_eingang=zahlung.datum_eingang,
                buchungs_monat=zahlung.buchungs_monat, konto=_park_konto('2030'),
                liegenschaft=zahlung.liegenschaft, guthaben_verwendung='offen', erstellt_von=user,
                status='verbucht',
                bemerkung=f"Guthaben wiederhergestellt [W{zahlung.pk}] — {zahlung.bemerkung}"[:255])
        for b in eingaenge:
            buche(b.soll_konto, b.haben_konto, b.betrag, f"Wiederherstellung {b.beleg_text}"[:255],
                  datum=b.datum, liegenschaft=b.liegenschaft, zahlung=neu, user=user)
        if ungeklaert:
            _absender_vergessen(zahlung, [zahlung.vertrag])
            Bankbewegung.objects.filter(zahlung=zahlung).update(zahlung=neu)
    from core.services.zahlungsverzug import pruefe_nach_zahlung
    pruefe_nach_zahlung(zahlung.vertrag)
    return neu


def verrechnete_guthaben(tage=120):
    """Verrechnungen von Guthaben (2030 an 1100) der letzten `tage` — für die
    Liste mit «Verrechnung rückgängig»."""
    from finance.models import Buchung, Zahlungseingang
    seit = timezone.localdate() - timedelta(days=tage)
    ids = (Buchung.objects.filter(soll_konto__nummer='2030', haben_konto__nummer='1100', ist_storno=False,
                                  storniert_am__isnull=True, datum__gte=seit, zahlungseingang__status='verbucht')
           .values_list('zahlungseingang_id', flat=True))
    return list(Zahlungseingang.objects.filter(pk__in=set(ids), vertrag__isnull=False)
                .select_related('vertrag__mieter', 'debitoren_rechnung').order_by('-id')[:50])


def zugeordnete_klaerungsfaelle(tage=120):
    """Geparkte Zahlungen (1190), die in den letzten `tage` einem Posten
    zugeordnet wurden — für die Liste mit «Zuordnung aufheben». Je Aufteilung
    eine Zeile (die ursprüngliche Zahlung), mit dem Bankbetrag als `total`."""
    from finance.models import Buchung, Zahlungseingang
    seit = timezone.localdate() - timedelta(days=tage)
    ids = set(Buchung.objects.filter(soll_konto__nummer='1190', haben_konto__nummer='1100', ist_storno=False,
                                     storniert_am__isnull=True, datum__gte=seit, zahlungseingang__status='verbucht')
              .values_list('zahlungseingang_id', flat=True))
    liste, gesehen = [], set()
    for z in (Zahlungseingang.objects.filter(pk__in=ids, vertrag__isnull=False)
              .select_related('vertrag__mieter', 'debitoren_rechnung').order_by('-id')):
        w = wurzel(z)
        if w.pk in gesehen or w.status != 'verbucht':
            continue
        gesehen.add(w.pk)
        if w.pk != z.pk:
            w = (Zahlungseingang.objects.select_related('vertrag__mieter', 'debitoren_rechnung').get(pk=w.pk))
        w.total = summe_mit_teilen(w)
        liste.append(w)
        if len(liste) >= 50:
            break
    return liste


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

    def dazu(v, grund, rechnungen, stark=False):
        # «stark»: Referenz, gelernter Absender oder Name belegen den Mieter.
        # Ein passender Betrag allein belegt nichts — 100.00 schuldet jeder
        # zweite Parkplatzmieter (Korrektur 26.10.2026).
        if v.id in vorschlag:
            if grund not in vorschlag[v.id]['gruende']:
                vorschlag[v.id]['gruende'].append(grund)
            vorschlag[v.id]['stark'] = vorschlag[v.id]['stark'] or stark
            return
        vorschlag[v.id] = {'vertrag': v, 'mieter': v.mieter.display_name if v.mieter_id else '—',
                           'gruende': [grund], 'rechnungen': rechnungen, 'stark': stark}

    if referenz:
        r = (DebitorenRechnung.objects.filter(qr_referenz=re.sub(r'\D', '', referenz), vertrag__isnull=False)
             .select_related('vertrag__mieter').first())
        if r is not None:
            dazu(r.vertrag, _("Referenz gehört zu «%(titel)s»") % {'titel': r.titel},
                 [p for p in posten if p.vertrag_id == r.vertrag_id], stark=True)
    if absender:
        v = _zahler.finde_vertrag(absender)
        if v is not None:
            dazu(v, _("Absender wurde schon diesem Mieter zugeordnet"),
                 [p for p in posten if p.vertrag_id == v.id], stark=True)
    text = f"{absender} {mitteilung}"
    namens_treffer = set()
    for p in posten:
        v = p.vertrag
        if v.mieter_id and v.mieter.nachname and _name_passt(v.mieter.nachname, text):
            namens_treffer.add(v.id)
            dazu(v, _("Name «%(name)s» steht im Absender oder in der Mitteilung") % {'name': v.mieter.nachname},
                 [x for x in posten if x.vertrag_id == v.id], stark=True)
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
    rang = sorted(vorschlag.values(), key=lambda x: (not x['stark'], -len(x['gruende'])))
    return rang[:3]


def tage_ungeklaert(zahlung, heute=None):
    heute = heute or timezone.localdate()
    return max(0, (heute - zahlung.datum_eingang).days)
