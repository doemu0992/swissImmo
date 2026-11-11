"""Abmelden: ein POST beendet die Sitzung; angemeldete Seiten werden nicht zwischengespeichert («Zurück» zeigt nichts mehr)."""
from django.test import Client, TestCase

from core.tests._isolation import MandantenFixture


class AbmeldenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _angemeldet(self):
        c = Client()
        c.force_login(self.a.benutzer)
        return c

    def test_abmelden_ist_ein_formular_mit_post_kein_link(self):
        seite = self._angemeldet().get('/neu/').content.decode()
        self.assertIn('<form method="post" action="/logout/">', seite)
        self.assertNotIn('href="/logout/"', seite)        # Gegenprobe: GET auf /logout/ ergibt 405, eine leere Seite

    def test_post_beendet_die_sitzung(self):
        c = self._angemeldet()
        antwort = c.post('/logout/')
        self.assertEqual(antwort.status_code, 302)
        danach = c.get('/neu/')
        self.assertEqual(danach.status_code, 302)
        self.assertIn('/login/', danach['Location'])

    def test_angemeldete_seite_ist_nicht_zwischenspeicherbar(self):
        antwort = self._angemeldet().get('/neu/')
        self.assertIn('no-store', antwort['Cache-Control'])
