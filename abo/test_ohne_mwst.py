"""Der Betreiber ist nicht mehrwertsteuerpflichtig: Die Rechnung weist keine MWST aus und sagt das."""
import io
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from abo import dienst
from abo.models import Abonnement
from abo.rechnung_pdf import abo_rechnung_pdf
from core.tests._helfer import _test_organisation

STELLER = {'name': 'Dominik Gerber', 'strasse': 'Selzacherstrasse 4', 'plz': '4512', 'ort': 'Bellach',
           'iban': 'CH8280808001171590915', 'uid': '', 'email': 'info@immoswiss.app'}


def _text(pdf):
    from pypdf import PdfReader
    return ' '.join(s.extract_text() for s in PdfReader(io.BytesIO(pdf)).pages)


class OhneMwstTests(TestCase):

    def setUp(self):
        self.org = _test_organisation()
        self.abo = Abonnement.alle_organisationen.get_or_create(organisation=self.org,
                                                                defaults={'abrechnung_ab': date(2026, 11, 1)})[0]
        self.abo.abrechnung_ab = date(2026, 11, 1)
        self.abo.save()

    def _rechnung(self):
        return dienst.rechnung_stellen(self.org, self.abo, heute=date(2026, 11, 9))

    @override_settings(ABO_PREISE_FESTGELEGT=True, ABO_MWST_PFLICHTIG=False, ABO_MWST_SATZ=None, ABO_RECHNUNGSSTELLER=STELLER)
    def test_rechnung_ohne_mwst_und_pdf_sagt_es(self):
        r = self._rechnung()
        self.assertEqual((r.mwst_satz, r.mwst_betrag, r.brutto), (None, Decimal('0.00'), r.netto))
        text = _text(abo_rechnung_pdf(r))
        self.assertIn('Nicht mehrwertsteuerpflichtig', text)
        self.assertNotIn('nicht festgelegt', text)
        self.assertIn('Dominik Gerber', text)

    @override_settings(ABO_PREISE_FESTGELEGT=True, ABO_MWST_PFLICHTIG=True, ABO_MWST_SATZ=None, ABO_RECHNUNGSSTELLER=STELLER)
    def test_pflichtig_aber_ohne_satz_bleibt_ein_offener_punkt(self):
        text = _text(abo_rechnung_pdf(self._rechnung()))
        self.assertIn('nicht festgelegt', text)

    @override_settings(ABO_PREISE_FESTGELEGT=True, ABO_MWST_PFLICHTIG=True, ABO_MWST_SATZ=Decimal('8.1'),
                       ABO_RECHNUNGSSTELLER={**STELLER, 'uid': 'CHE-123.456.789 MWST'})
    def test_pflichtig_mit_satz_weist_mwst_und_uid_aus(self):
        r = self._rechnung()
        self.assertEqual(r.mwst_betrag, Decimal('9.64'))
        text = _text(abo_rechnung_pdf(r))
        self.assertIn('MWST 8.1 %', text)
        self.assertIn('CHE-123.456.789 MWST', text)
