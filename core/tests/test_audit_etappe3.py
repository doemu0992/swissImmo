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
