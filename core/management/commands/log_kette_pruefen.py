"""Prüft die Hash-Kette des Audit-Logs (Roadmap 2.3): `python manage.py log_kette_pruefen [--organisation ID] [--anker DATEI]`.

Endet mit Fehlercode 1, wenn die Kette nicht stimmt (gelöschte, verschobene, eingeschleuste oder geänderte Einträge). Mit
`--anker DATEI` (Ausgabe von `log_kette_anker`) wird zusätzlich gegen die ausser Haus abgelegten Ankerpunkte geprüft; nur so
fällt eine vollständig neu berechnete Kette auf. Siehe `core/log_kette.py`.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from core import log_kette


class Command(BaseCommand):
    help = 'Prüft die Hash-Kette des Audit-Logs (optional gegen eine Ankerdatei).'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int, help='Nur diese Verwaltung prüfen.')
        parser.add_argument('--anker', metavar='DATEI', help='Ankerdatei (JSON-Zeilen) aus `log_kette_anker`.')

    def handle(self, *args, **opt):
        geprueft, befunde, _koepfe = log_kette.pruefen(opt.get('organisation'))
        if opt.get('anker'):
            with open(opt['anker'], encoding='utf-8') as fh:
                zeilen = [json.loads(z) for z in fh if z.strip()]
            befunde += log_kette.mit_anker_vergleichen(zeilen)
            self.stdout.write(f'{len(zeilen)} Ankerpunkt(e) abgeglichen.')
        self.stdout.write(f'{geprueft} Kettenglied(er) geprüft.')
        if befunde:
            for b in befunde:
                self.stderr.write(b)
            raise CommandError(f'{len(befunde)} Befund(e): Die Hash-Kette des Audit-Logs ist NICHT in Ordnung.')
        self.stdout.write(self.style.SUCCESS('Hash-Kette in Ordnung.'))
