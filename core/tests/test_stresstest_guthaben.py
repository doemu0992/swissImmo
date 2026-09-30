"""Stresstest 30.09.2026: Doppelzahlung und Rückerstattung als Vorgang."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


class GuthabenRueckerstattungTests(TestCase):

    def setUp(self):
        _seed_konten()
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete', datum=self.heute - timedelta(days=20),
            faellig_am=self.heute - timedelta(days=20), betrag=Decimal('1810.00'))
        self.c = Client(); self.c.force_login(_team_user('Verwalter'))
        # Überzahlung 300
        self.c.post('/neu/bankabgleich/verbuchen/',
                    {'rechnung_id': self.r.id, 'betrag': '2110.00'}, secure=True)
        from finance.models import Zahlungseingang
        self.g = Zahlungseingang.objects.get(bank_referenz__endswith=':ueber')

    def _saldo(self, nummer):
        from finance.models import Buchung, Buchungskonto
        k = Buchungskonto.objects.get(nummer=nummer)
        soll = sum((b.betrag for b in Buchung.objects.filter(soll_konto=k)), Decimal('0'))
        haben = sum((b.betrag for b in Buchung.objects.filter(haben_konto=k)), Decimal('0'))
        return soll - haben

    def test_ueberzahlung_erzeugt_eine_entscheidungs_pendenz(self):
        from core.models import Pendenz
        p = Pendenz.objects.get(quelle=f'auto:guthaben:{self.g.pk}')
        self.assertIn('verrechnen oder zurückerstatten', p.titel)
        self.assertFalse(p.erledigt)

    def test_rueckerstattung_bucht_2030_an_bank_und_raeumt_die_liste_auf(self):
        self.assertEqual(self._saldo('2030'), Decimal('-300.00'))
        self.c.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': self.g.id}, secure=True)
        self.assertEqual(self._saldo('2030'), Decimal('0.00'))
        self.assertEqual(self._saldo('1020'), Decimal('1810.00'),
                         'Bank: 2110 eingegangen, 300 zurückgezahlt.')
        self.g.refresh_from_db()
        self.assertIsNone(self.g.konto_id)
        self.assertIn('zurückerstattet', self.g.bemerkung)

    def test_zweite_rueckerstattung_ist_unmoeglich(self):
        from finance.models import Buchung
        self.c.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': self.g.id}, secure=True)
        n = Buchung.objects.count()
        self.c.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': self.g.id}, secure=True)
        self.assertEqual(Buchung.objects.count(), n, 'Das Guthaben wurde zweimal ausbezahlt.')

    def test_nur_verwalter_zahlen_aus(self):
        c2 = Client(); c2.force_login(_team_user('Sachbearbeiter'))
        r = c2.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': self.g.id}, secure=True)
        self.assertEqual(r.status_code, 403)

    def test_rechnungszahlung_ist_keine_rueckerstattung(self):
        haupt = self.g.__class__.objects.get(debitoren_rechnung=self.r)
        self.c.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': haupt.id}, secure=True)
        self.assertEqual(self._saldo('2030'), Decimal('-300.00'))

    def test_storno_der_zahlung_hebt_auch_die_rueckerstattung_auf(self):
        from finance.models import Zahlungseingang
        self.c.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': self.g.id}, secure=True)
        haupt = Zahlungseingang.objects.get(debitoren_rechnung=self.r)
        self.c.post(f'/neu/zahlungen/{haupt.id}/stornieren/', {}, secure=True)
        self.assertEqual(self._saldo('2030'), Decimal('0.00'))
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))

    def test_pendenz_erledigt_sich_nach_der_rueckerstattung(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        self.c.post('/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': self.g.id}, secure=True)
        generate_auto_pendenzen(horizont_tage=30)
        self.assertTrue(Pendenz.objects.get(quelle=f'auto:guthaben:{self.g.pk}').erledigt)
