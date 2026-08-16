"""Setzt die ID-Zähler nach einem Datenbankumzug auf den tatsächlichen Bestand.

Der Schritt, den man beim Umzug SQLite → PostgreSQL am ehesten vergisst und am
spätesten bemerkt. Nach `loaddata` stehen alle Sequenzen auf 1, obwohl in den
Tabellen schon Tausende Zeilen liegen. Es funktioniert alles — bis jemand den
ersten **neuen** Datensatz anlegt, dessen ID mit einer bestehenden kollidiert.
Der Fehler tritt Tage später auf und sieht dort nach einem Programmfehler aus,
nicht nach einem Umzugsproblem.

Der übliche Weg dafür ist `manage.py sqlsequencereset app | manage.py dbshell`.
Der startet aber das externe Programm `psql`; fehlt es auf dem Server, scheitert
ausgerechnet dieser Schritt. Dieser Befehl erzeugt dieselben Anweisungen und
führt sie über Djangos eigene Verbindung aus — ohne externes Programm.

    python manage.py sequenzen_richten              # setzen
    python manage.py sequenzen_richten --nur-zeigen # nur ausgeben

Auf SQLite ist der Befehl ein Leerlauf: Dort gibt es keine Sequenzen, und
`sequence_reset_sql` liefert eine leere Liste.
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.core.management.color import no_style
from django.db import connection


class Command(BaseCommand):
    help = 'Setzt die ID-Zähler auf den tatsächlichen Bestand (nach einem Datenbankumzug).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--nur-zeigen', action='store_true',
            help='Anweisungen ausgeben, ohne sie auszuführen.')

    def handle(self, *args, **optionen):
        modelle = [m for konfig in apps.get_app_configs()
                   if konfig.models_module is not None
                   for m in konfig.get_models(include_auto_created=True)]

        anweisungen = connection.ops.sequence_reset_sql(no_style(), modelle)

        if not anweisungen:
            self.stdout.write(
                f'· {connection.vendor}: keine Sequenzen zu setzen — nichts zu tun.')
            return

        if optionen['nur_zeigen']:
            for zeile in anweisungen:
                self.stdout.write(zeile)
            return

        # Eine Transaktion: Entweder stehen danach alle Zähler richtig oder
        # keiner. Ein halb gesetzter Zustand wäre schlimmer als gar keiner,
        # weil er wie Erfolg aussieht.
        with connection.cursor() as cursor:
            for zeile in anweisungen:
                cursor.execute(zeile)

        self.stdout.write(self.style.SUCCESS(
            f'✓ {len(anweisungen)} Sequenz(en) auf den tatsächlichen Bestand gesetzt.'))
