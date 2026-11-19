"""Kennzahlen sind überall eine Statuszeile (UI-Zielbild), ausser den grossen Zahlen auf Finanzen.

`.fw-kpis` wird in der Stilschicht zur Kapselzeile (Modul «Kennzahlen als Statuszeile»). Die einzige Ausnahme ist `.fw-gross`:
die Kontostände und der Abschluss-Block auf Finanzen, die auch im Zielbild Kacheln sind. Wer an anderer Stelle `fw-gross` setzt,
umgeht den Standard, und dieser Test sagt es.
"""
import pathlib

from django.test import SimpleTestCase

WURZEL = pathlib.Path(__file__).resolve().parents[2]
VORLAGEN = WURZEL / 'core' / 'templates'
ERLAUBT = {'fw/finanzen.html'}


class StatuszeileStandardTests(SimpleTestCase):
    def test_nur_finanzen_darf_grosse_kennzahlen_zeigen(self):
        gefunden = set()
        for datei in VORLAGEN.rglob('*.html'):
            rel = datei.relative_to(VORLAGEN).as_posix()
            if rel == 'fw/_schicht.html':
                continue
            if 'fw-gross' in datei.read_text(encoding='utf-8'):
                gefunden.add(rel)
        self.assertEqual(gefunden - ERLAUBT, set(),
                         'Grosse Kennzahlkacheln sind nur auf Finanzen erlaubt (Zielbild). Alles andere ist eine Statuszeile.')

    def test_das_modul_steht_in_der_stilschicht(self):
        schicht = (VORLAGEN / 'fw' / '_schicht.html').read_text(encoding='utf-8')
        self.assertIn('MODUL Kennzahlen als Statuszeile', schicht)
        self.assertIn('.fw-kpis:not(.fw-gross)', schicht)
