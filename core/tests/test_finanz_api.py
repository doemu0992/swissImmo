"""Lesende Finanz-API: Schlüssel, Mandantentrennung, nur Lesen, Bremse, Widerruf."""
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase

from core import api_token
from core.models import ApiToken
from core.tenancy import organisation_kontext

from ._isolation import MandantenFixture


class FinanzApiTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        cache.clear()
        self.token_a, self.roh_a = api_token.erzeugen(self.a.organisation, 'Treuhand A')
        self.c = Client()

    def _get(self, pfad, roh=None, **kw):
        kopf = {'HTTP_AUTHORIZATION': f'Bearer {roh}'} if roh else {}
        return self.c.get(pfad, **kopf, **kw)

    def _buchung(self, org_obj, text='Test'):
        from finance.models import Buchung, Buchungskonto
        with organisation_kontext(org_obj.organisation):
            k = list(Buchungskonto.objects.order_by('nummer')[:2])
            if len(k) < 2:
                k = [Buchungskonto.objects.create(nummer=n, bezeichnung=n, typ='bilanz') for n in ('9991', '9992')]
            return Buchung.objects.create(datum=date(2026, 3, 1), beleg_text=text, soll_konto=k[0], haben_konto=k[1],
                                          betrag=Decimal('12.50'))

    def test_ohne_schluessel_401(self):
        self.assertEqual(self._get('/api/v1/konten').status_code, 401)

    def test_falscher_und_session_schluessel_401(self):
        self.assertEqual(self._get('/api/v1/konten', 'imm_falsch').status_code, 401)
        self.c.force_login(self.a.benutzer)
        self.assertEqual(self._get('/api/v1/konten').status_code, 401)        # eine Sitzung ersetzt den Schlüssel nicht

    def test_klartext_nicht_gespeichert(self):
        self.assertNotIn(self.roh_a, self.token_a.schluessel_hash)
        self.assertEqual(len(self.token_a.schluessel_hash), 64)
        self.assertTrue(self.roh_a.startswith(self.token_a.anfang))

    def test_konten_nur_eigene_verwaltung(self):
        r = self._get('/api/v1/konten', self.roh_a)
        self.assertEqual(r.status_code, 200)
        from finance.models import Buchungskonto
        with organisation_kontext(self.a.organisation):
            erwartet = {k.nummer for k in Buchungskonto.objects.all()}
        self.assertEqual({k['nummer'] for k in r.json()['konten']}, erwartet)

    def test_buchungen_nur_eigene_und_gefiltert(self):
        eigene = self._buchung(self.a, 'Nur A')
        fremde = self._buchung(self.b, 'Nur B')
        r = self._get('/api/v1/buchungen', self.roh_a)
        self.assertEqual(r.status_code, 200)
        belege = [b['text'] for b in r.json()['buchungen']]
        self.assertEqual(r.json()['gesamt'], len(belege))
        self.assertIn('Nur A', belege)
        self.assertNotIn('Nur B', belege)
        from finance.models import Buchung
        with organisation_kontext(self.a.organisation):
            self.assertEqual(len(belege), Buchung.objects.count())
        self.assertNotEqual(eigene.organisation_id, fremde.organisation_id)
        # Datumsfilter und Seiten
        self.assertEqual(self._get('/api/v1/buchungen?von=2099-01-01', self.roh_a).json()['gesamt'], 0)
        self.assertEqual(self._get('/api/v1/buchungen?limit=9999', self.roh_a).json()['limit'], 500)
        self.assertEqual(self._get('/api/v1/buchungen?von=kaputt', self.roh_a).status_code, 422)

    def test_schreiben_ist_nicht_moeglich(self):
        for methode in ('post', 'put', 'patch', 'delete'):
            r = getattr(self.c, methode)('/api/v1/buchungen', HTTP_AUTHORIZATION=f'Bearer {self.roh_a}')
            self.assertIn(r.status_code, (404, 405), methode)

    def test_widerruf_wirkt_sofort(self):
        self.assertEqual(self._get('/api/v1/konten', self.roh_a).status_code, 200)
        api_token.widerrufen(self.token_a)
        self.assertEqual(self._get('/api/v1/konten', self.roh_a).status_code, 401)

    def test_bremse(self):
        for _i in range(api_token.LIMIT_JE_MINUTE):
            self._get('/api/v1/konten', self.roh_a)
        self.assertEqual(self._get('/api/v1/konten', self.roh_a).status_code, 429)

    def test_kein_kontext_bleibt_haengen(self):
        from core.tenancy import aktuelle_organisation
        self._get('/api/v1/konten', self.roh_a)
        self.assertIsNone(aktuelle_organisation())

    def test_befehle_anlegen_und_widerrufen_mit_log(self):
        from core.models import AktivitaetsLog
        aus = StringIO()
        call_command('api_token_erstellen', organisation=self.b.organisation.pk, name='Revision B', stdout=aus)
        roh = [z for z in aus.getvalue().split() if z.startswith('imm_')][0]
        self.assertEqual(self._get('/api/v1/konten', roh).status_code, 200)
        t = ApiToken.alle_organisationen.get(name='Revision B')
        call_command('api_token_widerrufen', id=t.pk, stdout=StringIO())
        self.assertEqual(self._get('/api/v1/konten', roh).status_code, 401)
        aktionen = set(AktivitaetsLog.alle_organisationen.filter(organisation=self.b.organisation)
                       .values_list('aktion', flat=True))
        self.assertTrue({'API-Schlüssel angelegt', 'API-Schlüssel widerrufen'} <= aktionen)
        self.assertNotIn(roh, ' '.join(AktivitaetsLog.alle_organisationen.values_list('details', flat=True)))


class ApiTokenModellTests(TestCase):
    def test_finden_lehnt_unsinn_ab(self):
        self.assertIsNone(api_token.finden(''))
        self.assertIsNone(api_token.finden('abc'))
        self.assertIsNone(api_token.finden('imm_' + 'x' * 500))
