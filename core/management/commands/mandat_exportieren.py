"""Mandatsexport von der Kommandozeile (FUNK-13): alle Daten EINER Organisation als ZIP.

    python manage.py mandat_exportieren --organisation ID --ziel datei.zip [--ohne-dokumente]

Dieselbe Erstellung wie in der Oberfläche (`core/services/datenexport.py`), ohne die
Zeitgrenze einer Webanfrage. Liest nur. Der Export wird im Aktivitätslog der Organisation
festgehalten. Jeder Aufruf gilt GENAU EINER Organisation (Pflichtargument).
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import AktivitaetsLog
from core.services.datenexport import mandat_zip
from core.tenancy import organisation_kontext
from crm.models import Organisation


class Command(BaseCommand):
    help = 'Schreibt alle Daten einer Organisation (CSV/JSON je Tabelle, Dokumente) in ein ZIP. Verändert nichts.'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int, required=True, help='ID der Organisation (Pflicht)')
        parser.add_argument('--ziel', required=True, help='Zieldatei (.zip); wird nicht überschrieben')
        parser.add_argument('--ohne-dokumente', action='store_true', help='Nur die Tabellen, keine Dokumente')

    def handle(self, *args, **opts):
        org = Organisation.objects.filter(pk=opts['organisation']).first()
        if org is None:
            raise CommandError(f'Organisation {opts["organisation"]} gibt es nicht.')
        ziel = Path(opts['ziel'])
        if ziel.exists():
            raise CommandError(f'{ziel} gibt es schon; es wird nichts überschrieben.')
        with organisation_kontext(org):
            try:
                with open(ziel, 'xb') as datei:
                    stat = mandat_zip(org, datei, mit_dokumenten=not opts['ohne_dokumente'], erstellt_von='Kommandozeile')
                AktivitaetsLog.objects.create(
                    organisation=org, aktion='Mandatsexport erstellt', objekt=org.firma[:200], kategorie='sicherheit',
                    details=f'Kommandozeile · {len(stat["tabellen"])} Tabellen · {stat["zeilen"]} Zeilen · '
                            f'{stat["dokumente"]} Dokumente')
            except Exception:
                ziel.unlink(missing_ok=True)       # kein halbes ZIP zurücklassen
                raise
        self.stdout.write(self.style.SUCCESS(
            f'{ziel}: {len(stat["tabellen"])} Tabellen, {stat["zeilen"]} Zeilen, {stat["dokumente"]} Dokumente '
            f'({stat["fehlende_dokumente"]} nicht lesbar).'))
