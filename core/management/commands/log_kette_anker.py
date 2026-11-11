"""Schreibt den Kopf der Hash-Kette je Verwaltung in eine Datei (Ankerpunkt ausser Haus), Roadmap 2.3.

`python manage.py log_kette_anker [--ziel ORDNER] [--mail ADRESSE]`

Ohne `--ziel`: `~/sicherungen/anker/`. Jede Zeile: `{"organisation", "kette_nr", "kette_hash", "zeitpunkt"}`. Die Datei hat das Datum im Namen
und wird nie überschrieben. Gedacht als täglicher Scheduled Task; die Dateien gehören ausser Haus (wie die Offsite-Sicherung) oder
per Mail an eine Adresse, die der Betreiber der Datenbank nicht verändern kann (`--mail`). Geprüft wird mit
`log_kette_pruefen --anker DATEI`. Siehe `core/log_kette.py`.
"""
import json
import os
from pathlib import Path

from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import log_kette


class Command(BaseCommand):
    help = 'Legt den Kopf der Audit-Log-Kette als Ankerpunkt ab.'

    def add_arguments(self, parser):
        parser.add_argument('--ziel', metavar='ORDNER', help='Zielordner (Standard: ~/sicherungen/anker).')
        parser.add_argument('--mail', metavar='ADRESSE', help='Zusätzlich per E-Mail an diese Adresse senden.')

    def handle(self, *args, **opt):
        _geprueft, befunde, koepfe = log_kette.pruefen()
        if befunde:
            for b in befunde:
                self.stderr.write(b)
            raise CommandError('Kette nicht in Ordnung: Es wird KEIN neuer Anker abgelegt (er würde den Schaden bestätigen).')
        jetzt = timezone.now()
        zeilen = [json.dumps({'organisation': org, 'kette_nr': nr, 'kette_hash': h, 'zeitpunkt': jetzt.isoformat()})
                  for org, (nr, h) in sorted(koepfe.items())]
        ordner = Path(opt.get('ziel') or os.path.expanduser('~/sicherungen/anker'))
        ordner.mkdir(parents=True, exist_ok=True)
        datei = ordner / f'anker-{jetzt:%Y%m%d-%H%M%S}.jsonl'
        datei.write_text('\n'.join(zeilen) + '\n', encoding='utf-8')
        self.stdout.write(f'{len(zeilen)} Anker in {datei}')
        if opt.get('mail'):
            mail = EmailMessage(subject=f'Audit-Log-Anker {jetzt:%d.%m.%Y %H:%M}', body='\n'.join(zeilen), to=[opt['mail']])
            mail.send()
            self.stdout.write(f'Per E-Mail an {opt["mail"]} gesendet.')
