"""Prüft und vervollständigt den Datenbank-Schutz der Buchhaltung.

    python manage.py db_schutz

Zeigt, ob der Trigger gegen Änderung/Löschung von Buchungen aktiv ist (PostgreSQL)
und ob die Eindeutigkeiten für Storno und Bankreferenz bestehen. Fehlende Indizes
werden angelegt, sobald der Bestand keine Dubletten mehr enthält; sonst werden die
doppelten Schlüssel ausgegeben. Siehe `finance/db_schutz.py`.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from finance import db_schutz


class Command(BaseCommand):
    help = 'Prüft den DB-Schutz der Buchungen und legt fehlende Eindeutigkeiten an, wenn der Bestand es zulässt.'

    def handle(self, *args, **optionen):
        if connection.vendor == 'postgresql':
            if db_schutz.trigger_vorhanden():
                self.stdout.write('Trigger gegen Änderung/Löschung von Buchungen: aktiv')
            else:
                raise CommandError('Der Trigger gegen Änderung/Löschung von Buchungen FEHLT '
                                   '(Migration finance.0054 ausführen).')
        else:
            self.stdout.write(f'{connection.vendor}: kein Trigger, es gilt der Manager-Schutz.')
        with connection.schema_editor() as editor:
            uebersprungen = db_schutz.eindeutigkeiten_nachziehen(editor)
        for name, dubletten in uebersprungen:
            self.stderr.write(f'{name}: nicht angelegt, {len(dubletten)} doppelte Schlüssel, z. B. {dubletten[:5]}')
        if uebersprungen:
            raise CommandError('Bestand zuerst bereinigen (Dubletten stornieren), dann erneut ausführen.')
        self.stdout.write('Eindeutigkeiten für Storno und Bankreferenz: vorhanden')
