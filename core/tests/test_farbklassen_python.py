"""Farbklassen leben nicht nur in Vorlagen — auch im Python-Code.

WARUM ES DIESEN ZWEITEN ZÄHLER GIBT

`core/tests/test_farbklassen.py` misst seit E2.1 die fest verdrahteten
Tailwind-Farbklassen in den **Vorlagen**: von 7437 auf 408, also 95 Prozent
abgebaut. Diese Zahl stimmt — und sie führt trotzdem in die Irre, wenn man sie
für die ganze Schuld hält.

Der Fund kam beim Aufräumen des Dunkelmodus-Overlays. Vierzehn Klassen, die
das Overlay umdefiniert, hatten in keiner Vorlage mehr ein Gegenstück; sie
sahen nach totem Code aus. Eine Suche über **alle** Quellen zeigte: **neun von
vierzehn** stehen im Python-Code und werden erst beim Rendern eingesetzt.

    core/views/fw/schaeden.py:38     'bg-sky-50'
    crm/admin.py:138                 'bg-indigo-100'
    portfolio/admin.py:405           'text-amber-500'

Hätte ich die Overlay-Regeln entfernt, wäre für diese neun Klassen der
Dunkelmodus ausgefallen — lautlos, und nur im Dunkelmodus sichtbar.

WAS DARAUS FOLGT

Für die drei Zwecke aus dem Kopf von `test_farbklassen.py` (Dunkelmodus,
mandantenspezifisches Branding, eine Änderung an einer Stelle) macht es keinen
Unterschied, ob eine Klasse in einer Vorlage oder in einem View steht.

Dieser Zähler arbeitet wie sein Geschwister: eine Obergrenze je Datei, die nur
sinken darf. Wer aufräumt, trägt die neue Zahl ein.

DIE ERSTE FASSSUNG MASS FALSCH — UM DEN FAKTOR DREI
---------------------------------------------------

Sie suchte Zeichenketten mit `['"]([^'"\n]{0,300})['"]` und meldete **221 in
20 Dateien**. Die Admin-Dateien schreiben ihre Kennzeichen aber als
HTML-Fragmente:

    format_html('<span class="bg-indigo-100 text-indigo-800">…</span>')

Das äussere Literal steht in einfachen, das Klassenattribut in doppelten
Anführungszeichen. Der Ausdruck bricht am ersten `"` ab, setzt dort neu an —
und die Klassenkette fällt **zwischen** zwei Treffer. Ergebnis: `crm/admin.py`
mit 112 Farbklassen wurde als **0** gezählt.

Gemessen mit dem Syntaxbaum: **687 in 24 Dateien**, nicht 221 in 20. Der
Zähler übersah 466 — mehr als das Doppelte dessen, was er fand. Ein Zähler,
der zwei Drittel nicht sieht, ist schlimmer als keiner: Er beziffert die
Schuld und beruhigt.

Jetzt liest `_zaehle` den **Syntaxbaum**. Der kennt Verschachtelung und
Anführungszeichen von sich aus, und er kennt keine Kommentare. Docstrings
werden ausgenommen — sie sind Prosa, sonst zählte dieser Erklärtext hier mit.

**STAND 478 in 5 Dateien.**

Alles davon steht in `admin.py`: Djangos eigene Oberfläche lädt die
Komponentenschicht nicht. Views und Dienste sind seit E2.20 auf null.

DIE ADMIN-FRAGE IST ENTSCHIEDEN: SIE BLEIBEN
=============================================

Diese 478 plus 191 in sechs Admin-Vorlagen — zusammen 669 — werden NICHT
umgestellt. Das ist eine Entscheidung, kein übersehener Rest.

WARUM

Die Komponentenschicht existiert für drei Dinge: Dunkelmodus,
mandantenspezifisches Branding (Entscheid D3, ab Professional), und eine
Änderung statt siebentausend. Keines davon trifft auf Djangos Admin zu.

Die Admin-Oberfläche sieht kein Kunde — weder Mieter noch Eigentümer noch die
Sachbearbeiterin einer Verwaltung. Sie ist das Werkzeug der Entwicklung. Ein
Mandant wird dort nie sein Logo sehen wollen, weil er die Seite nie aufruft.
Und `unfold` bringt einen eigenen Dunkelmodus mit.

Der Preis wäre auch nicht klein: Eine der beiden Hüllen stammt aus dem
Fremdpaket `django-unfold`. Sie zu überschreiben koppelt das Projekt an dessen
Innenleben — jede Aktualisierung kann das brechen, und zwar STILL, weil es
niemandem auffällt, der die Seite selten öffnet. Laufender Aufwand gegen einen
Nutzen, der sich nicht benennen lässt.

DAS ZIEL VON E2 HEISST DESHALB PRÄZISER

Nicht «null überall», sondern **null in dem, was wir selbst rendern**. Djangos
Admin ist eine fremde Oberfläche mit fremdem Gestaltungssystem — Werkzeugkasten,
nicht Produkt.

Die 478 unten sind damit keine Schuld, sondern eine Grenze. Die Obergrenze
hält sie fest: Sie darf nicht wachsen.

WANN DIESE ENTSCHEIDUNG ZU ÜBERDENKEN IST

Wenn die Admin-Oberfläche einmal Kunden gezeigt wird — etwa einer Verwaltung
zur Stammdatenpflege. Dann wird sie Produkt, und die Rechnung dreht sich.

WAS ER NICHT SIEHT

Zusammengesetzte Namen (`f'bg-{farbe}-50'`) und Werte aus der Datenbank. Wer
so etwas einführt, entzieht es dieser Messung; das steht hier, damit niemand
mehr Sicherheit annimmt, als da ist.
"""
import ast
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Identisch zum Muster in `test_farbklassen.py` — die beiden Zähler müssen
#: dasselbe meinen, sonst sind ihre Summen nicht vergleichbar.
FARBMUSTER = re.compile(
    r'\b(?:bg|text|border|ring|from|via|to|divide|placeholder|decoration|'
    r'outline|shadow|accent|caret|fill|stroke)-'
    r'(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|'
    r'emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|'
    r'white|black)(?:-\d{2,3})?(?:/\d{1,3})?\b')


