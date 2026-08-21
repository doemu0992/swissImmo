"""Die Liegenschaftsliste als Befundliste — eine Zeile je Objekt.

WARUM ES DIESE DATEI GIBT

Die Liste zeigte bis hierher je Liegenschaft eine Karte mit Einheitenzahl,
Ist-Miete und einem Vermietungsbalken. Das ist **Bestand**: bei einem ruhigen
Portfolio sehen alle Karten gleich aus, und wer die Seite oeffnet, muss jede
einzeln lesen, um zu merken, dass in der dritten seit zwei Monaten eine Wohnung
leer steht. Die Karte kostet dabei rund 280 Pixel Breite fuer vier Zahlen.

Jetzt eine Zeile je Liegenschaft, **sortiert nach Befund**. Wer von oben liest,
sieht zuerst, wo etwas klemmt. Wo nichts klemmt, steht «ohne Befund» — auch das
ist eine Aussage, und sie braucht eine Zeile statt einer Karte.

DIE LEERSTANDSREGEL (Entscheid 21.08.2026)

Drei Festlegungen, die im Code sonst nicht ablesbar waeren:

1. **Ein einziges leeres Objekt genuegt** (`SCHWELLE_LEER`). Keine
   Prozentschwelle. Bei einem Haus mit vier Wohnungen sind 25 % Leerstand ein
   Alarm, bei einem mit vierzig sind 2.5 % derselbe eine Wohnung — und beide
   kosten gleich viel Miete pro Monat. Die Prozentzahl steht im Streifen als
   Portfoliokennzahl, sie ist aber kein Ausloeser.

2. **Leer ist ein Objekt ab dem Ende der Kuendigungsfrist, nicht ab dem
   Auszug.** Massgeblich ist `Mietvertrag.ende` — bei einem gekuendigten
   unbefristeten Vertrag ist das die `per_datum` der Kuendigung, also der Tag,
   an dem das Verhaeltnis rechtlich endet. Das Abnahmeprotokoll (`typ='auszug'`)
   spielt keine Rolle: Ein Mieter, der drei Tage frueher auszieht, macht das
   Objekt nicht frueher vermietbar, und einer, der die Wohnung nach Vertragsende
   nicht raeumt, macht sie nicht laenger belegt.

3. **Ein Nachmieter hebt den Befund auf.** Steht fuer dasselbe Objekt bereits
   ein Vertrag mit spaeterem Beginn, ist der Leerstand bewirtschaftet und keine
   offene Aufgabe mehr. Ohne diese Regel meldet die Liste genau die Objekte,
   um die sich jemand schon gekuemmert hat.

WAS NICHT IN DER ZEILE STEHT

**Laufblockaden.** Ein `Lauf` haengt ueber `Laufart` an der Organisation und
hat keinen Bezug zu einer Liegenschaft (geprueft: kein `liegenschaft`-Feld).
Ein offener Mahnlauf ist eine Sache des ganzen Mandanten und gehoert auf die
Startseite, nicht in jede Objektzeile.

WAS SEIT DEM BUDGET-ENTSCHEID DAZUGEKOMMEN IST

**Unterhalt ueber Budget** stand hier als offene betriebliche Entscheidung:
Es gab kein Budgetfeld, und ob eines je Mandat oder je Liegenschaft gefuehrt
wird, war nicht zu erraten. Die Antwort ist **je Liegenschaft**
(`portfolio.Liegenschaftsbudget`, Entscheid 21.08.2026): Unterhalt faellt am
Gebaeude an, nicht am Eigentuemer — ein Mandat mit vier Liegenschaften hat
vier Daecher. Die Summe je Mandat laesst sich aus den Einzelbudgets bilden,
der umgekehrte Weg nicht. Siehe `_budget()`.

ZUR ANZAHL DER ABFRAGEN

Neun Abfragen fuer das ganze Portfolio, unabhaengig von der Zahl der
Liegenschaften — nicht neun je Zeile. Die Vorgaengerversion lief mit drei
Abfragen und wurde vorher von fuenf je Liegenschaft heruntergeholt; dieser
Stand darf nicht wieder verloren gehen. (Sechs bis zum Budget-Entscheid,
seither drei mehr fuer Budget, Unterhalt und Kreditoren.) Der Waechter dazu steht in
`faelle/test_liegenschaftsliste.py::AbfragezahlTests`.
"""
import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

