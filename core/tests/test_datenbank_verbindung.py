"""Die PostgreSQL-Verbindungseinstellungen — geprüft, ohne PostgreSQL.

WARUM ES DIESEN TESTSATZ GIBT

Am 18.08.2026, wenige Minuten nach dem Umzug, warf die Website auf `/neu/`:

    OperationalError: consuming input failed: SSL SYSCALL error: EOF detected

Nicht in einem View, sondern schon beim Laden der Sitzung — also bevor
irgendein Anwendungscode lief. Ursache war eine wiederverwendete, längst vom
Server geschlossene Verbindung: `CONN_MAX_AGE = 600` hält sie über den Request
hinaus offen, `CONN_HEALTH_CHECKS` fehlte, und damit prüfte Django vor der
Wiederverwendung nichts.

DAS PRÜFPROBLEM

Die Suite läuft auf SQLite; der PostgreSQL-Zweig in `settings.py` wird beim
Import gar nicht betreten. Ein gewöhnlicher Test sieht diese Einstellungen also
NIE — genau deshalb konnte die Lücke bis in den Betrieb durchrutschen.

Die Tests hier starten deshalb einen eigenen Python-Prozess mit
`DB_ENGINE=postgres` in der Umgebung und lesen die fertige Konfiguration aus.
Es wird keine Verbindung aufgebaut: `settings.DATABASES` ist ein Wörterbuch,
Django verbindet sich erst bei der ersten Abfrage.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Liest die zusammengebaute Konfiguration und gibt sie als JSON aus. Das
# Passwort bleibt draussen — es hat in keiner Testausgabe etwas zu suchen.
AUSLESEN = (
    'import os, django, json;'
    "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'swiss_immo.settings');"
    'django.setup();'
    'from django.conf import settings as s;'
    "d = dict(s.DATABASES['default']);"
    "d.pop('PASSWORD', None);"
    "print(json.dumps({k: v for k, v in d.items() if isinstance(v, (str, int, bool, type(None)))}))"
)


def _konfiguration(**umgebung):
    """Startet einen frischen Prozess und gibt dessen DATABASES['default']."""
    umwelt = dict(os.environ)
    for schluessel in ('DB_ENGINE', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT'):
        umwelt.pop(schluessel, None)
    umwelt.update(umgebung)
    lauf = subprocess.run([sys.executable, '-c', AUSLESEN],
                          cwd=str(Path(settings.BASE_DIR)), env=umwelt,
                          capture_output=True, text=True, timeout=120)
    if lauf.returncode != 0:
        raise AssertionError(f'Settings liessen sich nicht laden:\n{lauf.stderr}')
    return json.loads(lauf.stdout.strip().splitlines()[-1])


class PostgresVerbindungTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pg = _konfiguration(DB_ENGINE='postgres', DB_NAME='x', DB_USER='y',
                                DB_HOST='z', DB_PORT='15420')

    def test_der_postgres_zweig_wird_ueberhaupt_betreten(self):
        # Gegenprobe zum Testaufbau selbst: Ohne sie wäre nicht belegt, dass
        # der Unterprozess wirklich die PostgreSQL-Einstellungen liest und
        # nicht still auf SQLite zurückfällt — dann wären alle weiteren
        # Zusagen wertlos.
        self.assertEqual(self.pg['ENGINE'], 'django.db.backends.postgresql')

    def test_wiederverwendete_verbindungen_werden_geprueft(self):
        # Der eigentliche Fund. Fällt diese Zusage, kehrt der SSL-EOF-Fehler
        # zurück — und zwar nicht sofort, sondern nach der ersten längeren
        # Pause, was ihn besonders schwer zuzuordnen macht.
        self.assertTrue(
            self.pg.get('CONN_HEALTH_CHECKS'),
            'CONN_HEALTH_CHECKS fehlt: Django nimmt tote Verbindungen aus dem '
            'Bestand und die Sitzungsabfrage bricht mit «SSL SYSCALL error: '
            'EOF detected» ab.')

    def test_die_pruefung_ist_nur_noetig_weil_verbindungen_offen_bleiben(self):
        # Hält die Zusammengehörigkeit fest: Wer CONN_MAX_AGE auf 0 setzt,
        # braucht die Prüfung nicht mehr — wer es dabei belässt, sehr wohl.
        if self.pg.get('CONN_MAX_AGE'):
            self.assertTrue(self.pg.get('CONN_HEALTH_CHECKS'))

    def test_ohne_db_engine_bleibt_es_bei_sqlite(self):
        # Damit der Umbau die Entwicklungsumgebung nicht mitnimmt.
        #
        # Auf einer Maschine mit `.env` (Produktion) steht dort seit dem Umzug
        # `DB_ENGINE=postgres`; `load_dotenv` füllt es nach, sobald es nicht
        # schon in der Umgebung steht. Dann prüft dieser Test nichts mehr —
        # das gehört gesagt statt stillschweigend hingenommen.
        env = Path(settings.BASE_DIR) / '.env'
        if env.exists() and 'DB_ENGINE' in env.read_text(encoding='utf-8'):
            self.skipTest('.env setzt DB_ENGINE — hier nicht aussagekräftig.')
        self.assertEqual(_konfiguration()['ENGINE'], 'django.db.backends.sqlite3')
