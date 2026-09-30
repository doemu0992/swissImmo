"""Stresstest 30.09.2026, Punkt 8: Nutzungsentschädigung nach Vertragsende."""
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user
from core.services import nutzungsentschaedigung as ne


class NutzungsentschaedigungTests(TestCase):

    def setUp(self):
        _seed_konten()
        self.lg, self.e, self.m, self.v = _basis_objekte()
        # Stresstest-Fall: Kündigung per 28.02., Mieter bleibt.
        self.v.status = 'gekuendigt'
        self.v.ende = date(2026, 2, 28)
        self.v.netto_mietzins = Decimal('1300.00')
        self.v.nebenkosten = Decimal('180.00')
        self.v.save()

    def test_sollstellung_stoppt_nach_vertragsende_und_die_entschaedigung_fuellt_die_luecke(self):
        from core.services.automation import run_sollstellung
        run_sollstellung(2026, 3)
        self.assertFalse(self.v.debitoren_rechnungen.filter(titel__startswith='Miete').exists())
        r = ne.stelle(self.v, 2026, 3)
        self.assertIsNotNone(r)
        self.assertEqual(r.betrag, Decimal('1480.00'))        # 1300 + 180, ganzer März
        self.assertEqual(r.faellig_am, date(2026, 3, 1))
        self.assertEqual(r.status, 'offen')

    def test_ertrag_ist_gebucht_und_nebenbuch_stimmt_mit_1100_ueberein(self):
        from finance.models import Buchung, Buchungskonto
        r = ne.stelle(self.v, 2026, 3)
        k = Buchungskonto.objects.get(nummer='1100')
        soll = sum((b.betrag for b in Buchung.objects.filter(soll_konto=k, debitoren_rechnung=r)), Decimal('0'))
        self.assertEqual(soll, r.betrag)

    def test_idempotent(self):
        self.assertIsNotNone(ne.stelle(self.v, 2026, 3))
        self.assertIsNone(ne.stelle(self.v, 2026, 3))
        self.assertEqual(self.v.debitoren_rechnungen.filter(titel__startswith='Nutzungsent').count(), 1)

    def test_monat_des_vertragsendes_ist_nur_anteilig_wenn_ende_mitten_im_monat(self):
        self.v.ende = date(2026, 3, 15); self.v.save()
        r = ne.stelle(self.v, 2026, 3)           # 16.–31. März = 16 von 31 Tagen
        self.assertEqual(r.betrag, Decimal('670.97') + Decimal('92.90'))

    def test_ende_am_monatsletzten_gibt_im_selben_monat_nichts(self):
        self.assertIsNone(ne.stelle(self.v, 2026, 2))

    def test_rueckgabe_begrenzt_die_entschaedigung(self):
        from rentals.models import Abnahmeprotokoll
        Abnahmeprotokoll.objects.create(vertrag=self.v, typ='auszug', datum=date(2026, 3, 10))
        r = ne.stelle(self.v, 2026, 3)           # 1.–10. März = 10 von 31 Tagen
        # Netto und NK werden je für sich gerundet (wie in der Sollstellung).
        self.assertEqual(r.betrag, Decimal('419.35') + Decimal('58.06'))
        self.assertIsNone(ne.stelle(self.v, 2026, 4), 'Nach der Rückgabe wird nichts mehr gestellt.')

    def test_rueckgabe_am_vertragsende_schliesst_es_aus(self):
        from rentals.models import Abnahmeprotokoll
        Abnahmeprotokoll.objects.create(vertrag=self.v, typ='auszug', datum=date(2026, 2, 28))
        self.assertFalse(ne.ist_offen(self.v, date(2026, 5, 1)))
        self.assertEqual(ne.monate_ohne_forderung(self.v, date(2026, 5, 1)), [])

    def test_stelle_bis_heute_fuellt_alle_monate(self):
        neu = ne.stelle_bis_heute(self.v, bis=date(2026, 5, 10))
        self.assertEqual([r.titel for r in neu],
                         ['Nutzungsentschädigung 03/2026', 'Nutzungsentschädigung 04/2026',
                          'Nutzungsentschädigung 05/2026'])
        self.assertEqual(ne.stelle_bis_heute(self.v, bis=date(2026, 5, 10)), [])

    def test_aktiver_vertrag_schuldet_nichts(self):
        self.v.status = 'aktiv'; self.v.ende = None; self.v.save()
        self.assertFalse(ne.ist_offen(self.v))

    def test_pendenz_wird_angelegt_und_bei_rueckgabe_erledigt(self):
        from core.models import Pendenz
        from core.services.automation import generate_auto_pendenzen
        from rentals.models import Abnahmeprotokoll
        generate_auto_pendenzen(horizont_tage=30)
        p = Pendenz.objects.get(quelle=f'auto:nutzung:{self.v.pk}')
        self.assertFalse(p.erledigt)
        Abnahmeprotokoll.objects.create(vertrag=self.v, typ='auszug', datum=date(2026, 2, 28))
        generate_auto_pendenzen(horizont_tage=30)
        p.refresh_from_db()
        self.assertTrue(p.erledigt)

    def test_view_nur_fuer_verwaltungsrollen_und_stellt_per_post(self):
        c = Client(); c.force_login(_team_user('Verwalter'))
        self.assertEqual(c.get(f'/neu/vertraege/{self.v.id}/nutzungsentschaedigung/', secure=True).status_code, 200)
        c.post(f'/neu/vertraege/{self.v.id}/nutzungsentschaedigung/', {}, secure=True)
        self.assertTrue(self.v.debitoren_rechnungen.filter(titel__startswith='Nutzungsent').exists())
        c2 = Client(); c2.force_login(_team_user('Sachbearbeiter'))
        self.assertEqual(c2.post(f'/neu/vertraege/{self.v.id}/nutzungsentschaedigung/', {}, secure=True).status_code, 403)


class SollstellungFaelligkeitTests(TestCase):
    def test_einzug_mitten_im_monat_ist_ab_einzug_faellig(self):
        """Audit: faellig_am war immer der Monatserste — Verzugstage liefen vor dem Einzug."""
        from core.services.automation import run_sollstellung
        _seed_konten()
        lg, e, m, v = _basis_objekte()
        v.beginn = date(2025, 11, 15); v.save()
        run_sollstellung(2025, 11)
        r = v.debitoren_rechnungen.get(titel='Miete & NK 11/2025')
        self.assertEqual(r.faellig_am, date(2025, 11, 15))
