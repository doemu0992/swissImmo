"""Sammel-Mahnlauf über alle fälligen Debitoren. Für PythonAnywhere Scheduled
Task (z.B. wöchentlich): python manage.py mahnlauf [--zins] [--kein-versand]"""
from django.core.management.base import BaseCommand
from core.services.automation import run_mahnlauf
from core.models import AktivitaetsLog


class Command(BaseCommand):
    help = "Führt einen Sammel-Mahnlauf über alle fälligen offenen Debitoren aus."

    def add_arguments(self, parser):
        parser.add_argument('--zins', action='store_true', help="Verzugszins (5%) berechnen")
        parser.add_argument('--kein-versand', action='store_true', help="Keine E-Mails versenden")

    def handle(self, *args, **opts):
        res = run_mahnlauf(aktive_lg=None, send_email=not opts['kein_versand'],
                           mit_zins=opts['zins'], user=None)
        msg = (f"Mahnlauf: {res['gemahnt']} gemahnt, {res['emails']} E-Mails, "
               f"Gebühren CHF {res['gebuehren']}, Zins CHF {res['zins']}.")
        AktivitaetsLog.objects.create(aktion="Mahnlauf (Scheduler)", objekt="Sammellauf", details=msg)
        self.stdout.write(self.style.SUCCESS(msg))
