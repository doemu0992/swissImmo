"""Die Abrechnungsperiode rechnet ohne Fremdpaket: ganze Monate, Tag auf das Monatsende geklemmt."""
from datetime import date

from django.test import SimpleTestCase

from abo.dienst import _plus_monate


class PlusMonateTests(SimpleTestCase):

    def test_monatsende_wird_geklemmt(self):
        self.assertEqual(_plus_monate(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(_plus_monate(date(2028, 1, 31), 1), date(2028, 2, 29))
        self.assertEqual(_plus_monate(date(2026, 3, 31), 1), date(2026, 4, 30))

    def test_jahreswechsel_und_zwoelf_monate(self):
        self.assertEqual(_plus_monate(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(_plus_monate(date(2026, 11, 15), 12), date(2027, 11, 15))
        self.assertEqual(_plus_monate(date(2028, 2, 29), 12), date(2029, 2, 28))

    def test_periode_bis_ist_der_tag_vor_dem_naechsten_beginn(self):
        from datetime import timedelta
        self.assertEqual(_plus_monate(date(2026, 11, 1), 1) - timedelta(days=1), date(2026, 11, 30))
