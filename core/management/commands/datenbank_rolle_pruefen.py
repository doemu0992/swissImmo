"""Meldet, ob die Datenbankrolle der Anwendung die Trigger-Schutzmassnahmen umgehen könnte.

    python manage.py datenbank_rolle_pruefen            # Hinweise, Code 0
    python manage.py datenbank_rolle_pruefen --streng   # Code 1 bei Befund (für einen Prüflauf)

Auf SQLite gibt es keine Rollen; der Befehl sagt das und endet mit 0.
"""
from django.core.management.base import BaseCommand, CommandError

from core.services import db_rolle


class Command(BaseCommand):
    help = 'Prüft, ob die Anwendungsrolle TRUNCATE/DISABLE TRIGGER auf geschützten Tabellen darf (nur PostgreSQL).'

    def add_arguments(self, parser):
        parser.add_argument('--streng', action='store_true', help='Code 1, wenn die Rolle zu viel darf.')

    def handle(self, *args, streng=False, **opts):
        befunde = db_rolle.pruefen()
        if befunde is None:
            self.stdout.write('SQLite: keine Datenbankrollen, nichts zu prüfen.')
            return
        if not befunde:
            self.stdout.write(self.style.SUCCESS('Die Anwendungsrolle ist eingeschränkt (kein Superuser, nicht Eigentümerin).'))
            return
        for b in befunde:
            self.stdout.write(self.style.WARNING('• ' + b))
        self.stdout.write('Abhilfe: docs/AUTOMATISIERUNG.md, Abschnitt «Datenbankrolle».')
        if streng:
            raise CommandError(f'{len(befunde)} Befund(e).')
