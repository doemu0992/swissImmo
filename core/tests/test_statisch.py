"""Versionierte CSS-Adressen (`{% statisch %}`, core/templatetags/statisch.py).

Nach dem Ember-Deploy (26.10.2026) zeigte der Browser neues HTML mit alter,
zwischengespeicherter CSS — das Logo füllte die halbe Seite. Geprüft wird:
Die Adresse trägt die Prüfsumme des Inhalts, sie ändert sich mit dem Inhalt,
und jede Seite bindet ihre CSS so ein.
"""
import hashlib
import os
import pathlib
import re
import tempfile

from django.conf import settings
from django.template import Context, Template
from django.test import Client, SimpleTestCase, TestCase, override_settings

from core.templatetags import statisch

WURZEL = pathlib.Path(settings.BASE_DIR)


class StatischTagTests(SimpleTestCase):
    def test_adresse_traegt_die_pruefsumme_des_inhalts(self):
        inhalt = (WURZEL / 'static' / 'css' / 'schicht.css').read_bytes()
        erwartet = hashlib.sha256(inhalt).hexdigest()[:12]
        html = Template("{% load statisch %}{% statisch 'css/schicht.css' %}").render(Context())
        self.assertEqual(html, f'/static/css/schicht.css?v={erwartet}')

    def test_neuer_inhalt_neue_adresse(self):
        with tempfile.TemporaryDirectory() as ordner:
            datei = pathlib.Path(ordner) / 'probe.css'
            datei.write_text('a{color:red}')
            with override_settings(STATICFILES_DIRS=[ordner]):
                from django.contrib.staticfiles import finders
                finders.get_finder.cache_clear()
                try:
                    vorher = statisch.statisch('probe.css')
                    datei.write_text('a{color:blue}')
                    os.utime(datei, ns=(1, 2_000_000_000_000_000_000))   # andere Änderungszeit erzwingen
                    nachher = statisch.statisch('probe.css')
                finally:
                    finders.get_finder.cache_clear()
        self.assertIn('?v=', vorher)
        self.assertNotEqual(vorher, nachher)

    def test_unbekannte_datei_bleibt_eine_gewoehnliche_adresse(self):
        self.assertEqual(statisch.statisch('css/gibt-es-nicht.css'), '/static/css/gibt-es-nicht.css')


class SeitenBindenVersionierteCssEinTests(TestCase):
    def test_anmeldeseite_laedt_jede_eigene_css_mit_kennung(self):
        html = Client().get('/login/').content.decode()
        links = re.findall(r'<link rel="stylesheet" href="(/static/[^"]+)"', html)
        self.assertTrue(links, 'Die Anmeldeseite bindet keine CSS ein — dann prüft dieser Test nichts.')
        for href in links:
            self.assertRegex(href, r'\.css\?v=[0-9a-f]{12}$', f'{href} ohne Versionskennung')

    def test_keine_vorlage_bindet_eigene_css_ohne_kennung_ein(self):
        """Wer `{% static 'css/…' %}` schreibt, bringt den Zwischenspeicher-Fehler zurück."""
        funde = []
        for datei in (WURZEL / 'core' / 'templates').rglob('*.html'):
            text = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', ' ', datei.read_text(encoding='utf-8'), flags=re.S)
            if re.search(r"\{%\s*static\s+['\"]css/", text):
                funde.append(str(datei.relative_to(WURZEL)))
        self.assertEqual(funde, [])