log = logging.getLogger(__name__)

#: So viele leere Objekte loesen den Befund aus. Eins. Siehe Kopf.
SCHWELLE_LEER = 1

#: Horizont fuer alles, was auf ein Datum zulaeuft: auslaufende Vertraege ohne
#: Nachmieter, ablaufende Policen, faellige Wartungen. Ein halbes Jahr ist die
#: Spanne, in der eine Verwaltung noch handeln kann, ohne dass die Liste zur
#: Jahresvorschau wird.
VORSCHAU_TAGE = 180

#: Reihenfolge der Dringlichkeit. Wird sowohl fuer die Zeilenstufe als auch
#: fuer die Sortierung gebraucht.
RANG = {'crit': 0, 'warn': 1, 'good': 2}

#: Ein Vertrag belegt sein Objekt, solange er laeuft — auch ein gekuendigter.
#: `archiviert` ist beendet (siehe `Mietvertrag.anzeige_status`, Etappe 4b.14).
BELEGENDE_STATUS = ('aktiv', 'gekuendigt')

#: Ein Vertrag, der erst beginnt, ist ein Nachmieter — auch als Entwurf. Wer
#: den Vertrag geschrieben, aber noch nicht aktiviert hat, hat das Objekt
#: vermietet; die Zeile soll ihn nicht noch einmal daran erinnern.
NACHMIETER_STATUS = ('entwurf', 'aktiv', 'gekuendigt')


def _leerstand(lg_ids, stichtag):
    """Belegung, Leerstand und Ist-Miete je Liegenschaft — in drei Abfragen.

    Traegt die Ist-Miete mit, obwohl der Name nur vom Leerstand spricht: Sie
    faellt beim Durchlaufen derselben Vertragsmenge ab. Ein zweiter Durchgang
    nur fuer die Summe waere eine weitere Abfrage ueber dieselben Zeilen.

    DIE IST-MIETE ENTHAELT GEKUENDIGTE VERTRAEGE. Die Vorgaengerversion zaehlte
    nur `status='aktiv'` und liess damit jeden gekuendigten, aber noch
    laufenden Vertrag aus dem Ertrag fallen — obwohl er bis zum Vertragsende
    Miete schuldet (Etappe H4 hat das fuer die Sollstellung bereits so
    festgelegt). Die Zahl steigt dadurch gegenueber vorher; sie war vorher
    falsch.
    """
    from portfolio.models import Einheit
    from rentals.models import Mietvertrag

    grenze = stichtag + timedelta(days=VORSCHAU_TAGE)

    einheiten_je_lg = defaultdict(list)
    for e_id, e_lg in Einheit.objects.filter(
            liegenschaft_id__in=lg_ids).values_list('id', 'liegenschaft_id'):
        einheiten_je_lg[e_lg].append(e_id)

    laeuft = (Q(status__in=BELEGENDE_STATUS) & Q(beginn__lte=stichtag)
              & (Q(ende__isnull=True) | Q(ende__gte=stichtag)))
    kuenftig = Q(status__in=NACHMIETER_STATUS) & Q(beginn__gt=stichtag)

    belegt_je_lg = defaultdict(set)
    ertrag_je_lg = defaultdict(lambda: Decimal('0.00'))
    nachmieter = set()          # Einheiten-IDs mit kuenftigem Vertrag
    laeuft_aus = {}             # Einheiten-ID -> Enddatum im Horizont
    vertrag_lg = {}             # Vertrags-ID -> Liegenschafts-ID (fuer Nebenobjekte)
    kuenftige_vertraege = []

    for v_id, v_lg, e_id, status, beginn, ende, netto, nk in (
            Mietvertrag.objects
            .filter(Q(einheit__liegenschaft_id__in=lg_ids) & (laeuft | kuenftig))
            .values_list('id', 'einheit__liegenschaft_id', 'einheit_id',
                         'status', 'beginn', 'ende', 'netto_mietzins',
                         'nebenkosten')):
        if beginn > stichtag:
            kuenftige_vertraege.append(v_id)
            if e_id:
                nachmieter.add(e_id)
            continue
        vertrag_lg[v_id] = v_lg
        ertrag_je_lg[v_lg] += (netto or Decimal('0')) + (nk or Decimal('0'))
        if e_id:
            belegt_je_lg[v_lg].add(e_id)
            if ende and stichtag <= ende <= grenze:
                laeuft_aus[e_id] = ende

    # Nebenobjekte (Parkplatz, Keller) zaehlen als belegt bzw. als versorgt.
    # Zugeordnet werden sie der Liegenschaft des HAUPTobjekts — wie bisher;
    # ein Parkplatz in einer anderen Liegenschaft faerbt deren Leerstand also
    # nicht ein.
    alle_vertraege = list(vertrag_lg) + kuenftige_vertraege
    if alle_vertraege:
        for v_id, neben_id in Mietvertrag.objects.filter(
                id__in=alle_vertraege).values_list('id', 'nebenobjekte'):
            if not neben_id:
                continue
            if v_id in vertrag_lg:
                belegt_je_lg[vertrag_lg[v_id]].add(neben_id)
            else:
                nachmieter.add(neben_id)

    ergebnis = {}
    for lg_id in lg_ids:
        einheiten = einheiten_je_lg.get(lg_id, [])
        belegte = belegt_je_lg.get(lg_id, set())
        offen = [e for e in einheiten
                 if e not in belegte and e not in nachmieter]
        auslaufend = sorted(laeuft_aus[e] for e in einheiten
                            if e in laeuft_aus and e not in nachmieter)
        ergebnis[lg_id] = {
            'gesamt': len(einheiten),
            'belegt': len(einheiten) - len(offen),
            'leer': len(offen),
            'wird_leer': len(auslaufend),
            'wird_leer_am': auslaufend[0] if auslaufend else None,
            'ertrag': ertrag_je_lg[lg_id],
        }
    return ergebnis


