"""Keine `:has()`-Regel am Seitengerüst: Sie macht jede kleine Änderung am Bildschirm teuer.

Gemeldet 24.11.2026: «Software wurde extrem langsam.» Gemessen über acht Seiten (Maus über Zeilen, 40 kleine Änderungen im
Inhalt): 113 ms Stilberechnung vor «Aus einem Guss», 900 ms danach, 1500 ms mit der Portal-Seitenleiste. Ursache waren
`:has()`-Selektoren an den Wurzeln der Seite (`.fw-inhalt:not(:has(table))…`, `.fw-app:has(>#pSidebar)`,
`.fw-mit-schiene:has(#fwTabbar)`): Der Browser muss sie bei jeder Änderung irgendwo darunter neu auswerten. Nach dem
Umbau auf Klassen: 98 ms.

Regel: Was die ganze Seite betrifft, steht als Klasse am Gerüst (vom Server oder einmal per Skript gesetzt), nie als
`:has()`. `:has()` bleibt erlaubt, wo sein Träger ein kleiner Baustein ist (ein Feld, eine Zeile, eine Karte).
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CSS = Path(settings.BASE_DIR) / 'static' / 'css' / 'schicht.css'

#: Träger, an denen `:has()` die ganze Seite neu berechnen lässt.
GERUEST = ('html', 'body', 'main', '.fw-body', '.fw-app', '.fw-haupt', '.fw-inhalt', '.fw-portal-inhalt', '.fw-mit-schiene',
           '.fw-portal-app', '.fw-aussen', '.fw-aussen-inhalt', '.fw-einst-spalten', '.fw-einst-seite')

#: Obergrenze aller `:has(` in der ausgelieferten Schicht (Stand 24.11.2026). Sinkt sie, hier nachziehen.
OBERGRENZE = 31


def _selektoren():
    text = re.sub(r'/\*.*?\*/', ' ', CSS.read_text(), flags=re.S)
    for kopf in re.findall(r'([^{}]+)\{', text):
        for selektor in kopf.split(','):
            if ':has(' in selektor:
                yield ' '.join(selektor.split())


class StilLeistungTests(SimpleTestCase):

    def test_kein_has_am_seitengeruest(self):
        befunde = []
        for s in _selektoren():
            # der Träger ist das einfache Element direkt vor `:has(` (auch hinter `:not(`)
            for traeger in re.findall(r'([.#]?[\w-]+)(?::not\([^()]*\))*:(?:not\(\s*:)?has\(', s):
                if traeger in GERUEST:
                    befunde.append(s[:140])
        self.assertEqual(befunde, [], 'Diese Regeln hängen `:has()` an das Seitengerüst — bitte als Klasse lösen '
                                      '(siehe static/js/fw-lesespalte.js, CONTRIBUTING.md «Leistung»).')

    def test_die_suche_erkennt_die_drei_alten_regeln(self):
        """Gegenprobe: genau die Regeln, die die Seite langsam gemacht haben, müssen anschlagen."""
        muster = r'([.#]?[\w-]+)(?::not\([^()]*\))*:(?:not\(\s*:)?has\('
        for alt, traeger in (('.fw-inhalt:not(:has(table)):not(:has(.fw-cockpit))>*', '.fw-inhalt'),
                             ('html .fw-app:has(>#pSidebar)>.fw-haupt', '.fw-app'),
                             ('.fw-mit-schiene:has(#fwTabbar) .fw-toasts', '.fw-mit-schiene')):
            self.assertIn(traeger, re.findall(muster, alt), alt)
            self.assertIn(traeger, GERUEST)

    def test_anzahl_has_waechst_nicht(self):
        anzahl = CSS.read_text().count(':has(')
        self.assertLessEqual(anzahl, OBERGRENZE, f'{anzahl} `:has(` in der Schicht, erlaubt sind {OBERGRENZE}.')

    def test_die_lesespalte_ist_eine_klasse_und_das_skript_wird_geladen(self):
        css = CSS.read_text()
        self.assertIn('.fw-inhalt.fw-lesespalte>*{max-width:920px}', css)
        vorlagen = Path(settings.BASE_DIR) / 'core' / 'templates'
        for name in ('fw/base.html', 'core/portal_base.html'):
            self.assertIn("js/fw-lesespalte.js", (vorlagen / name).read_text(), name)
