"""Datenschutzerklärung in Deutsch, Französisch und Italienisch (FUNK-15, Entscheid D11).

Deutsch ist die massgebende Fassung. Französisch und Italienisch sind ENTWÜRFE einer Übersetzung, nicht
rechtlich geprüft, und müssen das auf der Seite selbst sagen: Eine Übersetzung, die wie eine geprüfte
aussieht, ist schlimmer als keine. Diese Tests halten fest:

* die Sprache wird gewählt (Cookie wie bei der Sprachwahl, dazu der Browser) und andere Sprachen zeigen Deutsch;
* FR und IT tragen den Entwurfshinweis, DE trägt ihn nicht;
* alle drei Fassungen haben denselben Aufbau (Abschnitte, Tabelle, Fallunterscheidung «Verantwortlicher»), damit
  eine Änderung am deutschen Text nicht still in einer Übersetzung fehlt;
* der Verantwortliche wird in jeder Sprache genannt.

Gegenprobe: den Entwurfshinweis aus `_text_fr.html` streichen, oder einen Abschnitt in `_text_it.html`
auslassen, und je ein Test wird rot.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from ._isolation import MandantenFixture

VORLAGEN = Path(settings.BASE_DIR) / 'core/templates/core/datenschutz'


def _gerueest(sprache):
    """Aufbau einer Fassung: Reihenfolge der Abschnitte, Tabellenzeilen und Vorlagenverzweigungen."""
    text = (VORLAGEN / f'_text_{sprache}.html').read_text(encoding='utf-8')
    text = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '', text, flags=re.S)
    return re.findall(r'<section>|</section>|<h2|<table|<tr|<th|<td|<strong>|\{%\s*(?:if|else|endif)[^%]*%\}|'
                      r'\{\{\s*verwaltung\.[a-z]+', text)


class AufbauTests(SimpleTestCase):
    def test_alle_fassungen_haben_denselben_aufbau(self):
        referenz = _gerueest('de')
        self.assertGreater(len(referenz), 40)
        for sprache in ('fr', 'it'):
            with self.subTest(sprache=sprache):
                self.assertEqual(_gerueest(sprache), referenz,
                                 f'Aufbau von _text_{sprache}.html weicht von der deutschen Fassung ab: '
                                 'eine Änderung am deutschen Text fehlt in der Übersetzung (oder umgekehrt).')

    def test_entwuerfe_tragen_den_hinweis_die_deutsche_fassung_nicht(self):
        fr = (VORLAGEN / '_text_fr.html').read_text(encoding='utf-8')
        it = (VORLAGEN / '_text_it.html').read_text(encoding='utf-8')
        de = (VORLAGEN / '_text_de.html').read_text(encoding='utf-8')
        self.assertIn('Traduction provisoire, non vérifiée juridiquement', fr)
        self.assertIn('Traduzione provvisoria, non verificata dal punto di vista giuridico', it)
        for text in (fr, it):
            self.assertIn('role="note"', text)
        self.assertNotIn('role="note"', de)
        self.assertNotIn('provisoire', de)


class SeiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def _hole(self, sprache=None):
        client = Client()
        if sprache:
            client.cookies[settings.LANGUAGE_COOKIE_NAME] = sprache
        return client.get(reverse('public_datenschutz_objekt', args=[self.a.einheit.pk]), HTTP_HOST='localhost')

    def test_deutsch_ist_die_voreinstellung_ohne_hinweis(self):
        antwort = self._hole()
        self.assertContains(antwort, 'Verantwortliche Stelle')
        self.assertNotContains(antwort, 'Traduction provisoire')
        self.assertNotContains(antwort, 'Traduzione provvisoria')
        self.assertContains(antwort, '<html lang="de">')

    def test_franzoesisch_mit_entwurfshinweis_und_verantwortlichem(self):
        antwort = self._hole('fr')
        self.assertContains(antwort, 'Responsable du traitement')
        self.assertContains(antwort, 'Traduction provisoire, non vérifiée juridiquement')
        self.assertContains(antwort, self.a.organisation.firma)
        self.assertContains(antwort, '<html lang="fr">')
        self.assertNotContains(antwort, 'Verantwortliche Stelle')

    def test_italienisch_mit_entwurfshinweis_und_verantwortlichem(self):
        antwort = self._hole('it')
        self.assertContains(antwort, 'Titolare del trattamento')
        self.assertContains(antwort, 'Traduzione provvisoria, non verificata dal punto di vista giuridico')
        self.assertContains(antwort, self.a.organisation.firma)
        self.assertContains(antwort, '<html lang="it">')

    def test_andere_sprachen_zeigen_die_deutsche_fassung(self):
        antwort = self._hole('en')
        self.assertContains(antwort, 'Verantwortliche Stelle')
        self.assertContains(antwort, '<html lang="de">')

    def test_die_sprachwahl_ist_auf_der_seite(self):
        self.assertContains(self._hole('fr'), 'name="language"')
