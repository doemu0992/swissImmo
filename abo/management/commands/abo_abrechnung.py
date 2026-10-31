"""Abrechnungslauf der Plattform: Rechnungen stellen, Zahlungszustand nachführen, erinnern.

    python manage.py abo_abrechnung                         # alle Verwaltungen
    python manage.py abo_abrechnung --organisation 3        # nur diese nachholen
    python manage.py abo_abrechnung --heute 2026-11-01      # Stichtag (Nachholen, Prüfen)

Täglich laufen lassen (Scheduled Task): Er ist idempotent. Pro Verwaltung und
Periode entsteht höchstens eine Rechnung, und der Zahlungszustand folgt dem
Datum (Mahnung, danach Lesemodus). Nichts wird gelöscht.

DIESER LAUF STELLT KEINE RECHNUNG MIT PLATZHALTERPREISEN. Solange
`settings.ABO_PREISE_FESTGELEGT` False ist, unterbleibt die Rechnungsstellung
und der Lauf sagt das; `--trotz-platzhalterpreisen` ist für Probeläufe.

JE VERWALTUNG EIN LAUF mit Fehlerisolation (`core.tenancy.je_organisation`): Ein
Fehler bei einer Verwaltung hält die übrigen nicht an; der Befehl endet am Schluss
trotzdem mit Fehler. Der Lauf selbst läuft auch für Verwaltungen im Lesemodus
(`abo_pruefen=False`): Er ist es, der sie wieder öffnet.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from abo.dienst import abrechnen


class Command(BaseCommand):
    help = 'Abrechnungslauf: Abo-Rechnungen stellen, Zahlungszustand nachführen, Erinnerungen senden.'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Verwaltung (ID). Ohne Angabe: alle.')
        parser.add_argument('--heute', default=None, help='Stichtag JJJJ-MM-TT (Standard: heute).')
        parser.add_argument('--trotz-platzhalterpreisen', action='store_true',
                            help='Rechnungen auch stellen, wenn die Preise nicht festgelegt sind (Probelauf).')
        parser.add_argument('--keine-mail', action='store_true', help='Keine Erinnerungen versenden.')

    def handle(self, *args, **opts):
        from core.tenancy import je_organisation

        heute = date.fromisoformat(opts['heute']) if opts['heute'] else None
        ergebnisse, fehler = je_organisation(
            lambda organisation: abrechnen(
                organisation, heute=heute, trotz_platzhalter=opts['trotz_platzhalterpreisen'],
                mail=not opts['keine_mail']),
            auswahl=opts['organisation'], ausgabe=self.stderr, abo_pruefen=False)

        neue = [e['rechnung'] for e in ergebnisse if e['rechnung']]
        self.stdout.write(f'{len(neue)} Rechnung(en) gestellt'
                          + (f': {", ".join(neue)}' if neue else '') + '.')
        for e in ergebnisse:
            if e['zustand'] != 'aktiv':
                self.stdout.write(f"  Verwaltung {e['organisation']}: {e['zustand']}")
        if any(e.get('preise_offen') for e in ergebnisse):
            self.stdout.write(self.style.WARNING(
                'Preise und MWST sind nicht festgelegt (settings.ABO_PREISE_FESTGELEGT): '
                'es wurden keine fälligen Rechnungen gestellt.'))
        if fehler:
            raise CommandError(
                f"Abrechnung: {len(fehler)} Verwaltung(en) abgebrochen — "
                f"{', '.join(str(o) for o, _ in fehler)}.")
