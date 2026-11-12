"""Prüfung der Datenbankrolle: Befunde, SQLite-Pfad und (auf PostgreSQL) die echte Abfrage."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from core.services import db_rolle
from core.tests._parallel import NUR_POSTGRES


class RolleTests(TestCase):

    def _lauf(self, *args):
        aus = StringIO()
        call_command('datenbank_rolle_pruefen', *args, stdout=aus)
        return aus.getvalue()

    def test_sqlite_hat_keine_rollen(self):
        if connection.vendor == 'postgresql':
            self.skipTest('nur SQLite')
        self.assertIsNone(db_rolle.pruefen())
        self.assertIn('SQLite', self._lauf('--streng'))

    def test_befund_ohne_streng_nur_hinweis(self):
        with mock.patch.object(db_rolle, 'pruefen', return_value=['«x» ist Superuser']):
            self.assertIn('Superuser', self._lauf())

    def test_befund_mit_streng_ist_fehler(self):
        with mock.patch.object(db_rolle, 'pruefen', return_value=['«x» ist Superuser']):
            with self.assertRaises(CommandError):
                self._lauf('--streng')

    def test_ohne_befund_ok(self):
        with mock.patch.object(db_rolle, 'pruefen', return_value=[]):
            self.assertIn('eingeschränkt', self._lauf('--streng'))

    @NUR_POSTGRES
    def test_echte_abfrage_laeuft_und_liefert_befunde_fuer_eigentuemer(self):
        befunde = db_rolle.pruefen()
        self.assertIsInstance(befunde, list)
        # Die Testrolle hat die Tabellen selbst angelegt: Das muss auffallen.
        self.assertTrue(any('Eigentümerin' in b or 'Superuser' in b for b in befunde))
