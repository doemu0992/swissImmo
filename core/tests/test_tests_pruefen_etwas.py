"""Jeder Test prüft etwas: eine Assertion, direkt oder über eine Hilfsfunktion, die eine enthält (SICH-45, Testgüte).

WARUM
Der Audit zählte 61 Testfunktionen ohne eine Assertion im Körper. Ein Teil davon ist harmlos (die Prüfung steht
in einer Hilfsfunktion), ein Teil steht für «läuft ohne Fehler», und das ist ein Test, der auch dann grün bleibt,
wenn die Funktion nichts mehr tut. Dieser Wächter schliesst die Lücke für alles Neue und für den Bestand:

Ein Test gilt als prüfend, wenn sein Körper
* eine `assert`-Anweisung oder einen Aufruf `assert…`/`fail`/`skipTest` enthält (auch `self.assertRaises` als
  `with`-Block), oder
* eine Funktion oder Methode derselben Datei aufruft, die ihrerseits so prüft (bis zur dritten Stufe), oder
* in `OHNE_ASSERTION` mit Begründung steht.

`OHNE_ASSERTION` ist die Liste der bewussten Rauchtests («läuft überhaupt», der Fehler ist die Aussage). Sie wird
nie länger, ohne dass jemand den Grund liest; wer eine Zeile streicht, indem er eine Assertion ergänzt, hat einen
besseren Test.

Gegenprobe: in einer beliebigen Testdatei einen Test ohne Assertion anlegen, und `test_jeder_test_prueft_etwas`
wird rot (Protokoll im Commit).
"""
import ast
import os
from pathlib import Path

from django.test import SimpleTestCase

WURZEL = Path(__file__).resolve().parents[2]
AUSSERHALB = {'.git', '.claude', 'node_modules', 'migrations', '__pycache__', 'static', 'staticfiles'}
SELBST = 'core/tests/test_tests_pruefen_etwas.py'

#: Rauchtests und Messwerkzeuge ohne Assertion — «Datei::Klasse.test»: Begründung.
OHNE_ASSERTION = {
    'core/tests/test_scheduler_organisation.py::BefehleLaufenUeberhauptTests': (
        'Rauchtests: Ein Scheduler-Befehl, der wirft, ist kaputt; der Traceback ist die Aussage (6.2-Regression)'),
    'core/tests/test_isolation.py::AusnahmenSindBegruendetTests.test_die_ausgenommenen_modelle_gibt_es_wirklich': (
        '`apps.get_model` wirft bei einem Tippfehler im Label; das ist die Aussage'),
    'core/tests_perf.py': 'Messwerkzeug (PERF), kein Test im Sinn der Suite; läuft nicht im Standardlauf',
    'core/tests_perf2.py': 'Messwerkzeug (PERF), kein Test im Sinn der Suite; läuft nicht im Standardlauf',
}


def _ist_pruefung(knoten):
    """Enthält dieser Teilbaum selbst eine Prüfung?"""
    for n in ast.walk(knoten):
        if isinstance(n, ast.Assert):
            return True
        if isinstance(n, ast.Call):
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', '')
            if name.startswith('assert') or name in ('fail', 'skipTest'):
                return True
    return False


def _aufrufe(knoten):
    namen = set()
    for n in ast.walk(knoten):
        if isinstance(n, ast.Call):
            namen.add(n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', ''))
    return namen


def tests_ohne_pruefung(quelle):
    """[(Klasse, Testname)] der Testfunktionen in `quelle` ohne Prüfung (direkt oder über Hilfen derselben Datei)."""
    baum = ast.parse(quelle)
    funktionen = {}
    for n in ast.walk(baum):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funktionen.setdefault(n.name, []).append(n)
    prueft = {name for name, defs in funktionen.items() if any(_ist_pruefung(d) for d in defs)}
    for _ in range(3):                       # Hilfe ruft Hilfe: drei Stufen genügen im Bestand
        prueft |= {name for name, defs in funktionen.items()
                   if any(_aufrufe(d) & prueft for d in defs)}
    ergebnis = []
    for klasse in (n for n in ast.walk(baum) if isinstance(n, ast.ClassDef)):
        for f in klasse.body:
            if isinstance(f, ast.FunctionDef) and f.name.startswith('test'):
                if not _ist_pruefung(f) and not (_aufrufe(f) & prueft):
                    ergebnis.append((klasse.name, f.name))
    return ergebnis


def _testdateien():
    for ordner, unterordner, dateien in os.walk(WURZEL):
        unterordner[:] = [d for d in unterordner if d not in AUSSERHALB]
        for name in dateien:
            if not name.endswith('.py'):
                continue
            pfad = Path(ordner) / name
            rel = pfad.relative_to(WURZEL).as_posix()
            if rel != SELBST and ('/tests/' in '/' + rel or name.startswith(('test_', 'tests')) or rel.endswith('/tests.py')):
                yield rel, pfad


def _erlaubt(rel, klasse, test):
    return any(schluessel in (rel, f'{rel}::{klasse}', f'{rel}::{klasse}.{test}') for schluessel in OHNE_ASSERTION)


class TestsPruefenEtwasTests(SimpleTestCase):

    def test_jeder_test_prueft_etwas(self):
        ohne = []
        geprueft = 0
        for rel, pfad in _testdateien():
            for klasse, test in tests_ohne_pruefung(pfad.read_text(encoding='utf-8')):
                if not _erlaubt(rel, klasse, test):
                    ohne.append(f'{rel}::{klasse}.{test}')
            geprueft += 1
        self.assertGreater(geprueft, 200, 'auffällig wenige Testdateien gelesen')
        self.assertEqual(ohne, [], 'Tests ohne Assertion (direkt oder über eine Hilfe): eine Prüfung ergänzen. '
                                   'Ein Test, der nur «läuft ohne Fehler» sagt, bleibt grün, wenn die Funktion '
                                   'nichts mehr tut. Bewusste Rauchtests mit Grund in OHNE_ASSERTION.')

    def test_die_ausnahmen_gibt_es_noch(self):
        """Ratsche: Eine Ausnahme, die nichts mehr deckt, wird gestrichen."""
        vorhanden = {rel: pfad for rel, pfad in _testdateien()}
        for schluessel in OHNE_ASSERTION:
            rel = schluessel.split('::')[0]
            with self.subTest(ausnahme=schluessel):
                self.assertIn(rel, vorhanden, 'Datei gibt es nicht mehr: Ausnahme streichen')
                self.assertGreater(len(OHNE_ASSERTION[schluessel]), 25, 'Begründung fehlt')

    def test_der_erkenner_unterscheidet(self):
        """Selbstprüfung: ohne sie wäre ein Wächter, der nichts findet, nicht von einem blinden zu unterscheiden."""
        quelle = '''
class T:
    def _hilfe(self):
        self.assertEqual(1, 1)
    def test_a(self):
        x = 1
    def test_b(self):
        self.assertTrue(True)
    def test_c(self):
        self._hilfe()
    def test_d(self):
        with self.assertRaises(ValueError):
            int('x')
    def test_e(self):
        assert True
'''
        self.assertEqual(tests_ohne_pruefung(quelle), [('T', 'test_a')])
