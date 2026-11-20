"""Endpunkt des Liniendiagramms nennt den Datenstand (UI-Zielbild)."""
from django.test import SimpleTestCase

from core.templatetags.diagramm import linien_diagramm


class DiagrammStandTests(SimpleTestCase):
    WERTE = [100.0, 100.0, 66.7]
    MONATE = ['Sep', 'Okt', 'Nov']

    def test_stand_steht_in_klammern_hinter_dem_endwert(self):
        html = linien_diagramm(self.WERTE, self.MONATE, 'Quote', stand='Stand Bankimport 26.10.')
        self.assertIn('(Stand Bankimport 26.10.)', html)

    def test_ohne_stand_bleibt_der_endwert_unveraendert(self):
        html = linien_diagramm(self.WERTE, self.MONATE, 'Quote')
        self.assertNotIn('(', html.split('fw-kurve-wert')[1].split('</span>')[0])
