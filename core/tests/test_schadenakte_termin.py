"""Bestandsfehler im Reiter «Handwerker» der Schadenakte (27.10.2026).

Beim vereinbarten Termin stand `{% zeichen 'kalender' %}` — ein Zeichen, das
es nicht gibt (docs/ZEICHEN.md: `termin`). Mit `DEBUG=True` — Entwicklung und
der e2e-Server aus `e2e/run-server.sh` — wirft der Baustein, und die ganze
Schadenakte antwortete mit 500, sobald ein Termin stand. In Produktion
(`DEBUG=False`) blieb das Zeichen still leer. Gefunden beim Bildschirmtest von
Modul 3: Mit dem Handwerkerportal setzt auch der Handwerker Termine.

Der Test läuft deshalb mit `DEBUG=True` — sonst sieht er den Fehler nicht.
"""
from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from ._isolation import MandantenFixture


class SchadenakteMitTerminTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    @override_settings(DEBUG=True)
    def test_akte_mit_vereinbartem_termin_laedt(self):
        from tickets.models import HandwerkerAuftrag
        HandwerkerAuftrag.alle_organisationen.filter(pk=self.a.auftrag.pk).update(
            termin_am=timezone.now() + timedelta(days=1), termin_status='vereinbart')
        c = Client(raise_request_exception=False)
        c.force_login(self.a.benutzer)
        r = c.get(f'/neu/schaeden/{self.a.schaden.pk}/?tab=handwerker')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Termin:')
