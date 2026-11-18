"""Eine MWST-Periode für den ganzen Bestand und eine für eine Liegenschaft schliessen sich aus.

Audit 17.11.2026 (F3): `_mwst_bereits_verbucht` suchte mit Liegenschaftsfilter nur Buchungen DIESER Liegenschaft. Wer
zuerst gesamt verbuchte und danach mit Liegenschaftsfilter, umging die Sperre: Konto 2201 stand auf 1'000 statt 500.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from ._helfer import _basis_objekte, _seed_konten


class MwstUeberlappungTests(TestCase):

    def setUp(self):
        from portfolio.models import Liegenschaft
        _seed_konten()
        self.lg, _e, _m, _v = _basis_objekte()
        self.lg2 = Liegenschaft.objects.create(strasse='Zweite 2', plz='8001', ort='Zürich',
                                               organisation=self.lg.organisation, versicherungswert=Decimal('1'))

    def _verbuche(self, liegenschaft, jahr=2026, quartal=''):
        from core.views.fw._basis import _mwst_beleg
        from finance.booking import buche
        buche('2200', '2201', Decimal('500.00'), f"{_mwst_beleg(jahr, quartal)} — Zahllast ESTV",
              datum=date(jahr, 12, 31), liegenschaft=liegenschaft)

    def _verbucht(self, liegenschaft, quartal=''):
        from core.views.fw._basis import _mwst_bereits_verbucht
        return _mwst_bereits_verbucht(2026, quartal, liegenschaft)

    def test_gesamt_verbucht_blockiert_die_einzelne_liegenschaft(self):
        self._verbuche(None)
        self.assertTrue(self._verbucht(self.lg), 'Nach der Gesamtabrechnung ist die Liegenschaft noch frei')
        self.assertTrue(self._verbucht(None))

    def test_einzelne_liegenschaft_blockiert_die_gesamtabrechnung(self):
        self._verbuche(self.lg)
        self.assertTrue(self._verbucht(None), 'Die Gesamtabrechnung doppelt die Liegenschaft')
        self.assertTrue(self._verbucht(self.lg))

    def test_gegenprobe_andere_liegenschaft_und_andere_periode_bleiben_frei(self):
        self._verbuche(self.lg)
        self.assertFalse(self._verbucht(self.lg2), 'Eine andere Liegenschaft ist nicht blockiert')
        self._verbuche(None, quartal='1')
        self.assertFalse(self._verbucht(self.lg2, quartal='2'), 'Ein anderes Quartal ist nicht blockiert')
