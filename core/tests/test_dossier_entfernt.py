"""Das «Dossier» (zweite, veraltete Oberfläche) ist entfallen (Etappe 3, DESIGN-08 / ROUTE-08).

Drei Routen und vier Vorlagen führten in eine eigene Hülle ohne Kopfzeile, mit toten Links
auf `/app/` und einem Skriptfehler. Aus der Anwendung verlinkte nichts darauf, aber
Lesezeichen und alte Mails konnten es noch tun: Die Adressen leiten deshalb auf die Akte um.

Gegenprobe: In `swiss_immo/urls.py` die drei `RedirectView`-Zeilen entfernen — die
Weiterleitungstests werden rot (404). Die alte View-Datei wieder anlegen und eine Vorlage
unter `core/templates/core/dossier/` — `test_keine_dossier_dateien` wird rot.
"""
from pathlib import Path

from django.test import Client, SimpleTestCase, TestCase
from django.urls import NoReverseMatch, reverse

from ._isolation import MandantenFixture

WURZEL = Path(__file__).resolve().parents[2]


class DossierEntfernt(SimpleTestCase):
    def test_keine_dossier_dateien(self):
        self.assertFalse((WURZEL / 'core' / 'views' / 'dossier.py').exists())
        self.assertFalse((WURZEL / 'core' / 'templates' / 'core' / 'dossier').exists())

    def test_keine_benannten_dossier_routen(self):
        for name in ('dossier_mieter', 'dossier_liegenschaft', 'dossier_vertrag'):
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(name, args=[1])


class DossierWeiterleitung(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def _ziele(self, m):
        return (
            (f'/dossier/mieter/{m.mieter.pk}/', f'/neu/personen/{m.mieter.pk}/'),
            (f'/dossier/liegenschaft/{m.liegenschaft.pk}/', f'/neu/liegenschaften/{m.liegenschaft.pk}/'),
            (f'/dossier/vertrag/{m.vertrag.pk}/', f'/neu/vertraege/{m.vertrag.pk}/'),
        )

    def test_alte_adresse_fuehrt_in_die_akte(self):
        c = Client()
        c.force_login(self.a.benutzer)
        for alt, neu in self._ziele(self.a):
            with self.subTest(alt=alt):
                r = c.get(alt)
                self.assertEqual((r.status_code, r['Location']), (302, neu))
                self.assertEqual(c.get(neu).status_code, 200)   # die Akte gibt es und sie öffnet

    def test_fremde_nummer_ergibt_in_der_akte_404(self):
        """Die Weiterleitung prüft nichts und öffnet nichts: Die Mandantenprüfung steht in der Akte."""
        c = Client()
        c.force_login(self.a.benutzer)
        for alt, _neu in self._ziele(self.b):
            with self.subTest(alt=alt):
                r = c.get(alt, follow=True)
                self.assertEqual(r.status_code, 404)
                self.assertNotContains(r, self.b.mieter.email, status_code=404)

    def test_ohne_anmeldung_landet_man_beim_login(self):
        r = Client().get(self._ziele(self.a)[0][0], follow=True)
        self.assertIn('/login', r.redirect_chain[-1][0])
