"""Stresstest 30.09.2026: Mietzinsvorschläge auf 5 Rappen."""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from core.services.mietrecht import runde_mietzins

from ._helfer import _basis_objekte


class RundungTests(SimpleTestCase):
    def test_auf_fuenf_rappen(self):
        for roh, soll in (('1699.08', '1699.10'), ('1699.07', '1699.05'), ('1699.025', '1699.05'),
                          ('1699.02', '1699.00'), ('1500.00', '1500.00'), ('1234.575', '1234.60')):
            self.assertEqual(runde_mietzins(Decimal(roh)), Decimal(soll), roh)

    def test_kaufmaennisch_auf_halbem_schritt(self):
        self.assertEqual(runde_mietzins(Decimal('10.025')), Decimal('10.05'))
        self.assertEqual(runde_mietzins(Decimal('10.075')), Decimal('10.10'))

    def test_ergebnis_hat_zwei_nachkommastellen(self):
        self.assertEqual(str(runde_mietzins(Decimal('1700'))), '1700.00')


class VorschlagTests(TestCase):
    def test_referenzzinssenkung_ergibt_einen_auf_5_rappen_gerundeten_vorschlag(self):
        from rentals.services import berechne_mietpotenzial
        lg, e, m, v = _basis_objekte()
        v.netto_mietzins = Decimal('1750.00')
        v.basis_referenzzinssatz = Decimal('1.25'); v.basis_lik_punkte = Decimal('107.1')
        r = berechne_mietpotenzial(v, Decimal('1.00'), Decimal('107.1'))
        self.assertEqual(r['neu_chf'] % Decimal('0.05'), 0, r['neu_chf'])
        self.assertEqual(r['neu_chf'], Decimal('1699.10'))            # 1750 × 0.9709 = 1699.075
        self.assertEqual(r['delta_chf'], r['neu_chf'] - Decimal('1750.00'))

    def test_indexvorschlag_ist_auf_5_rappen_gerundet(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        lg, e, m, v = _basis_objekte()
        v.mietzins_modell = 'index'; v.netto_mietzins = Decimal('1480.00')
        v.basis_lik_punkte = Decimal('105.0'); v.index_weitergabe_prozent = Decimal('100')
        r = index_anpassung_vorschlag(v, Decimal('107.3'))
        self.assertEqual(r['neu_netto'] % Decimal('0.05'), 0, r['neu_netto'])
