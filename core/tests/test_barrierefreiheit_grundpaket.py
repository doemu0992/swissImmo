"""Roadmap Nr. 21: Barrierefreiheit, Grundpaket — statische Wächter (der Browser-Test steht in e2e/tests/barrierefreiheit.spec.ts).

* Sprunglink «Zum Inhalt» und ein anspringbarer Hauptbereich (WCAG 2.4.1).
* Tabellenköpfe tragen `scope` (WCAG 1.3.1).
* Reiter sind Reiter: Rolle, Auswahlzustand, Bezug zur Fläche (WAI-ARIA).
* Kein Zoomverbot im viewport-Meta (WCAG 1.4.4).
* Links tragen kein `aria-pressed` (das gilt nur für Schalter); für den Zustand gilt `aria-current`.
* Das Modal sperrt den Rest der Seite (`inert`), statt es nur zu behaupten.
"""
import pathlib
import re

from django.test import SimpleTestCase

VORLAGEN = pathlib.Path('core/templates')
KOMMENTAR = re.compile(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|<!--.*?-->|\{#.*?#\}', re.S)


def _vorlagen():
    for pfad in sorted(VORLAGEN.rglob('*.html')):
        yield pfad, KOMMENTAR.sub(' ', pfad.read_text(encoding='utf-8'))


def th_ohne_scope(text):
    return [m.group(0) for m in re.finditer(r'<th\b[^>]*>', text) if 'scope' not in m.group(0)]


def link_mit_pressed(text):
    return [m.group(0)[:80] for m in re.finditer(r'<a\b[^>]*>', text) if 'aria-pressed' in m.group(0)]


class GrundpaketTests(SimpleTestCase):

    def test_alle_tabellenkoepfe_haben_scope(self):
        schlecht = {str(p): th_ohne_scope(t) for p, t in _vorlagen() if th_ohne_scope(t)}
        self.assertEqual(schlecht, {}, '`<th>` ohne scope="col"/"row" (WCAG 1.3.1).')

    def test_kein_zoomverbot(self):
        schlecht = [str(p) for p, t in _vorlagen() if re.search(r'user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(\.0)?\b', t)]
        self.assertEqual(schlecht, [], 'viewport-Meta verbietet das Zoomen (WCAG 1.4.4).')

    def test_links_ohne_aria_pressed(self):
        schlecht = {str(p): link_mit_pressed(t) for p, t in _vorlagen() if link_mit_pressed(t)}
        self.assertEqual(schlecht, {}, '`aria-pressed` gehört an Schalter; ein Link trägt `aria-current`.')

    def test_sprunglink_und_hauptbereich(self):
        base = (VORLAGEN / 'fw/base.html').read_text(encoding='utf-8')
        self.assertIn('href="#fw-inhalt" class="fw-skip"', base)
        for datei in ('fw/base.html', 'core/portal_base.html', 'core/handwerker_base.html', 'core/aussen_base.html'):
            text = (VORLAGEN / datei).read_text(encoding='utf-8')
            self.assertRegex(text, r'<main\b[^>]*id="fw-inhalt"[^>]*tabindex="-1"', datei)

    def test_reiterleiste_ist_ein_reitermuster(self):
        text = (VORLAGEN / 'fw/_detail_tabs.html').read_text(encoding='utf-8')
        for erwartet in ('role="tablist"', 'role="tab"', 'aria-selected=', 'aria-controls='):
            self.assertIn(erwartet, text)
        base = (VORLAGEN / 'fw/base.html').read_text(encoding='utf-8')
        self.assertIn("setAttribute('aria-selected'", base)          # fwTab führt den Zustand nach
        self.assertIn("'ArrowRight'", base)                          # Pfeiltasten wechseln den Reiter

    def test_modal_sperrt_den_rest_der_seite(self):
        text = (VORLAGEN / 'fw/_fwmodal.html').read_text(encoding='utf-8')
        self.assertIn('s.inert = true', text)
        self.assertIn('fwModalSperren(true)', text)
        self.assertIn('fwModalSperren(false)', text)


class WaechterWirkenTests(SimpleTestCase):
    """Gegenprobe: Die Wächter erkennen die Verstösse, die sie melden sollen."""

    def test_th_ohne_scope_wird_erkannt(self):
        self.assertEqual(th_ohne_scope('<th>A</th><th scope="col">B</th>'), ['<th>'])

    def test_link_mit_pressed_wird_erkannt(self):
        self.assertEqual(len(link_mit_pressed('<a href="#" aria-pressed="true">x</a><button aria-pressed="true">')), 1)
