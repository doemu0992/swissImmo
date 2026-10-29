"""Öffentliche Meldeformulare: Anzeige übersetzt, gespeicherter Wert deutsch.

`/report/<id>/` (Aushang im Treppenhaus) und `/schaden/melden/` führen Räume,
Objekte und Anliegen als deutsche Wörter. Diese Wörter werden gespeichert und
dürfen sich nicht mit der Sprache ändern. Angezeigt wird die Übersetzung aus
core/templatetags/raumkatalog.py.

Bis Etappe 3 standen die Listen doppelt in den Alpine-Daten zweier Vorlagen, und
die Prüfung las die Wörter mit einem regulären Ausdruck aus dem Quelltext. Beide
Formulare sind jetzt EINE Vorlage (`core/schaden_melden.html`), und der Katalog
steht in Python — geprüft wird der Katalog selbst, nicht sein Abdruck.

Ob die Karten im Browser den deutschen Wert senden, prüft e2e/tests/schadenformular.spec.ts
(«Französisch angezeigt, deutsch gespeichert»). Hier stehen die Prüfungen ohne Browser.

Gegenproben (29.10.2026, je einzeln eingebaut, rot gesehen, zurückgebaut):
  * einen Begriff aus `BEGRIFFE` entfernen      → `test_jedes_angezeigte_wort…` rot
  * «Decke» in die Liste des Briefkastens        → `test_ein_briefkasten_hat_keine_decke…` rot
  * in `OBJEKTE` einen Raum weglassen            → `test_jeder_raum_hat_eine_eigene_liste` rot
  * zwei Räume mit demselben Zeichen             → `test_jeder_raum_hat_ein_eigenes_zeichen` rot
  * `value="{{ r.wert }}"` auf `{{ r.anzeige }}`  → `test_aushang` und `test_website` rot
"""
import re
from pathlib import Path

from django.test import Client, SimpleTestCase, TestCase
from django.utils import translation

from core.tests._helfer import _basis_objekte
from core.templatetags.raumkatalog import (
    ALLGEMEIN, ANDERES, BEGRIFFE, OBJEKTE, RAEUME, anliegen_karten, raum_anzeige, raum_katalog)

WURZEL = Path(__file__).resolve().parents[2]


class KatalogVollstaendigTests(SimpleTestCase):
    """Gegenprobe: einen Begriff aus BEGRIFFE entfernen — der Test wird rot
    und nennt ihn. Ohne diesen Wächter bliebe ein neuer Raum still deutsch."""

    def _woerter(self):
        woerter = {raum for raum, _z in RAEUME} | {ANDERES}
        for liste in ALLGEMEIN.values():
            woerter |= set(liste)
        for liste in OBJEKTE.values():
            woerter |= {name for name, _geraet in liste}
        return woerter

    def test_jedes_angezeigte_wort_hat_eine_uebersetzung(self):
        with translation.override(None):
            bekannt = {str(b) for b in BEGRIFFE}
        self.assertEqual(sorted(self._woerter() - bekannt), [],
                         'Diese Wörter fehlen in BEGRIFFE (core/templatetags/raumkatalog.py)')

    def test_schluessel_bleibt_deutsch_anzeige_folgt_der_sprache(self):
        with translation.override('fr'):
            html = raum_anzeige()
        self.assertIn('"Zimmer": "Chambre"', html)
        # «Zimmer» als Zimmerzahl bleibt davon unberührt (eigener Kontext).
        with translation.override('fr'):
            self.assertEqual(translation.gettext('Zimmer'), 'Pièces')

    def test_der_katalog_liefert_deutschen_wert_und_franzoesische_anzeige(self):
        with translation.override('fr'):
            kueche = raum_katalog()[0]
            kuehlschrank = next(o for o in kueche['objekte'] if o['wert'] == 'Kühlschrank')
            anliegen = anliegen_karten()
        self.assertEqual((kueche['wert'], kueche['anzeige']), ('Küche', 'Cuisine'))
        self.assertEqual((kuehlschrank['wert'], kuehlschrank['anzeige'], kuehlschrank['geraet']),
                         ('Kühlschrank', 'Réfrigérateur', True))
        self.assertEqual(anliegen[0]['wert'], 'Schadensmeldung')
        self.assertTrue(anliegen[0]['schaden'])
        self.assertEqual([a['schaden'] for a in anliegen], [True, False, False, False, False])

    def test_jeder_raum_hat_eine_eigene_liste(self):
        """Fehlt sie, fällt der Raum auf die allgemeinen Posten zurück — für einen Briefkasten
        hiess das «Licht, Steckdose, Fenster» (E2.51: sieben von zwölf Räumen)."""
        raeume = {raum for raum, _z in RAEUME}
        self.assertEqual(sorted(raeume - set(OBJEKTE)), [])
        self.assertEqual(sorted(set(OBJEKTE) - raeume), [])
        self.assertTrue(set(ALLGEMEIN) - {'alle'} <= raeume)

    def test_ein_briefkasten_hat_keine_decke_und_ein_balkon_keine_decke(self):
        katalog = {r['wert']: [o['wert'] for o in r['objekte']] for r in raum_katalog()}
        for unmoeglich in ('Decke', 'Boden', 'Wand', 'Steckdose', 'Fenster', 'Storen/Markise'):
            self.assertNotIn(unmoeglich, katalog['Briefkasten'])
        self.assertNotIn('Decke', katalog['Balkon/Terrasse'])

    def test_nichts_doppelt_und_jeder_raum_bietet_etwas_an(self):
        for r in raum_katalog():
            namen = [o['wert'] for o in r['objekte']]
            with self.subTest(raum=r['wert']):
                self.assertEqual([n for i, n in enumerate(namen) if n in namen[:i]], [], 'doppelt angeboten')
                self.assertGreater(len(namen), 1)
                self.assertEqual(namen[-1], ANDERES)   # der Ausweg ist immer da, immer zuletzt

    def test_jeder_raum_hat_ein_eigenes_zeichen_das_es_im_sprite_gibt(self):
        """Gemessen am Sprite, weil ein Tippfehler nichts zeichnet und nichts meldet (E2.51)."""
        sprite = (WURZEL / 'core' / 'templates' / 'fw' / '_zeichen.html').read_text(encoding='utf-8')
        zeichen = [z for _r, z in RAEUME]
        self.assertEqual(len(set(zeichen)), len(zeichen), 'zwei Räume teilen sich ein Zeichen')
        for z in zeichen:
            self.assertIn(f'id="z-{z}"', sprite, f'Das Zeichen «{z}» fehlt im Sprite')


