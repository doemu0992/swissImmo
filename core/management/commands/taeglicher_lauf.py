"""Täglicher Sammellauf für PythonAnywhere Scheduled Task (einmal pro Tag):
python manage.py taeglicher_lauf
Generiert Auto-Pendenzen (Fristen), aktualisiert Marktdaten (Referenzzins/LIK)."""
from django.core.management.base import BaseCommand
from core.services.automation import generate_auto_pendenzen
from core.models import AktivitaetsLog


class Command(BaseCommand):
    help = "Täglicher Lauf: Auto-Pendenzen (Fristen) + Marktdaten-Update."

    def add_arguments(self, parser):
        parser.add_argument('--horizont', type=int, default=90, help="Vorlauf in Tagen")

    def handle(self, *args, **opts):
        neu = generate_auto_pendenzen(horizont_tage=opts['horizont'], user=None)
        details = [f"{neu} neue Pendenz(en)"]

        # Marktdaten (Referenzzins/LIK) best-effort aktualisieren
        try:
            from core.utils.market_data import update_verwaltung_rates
            update_verwaltung_rates()
            details.append("Marktdaten aktualisiert")
        except Exception as e:
            details.append(f"Marktdaten übersprungen ({e})")

        msg = "Täglicher Lauf: " + ", ".join(details) + "."
        AktivitaetsLog.objects.create(aktion="Täglicher Lauf (Scheduler)", objekt="", details=msg)
        self.stdout.write(self.style.SUCCESS(msg))
