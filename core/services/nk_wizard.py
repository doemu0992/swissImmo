"""Nebenkosten-Wizard (Modul 1, 27.10.2026): Daten und Prüfungen der sechs Schritte.

Hier steht, was die Seiten des Wizards lesen und schreiben — Periode, Objekte, Schlüssel je
Kostenart, Zählerstände, CSV-Import. GERECHNET wird hier nichts: Die Abrechnung bleibt in
`core.utils.billing.berechne_abrechnung`; der Wizard liest ihre Ausgabe.

Alle Abfragen laufen über die Default-Manager (Mandantenfilter) und zusätzlich über die
Liegenschaft der Periode: Eine Einheit, ein Vertrag oder ein Zähler, der nicht zu DIESER
Liegenschaft gehört, wird nicht gefunden (404 in der View).
"""
import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

#: Höchstdauer einer Abrechnungsperiode. Länger rechnet die Engine zwar, aber Heizgradtage,
#: Akonto und Einsprache beziehen sich auf eine Jahresabrechnung.
MAX_MONATE = 12


def monate_plus(tag, monate):
    """`tag` plus `monate` Kalendermonate; am Monatsende auf den letzten Tag geklemmt."""
    import calendar
    m = tag.month - 1 + monate
    j, m = tag.year + m // 12, m % 12 + 1
    return date(j, m, min(tag.day, calendar.monthrange(j, m)[1]))


def _datum(roh):
    try:
        return date.fromisoformat((roh or '').strip())
    except ValueError:
        return None


def periode_pruefen(start_roh, ende_roh):
    """(start, ende, {feld: fehler}). Höchstens 12 Monate: Ende spätestens am Vortag desselben
    Datums ein Jahr später (01.07.2025 → 30.06.2026)."""
    start, ende, fehler = _datum(start_roh), _datum(ende_roh), {}
    if start is None:
        fehler['start_datum'] = _('Bitte ein gültiges Datum angeben.')
    if ende is None:
        fehler['ende_datum'] = _('Bitte ein gültiges Datum angeben.')
    if start and ende:
        if ende < start:
            fehler['ende_datum'] = _('Das Ende liegt vor dem Beginn.')
        elif ende > monate_plus(start, MAX_MONATE) - timedelta(days=1):
            fehler['ende_datum'] = _('Eine Abrechnungsperiode umfasst höchstens %(n)s Monate '
                                     '(spätestens bis %(d)s).') % {
                'n': MAX_MONATE, 'd': (monate_plus(start, MAX_MONATE) - timedelta(days=1)).strftime('%d.%m.%Y')}
    return start, ende, fehler


def periode_zu_lang(p):
    return p.ende_datum > monate_plus(p.start_datum, MAX_MONATE) - timedelta(days=1)


# --------------------------------------------------------------------------- Schritt 1

def vertraege_der_periode(einheit, p):
    """Die Verträge, die die Engine für diese Einheit abrechnet (dieselbe Auswahl)."""
    return list(einheit.vertraege.exclude(status='entwurf').filter(beginn__lte=p.ende_datum)
                .filter(Q(ende__isnull=True) | Q(ende__gte=p.start_datum))
                .select_related('mieter').order_by('beginn', 'id'))


def einheiten_kacheln(p, result):
    """Je Einheit: Masse, Verträge der Periode und was fehlt."""
    braucht_m3 = Decimal(str(result.get('heizkosten') or 0)) > 0 or any(
        'm3' in k.get('arten', []) for k in result.get('kostenarten', []))
    braucht_personen = Decimal(str(result.get('personen_kosten') or 0)) > 0
    hat_m3 = any((e.volumen_m3 or 0) > 0 for e in p.liegenschaft.einheiten.all())
    kacheln = []
    for e in p.liegenschaft.einheiten.order_by('bezeichnung'):
        vertraege = vertraege_der_periode(e, p)
        fehlt = []
        if not (e.flaeche_m2 or 0) > 0:
            fehlt.append(_('Fläche'))
        if not (e.volumen_m3 or 0) > 0 and (braucht_m3 or hat_m3) and (e.flaeche_m2 or 0) > 0:
            fehlt.append(_('Volumen'))
        if braucht_personen and any(not (v.anzahl_personen or 0) > 0 for v in vertraege):
            fehlt.append(_('Personen'))
        kacheln.append({'e': e, 'vertraege': vertraege, 'fehlt': fehlt})
    return kacheln


