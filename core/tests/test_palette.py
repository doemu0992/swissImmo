"""Die Palette muss dem Konzept entsprechen — und lesbar bleiben.

WARUM

Am 19.08.2026 wurde behauptet, `fw/base.html` trage bereits die Konzeptpalette.
Das stimmte nicht: Dort stand weiterhin Indigo `#4f46e5` auf Slate. Der
Unterschied fiel erst auf, als jemand den Server neben den Prototyp hielt.

Zugleich verfehlt der Prototyp selbst an einer Stelle die Barrierefreiheit:
Sein `--ds-faint` (#7f959c) erreicht auf Weiss nur 3.14:1. Die Prototypen
entstanden ohne Kontrastprüfung.

Dieser Test hält beides fest: die Markenfarben so, wie das Konzept sie
vorgibt — und für jede Textfarbe die Rechnung, dass sie auf ihrer Fläche
lesbar ist.
"""
import pathlib
import re

from django.test import TestCase

BASE = pathlib.Path('core/templates/fw/base.html')

#: Werte aus mockups/konzept-v3.html. Wer sie ändert, ändert das Konzept —
#: und muss `docs/KONZEPT-UI.md` mitziehen.
KONZEPT = {
    '--ds-brand': '#0f6f6a',
    '--ds-brand-600': '#0b5450',
    '--ds-brand-soft': '#d9efed',
    '--ds-ink': '#0e2227',
    '--ds-muted': '#4c6169',
    '--ds-surface-2': '#f4f7f7',
    '--ds-line': '#dde6e8',
    '--ds-radius': '10px',
    '--ds-radius-sm': '7px',
}

#: Bewusste Abweichung: Der Prototypwert verfehlt WCAG AA.
ABWEICHUNG = {'--ds-faint': ('#5c757c', '#7f959c', 'Prototyp nur 3.14:1 auf Weiss')}

MINDESTKONTRAST = 4.5


def _block(name):
    quelle = BASE.read_text(encoding='utf-8')
    if name == 'hell':
        m = re.search(r':root\{(.*?)\}', quelle, re.S)
    else:
        m = re.search(r':root\[data-theme="dark"\]\{(.*?)\}', quelle, re.S)
    return dict(re.findall(r'(--ds-[a-z0-9-]+)\s*:\s*([^;]+);', m.group(1)))


def leuchtdichte(hex_):
    hex_ = hex_.strip().lstrip('#')
    if len(hex_) == 3:
        hex_ = ''.join(c * 2 for c in hex_)
    teile = [int(hex_[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    teile = [t / 12.92 if t <= 0.03928 else ((t + 0.055) / 1.055) ** 2.4
             for t in teile]
    return 0.2126 * teile[0] + 0.7152 * teile[1] + 0.0722 * teile[2]


def kontrast(vorne, hinten):
    a, b = leuchtdichte(vorne), leuchtdichte(hinten)
    hoch, tief = max(a, b), min(a, b)
    return (hoch + 0.05) / (tief + 0.05)


class PaletteTests(TestCase):
    def test_hellmodus_entspricht_dem_konzept(self):
        hell = _block('hell')
        for token, erwartet in KONZEPT.items():
            with self.subTest(token=token):
                self.assertEqual(
                    hell.get(token, '').strip().lower(), erwartet,
                    f'{token} weicht vom Konzept ab. Wenn das Absicht ist, '
                    f'gehoert die Aenderung auch in mockups/ und docs/KONZEPT-UI.md.')

    def test_die_eine_abweichung_ist_dokumentiert(self):
        hell = _block('hell')
        for token, (gesetzt, prototyp, grund) in ABWEICHUNG.items():
            with self.subTest(token=token):
                self.assertEqual(hell.get(token, '').strip().lower(), gesetzt)
                self.assertLess(
                    kontrast(prototyp, '#ffffff'), MINDESTKONTRAST,
                    f'Der Prototypwert {prototyp} ist inzwischen ausreichend — '
                    f'dann kann die Abweichung weg. Grund war: {grund}')
                self.assertGreaterEqual(kontrast(gesetzt, '#ffffff'), MINDESTKONTRAST)

    def test_kein_indigo_mehr(self):
        """Der Bestandswert, an dem der Unterschied zum Konzept hing."""
        quelle = BASE.read_text(encoding='utf-8').lower()
        hell = _block('hell')
        self.assertNotIn('#4f46e5', hell.get('--ds-brand', ''))
        self.assertNotIn(
            '--ds-brand:#4f46e5', quelle.replace(' ', ''),
            'Die Markenfarbe steht wieder auf Indigo.')

    def test_textfarben_erfuellen_wcag_aa(self):
        for modus, flaeche in (('hell', '--ds-surface'), ('dunkel', '--ds-surface')):
            werte = _block(modus)
            hintergrund = werte[flaeche].strip()
            if hintergrund == '#fff':
                hintergrund = '#ffffff'
            for token in ('--ds-ink', '--ds-muted', '--ds-faint', '--ds-brand',
                          '--ds-good', '--ds-warn', '--ds-crit', '--ds-info'):
                with self.subTest(modus=modus, token=token):
                    r = kontrast(werte[token].strip(), hintergrund)
                    self.assertGreaterEqual(
                        r, MINDESTKONTRAST,
                        f'{token} erreicht im {modus}modus nur {r:.2f}:1 auf '
                        f'{hintergrund} — WCAG AA verlangt {MINDESTKONTRAST}:1.')

    def test_zustandsfarben_auf_ihrer_weichen_flaeche(self):
        """Ein Chip traegt seine Farbe auf der zugehoerigen Flaeche, nicht auf Weiss."""
        for modus in ('hell', 'dunkel'):
            werte = _block(modus)
            for name in ('good', 'warn', 'crit', 'info', 'brand'):
                vorne = werte[f'--ds-{name}'].strip()
                hinten = werte[f'--ds-{name}-soft'].strip()
                with self.subTest(modus=modus, farbe=name):
                    r = kontrast(vorne, hinten)
                    self.assertGreaterEqual(
                        r, MINDESTKONTRAST,
                        f'--ds-{name} auf --ds-{name}-soft nur {r:.2f}:1 ({modus}).')

    def test_der_kontrastrechner_stimmt(self):
        """Gegenprobe. Ein Rechner, der immer hohe Werte liefert, besteht alles."""
        self.assertAlmostEqual(kontrast('#000000', '#ffffff'), 21, places=1)
        self.assertAlmostEqual(kontrast('#ffffff', '#ffffff'), 1, places=1)
        self.assertLess(kontrast('#7f959c', '#ffffff'), MINDESTKONTRAST)
