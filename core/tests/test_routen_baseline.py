"""Keine bestehende Adresse und keine Seite geht verloren.

Die Datei `routen_baseline.txt` hält fest, welche Adressen (mit ihren Namen)
beim Umbau der Oberfläche (Mix-Entwurf, November 2026) bestanden. Dieser Test
schlägt fehl, wenn eine davon fehlt oder ihren Namen wechselt.

NEUE Adressen dürfen jederzeit hinzukommen; die Baseline wächst nur. Eine
Adresse darf nur mit Begründung in `ABSICHTLICH_ENTFERNT` stehen.
"""
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import get_resolver

BASELINE = Path(__file__).with_name('routen_baseline.txt')

#: Adresse -> Grund. Leer lassen, solange nichts bewusst entfällt.
ABSICHTLICH_ENTFERNT = {}


def _alle():
    def walk(patterns, prefix=''):
        for p in patterns:
            if hasattr(p, 'url_patterns'):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern), p.name
    return set(walk(get_resolver().url_patterns))


class RoutenBaselineTest(SimpleTestCase):
    def test_keine_adresse_geht_verloren(self):
        jetzt = _alle()
        fehlend = []
        for zeile in BASELINE.read_text().splitlines():
            url, _, name = zeile.partition('\t')
            if url in ABSICHTLICH_ENTFERNT:
                continue
            if (url, None if name in ('', 'None') else name) not in jetzt:
                fehlend.append(zeile)
        self.assertEqual(fehlend, [], 'Adressen aus der Baseline fehlen oder haben einen anderen Namen')

    def test_baseline_ist_nicht_leer(self):
        self.assertGreater(len(BASELINE.read_text().splitlines()), 500)
