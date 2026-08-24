"""Jedes benutzte `var(--ds-…)` muss auch definiert sein.

WARUM ES DIESEN TEST GIBT

Am 19.08.2026 wurde eine Übergangsschicht vorgeschlagen, die neun Tokens
benutzte, die es nie gab: `--ds-brand-50` bis `-900`, `--ds-line-stark` und
`--ds-nav`. Die Git-Historie zeigt kein einziges Vorkommen.

Der Fehler ist heimtückisch, weil CSS ihn nicht meldet. Eine Deklaration mit
undefinierter Variable wird ungültig und fällt weg — mit `!important` schlägt
sie die darunterliegende Regel trotzdem. Gemessen wurde `bg-indigo-100`
durchsichtig und `border-slate-300` in Textfarbe. Vierzehn Tests waren dabei
grün; sie prüften Zeichenketten und Reihenfolge, nie ob ein Token existiert.

Dieser Test liest die Definitionen aus `:root` und vergleicht sie mit jeder
Verwendung — in `base.html` und in allen anderen Templates.
"""
import pathlib
import re

from django.test import TestCase

WURZEL = pathlib.Path('core/templates')

# Seit E2.10 stehen Tokens und `fw-*`-Regeln in `fw/_schicht.html`, damit auch
# die Aussenseiten sie sehen (Mieterportal, Bewerbungsformular). `base.html`
# bindet die Datei ein und traegt weiterhin das Markup und das
# Dunkelmodus-Overlay fuer Tailwind-Utilities.
#
# Dieser Waechter liest die SCHICHT — dort liegen die Werte, die er prueft.
# Nach dem Umzug meldete er sie als fehlend; still gruen blieb er nicht.
BASE = WURZEL / 'fw' / '_schicht.html'

DEFINITION = re.compile(r'(--ds-[a-z0-9-]+)\s*:')
VERWENDUNG = re.compile(r'var\(\s*(--ds-[a-z0-9-]+)')


def definierte():
    quelle = BASE.read_text(encoding='utf-8')
    return {m.group(1) for m in DEFINITION.finditer(quelle)}


def verwendungen():
    """Token → Menge der Dateien, die es benutzen."""
    treffer = {}
    for p in WURZEL.rglob('*.html'):
        for m in VERWENDUNG.finditer(p.read_text(errors='ignore')):
            treffer.setdefault(m.group(1), set()).add(
                str(p).replace('core/templates/', ''))
    return treffer


class TokenTests(TestCase):
    def test_es_gibt_ueberhaupt_definitionen(self):
        """Ohne diese Prüfung hinge der Test unten in der Luft.

        Fände die Abfrage nichts, wäre die Menge der definierten Tokens leer —
        und dann wäre jede Verwendung «unbekannt», oder je nach Richtung des
        Vergleichs bestünde alles.
        """
        self.assertGreater(
            len(definierte()), 10,
            'In base.html wurden fast keine --ds-Tokens gefunden — stimmt der '
            'Aufbau von :root noch?')

    def test_jedes_verwendete_token_ist_definiert(self):
        """Der eigentliche Test.

        Ein undefiniertes Token macht die ganze Deklaration ungültig, ohne dass
        irgendwo eine Meldung erscheint.
        """
        bekannt = definierte()
        unbekannt = {t: sorted(d) for t, d in verwendungen().items()
                     if t not in bekannt}
        meldung = '\n'.join(
            f'  {t} — benutzt in {", ".join(dateien[:3])}'
            + (f' und {len(dateien) - 3} weiteren' if len(dateien) > 3 else '')
            for t, dateien in sorted(unbekannt.items()))
        self.assertEqual(
            unbekannt, {},
            'Diese Tokens werden benutzt, sind aber nirgends definiert. CSS '
            'meldet das nicht — die Regel faellt still weg:\n' + meldung)

    def test_definierte_tokens_werden_auch_benutzt(self):
        """Ein totes Token ist harmlos, aber es täuscht ein Angebot vor.

        Wer eine Komponente baut, greift danach — und merkt erst im Browser,
        dass es zwar existiert, aber nirgends gepflegt wird.
        """
        benutzt = set(verwendungen())
        # Zwei Tokens sind definiert, aber (Stand 19.08.2026) nirgends per
        # var() gelesen. Sie stehen hier namentlich, damit die Liste nicht
        # unbemerkt waechst: Wer ein drittes ergaenzt, muss es begruenden.
        erlaubt_ungenutzt = {
            '--ds-bg',         # Seitenhintergrund kommt aus einer Tailwind-Klasse
            '--ds-shadow-sm',  # Reserve fuer flachere Karten, noch nicht gebraucht
        }
        tot = definierte() - benutzt - erlaubt_ungenutzt
        self.assertEqual(
            sorted(tot), [],
            'Definiert, aber nirgends benutzt — entweder einbauen oder streichen.')

    #: Nur Farben. Radien und Rundungen sind Geometrie und im Dunkeln
    #: dieselben — sie dort noch einmal zu setzen waere Rauschen. Eine
    #: erste Fassung dieses Tests verlangte es und wurde deshalb rot.
    GEOMETRIE = {'--ds-radius', '--ds-radius-sm', '--ds-pill'}

    #: **Beide** Dunkelblöcke, nicht nur einer.
    #:
    #: Die erste Fassung suchte mit `\[data-theme="dark"\]` und traf damit nur
    #: den Umschalter-Block. Eine Gegenprobe am 19.08.2026 entfernte `--ds-good`
    #: aus dem `@media`-Block — der Test blieb gruen. Das ist der folgenreichere
    #: der beiden: Er bedient jeden, der nie einen Umschalter angeruehrt hat,
    #: also den Normalfall. Die Farbe waere dort auf den Hellwert
    #: zurueckgefallen, sichtbar nur auf einem dunkel gestellten Geraet.
    DUNKELBLOECKE = (
        (r'@media\s*\(prefers-color-scheme:\s*dark\)\s*\{'
         r':root:not\(\[data-theme="light"\]\)\s*\{(.*?)\}\s*\}',
         'Systemeinstellung dunkel (@media)'),
        (r':root\[data-theme="dark"\]\s*\{(.*?)\}',
         'Umschalter auf dunkel ([data-theme])'),
    )

    def test_der_dunkelmodus_definiert_dieselben_tokens(self):
        """Sonst fällt eine Farbe im Dunkeln auf den Hellwert zurück.

        Das ist der unauffälligste aller Fehler: Die Seite funktioniert, sieht
        aber an einer Stelle falsch aus, und nur bei umgeschaltetem Modus.
        """
        quelle = BASE.read_text(encoding='utf-8')
        hell = re.search(r':root\s*\{(.*?)\}', quelle, re.S)
        in_hell = {m.group(1)
                   for m in DEFINITION.finditer(hell.group(1))} - self.GEOMETRIE

        for muster, name in self.DUNKELBLOECKE:
            block = re.search(muster, quelle, re.S)
            with self.subTest(block=name):
                self.assertIsNotNone(
                    block,
                    f'Der Dunkelblock «{name}» wurde nicht gefunden. Ohne ihn '
                    f'prueft dieser Test nichts — Aufbau von base.html geaendert?')
                in_dunkel = {m.group(1)
                             for m in DEFINITION.finditer(block.group(1))}
                fehlend = sorted(in_hell - in_dunkel)
                self.assertEqual(
                    fehlend, [],
                    f'In «{name}» nicht gesetzt — diese Farben behalten dort '
                    f'ihren Hellwert: {", ".join(fehlend)}')
