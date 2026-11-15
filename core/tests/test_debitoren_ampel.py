"""Die Ampel «Bezahlt» zählt nur — ohne Summenabfrage über die ganze Historie (Audit P12).

Gegenprobe (15.11.2026): `mit_summe=False` entfernt -> der Test wird rot (die Unterabfrage ist wieder da).
"""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.tenancy import organisation_kontext
from finance.models import DebitorenRechnung

from ._isolation import MandantenFixture


class DebitorenAmpelTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_bezahlte_werden_nur_gezaehlt(self):
        with organisation_kontext(self.a.organisation):
            bezahlt = DebitorenRechnung.objects.filter(status='bezahlt').count()
        self.client.force_login(self.a.benutzer)
        with CaptureQueriesContext(connection) as c:
            antwort = self.client.get('/neu/debitoren/')
        self.assertEqual(antwort.status_code, 200)
        gruen = {k: z for k, _label, z, _h in antwort.context['ampeln']}['gruen']
        self.assertEqual(gruen['n'], bezahlt)
        zu_bezahlten = [q['sql'] for q in c.captured_queries
                        if '"status" = \'bezahlt\'' in q['sql'] and 'core_zahlungseingang' in q['sql']]
        self.assertEqual(zu_bezahlten, [])

    def test_die_offenen_ampeln_tragen_weiter_ihre_summe(self):
        from datetime import date
        from decimal import Decimal
        with organisation_kontext(self.a.organisation):
            DebitorenRechnung.objects.create(vertrag=self.a.vertrag, titel='Ampelprobe', betrag=Decimal('250'),
                                             datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31), status='offen')
        self.client.force_login(self.a.benutzer)
        ampeln = {k: z for k, _label, z, _h in self.client.get('/neu/debitoren/').context['ampeln']}
        self.assertEqual(ampeln['rot']['summe'], Decimal('250'))
