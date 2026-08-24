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

Gemessen am 24.08.2026: **221 Farbklassen in 20 Python-Dateien**. Zusammen mit
den 408 aus den Vorlagen sind das 629 — gut ein Drittel der Restschuld war
nicht gezählt. Für die drei Zwecke aus dem Kopf von `test_farbklassen.py`
(Dunkelmodus, mandantenspezifisches Branding, eine Änderung an einer Stelle)
macht es keinen Unterschied, ob eine Klasse in einer Vorlage oder in einem
View steht.

Dieser Zähler arbeitet wie sein Geschwister: eine Obergrenze je Datei, die nur
sinken darf. Wer aufräumt, trägt die neue Zahl ein.

WAS GEZÄHLT WIRD

Nur **Zeichenketten-Literale**. Ein Kommentar, der `bg-slate-100` erwähnt,
zählt nicht — dieselbe Lehre wie beim Vorlagen-Zähler, der über seinen eigenen
Erklärtext gestolpert ist.

**STAND 221 in 20 Dateien.**

WAS ER NICHT SIEHT

Zusammengesetzte Namen (`f'bg-{farbe}-50'`) und Werte aus der Datenbank. Wer
so etwas einführt, entzieht es dieser Messung; das steht hier, damit niemand
mehr Sicherheit annimmt, als da ist.
"""
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

#: Einzeilige Zeichenketten-Literale. Reicht für den Bestand: Die Klassen
#: stehen durchweg in kurzen Literalen wie `{'ton': 'bg-sky-50'}`.
LITERAL = re.compile(r'''['"]([^'"\n]{0,300})['"]''')

#: Stand vom 24.08.2026. Obergrenze je Datei — nur senken.
OBERGRENZE = {
    'core/services/ersatzplanung.py': 8,
    'core/services/inbox.py': 10,
    'core/services/mahnstufen.py': 9,
    'core/views/dashboard_view.py': 8,
    'core/views/fw/_basis.py': 20,
    'core/views/fw/bankkonten.py': 6,
    'core/views/fw/dashboard.py': 24,
    'core/views/fw/detailseiten.py': 4,
    'core/views/fw/dienstleister.py': 18,
    'core/views/fw/dokumente.py': 10,
    'core/views/fw/kautionen.py': 8,
    'core/views/fw/kreditoren.py': 14,
    'core/views/fw/listen.py': 6,
    'core/views/fw/mietprozess.py': 12,
    'core/views/fw/mietzins.py': 6,
    'core/views/fw/pendenzen.py': 4,
    'core/views/fw/person.py': 2,
    'core/views/fw/schaeden.py': 26,
    'core/views/portal.py': 14,
    'tickets/admin.py': 12,
}


def _zaehle(pfad):
    text = pfad.read_text(encoding='utf-8', errors='ignore')
    return sum(len(FARBMUSTER.findall(l)) for l in LITERAL.findall(text))


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
        """
        beispiel = '''kontext = {'ton': 'bg-sky-50', 'rand': "border-slate-200"}'''
        self.assertEqual(
            sorted(FARBMUSTER.findall(' '.join(LITERAL.findall(beispiel)))),
            ['bg-sky-50', 'border-slate-200'],
            'Der Ausdruck erkennt Farbklassen in Zeichenketten nicht mehr — '
            'dann sind alle Zahlen oben wertlos.')
        self.assertEqual(
            FARBMUSTER.findall(' '.join(LITERAL.findall('# bg-slate-100 im Kommentar'))),
            [],
            'Ein Kommentar wird als Verwendung gezählt.')
        self.assertGreater(
            len(list(_alle_quellen())), 50,
            'Kaum Python-Dateien gefunden — stimmt der Suchpfad noch?')