def objekt_luecken(kacheln):
    return [k for k in kacheln if k['fehlt']]


def _dezimal(roh, *, stellen=2, minimum=Decimal('0')):
    """Decimal aus einer Eingabe ('1'234.50', '12,5'); None bei leer; ValueError sonst."""
    text = (roh or '').strip().replace("'", '').replace('’', '').replace(' ', '')
    if text == '':
        return None
    if ',' in text and '.' in text:
        text = text.replace('.', '').replace(',', '.') if text.rfind(',') > text.rfind('.') else text.replace(',', '')
    else:
        text = text.replace(',', '.')
    try:
        wert = Decimal(text)
    except InvalidOperation:
        raise ValueError(_('Bitte eine Zahl angeben.'))
    if not wert.is_finite() or wert < minimum:
        raise ValueError(_('Der Wert darf nicht negativ sein.'))
    return wert.quantize(Decimal(1).scaleb(-stellen))


def einheit_speichern(einheit, vertraege, post):
    """POST einer Kachel: Fläche, Volumen, Personen je Vertrag. Gibt {feld: fehler} zurück."""
    fehler, werte = {}, {}
    for feld in ('flaeche_m2', 'volumen_m3'):
        try:
            werte[feld] = _dezimal(post.get(feld))
        except ValueError as exc:
            fehler[feld] = str(exc)
            continue
        if werte[feld] is not None and werte[feld] >= Decimal('100000'):
            fehler[feld] = _('Der Wert ist zu gross.')
    personen = {}
    for v in vertraege:
        roh = (post.get(f'personen_{v.id}') or '').strip()
        if roh == '':
            continue
        try:
            n = int(roh)
        except ValueError:
            n = 0
        if n < 1 or n > 99:
            fehler[f'personen_{v.id}'] = _('Zwischen 1 und 99 Personen.')
        else:
            personen[v] = n
    if fehler:
        return fehler
    with transaction.atomic():
        for feld, wert in werte.items():
            setattr(einheit, feld, wert)
        einheit.save(update_fields=list(werte))
        for v, n in personen.items():
            if v.anzahl_personen != n:
                v.anzahl_personen = n
                v.save(update_fields=['anzahl_personen'])
    return {}


# --------------------------------------------------------------------------- Schritt 2

def nicht_einbezogene_kreditoren(p):
    """HNK-Kreditoren der Liegenschaft in der Periode, die die Engine (noch) nicht liest:
    nicht freigegeben, in Zahlung oder teilbezahlt. Angezeigt, damit nichts still fehlt."""
    from finance.models import KreditorenRechnung
    return list(KreditorenRechnung.objects.filter(
        liegenschaft=p.liegenschaft, is_hnk_relevant=True,
        status__in=['neu', 'in_zahlung', 'teilbezahlt'],
    ).filter(
        Q(leistungs_von__lte=p.ende_datum) & Q(leistungs_bis__gte=p.start_datum) |
        Q(leistungs_von__isnull=True, datum__range=[p.start_datum, p.ende_datum])
    ).order_by('datum', 'id'))


def kreditoren_liste(p):
    """Die Kreditoren der Abrechnung mit ihren HNK-Teilen und dem Anteil an der Periode —
    über dieselben Funktionen wie die Engine (Fehler c)."""
    from core.utils.billing import _hnk_teile, hnk_kreditoren, leistungs_anteil
    zeilen = []
    for k in hnk_kreditoren(p.liegenschaft, p.start_datum, p.ende_datum):
        faktor, tage_in, tage_l = leistungs_anteil(k, p.start_datum, p.ende_datum)
        teile = [{'betrag': b, 'konto': konto, 'text': t} for b, konto, t in _hnk_teile(k)]
        zeilen.append({'k': k, 'teile': teile, 'anteilig': faktor != 1, 'tage_in': tage_in, 'tage_l': tage_l,
                       'oel': bool(k.menge_liter and k.menge_liter > 0),
                       'summe': sum((t['betrag'] for t in teile), Decimal('0.00'))})
    return zeilen


