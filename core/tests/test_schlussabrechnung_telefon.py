"""Schlussabrechnung am Telefon: die Knopfzeile bricht um.

Bei 390 px lagen «Schlussabrechnung als PDF», «Verbuchen (Kaution +
Nachzahlung)» und «Abbrechen» in einer nicht umbrechenden Flex-Zeile — die
Seite war 42 px breiter als der Bildschirm (gefunden beim Durchlauf aller
Seiten am 29.09.2026, in allen Sprachen).

Gegenprobe: `flex-wrap` aus der Knopfzeile in fw/schlussabrechnung.html
entfernen — der Test wird rot.
"""
from django.test import Client, TestCase

from core.tests._helfer import _basis_objekte, _team_user


class SchlussabrechnungKnopfzeileTests(TestCase):

    def test_knopfzeile_bricht_um(self):
        _lg, _e, _m, v = _basis_objekte()
        c = Client()
        c.force_login(_team_user('Verwalter'))
        seite = c.get(f'/neu/vertraege/{v.id}/schlussabrechnung/')
        self.assertEqual(seite.status_code, 200)
        self.assertContains(seite, '<div class="flex flex-wrap items-center gap-3">')
