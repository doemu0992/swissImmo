"""Jahresabschluss-Läufe: lineare Abschreibungen + Erneuerungsfonds-Einlagen.
Für PythonAnywhere Scheduled Task (jährlich, z.B. 2. Januar):

    python manage.py jahresabschluss_lauf --jahr 2026
    python manage.py jahresabschluss_lauf --jahr 2026 --organisation 3

Ohne --jahr wird das Vorjahr abgeschlossen.

JE VERWALTUNG EIN LAUF — hier ist es besonders heikel: AfA und
Erneuerungsfonds sind Buchungen im Journal. Ein Lauf über den gesamten Bestand
schriebe Buchungssätze mit fremden Belegnummern in eine fremde Buchhaltung.
Rückgängig zu machen ist das nur über Stornobuchungen, die ihrerseits im
Journal stehen bleiben (OR 958f)."""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import AktivitaetsLog
from core.services.automation import run_abschreibungen, run_erneuerungsfonds_einlage


class Command(BaseCommand):
    help = "Bucht AfA (lineare Abschreibungen) + Erneuerungsfonds-Einlagen für ein Jahr, je Verwaltung."

    def add_arguments(self, parser):
        parser.add_argument('--jahr', type=int, default=timezone.localdate().year - 1)
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Verwaltung (ID). Ohne Angabe: alle.')

    def handle(self, *args, **opts):
        from core.tenancy import je_organisation

        jahr = opts['jahr']
        _, fehler = je_organisation(lambda organisation: self._abschliessen(organisation, jahr),
                                    auswahl=opts.get('organisation'), ausgabe=self.stderr)
        if fehler:
            raise CommandError(f"Jahresabschluss {jahr}: {len(fehler)} Verwaltung(en) "
                               f"abgebrochen — {', '.join(str(o) for o, _ in fehler)}.")

    def _abschliessen(self, organisation, jahr):
        n_afa, s_afa = run_abschreibungen(jahr, user=None)
        n_fonds, s_fonds = run_erneuerungsfonds_einlage(jahr, user=None)
        msg = (f"Jahresabschluss {jahr}: AfA {n_afa} Buchungen (CHF {s_afa}), "
               f"Erneuerungsfonds {n_fonds} Einlagen (CHF {s_fonds}).")
        AktivitaetsLog.objects.create(aktion="Jahresabschluss-Lauf (Scheduler)",
                                      objekt=str(jahr), details=msg)
        self.stdout.write(self.style.SUCCESS(f"{organisation}: {msg}"))
        return (n_afa, n_fonds)
