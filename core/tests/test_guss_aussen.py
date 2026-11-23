"""Fehlerseiten und Zwei-Faktor-Bestätigung «aus einem Guss» — der Browser-Testserver (DEBUG) zeigt sie nicht, darum hier.

Die übrigen Aussenseiten misst `e2e/tests/guss-aussen.spec.ts` am gerenderten Bild.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

VORLAGEN = Path(settings.BASE_DIR) / 'core' / 'templates'


class GussAussenTests(SimpleTestCase):
    def test_fehlerseiten_tragen_die_gemeinsame_klasse_und_keinen_eigenen_schatten(self):
        for name in ('400.html', '403.html', '404.html', '500.html', 'core/_passwort_shell_top.html'):
            text = (VORLAGEN / name).read_text()
            self.assertIn('fw-aussen-guss', text, name)
            self.assertNotIn('shadow-', text, name)

    def test_die_schicht_regelt_titel_karte_und_feld_der_aussenseiten(self):
        css = (Path(settings.BASE_DIR) / 'static' / 'css' / 'schicht.css').read_text()
        self.assertIn('html .fw-aussen-guss h1,html .fw-aussen-inhalt h1{font-family:var(--ds-disp);font-weight:700', css)
        self.assertIn('html .fw-aussen-guss .fw-flaeche.rounded-2xl{border-radius:var(--ds-radius);box-shadow:none', css)
        self.assertRegex(css, r'html \.fw-aussen-guss input[^{]*\{height:40px')

    def test_zwei_faktor_bestaetigung_titelschrift_pille_und_kein_schatten(self):
        text = (VORLAGEN / 'core' / 'zweifaktor_bestaetigen.html').read_text()
        self.assertIn('h1 { font-family:var(--ds-disp); font-size:24px; font-weight:700', text)
        self.assertIn('border-radius:var(--ds-pill)', text)
        self.assertIn('height:40px', text)
        self.assertNotIn('box-shadow:var(--ds-shadow)', text)