class OeffentlicheFormulareFranzoesischTests(TestCase):
    """Gegenprobe: `{% load i18n %}`/Auszeichnung aus der Vorlage
    entfernen — der zugehörige Test wird rot."""

    def setUp(self):
        self.lg, _e, _m, _v = _basis_objekte()
        self.c = Client()
        self.c.cookies['django_language'] = 'fr'

    def _gemeinsam(self, seite):
        self.assertContains(seite, '<html lang="fr">')
        # Anzeige französisch, gespeicherter Wert deutsch
        self.assertContains(seite, '<span>Cuisine</span>')
        self.assertContains(seite, 'name="raum" value="Küche"')
        self.assertContains(seite, 'name="objekt" value="Kühlschrank"')
        self.assertContains(seite, '<span>Réfrigérateur</span>')
        self.assertContains(seite, 'name="kategorie" value="Schadensmeldung"')
        self.assertContains(seite, 'Dans quelle pièce ?')

    def test_aushang(self):
        self._gemeinsam(self.c.get(f'/report/{self.lg.id}/'))

    def test_website(self):
        seite = self.c.get('/schaden/melden/')
        self._gemeinsam(seite)
        self.assertContains(seite, '<option value="telefon">Merci de me téléphoner pour fixer un rendez-vous</option>')


class EineVorlageFuerBeideWegeTests(TestCase):
    """Die Schadenmeldung gab es dreifach; `/schaden/melden/` blieb falsch, weil nur der Aushang
    geändert war. Beide öffentlichen Wege rendern jetzt dieselbe Vorlage (bekannte-fallen §2)."""

    def setUp(self):
        self.lg, _e, _m, _v = _basis_objekte()

    def test_beide_wege_rendern_dieselbe_vorlage_mit_gleichen_raeumen(self):
        c = Client()
        aushang = c.get(f'/report/{self.lg.id}/')
        web = c.get('/schaden/melden/')
        self.assertTemplateUsed(aushang, 'core/schaden_melden.html')
        self.assertTemplateUsed(web, 'core/schaden_melden.html')
        raeume = lambda seite: re.findall(r'name="raum" value="([^"]+)"', seite.content.decode())  # noqa: E731
        self.assertEqual(raeume(aushang), [r for r, _z in RAEUME])
        self.assertEqual(raeume(web), raeume(aushang))

    def test_die_alten_vorlagen_sind_weg(self):
        for alt in ('core/templates/core/public_ticket_form.html', 'core/templates/modern_base.html'):
            self.assertFalse((WURZEL / alt).exists(), alt)

    def test_der_modus_bestimmt_die_felder(self):
        c = Client()
        aushang = c.get(f'/report/{self.lg.id}/').content.decode()
        web = c.get('/schaden/melden/').content.decode()
        for feld in ('einheit_id', 'anrede', 'hersteller', 'seriennummer'):
            self.assertIn(f'name="{feld}"', aushang)
            self.assertNotIn(f'name="{feld}"', web)
        self.assertIn('name="adresse"', web)
        self.assertNotIn('name="adresse"', aushang)
