"""Finanzen: Periodenabschluss (UI-Zielbild, Phase 0, Befund 8 und 11).

Der Titel «Periodenabschluss» steht einmal (die Kennzahl daneben heisst «Abschluss»), und erledigte Schritte der Checkliste
sind mit einem Haken markiert statt durchgestrichen: Durchgestrichen liest sich wie «gestrichen» oder «storniert».
"""
import re

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user


class FinanzenAbschlussDarstellungTests(TestCase):

    def setUp(self):
        _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.html = self.c.get('/neu/finanzen/').content.decode()

    def test_der_titel_steht_einmal(self):
        treffer = re.findall(r'>\s*Periodenabschluss\s*<', self.html)
        self.assertEqual(len(treffer), 1, f'«Periodenabschluss» steht {len(treffer)}-mal als Titel')

    def test_erledigte_schritte_sind_nicht_durchgestrichen(self):
        """Die Vorlage streicht nichts durch; in den Testdaten ist kein Schritt erledigt, deshalb wird die Quelle gelesen."""
        import pathlib
        from django.conf import settings
        quelle = (pathlib.Path(settings.BASE_DIR) / 'core/templates/fw/finanzen.html').read_text(encoding='utf-8')
        self.assertNotIn('line-through', quelle)
        self.assertIn("{% zeichen 'gut' %}", quelle)

    def test_die_checkliste_ist_da(self):
        """Gegenprobe: Die Karte ist nicht einfach verschwunden."""
        self.assertIn('Reihenfolge = empfohlener Ablauf', self.html)
