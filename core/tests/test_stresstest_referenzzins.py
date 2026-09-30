"""Stresstest 30.09.2026: Referenzzins-Historie mit Stichtag/Quelle und Hinweis auf betroffene Verträge."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import Client, TestCase

from ._helfer import _basis_objekte, _team_user, _test_organisation


class ReferenzzinsHistorieTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.org = _test_organisation()
        self.org.aktueller_referenzzinssatz = Decimal('1.25'); self.org.save()
        self.v.basis_referenzzinssatz = Decimal('1.25'); self.v.save()

    def test_aenderung_aus_dem_abruf_schreibt_historie_und_pendenz(self):
        from core.models import Pendenz
        from core.utils import market_data
        from crm.models import ReferenzzinsStand
        with mock.patch.object(market_data, 'fetch_market_rates',
                               return_value=({'ref_zins': Decimal('1.00')}, [])):
            market_data.update_verwaltung_rates(alle=True)
        s = ReferenzzinsStand.objects.get()
        self.assertEqual((s.vorher, s.satz, s.quelle), (Decimal('1.25'), Decimal('1.00'), 'bwo'))
        self.assertEqual(s.stichtag, date.today())
        self.assertEqual(s.betroffene_senkung, 1, 'Der Vertrag mit Basis 1.25 hat Anspruch auf Senkung.')
        self.assertEqual(s.betroffene_erhoehung, 0)
        p = Pendenz.objects.get(quelle__startswith='auto:refzins:')
        self.assertIn('1 Senkung', p.titel)
        self.assertIn('270a', p.beschreibung)

    def test_erhoehung_wird_als_erhoehung_gezaehlt(self):
        from core.services.referenzzins import aenderung_festhalten
        s = aenderung_festhalten(self.org, Decimal('1.25'), Decimal('1.50'), quelle='manuell')
        self.assertEqual((s.betroffene_senkung, s.betroffene_erhoehung), (0, 1))

    def test_unveraenderter_wert_schreibt_nichts(self):
        from core.utils import market_data
        from crm.models import ReferenzzinsStand
        with mock.patch.object(market_data, 'fetch_market_rates',
                               return_value=({'ref_zins': Decimal('1.25')}, [])):
            market_data.update_verwaltung_rates(alle=True)
        self.assertFalse(ReferenzzinsStand.objects.exists())

    def test_fehlgeschlagener_abruf_schreibt_nichts(self):
        from core.utils import market_data
        from crm.models import ReferenzzinsStand
        with mock.patch.object(market_data.requests, 'get', side_effect=OSError('offline')):
            market_data.update_verwaltung_rates(alle=True)
        self.assertFalse(ReferenzzinsStand.objects.exists())

    def test_handaenderung_im_konto_wird_als_manuell_festgehalten(self):
        from crm.models import ReferenzzinsStand
        c = Client(); c.force_login(_team_user('Inhaber'))
        org = self.org
        c.post('/neu/account/', {
            'firma': org.firma, 'strasse': org.strasse or 'W 1', 'plz': org.plz or '8000',
            'ort': org.ort or 'Zürich', 'aktueller_referenzzinssatz': '1.00'}, secure=True)
        s = ReferenzzinsStand.objects.filter(quelle='manuell').first()
        self.assertIsNotNone(s, 'Handänderung des Satzes wurde nicht festgehalten.')
        self.assertEqual(s.satz, Decimal('1.00'))

    def test_verlaufsseite(self):
        from core.services.referenzzins import aenderung_festhalten
        aenderung_festhalten(self.org, Decimal('1.25'), Decimal('1.00'), quelle='bwo')
        c = Client(); c.force_login(_team_user('Sachbearbeiter'))
        r = c.get('/neu/referenzzins/', secure=True)
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.content.decode(), r'1[.,]00 %')
        self.assertContains(r, 'Abruf BWO')
