"""Tranche «Rest-Oberfläche»: die letzten deutschen Stellen der Arbeitsoberfläche.

Gefunden mit einem Durchlauf aller Seiten auf Französisch (29.09.2026):
Beschriftungstabellen in den Views (Bewerbungsspalten, Ticket-Status,
Filterchips) und die Vorlagen Kündigung erfassen, Schlussabrechnung,
Untermiete, Mängelrüge.

Bewusst deutsch bleiben dort Rechtssätze mit Artikelverweis (Art. 257d,
262, 266a ff. OR, Art. 18 MWSTG) und die Zustellarten der Kündigung.

Gegenproben:
- in core/views/fw/mietprozess.py bei `'Neu eingegangen'` das
  `gettext_lazy(…)` entfernen — `test_bewerbungen_franzoesisch` wird rot;
- in core/templates/fw/kuendigung_form.html die Option «Einschreiben (Mieter)»
  durch eine Übersetzung («Recommandé (locataire)») ersetzen —
  `test_kuendigung_rechtsbegriffe_bleiben_deutsch` wird rot.
"""
from datetime import date

from django.test import Client, TestCase

from core.tests._helfer import _basis_objekte, _team_user


class RestOberflaecheTests(TestCase):

    def setUp(self):
        self.lg, self.e, self.m, self.v = _basis_objekte()
        self.c = Client()
        self.c.force_login(_team_user())
        self.c.cookies['django_language'] = 'fr'

    def test_bewerbungen_franzoesisch(self):
        from mietprozess.models import Mietbewerbung
        Mietbewerbung.objects.create(einheit=self.e, vorname='Anna', nachname='Test', email='a@example.ch',
                                     geburtsdatum=date(1990, 1, 1), status='neu')
        seite = self.c.get('/neu/bewerbungen/').content.decode()
        self.assertIn('Nouvellement reçu', seite)
        self.assertNotIn('Neu eingegangen', seite)

    def test_schaeden_filter_franzoesisch(self):
        seite = self.c.get('/neu/schaeden/').content.decode()
        self.assertIn('Attend un tiers (', seite)
        self.assertNotIn('Wartet auf Dritte', seite)

    def test_kuendigung_franzoesisch(self):
        seite = self.c.get(f'/neu/vertraege/{self.v.id}/kuendigen/').content.decode()
        self.assertIn('Enregistrer la résiliation', seite)
        self.assertIn('Prochain terme de résiliation ordinaire', seite)

    def test_kuendigung_rechtsbegriffe_bleiben_deutsch(self):
        seite = self.c.get(f'/neu/vertraege/{self.v.id}/kuendigen/').content.decode()
        self.assertIn('Einschreiben (Mieter)', seite)
        self.assertIn('nur mit amtlich genehmigtem Formular gültig', seite)

    def test_schlussabrechnung_und_briefe_franzoesisch(self):
        for pfad, erwartet in ((f'/neu/vertraege/{self.v.id}/schlussabrechnung/', 'Décompte final au départ'),
                               (f'/neu/vertraege/{self.v.id}/maengelruege/', "Créer l'avis de défaut en PDF"),
                               (f'/neu/vertraege/{self.v.id}/untermiete/', 'Sous-location — accord / refus')):
            with self.subTest(pfad=pfad):
                antwort = self.c.get(pfad)
                self.assertEqual(antwort.status_code, 200)
                self.assertContains(antwort, erwartet, html=False)
