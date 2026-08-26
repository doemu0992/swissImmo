"""Der Baustein für Zeichen aus den DATEN — und die Datenwerte selbst.

WOFÜR ER DA IST

An 29 Stellen setzt eine Vorlage den Namen aus den Daten ein; der Name steht
in einer Tabelle im Python-Code (Kachellisten, Termin-Arten, Gewerke). Dort
ist das Zeichen ein Datenwert, kein Markup, und `{% zeichen 'name' %}` mit
fester Zeichenkette hilft nicht.

WARUM ER NICHT WIRFT

`zeichen` wirft bei unbekanntem Namen — richtig, wenn jemand ihn tippt.
`zeichen_wert` darf das nicht: Ein alter Wert in der Datenbank oder eine noch
nicht umgestellte Zeile würde die ganze Seite abstürzen lassen. Stattdessen
Rückfall auf `hinweis`, protokolliert.

WARUM DAS GEPRÜFT WERDEN MUSS

Genau dieser Rückfall ist **still**. Er hält die Seite am Leben und macht
dabei aus jedem vergessenen Datenwert ein Info-Zeichen — eine Falschaussage,
die aussieht wie eine Gestaltungsentscheidung. E2.41 hat ihn eingeführt und
im Browser einmal nachgesehen, dass er nicht greift; geprüft war er nicht.
Eine Beobachtung ist keine Sperre: Der nächste vergessene Datenwert fällt
still zurück, und niemand sieht es.
"""
import logging
import pathlib
import re

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Felder, unter denen ein Zeichenname als Datenwert steht.
FELDER = ('icon', 'ikon', 'symbol', 'typ_icon')


#: Zuordnungstabellen auf Modulebene: `BRANCHE_ICON`, `TERMIN_IKON`,
#: `DOK_ICON`. Ihre Werte sind teils blosse Zeichenketten, teils Tupel
#: `('name', 'farbklasse')` — der Name steht immer zuerst.
TABELLE = re.compile(r'^[A-Z][A-Z0-9_]*(?:ICON|IKON|SYMBOL)\s*=\s*\{')


def _datenwerte():
    """Jeder Zeichenname, der im Python-Code als Datenwert steht.

    Ergibt `(datei, zeile, name)`. Testdateien bleiben aussen vor.

    ZWEI FORMEN, UND DIE ZWEITE WAERE FAST DURCHGERUTSCHT

    Die erste Fassung suchte nur `'icon': 'name'`. Die Gewerke stehen aber
    als Tupel in einer Zuordnungstabelle:

        BRANCHE_ICON = {'garten': ('arbeit', 'fw-gut-flaeche fw-gut'), ...}

    Gegenprobe mit einem erfundenen Namen dort: alle acht Pruefungen blieben
    gruen. Deshalb werden Tabellen, deren Name auf ICON/IKON/SYMBOL endet,
    mitgelesen — der Zeichenname steht dort immer an erster Stelle.

    GRENZE: Eine Zuordnungstabelle unter anderem Namen faende dieser Scan
    nicht. Ein noch nicht umgestellter `fa-`-Wert faellt dann immer noch der
    Sperrklinke in `test_zeichensatz` auf; ein ERFUNDENER Name nicht.
    """
    feld = re.compile(r"'(?:%s)':\s*'([a-z][a-z0-9_-]*)'" % '|'.join(FELDER))
    eintrag = re.compile(r"^\s*'[^']+':\s*\(?'([a-z][a-z0-9_-]*)'")
    for p in sorted(WURZEL.rglob('*.py')):
        teile = p.parts
        if ('node_modules' in teile or 'migrations' in teile
                or p.name.startswith('test_') or 'templatetags' in teile):
            continue
        in_tabelle = False
        for nr, zeile in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
            for treffer in feld.findall(zeile):
                yield p.relative_to(WURZEL), nr, treffer
            if TABELLE.match(zeile):
                in_tabelle = True
                continue
            if in_tabelle:
                if zeile.startswith('}'):
                    in_tabelle = False
                    continue
                m = eintrag.match(zeile)
                if m:
                    yield p.relative_to(WURZEL), nr, m.group(1)


