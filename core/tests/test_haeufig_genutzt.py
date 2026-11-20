"""«Häufig genutzt» (UI-Zielbild): feste Liste mit drei Einträgen auf Berichte und Einstellungen, kein lernendes Verfahren."""
import html as htmlmod
import re

from django.test import Client, TestCase

from core.tenancy import organisation_kontext as mandant


class HaeufigGenutztTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.tests._isolation import MandantenFixture
        cls.a = MandantenFixture('K', '8000', 'Zürich')

    def _seite(self, adresse):
        c = Client()
        c.force_login(self.a.benutzer)
        with mandant(self.a.organisation):
            antwort = c.get(adresse)
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode()

    def _block(self, html):
        start = html.find('<div data-haeufig')
        self.assertGreaterEqual(start, 0, 'Block «Häufig genutzt» fehlt')
        ende = min(i for i in (html.find('data-gruppe', start), html.find('data-keine', start)) if i > 0)
        return html[start:ende]

    def _titel(self, html):
        return [htmlmod.unescape(t) for t in re.findall(r'class="fw-t">([^<]+)<', self._block(html))]

    def test_berichte_haeufig_drei_feste_eintraege(self):
        html = self._seite('/neu/berichte/')
        self.assertIn('Häufig genutzt', html)
        self.assertEqual(self._titel(html), ['Mieterspiegel', 'Debitoren-Altersstruktur', 'MWST-Abrechnung'])

    def test_einstellungen_haeufig_drei_feste_eintraege(self):
        html = self._seite('/neu/einstellungen/')
        self.assertEqual(self._titel(html), ['Benutzer & Rollen', 'Zahlungsfreigabe', 'Vorlagen'])

    def test_haeufig_zeilen_zaehlen_nicht_als_suchtreffer(self):
        """Die Duplikate tragen kein `data-zeile`: Die Live-Suche filtert nur die Liste, nicht die feste Auswahl."""
        for adresse in ('/neu/berichte/', '/neu/einstellungen/'):
            html = self._seite(adresse)
            self.assertNotIn('data-zeile', self._block(html))
