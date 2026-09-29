"""Öffentliche Meldeformulare: Anzeige übersetzt, gespeicherter Wert deutsch.

`/report/<id>/` (Aushang im Treppenhaus) und `/schaden/melden/` führen Räume,
Objekte und Anliegen als deutsche Wörter in ihren Alpine-Daten. Diese Wörter
werden gespeichert und dürfen sich nicht mit der Sprache ändern. Angezeigt
wird seit 29.09.2026 die Übersetzung aus core/templatetags/raumkatalog.py.

Ob die versteckten Felder wirklich den deutschen Wert senden, prüft der
Browser (e2e/tests/schadenformular.spec.ts, «Französisch angezeigt, deutsch
gespeichert»). Hier stehen die Prüfungen, die ohne Browser gehen.
"""
import re
from pathlib import Path

from django.test import Client, SimpleTestCase, TestCase
from django.utils import translation

from core.tests._helfer import _basis_objekte
from core.templatetags.raumkatalog import BEGRIFFE, raum_anzeige

WURZEL = Path(__file__).resolve().parents[2]
VORLAGEN = {
    'core/templates/core/public_ticket_form.html': ('categories: [', 'getCurrentObjects() {'),
    'core/templates/core/schaden_melden.html': ('raeume: [', 'selectRoom(raum) {'),
}


def _katalogwoerter(pfad, von, bis):
    """Alle angezeigten Katalogwörter (gross geschrieben) im Datenblock."""
    text = (WURZEL / pfad).read_text(encoding='utf-8')
    block = text[text.index(von):text.index(bis)]
    block = re.sub(r'//[^\n]*|/\*.*?\*/', '', block, flags=re.S)   # Kommentare
    block = re.sub(r"\bid: '[^']*'", '', block)   # Kennungen (`id: 'Schaden'`) werden nie angezeigt
    woerter = set(re.findall(r"'([^']+)'", block))
    return {w for w in woerter if w[0].isupper()}


class KatalogVollstaendigTests(SimpleTestCase):
    """Gegenprobe: einen Begriff aus BEGRIFFE entfernen — der Test wird rot
    und nennt ihn. Ohne diesen Wächter bliebe ein neuer Raum still deutsch."""

    def test_jedes_angezeigte_wort_hat_eine_uebersetzung(self):
        with translation.override(None):
            bekannt = {str(b) for b in BEGRIFFE}
        for pfad, (von, bis) in VORLAGEN.items():
            with self.subTest(vorlage=pfad):
                fehlt = sorted(_katalogwoerter(pfad, von, bis) - bekannt)
                self.assertEqual(fehlt, [], 'Diese Wörter fehlen in core/templatetags/raumkatalog.py')

    def test_schluessel_bleibt_deutsch_anzeige_folgt_der_sprache(self):
        with translation.override('fr'):
            html = raum_anzeige()
        self.assertIn('"Zimmer": "Chambre"', html)
        # «Zimmer» als Zimmerzahl bleibt davon unberührt (eigener Kontext).
        with translation.override('fr'):
            self.assertEqual(translation.gettext('Zimmer'), 'Pièces')


class OeffentlicheFormulareFranzoesischTests(TestCase):
    """Gegenprobe: `{% load i18n %}`/Auszeichnung aus einer der Vorlagen
    entfernen — der zugehörige Test wird rot."""

    def setUp(self):
        self.lg, _e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.cookies['django_language'] = 'fr'

    def test_aushang(self):
        seite = self.c.get(f'/report/{self.lg.id}/')
        self.assertContains(seite, 'Comment pouvons-nous vous aider ?')
        self.assertContains(seite, '"K\\u00fcche": "Cuisine"')
        self.assertContains(seite, '<html lang="fr">')

    def test_website(self):
        seite = self.c.get('/schaden/melden/')
        self.assertContains(seite, 'Dans quelle pièce ?')
        self.assertContains(seite, '"K\\u00fcche": "Cuisine"')
        self.assertContains(seite, '<option value="telefon">Merci de me téléphoner pour fixer un rendez-vous</option>')
