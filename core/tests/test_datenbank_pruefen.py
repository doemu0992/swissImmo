"""Der Wächter gegen die falsche Datenbank.

Er steht gegen einen Fehler, den niemand bemerkt: Auf PythonAnywhere hat jeder
Prozess eigene Umgebungsvariablen. Läuft die Web-App auf PostgreSQL und der
Deploy-Task auf SQLite, funktionieren beide Seiten für sich — der Deploy meldet
Erfolg, die Website sieht die Migration nie.

Die Tests prüfen deshalb nicht nur, dass die Prüfung bei Gleichstand schweigt,
sondern vor allem, dass sie bei Abweichung tatsächlich abbricht. Ein Wächter,
der nie anschlägt, ist von einem defekten nicht zu unterscheiden.
"""
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from core.management.commands.datenbank_pruefen import kurzname

POSTGRES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'swissimmo',
    'HOST': 'swissimmo-5420.postgres.pythonanywhere-services.com',
}}
SQLITE = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': '/home/swissimmo/swiss-manager/db.sqlite3',
    'HOST': '',
}}


def _datei(inhalt):
    """Schreibt eine Erwartungsdatei und gibt ihren Pfad zurück."""
    ordner = tempfile.mkdtemp()
    pfad = Path(ordner) / '.datenbank-erwartet'
    pfad.write_text(inhalt, encoding='utf-8')
    return str(pfad)


def _lauf(pfad):
    """Führt die Prüfung aus, gibt (erfolg, ausgabe) zurück."""
    raus, rerr = StringIO(), StringIO()
    try:
        call_command('datenbank_pruefen', datei=pfad, stdout=raus, stderr=rerr)
    except SystemExit:
        return False, raus.getvalue() + rerr.getvalue()
    return True, raus.getvalue() + rerr.getvalue()


class KurznameTests(SimpleTestCase):
    def test_bekannte_backends(self):
        self.assertEqual(kurzname('django.db.backends.postgresql'), 'postgres')
        self.assertEqual(kurzname('django.db.backends.postgresql_psycopg2'), 'postgres')
        self.assertEqual(kurzname('django.db.backends.sqlite3'), 'sqlite')

    def test_unbekanntes_backend_faellt_auf_letztes_segment_zurueck(self):
        # Ein fremdes Backend soll keinen Absturz erzeugen, sondern einen
        # lesbaren Namen, mit dem die Abweichungsmeldung noch etwas anfangen kann.
        self.assertEqual(kurzname('meine.eigene.oracle'), 'oracle')


class AbweichungTests(SimpleTestCase):
    """Der eigentliche Zweck: Anschlagen, wenn die Datenbank nicht stimmt."""

    @override_settings(DATABASES=SQLITE)
    def test_erwartet_postgres_tatsaechlich_sqlite_bricht_ab(self):
        # GENAU der Umzugsfall: Repo steht auf postgres, dieser Prozess sieht
        # die Variablen nicht und laeuft weiter auf der SQLite-Datei.
        erfolg, ausgabe = _lauf(_datei('engine = postgres\n'))
        self.assertFalse(erfolg, 'Die Prüfung hat die falsche Datenbank durchgelassen.')
        self.assertIn('erwartet «postgres»', ausgabe)
        self.assertIn('tatsächlich «sqlite»', ausgabe)

    @override_settings(DATABASES=POSTGRES)
    def test_gegenprobe_stimmt_die_engine_schweigt_die_pruefung(self):
        # Ohne diese Gegenprobe waere nicht belegt, dass der Test oben die
        # Abweichung misst und nicht einfach immer fehlschlaegt.
        erfolg, ausgabe = _lauf(_datei('engine = postgres\n'))
        self.assertTrue(erfolg, ausgabe)
        self.assertIn('wie erwartet', ausgabe)

    @override_settings(DATABASES=POSTGRES)
    def test_gleiche_engine_andere_datenbank_bricht_ab(self):
        # Der subtilere Fall: beide auf PostgreSQL, aber zwei verschiedene
        # Datenbanken. Ohne `name` faellt das nicht auf.
        erfolg, ausgabe = _lauf(_datei('engine = postgres\nname = swissimmo_test\n'))
        self.assertFalse(erfolg, 'Zwei verschiedene PostgreSQL-Datenbanken blieben unbemerkt.')
        self.assertIn('name:', ausgabe)

    @override_settings(DATABASES=POSTGRES)
    def test_optionale_felder_werden_nur_geprueft_wenn_genannt(self):
        # `name`/`host` fehlen in der Datei — der abweichende Host darf dann
        # nicht anschlagen, sonst waere die Angabe faktisch Pflicht.
        erfolg, _ = _lauf(_datei('engine = postgres\n'))
        self.assertTrue(erfolg)

    @override_settings(DATABASES=SQLITE)
    def test_synonyme_und_kommentare(self):
        erfolg, _ = _lauf(_datei('# Kommentarzeile\n\nengine = sqlite3   # nachgestellt\n'))
        self.assertTrue(erfolg)


class DateiTests(SimpleTestCase):
    @override_settings(DATABASES=SQLITE)
    def test_fehlende_datei_haelt_den_deploy_nicht_an(self):
        # Eine nicht hinterlegte Erwartung ist kein Fehler — sonst braeche der
        # erste Deploy nach dem Einbau auf jeder Bestandsinstallation ab.
        raus = StringIO()
        call_command('datenbank_pruefen', datei='/gibt/es/nicht/.datenbank-erwartet', stdout=raus)
        self.assertIn('nicht vorhanden', raus.getvalue())

    def test_datei_ohne_engine_ist_ein_fehler(self):
        # Eine Datei, die nichts prueft, ist schlimmer als keine: Sie sieht
        # aus wie ein Schutz.
        with self.assertRaises(CommandError):
            call_command('datenbank_pruefen', datei=_datei('name = swissimmo\n'))

    def test_unbekannter_motor_ist_ein_fehler(self):
        with self.assertRaises(CommandError):
            call_command('datenbank_pruefen', datei=_datei('engine = postgress\n'))

    def test_kaputte_zeile_ist_ein_fehler(self):
        with self.assertRaises(CommandError):
            call_command('datenbank_pruefen', datei=_datei('engine postgres\n'))


class RepoDateiTests(SimpleTestCase):
    """Die Datei im Repo muss zu der Datenbank passen, auf der wir laufen."""

    def test_repo_erwartung_passt_zur_laufenden_datenbank(self):
        # Schlaegt dieser Test fehl, ist entweder die Datei falsch gepflegt
        # oder die Testumgebung laeuft auf einer anderen Datenbank als
        # angenommen. Beides gehoert gesehen.
        from django.conf import settings
        pfad = Path(settings.BASE_DIR) / '.datenbank-erwartet'
        self.assertTrue(pfad.exists(), '.datenbank-erwartet fehlt — der Deploy prüft dann nichts.')
        erfolg, ausgabe = _lauf(str(pfad))
        self.assertTrue(erfolg, ausgabe)
