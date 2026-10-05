"""Prüft STWEG-Gemeinschaften: Integrität und Abstimmung des Hauptbuchs. Aufruf:
    python manage.py stweg_audit [--organisation ID] [--liegenschaft ID]
Endet mit Exit-Code 1, wenn ein FEHLER gefunden wurde (für Läufe und Überwachung)."""
from django.core.management.base import BaseCommand, CommandError

from core.tenancy import organisation_kontext
from crm.models import Organisation
from portfolio.models import Liegenschaft
from stweg import integritaet


class Command(BaseCommand):
    help = 'Integritätsprüfung und Hauptbuch-Abstimmung der STWEG-Gemeinschaften.'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int)
        parser.add_argument('--liegenschaft', type=int)

    def handle(self, *args, **opts):
        orgs = Organisation.objects.all()
        if opts['organisation']:
            orgs = orgs.filter(pk=opts['organisation'])
        fehler = 0
        for org in orgs:
            with organisation_kontext(org):
                lgs = Liegenschaft.objects.filter(typ=Liegenschaft.TYP_STWEG)
                if opts['liegenschaft']:
                    lgs = lgs.filter(pk=opts['liegenschaft'])
                for lg in lgs:
                    befunde = integritaet.pruefe(lg)
                    self.stdout.write(f'{org.firma} · {lg}: {"in Ordnung" if not befunde else f"{len(befunde)} Befund(e)"}')
                    for stufe, text in befunde:
                        self.stdout.write(f'  [{stufe.upper()}] {text}')
                        fehler += stufe == integritaet.FEHLER
        if opts['liegenschaft'] and not Liegenschaft.alle_organisationen.filter(pk=opts['liegenschaft']).exists():
            raise CommandError('Liegenschaft nicht gefunden.')
        if fehler:
            raise SystemExit(1)
