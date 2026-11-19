"""«Heute» nach UI-Zielbild: Segment, Statuszeile, Dringlichkeitsgruppen, Aufgabenknopf, ✓.

Reine Darstellung: Der Arbeitsvorrat bleibt dieselbe Liste (`faelle/arbeitsvorrat.py`), nur gruppiert und mit Knöpfen, die die Aufgabe nennen.
"""
from django.test import SimpleTestCase

from core.views.fw.dashboard import FESTGEFAHREN_TAGE, _dringlichkeitsgruppen
from faelle.arbeitsvorrat import LAUF_AKTION


class DringlichkeitsgruppenTests(SimpleTestCase):
    def _e(self, tage, name):
        return {'tage': tage, 'titel': name}

    def test_ueberfaellig_vor_festgefahren_vor_dem_rest(self):
        vorrat = [self._e(5, 'später'), self._e(-90, 'alt'), self._e(-2, 'frisch'), self._e(0, 'heute'), self._e(None, 'ohne')]
        r = _dringlichkeitsgruppen(vorrat, 'heute')
        self.assertEqual([e['titel'] for e in r], ['frisch', 'alt', 'später', 'heute', 'ohne'])
        self.assertEqual([e['gruppe'] for e in r], ['ueber', 'lang', '', '', ''])

    def test_die_grenze_liegt_bei_dreissig_tagen(self):
        r = _dringlichkeitsgruppen([self._e(-FESTGEFAHREN_TAGE, 'a'), self._e(-FESTGEFAHREN_TAGE - 1, 'b')], 'woche')
        self.assertEqual({e['titel']: e['gruppe'] for e in r}, {'a': 'ueber', 'b': 'lang'})

    def test_andere_ansichten_bleiben_ungruppiert(self):
        vorrat = [self._e(5, 'a'), self._e(-90, 'b')]
        self.assertEqual(_dringlichkeitsgruppen(vorrat, 'alle'), vorrat)
        self.assertNotIn('gruppe', vorrat[0])

    def test_die_laufknoepfe_nennen_die_aufgabe(self):
        self.assertEqual(str(LAUF_AKTION['bankabgleich']), 'Importieren')
        self.assertEqual(str(LAUF_AKTION['sollstellung']), 'Auslösen')
