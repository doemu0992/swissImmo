"""Stresstest 30.09.2026: Zahlungsvereinbarung mit Ratenplan statt Häkchen."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


class ZahlungsvereinbarungTests(TestCase):

    def setUp(self):
        _seed_konten()
        from finance.models import DebitorenRechnung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.heute = date.today()
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.v, titel='Miete', datum=self.heute - timedelta(days=40),
            faellig_am=self.heute - timedelta(days=40), betrag=Decimal('1000.00'))

    def _anlegen(self, raten=3, erste=None):
        from core.services import zahlungsvereinbarung as zv
        return zv.anlegen(self.v, raten, erste or self.heute, user=None)

    def _zahlen(self, betrag, am=None):
        from finance.models import Zahlungseingang
        Zahlungseingang.objects.create(vertrag=self.v, debitoren_rechnung=self.r, betrag=Decimal(betrag),
                                       datum_eingang=am or self.heute)
        self.r.status = 'bezahlt' if self.r.offener_betrag <= 0 else 'teilbezahlt'
        self.r.save(update_fields=['status'])

    def test_plan_verteilt_gleich_und_der_rest_geht_auf_die_letzte_rate(self):
        from core.services import zahlungsvereinbarung as zv
        vb = self._anlegen(3)
        plan = zv.raten_plan(vb)
        self.assertEqual([b for _, _, b in plan], [Decimal('333.33'), Decimal('333.33'), Decimal('333.34')])
        self.assertEqual(sum(b for _, _, b in plan), Decimal('1000.00'))
        self.assertEqual([f.month for _, f, _ in plan],
                         [(self.heute.month - 1 + i) % 12 + 1 for i in range(3)])

    def test_anlegen_setzt_mahnsperre_und_raten_pendenzen(self):
        from core.models import Pendenz
        vb = self._anlegen(3)
        self.m.refresh_from_db()
        self.assertTrue(self.m.mahnsperre)
        self.assertEqual(Pendenz.objects.filter(quelle__startswith=f'auto:rate:{vb.pk}:').count(), 3)

    def test_mahnlauf_mahnt_waehrend_der_vereinbarung_nicht(self):
        from core.services.automation import run_mahnlauf
        self._anlegen(3)
        self.assertEqual(run_mahnlauf(send_email=False)['gemahnt'], 0)

    def test_volle_zahlung_erfuellt_und_hebt_die_sperre_auf(self):
        from core.models import Pendenz
        vb = self._anlegen(3)
        self._zahlen('1000.00')
        vb.refresh_from_db(); self.m.refresh_from_db()
        self.assertEqual(vb.status, 'erfuellt')
        self.assertFalse(self.m.mahnsperre)
        self.assertFalse(Pendenz.objects.filter(quelle__startswith=f'auto:rate:{vb.pk}:', erledigt=False).exists())

    def test_erste_rate_bezahlt_erledigt_nur_deren_pendenz(self):
        from core.models import Pendenz
        vb = self._anlegen(3)
        self._zahlen('333.33')
        vb.refresh_from_db()
        self.assertEqual(vb.status, 'aktiv')
        self.assertTrue(Pendenz.objects.get(quelle=f'auto:rate:{vb.pk}:1').erledigt)
        self.assertFalse(Pendenz.objects.get(quelle=f'auto:rate:{vb.pk}:2').erledigt)

    def test_gebrochene_vereinbarung_hebt_die_sperre_auf_und_meldet_es(self):
        from core.models import Pendenz
        from core.services import zahlungsvereinbarung as zv
        vb = self._anlegen(3)
        # Erste Rate war vor 10 Tagen fällig und wurde nicht bezahlt.
        vb.erste_rate = self.heute - timedelta(days=10); vb.save()
        self.assertEqual(zv.pruefen(vb), 'gebrochen')
        self.m.refresh_from_db()
        self.assertFalse(self.m.mahnsperre)
        self.assertTrue(Pendenz.objects.filter(quelle=f'auto:ratenbruch:{vb.pk}').exists())

    def test_toleranz_verzeiht_wenige_tage_verspaetung(self):
        from core.services import zahlungsvereinbarung as zv
        vb = self._anlegen(3)
        vb.erste_rate = self.heute - timedelta(days=2); vb.save()
        self.assertEqual(zv.pruefen(vb), 'aktiv')

    def test_nachzahlung_nach_verspaetung_ist_kein_bruch(self):
        """Wer gerade nachzahlt, hat nicht gebrochen — die Zahlung löst kein Urteil aus."""
        vb = self._anlegen(3)
        vb.erste_rate = self.heute - timedelta(days=10); vb.save()
        self._zahlen('100.00')
        vb.refresh_from_db()
        self.assertEqual(vb.status, 'aktiv')

    def test_taeglicher_lauf_bewertet_die_vereinbarungen(self):
        from core.services.automation import generate_auto_pendenzen
        vb = self._anlegen(3)
        vb.erste_rate = self.heute - timedelta(days=10); vb.save()
        generate_auto_pendenzen(horizont_tage=30)
        vb.refresh_from_db()
        self.assertEqual(vb.status, 'gebrochen')

    def test_unzulaessige_angaben(self):
        from core.services import zahlungsvereinbarung as zv
        with self.assertRaises(ValueError):
            zv.anlegen(self.v, 1, self.heute)
        with self.assertRaises(ValueError):
            zv.anlegen(self.v, 3, self.heute - timedelta(days=1))
        self._anlegen(3)
        with self.assertRaises(ValueError):
            zv.anlegen(self.v, 3, self.heute)

    def test_ohne_rueckstand_keine_vereinbarung(self):
        from core.services import zahlungsvereinbarung as zv
        self._zahlen('1000.00')
        with self.assertRaises(ValueError):
            zv.anlegen(self.v, 3, self.heute)

    def test_spaeter_faellige_miete_gehoert_nicht_zum_rueckstand(self):
        from core.services import zahlungsvereinbarung as zv
        from finance.models import DebitorenRechnung
        vb = self._anlegen(3)
        DebitorenRechnung.objects.create(vertrag=self.v, titel='Miete neu', datum=self.heute + timedelta(days=5),
                                         faellig_am=self.heute + timedelta(days=5), betrag=Decimal('1700'))
        self.assertEqual(zv.rueckstand(vb), Decimal('1000.00'))

    def test_abbrechen_hebt_die_sperre_auf(self):
        from core.services import zahlungsvereinbarung as zv
        vb = self._anlegen(3)
        zv.abbrechen(vb)
        self.m.refresh_from_db(); vb.refresh_from_db()
        self.assertFalse(self.m.mahnsperre)
        self.assertEqual(vb.status, 'abgebrochen')

    def test_view_anlegen_und_rollen(self):
        c = Client(); c.force_login(_team_user('Verwalter'))
        url = f'/neu/vertraege/{self.v.id}/zahlungsvereinbarung/'
        self.assertEqual(c.get(url, secure=True).status_code, 200)
        c.post(url, {'aktion': 'anlegen', 'anzahl_raten': '4', 'intervall_monate': '1',
                     'erste_rate': (self.heute + timedelta(days=7)).isoformat()}, secure=True)
        self.assertEqual(self.v.zahlungsvereinbarungen.filter(status='aktiv').count(), 1)
        c2 = Client(); c2.force_login(_team_user('Sachbearbeiter'))
        self.assertEqual(c2.post(url, {'aktion': 'anlegen'}, secure=True).status_code, 403)