def beleg_pruefen(post, p):
    """Neuer manueller Beleg: (Werte, {feld: fehler})."""
    from finance.models import NebenkostenBeleg
    fehler, werte = {}, {}
    werte['text'] = (post.get('text') or '').strip()[:255]
    if not werte['text']:
        fehler['text'] = _('Bitte eine Beschreibung angeben.')
    werte['kategorie'] = post.get('kategorie') or ''
    if werte['kategorie'] not in dict(NebenkostenBeleg.NK_KATEGORIE_CHOICES):
        fehler['kategorie'] = _('Bitte eine Kategorie wählen.')
    werte['verteilschluessel'] = post.get('verteilschluessel') or 'm2'
    if werte['verteilschluessel'] not in dict(NebenkostenBeleg.VERTEIL_CHOICES):
        fehler['verteilschluessel'] = _('Bitte einen Verteilschlüssel wählen.')
    werte['datum'] = _datum(post.get('datum'))
    if werte['datum'] is None:
        fehler['datum'] = _('Bitte ein gültiges Datum angeben.')
    try:
        werte['betrag'] = _dezimal(post.get('betrag'))
    except ValueError as exc:
        fehler['betrag'] = str(exc)
    else:
        if werte['betrag'] is None or werte['betrag'] <= 0:
            fehler['betrag'] = _('Bitte einen Betrag über 0 angeben.')
        elif werte['betrag'] >= Decimal('100000000'):
            fehler['betrag'] = _('Der Betrag ist zu gross.')
    return werte, fehler


def oel_pruefen(post):
    fehler, werte = {}, {}
    for feld in ('anfangsbestand_liter', 'anfangsbestand_chf', 'endbestand_liter'):
        try:
            wert = _dezimal(post.get(feld))
        except ValueError as exc:
            fehler[feld] = str(exc)
            continue
        if wert is not None and wert >= Decimal('100000000'):
            fehler[feld] = _('Der Wert ist zu gross.')
            continue
        werte[feld] = wert if wert is not None else Decimal('0.00')
    return werte, fehler


# --------------------------------------------------------------------------- Schritt 3

#: Die Wahl im Segment-Umschalter einer Kostenart. Zimmer und Wertquote bleiben wählbar,
#: wenn sie schon gesetzt sind (Verteilschlüssel-Seite), stehen aber nicht im Umschalter.
SEGMENT = (('m2', gettext_lazy('m²')), ('m3', gettext_lazy('m³')), ('einheit', gettext_lazy('Einheit')),
           ('personen', gettext_lazy('Personen')), ('prozent', gettext_lazy('Eigene %')))
SEGMENT_WERTE = {k for k, _l in SEGMENT} | {'zimmer', 'anteil'}


def schluessel_der_periode(lg, kostenart, ende_p):
    """Der Schlüssel dieser Kostenart, der am Periodenende gilt (jede Art), oder None."""
    gueltig = [s for s in lg.standard_schluessel.filter(kostenart=kostenart, gueltig_ab__lte=ende_p)
               .order_by('gueltig_ab', 'id') if not s.gueltig_bis or s.gueltig_bis >= ende_p]
    return gueltig[-1] if gueltig else None


@transaction.atomic
def schluessel_setzen(lg, kostenart, typ, p):
    """Setzt den Schlüssel einer Kostenart für diese Periode. Gibt (Schlüssel, geändert) zurück.

    Bestehende Daten bleiben gültig: Ein Schlüssel, der VOR der Periode begann, wird am Vortag
    des Periodenbeginns beendet (frühere Perioden rechnen weiter mit ihm). Einer, der in dieser
    Periode begann, wird geändert. Prozentzeilen ziehen mit (wie `fw_verteilschluessel`).
    """
    from portfolio.models import LiegenschaftVerteilschluessel, Verteilschluessel
    s = schluessel_der_periode(lg, kostenart, p.ende_datum)
    if s is not None and s.typ == typ:
        return s, False
    if s is not None and s.gueltig_ab >= p.start_datum:
        if s.typ == 'prozent':
            Verteilschluessel.objects.filter(einheit__liegenschaft=lg, kostenart=kostenart, typ='prozent',
                                             gueltig_ab=s.gueltig_ab).delete()
        s.typ = typ
        s.save(update_fields=['typ'])
        return s, True
    if s is not None:
        vortag = p.start_datum - timedelta(days=1)
        Verteilschluessel.objects.filter(einheit__liegenschaft=lg, kostenart=kostenart, typ='prozent',
                                         gueltig_ab=s.gueltig_ab).update(gueltig_bis=vortag)
        s.gueltig_bis = vortag
        s.save(update_fields=['gueltig_bis'])
    neu = LiegenschaftVerteilschluessel.objects.create(liegenschaft=lg, kostenart=kostenart, typ=typ,
                                                       gueltig_ab=p.start_datum)
    return neu, True


