"""Stresstest 30.09.2026, Punkt 4: Eigentümerfreigabe sperrt die Rechnung."""
from decimal import Decimal

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _seed_konten, _team_user


class EigentuemerFreigabeSperreTests(TestCase):

    def setUp(self):
        _seed_konten()
        from crm.models import Handwerker
        from finance.booking import konto
        from finance.models import KreditorenRechnung
        from tickets.models import HandwerkerAuftrag, SchadenMeldung
        self.lg, self.e, self.m, self.v = _basis_objekte()
        t = SchadenMeldung.objects.create(titel='Wasserschaden', liegenschaft=self.lg,
                                          betroffene_einheit=self.e)
        hw = Handwerker.objects.create(firma='Sanitär AG')
        self.k = KreditorenRechnung.objects.create(
            lieferant='Sanitär AG', betrag=Decimal('1240.00'), status='neu',
            liegenschaft=self.lg, konto=konto('4000'))
        self.auftrag = HandwerkerAuftrag.objects.create(
            ticket=t, handwerker=hw, kreditoren_rechnung=self.k,
            kosten_geschaetzt=Decimal('1500'), freigabe_status='ausstehend')
        self.c = Client(); self.c.force_login(_team_user())

    def _freigeben(self):
        return self.c.post(f'/neu/kreditoren/{self.k.id}/freigeben/', {}, secure=True)

    def test_ausstehende_freigabe_sperrt_die_rechnungsfreigabe(self):
        from finance.models import Buchung
        self._freigeben()
        self.k.refresh_from_db()
        self.assertEqual(self.k.status, 'neu', 'Die Rechnung wurde trotz ausstehender Freigabe freigegeben.')
        self.assertFalse(Buchung.objects.filter(kreditoren_rechnung=self.k).exists())

    def test_abgelehnte_freigabe_sperrt_ebenfalls(self):
        self.auftrag.freigabe_status = 'abgelehnt'; self.auftrag.save()
        self._freigeben()
        self.k.refresh_from_db()
        self.assertEqual(self.k.status, 'neu')

    def test_nach_der_freigabe_geht_es(self):
        self.auftrag.freigabe_status = 'freigegeben'; self.auftrag.save()
        self._freigeben()
        self.k.refresh_from_db()
        self.assertEqual(self.k.status, 'freigegeben')

    def test_bezahlen_ist_gesperrt_wenn_die_freigabe_nachtraeglich_entzogen_wird(self):
        from finance.models import KreditorenZahlung
        self.auftrag.freigabe_status = 'freigegeben'; self.auftrag.save()
        self._freigeben()
        self.auftrag.freigabe_status = 'ausstehend'; self.auftrag.save()
        self.c.post('/neu/kreditoren/bezahlen/', {'rechnung_id': self.k.id}, secure=True)
        self.assertFalse(KreditorenZahlung.objects.filter(kreditor=self.k).exists())

    def test_zahllauf_laesst_gesperrte_rechnung_aus(self):
        self.auftrag.freigabe_status = 'freigegeben'; self.auftrag.save()
        self._freigeben()
        self.auftrag.freigabe_status = 'ausstehend'; self.auftrag.save()
        self.c.post('/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [self.k.id]}, secure=True)
        self.k.refresh_from_db()
        self.assertEqual(self.k.status, 'freigegeben')

    def test_weiterverrechnung_ist_gesperrt(self):
        from finance.models import DebitorenRechnung
        self.auftrag.freigabe_status = 'freigegeben'; self.auftrag.save()
        self._freigeben()
        self.auftrag.freigabe_status = 'ausstehend'; self.auftrag.save()
        self.c.post(f'/neu/kreditoren/{self.k.id}/weiterverrechnen/',
                    {'vertrag_id': self.v.id, 'betrag': '300', 'zuschlag': '0'}, secure=True)
        self.assertFalse(DebitorenRechnung.objects.filter(quell_kreditor=self.k).exists())

    def test_rechnung_ohne_auftrag_ist_nie_gesperrt(self):
        from finance.booking import konto
        from finance.models import KreditorenRechnung
        k2 = KreditorenRechnung.objects.create(lieferant='EW', betrag=Decimal('80'), status='neu',
                                               liegenschaft=self.lg, konto=konto('4000'))
        self.c.post(f'/neu/kreditoren/{k2.id}/freigeben/', {}, secure=True)
        k2.refresh_from_db()
        self.assertEqual(k2.status, 'freigegeben')

    def test_kostenabweichung_loest_nachfreigabe_aus(self):
        """Schätzung 900 freigegeben, effektiv 1240 (+38 %) → erneut ausstehend."""
        self.auftrag.freigabe_status = 'freigegeben'
        self.auftrag.kosten_geschaetzt = Decimal('900'); self.auftrag.save()
        self.c.post(f'/neu/auftrag/{self.auftrag.id}/kosten/',
                    {'kosten_geschaetzt': '900', 'kosten_effektiv': '1240'}, secure=True)
        self.auftrag.refresh_from_db()
        self.assertEqual(self.auftrag.freigabe_status, 'ausstehend')

    def test_geringe_abweichung_bleibt_freigegeben(self):
        self.auftrag.freigabe_status = 'freigegeben'
        self.auftrag.kosten_geschaetzt = Decimal('900'); self.auftrag.save()
        self.c.post(f'/neu/auftrag/{self.auftrag.id}/kosten/',
                    {'kosten_geschaetzt': '900', 'kosten_effektiv': '950'}, secure=True)
        self.auftrag.refresh_from_db()
        self.assertEqual(self.auftrag.freigabe_status, 'freigegeben')
