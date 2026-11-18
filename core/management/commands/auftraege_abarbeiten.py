"""Arbeitet wartende Aufträge ab (`core.Auftrag`, siehe `core/services/auftraege.py`).

Aufruf:
    python manage.py auftraege_abarbeiten --einmal      # ein Durchlauf (Scheduled Task, so oft der Hoster erlaubt)
    python manage.py auftraege_abarbeiten --dauerlauf   # Schleife alle 10 s (Always-on-Task)

Nur EINE der beiden Formen einrichten. Zwei Läufer nähmen nie denselben Auftrag (PostgreSQL: `skip_locked`).
"""
import logging
import signal
import threading

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core.services import auftraege

logger = logging.getLogger(__name__)

PAUSE_SEKUNDEN = 10


class Command(BaseCommand):
    help = 'Arbeitet wartende Hintergrund-Aufträge ab.'

    def add_arguments(self, parser):
        gruppe = parser.add_mutually_exclusive_group()
        gruppe.add_argument('--einmal', action='store_true', help='Ein Durchlauf. Vorgabe.')
        gruppe.add_argument('--dauerlauf', action='store_true',
                            help=f'Schleife alle {PAUSE_SEKUNDEN} s; beendet sich sauber bei SIGTERM/SIGINT.')

    def handle(self, *args, **options):
        if not options['dauerlauf']:
            self.durchlauf()
            return
        self._stopp = threading.Event()
        for nummer in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(nummer, lambda _n, _r: self._stopp.set())
            except ValueError:                                # nicht im Hauptthread (Tests)
                logger.debug('Signal %s nicht verdrahtet', nummer)
        self.stdout.write(f'Aufträge werden abgearbeitet (Schleife, alle {PAUSE_SEKUNDEN} s) …')
        while not self._stopp.is_set():
            try:
                self.durchlauf()
            except Exception as fehler:                       # noqa: BLE001 — die Schleife darf nicht sterben
                logger.exception('Aufträge: Durchlauf abgebrochen')
                self.stdout.write(self.style.ERROR(f'Fehler im Lauf: {fehler}'))
            close_old_connections()
            if self._stopp.wait(PAUSE_SEKUNDEN):
                break
        self.stdout.write('Auftragslauf beendet.')

    def durchlauf(self):
        auftraege.puls_melden()                               # «der Läufer lebt» für `auftraege.laeufer_aktiv`
        n = auftraege.abarbeiten()
        if n:
            self.stdout.write(self.style.SUCCESS(f'{n} Auftrag/Aufträge bearbeitet.'))
        return n
