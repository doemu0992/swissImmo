"""Der Betreiber stellt ein Abonnement ein (Admin und Oberfläche sind dafür nicht gedacht).

    python manage.py abo_einstellen 3 --module signatur,belegerkennung
    python manage.py abo_einstellen 3 --abrechnung-ab 2026-12-01
    python manage.py abo_einstellen 3 --bestandsschutz aus
    python manage.py abo_einstellen 3 --zahlung AB-2026-000012 [--datum 2026-12-05]
    python manage.py abo_einstellen 3 --stornieren AB-2026-000012

Der Admin ist nur lesend (`core/admin_base.py`); Zahlungen und Zubuchungen laufen
über diesen Befehl, damit sie einen Ort und eine Spur haben. Es wird nichts
gelöscht: Eine Rechnung wird storniert, ein Modul ausgeschaltet.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from core import funktionen as f


class Command(BaseCommand):
    help = 'Zugebuchte Module, Abrechnungsbeginn, Bestandsschutz und Zahlungseingang eines Abonnements setzen.'

    def add_arguments(self, parser):
        parser.add_argument('organisation', type=int)
        parser.add_argument('--module', default=None,
                            help='Kommagetrennte Schlüssel (ersetzt die Liste). Leer = keine.')
        parser.add_argument('--abrechnung-ab', default=None, help='JJJJ-MM-TT; "aus" setzt den Beginn zurück.')
        parser.add_argument('--bestandsschutz', choices=['an', 'aus'], default=None)
        parser.add_argument('--zahlung', default=None, help='Rechnungsnummer: Zahlungseingang bestätigen.')
        parser.add_argument('--datum', default=None, help='Zahlungsdatum JJJJ-MM-TT (Standard: heute).')
        parser.add_argument('--stornieren', default=None, help='Rechnungsnummer stornieren.')

    def handle(self, *args, **opts):
        from abo import dienst
        from abo.models import AboRechnung, Abonnement
        from crm.models import Organisation

        organisation = Organisation.objects.filter(pk=opts['organisation']).first()
        if organisation is None:
            raise CommandError(f"Keine Verwaltung mit ID {opts['organisation']}.")
        abo = Abonnement.alle_organisationen.filter(organisation=organisation).first()
        if abo is None:
            abo = dienst.abonnement_anlegen(organisation)

        if opts['module'] is not None:
            schluessel = [m.strip() for m in opts['module'].split(',') if m.strip()]
            for k in schluessel:
                f.hat_funktion(None, k)          # wirft UnbekannteFunktion bei Tippfehlern
            abo.zusatzmodule = schluessel
        if opts['abrechnung_ab'] is not None:
            abo.abrechnung_ab = None if opts['abrechnung_ab'] == 'aus' else date.fromisoformat(opts['abrechnung_ab'])
        if opts['bestandsschutz'] is not None:
            abo.uneingeschraenkt = opts['bestandsschutz'] == 'an'
        abo.save()

        for nummer, tun in ((opts['zahlung'], 'zahlung'), (opts['stornieren'], 'storno')):
            if not nummer:
                continue
            rechnung = AboRechnung.alle_organisationen.filter(organisation=organisation, nummer=nummer).first()
            if rechnung is None:
                raise CommandError(f'Rechnung {nummer} gehört nicht zu dieser Verwaltung.')
            if tun == 'zahlung':
                datum = date.fromisoformat(opts['datum']) if opts['datum'] else None
                dienst.als_bezahlt(rechnung, datum)
            else:
                dienst.stornieren(rechnung)
        self.stdout.write(self.style.SUCCESS(f'Abonnement {organisation}: gespeichert.'))