def prozente_speichern(lg, s, werte):
    from portfolio.models import Verteilschluessel
    for e in lg.einheiten.all():
        Verteilschluessel.objects.update_or_create(
            einheit=e, kostenart=s.kostenart, typ='prozent', gueltig_ab=s.gueltig_ab,
            defaults={'wert': werte.get(e.id, Decimal('0')), 'gueltig_bis': s.gueltig_bis})


def vertraege_liegenschaft(p):
    from rentals.models import Mietvertrag
    return list(Mietvertrag.objects.filter(einheit__liegenschaft=p.liegenschaft).exclude(status='entwurf')
                .filter(beginn__lte=p.ende_datum).filter(Q(ende__isnull=True) | Q(ende__gte=p.start_datum))
                .select_related('mieter', 'einheit').order_by('einheit__bezeichnung', 'beginn'))


# --------------------------------------------------------------------------- Schritt 4

def heizzaehler(lg):
    from core.utils.billing import _ist_heizzaehler
    from portfolio.models import Zaehler
    return [z for z in Zaehler.objects.filter(einheit__liegenschaft=lg).select_related('einheit')
            .order_by('einheit__bezeichnung', 'zaehler_nummer') if _ist_heizzaehler(z)]


def wechsel_grenzen(einheit, p):
    """Erste Tage neuer Abschnitte (Mieterwechsel, Beginn/Ende eines Leerstands) in der Periode."""
    grenzen = set()
    for v in vertraege_der_periode(einheit, p):
        if v.beginn > p.start_datum:
            grenzen.add(v.beginn)
        if v.ende and v.ende < p.ende_datum:
            grenzen.add(v.ende + timedelta(days=1))
    return sorted(grenzen)


def staende_raster(p, eingabe=None):
    """Je Heizzähler die Felder Anfang, Wechsel (je Grenze) und Ende mit dem vorhandenen Stand.

    Gelesen wird derselbe Zeitraum wie in der Abrechnung (`_heiz_staende`: Periode inklusive
    Rändern); ein Stand am Vortag des Periodenbeginns zählt dort nicht und steht hier nicht.
    `eingabe`: {zaehler_id: POST-Daten} — nach einem Fehler bleibt die Eingabe stehen.
    """
    from portfolio.models import ZaehlerStand
    raster = []
    for z in heizzaehler(p.liegenschaft):
        staende = list(ZaehlerStand.objects.filter(zaehler=z, datum__gte=p.start_datum,
                                                   datum__lte=p.ende_datum).order_by('datum', 'id'))

        def am(*tage):
            treffer = [s for s in staende if s.datum in tage]
            return treffer[-1] if treffer else None
        anfang = am(p.start_datum) or (staende[0] if staende and staende[0].art == 'anfang' else None)
        ende = am(p.ende_datum) or (staende[-1] if staende and staende[-1].art == 'ende' else None)
        slots = [{'name': 'anfang', 'art': 'anfang', 'datum': anfang.datum if anfang else p.start_datum,
                  'stand': anfang, 'label': _('Anfang')}]
        for i, grenze in enumerate(wechsel_grenzen(z.einheit, p)):
            st = am(grenze - timedelta(days=1), grenze)
            slots.append({'name': f'wechsel_{i}', 'art': 'zwischen', 'stand': st,
                          'datum': st.datum if st else grenze - timedelta(days=1),
                          'label': _('Wechsel %(d)s') % {'d': (grenze - timedelta(days=1)).strftime('%d.%m.')}})
        slots.append({'name': 'ende', 'art': 'ende', 'datum': ende.datum if ende else p.ende_datum,
                      'stand': ende, 'label': _('Ende')})
        ein = (eingabe or {}).get(z.id)
        for slot in slots:
            if ein is not None:
                slot['datum_text'] = ein.get(f"{slot['name']}_datum", '')
                slot['wert_text'] = ein.get(f"{slot['name']}_wert", '')
            else:
                slot['datum_text'] = slot['datum'].isoformat()
                slot['wert_text'] = '' if slot['stand'] is None else format(slot['stand'].wert.normalize(), 'f')
        raster.append({'z': z, 'slots': slots})
    return raster


