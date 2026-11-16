"""Legt die RLS-Regeln der Finanztabellen an oder nimmt sie zurück (nur PostgreSQL). Siehe `core/rls.py`, `ARCHITECTURE.md`.

    python manage.py rls_einrichten              # anlegen (wiederholbar)
    python manage.py rls_einrichten --trocken    # nur zeigen, was geschähe
    python manage.py rls_einrichten --entfernen  # zurücknehmen
    python manage.py rls_einrichten --status     # Zustand je Tabelle

Muss als EIGENTÜMERIN der Tabellen laufen (dieselbe Rolle wie `migrate`). Wirksam werden die Regeln erst mit
`RLS_MODUS=scharf` in der `.env`: Ohne die Sitzungsvariable lassen sie alles durch.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core import rls


class Command(BaseCommand):
    help = 'Row-Level-Security der Finanztabellen anlegen, entfernen oder prüfen (PostgreSQL).'

    def add_arguments(self, parser):
        gruppe = parser.add_mutually_exclusive_group()
        gruppe.add_argument('--entfernen', action='store_true', help='Regeln und RLS wieder entfernen.')
        gruppe.add_argument('--status', action='store_true', help='Nur den Zustand zeigen.')
        gruppe.add_argument('--trocken', action='store_true', help='Die Befehle zeigen, nichts ausführen.')

    def handle(self, *args, **opts):
        if connection.vendor != 'postgresql':
            raise CommandError('Row-Level-Security gibt es nur auf PostgreSQL.')
        if opts['trocken']:
            for tabelle in rls.tabellen():
                for befehl in rls.sql_einrichten(tabelle):
                    self.stdout.write(befehl + ';')
            return
        if opts['status']:
            return self._status()
        if opts['entfernen']:
            liste = rls.entfernen()
            self.stdout.write(self.style.SUCCESS(f'RLS entfernt von {len(liste)} Tabellen.'))
        else:
            liste = rls.einrichten()
            self.stdout.write(self.style.SUCCESS(f'RLS eingerichtet auf {len(liste)} Tabellen.'))
        self._status()

    def _status(self):
        s = rls.status()
        self.stdout.write(f"Modus (RLS_MODUS): {s['modus']} · Rolle der Verbindung: {s['rolle']}")
        if s['umgeht']:
            self.stdout.write(self.style.WARNING(
                'Diese Rolle ist Superuser oder hat BYPASSRLS: Für sie gilt keine Regel. Die Anwendung braucht eine '
                'Rolle ohne diese Rechte (ARCHITECTURE.md).'))
        fertig = sum(1 for t in s['tabellen'] if t['ein'] and t['erzwungen'] and t['regeln'] >= 4)
        self.stdout.write(f"{fertig} von {len(s['tabellen'])} Tabellen geschützt.")
        for t in s['tabellen']:
            if not (t['ein'] and t['erzwungen'] and t['regeln'] >= 4):
                self.stdout.write(f"  offen: {t['tabelle']} (ein={t['ein']}, erzwungen={t['erzwungen']}, "
                                  f"Regeln={t['regeln']})")