#: Stand vom 24.08.2026. Obergrenze je Datei — nur senken.
OBERGRENZE = {
    'crm/admin.py': 112,
    'finance/admin.py': 63,
    'portfolio/admin.py': 189,
    'rentals/admin.py': 63,
    'tickets/admin.py': 51,
}


def _zeichenketten(baum):
    """Alle Zeichenketten-Literale ausser Docstrings.

    Über den Syntaxbaum, nicht über einen Ausdruck: Er kennt Verschachtelung
    und gemischte Anführungszeichen von sich aus. Genau daran ist die erste
    Fassung gescheitert (siehe Kopf dieser Datei).
    """
    prosa = set()
    for k in ast.walk(baum):
        if isinstance(k, (ast.Module, ast.ClassDef,
                          ast.FunctionDef, ast.AsyncFunctionDef)):
            if (k.body and isinstance(k.body[0], ast.Expr)
                    and isinstance(k.body[0].value, ast.Constant)
                    and isinstance(k.body[0].value.value, str)):
                prosa.add(id(k.body[0].value))
    for k in ast.walk(baum):
        if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                and id(k) not in prosa):
            yield k.value


def _zaehle(pfad):
    try:
        baum = ast.parse(pfad.read_text(encoding='utf-8', errors='ignore'))
    except SyntaxError:
        return 0
    return sum(len(FARBMUSTER.findall(s)) for s in _zeichenketten(baum))


def _alle_quellen():
    """Produktiver Python-Code. Tests und Migrationen bleiben draussen.

    Tests dürfen Farbklassen nennen — sie prüfen sie ja. Migrationen sind
    Bestand, den niemand mehr anfasst.
    """
    for p in sorted(WURZEL.rglob('*.py')):
        rel = p.relative_to(WURZEL).as_posix()
        if any(x in rel for x in ('node_modules', '/migrations/', '/tests/')):
            continue
        if '/test_' in rel or rel.startswith('test'):
            continue
        yield rel, p