def _weitere_befunde(lg_ids, stichtag):
    """Policen, Wartungen, Tickets, Budget — sechs Abfragen fuer alle Objekte.

    Jeder Eintrag ist ein Tupel `(stufe, text, kategorie, titel)`. Der Titel
    traegt die Zahlen, die den Chip belegen — beim Budget ist genau das der
    Punkt: «Unterhalt überschritten» ist eine Behauptung, «CHF 34'800 von
    31'000 bei 4 Monaten Restjahr» ist eine Aussage. Die Kategorie
    traegt die Filterleiste ueber der Liste; sie steht hier und nicht im View,
    damit Chip und Filter nicht auseinanderlaufen koennen. Die Reihenfolge
    innerhalb einer Zeile ergibt sich spaeter aus der Stufe, nicht aus der
    Reihenfolge hier.
    """
    from portfolio.models import Versicherung, Wartungsfrist
    from tickets.models import SchadenMeldung

    grenze = stichtag + timedelta(days=VORSCHAU_TAGE)
    befunde = defaultdict(list)

    # Gebaeudeversicherung: die einzige Police, die in der Zeile steht. Sie ist
    # in fast allen Kantonen obligatorisch; eine abgelaufene Glasbruchpolice
    # ist dagegen eine Frage der Zweckmaessigkeit und gehoert in die Objektakte.
    for lg_id, ablauf in Versicherung.objects.filter(
            liegenschaft_id__in=lg_ids, art='gebaeude',
            ablauf_datum__isnull=False, ablauf_datum__lte=grenze
            ).values_list('liegenschaft_id', 'ablauf_datum'):
        if ablauf < stichtag:
            befunde[lg_id].append(('crit', 'Gebäudepolice abgelaufen', 'frist',
                               f'abgelaufen am {ablauf.strftime("%d.%m.%Y")}'))
        else:
            befunde[lg_id].append(('warn', 'Police läuft ab', 'frist',
                               f'läuft ab am {ablauf.strftime("%d.%m.%Y")}'))

    faellig = defaultdict(int)
    ueberfaellig = defaultdict(int)
    for lg_id, termin in Wartungsfrist.objects.filter(
            liegenschaft_id__in=lg_ids, aktiv=True,
            naechste_faelligkeit__lte=grenze
            ).values_list('liegenschaft_id', 'naechste_faelligkeit'):
        if termin < stichtag:
            ueberfaellig[lg_id] += 1
        else:
            faellig[lg_id] += 1
    for lg_id, anzahl in ueberfaellig.items():
        befunde[lg_id].append(('crit', f'{anzahl} Wartung überfällig'
                               if anzahl == 1 else f'{anzahl} Wartungen überfällig',
                               'frist', ''))
    for lg_id, anzahl in faellig.items():
        befunde[lg_id].append(('warn', f'{anzahl} Wartung fällig'
                               if anzahl == 1 else f'{anzahl} Wartungen fällig',
                               'frist', f'innert {VORSCHAU_TAGE} Tagen'))

    tickets = defaultdict(int)
    for lg_id in SchadenMeldung.objects.filter(
            liegenschaft_id__in=lg_ids).exclude(status='erledigt'
            ).values_list('liegenschaft_id', flat=True):
        tickets[lg_id] += 1
    for lg_id, anzahl in tickets.items():
        befunde[lg_id].append(('warn', f'{anzahl} offenes Ticket' if anzahl == 1
                               else f'{anzahl} offene Tickets', 'ticket', ''))

    for lg_id, eintrag in _budget(lg_ids, stichtag).items():
        befunde[lg_id].append(eintrag)

    return befunde


