"""Monatlicher Mietenlauf (Sollstellung). Für PythonAnywhere Scheduled Task
(z.B. am 1. jeden Monats):

    python manage.py monatslauf                    # alle Verwaltungen
    python manage.py monatslauf --organisation 3   # nur diese eine nachholen

Ohne --jahr/--monat wird der aktuelle Monat gestellt.

JE VERWALTUNG EIN LAUF. `run_sollstellung` greift über `Mietvertrag.objects`
zu; seit Etappe 6.2 wirft das ohne Mandantenkontext, und der gibt es in einem
Scheduled Task keinen. Wer für wen gestellt wird, muss der Befehl also selbst
sagen — geraten wird hier nichts, dafür ist die Sollstellung zu teuer: Eine
Rechnung im falschen Bestand ist ein Beleg mit fremder Nummer im Journal
(OR 957a) und eine Forderung an einen fremden Mieter.

Bricht eine Verwaltung ab, laufen die übrigen weiter (siehe `je_organisation`)
— sonst bliebe der halbe Bestand ungestellt, weil bei einer Verwaltung ein
Konto fehlt. Der Befehl endet trotzdem mit Fehler, damit es auffällt."""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import AktivitaetsLog
from core.services.automation import run_sollstellung


class Command(BaseCommand):
    help = "Führt die monatliche Sollstellung (Mietenlauf) aus — idempotent, je Verwaltung."

    def add_arguments(self, parser):
        heute = timezone.localdate()
        parser.add_argument('--jahr', type=int, default=heute.year)
        parser.add_argument('--monat', type=int, default=heute.month)
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Verwaltung (ID). Ohne Angabe: alle.')

    def handle(self, *args, **opts):
        from core.tenancy import je_organisation

        jahr, monat = opts['jahr'], opts['monat']
        _, fehler = je_organisation(
            lambda organisation: self._stellen(organisation, jahr, monat),
            auswahl=opts.get('organisation'), ausgabe=self.stderr)
        if fehler:
            raise CommandError(
                f"Sollstellung {monat:02d}/{jahr}: {len(fehler)} Verwaltung(en) "
                f"abgebrochen — {', '.join(str(o) for o, _ in fehler)}.")

    def _stellen(self, organisation, jahr, monat):
        try:
            n = run_sollstellung(jahr, monat, user=None)
        except RuntimeError as e:
            # Fachlicher Abbruch (z.B. gesperrte Periode) — kein Programmfehler,
            # aber auch kein Erfolg: als Fehler weiterreichen, damit der Lauf
            # nicht still als erledigt gilt.
            raise CommandError(str(e)) from e
        msg = f"Sollstellung {monat:02d}/{jahr}: {n} Rechnung(en) erstellt."
        AktivitaetsLog.objects.create(aktion="Sollstellung (Scheduler)",
                                      objekt=f"{monat:02d}/{jahr}", details=msg)
        self.stdout.write(self.style.SUCCESS(f"{organisation}: {msg}"))
        return n
