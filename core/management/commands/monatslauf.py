"""Monatlicher Mietenlauf (Sollstellung). Für PythonAnywhere Scheduled Task
(z.B. am 1. jeden Monats): python manage.py monatslauf
Ohne Argumente wird der aktuelle Monat gestellt; --jahr/--monat überschreiben."""
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.services.automation import run_sollstellung
from core.models import AktivitaetsLog


class Command(BaseCommand):
    help = "Führt die monatliche Sollstellung (Mietenlauf) aus — idempotent."

    def add_arguments(self, parser):
        heute = timezone.localdate()
        parser.add_argument('--jahr', type=int, default=heute.year)
        parser.add_argument('--monat', type=int, default=heute.month)

    def handle(self, *args, **opts):
        jahr, monat = opts['jahr'], opts['monat']
        try:
            n = run_sollstellung(jahr, monat, user=None)
        except RuntimeError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            return
        msg = f"Sollstellung {monat:02d}/{jahr}: {n} Rechnung(en) erstellt."
        AktivitaetsLog.objects.create(aktion="Sollstellung (Scheduler)", objekt=f"{monat:02d}/{jahr}", details=msg)
        self.stdout.write(self.style.SUCCESS(msg))
