"""Kaufmännische Rundung auf Rappen (Audit F7): halbe Rappen werden aufgerundet, nicht zur geraden Zahl.

Pythons `round(Decimal('0.125'), 2)` ergibt 0.12 (Banker-Rundung); eine Schweizer Rechnung rundet 0.13.
"""
import pathlib
import re
from decimal import Decimal

from django.test import SimpleTestCase

from core.utils.betrag import runde_rappen


class RundeRappenTests(SimpleTestCase):

    def test_halbe_rappen_werden_aufgerundet(self):
        for roh, soll in (('0.125', '0.13'), ('0.135', '0.14'), ('2.675', '2.68'), ('1.005', '1.01'), ('0.115', '0.12')):
            self.assertEqual(runde_rappen(Decimal(roh)), Decimal(soll), roh)

    def test_gegenprobe_python_round_ist_banker(self):
        """Warum es den Helfer braucht: das eingebaute `round` liefert hier das Falsche."""
        self.assertEqual(round(Decimal('0.125'), 2), Decimal('0.12'))
        self.assertEqual(round(Decimal('0.135'), 2), Decimal('0.14'))

    def test_negative_halbe_rappen_runden_von_null_weg(self):
        self.assertEqual(runde_rappen(Decimal('-0.125')), Decimal('-0.13'))

    def test_normale_werte_und_zwei_nachkommastellen(self):
        self.assertEqual(runde_rappen(Decimal('12.3')), Decimal('12.30'))
        self.assertEqual(str(runde_rappen(Decimal('100'))), '100.00')
        self.assertEqual(runde_rappen(Decimal('1.004')), Decimal('1.00'))

    def test_andere_zahlen_gehen_unveraendert_durch_round(self):
        self.assertEqual(runde_rappen(1.234), 1.23)
        self.assertEqual(runde_rappen(5), 5)


class KeinBankerRundenInDerAbrechnungTests(SimpleTestCase):
    def test_abrechnung_und_sollstellung_runden_nur_ueber_den_helfer(self):
        """In diesen beiden Dateien steht kein `round(…, 2)` mehr: Es würde Beträge halbe-Rappen-gerade runden."""
        wurzel = pathlib.Path(__file__).resolve().parents[2]
        for rel in ('core/utils/billing.py', 'core/services/automation.py'):
            text = (wurzel / rel).read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'(?<![\w.])round\(', text), f'{rel}: eingebautes round() statt runde_rappen()')
