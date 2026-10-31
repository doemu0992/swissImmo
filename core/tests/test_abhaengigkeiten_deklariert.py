"""Jeder Fremd-Import im Programm steht in `requirements.txt`.

Der Fehler, den dieser Wächter fängt: Ein Modul importiert ein Paket, das nur zufällig auf der Entwicklungsmaschine
installiert ist (hier `dateutil`). Lokal laufen alle Tests, die CI bricht beim Start ab (`ModuleNotFoundError`).

Gegenprobe: in irgendeine Programmdatei `import dateutil` schreiben, und der Test nennt Datei und Paket.
"""
import ast
import re
import sys
from importlib import metadata
from pathlib import Path

from django.test import SimpleTestCase

WURZEL = Path(__file__).resolve().parents[2]
AUSSERHALB = {'.git', '.claude', 'node_modules', 'staticfiles', '__pycache__', 'docs', 'e2e', 'mockups', 'migrations',
              'venv', '.venv', 'media', 'logs'}
#: Pakete, die absichtlich nicht in `requirements.txt` stehen (Entwicklungswerkzeug), mit Grund.
ENTWICKLUNG = {
    'playwright': 'nur e2e, über npm',
}


def _norm(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def _deklariert():
    namen = set()
    for zeile in (WURZEL / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        zeile = zeile.split('#')[0].strip()
        if not zeile or zeile.startswith('-'):
            continue
        namen.add(_norm(re.split(r'[=<>!~\[; ]', zeile, maxsplit=1)[0]))
    return namen


def _lokale_module():
    lokal = set()
    for p in WURZEL.iterdir():
        if p.name in AUSSERHALB:
            continue
        if p.is_dir() and (p / '__init__.py').exists():
            lokal.add(p.name)
        elif p.suffix == '.py':
            lokal.add(p.stem)
    return lokal


class AbhaengigkeitenDeklariertTests(SimpleTestCase):

    def test_jeder_fremd_import_steht_in_requirements(self):
        deklariert = _deklariert()
        lokal = _lokale_module()
        verteilungen = metadata.packages_distributions()
        fehlend = {}
        geprueft = 0
        for pfad in WURZEL.rglob('*.py'):
            if any(teil in AUSSERHALB for teil in pfad.relative_to(WURZEL).parts):
                continue
            try:
                baum = ast.parse(pfad.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for knoten in ast.walk(baum):
                if isinstance(knoten, ast.Import):
                    namen = [a.name.split('.')[0] for a in knoten.names]
                elif isinstance(knoten, ast.ImportFrom) and knoten.level == 0 and knoten.module:
                    namen = [knoten.module.split('.')[0]]
                else:
                    continue
                for name in namen:
                    if name in sys.stdlib_module_names or name in lokal or name in ENTWICKLUNG:
                        continue
                    geprueft += 1
                    dists = {_norm(d) for d in verteilungen.get(name, [])}
                    if not dists & deklariert and _norm(name) not in deklariert:
                        fehlend.setdefault(name, set()).add(pfad.relative_to(WURZEL).as_posix())
        self.assertGreater(geprueft, 100, 'Es wurden kaum Importe gefunden, der Wächter prüft nichts.')
        self.assertEqual(
            {k: sorted(v)[:3] for k, v in fehlend.items()}, {},
            'Diese Pakete werden importiert, stehen aber nicht in requirements.txt (auf der CI fehlt dann das Modul).')
