"""Sammel-Mahnlauf über alle fälligen Debitoren. Für PythonAnywhere Scheduled
Task (z.B. wöchentlich):

    python manage.py mahnlauf [--zins] [--kein-versand]
    python manage.py mahnlauf --organisation 3

JE VERWALTUNG EIN LAUF. Der Lauf verschickt Mahnungen mit Namen und Betrag an
Mieter; ein Lauf über den gesamten Bestand wäre also nicht bloss falsch
gerechnet, sondern versendet — mit dem Briefkopf der falschen Verwaltung.
Seit Etappe 6.2 wirft `DebitorenRechnung.objects` ohne Kontext, was den Fehler
sichtbar macht, statt ihn zuzustellen."""
from django.core.management.base import BaseCommand, CommandError

from core.models import AktivitaetsLog
from core.services.automation import run_mahnlauf


class Command(BaseCommand):
    help = "Führt einen Sammel-Mahnlauf über alle fälligen offenen Debitoren aus — je Verwaltung."

    def add_arguments(self, parser):
        parser.add_argument('--zins', action='store_true', help="Verzugszins (5%) berechnen")
        parser.add_argument('--kein-versand', action='store_true', help="Keine E-Mails versenden")
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Verwaltung (ID). Ohne Angabe: alle.')

    def handle(self, *args, **opts):
        from core.tenancy import je_organisation

        _, fehler = je_organisation(lambda organisation: self._mahnen(organisation, opts),
                                    auswahl=opts.get('organisation'), ausgabe=self.stderr)
        if fehler:
            raise CommandError(f"Mahnlauf: {len(fehler)} Verwaltung(en) abgebrochen — "
                               f"{', '.join(str(o) for o, _ in fehler)}.")

    def _mahnen(self, organisation, opts):
        res = run_mahnlauf(aktive_lg=None, send_email=not opts['kein_versand'],
                           mit_zins=opts['zins'], user=None)
        msg = (f"Mahnlauf: {res['gemahnt']} gemahnt, {res['emails']} E-Mails, "
               f"Gebühren CHF {res['gebuehren']}, Zins CHF {res['zins']}.")
        AktivitaetsLog.objects.create(aktion="Mahnlauf (Scheduler)", objekt="Sammellauf",
                                      details=msg)
        self.stdout.write(self.style.SUCCESS(f"{organisation}: {msg}"))
        return res