class ZeichenWertTest(SimpleTestCase):

    def _rendern(self, ausdruck, **kontext):
        vorlage = Template('{% load zeichen %}' + ausdruck)
        return vorlage.render(Context(kontext))

    def test_ein_bekannter_name_wird_gezeichnet(self):
        aus = self._rendern('{% zeichen_wert n %}', n='liegenschaft')
        self.assertIn('#z-liegenschaft', aus)
        self.assertIn('fw-zeichen', aus)

    def test_ein_unbekannter_name_faellt_auf_hinweis_zurueck(self):
        """Die Seite darf nicht abstürzen, weil ein Datenwert veraltet ist."""
        with self.assertLogs('core.templatetags.zeichen', level='WARNING'):
            aus = self._rendern('{% zeichen_wert n %}', n='gibtesnicht')
        self.assertIn('#z-hinweis', aus)

    def test_ein_alter_font_awesome_wert_faellt_ebenfalls_zurueck(self):
        with self.assertLogs('core.templatetags.zeichen', level='WARNING'):
            aus = self._rendern('{% zeichen_wert n %}', n='fa-plug')
        self.assertIn('#z-hinweis', aus)

    def test_ein_leerer_wert_stuerzt_nicht_ab(self):
        """Ein fehlendes Feld im Kontext ergibt eine leere Zeichenkette."""
        with self.assertLogs('core.templatetags.zeichen', level='WARNING'):
            aus = self._rendern('{% zeichen_wert n %}', n='')
        self.assertIn('#z-hinweis', aus)

    def test_der_rueckfall_wird_nur_einmal_je_name_gemeldet(self):
        """Sonst füllt eine Kachelliste das Logbuch bei jedem Aufruf."""
        from core.templatetags import zeichen as baustein

        baustein._gemeldet.discard('nurEinmalGemeldet')
        with self.assertLogs('core.templatetags.zeichen', level='WARNING') as erst:
            self._rendern('{% zeichen_wert n %}', n='nurEinmalGemeldet')
        self.assertEqual(len(erst.output), 1)

        # Zweiter Aufruf: kein weiterer Eintrag. `assertNoLogs` gibt es erst
        # ab Python 3.10 — hier zaehlen statt zusichern.
        mitschrift = []
        griff = logging.Handler()
        griff.emit = mitschrift.append
        log = logging.getLogger('core.templatetags.zeichen')
        log.addHandler(griff)
        try:
            self._rendern('{% zeichen_wert n %}', n='nurEinmalGemeldet')
        finally:
            log.removeHandler(griff)
        self.assertEqual(mitschrift, [])


class DatenwerteTest(SimpleTestCase):
    """Die Werte selbst — sonst prüft der Rückfall sich selbst.

    E2.41 hat 139 Datenwerte umgestellt. Bliebe einer stehen, fiele er still
    auf `hinweis` zurück: Die Seite sieht heil aus, das Zeichen ist falsch.
    """

    def test_jeder_datenwert_ist_ein_bekanntes_zeichen(self):
        from core.templatetags.zeichen import erlaubte_zeichen

        erlaubt = erlaubte_zeichen()
        # Werte, die keine Zeichennamen sind (Schlüssel anderer Bedeutung).
        egal = {'crit', 'warn', 'info', 'ok'}
        fehlend = [f'{d}:{nr} → «{n}»' for d, nr, n in _datenwerte()
                   if n not in erlaubt and n not in egal]
        self.assertEqual(
            fehlend, [],
            f'Diese Datenwerte sind keine Zeichen aus docs/ZEICHEN.md und '
            f'fallen still auf «hinweis» zurück: {fehlend}')

    def test_kein_datenwert_traegt_noch_font_awesome(self):
        alt = [f'{d}:{nr} → «{n}»' for d, nr, n in _datenwerte()
               if n.startswith('fa-')]
        self.assertEqual(alt, [], f'Noch nicht umgestellt: {alt}')

    def test_die_pruefung_findet_ueberhaupt_datenwerte(self):
        """Gegenprobe: Eine leere Liste wäre trivial grün."""
        self.assertGreater(len(list(_datenwerte())), 80)
