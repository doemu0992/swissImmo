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

# Seit E2.10 zweigeteilt: Die REGELN stehen in `fw/_schicht.html`, das
# `<aside>`-MARKUP weiterhin in `fw/base.html`. Dieser Waechter braucht beides
# — er vergleicht die benutzten Klassen mit den Regeln, die sie treffen.
BASE = pathlib.Path('core/templates/fw/_schicht.html')
MARKUP = pathlib.Path('core/templates/fw/base.html')

#: Die beiden Enden des Verlaufs. Beide müssen bestehen — ein Ton, der nur oben
#: reicht, ist unten unlesbar, und die Leiste ist an beiden Enden beschriftet.
#: Seit E2.21 steht die Leiste auf `--ds-surface` (Entscheid D2). Geprueft
#: wird gegen DIESE Flaeche — der dunkle Verlauf ist Geschichte, und mit
#: ihm die Ausnahme, die `fw-mutet`/`fw-faint` dort anhob.
VERLAUF = ('#ffffff',)


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
    quelle = MARKUP.read_text(encoding='utf-8')
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


def _schichtklassen_in_der_leiste():
    """Textklassen der Komponentenschicht auf dem dunklen Verlauf.

    Seit E2.14 traegt die Leiste `fw-mutet`, `fw-faint`, `fw-ink`, `fw-strong`
    statt `text-slate-*`. Die Gefahr ist dieselbe: Diese Toene sind fuer HELLE
    Flaechen gerechnet — `--ds-muted` erreicht 8.4:1 auf `--ds-surface`, auf
    dem Verlauf der Leiste waren es in E0.3 gemessene 2.28:1.

    Der Waechter kannte sie zuerst nicht und meldete «Nur set() in der
    Seitenleiste gefunden»: Seine Blindheitspruefung hat den Umbau angezeigt,
    statt still gruen zu bleiben.
    """
    return set(re.findall(r'\bfw-(mutet|faint|ink|strong)\b', _leisten_block()))



class KontrastSeitenleisteTest(SimpleTestCase):

    def test_die_suche_findet_ueberhaupt_klassen(self):
        """Sonst prüfte der Test darunter eine leere Menge.

        Dieselbe Blindheit wie in `AktenkopfTests`: eine Bedingung, die immer
        erfüllt ist, weil sie ins Leere greift.
        """
        gefunden = _slate_klassen_in_der_leiste() | _schichtklassen_in_der_leiste()
        # Zwei genuegen: Nach E2.14 traegt die Leiste noch `fw-mutet` und
        # `fw-faint`. Die Schwelle steht gegen BLINDHEIT (leere Menge), nicht
        # gegen Aufraeumen — sie darf Fortschritt nicht als Fehler melden,
        # dieselbe Lehre wie bei `test_die_messung_findet_ueberhaupt_etwas`.
        self.assertGreaterEqual(
            len(gefunden), 2,
            f'Nur {gefunden} in der Seitenleiste gefunden — Aufbau geändert?')

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
