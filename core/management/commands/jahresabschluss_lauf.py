"""Jahresabschluss-Läufe: lineare Abschreibungen + Erneuerungsfonds-Einlagen.
Für PythonAnywhere Scheduled Task (jährlich, z.B. 2. Januar):
python manage.py jahresabschluss_lauf --jahr 2026
Ohne --jahr wird das Vorjahr abgeschlossen."""
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.services.automation import run_abschreibungen, run_erneuerungsfonds_einlage
from core.models import AktivitaetsLog


class Command(BaseCommand):
    help = "Bucht AfA (lineare Abschreibungen) + Erneuerungsfonds-Einlagen für ein Jahr."

    def add_arguments(self, parser):
        parser.add_argument('--jahr', type=int, default=timezone.localdate().year - 1)

    def handle(self, *args, **opts):
        jahr = opts['jahr']
        n_afa, s_afa = run_abschreibungen(jahr, user=None)
        n_fonds, s_fonds = run_erneuerungsfonds_einlage(jahr, user=None)
        msg = (f"Jahresabschluss {jahr}: AfA {n_afa} Buchungen (CHF {s_afa}), "
               f"Erneuerungsfonds {n_fonds} Einlagen (CHF {s_fonds}).")
        AktivitaetsLog.objects.create(aktion="Jahresabschluss-Lauf (Scheduler)", objekt=str(jahr), details=msg)
        self.stdout.write(self.style.SUCCESS(msg))
