"""Jede `fw-`-Klasse in einer Vorlage muss von einer Regel getroffen werden.

WARUM ES DIESEN WÄCHTER GIBT

E2.1 bis E2.3 haben Tailwind-Farbklassen durch die Komponentenschicht ersetzt —
`bg-slate-50` wurde `fw-flaeche2`, `hover:bg-slate-50` wurde
`hover:fw-flaeche2`. Der erste Ersatz ist richtig. Der zweite ist tot.

Der Unterschied: `hover:bg-slate-50` funktioniert, weil **Tailwind die Regel
erzeugt**. `fw-flaeche2` steht dagegen von Hand im `<style>`-Block von
`fw/base.html`; Tailwind kennt sie nicht und baut für sie auch keine
Varianten. Der Browser sieht dann eine Klasse namens `hover:fw-flaeche2`, auf
die keine einzige Regel passt — und tut nichts.

Dasselbe gilt für den Opazitäts-Zusatz: `fw-markenflaeche/60` ist ebenfalls
reine Tailwind-Syntax. Im Browser gemessen (Chromium, echte Seite, echte
Stylesheets) ergab `fw-markenflaeche/60` die Hintergrundfarbe
`rgba(0, 0, 0, 0)` — vollständig durchsichtig —, während `fw-markenflaeche`
korrekt `rgb(217, 239, 237)` lieferte. Unter 292 geladenen Regeln passte
**keine** auf `hover:fw-*`, `focus:fw-*`, `file:fw-*` oder `group-hover:fw-*`.

Gefunden waren so 127 tote Vorkommen in 17 Vorlagen. Kein Test schlug an, kein
Fehler erschien im Protokoll: Ein Element ohne Hintergrund sieht aus wie ein
Element, das keinen haben soll.

WAS DIESER TEST PRÜFT

Er liest die Klassenattribute aller Vorlagen unter `core/templates/fw/` und
prüft für jedes Wort, das `fw-` enthält, ob der `<style>`-Block von
`fw/base.html` eine Regel dafür führt — die Grundklasse ebenso wie die
maskierte Varianten-Form (`.hover\\:fw-marke:hover`).

WAS ER NICHT PRÜFT

Ob die Regel das Richtige tut. `hover:fw-btn` war eine Regel wert und trotzdem
falsch: Es entstand, weil `bg-indigo-600 hover:bg-indigo-700` durch
`fw-balken-voll hover:fw-btn fw-primary` ersetzt wurde — das `hover:` blieb am
ersten von **zwei** Ersatzwörtern hängen. Eine Regel dafür hätte Polsterung und
Radius nur beim Überfahren gesetzt, also einen Sprung im Layout erzeugt. Die
vier Stellen sind entfernt; `fw-primary` bringt den Hover-Zustand schon mit.

Der Wächter hätte das nicht gefunden. Er findet die tote Klasse, nicht die
falsche — dafür braucht es weiterhin den Blick in den Browser.

Ebenso wenig prüft er, ob eine Klasse ALLEIN wirkt. `fw-gefahr` (E2.5) ist nur
als `.fw-btn.fw-gefahr` definiert; ohne `fw-btn` daneben bleibt der Knopf
durchsichtig — im Browser nachgemessen: `rgba(0, 0, 0, 0)`. Für den Wächter
ist die Klasse trotzdem «getroffen», weil ihr Name in einem Selektor steht.
Das ist kein Versehen, sondern eine bewusste Grenze: **33** der `fw-`-Klassen
sind reine Zusätze, die nur im Verbund gelten (`fw-primary`, `fw-mitte`,
`fw-on`, `fw-zeit` …). Eine Regel «muss zusammen mit X stehen» bräuchte für
jede von ihnen die Angabe, mit welchem X — und wäre damit eine zweite Liste,
die altert. Wer eine neue Verbund-Klasse einführt, prüft sie im Browser.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)
VORLAGEN = WURZEL / 'core' / 'templates' / 'fw'
BASIS = VORLAGEN / 'base.html'

#: Klassen, die nur als Aufhänger für JavaScript dienen und bewusst kein
#: eigenes Aussehen haben. Wer hier etwas einträgt, muss sagen, warum die
#: Klasse ohne Regel richtig ist.
OHNE_REGEL_RICHTIG = {
    # `fw/base.html` erzeugt die Einträge der Befehlspalette im Skript und
    # sucht sie später mit `querySelector('.fw-pal-item')` wieder. Die
    # Gestaltung liegt in den daneben stehenden Tailwind-Klassen.
    'fw-pal-item',
}


def _regeln():
    """Alle Selektoren aus dem <style>-Block von fw/base.html."""
    text = BASIS.read_text(encoding='utf-8')
    # Die Maskierung `\:` und `\/` gehört zum Selektor, nicht zum Klassennamen.
    return set(re.findall(r'\.((?:[\w-]|\\.)+)', text))


#: Platzhalter für eine Stelle, an der die Vorlage rechnet statt zu schreiben.
#: Muss ein Zeichen sein, das in keinem Klassennamen vorkommt.
_EINGESETZT = '\x00'


def _klassen_der_vorlagen():
    """Jedes Wort mit `fw-` aus einem class-Attribut, mit Fundstelle.

    Wörter, in denen die Vorlage einen Wert einsetzt (`fw-{{ chip.0 }}`),
    fallen weg — statisch ist nicht zu sehen, was herauskommt. Sie sind
    deshalb nicht ungeprüft: `test_die_toene_aus_den_views_sind_definiert`
    nimmt sich die Werte vor, die dort eingesetzt werden.
    """
    for pfad in sorted(VORLAGEN.rglob('*.html')):
        text = pfad.read_text(encoding='utf-8')
        for treffer in re.finditer(r'class\s*=\s*"([^"]*)"', text):
            # Django-Tags zuerst entfernen — sonst klebt `{% if x %}` am
            # Klassennamen und erzeugt einen Fund, den es nicht gibt.
            roh = re.sub(r'\{%.*?%\}', ' ', treffer.group(1), flags=re.S)
            roh = re.sub(r'\{\{.*?\}\}', _EINGESETZT, roh, flags=re.S)
            for wort in roh.split():
                if 'fw-' in wort and _EINGESETZT not in wort:
                    zeile = text.count('\n', 0, treffer.start()) + 1
                    yield wort, f'{pfad.name}:{zeile}'


class FwKlassenWirkenTest(SimpleTestCase):

    def test_jede_fw_klasse_wird_von_einer_regel_getroffen(self):
        regeln = _regeln()
        tot = []
        for wort, ort in _klassen_der_vorlagen():
            kern = wort.split(':')[-1]
            if kern in OHNE_REGEL_RICHTIG:
                continue
            # Als Grundklasse ohne Variante: genügt die schlichte Regel.
            if wort == kern and kern in regeln:
                continue
            # Mit Variante oder Zusatz: die maskierte Form muss stehen.
            if wort.replace(':', r'\:').replace('/', r'\/') in regeln:
                continue
            tot.append(f'{ort}: {wort}')

        self.assertEqual(
            tot, [],
            'Diese Klassen trifft keine Regel — die Elemente bleiben ohne '
            'Hintergrund, ohne Farbe oder ohne Zustand:\n  '
            + '\n  '.join(tot)
            + '\n\nTailwind erzeugt Varianten (`hover:`, `focus:`, `file:`) '
              'und Opazitäts-Zusätze (`/40`) nur für seine EIGENEN Utilities. '
              'Für eine handgeschriebene `fw-`-Klasse muss die Regel im '
              '<style>-Block von fw/base.html stehen — oder der Zusatz '
              'gehört weg.')

    def test_die_toene_aus_den_views_sind_definiert(self):
        """Die Lücke, die der Test darüber offen lässt.

        `<span class="fw-chip fw-{{ chip.0 }}">` setzt den Ton erst beim
        Rendern ein — 57 solcher Stellen gibt es. Statisch ist dort nichts zu
        prüfen. Die Werte selbst stehen aber im Python-Code: `{'ton':
        'fw-warn'}`. Ein Tippfehler dort erzeugt genau denselben stillen
        Ausfall wie eine fehlende Varianten-Regel — ein Chip ohne Farbe.
        """
        regeln = _regeln()
        toene = set()
        for pfad in sorted((WURZEL / 'core' / 'views').rglob('*.py')):
            for treffer in re.finditer(
                    r'''['"]ton['"]\s*:\s*['"](fw-[a-z0-9-]+)['"]''',
                    pfad.read_text(encoding='utf-8')):
                toene.add(treffer.group(1))

        self.assertGreater(
            len(toene), 3,
            'Keine Ton-Werte in core/views gefunden — entweder heisst der '
            'Schlüssel nicht mehr «ton», oder die Suche greift daneben. So '
            'oder so prüft dieser Test dann nichts.')

        unbekannt = sorted(t for t in toene if t not in regeln)
        self.assertEqual(
            unbekannt, [],
            'Diese Töne setzen die Views ein, aber fw/base.html kennt sie '
            f'nicht: {unbekannt}. Der Chip erscheint dann farblos.')

    def test_der_waechter_findet_die_vorlagen_ueberhaupt(self):
        """Ohne diese Zeile wäre der Test oben auch bei leerem Suchpfad grün.

        Ein Wächter, der nichts liest, meldet nie etwas. Das ist der stillste
        Ausfall überhaupt — deshalb hier die Untergrenze.
        """
        gefunden = list(_klassen_der_vorlagen())
        self.assertGreater(
            len(gefunden), 2000,
            f'Nur {len(gefunden)} fw-Klassen in {VORLAGEN} gefunden. Entweder '
            'stimmt der Pfad nicht mehr, oder das Ablesen der '
            'class-Attribute ist kaputt.')
        self.assertGreater(
            len(_regeln()), 100,
            'Im <style>-Block von fw/base.html stehen kaum Regeln — der '
            'Vergleich oben liefe dann gegen eine fast leere Menge.')
