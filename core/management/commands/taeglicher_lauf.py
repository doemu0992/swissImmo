"""Täglicher Sammellauf für PythonAnywhere Scheduled Task (einmal pro Tag):
python manage.py taeglicher_lauf
Generiert Auto-Pendenzen (Fristen), aktualisiert Marktdaten (Referenzzins/LIK)
und verschickt am gewählten Wochentag das Fristen-Wochenmail — so genügt ein
einziger täglicher Scheduled Task."""
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.utils import timezone
from core.services.automation import generate_auto_pendenzen, run_adress_umzuege
from core.models import AktivitaetsLog


class Command(BaseCommand):
    help = "Täglicher Lauf: Auto-Pendenzen (Fristen) + Marktdaten + wöchentl. Fristen-Mail."

    def add_arguments(self, parser):
        parser.add_argument('--horizont', type=int, default=90, help="Vorlauf in Tagen")
        parser.add_argument('--digest-weekday', type=int, default=0,
                            help="Wochentag fürs Fristen-Mail (0=Montag … 6=Sonntag, -1=nie)")

    def handle(self, *args, **opts):
        neu = generate_auto_pendenzen(horizont_tage=opts['horizont'], user=None)
        details = [f"{neu} neue Pendenz(en)"]

        # Fällige Adresswechsel aktivieren (aus dem GET-Lesepfad hierher verlagert)
        try:
            umz = run_adress_umzuege()
            if umz:
                details.append(f"{umz} Adresswechsel aktiviert")
        except Exception as e:
            details.append(f"Adresswechsel übersprungen ({e})")

        # Marktdaten (Referenzzins/LIK) best-effort aktualisieren
        try:
            from core.utils.market_data import update_verwaltung_rates
            update_verwaltung_rates()
            details.append("Marktdaten aktualisiert")
        except Exception as e:
            details.append(f"Marktdaten übersprungen ({e})")

        # Wöchentliches Fristen-Mail am gewählten Wochentag (Standard Montag)
        wd = opts['digest_weekday']
        if wd is not None and wd >= 0 and timezone.localdate().weekday() == wd:
            try:
                call_command('fristen_digest')
                details.append("Fristen-Mail versendet")
            except Exception as e:
                details.append(f"Fristen-Mail übersprungen ({e})")

        msg = "Täglicher Lauf: " + ", ".join(details) + "."
        AktivitaetsLog.objects.create(aktion="Täglicher Lauf (Scheduler)", objekt="", details=msg)
        self.stdout.write(self.style.SUCCESS(msg))
