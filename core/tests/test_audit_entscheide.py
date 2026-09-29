"""Offene Entscheide aus dem Audit (docs/AUDIT-SAAS-NIVEAU.md).

- Kaution beim Objekt: Wohnräume höchstens drei Monatsmieten (Art. 257e OR),
  Gewerbe und Nebenobjekte frei.
- GWR-Import: Ein abgewähltes Häkchen verhindert den Import.
- Mahnung: «Kopie per E-Mail» als Zusatz zur Mahnung per Post.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, Client
from django.utils import timezone

from ._helfer import _team_user, _basis_objekte


class KautionBeimObjekt(TestCase):

    def setUp(self):
        self.lg, self.e, _m, _v = _basis_objekte()
        self.e.standard_kautionsmonate = 2
        self.e.save()
        self.c = Client()
        self.c.force_login(_team_user())
        self.pfad = f'/neu/objekte/{self.e.id}/bearbeiten/'

    def _post(self, typ, monate):
        return self.c.post(self.pfad, {'liegenschaft_id': str(self.lg.id), 'bezeichnung': 'Objekt',
                                       'typ': typ, 'standard_kautionsmonate': monate})

    def test_wohnung_mit_vier_monaten_wird_abgelehnt(self):
        r = self._post('whg', '4')
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn('id="id_standard_kautionsmonate_fehler"', body)
        self.assertIn('Art. 257e OR', body)
        self.e.refresh_from_db()
        self.assertEqual(self.e.standard_kautionsmonate, 2)

    def test_wohnung_mit_drei_monaten_geht(self):
        self.assertEqual(self._post('whg', '3').status_code, 302)
        self.e.refresh_from_db()
        self.assertEqual(self.e.standard_kautionsmonate, 3)

    def test_gewerbe_und_parkplatz_bleiben_frei(self):
        for typ in ('gew', 'pp'):
            with self.subTest(typ=typ):
                self.assertEqual(self._post(typ, '6').status_code, 302)
                self.e.refresh_from_db()
                self.assertEqual(self.e.standard_kautionsmonate, 6)


@patch('portfolio.services.sync_liegenschaft_with_gwr', return_value={})
class GwrHaekchen(TestCase):

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())
        self.daten = {'strasse': 'Neue Strasse 5', 'plz': '8001', 'ort': 'Zürich',
                      'kanton': 'ZH', 'hkvo_grundkosten_prozent': '40'}

    def test_abgewaehlt_importiert_nicht(self, gwr):
        # Ein abgewähltes Kontrollkästchen fehlt im POST ganz.
        r = self.c.post('/neu/liegenschaften/neu/', self.daten)
        self.assertEqual(r.status_code, 302)
        gwr.assert_not_called()

    def test_angewaehlt_importiert(self, gwr):
        r = self.c.post('/neu/liegenschaften/neu/', {**self.daten, 'gwr_import': 'on'})
        self.assertEqual(r.status_code, 302)
        gwr.assert_called_once()


class MahnungKopiePerEmail(TestCase):

    def setUp(self):
        from finance.models import DebitorenRechnung
        _lg, _e, self.m, self.v = _basis_objekte()
        faellig = timezone.localdate() - timedelta(days=40)
        self.monat = faellig.strftime('%m/%Y')
        DebitorenRechnung.objects.create(
            vertrag=self.v, liegenschaft=self.v.einheit.liegenschaft, titel='Miete',
            betrag=Decimal('1700'), datum=faellig, faellig_am=faellig, status='offen')
        self.c = Client()

    def test_verwalter_sieht_knopf_mit_monat_und_betrag(self):
        self.c.force_login(_team_user())
        body = self.c.get('/neu/mahnwesen/').content.decode()
        self.assertIn(f'action="/vertrag/{self.v.id}/mahnung/mail/"', body)
        self.assertIn(f'name="monat" value="{self.monat}"', body)
        self.assertIn('name="betrag" value="1700.00"', body)
        self.assertIn('Kopie per E-Mail', body)
        self.assertIn('Art. 257d OR', body)

    def test_ohne_email_kein_knopf(self):
        self.m.email = ''
        self.m.save()
        self.c.force_login(_team_user())
        body = self.c.get('/neu/mahnwesen/').content.decode()
        self.assertNotIn('/mahnung/mail/', body)

    def test_ohne_recht_kein_knopf(self):
        self.c.force_login(_team_user('Sachbearbeitung'))
        body = self.c.get('/neu/mahnwesen/').content.decode()
        self.assertNotIn('/mahnung/mail/', body)

    def test_knopf_verschickt_die_kopie(self):
        self.c.force_login(_team_user())
        r = self.c.post(f'/vertrag/{self.v.id}/mahnung/mail/',
                        {'monat': self.monat, 'betrag': '1700.00'},
                        HTTP_REFERER='/neu/mahnwesen/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.m.email])
