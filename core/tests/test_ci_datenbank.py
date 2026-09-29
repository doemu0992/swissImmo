"""Läuft der PostgreSQL-Job der CI wirklich auf PostgreSQL?

Der Job `test-postgres` in .github/workflows/ci.yml setzt `DB_ENGINE` und die
übrigen DB_-Variablen. Ein Tippfehler darin fiele nicht auf: `settings.py`
nähme still SQLite, die Suite liefe grün — und der Job prüfte nichts. Deshalb
setzt der Job zusätzlich `CI_DATENBANK=postgres`, und dieser Test verlangt
dann eine echte PostgreSQL-Verbindung.

Ohne `CI_DATENBANK` (lokal, Job `test`) ist er übersprungen.

Gegenprobe: `CI_DATENBANK=postgres python manage.py test
core.tests.test_ci_datenbank` OHNE `DB_ENGINE` — der Test wird rot.
"""
import os
import unittest

from django.db import connection
from django.test import SimpleTestCase


@unittest.skipUnless(os.getenv('CI_DATENBANK'), 'nur im Datenbank-Job der CI')
class CiDatenbankTests(SimpleTestCase):

    def test_die_verlangte_datenbank_ist_die_benutzte(self):
        erwartet = {'postgres': 'postgresql'}.get(os.getenv('CI_DATENBANK'), os.getenv('CI_DATENBANK'))
        self.assertEqual(connection.vendor, erwartet,
                         'Der CI-Job verlangt eine andere Datenbank, als Django benutzt — '
                         'stimmen DB_ENGINE und die DB_-Variablen im Job?')
