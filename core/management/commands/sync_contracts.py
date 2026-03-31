from rentals.models import Mietvertrag, Dokument

from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Erstellt fehlende Dokumenten-Einträge für bereits unterschriebene Verträge'

    def handle(self, *args, **options):
        # 1. Alle unterschriebenen Verträge mit PDF suchen
        vertraege = Mietvertrag.objects.filter(
            sign_status='unterzeichnet'
        ).exclude(pdf_datei='')

        count = 0
        skipped = 0

        self.stdout.write(f"Prüfe {vertraege.count()} unterschriebene Verträge...")

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
                    self.stdout.write(self.style.SUCCESS(f"✅ Dokument erstellt für: {v.mieter}"))
                    count += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"❌ Fehler bei {v.mieter}: {e}"))
            else:
                skipped += 1

        self.stdout.write("-" * 30)
        self.stdout.write(f"Fertig! {count} Dokumente erstellt, {skipped} waren schon da.")
