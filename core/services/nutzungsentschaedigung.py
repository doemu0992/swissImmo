"""Nutzungsentschädigung, wenn der Mieter nach Vertragsende nicht auszieht.

Stresstest 30.09.2026, Punkt 8: Nach dem 28.02. stellte das System für den
Nichtzahler nichts mehr, obwohl er die Wohnung nicht geräumt hatte — ab März
fehlten CHF 1480 Ertrag pro Monat. Die Sollstellung verrechnet einen Vertrag nur
bis zu seinem Ende.

Wer nach Vertragsende in der Sache bleibt, schuldet dem Vermieter eine
Entschädigung für die Nutzung (Art. 641 ZGB / Bereicherungsrecht; in der Praxis
in Höhe des bisherigen Bruttomietzinses). Sie ist kein Mietzins und wird nicht
automatisch gestellt: Ob der Mieter wirklich noch drin ist, weiss nur die
Verwaltung, und eine zu Unrecht gestellte Forderung ist teurer als eine
verspätete. Darum zwei Schritte:

1. Der tägliche Lauf legt die Pendenz «Nutzungsentschädigung prüfen» an, sobald
   ein Vertrag beendet ist, ohne dass ein Rücknahmeprotokoll vorliegt
   (`nutzung_pendenzen`).
2. Die Verwaltung stellt die Entschädigung auf der Vertragsakte aus
   (`stelle_bis_heute`) — je Monat eine Forderung, idempotent, anteilig im
   ersten Monat und nur bis zur Rückgabe, falls diese inzwischen protokolliert ist.

MWST: Folgt dem Vertrag. Ist das Objekt steuerpflichtig vermietet (`mwst_pflichtig`),
wird die Entschädigung wie die Miete mit dem Satz des Vertrags belastet und über
2200 gebucht; bei Wohnraum (nicht steuerbar) entsteht keine MWST. Beides kommt vor.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

TITEL_PRAEFIX = 'Nutzungsentschädigung'


def _titel(jahr, monat):
    return f'{TITEL_PRAEFIX} {monat:02d}/{jahr}'


def rueckgabe_datum(vertrag):
    """Datum der protokollierten Rücknahme (Auszugsprotokoll), sonst None."""
    p = (vertrag.abnahmen.filter(typ='auszug').order_by('datum', 'id').first())
    return p.datum if p else None


def ist_offen(vertrag, stichtag=None):
    """Vertrag ist beendet, und eine Rücknahme ist nicht protokolliert."""
    stichtag = stichtag or timezone.localdate()
    if vertrag.status == 'entwurf' or not vertrag.ende or vertrag.ende >= stichtag:
        return False
    rg = rueckgabe_datum(vertrag)
    return rg is None or rg > vertrag.ende


def monate_ohne_forderung(vertrag, bis=None):
    """(jahr, monat) aller Monate nach Vertragsende bis `bis`, für die noch keine
    Entschädigung gestellt ist — inklusive des laufenden Monats."""
    from finance.models import DebitorenRechnung
    bis = bis or timezone.localdate()
    if not ist_offen(vertrag, bis):
        return []
    ende_nutzung = rueckgabe_datum(vertrag) or bis
    ende_nutzung = min(ende_nutzung, bis)
    j, m = vertrag.ende.year, vertrag.ende.month
    ergebnis = []
    vorhanden = set(vertrag.debitoren_rechnungen.exclude(status='storniert')
                    .filter(titel__startswith=TITEL_PRAEFIX).values_list('titel', flat=True))
    while (j, m) <= (ende_nutzung.year, ende_nutzung.month):
        # Der Endmonat ist nur teilweise nach Vertragsende, wenn das Ende nicht der
        # Monatsletzte ist; ist es der Monatsletzte, gibt es in diesem Monat nichts.
        if date(j, m, calendar.monthrange(j, m)[1]) > vertrag.ende and _titel(j, m) not in vorhanden:
            ergebnis.append((j, m))
        m += 1
        if m == 13:
            j, m = j + 1, 1
    return ergebnis


def stelle(vertrag, jahr, monat, user=None):
    """Stellt die Entschädigung für EINEN Monat. Gibt die Forderung zurück oder None
    (nichts geschuldet oder bereits gestellt)."""
    from core.services.automation import _konten_fuer
    from finance.booking import buche, ensure_kontenplan
    from finance.models import DebitorenRechnung

    titel = _titel(jahr, monat)
    if vertrag.debitoren_rechnungen.filter(titel=titel).exclude(status='storniert').exists():
        return None
    letzter = calendar.monthrange(jahr, monat)[1]
    monat_start, monat_ende = date(jahr, monat, 1), date(jahr, monat, letzter)
    von = max(monat_start, vertrag.ende + timedelta(days=1))
    bis = monat_ende
    rg = rueckgabe_datum(vertrag)
    if rg is not None:
        bis = min(bis, rg)
    if von > bis:
        return None
    faktor = Decimal((bis - von).days + 1) / Decimal(letzter)
    # Die Höhe folgt dem zuletzt geltenden Bruttomietzins (Stichtag Vertragsende).
    netto = round((vertrag.verrechneter_netto_mietzins(vertrag.ende) or Decimal('0')) * faktor, 2)
    nk = round((vertrag.verrechnete_nebenkosten(vertrag.ende) or Decimal('0')) * faktor, 2)
    total = netto + nk
    if total <= 0:
        return None
    # MWST wie in der Sollstellung: auf Netto + Nebenkosten, nur bei steuerpflichtigem Vertrag.
    mwst = Decimal('0.00')
    if vertrag.mwst_pflichtig and (vertrag.mwst_satz or 0) > 0:
        mwst = round(total * (vertrag.mwst_satz / Decimal('100')), 2)

    ensure_kontenplan()
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    ertrag_konto, nk_konto, nk_label = _konten_fuer(vertrag)
    rechnung = DebitorenRechnung.objects.create(
        vertrag=vertrag, liegenschaft=lg, einheit=vertrag.einheit, titel=titel,
        beschreibung=(f'Entschädigung für die Weiternutzung vom {von:%d.%m.%Y} bis '
                      f'{bis:%d.%m.%Y} nach Vertragsende am {vertrag.ende:%d.%m.%Y}.'),
        betrag=total + mwst, faellig_am=von, status='offen')
    buche("1100", ertrag_konto, netto, f"{titel} {vertrag.mieter}",
          datum=von, liegenschaft=lg, debitor=rechnung, user=user)
    buche("1100", nk_konto, nk, f"{titel} ({nk_label}) {vertrag.mieter}",
          datum=von, liegenschaft=lg, debitor=rechnung, user=user)
    buche("1100", "2200", mwst, f"MWST {vertrag.mwst_satz}% {titel} {vertrag.mieter}",
          datum=von, liegenschaft=lg, debitor=rechnung, user=user)
    return rechnung


def stelle_bis_heute(vertrag, user=None, bis=None):
    """Stellt alle noch fehlenden Monate bis und mit dem laufenden. Gibt die Liste
    der neuen Forderungen zurück."""
    neu = []
    for j, m in monate_ohne_forderung(vertrag, bis):
        r = stelle(vertrag, j, m, user=user)
        if r is not None:
            neu.append(r)
    return neu


def nutzung_pendenzen(heute=None):
    """Pendenz «Nutzungsentschädigung prüfen» je beendetem, nicht zurückgenommenem
    Vertrag; erledigt, sobald die Rücknahme protokolliert oder nichts mehr offen ist.
    Läuft im Kontext EINER Organisation (Aufruf aus `_pendenzen_fuer_organisation`).
    Gibt die Anzahl neu angelegter Pendenzen zurück."""
    from core.models import Pendenz
    from rentals.models import Mietvertrag

    heute = heute or timezone.localdate()
    neu = 0
    kandidaten = (Mietvertrag.objects.filter(status__in=('aktiv', 'gekuendigt'), ende__lt=heute)
                  .select_related('mieter', 'einheit__liegenschaft'))
    offene_ids = set()
    for v in kandidaten:
        if not ist_offen(v, heute):
            continue
        offene_ids.add(v.pk)
        fehlend = monate_ohne_forderung(v, heute)
        quelle = f'auto:nutzung:{v.pk}'
        titel = f'Nutzungsentschädigung prüfen – {v.mieter.display_name} ({v.einheit.bezeichnung})'
        beschr = (f'Vertrag am {v.ende:%d.%m.%Y} beendet, keine Rücknahme protokolliert. '
                  f'Zieht der Mieter nicht aus, schuldet er eine Nutzungsentschädigung. '
                  f'{len(fehlend)} Monat(e) ohne Forderung.')
        p, created = Pendenz.objects.get_or_create(
            quelle=quelle, defaults={
                'titel': titel, 'kategorie': 'finanzen', 'faellig_am': heute,
                'beschreibung': beschr, 'vertrag': v,
                'liegenschaft': v.einheit.liegenschaft if v.einheit_id else None})
        if created:
            neu += 1
        elif not p.erledigt and p.beschreibung != beschr:
            p.beschreibung = beschr
            p.save(update_fields=['beschreibung'])
    for p in Pendenz.objects.filter(quelle__startswith='auto:nutzung:', erledigt=False):
        if p.vertrag_id not in offene_ids:
            p.erledigt = True
            p.erledigt_am = heute
            p.save(update_fields=['erledigt', 'erledigt_am'])
    return neu
