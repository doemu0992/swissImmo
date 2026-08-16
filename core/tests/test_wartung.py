"""Wartungsseite bei Schemaabweichung — siehe docs/WARTUNGSSEITE.md.

Der Auftrag nennt zwei dieser Tests ausdrücklich als Abnahmekriterium und
begründet das auch: Eine Absicherung, die `migrate` blockiert, wäre schlimmer
als der Fehler, den sie behebt — eine Anwendung, die sich nicht mehr migrieren
lässt, kommt ohne Datenbankzugriff von Hand nicht mehr heraus.

DIE GEGENPROBE, protokolliert
-----------------------------
Mit ausgehängter Middleware (`core.wartung.WartungsMiddleware` aus
`settings.MIDDLEWARE` entfernt):

    WartungsseiteTests.test_wartungsmodus_liefert_503                  FEHLER
    WartungsseiteTests.test_seite_verraet_nichts_ueber_das_innenleben  FEHLER
    WartungsseiteTests.test_healthz_bleibt_erreichbar                  ok
    WartungsseiteTests.test_ohne_fehlende_migrationen_laeuft_alles_normal  ok
    StartcheckTests.*                                                  ok

Die grün gebliebenen sind es zu Recht: Sie behaupten, dass etwas NICHT
blockiert wird — ohne Middleware blockiert erst recht nichts.

Der zweite Eintrag der Liste stimmte beim ersten Anlauf NICHT. Der Test prüfte
nur, dass bestimmte Wörter fehlen, und blieb ohne Middleware grün: Auf einer
ganz normalen Seite fehlen sie auch. Er belegte damit nichts. Erst die
vorangestellte Statusprüfung macht ihn zu einer Aussage über die
Wartungsseite. Die Gegenprobe hat das aufgedeckt, nicht das Nachdenken darüber
— was genau ihr Zweck ist.

ZWEITE GEGENPROBE — die Erkennungsart
-------------------------------------
Mit der ersten Fassung von `pruefe_migrationsstand()` (`migration_plan` statt
Mengenvergleich):

    StartcheckTests.test_luecke_mitten_in_der_kette_wird_erkannt       FEHLER
        AssertionError: Lists differ: [] != ['crm.0033_mitgliedschaft']
    alle übrigen                                                       ok

Genau so war der Fehler gemeldet: Der Plan ist leer, obwohl eine Migration
fehlt. Dass alle anderen Tests grün blieben, ist der Punkt — der Defekt lag
ausserhalb dessen, was sie prüften.
"""
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, Client, override_settings

from core import wartung


class StartcheckTests(TestCase):
    """Was `pruefe_migrationsstand()` feststellt — und was es sein lässt."""

    def tearDown(self):
        wartung.FEHLENDE_MIGRATIONEN = None

    def test_bei_vollstaendigem_schema_ist_nichts_offen(self):
        """Die Testdatenbank ist frisch migriert — es darf nichts fehlen."""
        with patch.object(wartung.sys, 'argv', ['manage.py', 'runserver']):
            self.assertEqual(wartung.pruefe_migrationsstand(), [])

    def test_migrate_wird_nicht_geprueft(self):
        """DER wichtigste Test dieser Datei.

        `ready()` läuft auch bei `manage.py migrate`. Würde die Prüfung dort
        greifen und die Anwendung in den Wartungsmodus schicken, liesse sich
        genau der Zustand nicht mehr beheben, für den sie gebaut ist.
        """
        for befehl in ('migrate', 'collectstatic', 'makemigrations', 'benutzer_uebernahme'):
            with self.subTest(befehl=befehl):
                with patch.object(wartung.sys, 'argv', ['manage.py', befehl]):
                    self.assertIsNone(
                        wartung.pruefe_migrationsstand(),
                        f'`{befehl}` darf nicht geprüft werden — sonst ist die '
                        f'Anwendung nicht mehr zu migrieren.')

    def test_luecke_mitten_in_der_kette_wird_erkannt(self):
        """Der Fall, an dem die erste Fassung vorbeisah — und der einzige, der
        wirklich vorgekommen ist.

        `crm.0033` aus `django_migrations` entfernen, `crm.0034` stehen lassen.
        Die alte Prüfung nahm `executor.migration_plan(graph.leaf_nodes())`, und
        der ist in dieser Lage **leer**: Django beantwortet damit die Frage „was
        müsste ich jetzt ausführen?" unter der Annahme, die Buchführung sei in
        sich stimmig. Ist ein späterer Schritt vermerkt, gelten seine Vorgänger
        als erledigt.

        Das ist keine Spitzfindigkeit, sondern genau die Form des Ausfalls vom
        15.08.2026: `migrate` meldete „No migrations to apply", während
        `crm_mitgliedschaft` nachweislich fehlte. Eine Wartungsseite, die
        ausgerechnet diesen Fall nicht erkennt, wäre für ihren eigenen Anlass
        blind.
        """
        from django.db.migrations.recorder import MigrationRecorder

        recorder = MigrationRecorder(connection)
        vorher = recorder.migration_qs.filter(app='crm', name='0033_mitgliedschaft')
        self.assertTrue(vorher.exists(), 'Voraussetzung: crm.0033 ist angewendet.')
        self.assertTrue(
            recorder.migration_qs.filter(app='crm', name='0034_bestand_der_organisation_zuordnen').exists(),
            'Voraussetzung: der NACHFOLGER crm.0034 ist ebenfalls angewendet — '
            'nur so entsteht die Lücke, um die es geht.')

        vorher.delete()
        try:
            with patch.object(wartung.sys, 'argv', ['manage.py', 'runserver']):
                offen = wartung.pruefe_migrationsstand()
            self.assertEqual(
                offen, ['crm.0033_mitgliedschaft'],
                'Die Lücke mitten in der Kette wurde nicht erkannt. Genau dafür '
                'steht hier ein Mengenvergleich und kein `migration_plan`.')
        finally:
            recorder.record_applied('crm', '0033_mitgliedschaft')

    def test_fehler_bei_der_pruefung_blockiert_nicht(self):
        """Datenbank kurz weg ist kein Grund für eine Wartungsseite.

        Die Prüfung ist ein Wächter, kein Türsteher: Sie meldet, was sie sicher
        weiss, und schweigt, wenn sie nichts weiss. `None` heisst „nicht
        geprüft" — und `None` löst keinen Wartungsmodus aus.
        """
        with patch.object(wartung.sys, 'argv', ['manage.py', 'runserver']), \
             patch('django.db.migrations.loader.MigrationLoader',
                   side_effect=RuntimeError('Datenbank nicht erreichbar')):
            self.assertIsNone(wartung.pruefe_migrationsstand())
        self.assertIsNone(wartung.FEHLENDE_MIGRATIONEN)


