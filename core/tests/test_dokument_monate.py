"""Monatsnamen in Mahnungs-E-Mail und Mahnbrief.

`strftime('%B')` richtet sich nach der Server-Locale und lieferte auf dem
Server englische Monate («May 2024») in einem deutschen Dokument. Bis die
Dokumente der Sprache des Empfängers folgen (D11), sind sie durchgehend
Deutsch — unabhängig von der Sprache der angemeldeten Person.
"""
import datetime
import tempfile
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import translation


def _vertrag():
    mieter = SimpleNamespace(id=7, vorname='Anna', nachname='Muster', email='anna@example.ch',
                             strasse='Weg 1', plz='3000', ort='Bern', anrede='Frau')
    liegenschaft = SimpleNamespace(strasse='Weg 1')
    einheit = SimpleNamespace(bezeichnung='3.5 Zi. EG', liegenschaft=liegenschaft)
    return SimpleNamespace(id=11, mieter=mieter, einheit=einheit)


class MahnungsMailMonatTests(SimpleTestCase):
    def test_betreff_nennt_den_monat_deutsch(self):
        from core.utils import email_service
        with mock.patch.object(email_service.threading, 'Thread') as thread, \
                translation.override('en'):
            email_service.send_payment_reminder(_vertrag(), datetime.date(2024, 5, 1), Decimal('1500'))
        betreff = thread.call_args.kwargs['args'][1]
        self.assertIn('Mai 2024', betreff)
        self.assertNotIn('May', betreff)


class MahnbriefMonatTests(SimpleTestCase):
    def test_datum_im_brief_ist_deutsch(self):
        from core.utils import qr_code
        verwaltung = SimpleNamespace(firma='Verwaltung AG', strasse='Gasse 2', plz='3000',
                                     ort='Bern', iban='CH9300762011623852957')
        jetzt = datetime.datetime(2024, 5, 3, 10, 0, tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp), \
                mock.patch.object(qr_code.canvas, 'Canvas') as leinwand, \
                mock.patch.object(qr_code.timezone, 'now', return_value=jetzt), \
                translation.override('en'):
            try:
                qr_code.generate_mahnung_pdf(_vertrag(), Decimal('1500'), verwaltung)
            except Exception:
                pass  # Nur der gezeichnete Text zählt, nicht der Rest der Seite.
        texte = [str(a.args[2]) for a in leinwand.return_value.drawString.call_args_list]
        self.assertIn('Bern 03. Mai 2024', texte)
        self.assertFalse([t for t in texte if 'May' in t])