def staende_aus_post(post, eintrag):
    """[(art, datum, wert)] und {Feldname: Fehler} aus dem Formular eines Zählers."""
    eingaben, fehler = [], {}
    for slot in eintrag['slots']:
        roh = (post.get(f"{slot['name']}_wert") or '').strip()
        if roh == '':
            continue
        try:
            wert = _dezimal(roh, stellen=3)
        except ValueError as exc:
            fehler[slot['name']] = str(exc)
            continue
        d = _datum(post.get(f"{slot['name']}_datum"))
        if d is None:
            fehler[slot['name']] = _('Bitte ein gültiges Datum angeben.')
            continue
        eingaben.append((slot['art'], d, wert))
    return eingaben, fehler


def _folge_pruefen(staende):
    """Fehlertext, wenn ein Stand unter einem früheren liegt — sonst ''. `staende`: [(datum, wert)]."""
    letzter = None
    for d, w in sorted(staende):
        if letzter is not None and w < letzter[1]:
            return _('Der Stand vom %(d)s (%(w)s) liegt unter dem Stand vom %(d0)s (%(w0)s).') % {
                'd': d.strftime('%d.%m.%Y'), 'w': w, 'd0': letzter[0].strftime('%d.%m.%Y'), 'w0': letzter[1]}
        letzter = (d, w)
    return ''


@transaction.atomic
def staende_speichern(z, eingaben, *, herkunft='manuell'):
    """Schreibt Stände eines Zählers: [(art, datum, wert)]. Am selben Tag wird überschrieben.

    Gibt einen Fehlertext zurück (dann ist nichts gespeichert) oder ''.
    """
    from portfolio.models import ZaehlerStand
    heute = timezone.localdate()
    for _art, d, _w in eingaben:
        if d > heute:
            return _('Das Ablesedatum %(d)s liegt in der Zukunft.') % {'d': d.strftime('%d.%m.%Y')}
    bestand = {s.datum: s for s in ZaehlerStand.objects.filter(zaehler=z)}
    neu = {d: w for _a, d, w in eingaben}
    fehler = _folge_pruefen([(d, neu.get(d, s.wert)) for d, s in bestand.items()]
                            + [(d, w) for d, w in neu.items() if d not in bestand])
    if fehler:
        return fehler
    for art, d, w in eingaben:
        s = bestand.get(d)
        if s is None:
            ZaehlerStand.objects.create(zaehler=z, datum=d, wert=w, art=art, herkunft=herkunft)
        elif s.wert != w or s.art != art:
            s.wert, s.art = w, art
            s.save(update_fields=['wert', 'art'])
    letzter = z.staende.order_by('-datum', '-id').first()
    if letzter and z.aktueller_stand != letzter.wert:
        z.aktueller_stand = letzter.wert
        z.save(update_fields=['aktueller_stand'])
    return ''


# --------------------------------------------------------------------------- CSV-Import (E5)

#: Felder des Imports: (Schlüssel, Bezeichnung, Pflicht). Feste Herstellerformate gibt es
#: bewusst nicht (Entscheid E5): Die Spalten ordnet der Mensch zu, die Zuordnung bleibt.
IMPORT_FELDER = (
    ('zaehler', gettext_lazy('Zählernummer'), True),
    ('datum', gettext_lazy('Ablesedatum'), True),
    ('stand', gettext_lazy('Stand'), True),
    ('art', gettext_lazy('Art (Anfang/Zwischen/Ende)'), False),
)
IMPORT_MAX_BYTES = 512 * 1024
IMPORT_MAX_ZEILEN = 5000
_RATEN = {'zaehler': ('zähler', 'zaehler', 'nummer', 'meter', 'gerät', 'geraet'),
          'datum': ('datum', 'date', 'ablese'), 'stand': ('stand', 'wert', 'value', 'zählerstand'),
          'art': ('art', 'typ', 'type')}
