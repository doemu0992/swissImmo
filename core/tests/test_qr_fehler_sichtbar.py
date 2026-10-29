"""Ein misslungener Einzahlungsschein darf nicht still verschwinden (Audit FIN-11).

Drei Stellen verschluckten den Fehler beim Zeichnen der QR-Rechnung: das Mahnschreiben
(`except Exception: pass`), die NK-Abrechnung in `email_views` (`except: pass`) und die
NK-Abrechnung in `billing` (`print`). Das Schreiben ging dann OHNE Einzahlungsschein
hinaus, und niemand erfuhr davon.

Jetzt: Protokolleintrag und Abbruch. Die View liefert eine Absage statt eines PDF.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from ._isolation import MandantenFixture

IBAN = 'CH9300762011623852957'


class QrFehlerSichtbarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        lg = cls.a.liegenschaft
        lg.iban = IBAN
        lg.save()

    def _zeile(self):
        return {'typ': 'mieter', 'name': 'Mieter A', 'einheit': '3.5 Zi', 'kosten_anteil': Decimal('800'),
                'akonto': Decimal('500'), 'saldo': Decimal('300'), 'nachzahlung': True}

    def test_nk_pdf_view_liefert_absage_statt_pdf_ohne_schein(self):
        self.client.force_login(self.a.benutzer)
        ergebnis = {'abrechnungen': [self._zeile()]}
        with mock.patch('core.views.billing.hole_abrechnung', return_value=ergebnis), \
                mock.patch('core.views.billing.draw_qr_bill', side_effect=ValueError('IBAN ungültig')), \
                self.assertLogs('core.views.billing', level='ERROR') as log:
            antwort = self.client.get(f'/abrechnung/{self.a.periode.pk}/pdf/')
        self.assertEqual(antwort.status_code, 500)
        self.assertIn('QR-Rechnung', antwort.content.decode())
        self.assertNotEqual(antwort['Content-Type'], 'application/pdf')
        self.assertTrue(any('nicht erzeugt' in z for z in log.output))

    def test_nk_pdf_view_ohne_fehler_liefert_pdf(self):
        self.client.force_login(self.a.benutzer)
        ergebnis = {'abrechnungen': [self._zeile()]}
        with mock.patch('core.views.billing.hole_abrechnung', return_value=ergebnis):
            antwort = self.client.get(f'/abrechnung/{self.a.periode.pk}/pdf/')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort['Content-Type'], 'application/pdf')

    def test_nk_einzelpdf_wirft_und_protokolliert(self):
        from core.views.email_views import generate_single_pdf_bytes
        zeile = dict(self._zeile(), nachzahlung=True)
        with mock.patch('core.views.email_views.draw_qr_bill', side_effect=ValueError('kaputt')), \
                self.assertLogs('core.views.email_views', level='ERROR') as log:
            with self.assertRaises(ValueError):
                generate_single_pdf_bytes(self.a.periode, zeile, self.a.organisation,
                                          self.a.liegenschaft, self.a.vertrag)
        self.assertTrue(any('nicht erzeugt' in z for z in log.output))

    def test_mahnschreiben_wirft_und_protokolliert(self):
        from core.services.mahnbrief import mahnbrief_pdf
        with mock.patch('core.utils.qr_code.draw_qr_bill', side_effect=ValueError('kaputt')), \
                self.assertLogs('core.services.mahnbrief', level='ERROR') as log:
            with self.assertRaises(ValueError):
                mahnbrief_pdf(self.a.vertrag, self.a.organisation, stufe=1, monat='März 2026',
                              betrag='1700.00', datum=date(2026, 3, 20), letzte_stufe=False)
        self.assertTrue(any('nicht erzeugt' in z for z in log.output))
