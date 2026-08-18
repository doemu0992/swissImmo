"""Das Betreiberlog lesen — Sicherheitsereignisse ohne bestimmbare Verwaltung.

    python manage.py sicherheitslog                 # letzte 50
    python manage.py sicherheitslog --tage 7        # letzte 7 Tage
    python manage.py sicherheitslog --ip            # nach IP gruppiert

Hier landen die Ereignisse, die die INSTALLATION treffen statt eine
Verwaltung — vor allem Anmeldeversuche mit Benutzernamen, die es gar nicht
gibt. Ereignisse mit bestimmbarem Mandanten stehen weiterhin im Logbuch der
jeweiligen Verwaltung (`AktivitaetsLog`), weil sie dort gebraucht werden.

Ein Log, das niemand lesen kann, ist nur wenig besser als keines — deshalb
dieser Befehl. Eine Oberfläche dafür gibt es bewusst (noch) nicht: Das Log
gehört dem Betreiber, nicht einem Mandanten, und in der Fairwalter-Oberfläche
ist jede Seite mandantengebunden.
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import SicherheitsEreignis


class Command(BaseCommand):
    help = 'Zeigt die Sicherheitsereignisse ohne bestimmbare Verwaltung.'

    def add_arguments(self, parser):
        parser.add_argument('--tage', type=int, default=None,
                            help='Nur die letzten N Tage.')
        parser.add_argument('--anzahl', type=int, default=50,
                            help='Wie viele Zeilen (Standard 50).')
        parser.add_argument('--ip', action='store_true',
                            help='Nach IP-Adresse gruppiert statt chronologisch — '
                                 'so faellt ein Dauerbeschuss von einer Adresse auf.')

    def handle(self, *args, **opts):
        qs = SicherheitsEreignis.objects.all()
        if opts['tage']:
            qs = qs.filter(zeitpunkt__gte=timezone.now() - timedelta(days=opts['tage']))

        gesamt = qs.count()
        if not gesamt:
            self.stdout.write(self.style.SUCCESS('Keine Sicherheitsereignisse.'))
            return

        if opts['ip']:
            zaehler = Counter(e.ip_adresse or '—' for e in qs)
            self.stdout.write(f'{gesamt} Ereignis(se), nach IP-Adresse:\n')
            for ip, n in zaehler.most_common(opts['anzahl']):
                self.stdout.write(f'  {n:6d}  {ip}')
            return

        self.stdout.write(f'{gesamt} Ereignis(se), neueste zuerst:\n')
        for e in qs[:opts['anzahl']]:
            self.stdout.write(
                f'  {e.zeitpunkt:%d.%m.%Y %H:%M}  {e.ip_adresse or "—":<16}  '
                f'{e.aktion} — {e.objekt}')
        if gesamt > opts['anzahl']:
            self.stdout.write(f'\n… {gesamt - opts["anzahl"]} weitere. Mit --anzahl mehr zeigen.')
