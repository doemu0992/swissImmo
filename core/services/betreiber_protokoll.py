"""Protokoll des Betreibers: alles, was schiefgehen kann, auf EINER Seite.

Bis 15.11.2026 lagen die Hinweise verstreut: Fehler der Anwendung nur in der Logdatei auf dem Server, CSP-Meldungen auf
einer eigenen Seite, Abrufausfälle und Pflege auf der Startseite, gescheiterte Aufträge je Verwaltung, Sicherheitsereignisse
und RLS-Befunde nur über `manage.py sicherheitslog`. Dieser Dienst liest alle Quellen und gibt EINE zeitlich geordnete Liste
zurück; die Leiste des Betreiber-Portals zeigt die Zahl der neuen Fehler als rote Pille.

QUELLEN
    anwendung   ERROR/CRITICAL/WARNING aus dem Anwendungs-Log (gleiche Meldung = ein Eintrag mit Zähler)
    abruf       Abrufe, die zuletzt scheiterten (`core.AbrufStatus`) — bleiben stehen, bis der Abruf wieder gelingt
    auftrag     Aufträge im Zustand «fehler», über alle Verwaltungen
    rls         Befunde der RLS-Probe
    csp         Verstösse gegen die Content-Security-Policy (zusammengefasst, `csp_meldungen`)
    pflege      fällige Pflege (LIK-Tabelle, Formularpflicht)
    sicherheit  Sicherheitsereignisse (Anmeldungen, Schlüssel, Nachträge)

STUFEN
    fehler (zählt in der Pille), warnung, info.

WAS «NEU» IST
    Ein Fehler zählt, bis der Betreiber die Seite geöffnet hat (`als_gesehen_merken`, je Benutzer im Cache). Abrufausfälle
    sind ein Zustand, kein Ereignis: Sie zählen, solange sie bestehen.

Die gezeigte Auswahl lässt sich als CSV herunterladen (`als_csv`); der Export wird als Sicherheitsereignis vermerkt.

Es wird nichts zusätzlich gespeichert ausser dem Zeitpunkt «zuletzt gesehen». Die Seite sieht nur der Betreiber; in
Logzeilen können Namen aus allen Verwaltungen stehen.
"""
import re
from collections import OrderedDict
from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone
from django.utils.translation import gettext as _

from core.services import csp_meldungen

#: So weit zurück reicht die Liste.
FENSTER_TAGE = 14
#: Höchstzahl Zeilen je Quelle, damit die Seite lesbar bleibt.
MAX_JE_QUELLE = 200

QUELLEN = OrderedDict([
    ('anwendung', 'Anwendung'), ('abruf', 'Abrufe'), ('auftrag', 'Aufträge'), ('rls', 'RLS-Probe'),
    ('csp', 'CSP'), ('pflege', 'Pflege'), ('sicherheit', 'Sicherheit'),
])
STUFEN = ('fehler', 'warnung', 'info')

_KOPF = re.compile(r'^(?P<zeit>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[,.]?\d* (?P<stufe>[A-Z]+) (?P<logger>\S+): (?P<text>.*)$')
_STUFE = {'ERROR': 'fehler', 'CRITICAL': 'fehler', 'WARNING': 'warnung'}
_ZAHL = re.compile(r'\d+')

#: Bekannte Meldungen, die keine Fehler der Anwendung sind: (Muster im Text, Stufe, Erklärung). Ohne diese Liste stünde
#: die rote Zahl dauernd an und sagte nichts mehr (15.11.2026: «OSError: write error» 203-mal in zwei Wochen).
BEKANNT = (
    (re.compile(r'^OSError: write error'), 'warnung',
     ('Meldung des Webservers: Der Browser hat die Verbindung geschlossen, bevor die Antwort fertig war (Seite verlassen, '
      'Abruf abgebrochen). In der Regel harmlos; auffällig wäre nur eine Häufung zusammen mit Klagen über Ladefehler.')),
    (re.compile(r'^WARTUNGSMODUS: \d+ Migration\(en\) nicht angewendet'), 'warnung',
     ('Entsteht bei jedem Einspielen zwischen «Code holen» und «migrate»: In dieser Zeit zeigt die Anwendung die '
      'Wartungsseite. Erledigt, sobald die Migration gelaufen ist; ein Problem nur, wenn die Meldung sich weiter wiederholt.')),
)


def _zeit(text):
    """Zeitstempel einer Logzeile (Ortszeit des Servers) als Zeitpunkt mit Zone."""
    try:
        return timezone.make_aware(datetime.strptime(text, '%Y-%m-%d %H:%M:%S'))
    except (ValueError, OverflowError):
        return None


