"""Das Journal storniert keine Buchung, die zu einer Zahlung oder Rechnung gehört.

Audit 17.11.2026 (F1): Eine Zahlungsbuchung im Journal zu stornieren, liess die Rechnung «bezahlt» und die Zahlung
«verbucht»; das Konto zeigte wieder den alten Stand. Die Rechnung wurde nie mehr gemahnt. Das Journal verweist jetzt auf
den richtigen Weg (Zahlung oder Rechnung stornieren).
"""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


class JournalStornoMitNebenbuchTests(TestCase):

    def setUp(self):
        from finance.booking import buche
        from finance.models import DebitorenRechnung, Zahlungseingang
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.rechnung = DebitorenRechnung.objects.create(
            vertrag=self.v, betrag=Decimal('1700.00'), faellig_am=date(2026, 6, 30), status='bezahlt')
        self.zahlung = Zahlungseingang.objects.create(betrag=Decimal('1700.00'), datum_eingang=date(2026, 7, 1),
                                                      debitoren_rechnung=self.rechnung, vertrag=self.v,
                                                      status='verbucht', bank_referenz='R-1')
        self.b_zahlung = buche('1020', '1100', Decimal('1700.00'), 'Zahlung Miete', datum=date(2026, 7, 1),
                               zahlung=self.zahlung, debitor=self.rechnung)
        self.b_frei = buche('1020', '3000', Decimal('50.00'), 'Handbuchung ohne Bezug', datum=date(2026, 7, 2))
        self.c = Client()
        self.c.force_login(_team_user())

    def _storniere(self, b):
        return self.c.post(f'/neu/buchhaltung/buchung/{b.id}/stornieren/')

    def test_zahlungsbuchung_wird_im_journal_nicht_storniert(self):
        from finance.models import Buchung
        r = self._storniere(self.b_zahlung)
        self.assertEqual(r.status_code, 302)
        self.b_zahlung.refresh_from_db()
        self.assertIsNone(self.b_zahlung.storniert_am, 'Die Zahlungsbuchung wurde im Journal storniert')
        self.assertFalse(Buchung.objects.filter(storno_von=self.b_zahlung).exists())
        self.rechnung.refresh_from_db()
        self.assertEqual(self.rechnung.status, 'bezahlt')

    def test_gegenprobe_handbuchung_ohne_bezug_wird_weiter_storniert(self):
        from finance.models import Buchung
        self._storniere(self.b_frei)
        self.b_frei.refresh_from_db()
        self.assertIsNotNone(self.b_frei.storniert_am)
        self.assertTrue(Buchung.objects.filter(storno_von=self.b_frei).exists())
