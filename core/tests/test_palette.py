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

# Seit E2.10 stehen Tokens und Bausteine in `fw/_schicht.html`; `base.html`
# bindet sie ein. Dieser Waechter liest die Schicht, weil dort die Farbwerte
# liegen — seine Blindheitspruefung («kaum Hexwerte gefunden») hat den Umzug
# sofort gemeldet, statt still gruen zu bleiben.
BASE = pathlib.Path('core/templates/fw/_schicht.html')
#: Die Huelle selbst — sie traegt weiterhin das Dunkelmodus-Overlay fuer
#: Tailwind-Utilities und wird von `EinFarbtonTests` mitgelesen.
HUELLE = pathlib.Path('core/templates/fw/base.html')

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


class KonzeptTests(TestCase):
    """Das Konzept ist die Quelle — also muss es auch gelesen werden.

    WARUM

    `KONZEPT` oben ist abgeschrieben aus `mockups/konzept-v3.html`, und der
    Docstring dieser Datei sagt, wer die Werte aendert, muesse
    `docs/KONZEPT-UI.md` mitziehen. Bis zum 20.08.2026 fuehrte das Dokument
    aber ueberhaupt keine Palette: Der Test verwies auf eine Quelle, die
    nichts sagte, und niemand haette es gemerkt.

    Seit Abschnitt 16.1 steht die Tabelle dort. Dieser Test liest sie und
    vergleicht sie mit `base.html` — damit die Zusage «wer die Palette
    aendert, aendert das Konzept» geprueft ist statt nur behauptet.
    """

    DOKUMENT = pathlib.Path('docs/KONZEPT-UI.md')
    ZEILE = re.compile(r'\| `(--ds-[a-z0-9-]+)` \| `(#[0-9a-f]{6})` \| `(#[0-9a-f]{6})` \|')

    def _tabelle(self):
        return self.ZEILE.findall(self.DOKUMENT.read_text(encoding='utf-8'))

    def test_das_konzept_fuehrt_ueberhaupt_eine_palette(self):
        """Ohne diese Pruefung bestuende der Test unten auf einer leeren Liste."""
        self.assertGreaterEqual(
            len(self._tabelle()), 5,
            'In KONZEPT-UI.md wurde keine Palettentabelle gefunden — Abschnitt '
            '16.1 umbenannt oder das Format geaendert?')

    def test_konzept_und_base_html_stimmen_ueberein(self):
        hell, dunkel = _block('hell'), _block('dunkel')
        for token, soll_hell, soll_dunkel in self._tabelle():
            with self.subTest(token=token, modus='hell'):
                self.assertEqual(hell.get(token, '').strip().lower(), soll_hell)
            with self.subTest(token=token, modus='dunkel'):
                self.assertEqual(dunkel.get(token, '').strip().lower(), soll_dunkel)

    def test_die_dokumentierte_abweichung_steht_auch_im_konzept(self):
        """Die eine Stelle, an der bewusst vom Prototyp abgewichen wird."""
        text = self.DOKUMENT.read_text(encoding='utf-8')
        self.assertIn('#7f959c', text,
                      'Der Prototypwert fehlt — dann ist nicht nachvollziehbar, '
                      'wovon abgewichen wurde.')
        self.assertIn('3.14', text,
                      'Der gemessene Kontrast des Prototypwerts fehlt.')


def ohne_kommentare(quelle):
    """Erklaerungen sind keine Farbwerte.

    Zweimal ist an dieser Stelle schon ein Waechter auf den eigenen Kommentar
    hereingefallen und hat die Beschreibung eines Alt-Wertes fuer den Wert
    selbst gehalten. Deshalb fliegen Django- und CSS-Kommentare vorher raus.
    """
    quelle = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', ' ',
                    quelle, flags=re.S)
    return re.sub(r'/\*.*?\*/', ' ', quelle, flags=re.S)


