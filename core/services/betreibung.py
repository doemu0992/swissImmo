"""Betreibung (SchKG) — was eine Betreibung im übrigen System bewirkt.

Das Modell `finance.Betreibung` hält Stand und Daten. Dieser Dienst verzahnt sie
mit dem Rest, an je EINER Stelle:

MAHNLAUF. Eine Forderung in einer offenen Betreibung wird nicht mehr gemahnt —
die Zahlungsaufforderung kommt jetzt vom Betreibungsamt, und eine weitere Mahnung
mit Gebühr wäre eine zweite Forderung für denselben Verzug
(`rechnung_ids_in_offener_betreibung`, genutzt über `core.services.mahnsperre`).

ZAHLUNGEN. Ohne Tilgungserklärung des Zahlers wird eine Zahlung zuerst auf die
betriebene Schuld angerechnet, unter mehreren auf die zuerst betriebene, sonst auf
die früher verfallene (Art. 87 Abs. 1 OR) — `tilgungsrang`, genutzt von
`zahlungszuordnung.offene_rechnungen`. Sind alle Forderungen einer Betreibung
bezahlt, steht sie von selbst auf «Bezahlt» (`nach_rechnungsstatus`, aus dem
post_save-Signal der Debitorenrechnung).

PENDENZEN. Mit dem Zahlungsbefehl beginnt die Rechtsvorschlagsfrist (10 Tage,
Art. 74 SchKG); sobald fortgesetzt werden darf, erinnert eine Pendenz an das
Fortsetzungsbegehren (Art. 88 SchKG). Stabile `quelle` `betreibung:<pk>:…` — ein
zweites Speichern legt nichts doppelt an (`pendenzen_nachfuehren`).

BUCHHALTUNG. «Kosten dem Mieter belasten» stellt die Betreibungskosten
(Art. 68 SchKG) als abgeleitete Forderung (`stammrechnung` = Hauptforderung) in
Rechnung, gebucht wie eine Mahngebühr (1100 an 3600). Als abgeleitete Forderung
zählt sie nicht zum Rückstand nach Art. 257d OR. Beim Verlustschein werden die
offenen Beträge der Forderungen über den bestehenden Abschreibungsdienst auf 3805
ausgebucht (`verlustschein_abschreiben`).
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext

logger = logging.getLogger(__name__)

OFFENE_RECHNUNGSSTATUS = ('offen', 'teilbezahlt')
KOSTEN_TITEL = 'Betreibungskosten (Art. 68 SchKG)'


def _abgeschlossen():
    from finance.models import Betreibung
    return Betreibung.ABGESCHLOSSEN


def offene_betreibungen():
    from finance.models import Betreibung
    return Betreibung.objects.exclude(status__in=_abgeschlossen())


def rechnung_ids_in_offener_betreibung():
    """IDs aller Forderungen in einer offenen Betreibung — Hauptforderung und weitere.

    Eine Abfrage, im Kontext der Organisation (`objects`)."""
    from finance.models import DebitorenRechnung
    offen = offene_betreibungen()
    return set(DebitorenRechnung.objects
               .filter(Q(betreibungen__in=offen) | Q(betreibungen_weitere__in=offen))
               .values_list('pk', flat=True).distinct())


def ist_in_offener_betreibung(rechnung):
    """Steht diese Forderung in einer offenen Betreibung?"""
    from finance.models import Betreibung
    # `alle_organisationen`: gesucht wird über GENAU DIESE Rechnung, die einer
    # Verwaltung gehört — die Grenze steht im Ausdruck. So funktioniert die
    # Frage auch ohne Anfragekontext (Signal, Lauf).
    return (Betreibung.alle_organisationen
            .filter(Q(debitoren_rechnung_id=rechnung.pk) | Q(weitere_rechnungen=rechnung.pk))
            .exclude(status__in=_abgeschlossen()).exists())


def tilgungsrang(vertrag):
    """{rechnung_id: (begehren_am, betreibung_pk)} der Forderungen dieses Vertrags in
    offenen Betreibungen — für die Reihenfolge nach Art. 87 Abs. 1 OR. Zwei Abfragen."""
    offen = offene_betreibungen()
    rang = {}
    zeilen = list(offen.filter(debitoren_rechnung__vertrag=vertrag)
                  .values_list('debitoren_rechnung_id', 'begehren_am', 'pk'))
    zeilen += list(offen.filter(weitere_rechnungen__vertrag=vertrag)
                   .values_list('weitere_rechnungen__id', 'begehren_am', 'pk'))
    for rid, begehren, bpk in zeilen:
        schluessel = (begehren, bpk)
        if rid not in rang or schluessel < rang[rid]:
            rang[rid] = schluessel
    return rang


# ---------------------------------------------------------------- Anlegen

def betreibbare_forderungen(vertrag, stichtag=None):
    """Offene, fällige Hauptforderungen des Vertrags, älteste zuerst — die Auswahl im
    Assistenten. Mahngebühren und Zinsen (`stammrechnung`) stehen nicht zur Wahl:
    Sie werden mit der Hauptforderung eingefordert."""
    from finance.models import DebitorenRechnung
    if vertrag is None:
        return []
    stichtag = stichtag or timezone.localdate()
    return [r for r in (DebitorenRechnung.objects
                        .filter(vertrag=vertrag, status__in=OFFENE_RECHNUNGSSTATUS,
                                stammrechnung__isnull=True)
                        .prefetch_related('zahlungseingaenge')
                        .order_by('faellig_am', 'datum', 'id'))
            if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) <= stichtag
            and r.offener_betrag > 0]


def forderungsgrund_vorschlag(rechnungen, vertrag=None):
    """«Mietzins Wohnung …, Strasse: Miete 08/2026 (fällig 01.08.2026) CHF …; …»."""
    objekt = ''
    if vertrag is not None and vertrag.einheit_id:
        e = vertrag.einheit
        objekt = f"{e.bezeichnung}, {e.liegenschaft.strasse}, {e.liegenschaft.plz} {e.liegenschaft.ort}"
    teile = []
    for r in rechnungen:
        f = r.faellig_am or r.datum
        teile.append(f"{r.titel}" + (f" (fällig {f:%d.%m.%Y})" if f else '')
                     + f" CHF {r.offener_betrag:.2f}")
    kopf = f"Mietzins {objekt}" if objekt else "Mietzins"
    return f"{kopf}: " + '; '.join(teile) if teile else kopf


def zins_ab_vorschlag(rechnungen):
    """Zinsbeginn für EINE Forderung: der Tag nach der Fälligkeit (der Fälligkeitstag
    ist Tag 0, wie im Mahnwesen). Bei mehreren Forderungen keiner — einen einzigen
    Zinsbeginn für verschieden fällige Mieten zu setzen, wäre eine Annahme
    (z. B. mittlerer Verfall), die die Verwaltung selbst trifft."""
    if len(rechnungen) != 1:
        return None
    f = rechnungen[0].faellig_am or rechnungen[0].datum
    return f + timedelta(days=1) if f else None


def glaeubiger(b):
    """(Gläubiger, Vertreter) als Zeilenlisten: Eigentümer der Liegenschaft, vertreten
    durch die Verwaltung. Ohne erfassten Eigentümer ist die Verwaltung Gläubigerin —
    das steht dann so auf dem Blatt, statt still einen Namen zu erfinden."""
    vertrag = b.vertrag or b.debitoren_rechnung.vertrag
    lg = None
    if vertrag is not None and vertrag.einheit_id:
        lg = vertrag.einheit.liegenschaft
    lg = lg or b.debitoren_rechnung.liegenschaft
    org = b.organisation
    vertreter = [org.firma or '', org.strasse or '', f"{org.plz or ''} {org.ort or ''}".strip()]
    eig = getattr(lg, 'eigentuemer', None) if lg is not None else None
    if eig is None:
        return vertreter, None
    gl = [eig.firma_oder_name or '', eig.strasse or '', f"{eig.plz or ''} {eig.ort or ''}".strip()]
    return gl, vertreter


# ---------------------------------------------------------------- Pendenzen

def _pendenz_setzen(b, quelle, *, titel, faellig, beschreibung, erledigt):
    """Legt die Pendenz an oder führt sie nach — nie doppelt (stabile `quelle`)."""
    from core.models import Pendenz
    heute = timezone.localdate()
    p = Pendenz.objects.filter(quelle=quelle).first()
    if p is None:
        if erledigt:
            return None
        vertrag = b.vertrag
        lg = vertrag.einheit.liegenschaft if vertrag is not None and vertrag.einheit_id else None
        return Pendenz.objects.create(
            titel=titel[:200], beschreibung=beschreibung, kategorie='frist', faellig_am=faellig,
            vertrag=vertrag, liegenschaft=lg or b.debitoren_rechnung.liegenschaft, quelle=quelle)
    felder = []
    if erledigt and not p.erledigt:
        p.erledigt, p.erledigt_am = True, heute
        felder += ['erledigt', 'erledigt_am']
    elif not p.erledigt:
        # Ein korrigiertes Datum (Zahlungsbefehl, Rechtsöffnung) verschiebt die Frist.
        for feld, wert in (('faellig_am', faellig), ('beschreibung', beschreibung), ('titel', titel[:200])):
            if getattr(p, feld) != wert:
                setattr(p, feld, wert)
                felder.append(feld)
    if felder:
        p.save(update_fields=felder)
    return p


def pendenzen_nachfuehren(b):
    """Rechtsvorschlagsfrist und Fortsetzungsbegehren als Pendenzen — idempotent."""
    name = (b.vertrag.mieter.display_name if b.vertrag_id and b.vertrag.mieter_id
            else b.debitoren_rechnung.titel)
    nr = b.betreibungsnummer or f'#{b.pk}'
    if b.zahlungsbefehl_am:
        _pendenz_setzen(
            b, f'betreibung:{b.pk}:rechtsvorschlag',
            titel=f'Rechtsvorschlag-Frist prüfen – {name}',
            faellig=b.rechtsvorschlag_frist_bis,
            beschreibung=(f'Betreibung {nr}: Zahlungsbefehl zugestellt am {b.zahlungsbefehl_am:%d.%m.%Y}. '
                          f'Der Rechtsvorschlag ist innert 10 Tagen zu erheben (Art. 74 SchKG), also bis '
                          f'{b.rechtsvorschlag_frist_bis:%d.%m.%Y}. Beim Betreibungsamt nachfragen und '
                          f'einen Rechtsvorschlag in der Betreibung erfassen.'),
            erledigt=bool(b.rechtsvorschlag_am) or not b.ist_offen
            or b.status not in ('begehren', 'zahlungsbefehl'))
    frist = b.fortsetzung_frist
    if frist and frist[0]:
        frueh, spaet = frist
        bis = (f'spätestens {spaet:%d.%m.%Y}' if spaet
               else 'Ende offen, solange das Rechtsöffnungsverfahren läuft')
        _pendenz_setzen(
            b, f'betreibung:{b.pk}:fortsetzung',
            titel=f'Fortsetzungsbegehren stellen – {name}',
            faellig=frueh,
            beschreibung=(f'Betreibung {nr}: Das Fortsetzungsbegehren ist frühestens am {frueh:%d.%m.%Y} '
                          f'möglich, {bis} (Art. 88 SchKG). Danach erlischt das Recht, die Betreibung '
                          f'fortzusetzen.'),
            erledigt=bool(b.fortsetzung_am) or not b.ist_offen
            or b.status in ('fortsetzung', 'pfaendung'))
    elif not b.ist_offen:
        _pendenz_setzen(b, f'betreibung:{b.pk}:fortsetzung', titel='', faellig=None,
                        beschreibung='', erledigt=True)


# ---------------------------------------------------------------- Zahlungen

def nach_rechnungsstatus(rechnung):
    """Aus dem post_save-Signal: Ist eine Forderung bezahlt, wird jede offene
    Betreibung, deren Forderungen nun ALLE bezahlt sind, auf «Bezahlt» gesetzt.

    Billig, wenn die Rechnung in keiner Betreibung steht: eine Abfrage, und nur für
    Rechnungen im Status «bezahlt». Eine stornierte Forderung hält die Betreibung
    nicht offen — sie ist keine Forderung mehr."""
    if rechnung.status != 'bezahlt' or not rechnung.pk:
        return 0
    from core.tenancy import organisation_kontext
    from finance.models import Betreibung
    # `alle_organisationen`: über GENAU DIESE Rechnung gesucht (siehe
    # `ist_in_offener_betreibung`); der Rest läuft im Kontext ihrer Organisation.
    kandidaten = list(Betreibung.alle_organisationen
                      .filter(Q(debitoren_rechnung_id=rechnung.pk) | Q(weitere_rechnungen=rechnung.pk))
                      .exclude(status__in=_abgeschlossen()).distinct()
                      .select_related('debitoren_rechnung', 'vertrag__mieter', 'organisation'))
    n = 0
    for b in kandidaten:
        with organisation_kontext(b.organisation):
            stati = {r.status for r in b.rechnungen()}
            if 'bezahlt' in stati and stati <= {'bezahlt', 'storniert'}:
                b.status = 'bezahlt'
                b.save(update_fields=['status'])
                pendenzen_nachfuehren(b)
                n += 1
                logger.info('Betreibung %s: alle Forderungen bezahlt — Stand «Bezahlt»', b.pk)
    return n


# ---------------------------------------------------------------- Buchhaltung

class BetreibungsFehler(ValueError):
    """Fachlicher Grund, warum die Aktion an dieser Betreibung nicht geht."""


def kosten_belasten(b, user=None):
    """Belastet die Betreibungskosten (Art. 68 SchKG) dem Mieter.

    Wie eine Mahngebühr (`automation._mahnschritt_buchen`): eine abgeleitete
    Debitorenrechnung mit `stammrechnung` = Hauptforderung, fällig in 30 Tagen,
    gebucht 1100 an 3600. Einmalig je Betreibung (`kosten_rechnung`); ist die
    Kostenrechnung storniert, darf neu belastet werden. Gibt die Rechnung zurück."""
    from finance.booking import buche
    from finance.models import Betreibung, DebitorenRechnung

    heute = timezone.localdate()
    with transaction.atomic():
        # Zeilensperre: ein Doppelklick belastete sonst dieselben Kosten zweimal.
        b = (Betreibung.objects.select_for_update(of=('self',))
             .select_related('debitoren_rechnung', 'vertrag__mieter', 'vertrag__einheit__liegenschaft',
                             'kosten_rechnung')
             .get(pk=b.pk))
        if not b.kosten or b.kosten <= 0:
            raise BetreibungsFehler(gettext('Zuerst die Betreibungskosten erfassen (Feld «Betreibungskosten»).'))
        if b.kosten_rechnung_id and b.kosten_rechnung.status != 'storniert':
            raise BetreibungsFehler(gettext('Die Betreibungskosten sind dem Mieter bereits belastet.'))
        haupt = b.debitoren_rechnung
        vertrag = b.vertrag or haupt.vertrag
        if vertrag is None:
            raise BetreibungsFehler(gettext('Ohne Mietvertrag lassen sich keine Kosten belasten.'))
        lg = haupt.liegenschaft or (vertrag.einheit.liegenschaft if vertrag.einheit_id else None)
        nr = b.betreibungsnummer or f'#{b.pk}'
        k = DebitorenRechnung.objects.create(
            vertrag=vertrag, liegenschaft=lg, titel=KOSTEN_TITEL,
            beschreibung=f"Zu: Betreibung {nr} ({haupt.titel})",
            datum=heute, faellig_am=heute + timedelta(days=30),
            betrag=b.kosten, status='offen', stammrechnung=haupt, forderungsart='sonstige')
        buche("1100", "3600", b.kosten, f"{KOSTEN_TITEL} {vertrag.mieter}",
              datum=heute, liegenschaft=lg, debitor=k, user=user)
        b.kosten_rechnung = k
        b.save(update_fields=['kosten_rechnung'])
    return k


def verlustschein_abschreiben(b, user=None):
    """Schreibt die offenen Beträge der Forderungen dieser Betreibung auf 3805 ab —
    über `core.services.debitorenverlust`, dieselbe Buchung wie «Abschreiben» im
    OP-Buch. Die belasteten Betreibungskosten gehören dazu: Der Verlustschein
    umfasst auch sie. Gebucht wird heute, wie beim Abschreiben von Hand — ein
    zurückdatierter Verlustschein träfe sonst eine abgeschlossene Periode.

    Gibt (Anzahl, Summe, ausgelassen) zurück; eine Forderung in einer gesperrten
    Periode wird ausgelassen und protokolliert, die übrigen gelten."""
    from core.services.debitorenverlust import AbschreibungNichtMoeglich, forderung_abschreiben
    from finance.models import DebitorenRechnung

    grund = f"Verlustschein Betreibung {b.betreibungsnummer or '#' + str(b.pk)}"
    if b.verlustschein_am:
        grund += f" vom {b.verlustschein_am:%d.%m.%Y}"
    ids = [r.pk for r in b.rechnungen()]
    if b.kosten_rechnung_id:
        ids.append(b.kosten_rechnung_id)
    n, summe, ausgelassen = 0, Decimal('0.00'), 0
    for pk in ids:
        try:
            with transaction.atomic():
                r = (DebitorenRechnung.objects.select_for_update(of=('self',))
                     .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft')
                     .get(pk=pk))
                if r.status not in OFFENE_RECHNUNGSSTATUS:
                    continue
                summe += forderung_abschreiben(r, grund, user=user)
                n += 1
        except AbschreibungNichtMoeglich:
            continue
        except PermissionError:
            ausgelassen += 1
            logger.warning('Verlustschein Betreibung %s: Rechnung %s nicht abgeschrieben (Periode gesperrt)',
                           b.pk, pk)
    return n, summe, ausgelassen


def nach_speichern(b, alter_status=None, user=None):
    """Nach jedem Speichern aus der Oberfläche: Pendenzen nachführen, beim Wechsel
    auf «Verlustschein» die Forderungen abschreiben. Gibt (Anzahl, Summe,
    ausgelassen) der Abschreibung zurück oder None."""
    pendenzen_nachfuehren(b)
    if b.status == 'verlustschein' and alter_status != 'verlustschein':
        return verlustschein_abschreiben(b, user=user)
    return None
