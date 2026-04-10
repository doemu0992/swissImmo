# rentals/tests.py
from django.test import TestCase
from decimal import Decimal
from unittest.mock import MagicMock

# Neuer, sauberer Import aus dem Service!
from rentals.services import berechne_mietpotenzial

class MietrechtLogicTests(TestCase):

    def setUp(self):
        self.dummy_vertrag = MagicMock()
        self.dummy_vertrag.mieter = "Max Mustermann"
        self.dummy_vertrag.einheit = "Wohnung 1"
        self.dummy_vertrag.basis_referenzzinssatz = Decimal('1.25')
        self.dummy_vertrag.basis_lik_punkte = Decimal('100.0')
        self.dummy_vertrag.netto_mietzins = Decimal('1000.00')

    def test_fehlende_basisdaten(self):
        self.dummy_vertrag.basis_referenzzinssatz = None
        ergebnis = berechne_mietpotenzial(self.dummy_vertrag, Decimal('1.5'), Decimal('100.0'))
        self.assertIsNone(ergebnis)

    def test_zins_erhoehung(self):
        ergebnis = berechne_mietpotenzial(self.dummy_vertrag, Decimal('1.50'), Decimal('100.0'))
        self.assertEqual(ergebnis['action'], 'UP')
        self.assertEqual(ergebnis['delta_prozent'], Decimal('3.00'))
        self.assertEqual(ergebnis['neu_chf'], Decimal('1030.00'))

    def test_zins_senkung(self):
        self.dummy_vertrag.basis_referenzzinssatz = Decimal('1.50')
        ergebnis = berechne_mietpotenzial(self.dummy_vertrag, Decimal('1.25'), Decimal('100.0'))
        self.assertEqual(ergebnis['action'], 'DOWN')
        self.assertEqual(ergebnis['delta_prozent'], Decimal('-2.91'))
        self.assertEqual(ergebnis['neu_chf'], Decimal('970.90'))

    def test_allgemeine_kostensteigerung(self):
        """Testet die Weitergabe der allgemeinen Kosten (z.B. pauschal 0.5%)"""
        # Zins und LIK bleiben gleich, aber wir geben 0.5% Kostensteigerung an
        ergebnis = berechne_mietpotenzial(
            self.dummy_vertrag,
            Decimal('1.25'),
            Decimal('100.0'),
            allg_kosten_pct=Decimal('0.5')
        )
        self.assertEqual(ergebnis['delta_prozent'], Decimal('0.50'))
        self.assertEqual(ergebnis['neu_chf'], Decimal('1005.00'))

    def test_vollstaendige_kombination(self):
        """Testet Zins + LIK + Allg. Kosten zusammen"""
        # Refzins +0.25% (= 3.00%)
        # LIK +5% -> 40% davon (= 2.00%)
        # Allg. Kosten = 0.5%
        # Total = 5.50%
        ergebnis = berechne_mietpotenzial(
            self.dummy_vertrag,
            Decimal('1.50'),
            Decimal('105.0'),
            allg_kosten_pct=Decimal('0.5')
        )
        self.assertEqual(ergebnis['delta_prozent'], Decimal('5.50'))
        self.assertEqual(ergebnis['neu_chf'], Decimal('1055.00'))