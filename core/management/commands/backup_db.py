"""Erstellt ein konsistentes Backup der Datenbank.

SQLite: konsistente Kopie über die eingebaute Backup-API (auch bei laufendem
Betrieb sicher). PostgreSQL: Hinweis auf pg_dump. Alte Backups werden rotiert.

Aufruf:  python manage.py backup_db
Planen:  täglich per PythonAnywhere-Scheduler / Cron.
"""
import datetime
import shutil
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Erstellt ein Backup der Datenbank (SQLite konsistent, sonst Hinweis)."

    def add_arguments(self, parser):
        parser.add_argument('--keep', type=int, default=14,
                            help='Anzahl aufzubewahrender Backups (Standard 14).')

    def handle(self, *args, **opts):
        db = settings.DATABASES['default']
        backup_dir = Path(settings.BASE_DIR) / 'backups'
        backup_dir.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')

        engine = db.get('ENGINE', '')
        if 'sqlite3' in engine:
            src = Path(db['NAME'])
            if not src.exists():
                self.stderr.write(f"DB-Datei nicht gefunden: {src}")
                return
            ziel = backup_dir / f'db-{ts}.sqlite3'
            # Konsistente Online-Kopie via SQLite-Backup-API
            with sqlite3.connect(str(src)) as quelle, sqlite3.connect(str(ziel)) as dest:
                quelle.backup(dest)
            self.stdout.write(self.style.SUCCESS(f"✅ Backup erstellt: {ziel}"))
        elif 'postgresql' in engine:
            self.stdout.write(
                "PostgreSQL erkannt. Bitte pg_dump verwenden, z.B.:\n"
                f"  pg_dump -Fc -f {backup_dir}/db-{ts}.dump "
                f"-h {db.get('HOST','localhost')} -U {db.get('USER','')} {db.get('NAME','')}")
            return
        else:
            self.stderr.write(f"Nicht unterstützte DB-Engine: {engine}")
            return

        # Rotation: nur die neuesten N behalten
        keep = max(1, opts['keep'])
        backups = sorted(backup_dir.glob('db-*.sqlite3'), reverse=True)
        for alt in backups[keep:]:
            try:
                alt.unlink()
                self.stdout.write(f"  entfernt (Rotation): {alt.name}")
            except Exception:
                pass
