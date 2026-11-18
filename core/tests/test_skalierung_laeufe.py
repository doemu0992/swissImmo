"""Massenläufe und Mietzinsseiten wachsen in der Abfragezahl nicht mit dem Bestand (Roadmap 5.1).

Wie `test_skalierung_kernseiten`: Die Abfragezahl wird mit dem kleinen Bestand gezählt und muss mit dem grossen GENAU gleich
sein. Gemessen werden die lesenden Wege: der Mahnlauf im Probelauf (`dry_run`, schreibt nichts) und die Mietzinsseiten
(Übersicht). Der Sollstellungslauf SCHREIBT je Vertrag (Rechnung, Buchungen) und wächst deshalb zwangsläufig
mit; dort zählt die Idempotenz (siehe test_sollstellung*), nicht die Abfragezahl.
"""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from ._grossbestand import grossbestand_anlegen
from ._isolation import MandantenFixture

SEITEN = ['/neu/mietzins/']


class LaeufeSkalierenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        grossbestand_anlegen(cls.a.organisation, 2, 3)

    def _mahnlauf_abfragen(self):
        from core.services.automation import run_mahnlauf
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.a.organisation):
            with CaptureQueriesContext(connection) as c:
                run_mahnlauf(send_email=False, dry_run=True)
        return len(c)

    def test_mahnlauf_probelauf_waechst_nicht_mit_den_rechnungen(self):
        self._mahnlauf_abfragen()                           # aufwärmen
        klein = self._mahnlauf_abfragen()
        grossbestand_anlegen(self.a.organisation, 5, 6, ab=10)
        self.assertEqual(self._mahnlauf_abfragen(), klein)

    def test_mietzinsseiten_wachsen_nicht_mit_den_vertraegen(self):
        self.client.force_login(self.a.benutzer)
        for url in SEITEN:
            self.client.get(url)
        klein = {}
        for url in SEITEN:
            with CaptureQueriesContext(connection) as c:
                antwort = self.client.get(url)
            self.assertEqual(antwort.status_code, 200, url)
            klein[url] = len(c)
        grossbestand_anlegen(self.a.organisation, 5, 6, ab=10)
        self.client.force_login(self.a.benutzer)
        for url in SEITEN:
            with self.subTest(url=url):
                with self.assertNumQueries(klein[url]):
                    self.assertEqual(self.client.get(url).status_code, 200)