class FarbklassenImPythonCodeTest(SimpleTestCase):

    def test_keine_datei_bekommt_mehr_farbklassen(self):
        gewachsen = []
        for rel, pfad in _alle_quellen():
            ist, grenze = _zaehle(pfad), OBERGRENZE.get(rel, 0)
            if ist > grenze:
                gewachsen.append(f'{rel}: {grenze} → {ist}')
        self.assertEqual(
            gewachsen, [],
            'Diese Python-Dateien setzen mehr Farbklassen als zuvor:\n  '
            + '\n  '.join(gewachsen)
            + '\n\nEine Farbe, die im View entsteht, ist genauso fest '
              'verdrahtet wie eine in der Vorlage — sie folgt weder dem '
              'Dunkelmodus noch einer Akzentfarbe je Mandant. Statt '
              "`'bg-sky-50'` gehört dorthin ein Ton der Komponentenschicht "
              "(`{'ton': 'fw-info'}`), den `fw/_schicht.html` auflöst.")

    def test_gesunkene_zahlen_werden_nachgefuehrt(self):
        gesunken = []
        for rel, pfad in _alle_quellen():
            ist, grenze = _zaehle(pfad), OBERGRENZE.get(rel)
            if grenze is not None and ist < grenze:
                gesunken.append(f'{rel}: {grenze} → {ist}')
        self.assertEqual(
            gesunken, [],
            'Hier wurde aufgeräumt — bitte OBERGRENZE nachführen:\n  '
            + '\n  '.join(gesunken)
            + '\n\n(Bei 0 den Eintrag ganz streichen.)')

    def test_der_stand_im_kopf_stimmt(self):
        """Die Zahl im Erklärtext darf nicht altern.

        Dieselbe Vorkehrung wie beim Vorlagen-Zähler, wo der Kopf zweimal eine
        Zahl nannte, die niemand nachgerechnet hatte.
        """
        treffer = re.search(r'STAND (\d+) in (\d+) Dateien', __doc__ or '')
        self.assertIsNotNone(
            treffer,
            'Im Kopf dieser Datei fehlt die Zeile «STAND <n> in <m> Dateien».')

        gezaehlt = {rel: _zaehle(p) for rel, p in _alle_quellen()}
        gesamt = sum(gezaehlt.values())
        dateien = sum(1 for n in gezaehlt.values() if n)
        self.assertEqual(
            (gesamt, dateien), (int(treffer.group(1)), int(treffer.group(2))),
            f'Der Kopf sagt {treffer.group(1)} in {treffer.group(2)} Dateien, '
            f'gemessen sind es {gesamt} in {dateien}.')

    def test_die_messung_findet_ueberhaupt_etwas(self):
        """Blindheitsprüfung — am Ausdruck, nicht am Bestand.

        Verankerte man sie an einer echten Datei, meldete sie Fortschritt als
        Fehler, sobald die aufgeräumt ist. Dieselbe Lehre wie bei
        `test_die_messung_findet_ueberhaupt_etwas` in
        `faelle/test_bereichsgestaltung.py`.

        DER DRITTE FALL IST DIE EIGENTLICHE REGRESSIONSPRÜFUNG: An genau
        diesem Muster — HTML-Fragment in einfachen, Klassenattribut in
        doppelten Anführungszeichen — hat die erste Fassung dieses Zählers
        112 Vorkommen in `crm/admin.py` als 0 gemeldet.
        """
        def zaehle(quelle):
            return sorted(x for s in _zeichenketten(ast.parse(quelle))
                          for x in FARBMUSTER.findall(s))

        self.assertEqual(
            zaehle("""kontext = {'ton': 'bg-sky-50', 'rand': "border-slate-200"}"""),
            ['bg-sky-50', 'border-slate-200'],
            'Der Ausdruck erkennt Farbklassen in Zeichenketten nicht mehr — '
            'dann sind alle Zahlen oben wertlos.')

        self.assertEqual(
            zaehle('x = 1  # bg-slate-100 im Kommentar'), [],
            'Ein Kommentar wird als Verwendung gezählt.')

        self.assertEqual(
            zaehle("""s = format_html('<span class="bg-indigo-100 text-indigo-800">x</span>')"""),
            ['bg-indigo-100', 'text-indigo-800'],
            'Das HTML-Fragment mit gemischten Anführungszeichen wird nicht '
            'erkannt — genau daran ist die erste Fassung gescheitert, und '
            'genau so schreiben die admin.py ihre Kennzeichen.')

        self.assertEqual(
            zaehle('"""Ein Docstring mit bg-rose-50."""\nx = 1'), [],
            'Ein Docstring wird als Verwendung gezählt — dann zählte der '
            'Erklärtext dieser Datei mit.')

        self.assertGreater(
            len(list(_alle_quellen())), 50,
            'Kaum Python-Dateien gefunden — stimmt der Suchpfad noch?')
