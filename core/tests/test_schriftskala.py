"""Schriftskala (UI-Zielbild, Phase 3): sieben Stufen statt achtundzwanzig.

12, 13, 14, 15, 18, 22 und 28 px. Jede frühere Grösse wurde auf die nächste Stufe gerundet. Wie bei Farben und Rundungen
hält ein Wächter die Skala fest: Eine neue Pixelgrösse in der Stilschicht lässt den Test scheitern.

Ausnahmen, mit Begründung:
* unter 12 px: nur die Selektoren aus `test_schrift_mindestgroesse` (Zahlen in kleinen Kreisen, Achsen);
* 34, 36, 40, 52 px und `clamp(…)`: Anzeigezahlen und Seitentitel (36 px am PC), bewusst grösser als jede Textstufe;
* `1rem`, `inherit`: übernehmen die Grösse des Umfelds.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)
SKALA = {12, 13, 14, 15, 18, 22, 28}
ANZEIGE = {34, 36, 40, 52}


class SchriftskalaTests(SimpleTestCase):
    def test_nur_stufen_der_skala(self):
        text = (WURZEL / 'core/templates/fw/_schicht.html').read_text(encoding='utf-8')
        fremd = sorted({m.group(1) for m in re.finditer(r'font-size:\s*([0-9.]+)px', text)
                        if float(m.group(1)) >= 12 and float(m.group(1)) not in SKALA | ANZEIGE})
        self.assertEqual(fremd, [], 'Schriftgrösse ausserhalb der Skala 12/13/14/15/18/22/28 px')

    def test_skala_wird_benutzt(self):
        """Gegenprobe: Jede Stufe kommt vor, sonst ist die Skala nur Behauptung."""
        text = (WURZEL / 'core/templates/fw/_schicht.html').read_text(encoding='utf-8')
        benutzt = {float(m.group(1)) for m in re.finditer(r'font-size:\s*([0-9.]+)px', text)}
        for stufe in SKALA:
            self.assertIn(float(stufe), benutzt, f'{stufe} px kommt nicht mehr vor')