def _budget(lg_ids, stichtag):
    """Unterhalt gegen Budget — mit Blick auf das Restjahr.

    «CHF 34'800 von 31'000 verbraucht» ist eine Zahl. «34'800 von 31'000 bei
    vier Monaten Restjahr» ist eine Aussage: Im Februar waeren 60 Prozent
    Verbrauch alarmierend, im November unauffaellig. Der Titel des Chips nennt
    deshalb immer beides.

    OHNE HINTERLEGTES BUDGET WIRD NICHT GEMELDET. Ein Hinweis «kein Budget
    erfasst» an jeder Liegenschaft waere die klassische Dauerbeschwerde — wer
    keines fuehrt, will keines fuehren. Der Befund ist der Preis dafuer, eines
    gesetzt zu haben, nicht eine Mahnung, eines zu setzen.

    GEZAEHLT WERDEN UNTERHALT UND KREDITORENRECHNUNGEN. Unterhalt wird in
    diesem Haus auf beiden Wegen erfasst: als `Unterhalt`-Eintrag und als
    Eingangsrechnung an der Liegenschaft. Nur einen der beiden zu zaehlen
    hiesse, je nach Arbeitsweise die Haelfte zu uebersehen.

    Zwei Abfragen fuer das ganze Portfolio, plus eine fuer die Budgets.
    """
    from finance.models import KreditorenRechnung
    from portfolio.models import Liegenschaftsbudget, Unterhalt

    budgets = {b.liegenschaft_id: b for b in Liegenschaftsbudget.objects.filter(
        liegenschaft_id__in=lg_ids, jahr=stichtag.year)}
    if not budgets:
        return {}

    verbraucht = {lg_id: Decimal('0') for lg_id in budgets}
    for lg_id, kosten in Unterhalt.objects.filter(
            liegenschaft_id__in=budgets, datum__year=stichtag.year
    ).values_list('liegenschaft_id', 'kosten'):
        verbraucht[lg_id] += kosten or Decimal('0')
    for lg_id, betrag in KreditorenRechnung.objects.filter(
            liegenschaft_id__in=budgets, datum__year=stichtag.year
    ).exclude(status='storniert').values_list('liegenschaft_id', 'betrag'):
        verbraucht[lg_id] += betrag or Decimal('0')

    # Der erwartete Verbrauch bis heute, linear ueber das Jahr. Grob, aber
    # ehrlich grob — eine Heizungsreparatur im Januar verzerrt jede feinere
    # Rechnung ohnehin. Deshalb meldet «ueber Plan» erst ab 15 Punkten
    # Abstand: Unterhalt faellt in Schueben an, nicht in Tagesraten.
    anteil = Decimal(stichtag.timetuple().tm_yday) / Decimal(365)
    restmonate = max(0, 12 - stichtag.month)

    ergebnis = {}
    for lg_id, b in budgets.items():
        ist = verbraucht[lg_id]
        if not b.unterhalt:
            continue
        if ist > b.unterhalt:
            stufe, wie = 'crit', 'überschritten'
        elif ist / b.unterhalt > anteil + Decimal('0.15'):
            stufe, wie = 'warn', 'über Plan'
        else:
            continue
        rest = (f' bei {restmonate} Monat{"en" if restmonate != 1 else ""} Restjahr'
                if restmonate else ' — Jahr fast vorbei')
        ergebnis[lg_id] = (
            stufe, f'Unterhalt {wie}', 'budget',
            f'CHF {ist:,.0f} von {b.unterhalt:,.0f}{rest}'.replace(',', "'"))
    return ergebnis


