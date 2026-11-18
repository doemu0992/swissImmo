"""Widerruft API-Schlüssel (sofort wirksam). Ohne `--id` werden die Schlüssel aufgelistet.

    python manage.py api_token_widerrufen              # Liste
    python manage.py api_token_widerrufen --id 3
"""
from django.core.management.base import BaseCommand, CommandError

from core import api_token
from core.auth import log_aktion
from core.models import ApiToken
from core.tenancy import organisation_kontext


class Command(BaseCommand):
    help = 'Listet API-Schlüssel oder widerruft einen (--id).'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int)

    def handle(self, *args, id=None, **opts):
        if id is None:
            for t in ApiToken.alle_organisationen.select_related('organisation').order_by('organisation_id', 'pk'):
                zustand = 'aktiv' if t.aktiv else f'widerrufen {t.widerrufen_am:%d.%m.%Y}'
                benutzt = f'zuletzt {t.zuletzt_benutzt:%d.%m.%Y %H:%M}' if t.zuletzt_benutzt else 'nie benutzt'
                self.stdout.write(f'{t.pk}\t{t.organisation.firma}\t{t.name}\t{t.anfang}…\t{zustand}\t{benutzt}')
            return
        t = ApiToken.alle_organisationen.select_related('organisation').filter(pk=id).first()
        if t is None:
            raise CommandError(f'Schlüssel {id} gibt es nicht.')
        api_token.widerrufen(t)
        with organisation_kontext(t.organisation):
            log_aktion(None, 'API-Schlüssel widerrufen', objekt=t.name, details=f'{t.anfang}…', kategorie='sicherheit')
        self.stdout.write(f'Schlüssel {id} widerrufen.')
