"""SICH-04: Die Auswertung des CI-Jobs `pip-audit` (`_tools/pip_audit_pruefen.py`).

Gegenprobe: In `pruefen` die Zeile `(mit_fix if zeile[3] else ohne_fix)` auf `ohne_fix` stellen —
`test_schwachstelle_mit_fix_ist_ein_fund` wird rot.
"""
import importlib.util
import json
import pathlib
import tempfile

from django.conf import settings
from django.test import SimpleTestCase


def _modul():
    pfad = pathlib.Path(settings.BASE_DIR) / '_tools' / 'pip_audit_pruefen.py'
    spec = importlib.util.spec_from_file_location('pip_audit_pruefen', pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


BERICHT = {'dependencies': [
    {'name': 'django', 'version': '5.2.9', 'vulns': [
        {'id': 'PYSEC-1', 'aliases': ['CVE-2026-1'], 'fix_versions': ['5.2.17']}]},
    {'name': 'altlast', 'version': '1.0', 'vulns': [
        {'id': 'PYSEC-2', 'aliases': [], 'fix_versions': []}]},
    {'name': 'sauber', 'version': '2.0', 'vulns': []},
]}


class PipAuditAuswertungTests(SimpleTestCase):
    def setUp(self):
        self.m = _modul()

    def test_schwachstelle_mit_fix_ist_ein_fund(self):
        mit_fix, ohne_fix, _ungenutzt = self.m.pruefen(BERICHT, {})
        self.assertEqual([z[0] for z in mit_fix], ['django'])
        self.assertEqual([z[0] for z in ohne_fix], ['altlast'])          # nur Hinweis, nicht rot

    def test_begruendete_ausnahme_nimmt_den_fund_heraus_auch_ueber_den_alias(self):
        for kennung in ('PYSEC-1', 'CVE-2026-1'):
            mit_fix, _o, ungenutzt = self.m.pruefen(BERICHT, {kennung: 'weil es so ist, geprüft'})
            self.assertEqual(mit_fix, [], kennung)
            self.assertEqual(ungenutzt, [])

    def test_ungenutzte_ausnahme_wird_gemeldet(self):
        _m, _o, ungenutzt = self.m.pruefen(BERICHT, {'PYSEC-99': 'veraltet, längst behoben'})
        self.assertEqual(ungenutzt, ['PYSEC-99'])

    def test_ausnahme_ohne_begruendung_zaehlt_nicht(self):
        ausnahmen, fehler = self.m.ausnahmen_lesen(
            '# Kopf\n\nPYSEC-1\nPYSEC-2  # zu kurz\nPYSEC-3   # Begründung, die ausreicht; 28.10.2026\n')
        self.assertEqual(list(ausnahmen), ['PYSEC-3'])
        self.assertEqual(len(fehler), 2)

    def test_ende_zu_ende_exitcode(self):
        with tempfile.TemporaryDirectory() as ordner:
            bericht = pathlib.Path(ordner) / 'b.json'
            ignore = pathlib.Path(ordner) / 'i.txt'
            bericht.write_text(json.dumps(BERICHT), encoding='utf-8')
            ignore.write_text('', encoding='utf-8')
            self.assertEqual(self.m.main(['x', str(bericht), str(ignore)]), 1)
            ignore.write_text('PYSEC-1   # Update folgt nach dem Test, 28.10.2026 Dominik\n', encoding='utf-8')
            self.assertEqual(self.m.main(['x', str(bericht), str(ignore)]), 0)

    def test_die_ignore_datei_im_repo_ist_gueltig(self):
        text = (pathlib.Path(settings.BASE_DIR) / 'pip-audit-ignore.txt').read_text(encoding='utf-8')
        _ausnahmen, fehler = self.m.ausnahmen_lesen(text)
        self.assertEqual(fehler, [])
