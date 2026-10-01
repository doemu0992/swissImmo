"""Legt die Standard-Laufarten an und plant die faelligen Perioden.

Idempotent in beiden Teilen: Bestehende Laufarten werden nicht ueberschrieben
(eine Verwaltung darf den Faelligkeitstag anpassen), und eine bereits geplante
Periode wird nicht doppelt angelegt.

    manage.py laeufe_planen                     alle Organisationen, aktuelle Periode
    manage.py laeufe_planen --periode 2026-09
    manage.py laeufe_planen --organisation 3
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from crm.models import Organisation
# Planung liegt im Dienst, damit Scheduler, Dashboard und dieser Befehl EINE
# Logik teilen. Namen bleiben hier importierbar (Tests, alte Aufrufer).
from faelle.lauf_dienst import (  # noqa: F401
    JAHRESMONAT, QUARTALSMONATE, VORLAGEN, abgleichen_aus_daten, faelligkeit,
    periode_fuer, planen)


class Command(BaseCommand):
    help = 'Legt Standard-Laufarten an und plant die faelligen Perioden.'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int, default=None)
        parser.add_argument('--periode', type=str, default=None,
                            help='Stichtag als JJJJ-MM; ohne Angabe der heutige Monat.')
        parser.add_argument('--abgleichen', action='store_true',
                            help='Ueberfaellige Monatslaeufe schliessen, deren '
                                 'Ausfuehrung in den Daten belegt ist.')

    @transaction.atomic
    def handle(self, *args, **opt):
        laut = opt.get('verbosity', 1) >= 1
        if opt['periode']:
            jahr, monat = (int(t) for t in opt['periode'].split('-'))
            stichtag = date(jahr, monat, 1)
        else:
            stichtag = timezone.localdate()

        organisationen = Organisation.objects.all()
        if opt['organisation']:
            organisationen = organisationen.filter(pk=opt['organisation'])
        if not organisationen:
            if laut:
                self.stdout.write('Keine Organisation gefunden — nichts zu tun.')
            return

        for org in organisationen:
            neue_arten, neue_laeufe = planen(org, stichtag)
            geschlossen = 0
            if opt['abgleichen']:
                from core.tenancy import organisation_kontext
                with organisation_kontext(org):
                    geschlossen = abgleichen_aus_daten()
            if laut:
                self.stdout.write(
                    f'  {org}: {neue_arten} Laufarten, {neue_laeufe} Perioden neu'
                    + (f', {geschlossen} belegte Laeufe abgeschlossen'
                       if opt['abgleichen'] else ''))
        if laut:
            self.stdout.write(self.style.SUCCESS('Fertig.'))
