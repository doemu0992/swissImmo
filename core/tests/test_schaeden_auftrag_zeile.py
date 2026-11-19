"""Schadensliste: «Auftrag erteilen» steht nur, wo noch kein Auftrag läuft (UI-Zielbild).

Der Knopf versendet nichts: Er öffnet den Auftragsbereich des Schadens in der Schublade
(`?tab=handwerker`); Handwerker und Text wählt die Person dort, der Versand bleibt dort.
"""
from django.test import Client, TestCase

from core.tenancy import organisation_kontext as mandant


class AuftragErteilenZeileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.tests._isolation import MandantenFixture
        cls.a = MandantenFixture('K', '8000', 'Zürich')

    def _liste(self):
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            antwort = c.get('/neu/schaeden/')
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode()

    def test_offener_schaden_ohne_auftrag_hat_den_knopf(self):
        s = self.a.schaden
        with mandant(self.a.organisation):
            s.status = 'neu'
            s.save(update_fields=['status'])
            s.handwerker_auftraege.all().delete()
        html = self._liste()
        self.assertIn(f'/neu/schaeden/{s.pk}/?tab=handwerker', html)

    def test_schaden_mit_laufendem_auftrag_hat_keinen_knopf(self):
        s = self.a.schaden
        with mandant(self.a.organisation):
            s.status = 'in_bearbeitung'
            s.save(update_fields=['status'])
            self.assertTrue(s.handwerker_auftraege.exclude(status='storniert').exists())
        self.assertNotIn('?tab=handwerker', self._liste())
