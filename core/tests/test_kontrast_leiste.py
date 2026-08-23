"""Jede Textfarbe auf der dunklen Seitenleiste muss lesbar sein.

WARUM

Die globale Kontrastregel in `fw/base.html` hebt `.text-slate-400` und `-300`
auf `var(--ds-muted)` an. Für helle Flächen ist das richtig gerechnet: 8.4:1 auf
`--ds-surface`.

Die Seitenleiste ist aber dunkel (`#122b31` → `#0a1c20`) und benutzt genau diese
Klassen. Dort erreichte derselbe Wert **2.28:1** — die Einträge «Vermieten»,
«Geld» und «Übersichten» waren auf dem Bildschirm kaum zu lesen. Die Regel war
richtig gedacht und an einer Stelle falsch angewandt.

`text-slate-500` kam dazu (Gruppenknopf, Einstellungen): 3.03:1, von der Regel
oben gar nicht erfasst.

WAS DIESER TEST ANDERS MACHT ALS EINE LISTE

Er liest den `<aside>`-Block und findet die benutzten `text-slate-*`-Klassen
selbst. Eine feste Liste würde eine neu hinzugefügte Klasse nie bemerken —
genau so ist `text-slate-500` durchgerutscht. Wer morgen `text-slate-600` in die
Leiste schreibt, bekommt hier eine rote Meldung statt einer unlesbaren Zeile.

WAS ER NICHT PRÜFT

Ob der Browser die Regeln in dieser Reihenfolge anwendet. Der Test rechnet mit
den Werten, die im Stilblock stehen. Die tatsächliche Darstellung ist am
laufenden System nachgemessen worden (Playwright, beide Verlaufsenden).
"""
import pathlib
import re

from django.test import SimpleTestCase

from core.tests.test_palette import kontrast, MINDESTKONTRAST

BASE = pathlib.Path('core/templates/fw/base.html')

#: Die beiden Enden des Verlaufs. Beide müssen bestehen — ein Ton, der nur oben
#: reicht, ist unten unlesbar, und die Leiste ist an beiden Enden beschriftet.
VERLAUF = ('#122b31', '#0a1c20')


def _stilblock():
    return BASE.read_text(encoding='utf-8')


def _token(name):
    """Den Wert eines Tokens aus dem Hellsatz (`:root`) lesen."""
    quelle = _stilblock()
    anfang = quelle.index(':root{')
    block = quelle[anfang:quelle.index('}', anfang)]
    treffer = re.search(rf'{re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{3,6}})', block)
    assert treffer, f'{name} steht nicht in :root'
    return treffer.group(1)


def _leisten_block():
    quelle = _stilblock()
    anfang = quelle.index('<aside id="fwSidebar"')
    return quelle[anfang:quelle.index('</aside>', anfang)]


def _slate_klassen_in_der_leiste():
    """Alle `text-slate-N`, die im `<aside>` auf dem dunklen Grund landen.

    Ausgenommen ist `[&>option]:text-slate-900`: Die Einträge einer
    Auswahlliste zeichnet der Browser in seinem eigenen Fenster auf hellem
    Grund, nicht auf der Leiste. Die Klasse steht dort genau deshalb — sie
    hier mitzuzählen hiesse, sie auf einen Grund zu prüfen, auf dem sie nie
    erscheint, und würde den hellen Fall unlesbar machen.
    """
    block = _leisten_block()
    block = re.sub(r'\[&>option\]:text-slate-\d{3}', '', block)
    return {int(n) for n in re.findall(r'text-slate-(\d{3})', block)}


class KontrastSeitenleisteTest(SimpleTestCase):

    def test_die_suche_findet_ueberhaupt_klassen(self):
        """Sonst prüfte der Test darunter eine leere Menge.

        Dieselbe Blindheit wie in `AktenkopfTests`: eine Bedingung, die immer
        erfüllt ist, weil sie ins Leere greift.
        """
        gefunden = _slate_klassen_in_der_leiste()
        self.assertGreaterEqual(
            len(gefunden), 3,
            f'Nur {gefunden} in der Seitenleiste gefunden — Aufbau geändert?')

    def test_der_token_fuer_dunkle_flaechen_ist_lesbar(self):
        farbe = _token('--ds-auf-dunkel')
        for grund in VERLAUF:
            with self.subTest(grund=grund):
                r = kontrast(farbe, grund)
                self.assertGreaterEqual(
                    r, MINDESTKONTRAST,
                    f'--ds-auf-dunkel ({farbe}) erreicht auf {grund} nur '
                    f'{r:.2f}:1. Die Seitenleiste wäre dort nicht lesbar.')

    def test_jede_benutzte_klasse_wird_in_der_leiste_umgesetzt(self):
        """Die Regel muss ALLE Klassen abdecken, die die Leiste benutzt.

        `text-slate-500` fehlte in der ersten Fassung der Regel und erreichte
        3.03:1 — der Grund, warum dieser Test die Klassen sucht statt sie
        aufzuzählen.
        """
        quelle = _stilblock()
        regel = re.search(
            r'((?:#fwSidebar\s+\.text-slate-\d{3},?\s*)+)\{color:var\(--ds-auf-dunkel\)',
            quelle)
        self.assertIsNotNone(
            regel,
            'Die Regel `#fwSidebar .text-slate-… {color:var(--ds-auf-dunkel)}` '
            'fehlt. Ohne sie greift die globale Kontrastregel, die für helle '
            'Flächen gerechnet ist.')
        abgedeckt = {int(n) for n in re.findall(r'text-slate-(\d{3})', regel.group(1))}

        for stufe in sorted(_slate_klassen_in_der_leiste()):
            with self.subTest(klasse=f'text-slate-{stufe}'):
                self.assertIn(
                    stufe, abgedeckt,
                    f'Die Seitenleiste benutzt `text-slate-{stufe}`, die Regel '
                    f'deckt sie nicht ab. Auf dem dunklen Verlauf ist das '
                    f'unlesbar — Stufe in die Regel aufnehmen.')

    def test_der_aktive_eintrag_hebt_sich_weiterhin_ab(self):
        """Lesbarkeit allein genügt nicht — die Stufung muss sichtbar bleiben.

        Wäre der ruhende Eintrag so hell wie der aktive, wäre die Leiste zwar
        lesbar, aber man sähe nicht mehr, wo man ist.
        """
        ruhend = _token('--ds-auf-dunkel')
        for grund in VERLAUF:
            with self.subTest(grund=grund):
                self.assertGreater(
                    kontrast('#ffffff', grund) - kontrast(ruhend, grund), 3.0,
                    'Ruhender und aktiver Eintrag liegen zu nah beieinander.')

    def test_die_globale_regel_bleibt_fuer_helle_flaechen(self):
        """Gegenprobe: Die Ausnahme darf die Regel nicht ersetzen.

        Die globale Anhebung auf `--ds-muted` ist auf jeder hellen Fläche der
        Anwendung richtig und muss stehen bleiben — hier wird nur die eine
        dunkle Stelle ausgenommen.
        """
        quelle = _stilblock()
        self.assertIn('.text-slate-400{color:var(--ds-muted)!important}', quelle)
        self.assertIn('.text-slate-300{color:var(--ds-muted)!important}', quelle)
        r = kontrast(_token('--ds-muted'), _token('--ds-surface'))
        self.assertGreaterEqual(
            r, MINDESTKONTRAST,
            f'--ds-muted erreicht auf --ds-surface nur {r:.2f}:1.')
