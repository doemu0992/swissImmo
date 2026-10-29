"""Datenimport für Wechselkunden von der Kommandozeile (FUNK-09).

    python manage.py daten_importieren --organisation ID [--trockenlauf]
        [--eigentuemer datei] [--liegenschaften datei] [--objekte datei] [--mieter datei] [--vertraege datei]

Dieselbe Verarbeitung wie die Oberfläche (`core/services/datenimport.py`): zuerst ein Trockenlauf, bei
Fehlern Abbruch mit der Fehlerliste (Exit-Code 1, nichts angelegt), sonst die Ausführung in EINER
Transaktion. Ohne `--trockenlauf` wird importiert, wenn der Trockenlauf fehlerfrei war. Der Lauf steht
im Protokoll der Organisation (Einstellungen, Daten). Gedacht für grosse Bestände, bei denen der
Webzugriff an eine Zeitgrenze stösst.

Jeder Aufruf gilt GENAU EINER Organisation (Pflichtargument): Es gibt keinen Lauf über alle.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.services.datenimport import ARTEN, AusfuehrungsFehler, lauf_ausfuehren, vorschau_erstellen
from crm.models import Organisation


class Command(BaseCommand):
    help = 'Importiert Eigentümer, Liegenschaften, Objekte, Mieter und laufende Verträge aus CSV/XLSX (alles oder nichts).'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int, required=True, help='ID der Organisation (Pflicht)')
        parser.add_argument('--trockenlauf', action='store_true', help='Nur prüfen, nichts anlegen')
        for art in ARTEN:
            parser.add_argument(f'--{art}', default=None, help=f'Datei für {art}')

    def handle(self, *args, **opts):
        org = Organisation.objects.filter(pk=opts['organisation']).first()
        if org is None:
            raise CommandError(f'Organisation {opts["organisation"]} gibt es nicht.')
        dateien = {}
        for art in ARTEN:
            if opts.get(art):
                pfad = Path(opts[art])
                if not pfad.is_file():
                    raise CommandError(f'Datei nicht gefunden: {pfad}')
                dateien[art] = (pfad.name, pfad.read_bytes())
        if not dateien:
            raise CommandError('Keine Datei angegeben (z. B. --liegenschaften datei.csv).')
        lauf = vorschau_erstellen(org, None, dateien)
        self._ausgabe(lauf)
        if lauf.anzahl_fehler:
            raise CommandError(f'{lauf.anzahl_fehler} Fehler: nichts wurde angelegt.')
        if opts['trockenlauf']:
            self.stdout.write(self.style.SUCCESS('Trockenlauf fehlerfrei. Nichts angelegt.'))
            return
        try:
            lauf = lauf_ausfuehren(org, lauf.pk, None)
        except AusfuehrungsFehler as e:
            raise CommandError(str(e))
        self._ausgabe(lauf)
        if lauf.anzahl_fehler:
            raise CommandError(f'{lauf.anzahl_fehler} Fehler beim Ausführen: nichts wurde angelegt.')
        neu = sum(z.get('neu', 0) for z in lauf.zaehler.values())
        self.stdout.write(self.style.SUCCESS(f'Importiert: {neu} Datensätze angelegt (Protokoll {lauf.pk}).'))

    def _ausgabe(self, lauf):
        for art, z in lauf.zaehler.items():
            self.stdout.write(f'{art}: {z["zeilen"]} Zeilen, {z["neu"]} neu, {z["vorhanden"]} übersprungen, {z["fehler"]} Fehler')
        for m in lauf.meldungen:
            ort = f'Zeile {m["zeile"]}' if m.get('zeile') else 'Datei'
            feld = f' [{m["feld"]}]' if m.get('feld') else ''
            self.stdout.write(f'{m["stufe"].upper()} {m["art"]} {ort}{feld}: {m["text"]}')
