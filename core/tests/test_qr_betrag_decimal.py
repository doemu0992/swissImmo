"""QR-Betrag ohne float; genau eine Definition von `ist_qr_iban`."""
from decimal import Decimal

from django.test import SimpleTestCase

from core.services import iban as iban_modul
from core.utils import qr_code


class QrBetragTests(SimpleTestCase):
    def test_kaufmaennisch_gerundet_nicht_gerade_auf_float(self):
        self.assertEqual(qr_code.betrag_payload(Decimal('0.125')), '0.13')    # f"{0.125:.2f}" gäbe 0.12
        self.assertEqual(qr_code.betrag_payload(Decimal('1234.5')), '1234.50')
        self.assertEqual(qr_code.betrag_payload(119), '119.00')

    def test_ohne_betrag_bleibt_das_feld_leer(self):
        self.assertEqual(qr_code.betrag_payload(None), '')


class EineDefinitionTests(SimpleTestCase):
    def test_qr_iban_prueft_in_beiden_modulen_gleich(self):
        self.assertIs(qr_code.ist_qr_iban, iban_modul.ist_qr_iban)
        self.assertFalse(qr_code.ist_qr_iban('CH82'))                          # zu kurz: die alte lockere Fassung sagte True/False je Länge
        self.assertTrue(qr_code.ist_qr_iban('CH44 3199 9123 0008 8901 2'))
        self.assertFalse(qr_code.ist_qr_iban('CH82 8080 8001 1715 9091 5'))    # normale IBAN
