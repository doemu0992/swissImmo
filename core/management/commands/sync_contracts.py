"""Erstellt fehlende Dokumenten-Einträge für bereits unterschriebene Verträge.

    python manage.py sync_contracts
    python manage.py sync_contracts --organisation 3

JE VERWALTUNG EIN LAUF. Der Befehl legt `Dokument`-Einträge an; ohne Kontext
bekäme der Datensatz seine Zugehörigkeit vom Zufall (bzw. wirft seit Etappe
6.2, was besser ist als zu raten).
"""
from django.core.management.base import BaseCommand, CommandError

from rentals.models import Dokument, Mietvertrag


class Command(BaseCommand):
    help = 'Erstellt fehlende Dokumenten-Einträge für bereits unterschriebene Verträge'

    def add_arguments(self, parser):
        parser.add_argument('--organisation', type=int, default=None,
                            help='Nur diese Verwaltung (ID). Ohne Angabe: alle.')

    def handle(self, *args, **options):
        from core.tenancy import je_organisation

        _, fehler = je_organisation(self._nachtragen,
                                    auswahl=options.get('organisation'), ausgabe=self.stderr)
        if fehler:
            raise CommandError(f"{len(fehler)} Verwaltung(en) abgebrochen — "
                               f"{', '.join(str(o) for o, _ in fehler)}.")

    def _nachtragen(self, organisation):
        # 1. Alle unterschriebenen Verträge mit PDF suchen
        vertraege = Mietvertrag.objects.filter(
            sign_status='unterzeichnet'
        ).exclude(pdf_datei='')

        count = 0
        skipped = 0

        self.stdout.write(f"{organisation}: prüfe {vertraege.count()} unterschriebene Verträge...")

        for v in vertraege:
            # 2. Prüfen, ob das Dokument schon existiert
            exists = Dokument.objects.filter(vertrag=v, kategorie='vertrag').exists()

            if not exists:
                # 3. Dokument erstellen (nachträglich)
                try:
                    Dokument.objects.create(
                        titel=f"Mietvertrag {v.mieter} (Unterschrieben)",
                        kategorie='vertrag',
                        vertrag=v,
                        mieter=v.mieter,
                        einheit=v.einheit,
                        datei=v.pdf_datei
                    )
                    self.stdout.write(self.style.SUCCESS(f"OK Dokument erstellt für: {v.mieter}"))
                    count += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Fehler bei {v.mieter}: {e}"))
            else:
                skipped += 1

        self.stdout.write(f"Fertig! {count} Dokumente erstellt, {skipped} waren schon da.")
        return count
