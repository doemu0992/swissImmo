"""Rote Zahlen an den einzelnen Seiten im Feld der Schiene (`/neu/leistenzahlen/`, Schlüssel `punkte`).

Wer bei «Heute» eine Zahl sieht, soll im Feld sehen, WOHIN er muss (18.11.2026). Jede Zahl zählt dasselbe wie ihre Seite.
"""
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from ._helfer import _team_user


class PunktzahlenTests(TestCase):

    def setUp(self):
        from core.models import Pendenz
        self.Pendenz = Pendenz
        self.c = Client()
        self.c.force_login(_team_user())
        self.heute = timezone.localdate()

    def _punkte(self):
        r = self.c.get('/neu/leistenzahlen/')
        self.assertEqual(r.status_code, 200)
        return r.json()['punkte']

    def test_ohne_etwas_zu_tun_ist_die_antwort_leer(self):
        self.assertEqual(self._punkte(), {})

    def test_ueberfaellige_pendenz_zaehlt_bei_pendenzen_und_fristen(self):
        self.Pendenz.objects.create(titel='Zu spät', faellig_am=self.heute - timedelta(days=3))
        p = self._punkte()
        self.assertEqual(p.get('pendenzen'), 1)
        self.assertEqual(p.get('fristen'), 1)

    def test_heute_faellige_pendenz_zaehlt_bei_pendenzen_aber_noch_nicht_bei_fristen(self):
        self.Pendenz.objects.create(titel='Heute', faellig_am=self.heute)
        p = self._punkte()
        self.assertEqual(p.get('pendenzen'), 1)
        self.assertNotIn('fristen', p, 'Die Seite «Fristen» nennt nur Überfälliges überfällig')

    def test_gegenprobe_erledigte_und_kuenftige_zaehlen_nicht(self):
        self.Pendenz.objects.create(titel='Erledigt', faellig_am=self.heute - timedelta(days=1), erledigt=True)
        self.Pendenz.objects.create(titel='Später', faellig_am=self.heute + timedelta(days=5))
        self.assertEqual(self._punkte(), {})

    def test_uebersicht_traegt_die_zahl_von_heute(self):
        self.Pendenz.objects.create(titel='Heute', faellig_am=self.heute)
        r = self.c.get('/neu/leistenzahlen/').json()
        self.assertEqual(r['punkte'].get('dashboard'), r['heute'])