def farbton(hexwert):
    """Farbton in Grad (0-360). Grau (Saettigung ~0) hat keinen — dann None."""
    r, g, b = [int(hexwert.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    hoch, tief = max(r, g, b), min(r, g, b)
    if hoch - tief < 0.04:
        return None
    if hoch == r:
        ton = (g - b) / (hoch - tief) % 6
    elif hoch == g:
        ton = (b - r) / (hoch - tief) + 2
    else:
        ton = (r - g) / (hoch - tief) + 4
    return ton * 60


class EinFarbtonTests(TestCase):
    """Die ganze Datei traegt Petrol — nicht nur der :root-Block.

    WARUM DIESER TEST NOETIG WURDE

    Etappe 4b.6 hiess «die Anwendung ist einfarbig» und stellte die
    Tailwind-Konfiguration auf die Petrol-Rampe um. Die Pruefungen darueber
    lasen den `:root`-Block und die Rampen — und waren gruen. Zwei grosse
    Flaechen sahen sie nie an:

        Die Seitenleiste   stand als `from-[#15182e] to-[#0d0f1e]` in der
                           Tailwind-Notation fuer beliebige Werte, kam also an
                           der Rampe vorbei. Sie ist auf JEDER Seite sichtbar.
        Der Dunkelmodus    ueberschreibt weiter unten mit `!important` und
                           festen Hexwerten. Er war vollstaendig das alte
                           Indigo-Produkt, obwohl die Tokens darueber Petrol
                           fuehrten — zwei Farbwelten, je nach Systemeinstellung.

    Ein Test, der nur dort hinsieht, wo aufgeraeumt wurde, bestaetigt das
    Aufraeumen und nicht das Ergebnis. Dieser hier misst jeden Farbwert der
    Datei.
    """

    #: Indigo und Violett liegen zwischen 215 und 300 Grad, Petrol bei ~180-200.
    #: Der Abstand ist gross genug, dass kein Grenzfall entscheidet.
    VERBOTEN = (215, 300)
    #: Unterhalb davon ist es Grau und der Farbton bedeutungslos.
    MERKLICH = 0.12

    def _hexwerte(self):
        quelle = ohne_kommentare(BASE.read_text(encoding='utf-8')
                                 + HUELLE.read_text(encoding='utf-8'))
        return sorted(set(m.group(0).lower()
                          for m in re.finditer(r'#[0-9a-fA-F]{6}\b', quelle)))

    @staticmethod
    def _saettigung(hexwert):
        r, g, b = [int(hexwert.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        hoch, tief = max(r, g, b), min(r, g, b)
        if hoch == tief:
            return 0.0
        helligkeit = (hoch + tief) / 2
        return ((hoch - tief) / (hoch + tief) if helligkeit < 0.5
                else (hoch - tief) / (2 - hoch - tief))

    def test_es_gibt_ueberhaupt_farbwerte_zu_pruefen(self):
        """Sonst pruefte der Test unten eine leere Liste."""
        self.assertGreater(
            len(self._hexwerte()), 50,
            'In base.html wurden kaum Hexwerte gefunden — Format geaendert?')

    def test_kein_indigo_und_kein_violett_mehr_in_base_html(self):
        for wert in self._hexwerte():
            ton = farbton(wert)
            if ton is None or self._saettigung(wert) < self.MERKLICH:
                continue
            with self.subTest(farbe=wert):
                self.assertFalse(
                    self.VERBOTEN[0] <= ton <= self.VERBOTEN[1],
                    f'{wert} liegt bei {ton:.0f}° und damit im Indigo-/Violett-'
                    f'Bereich. Die Anwendung fuehrt Petrol (~180-200°).')

    def test_die_messung_erkennt_indigo_auch(self):
        """Gegenprobe. Ein Farbtonrechner, der immer None liefert, besteht alles."""
        self.assertAlmostEqual(farbton('#4f46e5'), 244, delta=2)   # Alt-Marke
        self.assertAlmostEqual(farbton('#15182e'), 232, delta=2)   # Alt-Seitenleiste
        self.assertAlmostEqual(farbton('#0f6f6a'), 177, delta=2)   # Petrol
        self.assertIsNone(farbton('#808080'))

    def test_der_kommentarfilter_wirkt(self):
        """Gegenprobe. Ohne ihn liest der Test seine eigene Erklaerung als Farbe."""
        self.assertNotIn('#15182e', ohne_kommentare(
            '{% comment %} frueher #15182e {% endcomment %}'))
        self.assertNotIn('#15182e', ohne_kommentare('/* frueher #15182e */'))
        self.assertIn('#15182e', ohne_kommentare('a{color:#15182e}'))

    def test_die_seitenleiste_traegt_den_prototyp_verlauf(self):
        """Der Verlauf steht in Tailwinds Notation fuer beliebige Werte und
        kommt damit an der Farbrampe vorbei — er braucht eine eigene Pruefung.
        Werte aus `mockups/konzept-v2.html`, Token `--nav`."""
        # Der Verlauf steht im MARKUP der Huelle, nicht in der Schicht.
        quelle = ohne_kommentare(HUELLE.read_text(encoding='utf-8'))
        self.assertIn('from-[#122b31] to-[#0a1c20]', quelle,
                      'Die Seitenleiste fuehrt nicht mehr den Petrol-Verlauf '
                      'des Prototyps.')