def aus_log(zeilen):
    """Fehler und Warnungen aus Logzeilen, gleiche Meldung zusammengefasst.

    «Gleich» heisst: gleiche Stufe, gleicher Logger, gleicher Text ohne Zahlen (Ticket #3 und Ticket #4 sind dieselbe
    Meldung). Folgezeilen ohne Zeitstempel (Traceback) gehören zur Meldung davor; gezeigt wird ihr Ende, dort steht die
    Ausnahme. Der Logger `csp` fehlt hier: Seine Zeilen liest `csp_meldungen`."""
    gruppen = OrderedDict()
    aktuell = None
    for zeile in zeilen:
        m = _KOPF.match(zeile)
        if not m:
            if aktuell is not None and zeile.strip():
                aktuell['_folge'].append(zeile.rstrip())
            continue
        aktuell = None
        stufe = _STUFE.get(m['stufe'])
        if stufe is None or m['logger'] == 'csp':
            continue
        text = m['text'].strip()[:400]
        erklaerung = ''
        for muster, bekannt_stufe, bekannt_text in BEKANNT:
            if muster.search(text):
                stufe, erklaerung = bekannt_stufe, bekannt_text
                break
        schluessel = (stufe, m['logger'], _ZAHL.sub('#', text)[:200])
        zeit = _zeit(m['zeit'])
        g = gruppen.get(schluessel)
        if g is None:
            gruppen[schluessel] = g = {'quelle': 'anwendung', 'stufe': stufe, 'titel': text, 'ort': m['logger'],
                                       'anzahl': 0, 'zeit': zeit, '_folge': [], '_erklaerung': erklaerung}
        g['anzahl'] += 1
        g['titel'], g['_folge'] = text, []
        if zeit is not None:
            g['zeit'] = zeit
        aktuell = g
    for g in gruppen.values():
        folge = g.pop('_folge')
        g['detail'] = g.pop('_erklaerung') or '\n'.join(folge[-6:])[:1200]
    return list(gruppen.values())


def _log_zeilen():
    zeilen = []
    for datei in csp_meldungen.logdateien():
        try:
            zeilen.extend(csp_meldungen._hinteres_stueck(datei))
        except OSError:
            continue
    return zeilen


def _anwendung(zeilen):
    return aus_log(zeilen)


def _csp(zeilen):
    """CSP-Meldungen, je Regel und Ursache EINE Zeile: Dieselbe Ursache meldet sich auf jeder Seite, und fünfzig Zeilen
    «style-src-attr» verdrängten sonst alles andere. Die Seiten einzeln zeigt die CSP-Seite."""
    gruppen = OrderedDict()
    for e in csp_meldungen.lesen(zeilen):
        ursache = ' · '.join(t for t in (e.get('quelle'), e.get('probe')) if t)
        if e.get('quelle', '').startswith(e['seite']):             # Quelle ist die Seite selbst (mit Zeile): keine Ursache
            ursache = e.get('probe') or ''
        zeit = _zeit(e['zuletzt'])
        g = gruppen.setdefault((e['regel'], e['blockiert'], ursache), {
            'quelle': 'csp', 'stufe': 'warnung', 'titel': f"{e['regel']} ({e['blockiert']})", 'detail': ursache,
            'anzahl': 0, 'zeit': zeit, '_seiten': []})
        g['anzahl'] += e['anzahl']
        g['_seiten'].append(e['seite'])
        if zeit is not None and (g['zeit'] is None or zeit > g['zeit']):
            g['zeit'] = zeit
    for g in gruppen.values():
        seiten = sorted(set(g.pop('_seiten')))
        g['ort'] = seiten[0] if len(seiten) == 1 else f'{len(seiten)} Seiten'
    return list(gruppen.values())


def _abrufe():
    from core.models import AbrufStatus
    return [{'quelle': 'abruf', 'stufe': 'fehler', 'titel': s.letzter_fehler or _('Abruf gescheitert'), 'ort': s.name,
             'detail': '', 'anzahl': s.fehler_in_folge, 'zeit': s.letzter_versuch, 'zustand': True}
            for s in AbrufStatus.objects.filter(fehler_in_folge__gt=0)]


def _auftraege(seit):
    from core.models import Auftrag
    qs = (Auftrag.alle_organisationen.filter(zustand=Auftrag.ZUSTAND_FEHLER, erstellt_am__gte=seit)
          .select_related('organisation').order_by('-erstellt_am')[:MAX_JE_QUELLE])
    return [{'quelle': 'auftrag', 'stufe': 'fehler', 'titel': a.fehler or _('Auftrag gescheitert'),
             'ort': f'{a.art} · {a.organisation}', 'detail': '', 'anzahl': 1, 'zeit': a.beendet_am or a.erstellt_am}
            for a in qs]


