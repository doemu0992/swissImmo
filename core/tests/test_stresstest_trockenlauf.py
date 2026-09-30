"""Stresstest 30.09.2026: Trockenlauf des Mahnlaufs und Mindestabstand der Stufen."""
from datetime import date, timedelta
from decimal import Decimal

from django.core import mail
from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


class TrockenlaufTests(TestCase):

    def setUp(self):
        _seed_konten()
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete', datum=self.heute - timedelta(days=35),
            faellig_am=self.heute - timedelta(days=35), betrag=Decimal('1700.00'))

    def test_trockenlauf_schreibt_und_versendet_nichts(self):
        from core.services.automation import run_mahnlauf
        from finance.models import DebitorenRechnung, Mahnung
        vorher = DebitorenRechnung.objects.count()
        res = run_mahnlauf(dry_run=True)
        self.assertEqual(res['gemahnt'], 1)
        self.assertEqual(res['emails'], 1)
        self.assertEqual(res['gebuehren'], Decimal('20.00'))     # Stufe 2 nach 35 Tagen
        self.assertEqual(len(res['plan']), 1)
        self.assertEqual(res['plan'][0]['stufe'], 2)
        self.assertEqual(Mahnung.objects.count(), 0, 'Der Trockenlauf hat eine Mahnung geschrieben.')
        self.assertEqual(DebitorenRechnung.objects.count(), vorher)
        self.assertEqual(len(mail.outbox), 0, 'Der Trockenlauf hat E-Mails versandt.')

    def test_trockenlauf_und_echter_lauf_entscheiden_gleich(self):
        from core.services.automation import run_mahnlauf
        plan = run_mahnlauf(dry_run=True)
        echt = run_mahnlauf(send_email=False)
        self.assertEqual(plan['gemahnt'], echt['gemahnt'])
        self.assertEqual(plan['gebuehren'], echt['gebuehren'])

    def test_trockenlauf_seite(self):
        c = Client(); c.force_login(_team_user('Verwalter'))
        r = c.get('/neu/mahnwesen/trockenlauf/', secure=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Trockenlauf')
        self.assertContains(r, 'Miete')
        self.assertEqual(len(mail.outbox), 0)

    def test_mindestabstand_zwischen_zwei_stufen(self):
        """Erste Mahnung gestern → die nächste Stufe wartet, auch wenn sie fällig wäre."""
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        Mahnung.objects.create(debitoren_rechnung=self.r, vertrag=self.v, stufe=1,
                               datum=self.heute - timedelta(days=1), betrag_offen=Decimal('1700'))
        res = run_mahnlauf(send_email=False)
        self.assertEqual(res['gemahnt'], 0, 'Stufe 2 einen Tag nach Stufe 1.')

    def test_nach_dem_mindestabstand_geht_die_naechste_stufe(self):
        from core.services.automation import run_mahnlauf
        from finance.models import Mahnung
        Mahnung.objects.create(debitoren_rechnung=self.r, vertrag=self.v, stufe=1,
                               datum=self.heute - timedelta(days=8), betrag_offen=Decimal('1700'))
        self.assertEqual(run_mahnlauf(send_email=False)['gemahnt'], 1)
