"""Etappe 3 aus docs/AUDIT-SAAS-NIVEAU.md: Komponentenschicht und Typografie."""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase, Client, SimpleTestCase

from ._helfer import _team_user, _basis_objekte

VORLAGEN = Path(settings.BASE_DIR) / 'core' / 'templates'


class EmbedHuelle(SimpleTestCase):
    """Die Iframe-Modals (Abnahme, Ausschreibung, Schlussabrechnung) liefen bis
    29.09.2026 ohne Stilschicht und ohne Icon-Sprite — gemessen mit Chromium:
    keine Karten, keine Knöpfe, 570 px breit bei 384 px Bildschirm."""

    EINBINDUNGEN = ("{% include 'fw/_assets.html' %}", "{% include 'fw/_schicht_link.html' %}",
                    "{% include 'fw/_zeichen.html' %}")

    def test_embed_huelle_laedt_was_base_laedt(self):
        base = (VORLAGEN / 'fw' / 'base.html').read_text(encoding='utf-8')
        embed = (VORLAGEN / 'fw' / 'base_embed.html').read_text(encoding='utf-8')
        for zeile in self.EINBINDUNGEN:
            self.assertIn(zeile, base, zeile)
            self.assertIn(zeile, embed, zeile)


class EmbedSeite(TestCase):

    def test_abnahme_im_modal_hat_schicht_und_symbole(self):
        _lg, _e, _m, v = _basis_objekte()
        c = Client()
        c.force_login(_team_user())
        body = c.get(f'/neu/vertraege/{v.id}/abnahme/neu/?embed=1').content.decode()
        self.assertIn('css/schicht.css', body)
        # Jedes verwendete Symbol muss in der Seite definiert sein.
        benutzt = set(re.findall(r'href="#(z-[a-z0-9-]+)"', body))
        definiert = set(re.findall(r'<symbol id="(z-[a-z0-9-]+)"', body))
        self.assertTrue(benutzt)
        self.assertEqual(benutzt - definiert, set())


class Schriftgrade(SimpleTestCase):
    """Vier kleine Schriftgrade statt acht frei gewählter Pixelwerte, und keine
    Gewichte über 700 — IBM Plex Sans wird nur bis Bold (700) ausgeliefert
    (`static/css/schriften.css`); alles darüber zeichnete der Browser als
    künstliches Fett."""

    def _fw_vorlagen(self):
        for datei in (VORLAGEN / 'fw').rglob('*.html'):
            if datei.name != '_schicht.html':
                yield datei, datei.read_text(encoding='utf-8')

    def test_keine_frei_gewaehlten_pixelgroessen_in_fw(self):
        treffer = [f'{d.relative_to(VORLAGEN)}: {m}' for d, text in self._fw_vorlagen()
                   for m in re.findall(r'(?<![\w:-])text-\[[0-9.]+px\]', text)]
        self.assertEqual(treffer, [], 'Statt text-[Npx]: fw-fs-mikro/klein/fein/text.')

    def test_keine_gewichte_ueber_700(self):
        treffer = [str(d.relative_to(VORLAGEN)) for d, text in self._fw_vorlagen()
                   if re.search(r'\bfont-(black|extrabold)\b|font-weight: *(800|900)', text)]
        self.assertEqual(treffer, [])

    def test_schicht_hat_keine_gewichte_ueber_700_ausser_font_awesome(self):
        schicht = (VORLAGEN / 'fw' / '_schicht.html').read_text(encoding='utf-8')
        for regel in re.findall(r'\{[^{}]*font-weight:(?:800|900)[^{}]*\}', schicht):
            # Font Awesome «Solid» IST das Gewicht 900 — dort ist es die Glyphe.
            self.assertIn('Font Awesome', regel)

    def test_die_skala_ist_definiert(self):
        schicht = (VORLAGEN / 'fw' / '_schicht.html').read_text(encoding='utf-8')
        benutzt = {m for _d, text in self._fw_vorlagen()
                   for m in re.findall(r'\bfw-fs-[a-z]+\b', text)}
        definiert = set(re.findall(r'\.(fw-fs-[a-z]+)\{', schicht))
        self.assertTrue(benutzt)
        self.assertEqual(benutzt - definiert, set())