def _sicherheit(seit):
    from core import rls
    from core.models import SicherheitsEreignis
    aus = []
    for e in SicherheitsEreignis.objects.filter(zeitpunkt__gte=seit).order_by('-zeitpunkt')[:MAX_JE_QUELLE]:
        probe = e.aktion == rls.AKTION_PROBE
        aus.append({'quelle': 'rls' if probe else 'sicherheit', 'stufe': 'fehler' if probe else 'info', 'titel': e.aktion,
                    'ort': e.objekt, 'detail': (e.details or '')[:600], 'anzahl': 1, 'zeit': e.zeitpunkt})
    return aus


def _pflege(heute):
    from core.services import abruf_status, datenpflege
    schon = set(abruf_status.ausfaelle())          # Abrufausfälle stehen als eigene Quelle da
    return [{'quelle': 'pflege', 'stufe': 'warnung', 'titel': text, 'ort': '', 'detail': '', 'anzahl': 1, 'zeit': None}
            for text in datenpflege.faellig(heute) if text not in schon]


def eintraege(jetzt=None):
    """Alle Einträge der letzten `FENSTER_TAGE` Tage, neueste zuerst; Einträge ohne Zeitpunkt (Pflege) zuoberst."""
    jetzt = jetzt or timezone.now()
    seit = jetzt - timedelta(days=FENSTER_TAGE)
    zeilen = _log_zeilen()
    alle = (_anwendung(zeilen) + _csp(zeilen) + _abrufe() + _auftraege(seit) + _sicherheit(seit)
            + _pflege(timezone.localdate(jetzt)))
    alle = [e for e in alle if e['zeit'] is None or e['zeit'] >= seit or e.get('zustand')]
    alle.sort(key=lambda e: (e['zeit'] is None, e['zeit'] or jetzt), reverse=True)
    return alle


def als_csv(liste, quellen_namen):
    """Die Einträge als CSV für Excel: Strichpunkt, UTF-8 mit BOM, Zellen gegen Formelinjektion geschützt."""
    import csv
    import io

    from core.services.datenexport import _csv_zelle
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=';', lineterminator='\r\n')
    w.writerow(['Zuletzt', 'Stufe', 'Quelle', 'Meldung', 'Ort', 'Detail', 'Anzahl'])
    for e in liste:
        zeit = timezone.localtime(e['zeit']).strftime('%d.%m.%Y %H:%M') if e['zeit'] else ''
        w.writerow([_csv_zelle(x) for x in (zeit, e['stufe'], quellen_namen.get(e['quelle'], e['quelle']), e['titel'],
                                            e.get('ort', ''), e.get('detail', ''), e['anzahl'])])
    return '\ufeff' + puffer.getvalue()


# ── «zuletzt gesehen» und die Zahl in der Leiste ────────────────────────────────────────────────────────────────
def _schluessel(benutzer):
    return f'betreiber-protokoll-gesehen:{getattr(benutzer, "pk", 0)}'


def gesehen_am(benutzer):
    return cache.get(_schluessel(benutzer))


def als_gesehen_merken(benutzer, jetzt=None):
    cache.set(_schluessel(benutzer), jetzt or timezone.now(), 400 * 24 * 3600)
    cache.delete(f'betreiber-protokoll-zahl:{getattr(benutzer, "pk", 0)}')


def ist_neu(eintrag, gesehen):
    """Ein Fehler, den der Betreiber noch nicht gesehen hat (oder ein Zustand, der noch besteht)."""
    if eintrag['stufe'] != 'fehler':
        return False
    if eintrag.get('zustand'):
        return True
    return gesehen is None or (eintrag['zeit'] is not None and eintrag['zeit'] > gesehen)


def fehlerzahl(benutzer, jetzt=None):
    """Zahl der neuen Fehler für die rote Pille. Eine Minute gemerkt: Die Leiste steht auf jeder Seite des Portals."""
    merk = f'betreiber-protokoll-zahl:{getattr(benutzer, "pk", 0)}'
    zahl = cache.get(merk)
    if zahl is None:
        try:
            gesehen = gesehen_am(benutzer)
            zahl = sum(1 for e in eintraege(jetzt) if ist_neu(e, gesehen))
        except Exception:                                    # noqa: BLE001 — die Leiste darf an keinem Protokoll scheitern
            import logging
            logging.getLogger(__name__).exception('Fehlerzahl des Betreiber-Protokolls nicht ermittelbar')
            return 0
        cache.set(merk, zahl, 60)
    return zahl
