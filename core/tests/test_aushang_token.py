"""Der QR-Aushang trägt ein Token, und das Webformular antwortet immer gleich.

Vorher: `/report/<Nummer>/` liess sich abzählen (jede Nummer lieferte Adresse und Einheitenliste), und
`/schaden/melden/` verriet über seine Fehlermeldung, ob eine E-Mail-Adresse einem Mieter gehört.

Gegenprobe (15.11.2026): Stichtag-Prüfung in `public_ticket_view` entfernt -> Auslauf-Test rot; den Abgleich
einer leeren Adresse wieder zugelassen -> Test «leere E-Mail» rot; `gemeldet_von` wieder gesetzt -> Test rot.
"""
import re
from datetime import date
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from core.tenancy import organisation_kontext
from crm.models import Mieter
from portfolio.models import Liegenschaft
from tickets.models import SchadenMeldung

from ._isolation import MandantenFixture

MELDUNG = {'kategorie': 'Schadensmeldung', 'raum': 'Küche', 'objekt': 'Backofen', 'beschreibung': 'heizt nicht',
           'vorname': 'Mia', 'nachname': 'Muster', 'telefon': '079 000 00 00', 'adresse': 'Irgendwo 1'}


class AushangTokenTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        cache.clear()
        self.a.liegenschaft.refresh_from_db()

    def test_jede_liegenschaft_hat_ein_eigenes_token(self):
        tokens = list(Liegenschaft.alle_organisationen.values_list('aushang_token', flat=True))
        self.assertTrue(all(len(t) >= 16 for t in tokens))
        self.assertEqual(len(set(tokens)), len(tokens))

    def test_token_adresse_zeigt_das_formular(self):
        antwort = self.client.get(f'/aushang/{self.a.liegenschaft.aushang_token}/')
        self.assertContains(antwort, self.a.liegenschaft.strasse)

    def test_falsches_oder_kurzes_token_ist_404(self):
        for wert in ('x', 'A' * 22, str(self.a.liegenschaft.pk)):
            self.assertEqual(self.client.get(f'/aushang/{wert}/').status_code, 404, wert)

    def test_der_aushang_druckt_die_token_adresse(self):
        from tickets import services
        with mock.patch.object(services.segno, 'make', wraps=services.segno.make) as machen:
            services.generate_qr_poster(self.a.liegenschaft, 'beispiel.ch')
        adresse = machen.call_args[0][0]
        self.assertEqual(adresse, f'https://beispiel.ch/aushang/{self.a.liegenschaft.aushang_token}/')

    def test_erneuern_entwertet_den_alten_code(self):
        alt = self.a.liegenschaft.aushang_token
        self.client.force_login(self.a.benutzer)
        self.client.post(f'/neu/liegenschaften/{self.a.liegenschaft.pk}/aushang-erneuern/')
        self.a.liegenschaft.refresh_from_db()
        self.assertNotEqual(self.a.liegenschaft.aushang_token, alt)
        self.client.logout()
        self.assertEqual(self.client.get(f'/aushang/{alt}/').status_code, 404)
        self.assertEqual(self.client.get(f'/aushang/{self.a.liegenschaft.aushang_token}/').status_code, 200)

    def test_fremde_liegenschaft_laesst_sich_nicht_erneuern(self):
        alt = self.b.liegenschaft.aushang_token
        self.client.force_login(self.a.benutzer)
        antwort = self.client.post(f'/neu/liegenschaften/{self.b.liegenschaft.pk}/aushang-erneuern/')
        self.assertEqual(antwort.status_code, 404)
        self.b.liegenschaft.refresh_from_db()
        self.assertEqual(self.b.liegenschaft.aushang_token, alt)

    def test_die_adresse_mit_nummer_laeuft_aus(self):
        pfad = f'/report/{self.a.liegenschaft.pk}/'
        with override_settings(AUSHANG_ID_ROUTE_BIS=date(2999, 1, 1)):
            self.assertEqual(self.client.get(pfad).status_code, 200)
        with override_settings(AUSHANG_ID_ROUTE_BIS=date(2000, 1, 1)):
            self.assertEqual(self.client.get(pfad).status_code, 404)
            self.assertEqual(self.client.post(pfad, MELDUNG).status_code, 404)

    def test_die_adresse_mit_nummer_laesst_sich_nicht_abzaehlen(self):
        codes = [self.client.get(f'/report/{self.a.liegenschaft.pk}/').status_code for _ in range(32)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertEqual(codes[30:], [404, 404])


class WebformularTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        with organisation_kontext(cls.a.organisation):
            Mieter.objects.filter(pk=cls.a.mieter.pk).update(email='mieterin@example.ch')
            cls.ohne = Mieter.objects.create(vorname='Ohne', nachname='Adresse', email='')

    def setUp(self):
        cache.clear()

    def _melden(self, email):
        return self.client.post('/schaden/melden/', {**MELDUNG, 'email': email})

    def test_bekannte_und_unbekannte_adresse_sehen_dieselbe_antwort(self):
        bekannt = self._melden('mieterin@example.ch')
        unbekannt = self._melden('niemand@example.ch')
        self.assertEqual(bekannt.status_code, unbekannt.status_code)
        ohne_nonce = lambda a: re.sub(r'nonce="[^"]+"|csrfmiddlewaretoken" value="[^"]+"', '', a.content.decode())  # noqa: E731
        self.assertEqual(ohne_nonce(bekannt), ohne_nonce(unbekannt))
        self.assertEqual(SchadenMeldung.alle_organisationen.filter(email_melder='mieterin@example.ch').count(), 1)
        self.assertFalse(SchadenMeldung.alle_organisationen.filter(email_melder='niemand@example.ch').exists())

    def test_leere_email_trifft_keinen_mieter_ohne_adresse(self):
        vorher = SchadenMeldung.alle_organisationen.count()
        self._melden('')
        self.assertEqual(SchadenMeldung.alle_organisationen.count(), vorher)

    def test_die_meldung_wird_nicht_mit_der_person_verknuepft(self):
        self._melden('mieterin@example.ch')
        ticket = SchadenMeldung.alle_organisationen.get(email_melder='mieterin@example.ch')
        self.assertIsNone(ticket.gemeldet_von_id)
        self.assertEqual(ticket.liegenschaft_id, self.a.liegenschaft.pk)

    def test_eine_liegenschaftsnummer_im_formular_wird_uebergangen(self):
        vorher = SchadenMeldung.alle_organisationen.count()
        self.client.post('/schaden/melden/', {**MELDUNG, 'email': 'niemand@example.ch',
                                              'liegenschaft_id': self.a.liegenschaft.pk})
        self.assertEqual(SchadenMeldung.alle_organisationen.count(), vorher)
