"""Wächter gegen neue Kalender-Zeitbomben in Tests (SICH-45).

WARUM
Ein Test, der `date.today()` oder `datetime.now()` ruft, rechnet mit der Uhr der Maschine. Das ist
nicht verboten, aber es sind die Stellen, an denen die Suite an einem bestimmten Kalendertag rot wird:

* Läuft der Test unter `@bei_stichtag` (core/tests/_uhr.py), friert die feste Uhr nur `timezone.now`
  ein. Die echte Uhr bleibt bei der Maschine, und Test und Code reden von verschiedenen Tagen.
* Code unter Test, der den Zürcher Tag (`core.zeit.datum_heute()`) oder Werktage
  (`core/services/fristen.py`) nimmt, weicht von der Maschinenuhr ab, sobald die Zeitzonen
  auseinanderliegen (die CI läuft oft nach 22:00 UTC, in Zürich schon am Folgetag).

DIE REGELN
1. In Dateien mit `bei_stichtag` keine Maschinenuhr: dort gibt es nur `timezone.localdate()`.
2. Die Zahl der Stellen je Testdatei steigt nie über die Basislinie (`zeit_basislinie.json`), und eine Datei,
   die dort nicht steht, hat keine. Neue Tests nehmen `timezone.localdate()` bzw. `_helfer.vor_tagen()`,
   oder fahren unter `bei_stichtag`.
3. Die Basislinie darf nur sinken: Wer Stellen entfernt, senkt auch die Zahl (der Test meldet es).

Die Basislinie ist keine Freigabe der Altstellen, sondern die Liste dessen, was noch abzubauen ist.
Gegenprobe: in einer beliebigen neuen Testdatei eine Maschinenuhr-Stelle einfügen, und der Test wird rot.
"""
import json
import os
import re
from pathlib import Path

from django.test import SimpleTestCase

WURZEL = Path(__file__).resolve().parents[2]
BASIS = Path(__file__).with_name('zeit_basislinie.json')
MUSTER = re.compile(r'\bdate\.today\(\)|\bdatetime\.(?:now|today|utcnow)\(\)|\.now\(\)\.date\(\)')
AUSSERHALB = {'.git', '.claude', 'node_modules', 'migrations', '__pycache__', 'static', 'staticfiles'}
SELBST = 'core/tests/test_zeit_waechter.py'


def _teststellen():
    """{relativer Pfad: (Anzahl, Datei nutzt bei_stichtag)} für alle Testdateien."""
    erg = {}
    for ordner, unterordner, dateien in os.walk(WURZEL):
        unterordner[:] = [d for d in unterordner if d not in AUSSERHALB]
        for name in dateien:
            if not name.endswith('.py'):
                continue
            pfad = Path(ordner) / name
            rel = pfad.relative_to(WURZEL).as_posix()
            if rel == SELBST:
                continue
            if not ('/tests/' in '/' + rel or name.startswith(('test_', 'tests')) or rel.endswith('/tests.py')):
                continue
            text = pfad.read_text(encoding='utf-8')
            anzahl = len(MUSTER.findall(text))
            if anzahl:
                erg[rel] = (anzahl, 'bei_stichtag' in text and rel != 'core/tests/_uhr.py')
    return erg


class ZeitWaechterTests(SimpleTestCase):

    def test_unter_fester_uhr_keine_maschinenuhr(self):
        verstoesse = [rel for rel, (_n, fest) in _teststellen().items() if fest]
        self.assertEqual(verstoesse, [], 'Datei mit bei_stichtag ruft die Maschinenuhr: '
                                         'dort `timezone.localdate()` nehmen, sonst reden Test und Code von zwei Tagen.')

    def test_keine_neuen_stellen_ueber_die_basislinie(self):
        basis = json.loads(BASIS.read_text(encoding='utf-8'))
        mehr = {rel: (n, basis.get(rel, 0)) for rel, (n, _f) in _teststellen().items() if n > basis.get(rel, 0)}
        self.assertEqual(mehr, {}, 'Neue Uhr-Zugriffe in Tests (jetzt, erlaubt): statt der Maschinenuhr '
                                   '`timezone.localdate()` oder `_helfer.vor_tagen()` nehmen, oder die Klasse mit '
                                   '`@bei_stichtag` auf einen festen Tag stellen.')

    def test_die_basislinie_sinkt_mit(self):
        """Ratsche: Wer Stellen abbaut, trägt die kleinere Zahl ein, sonst bliebe Luft für neue."""
        basis = json.loads(BASIS.read_text(encoding='utf-8'))
        stellen = _teststellen()
        luft = {rel: (stellen.get(rel, (0, 0))[0], n) for rel, n in basis.items()
                if stellen.get(rel, (0, 0))[0] < n}
        self.assertEqual(luft, {}, 'Basislinie zu hoch (jetzt, eingetragen): in core/tests/zeit_basislinie.json '
                                   'auf die tatsächliche Zahl senken bzw. die Zeile streichen.')

    def test_der_zaehler_sieht_die_muster(self):
        """Selbstprüfung: ein Zähler, der nichts zählt, wäre ein blinder Wächter."""
        text = 'a = date.today()\nb = datetime.now()\nc = timezone.now().date()\nd = timezone.localdate()\n'
        self.assertEqual(len(MUSTER.findall(text)), 3)
