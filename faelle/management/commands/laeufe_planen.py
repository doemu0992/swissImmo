"""Legt die Standard-Laufarten an und plant die faelligen Perioden.

Idempotent in beiden Teilen: Bestehende Laufarten werden nicht ueberschrieben
(eine Verwaltung darf den Faelligkeitstag anpassen), und eine bereits geplante
Periode wird nicht doppelt angelegt.

    manage.py laeufe_planen                     alle Organisationen, aktuelle Periode
    manage.py laeufe_planen --periode 2026-09
    manage.py laeufe_planen --organisation 3
"""
import calendar
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from crm.models import Organisation
from faelle.lauf_models import Lauf, Laufart

# schluessel: (bezeichnung, rhythmus, faellig_am_tag, reihenfolge, entitlement, ziel)
VORLAGEN = {
    'sollstellung':  ('Sollstellung', Laufart.MONATLICH, 1, 10,
                      'monatslauf', 'fw_sollstellung'),
    'bankabgleich':  ('Bankabgleich', Laufart.MONATLICH, 5, 20,
                      'monatslauf', 'fw_bankabgleich'),
    'mahnlauf':      ('Mahnlauf', Laufart.MONATLICH, 15, 30,
                      'monatslauf', 'fw_mahnwesen'),
    'zahllauf':      ('Zahllauf Kreditoren', Laufart.MONATLICH, 25, 40,
                      'monatslauf', 'fw_zahllauf'),
    'mwst':          ('MWST-Abrechnung', Laufart.QUARTALSWEISE, 28, 50,
                      'monatslauf', 'fw_mwst'),
    'nebenkosten':   ('Nebenkostenabrechnung', Laufart.JAEHRLICH, 30, 60,
                      'nebenkostenlauf', 'fw_nebenkosten'),
}

#: Monate, in denen ein quartalsweiser bzw. jaehrlicher Lauf faellig wird.
QUARTALSMONATE = (1, 4, 7, 10)
JAHRESMONAT = 9          # Abgabe der Nebenkostenabrechnung: September


def periode_fuer(art, stichtag):
    """Periodenschluessel je Rhythmus, oder None wenn jetzt nichts ansteht."""
    if art.rhythmus == Laufart.MONATLICH:
        return f'{stichtag.year}-{stichtag.month:02d}'
    if art.rhythmus == Laufart.QUARTALSWEISE:
        if stichtag.month not in QUARTALSMONATE:
            return None
        return f'{stichtag.year}-Q{(stichtag.month - 1) // 3 + 1}'
    if stichtag.month != JAHRESMONAT:
        return None
    return str(stichtag.year - 1)      # abgerechnet wird das Vorjahr


def faelligkeit(art, stichtag):
    tag = min(art.faellig_am_tag, calendar.monthrange(stichtag.year, stichtag.month)[1])
    return date(stichtag.year, stichtag.month, tag)


class Command(BaseCommand):
    help = 'Legt Standard-Laufarten an und plant die faelligen Perioden.'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int, default=None)
        parser.add_argument('--periode', type=str, default=None,
                            help='Stichtag als JJJJ-MM; ohne Angabe der heutige Monat.')

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
            neue_arten = neue_laeufe = 0
            for schluessel, (bez, rhythmus, tag, reihe, ent, ziel) in VORLAGEN.items():
                art, erzeugt = Laufart.alle_organisationen.get_or_create(
                    organisation=org, schluessel=schluessel,
                    defaults={'bezeichnung': bez, 'rhythmus': rhythmus,
                              'faellig_am_tag': tag, 'reihenfolge': reihe,
                              'entitlement': ent, 'ziel_ansicht': ziel})
                neue_arten += int(erzeugt)
                if not art.aktiv:
                    continue
                periode = periode_fuer(art, stichtag)
                if periode is None:
                    continue
                _lauf, neu = Lauf.alle_organisationen.get_or_create(
                    laufart=art, periode=periode,
                    defaults={'organisation': org,
                              'faellig_am': faelligkeit(art, stichtag)})
                neue_laeufe += int(neu)
            if laut:
                self.stdout.write(
                    f'  {org}: {neue_arten} Laufarten, {neue_laeufe} Perioden neu')
        if laut:
            self.stdout.write(self.style.SUCCESS('Fertig.'))
