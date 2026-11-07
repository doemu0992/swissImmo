"""Prüft und vervollständigt den Datenbank-Schutz der Buchhaltung.

    python manage.py db_schutz

Zeigt, ob der Trigger gegen Änderung/Löschung von Buchungen aktiv ist (PostgreSQL)
und ob die Eindeutigkeiten für Storno und Bankreferenz sowie die Prüfregeln (Betrag > 0,
Soll ≠ Haben) bestehen. Fehlende Indizes und Regeln werden angelegt, sobald der Bestand
sie zulässt; sonst werden die betroffenen Schlüssel bzw. Buchungen ausgegeben. Siehe `finance/db_schutz.py`.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core import log_schutz
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
            if log_schutz.trigger_vorhanden():
                self.stdout.write('Trigger gegen Änderung/Löschung im Audit-Log: aktiv')
            else:
                raise CommandError('Der Trigger des Audit-Logs FEHLT (Migration core.0020 ausführen).')
        else:
            self.stdout.write(f'{connection.vendor}: kein Trigger, es gilt der Manager-Schutz.')
        with connection.schema_editor() as editor:
            uebersprungen = db_schutz.eindeutigkeiten_nachziehen(editor)
        for name, dubletten in uebersprungen:
            self.stderr.write(f'{name}: nicht angelegt, {len(dubletten)} doppelte Schlüssel, z. B. {dubletten[:5]}')
        if uebersprungen:
            raise CommandError('Bestand zuerst bereinigen (Dubletten stornieren), dann erneut ausführen.')
        self.stdout.write('Eindeutigkeiten für Storno und Bankreferenz: vorhanden')
        with connection.schema_editor() as editor:
            verletzt = db_schutz.pruefregeln_nachziehen(editor)
        for name, buchungen in verletzt:
            self.stderr.write(f'{name}: nicht angelegt, {len(buchungen)} Buchung(en) verstossen dagegen, '
                              f'z. B. {buchungen[:5]}')
        if verletzt:
            raise CommandError('Die genannten Buchungen klären (Gegenbuchung), dann erneut ausführen.')
        if connection.vendor == 'postgresql':
            self.stdout.write('Prüfregeln (Betrag > 0, Soll ≠ Haben): vorhanden')
        else:
            self.stdout.write(f'{connection.vendor}: keine CHECK-Constraints, es gilt die Prüfung im Modell.')
