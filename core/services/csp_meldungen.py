"""CSP-Meldungen für den Betreiber: die Verstösse aus dem Anwendungs-Log, zusammengefasst.

Der Browser meldet jeden Verstoss gegen die Content-Security-Policy an `/csp-bericht/` (`core/csp.py`); die Anwendung
schreibt ihn als Zeile «CSP-Verstoss: <Regel> | blockiert=… | Seite=… | Zeile=…» ins Log (`logs/swissimmo.log`, rotierend).
Diese Seite liest das Log (nur den hinteren Teil), fasst gleiche Meldungen zusammen und zeigt sie dem Betreiber, der dazu
keinen Serverzugang braucht. Es wird nichts zusätzlich gespeichert.

DATENSCHUTZ: In Adressen können Tokens oder Namen stecken (`?token=…`). Vor der Anzeige fallen Abfrageteil und Fragment weg,
und lange Zeichenfolgen im Pfad werden gekürzt.
"""
import re
from collections import OrderedDict
from pathlib import Path

from django.conf import settings

#: Wie viel vom Ende jeder Logdatei gelesen wird (die Datei rotiert bei 5 MB).
MAX_BYTES = 3 * 1024 * 1024

_ZEILE = re.compile(
    r'^(?P<zeit>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[,.]?\d* \S+ csp: CSP-Verstoss: '
    r'(?P<regel>.*?) \| blockiert=(?P<blockiert>.*?) \| Seite=(?P<seite>.*?) \| Zeile=(?P<zeile>.*)$')
_LANG = re.compile(r'[A-Za-z0-9_\-]{24,}')


def logdateien():
    """Die Logdatei und ihre jüngste Sicherung (älteste zuerst), soweit vorhanden."""
    try:
        haupt = Path(settings.LOGGING['handlers']['file']['filename'])
    except (KeyError, TypeError):
        return []
    return [p for p in (haupt.with_name(haupt.name + '.1'), haupt) if p.is_file()]


def bereinigen(adresse):
    """Adresse ohne Abfrageteil und Fragment, lange Zeichenfolgen gekürzt (Tokens)."""
    a = (adresse or '').strip()
    a = a.split('#', 1)[0].split('?', 1)[0]
    return _LANG.sub('…', a)[:200]


def _hinteres_stueck(pfad):
    with open(pfad, 'rb') as f:
        f.seek(0, 2)
        groesse = f.tell()
        f.seek(max(0, groesse - MAX_BYTES))
        roh = f.read()
    return roh.decode('utf-8', errors='replace').splitlines()


def lesen(zeilen):
    """Fasst Logzeilen zusammen: gleiche Regel, gleiches Ziel, gleiche Seite = ein Eintrag mit Zähler."""
    gruppen = OrderedDict()
    for z in zeilen:
        m = _ZEILE.match(z)
        if not m:
            continue
        schluessel = (m['regel'].strip(), bereinigen(m['blockiert']), bereinigen(m['seite']))
        g = gruppen.get(schluessel)
        if g is None:
            gruppen[schluessel] = g = {
                'regel': schluessel[0], 'blockiert': schluessel[1], 'seite': schluessel[2],
                'anzahl': 0, 'zuerst': m['zeit'], 'zuletzt': m['zeit'], 'zeile': m['zeile'].strip()}
        g['anzahl'] += 1
        g['zuletzt'] = m['zeit']
    return sorted(gruppen.values(), key=lambda g: (-g['anzahl'], g['zuletzt']), reverse=False)


def uebersicht():
    """Alles, was die Seite braucht: Zusammenfassung, Zahl der Meldungen, Zustand der Quelle."""
    dateien = logdateien()
    zeilen = []
    for d in dateien:
        try:
            zeilen.extend(_hinteres_stueck(d))
        except OSError:
            continue
    eintraege = lesen(zeilen)
    return {
        'eintraege': eintraege,
        'gesamt': sum(e['anzahl'] for e in eintraege),
        'dateien': [d.name for d in dateien],
        'modus': getattr(settings, 'CSP_MODUS', 'report-only'),
    }
