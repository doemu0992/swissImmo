"""Kennzahlen stehen sofort im Endwert (UI-Zielbild, Phase 0, Befund 1): kein Hochzählen.

Wer eine Zahl liest, soll nicht warten, bis sie stimmt; ein Bild, das in der Mitte der Animation entsteht (Screenshot,
Bericht, langsames Telefon), zeigt sonst eine falsche Zahl. Der Wächter liest die Quelle: Das Skript der Kapsel darf keine
Zahl verändern.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)


class KennzahlenSofortTests(SimpleTestCase):

    def test_das_skript_zaehlt_nicht_hoch(self):
        text = (WURZEL / 'static/js/fw-kapsel.js').read_text(encoding='utf-8')
        for merkmal in ('toFixed', 'textContent', 'data-zaehlen', 'fmt('):
            self.assertNotIn(merkmal, text, f'fw-kapsel.js verändert wieder Zahlen ({merkmal}): kein Hochzählen')

    def test_keine_vorlage_markiert_zahlen_zum_hochzaehlen(self):
        treffer = [p.relative_to(WURZEL).as_posix() for p in (WURZEL / 'core/templates').rglob('*.html')
                   if re.search(r'data-zaehlen\b', p.read_text(encoding='utf-8'))]
        self.assertEqual(treffer, [], 'data-zaehlen steht noch in Vorlagen')

    def test_die_lastbalken_bleiben(self):
        """Gegenprobe: Nur das Hochzählen ist weg, die Breite der Lastbalken wird weiter gesetzt."""
        text = (WURZEL / 'static/js/fw-kapsel.js').read_text(encoding='utf-8')
        self.assertIn('.fw-lastbalken[data-w]', text)
