"""IDs aus Formular und Querystring (`core/utils/formularid.py`, SICH-01 / SICH-14).

Der Helfer ist die eine Stelle, an der eine mitgeschickte ID zum Objekt der EIGENEN
Verwaltung wird — oder zu `None`. Ein 500 darf er nie auslösen: Eine 20-stellige ID
liess `INSERT` auf PostgreSQL mit `DataError` scheitern (`pgfuzz_ids.json`).

GEGENPROBE: `ganzzahl` ohne die Grenze `_MAX_ID` → `test_zu_gross…` rot;
`eigenes_objekt` mit `alle_organisationen` statt `objects` → `test_fremdes_objekt…` rot.
"""
from django.test import TestCase

from core.tenancy import organisation_kontext
from core.utils.formularid import eigenes_objekt, ganzzahl

from ._isolation import MandantenFixture


class GanzzahlTests(TestCase):

    def test_gueltige_ids(self):
        for roh, erwartet in (('1', 1), (' 42 ', 42), (7, 7), ('9223372036854775807', 2 ** 63 - 1)):
            with self.subTest(roh=roh):
                self.assertEqual(ganzzahl(roh), erwartet)

    def test_alles_andere_ist_none_und_wirft_nie(self):
        for roh in (None, '', ' ', 'abc', '1.5', '-1', '0', '1e3', '１２', '²', '١٢', '1 2', '1;2',
                    '9223372036854775808', '99999999999999999999', 0, -4, 1.5):
            with self.subTest(roh=roh):
                self.assertIsNone(ganzzahl(roh))

    def test_zu_gross_ist_none(self):
        self.assertIsNone(ganzzahl(str(2 ** 63)))


class EigenesObjektTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_eigenes_objekt_wird_gefunden(self):
        from portfolio.models import Liegenschaft
        with organisation_kontext(self.a.organisation):
            self.assertEqual(eigenes_objekt(Liegenschaft, str(self.a.liegenschaft.pk)), self.a.liegenschaft)

    def test_fremdes_objekt_ist_none(self):
        from portfolio.models import Liegenschaft
        with organisation_kontext(self.a.organisation):
            self.assertIsNone(eigenes_objekt(Liegenschaft, self.b.liegenschaft.pk))

    def test_zusaetzliche_bedingung_wird_beachtet(self):
        from portfolio.models import Einheit
        with organisation_kontext(self.a.organisation):
            self.assertEqual(eigenes_objekt(Einheit, self.a.einheit.pk, liegenschaft=self.a.liegenschaft),
                             self.a.einheit)
            self.assertIsNone(eigenes_objekt(Einheit, self.a.einheit.pk, liegenschaft=self.b.liegenschaft))

    def test_unsinn_ist_none_statt_fehler(self):
        from portfolio.models import Liegenschaft
        with organisation_kontext(self.a.organisation):
            for roh in ('abc', '', None, '99999999999999999999'):
                self.assertIsNone(eigenes_objekt(Liegenschaft, roh))