_ARTEN = {'anfang': 'anfang', 'anfangsstand': 'anfang', 'start': 'anfang', 'a': 'anfang',
          'zwischen': 'zwischen', 'zwischenstand': 'zwischen', 'wechsel': 'zwischen', 'z': 'zwischen',
          'ende': 'ende', 'endstand': 'ende', 'end': 'ende', 'e': 'ende', '': ''}


class ImportFehler(ValueError):
    pass


def csv_lesen(roh):
    """(Spalten, Zeilen) aus einer CSV-Datei. Trennzeichen ; , oder Tab, Kopfzeile Pflicht."""
    if len(roh) > IMPORT_MAX_BYTES:
        raise ImportFehler(_('Die Datei ist grösser als %(n)s KB.') % {'n': IMPORT_MAX_BYTES // 1024})
    for kodierung in ('utf-8-sig', 'cp1252'):
        try:
            text = roh.decode(kodierung)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ImportFehler(_('Die Datei ist keine lesbare Textdatei.'))
    try:
        dialekt = csv.Sniffer().sniff(text[:4096], delimiters=';,\t')
        trenner = dialekt.delimiter
    except csv.Error:
        trenner = ';'
    zeilen = [z for z in csv.reader(io.StringIO(text), delimiter=trenner) if any((x or '').strip() for x in z)]
    if len(zeilen) < 2:
        raise ImportFehler(_('Die Datei braucht eine Kopfzeile und mindestens eine Datenzeile.'))
    if len(zeilen) - 1 > IMPORT_MAX_ZEILEN:
        raise ImportFehler(_('Höchstens %(n)s Zeilen je Import.') % {'n': IMPORT_MAX_ZEILEN})
    spalten = []
    for i, name in enumerate(zeilen[0]):
        name = (name or '').strip() or _('Spalte %(n)s') % {'n': i + 1}
        while name in spalten:
            name = f'{name} ({i + 1})'
        spalten.append(name)
    daten = [dict(zip(spalten, [(x or '').strip() for x in z] + [''] * (len(spalten) - len(z))))
             for z in zeilen[1:]]
    return spalten, daten


def zuordnung_vorschlag(spalten, gespeichert):
    """Die gespeicherte Zuordnung, soweit die Spalten passen — sonst nach dem Spaltennamen geraten
    (nur als Vorbelegung; übernommen wird erst, was der Mensch bestätigt)."""
    gespeichert = gespeichert if isinstance(gespeichert, dict) else {}
    zuordnung, vergeben = {}, set()
    for feld, _l, _p in IMPORT_FELDER:
        if gespeichert.get(feld) in spalten:
            zuordnung[feld] = gespeichert[feld]
            vergeben.add(gespeichert[feld])
    for feld, _l, _p in IMPORT_FELDER:
        if feld in zuordnung:
            continue
        for s in spalten:
            if s not in vergeben and any(w in s.lower() for w in _RATEN[feld]):
                zuordnung[feld] = s
                vergeben.add(s)
                break
    return zuordnung


def zuordnung_aus_post(post, spalten):
    zuordnung, fehler = {}, {}
    for feld, label, pflicht in IMPORT_FELDER:
        wert = post.get(f'spalte_{feld}', '')
        if wert == '':
            if pflicht:
                fehler[feld] = _('Bitte eine Spalte wählen.')
            continue
        if wert not in spalten:
            fehler[feld] = _('Diese Spalte gibt es in der Datei nicht.')
            continue
        if wert in zuordnung.values():
            fehler[feld] = _('Diese Spalte ist schon einem anderen Feld zugeordnet.')
            continue
        zuordnung[feld] = wert
    return zuordnung, fehler


def _datum_csv(text):
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d.%m.%y', '%d/%m/%Y'):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def vorschau(lg, daten, zuordnung):
    """Je Datenzeile: was übernommen würde, oder warum nicht. Prüft gegen den Bestand UND gegen
    die übrigen Zeilen der Datei (ein Stand darf nicht unter einem früheren liegen)."""
    from portfolio.models import Zaehler, ZaehlerStand
    zaehler = {}
    for z in Zaehler.objects.filter(Q(einheit__liegenschaft=lg) | Q(liegenschaft=lg)).select_related('einheit'):
        zaehler.setdefault((z.zaehler_nummer or '').strip().lower(), []).append(z)
    heute = timezone.localdate()
    zeilen = []
    for nr, d in enumerate(daten, start=2):
        z_text = d.get(zuordnung.get('zaehler'), '')
        zeile = {'nr': nr, 'zaehler_text': z_text, 'datum_text': d.get(zuordnung.get('datum'), ''),
                 'stand_text': d.get(zuordnung.get('stand'), ''), 'art_text': d.get(zuordnung.get('art'), ''),
                 'zaehler': None, 'datum': None, 'wert': None, 'art': '', 'fehler': '', 'doppelt': False}
        treffer = zaehler.get(z_text.strip().lower(), [])
        datum = _datum_csv(zeile['datum_text'])
        try:
            wert = _dezimal(zeile['stand_text'], stellen=3)
        except ValueError:
            wert = None
        art = _ARTEN.get(zeile['art_text'].strip().lower()) if zuordnung.get('art') else ''
        if not treffer:
            zeile['fehler'] = _('Zähler «%(n)s» gibt es in dieser Liegenschaft nicht.') % {'n': z_text}
        elif len(treffer) > 1:
            zeile['fehler'] = _('Die Zählernummer «%(n)s» ist mehrfach vergeben.') % {'n': z_text}
        elif datum is None:
            zeile['fehler'] = _('Datum «%(d)s» nicht lesbar (TT.MM.JJJJ oder JJJJ-MM-TT).') % {'d': zeile['datum_text']}
        elif datum > heute:
            zeile['fehler'] = _('Das Ablesedatum liegt in der Zukunft.')
        elif wert is None:
            zeile['fehler'] = _('Stand «%(s)s» ist keine gültige Zahl.') % {'s': zeile['stand_text']}
        elif wert >= Decimal('1000000000'):
            zeile['fehler'] = _('Der Stand ist zu gross.')
        elif art is None:
            zeile['fehler'] = _('Art «%(a)s» unbekannt (Anfang, Zwischen oder Ende).') % {'a': zeile['art_text']}
        else:
            zeile.update({'zaehler': treffer[0], 'datum': datum, 'wert': wert, 'art': art})
        zeilen.append(zeile)

    # Folgeprüfung je Zähler: Bestand plus gültige Zeilen der Datei.
    gueltig = [z for z in zeilen if not z['fehler']]
    for zid in {z['zaehler'].id for z in gueltig}:
        bestand = {s.datum: s.wert for s in ZaehlerStand.objects.filter(zaehler_id=zid)}
        eigene = sorted((z for z in gueltig if z['zaehler'].id == zid), key=lambda z: (z['datum'], z['nr']))
        bekannt = dict(bestand)
        for z in eigene:
            if z['datum'] in bestand and bestand[z['datum']] == z['wert']:
                z['doppelt'] = True
                continue
            if z['datum'] in bekannt:
                z['fehler'] = _('Für den %(d)s gibt es schon einen anderen Stand (%(w)s).') % {
                    'd': z['datum'].strftime('%d.%m.%Y'), 'w': bekannt[z['datum']]}
                continue
            fehler = _folge_pruefen(list(bekannt.items()) + [(z['datum'], z['wert'])])
            if fehler:
                z['fehler'] = fehler
                continue
            bekannt[z['datum']] = z['wert']
    return zeilen


def uebernehmen(lg, zeilen, zuordnung):
    """Übernimmt die fehlerfreien, neuen Zeilen (Herkunft «Import») und speichert die Zuordnung.
    Gibt die Zahl der übernommenen Stände zurück."""
    from portfolio.models import ZaehlerStand
    neu = [z for z in zeilen if not z['fehler'] and not z['doppelt']]
    with transaction.atomic():
        for z in neu:
            ZaehlerStand.objects.create(zaehler=z['zaehler'], datum=z['datum'], wert=z['wert'],
                                        art=z['art'], herkunft='import')
        for zaehler in {z['zaehler'] for z in neu}:
            letzter = zaehler.staende.order_by('-datum', '-id').first()
            zaehler.aktueller_stand = letzter.wert
            zaehler.save(update_fields=['aktueller_stand'])
        # Über den Manager statt `lg.save()`: Das Speichern einer Liegenschaft prüft bei einer
        # STWEG die Wertquoten — eine Spaltenzuordnung hat damit nichts zu tun.
        type(lg).objects.filter(pk=lg.pk).update(zaehler_import_zuordnung=zuordnung)
        lg.zaehler_import_zuordnung = zuordnung
    return len(neu)
