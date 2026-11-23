"""Formulare «aus einem Guss»: Der Fuss eines Seitenformulars ist `.fw-formular-fuss` (Abbrechen, dann Hauptknopf rechts).

Gemessen 23.11.2026: Hauptknopf in 25 Seitenformularen links, in 8 rechts. Das Bild prüft `e2e/tests/guss-formulare.spec.ts`;
dieser Test fängt neue handgebaute Knopfreihen schon im Quelltext.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

FW = Path(settings.BASE_DIR) / 'core' / 'templates' / 'fw'
#: Reihen, die kein Formularfuss sind (Kopieren-Knopf mit Rückweg).
AUSNAHMEN = {'auftrag_link.html'}


class FormularFussTests(SimpleTestCase):
    def test_keine_handgebaute_knopfreihe_mit_hauptknopf_und_abbrechen(self):
        befunde = []
        for datei in sorted(FW.rglob('*.html')):
            if datei.name in AUSNAHMEN or datei.name.startswith('_schicht'):
                continue
            zeilen = datei.read_text().split('\n')
            for i, zeile in enumerate(zeilen):
                if not re.search(r'<div class="[^"]*\bflex\b[^"]*"', zeile) or 'justify-end' in zeile or 'items-end' in zeile:
                    continue
                block = ' '.join(zeilen[i:i + 5])
                if 'fw-btn fw-primary' in block and re.search(r'>\s*\{% trans "Abbrechen" %\}|>Abbrechen<', block):
                    befunde.append(f'{datei.name}:{i + 1}')
        self.assertEqual(befunde, [], 'Knopfreihe als .fw-formular-fuss bauen (CONTRIBUTING.md, «Formulare»)')

    def test_die_schicht_ordnet_abbrechen_links_und_den_hauptknopf_rechts(self):
        css = (Path(settings.BASE_DIR) / 'static' / 'css' / 'schicht.css').read_text()
        self.assertIn('.fw-formular-fuss>.fw-geist{order:-1}', css)
        self.assertIn('.fw-formular-fuss>.fw-primary{order:9}', css)
        self.assertIn('.fw-lesebreite{max-width:920px}', css)

    def test_der_hauptknopf_bleibt_im_quelltext_der_erste_absendeknopf(self):
        """Enter in einem Feld löst den ersten Absendeknopf aus: «Frist ansetzen», nicht «Zusätzlich als PDF öffnen»."""
        for name, erster in (('verzug_257d.html', 'Frist ansetzen'), ('schlussabrechnung.html', 'Schlussabrechnung als PDF')):
            text = (FW / name).read_text()
            fuss = text[text.rindex('fw-formular-fuss'):]
            knopf = re.search(r'<button type="submit"[^>]*>(.*?)</button>', fuss, re.S)
            self.assertIn(erster, knopf.group(1), name)
            self.assertIn('fw-primary', knopf.group(0), name)