def zeilen(lg_liste, stichtag=None):
    """Eine Zeile je Liegenschaft, sortiert nach Befund.

    `lg_liste` ist eine bereits mandantengefilterte Liste von Liegenschaften —
    die Funktion holt sie nicht selbst, damit der Aufrufer den `?lg=`-Filter
    und die Sortierung behaelt.
    """
    stichtag = stichtag or timezone.localdate()
    lgs = list(lg_liste)
    lg_ids = [lg.id for lg in lgs]
    if not lg_ids:
        return []

    bestand = _leerstand(lg_ids, stichtag)
    weitere = _weitere_befunde(lg_ids, stichtag)

    rows = []
    for lg in lgs:
        zahlen = bestand.get(lg.id, {'gesamt': 0, 'belegt': 0, 'leer': 0,
                                     'wird_leer': 0, 'wird_leer_am': None,
                                     'ertrag': Decimal('0.00')})
        chips = []
        gesamt_vorab = zahlen['gesamt']
        leer = zahlen['leer']
        if leer >= SCHWELLE_LEER:
            chips.append(('crit', f'{leer} leer', 'leer',
                          f'von {gesamt_vorab} Objekt(en)' if gesamt_vorab else ''))
        if zahlen['wird_leer']:
            chips.append(('warn', f"{zahlen['wird_leer']} wird frei", 'leer',
                          f"ab {zahlen['wird_leer_am'].strftime('%d.%m.%Y')}"
                          if zahlen['wird_leer_am'] else ''))
        chips.extend(weitere.get(lg.id, []))

        stufe = 'good'
        for kennung, _text, _kat, _titel in chips:
            if RANG[kennung] < RANG[stufe]:
                stufe = kennung
        gesamt = zahlen['gesamt']
        rows.append({
            'lg': lg,
            'einheiten': gesamt,
            'belegt': zahlen['belegt'],
            'leer': leer,
            'wird_leer_am': zahlen['wird_leer_am'],
            'ertrag': zahlen['ertrag'],
            'belegung': round(zahlen['belegt'] / gesamt * 100) if gesamt else 0,
            'chips': sorted(chips, key=lambda c: RANG[c[0]]),
            'kategorien': {kat for _s, _t, kat, _ti in chips},
            'stufe': stufe,
            'ohne_befund': not chips,
        })

    # Nach Befund, dann nach der Zahl leerer Objekte, dann nach Adresse. Die
    # Adresse zuletzt, damit die Reihenfolge bei gleichem Befund stabil ist —
    # eine Liste, die bei jedem Aufruf anders sortiert, wird nicht gelesen.
    rows.sort(key=lambda r: (RANG[r['stufe']], -r['leer'],
                             (r['lg'].strasse or '').lower()))
    return rows


def streifen(rows):
    """Die Kennzahlen ueber der Liste — aus den Zeilen, ohne neue Abfrage."""
    einheiten = sum(r['einheiten'] for r in rows)
    leer = sum(r['leer'] for r in rows)
    return {
        'objekte': len(rows),
        'einheiten': einheiten,
        'leer': leer,
        'leer_quote': (Decimal(leer) / Decimal(einheiten) * 100
                       ).quantize(Decimal('0.1')) if einheiten else Decimal('0.0'),
        'ertrag': sum((r['ertrag'] for r in rows), Decimal('0.00')),
        'mit_befund': sum(1 for r in rows if not r['ohne_befund']),
    }
