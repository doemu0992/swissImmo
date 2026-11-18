"""Die Rolle wird je Anfrage einmal gelesen, nicht je Frage.

Gemessen am 15.11.2026 auf `/neu/einstellungen/`: 14 Abfragen, bevor die Seite
etwas tut; acht davon lasen dieselben Mitgliedschaften (sechsmal `hat_rolle`,
zweimal `eigene_rollen`). Seit `core.auth.rollen_der_anfrage` ist es eine.

Der Test zählt die Abfragen auf die Mitgliedschaftstabelle, die nach der Rolle
fragen — nicht die Gesamtzahl, die sich mit jeder Kopfzeile ändert.

Gegenprobe (15.11.2026): Merker in `rollen_der_anfrage` umgangen (immer neu
lesen) -> `test_rolle_wird_je_anfrage_einmal_gelesen` rot (8 statt 1);
Signal in `core/signals.py` entfernt -> `test_rollenwechsel_wirkt_sofort` rot.
"""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.auth import ROLLE_VERWALTER, eigene_rollen, hat_rolle
from core.tenancy import organisation_kontext
from crm.models import Mitgliedschaft

from ._isolation import MandantenFixture


def _rollenabfragen(abfragen):
    tabelle = Mitgliedschaft._meta.db_table
    return [a['sql'] for a in abfragen
            if tabelle in a['sql'] and '"rolle"' in a['sql'] and 'JOIN' not in a['sql']]


class GrundlastTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_rolle_wird_je_anfrage_einmal_gelesen(self):
        self.client.force_login(self.a.benutzer)
        self.client.get('/neu/einstellungen/')          # Aufwärmen
        with CaptureQueriesContext(connection) as c:
            antwort = self.client.get('/neu/einstellungen/')
        self.assertEqual(antwort.status_code, 200)
        rollen = _rollenabfragen(c.captured_queries)
        self.assertLessEqual(len(rollen), 1, rollen)

    def test_viele_fragen_eine_abfrage(self):
        benutzer = type(self.a.benutzer).objects.get(pk=self.a.benutzer.pk)
        with organisation_kontext(self.a.organisation):
            with self.assertNumQueries(1):
                for _ in range(5):
                    hat_rolle(benutzer, [ROLLE_VERWALTER])
                    eigene_rollen(benutzer)

    def test_merker_gilt_nur_fuer_die_aktive_organisation(self):
        """Wer bei A eine Rolle hat, hat sie bei B nicht — auch nicht aus dem Merker."""
        benutzer = type(self.a.benutzer).objects.get(pk=self.a.benutzer.pk)
        with organisation_kontext(self.a.organisation):
            self.assertTrue(eigene_rollen(benutzer))
        with organisation_kontext(self.b.organisation):
            self.assertEqual(eigene_rollen(benutzer), set())
            self.assertFalse(hat_rolle(benutzer, list(eigene_rollen(self.b.benutzer))))

    def test_rollenwechsel_wirkt_sofort(self):
        """Eine entzogene Rolle gilt in derselben Anfrage nicht weiter."""
        benutzer = type(self.a.benutzer).objects.get(pk=self.a.benutzer.pk)
        with organisation_kontext(self.a.organisation):
            vorher = eigene_rollen(benutzer)
            self.assertTrue(vorher)
            self.assertTrue(hat_rolle(benutzer, list(vorher)))
            for m in Mitgliedschaft.objects.filter(benutzer=benutzer):
                m.delete()
            self.assertEqual(eigene_rollen(benutzer), set())
            self.assertFalse(hat_rolle(benutzer, list(vorher)))

    def test_rueckgabe_ist_eine_kopie(self):
        benutzer = type(self.a.benutzer).objects.get(pk=self.a.benutzer.pk)
        with organisation_kontext(self.a.organisation):
            eigene_rollen(benutzer).add('Erfunden')
            self.assertNotIn('Erfunden', eigene_rollen(benutzer))
