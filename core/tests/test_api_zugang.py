"""Seite «API-Zugang»: nur Inhaber, nur mit dem Merkmal `api_zugang`, Klartext nur einmal, Widerruf, Mandantentrennung."""
from django.core.cache import cache
from django.test import Client, TestCase

from abo.models import Abonnement
from core import api_token
from core.models import AktivitaetsLog, ApiToken
from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture

SEITE = '/neu/einstellungen/api/'


def _stufe(org, stufe):
    org.abo_plan = stufe
    org.save(update_fields=['abo_plan'])
    Abonnement.alle_organisationen.update_or_create(organisation=org, defaults={'uneingeschraenkt': False, 'zusatzmodule': []})


class ApiZugangSeiteTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        cache.clear()
        _stufe(self.a.organisation, 'enterprise')
        _stufe(self.b.organisation, 'enterprise')
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def test_enterprise_inhaber_sieht_die_seite(self):
        r = self.c.get(SEITE)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Noch kein Schlüssel')

    def test_ohne_merkmal_gesperrt_und_api_antwortet_403(self):
        _stufe(self.a.organisation, 'professional')
        r = self.c.get(SEITE)
        self.assertNotEqual(r.status_code, 200)
        self.assertNotContains(r, 'Schlüssel anlegen', status_code=r.status_code)
        # Ein Schlüssel, der vor einem Downgrade angelegt wurde, hört auf zu gelten.
        _token, roh = api_token.erzeugen(self.a.organisation, 'Alt')
        r = Client().get('/api/v1/konten', HTTP_AUTHORIZATION=f'Bearer {roh}')
        self.assertEqual(r.status_code, 403)

    def test_anlegen_zeigt_klartext_einmal_und_speichert_nur_den_hash(self):
        r = self.c.post(SEITE, {'name': 'Treuhand X'})
        self.assertEqual(r.status_code, 200)
        roh = r.context['neuer_schluessel']
        self.assertTrue(roh.startswith('imm_'))
        self.assertContains(r, roh)
        t = ApiToken.alle_organisationen.get(name='Treuhand X')
        self.assertNotIn(roh, t.schluessel_hash)
        # Beim nächsten Aufruf ist er weg.
        self.assertNotContains(self.c.get(SEITE), roh)
        # Er funktioniert.
        self.assertEqual(Client().get('/api/v1/konten', HTTP_AUTHORIZATION=f'Bearer {roh}').status_code, 200)
        # Im Logbuch steht nur der Anfang.
        e = AktivitaetsLog.alle_organisationen.filter(aktion='API-Schlüssel angelegt').latest('pk')
        self.assertEqual(e.details, f'{t.anfang}…')
        self.assertNotIn(roh, e.details)

    def test_name_ist_pflicht_und_anzahl_begrenzt(self):
        self.c.post(SEITE, {'name': '  '})
        self.assertEqual(ApiToken.alle_organisationen.filter(organisation=self.a.organisation).count(), 0)
        for i in range(10):
            api_token.erzeugen(self.a.organisation, f'T{i}')
        self.c.post(SEITE, {'name': 'Elfter'})
        self.assertFalse(ApiToken.alle_organisationen.filter(name='Elfter').exists())

    def test_widerrufen_wirkt_und_protokolliert(self):
        t, roh = api_token.erzeugen(self.a.organisation, 'Weg')
        r = self.c.post(f'{SEITE}{t.pk}/widerrufen/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Client().get('/api/v1/konten', HTTP_AUTHORIZATION=f'Bearer {roh}').status_code, 401)
        self.assertTrue(AktivitaetsLog.alle_organisationen.filter(aktion='API-Schlüssel widerrufen').exists())

    def test_get_widerruft_nicht(self):
        t, roh = api_token.erzeugen(self.a.organisation, 'Bleibt')
        self.c.get(f'{SEITE}{t.pk}/widerrufen/')
        self.assertEqual(Client().get('/api/v1/konten', HTTP_AUTHORIZATION=f'Bearer {roh}').status_code, 200)

    def test_fremder_schluessel_ist_404_und_unberuehrt(self):
        fremd, roh = api_token.erzeugen(self.b.organisation, 'Fremd')
        self.assertEqual(self.c.post(f'{SEITE}{fremd.pk}/widerrufen/').status_code, 404)
        self.assertEqual(Client().get('/api/v1/konten', HTTP_AUTHORIZATION=f'Bearer {roh}').status_code, 200)

    def test_liste_zeigt_nur_eigene(self):
        api_token.erzeugen(self.a.organisation, 'Eigener')
        api_token.erzeugen(self.b.organisation, 'Fremder')
        body = self.c.get(SEITE).content.decode()
        self.assertIn('Eigener', body)
        self.assertNotIn('Fremder', body)

    def test_nur_der_inhaber(self):
        from crm.models import Mitgliedschaft
        with organisation_kontext(self.a.organisation):
            Mitgliedschaft.objects.filter(benutzer=self.a.benutzer).update(rolle=Mitgliedschaft.ROLLE_VERWALTER)
        self.assertEqual(self.c.get(SEITE).status_code, 403)
        self.assertEqual(self.c.post(SEITE, {'name': 'X'}).status_code, 403)

    def test_anonym_wird_zum_login_geschickt(self):
        self.assertEqual(Client().get(SEITE).status_code, 302)