@override_settings(DEBUG=False)
class WartungsseiteTests(TestCase):
    """Was der Nutzer sieht, wenn das Schema nicht zum Code passt."""

    def setUp(self):
        # Zustand „Migration fehlt" herstellen, ohne die Testdatenbank
        # tatsächlich zurückzumigrieren — die Middleware liest nur dieses
        # Attribut, und genau das ist der Punkt der Bauform.
        wartung.FEHLENDE_MIGRATIONEN = ['crm.0033_mitgliedschaft']

    def tearDown(self):
        wartung.FEHLENDE_MIGRATIONEN = None

    def test_wartungsmodus_liefert_503(self):
        antwort = Client().get('/')
        self.assertEqual(antwort.status_code, 503)
        self.assertIn('Wartungsarbeiten', antwort.content.decode())
        self.assertEqual(antwort['Retry-After'], '120')
        self.assertEqual(antwort['Cache-Control'], 'no-store')

    def test_seite_verraet_nichts_ueber_das_innenleben(self):
        """Sie ist öffentlich. Was fehlt, gehört ins Log, nicht in die Antwort.

        Die erste Fassung prüfte nur die Abwesenheit der Verräter-Wörter und
        blieb in der Gegenprobe grün: Ohne Middleware liefert `/` eine ganz
        normale Seite, in der diese Wörter ebenfalls nicht vorkommen. Der Test
        belegte also nichts. Deshalb steht die Statusprüfung voran — erst damit
        ist gesagt, WELCHE Antwort untersucht wird.
        """
        antwort = Client().get('/')
        self.assertEqual(antwort.status_code, 503,
                         'Ohne Wartungsseite prüft der Rest dieses Tests die falsche Antwort.')
        html = antwort.content.decode()
        for verraeter in ('crm.0033', 'Migration', 'Traceback', 'OperationalError',
                          'sqlite', '/home/', 'django', 'manage.py'):
            self.assertNotIn(
                verraeter, html,
                f'«{verraeter}» steht in einer öffentlich erreichbaren Antwort.')

    def test_healthz_bleibt_erreichbar(self):
        """Von aussen muss sichtbar bleiben, WELCHER Stand hängt.

        Sonst ist man zur Fehlersuche auf die Konsole des Hosters angewiesen —
        und die war am 15.08.2026 der einzige Weg, überhaupt etwas zu erfahren.
        """
        self.assertNotEqual(Client().get('/version/').status_code, 503)

    def test_ohne_fehlende_migrationen_laeuft_alles_normal(self):
        wartung.FEHLENDE_MIGRATIONEN = []
        self.assertNotEqual(Client().get('/').status_code, 503)
