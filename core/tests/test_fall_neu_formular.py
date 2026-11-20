"""«Neuer Fall»: keine riskante Vorbelegung (UI-Zielbild).

Früher stand die erste Art vorgewählt, und das Akte-Feld wählte durch einen leeren Vergleich
(`add` liefert bei Zahlen leer, '' == '') stillschweigend den letzten Mietvertrag vor. Wer nur den
Betreff tippte, legte einen Fall auf der falschen Akte an. Jetzt muss man Art und Akte selbst wählen.
"""
import re

from django.test import Client, TestCase

from core.tenancy import organisation_kontext as mandant


class FallNeuFormularTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.tests._isolation import MandantenFixture
        from faelle.management.commands.fallarten_anlegen import Command
        cls.a = MandantenFixture('K', '8000', 'Zürich')
        with mandant(cls.a.organisation):
            Command().handle(organisation=cls.a.organisation.pk)

    def _seite(self, adresse='/neu/faelle/neu/'):
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            antwort = c.get(adresse)
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode()

    def test_keine_art_und_keine_akte_vorgewaehlt(self):
        html = self._seite()
        self.assertNotRegex(html, r'name="fallart"[^>]*\bchecked\b')
        self.assertNotRegex(html, r'<option value="(lg|mv)-\d+"\s+selected')
        self.assertIn('data-knopf-erst-gueltig', html)
        self.assertEqual(len(re.findall(r'name="fallart"[^>]*\brequired\b', html)),
                         len(re.findall(r'name="fallart"', html)))

    def test_akte_aus_adresse_wird_vorgewaehlt(self):
        html = self._seite(f'/neu/faelle/neu/?akte=mv-{self.a.vertrag.pk}')
        self.assertRegex(html, rf'<option value="mv-{self.a.vertrag.pk}"\s+selected')
        self.assertEqual(len(re.findall(r'<option value="(?:lg|mv)-\d+"\s+selected', html)), 1)

    def test_frist_chips_vorhanden(self):
        html = self._seite()
        for tage in ('0', '7', '30', 'keine'):
            self.assertIn(f'data-frist-tage="{tage}"', html)
