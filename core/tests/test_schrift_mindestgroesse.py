"""Schrift mindestens 12 px (UI-Zielbild, Phase 1, Befund 9).

Text unter 12 px ist am Telefon und für ältere Augen schlecht lesbar. In der Stilschicht darf keine Regel mit weniger
als 12 px stehen, ausser den hier genannten (Zahlen in kleinen Kreisen, Diagrammachsen, Mikroschrift). Neue Ausnahmen
brauchen einen Eintrag mit Begründung.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Ausnahmen (Teil des Selektors → Grund)
AUSNAHMEN = {
    '.fw-avatar.fw-avatar-klein': 'Initialen in einem 20-px-Kreis',
    '.fw-schiene-zahl': 'Zahl in einer 16-px-Pille an einem Symbol',
    '.fw-kurve-y': 'Achsenbeschriftung eines Diagramms',
    '.fw-kurve-x': 'Achsenbeschriftung eines Diagramms',
    '.fw-fs-mikro': 'ausdrücklich winzige Schrift (Schriftgrössen-Test)',
    '.fw-donut .fw-c .fw-s': 'Beschriftung im Loch eines Ringdiagramms',
}


class SchriftMindestgroesseTests(SimpleTestCase):

    def test_keine_regel_unter_12_px_ausser_den_ausnahmen(self):
        text = (WURZEL / 'core/templates/fw/_schicht.html').read_text(encoding='utf-8')
        zu_klein = []
        for m in re.finditer(r'([^{}]*)\{[^{}]*?font-size:\s*([0-9.]+)px[^{}]*\}', text):
            if float(m.group(2)) >= 12:
                continue
            selektor = m.group(1).strip().split('\n')[-1].strip()
            if not any(a in selektor for a in AUSNAHMEN):
                zu_klein.append(f'{selektor[:70]} → {m.group(2)}px')
        self.assertEqual(zu_klein, [], 'Schrift unter 12 px (Ausnahme mit Begründung in AUSNAHMEN eintragen)')

    def test_gegenprobe_ausnahmen_gibt_es_noch(self):
        """Eine Ausnahme, die nirgends mehr vorkommt, wird gestrichen (sonst wächst die Liste unbemerkt)."""
        text = (WURZEL / 'core/templates/fw/_schicht.html').read_text(encoding='utf-8')
        for a in AUSNAHMEN:
            self.assertIn(a, text, f'Ausnahme {a} steht nicht mehr in der Stilschicht: streichen')
