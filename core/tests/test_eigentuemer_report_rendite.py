"""Eigentümer-Report: die Rendite kommt aus `rendite.py`, nicht aus dem Versicherungswert.

Befund (Analysebericht 06.11.2026): `_portfolio_daten` teilte die Jahresmiete inklusive Nebenkosten durch den
Gebäudeversicherungswert. In der Verwaltung stand für dieselbe Liegenschaft unter demselben Namen «Bruttorendite» eine
andere Zahl (Netto-Sollmiete durch Verkehrswert bzw. Anlagekosten, `rendite.py`). Der Versicherungswert taugt als Nenner
nicht; fehlt ein Wert, gibt es jetzt keine Rendite statt einer Näherung.

Gegenproben: in `_portfolio_daten` die Rendite wieder aus `vw` rechnen -> `test_ohne_wert_keine_rendite` rot; die
Gesamtrendite wieder durch `total_versicherungswert` teilen -> `test_mit_verkehrswert_*` rot.
"""
from decimal import Decimal
from io import BytesIO

from django.test import TestCase

from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture


class ReportRenditeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _daten(self):
        from core.views.portal import _portfolio_daten
        with organisation_kontext(self.a.organisation):
            return _portfolio_daten(self.a.eigentuemer)

    def _setze(self, **felder):
        lg = self.a.liegenschaft
        for k, v in felder.items():
            setattr(lg, k, v)
        lg.save(update_fields=list(felder))

    def test_ohne_wert_keine_rendite(self):
        """Der Versicherungswert (1 Mio. in der Fixture) darf keine Rendite mehr ergeben."""
        self.assertEqual(self.a.liegenschaft.versicherungswert, Decimal('1000000'))
        self.assertFalse(self.a.liegenschaft.verkehrswert)
        self.assertFalse(self.a.liegenschaft.anlagekosten)
        daten = self._daten()
        self.assertIsNone(daten['bruttorendite'])
        self.assertIsNone(daten['liegenschaften'][0]['rendite'])
        self.assertEqual(daten['rendite_ohne_wert'], 1)

    def test_mit_verkehrswert_rechnet_sie_wie_die_verwaltung(self):
        from core.services.portfolio_kennzahlen import uebersicht
        from core.services.rendite import liegenschaft_renditen
        self._setze(verkehrswert=Decimal('2000000'))
        daten = self._daten()
        with organisation_kontext(self.a.organisation):
            r = liegenschaft_renditen([self.a.liegenschaft])[self.a.liegenschaft.pk]
            verwaltung = uebersicht([self.a.liegenschaft])['zeilen'][0]['brutto']
        self.assertGreater(r['jahres_netto'], 0, 'die Fixture hat keine Miete: Test prüft nichts')
        erwartet = float(r['jahres_netto']) / 2000000 * 100
        self.assertAlmostEqual(daten['liegenschaften'][0]['rendite'], erwartet, places=6)
        self.assertAlmostEqual(daten['bruttorendite'], erwartet, places=6)
        self.assertAlmostEqual(daten['liegenschaften'][0]['rendite'], verwaltung, places=6,
                               msg='Report und Verwaltung zeigen verschiedene Zahlen unter demselben Namen')
        self.assertEqual(daten['rendite_ohne_wert'], 0)

    def test_ersatzweise_anlagekosten(self):
        self._setze(anlagekosten=Decimal('1500000'))
        daten = self._daten()
        self.assertIsNotNone(daten['bruttorendite'])

    def test_der_pdf_report_nennt_es_ehrlich(self):
        """Ohne Wert steht «nicht berechenbar» und die Erklärung, nicht eine Zahl."""
        from pypdf import PdfReader

        from core.services import portfolio_report
        with organisation_kontext(self.a.organisation):
            pdf = portfolio_report.generate_portfolio_report_fuer(self.a.eigentuemer)
        text = ' '.join(seite.extract_text() for seite in PdfReader(BytesIO(pdf)).pages)
        self.assertIn('nicht berechenbar', text)
        self.assertIn('Verkehrswert', text)
        self.assertNotIn('Gebäudeversicherungswert', text)
