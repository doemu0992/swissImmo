"""Die Einstellungen in sechs Gruppen: eine Quelle für Hub-Seite, Feld der Schiene und Brotkrumen.

Bis 17.11.2026 standen 17 Kacheln in einer Reihe; die Seiten dahinter hatten weder Menüband noch einen Weg zurück
(Audit 17.11.2026). `core/navigation.py` (`einstellungen_gruppen`) ist jetzt die einzige Liste.
"""
from django.test import Client, SimpleTestCase, TestCase
from django.urls import resolve

from core.navigation import EINSTELLUNGEN_ZIELE, einstellungen_gruppen, einstellungen_krume

from ._isolation import MandantenFixture


class GruppenAufbauTests(SimpleTestCase):

    def test_sechs_oder_weniger_gruppen_mit_eindeutigen_adressen(self):
        gruppen = einstellungen_gruppen()
        self.assertEqual(len(gruppen), 5, 'Die Gruppen der Einstellungen sind eine Entscheidung, kein Zufall')
        urls = [e['url'] for g in gruppen for e in g['eintraege']]
        self.assertEqual(len(urls), len(set(urls)), 'Eine Seite steht in zwei Gruppen')
        self.assertGreater(len(urls), 12, 'auffällig wenige Einstellungsseiten')

    def test_jede_adresse_loest_sich_auf_und_steht_unter_den_zielen(self):
        for g in einstellungen_gruppen():
            for e in g['eintraege']:
                with self.subTest(url=e['url']):
                    self.assertIsNotNone(resolve(e['url']).func)
                    self.assertIn(e['url'], EINSTELLUNGEN_ZIELE)

    def test_krume_nennt_die_gruppe(self):
        self.assertEqual(einstellungen_krume('/neu/benutzer/'), 'Team & Zugriff')
        self.assertEqual(einstellungen_krume('/neu/regelwerk/neu/'), 'Vorlagen & Regeln')
        self.assertEqual(einstellungen_krume('/neu/logbuch/'), 'Daten & Protokoll')
        # Hub und fremde Seiten tragen keine Gruppe; das Betreiber-Portal ist kein Teil der Verwaltung
        self.assertIsNone(einstellungen_krume('/neu/einstellungen/'))
        self.assertIsNone(einstellungen_krume('/neu/liegenschaften/'))
        self.assertIsNone(einstellungen_krume('/betreiber/'))


class GruppenSeitenTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.a.benutzer)

    def test_hub_und_schiene_zeigen_dieselben_seiten(self):
        r = self.client.get('/neu/einstellungen/')
        self.assertEqual(r.status_code, 200)
        hub = {k['url'] for g in r.context['gruppen'] for k in g['eintraege']}
        schiene = {k['url'] for g in r.context['fw_einstellungen_gruppen'] for k in g['eintraege']}
        self.assertEqual(hub, schiene)
        self.assertContains(r, 'data-fach-bereich="einst"')

    def test_einstellungsseite_traegt_die_krume_der_hub_nicht(self):
        r = self.client.get('/neu/benutzer/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'fw-einst-krumen')
        self.assertEqual(r.context['fw_einstellungen_krume'], 'Team & Zugriff')
        self.assertNotContains(self.client.get('/neu/einstellungen/'), 'fw-einst-krumen')
        # Gegenprobe: eine Seite ausserhalb der Einstellungen trägt sie nicht
        self.assertNotContains(self.client.get('/neu/liegenschaften/'), 'fw-einst-krumen')


class EinstellungenSeitenlisteTests(TestCase):
    """Modul 9: Auf jeder Einstellungsseite steht die Liste aller Einstellungen, die offene Seite ist markiert."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.a.benutzer)

    def test_unterseite_hat_liste_und_markiert_sich(self):
        r = self.client.get('/neu/vorlagen/')
        self.assertContains(r, 'id="fwEinstNav"')
        html = r.content.decode()
        nav = html[html.index('id="fwEinstNav"'):html.index('class="fw-einst-seite"')]
        self.assertEqual(nav.count('aria-current="page"'), 1)
        self.assertRegex(nav, r'href="/neu/vorlagen/[^"]*" data-zeile aria-current="page"')
        # Dieselben Seiten wie im Feld der Schiene (Rolle und Abo-Stufe gefiltert), keine mehr und keine weniger
        for g in r.context['fw_einstellungen_gruppen']:
            for k in g['eintraege']:
                self.assertIn('href="%s' % k['url'], nav)

    def test_uebersicht_im_selben_rahmen_fremde_seite_ohne_liste(self):
        r = self.client.get('/neu/einstellungen/')
        self.assertContains(r, 'id="fwEinstNav"')
        # Auf der Übersicht ist keine einzelne Seite offen
        html = r.content.decode()
        self.assertNotIn('aria-current="page"', html[html.index('id="fwEinstNav"'):html.index('class="fw-einst-seite"')])
        self.assertNotContains(self.client.get('/neu/liegenschaften/'), 'id="fwEinstNav"')

    def test_seitentitel_gleich_wie_in_der_liste(self):
        """Aus einem Guss: Der Titel der Seite ist der Name, unter dem sie in der Liste steht."""
        import html as _html
        import re
        for g in self.client.get('/neu/einstellungen/').context['fw_einstellungen_gruppen']:
            for k in g['eintraege']:
                r = self.client.get(k['url'])
                if r.status_code != 200:
                    continue
                m = re.search(r'<h1[^>]*>(.*?)</h1>', r.content.decode(), re.S)
                self.assertIsNotNone(m, k['url'])
                self.assertEqual(_html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip(), str(k['titel']), k['url'])
                # die Leiste markiert «Einstellungen», nicht einen Arbeitsbereich
                self.assertIn(r.context['nav'], r.context['fw_einstellungen_keys'], k['url'])
                # und genau eine Pfadzeile
                self.assertNotContains(r, 'fw-brotkrume', msg_prefix=k['url'])
