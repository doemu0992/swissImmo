"""Der Kalender-Link für Fristen gehört einer Person und lässt sich widerrufen.

Vorher: eine Signatur über die Organisations-ID — derselbe Link für alle, nie ablaufend, nicht erneuerbar, auch
für Lesezugriff sichtbar. Jetzt: ein Zufallswert an der Mitgliedschaft, mit «neu erzeugen» und «entfernen».

Gegenprobe (15.11.2026): Rollen- und Aktivprüfung in `organisation_aus_token` entfernt -> die Tests zu
Rückstufung und gesperrtem Konto rot; `darf_abonnieren` in der Ansicht auf True -> Lesezugriff-Test rot.
"""
from datetime import timedelta

from django.core import signing
from django.test import TestCase
from django.utils import timezone

from core.models import Pendenz
from core.services.ical import feed_token, organisation_aus_token, token_setzen
from core.tenancy import organisation_kontext
from crm.models import Mitgliedschaft

from ._isolation import MandantenFixture


class KalenderLinkTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        for f in (cls.a, cls.b):
            with organisation_kontext(f.organisation):
                Pendenz.objects.create(titel=f'Frist {f.kuerzel}', erledigt=False,
                                       faellig_am=timezone.localdate() + timedelta(days=3))

    def _abruf(self, token):
        return self.client.get('/fristen.ics', {'token': token})

    def test_ohne_abonnement_gibt_es_keinen_link(self):
        self.assertEqual(feed_token(self.a.benutzer, self.a.organisation), '')
        self.assertEqual(self._abruf('').status_code, 403)

    def test_der_alte_signierte_link_gilt_nicht_mehr(self):
        alt = signing.Signer(salt='fristen-feed').sign(f'fristen:{self.a.organisation.pk}')
        self.assertEqual(self._abruf(alt).status_code, 403)

    def test_erzeugen_ueber_die_seite_und_abrufen(self):
        self.client.force_login(self.a.benutzer)
        self.assertNotContains(self.client.get('/neu/fristen/'), '/fristen.ics?token=')
        self.client.post('/neu/fristen/kalender-link/', {'aktion': 'neu'})
        token = feed_token(self.a.benutzer, self.a.organisation)
        self.assertGreaterEqual(len(token), 40)
        self.assertContains(self.client.get('/neu/fristen/'), f'/fristen.ics?token={token}')
        self.client.logout()
        inhalt = self._abruf(token).content.decode()
        self.assertIn('Frist A', inhalt)
        self.assertNotIn('Frist B', inhalt)

    def test_neu_erzeugen_entwertet_den_alten(self):
        alt = token_setzen(self.a.benutzer, self.a.organisation)
        neu = token_setzen(self.a.benutzer, self.a.organisation)
        self.assertNotEqual(alt, neu)
        self.assertEqual(self._abruf(alt).status_code, 403)
        self.assertEqual(self._abruf(neu).status_code, 200)

    def test_entfernen_ueber_die_seite(self):
        token = token_setzen(self.a.benutzer, self.a.organisation)
        self.client.force_login(self.a.benutzer)
        self.client.post('/neu/fristen/kalender-link/', {'aktion': 'entfernen'})
        self.assertEqual(feed_token(self.a.benutzer, self.a.organisation), '')
        self.assertEqual(self._abruf(token).status_code, 403)

    def test_rueckstufung_auf_lesezugriff_schliesst_den_kalender(self):
        token = token_setzen(self.a.benutzer, self.a.organisation)
        Mitgliedschaft.alle_organisationen.filter(benutzer=self.a.benutzer).update(
            rolle=Mitgliedschaft.ROLLE_LESEZUGRIFF)
        self.assertIsNone(organisation_aus_token(token))
        self.assertEqual(self._abruf(token).status_code, 403)

    def test_gesperrtes_konto_schliesst_den_kalender(self):
        token = token_setzen(self.a.benutzer, self.a.organisation)
        type(self.a.benutzer).objects.filter(pk=self.a.benutzer.pk).update(is_active=False)
        self.assertEqual(self._abruf(token).status_code, 403)

    def test_lesezugriff_sieht_keinen_link_und_kann_keinen_erzeugen(self):
        Mitgliedschaft.alle_organisationen.filter(benutzer=self.a.benutzer).update(
            rolle=Mitgliedschaft.ROLLE_LESEZUGRIFF)
        self.client.force_login(self.a.benutzer)
        seite = self.client.get('/neu/fristen/')
        self.assertEqual(seite.status_code, 200)
        self.assertNotContains(seite, 'kalender-link')
        self.client.post('/neu/fristen/kalender-link/', {'aktion': 'neu'})
        self.assertFalse(Mitgliedschaft.alle_organisationen.exclude(fristen_feed_token='').exists())

    def test_kurzer_oder_leerer_wert_trifft_nie_eine_zeile_ohne_token(self):
        for wert in ('', ' ', 'x', None):
            self.assertIsNone(organisation_aus_token(wert))
