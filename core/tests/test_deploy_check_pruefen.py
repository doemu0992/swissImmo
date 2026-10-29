"""SICH-28: Die Auswertung des CI-Schritts `check --deploy` (`_tools/deploy_check_pruefen.py`).

Gegenprobe: In `pruefen` die Zeile `offen = sorted(k for k in set(gefunden) if k not in ausnahmen)` auf
`offen = []` stellen, und `test_unbegruendete_warnung_ist_ein_fund` wird rot.
"""
import importlib.util
import pathlib

from django.conf import settings
from django.test import SimpleTestCase


def _modul():
    pfad = pathlib.Path(settings.BASE_DIR) / '_tools' / 'deploy_check_pruefen.py'
    spec = importlib.util.spec_from_file_location('deploy_check_pruefen', pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


AUSGABE = """System check identified some issues:

WARNINGS:
?: (security.W019) You have 'django.middleware.clickjacking.XFrameOptionsMiddleware' in your MIDDLEWARE
?: (security.W008) Your SECURE_SSL_REDIRECT setting is not set to True.

System check identified 2 issues (0 silenced).
"""


class DeployCheckPruefenTests(SimpleTestCase):
    def test_unbegruendete_warnung_ist_ein_fund(self):
        offen, ungenutzt = _modul().pruefen(AUSGABE, {'security.W019': 'Absicht, weil Popups'})
        self.assertEqual(offen, ['security.W008'])
        self.assertEqual(ungenutzt, [])

    def test_alles_begruendet_ist_sauber(self):
        offen, _ = _modul().pruefen(AUSGABE, {'security.W019': 'x' * 12, 'security.W008': 'y' * 12})
        self.assertEqual(offen, [])

    def test_ausnahme_ohne_treffer_wird_gemeldet(self):
        _, ungenutzt = _modul().pruefen(AUSGABE, {'security.W019': 'x' * 12, 'security.W999': 'y' * 12})
        self.assertEqual(ungenutzt, ['security.W999'])

    def test_ausnahme_ohne_begruendung_wird_abgewiesen(self):
        ausnahmen, fehler = _modul().ausnahmen_lesen('security.W019\nsecurity.W008  # kurz\nkeine kennung # ein langer Grund\n')
        self.assertEqual(ausnahmen, {})
        self.assertEqual(len(fehler), 3)

    def test_die_ignore_datei_des_repos_ist_gueltig(self):
        text = (pathlib.Path(settings.BASE_DIR) / 'deploy-check-ignore.txt').read_text(encoding='utf-8')
        ausnahmen, fehler = _modul().ausnahmen_lesen(text)
        self.assertEqual(fehler, [])
        self.assertIn('security.W019', ausnahmen)
