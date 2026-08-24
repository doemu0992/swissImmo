"""Schutz der Farbschicht in `fw/base.html`.

`base.html` trägt zweierlei, das leicht zu übersehen ist und teuer kaputtgeht:

1. **Die Tokens** (`--ds-*`) und 53 handgeschriebene Regeln, die die fest
   verdrahteten Tailwind-Klassen im Dunkelmodus umbiegen. Das ist die
   Übergangsschicht dieses Projekts — sie steht nur nicht so da.
2. **Zwei Kontrastregeln**, die `.text-slate-400` und `.text-slate-300` auf
   `--ds-muted` zwingen, weil die Rohwerte WCAG AA verfehlen.

Beide Tests hier sind aus einem konkreten Beinahe-Unfall entstanden (19.08.2026):
Eine vorgeschlagene zweite Farbschicht hätte `.text-slate-400` später in der
Kaskade auf `--ds-faint` gesetzt — 4.34:1 statt 6.92:1, also unter AA — und
dabei auf neun Tokens verwiesen, die es gar nicht gibt. Ein `var()` auf eine
undefinierte Variable ohne Rückfallwert macht die Deklaration ungültig; mit
`!important` schlägt sie trotzdem Tailwind. Gemessen in Chromium wurde aus
`bg-indigo-100` durchsichtig und aus `border-slate-300` die Textfarbe.

Kein Test hätte das gemeldet. Diese beiden schon.
"""
import pathlib
import re

from django.test import TestCase


# Seit E2.10 stehen Tokens und `fw-*`-Regeln in `fw/_schicht.html`, damit auch
# die Aussenseiten sie sehen (Mieterportal, Bewerbungsformular). `base.html`
# bindet die Datei ein und traegt weiterhin das Markup und das
# Dunkelmodus-Overlay fuer Tailwind-Utilities.
#
# Dieser Waechter liest die SCHICHT — dort liegen die Werte, die er prueft.
# Nach dem Umzug meldete er sie als fehlend; still gruen blieb er nicht.
BASE = pathlib.Path('core/templates/fw/_schicht.html')


class TokensSindDefiniertTests(TestCase):
    """Jedes benutzte `--ds-*` muss es auch geben.

    Der allgemeine Fall des Fehlers oben: Wer eine Regel auf ein Token legt,
    das nicht existiert, bekommt keine Fehlermeldung — die Eigenschaft fällt
    still auf ihren Anfangswert zurück. Bei `background-color` heisst das
    durchsichtig, bei `border-color` die Textfarbe.
    """

    def test_kein_verweis_auf_ein_undefiniertes_token(self):
        """Gilt für ALLE Templates, nicht nur für `base.html`.

        Absichtlich weit gefasst: Der Fall, aus dem dieser Test entstand, war
        eine **neue** Datei, die auf Tokens von `base.html` zeigte. Ein Test,
        der nur `base.html` liest, hätte sie durchgewinkt.
        """
        definiert = set(re.findall(r'(--ds-[a-z0-9-]+)\s*:',
                                   BASE.read_text(encoding='utf-8')))
        fehlend = {}
        for pfad in sorted(pathlib.Path('core/templates').rglob('*.html')):
            # Nur Verweise OHNE Rückfallwert sind gefährlich: `var(--x, #fff)`
            # liefert auch ohne Definition ein Ergebnis.
            benutzt = set(re.findall(r'var\((--ds-[a-z0-9-]+)\s*\)',
                                     pfad.read_text(encoding='utf-8')))
            offen = benutzt - definiert
            if offen:
                fehlend[str(pfad)] = sorted(offen)
        self.assertEqual(
            fehlend, {},
            'Diese Tokens werden benutzt, aber in base.html nirgends definiert. '
            'Die betroffenen Regeln fallen still aus — bei background-color auf '
            'durchsichtig, bei border-color auf die Textfarbe:\n'
            + '\n'.join(f'  {p}: {", ".join(t)}' for p, t in fehlend.items()))

    def test_dunkelmodus_definiert_dieselben_tokens_wie_hell(self):
        """Ein Token, das nur hell existiert, behält im Dunkeln den hellen Wert."""
        quelle = BASE.read_text(encoding='utf-8')
        hell = _tokens_im_block(quelle, r':root\{')
        dunkel = _tokens_im_block(quelle, r':root\[data-theme="dark"\]\{')
        # Form- und Schattentokens sind bewusst nicht themenabhängig.
        egal = {t for t in hell if t.startswith(('--ds-radius', '--ds-pill'))}
        fehlend = sorted((hell - dunkel) - egal)
        self.assertEqual(
            fehlend, [],
            'Im Dunkelmodus nicht neu gesetzt: ' + ', '.join(fehlend))


class KontrastregelTests(TestCase):
    """Die Kontrastregeln müssen die letzte Aussage zu ihren Klassen bleiben."""

    def test_letzte_regel_fuer_text_slate_400_setzt_ds_muted(self):
        for klasse in ('text-slate-400', 'text-slate-300'):
            with self.subTest(klasse=klasse):
                treffer = re.findall(
                    r'\.' + klasse + r'\s*\{[^}]*?color\s*:\s*([^;!}]+)',
                    BASE.read_text(encoding='utf-8'))
                self.assertTrue(treffer, f'Keine Farbregel für .{klasse} gefunden.')
                self.assertIn(
                    'var(--ds-muted)', treffer[-1].strip(),
                    f'Die letzte Farbregel für .{klasse} ist nicht --ds-muted. '
                    f'Die Rohwerte verfehlen WCAG AA (2.34:1 bzw. 1.48:1); '
                    f'--ds-faint reicht mit 4.34:1 ebenfalls nicht.')

    def test_begruendung_steht_daneben(self):
        """Ohne die Begründung entfernt sie irgendwann jemand als Altlast."""
        quelle = BASE.read_text(encoding='utf-8')
        self.assertIn('WCAG AA', quelle)


def _tokens_im_block(quelle, muster):
    treffer = re.search(muster, quelle)
    if not treffer:
        return set()
    rest = quelle[treffer.end():]
    block = rest[:rest.index('}')]
    return set(re.findall(r'(--ds-[a-z0-9-]+)\s*:', block))
