"""Die Sicherung lässt sich zurückspielen, und der Bestand danach ist derselbe (SICH-28).

WARUM
`test_sicherung.PostgresWegTests` liest den Stand mit `pg_restore --list` gegen: Die Datei ist lesbar und
nennt die Tabellen. Ob die Daten beim Zurückspielen auch ankommen (Reihenfolge der Fremdschlüssel, Sequenzen,
Typen), sagt das nicht. «Eine Sicherung, die niemand je zurückgespielt hat, ist eine Hoffnung»
(`docs/SICHERUNG.md`).

WAS DIESER TEST TUT (nur PostgreSQL, im CI-Job `test-postgres`)
1. Zwei Verwaltungen mit vollem Bestand anlegen und **festschreiben** (`TransactionTestCase`; `pg_dump` sieht
   keine offene Transaktion).
2. `manage.py sicherung` laufen lassen.
3. In eine frisch angelegte Datenbank mit `pg_restore` zurückspielen.
4. Je Tabelle Zeilenzahl **und** Inhaltsprüfsumme beider Datenbanken vergleichen.
5. Die Probe-Datenbank wieder löschen.

Die Prüfsumme (`md5` über den Text jeder Zeile, sortiert) fängt auch eine Zeile, die zwar da ist, aber anders
ankommt (Betrag, Datum, Text). Eine reine Zeilenzahl nicht.

Gegenprobe: Nach dem Zurückspielen in der Probe-Datenbank eine Zeile ändern (siehe `test_der_vergleich_sieht_eine_abweichung`),
und der Vergleich meldet sie.
"""
import os
import shutil
import subprocess
import tempfile
from io import StringIO
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase

from ._isolation import MandantenFixture


def _verbindung(name):
    """psycopg-Verbindung (Autocommit) zu `name` mit den Zugangsdaten der Anwendung."""
    import psycopg
    d = settings.DATABASES['default']
    return psycopg.connect(dbname=name, user=d.get('USER') or None, password=d.get('PASSWORD') or None,
                           host=d.get('HOST') or None, port=d.get('PORT') or None, autocommit=True)


def _tabellen(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        return [z[0] for z in cur.fetchall()]


def abdruck(conn):
    """{Tabelle: (Zeilenzahl, Prüfsumme)} der Datenbank hinter `conn`."""
    ergebnis = {}
    with conn.cursor() as cur:
        for tabelle in _tabellen(conn):
            cur.execute(f'SELECT count(*), md5(coalesce(string_agg(t::text, \'|\' ORDER BY t::text), \'\')) '
                        f'FROM "{tabelle}" t')
            ergebnis[tabelle] = tuple(cur.fetchone())
    return ergebnis


@skipUnless(connection.vendor == 'postgresql', 'Wiederherstellung wird auf PostgreSQL geprüft (Weg der Produktion).')
@skipUnless(shutil.which('pg_dump') and shutil.which('pg_restore'), 'pg_dump/pg_restore sind nicht installiert.')
class WiederherstellungTests(TransactionTestCase):

    def setUp(self):
        self.a = MandantenFixture('A', '8000', 'Zürich')
        self.b = MandantenFixture('B', '3000', 'Bern')
        self.probe = f'restore_probe_{os.getpid()}'
        self.ordner = Path(tempfile.mkdtemp())

    def tearDown(self):
        try:
            with _verbindung('postgres') as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{self.probe}"')
        finally:
            shutil.rmtree(self.ordner, ignore_errors=True)

    def _zurueckspielen(self):
        call_command('sicherung', ziel=str(self.ordner), ohne_medien=True, stdout=StringIO())
        stand = next(self.ordner.glob('*-db.dump'))
        with _verbindung('postgres') as conn:
            conn.execute(f'CREATE DATABASE "{self.probe}"')
        d = settings.DATABASES['default']
        umgebung = dict(os.environ, PGPASSWORD=d.get('PASSWORD') or '')
        befehl = ['pg_restore', '--no-owner', '--exit-on-error', '-d', self.probe]
        if d.get('HOST'):
            befehl += ['-h', d['HOST']]
        if d.get('PORT'):
            befehl += ['-p', str(d['PORT'])]
        if d.get('USER'):
            befehl += ['-U', d['USER']]
        lauf = subprocess.run(befehl + [str(stand)], capture_output=True, text=True, env=umgebung)
        self.assertEqual(lauf.returncode, 0, f'pg_restore ist gescheitert: {lauf.stderr[-800:]}')

    def test_zurueckgespielter_bestand_ist_derselbe(self):
        self._zurueckspielen()
        with _verbindung(connection.settings_dict['NAME']) as original, _verbindung(self.probe) as kopie:
            vorher, nachher = abdruck(original), abdruck(kopie)
        self.assertGreater(len(vorher), 100, 'auffällig wenige Tabellen verglichen')
        self.assertGreater(sum(z for z, _ in vorher.values()), 200, 'der Bestand ist zu klein, um etwas zu beweisen')
        self.assertEqual(sorted(vorher), sorted(nachher), 'Tabellen fehlen oder sind hinzugekommen')
        abweichend = {t: (vorher[t], nachher[t]) for t in vorher if vorher[t] != nachher[t]}
        self.assertEqual(abweichend, {}, 'Nach dem Zurückspielen weichen Tabellen ab (Zeilen, Prüfsumme): '
                                         + str(abweichend)[:600])

    def test_der_vergleich_sieht_eine_abweichung(self):
        """Gegenprobe zur Messung: Ändert man eine Zeile der Kopie, MUSS der Vergleich es melden."""
        from crm.models import Organisation
        tabelle = Organisation._meta.db_table
        self._zurueckspielen()
        with _verbindung(self.probe) as kopie:
            kopie.execute(f'UPDATE "{tabelle}" SET firma = firma || \' (geändert)\' '
                          f'WHERE id = (SELECT min(id) FROM "{tabelle}")')
            nachher = abdruck(kopie)
        with _verbindung(connection.settings_dict['NAME']) as original:
            vorher = abdruck(original)
        abweichend = [t for t in vorher if vorher[t] != nachher.get(t)]
        self.assertEqual(abweichend, [tabelle])
