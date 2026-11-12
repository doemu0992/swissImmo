"""Legt einen Schlüssel für die lesende Finanz-API an (`/api/v1/`). Der Klartext erscheint nur hier, einmal.

    python manage.py api_token_erstellen --organisation 1 --name "Treuhand Muster AG"
"""
from django.core.management.base import BaseCommand, CommandError

from core import api_token
from core.auth import log_aktion
from crm.models import Organisation


class Command(BaseCommand):
    help = 'Neuer API-Schlüssel (nur Lesen) für eine Verwaltung; der Klartext wird einmalig ausgegeben.'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int, required=True)
        parser.add_argument('--name', required=True)

    def handle(self, *args, organisation, name, **opts):
        org = Organisation.objects.filter(pk=organisation).first()
        if org is None:
            raise CommandError(f'Organisation {organisation} gibt es nicht.')
        if not name.strip():
            raise CommandError('--name darf nicht leer sein.')
        token, roh = api_token.erzeugen(org, name)
        from core.tenancy import organisation_kontext
        with organisation_kontext(org):
            log_aktion(None, 'API-Schlüssel angelegt', objekt=token.name, details=f'{token.anfang}…', kategorie='sicherheit')
        self.stdout.write(f'Schlüssel für «{org.firma}» ({token.name}). Jetzt notieren, er wird nicht wieder angezeigt:\n\n{roh}\n')
