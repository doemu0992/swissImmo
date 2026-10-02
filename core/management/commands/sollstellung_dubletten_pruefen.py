"""Prüft den Bestand auf doppelt gestellte Sollstellungs-Rechnungen (nur lesen).

    python manage.py sollstellung_dubletten_pruefen

Eine Dublette ist: zwei oder mehr nicht stornierte Rechnungen «Miete & NK MM/JJJJ»
zum selben Vertrag. `run_sollstellung` verhindert sie (Zeilensperre plus
Existenzprüfung, bei Postgres getestet), eine Datenbank-Einschränkung gibt es
bewusst nicht: Ein Unique-Constraint auf einem Bestand mit Altlasten lässt die
Migration scheitern und blockiert damit den Deploy. Dieser Befehl ist die
Voraussetzung, um sie später sicher einzuführen: Meldet er «keine Dubletten»,
kann der Constraint ohne Risiko nachgezogen werden.

Es wird nichts verändert. Doppelte Rechnungen bucht ein Mensch per Storno
(Debitoren → Rechnung stornieren) aus — Geld wird nie automatisch korrigiert.
Endet mit Fehlercode 1, wenn Dubletten existieren (für Scheduler und CI).
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from finance.models import DebitorenRechnung

PRAEFIX = 'Miete & NK '


class Command(BaseCommand):
    help = "Listet doppelt gestellte Sollstellungs-Rechnungen (verändert nichts)."

    def handle(self, *args, **opts):
        doppelt = (DebitorenRechnung.alle_organisationen
                   .filter(titel__startswith=PRAEFIX, vertrag__isnull=False)
                   .exclude(status='storniert')
                   .values('vertrag_id', 'titel')
                   .annotate(anzahl=Count('id'))
                   .filter(anzahl__gt=1)
                   .order_by('titel', 'vertrag_id'))
        zeilen = list(doppelt)
        if not zeilen:
            self.stdout.write(self.style.SUCCESS('Keine Dubletten — Sollstellung ist eindeutig.'))
            return
        for z in zeilen:
            ids = list(DebitorenRechnung.alle_organisationen
                       .filter(vertrag_id=z['vertrag_id'], titel=z['titel'])
                       .exclude(status='storniert').values_list('id', flat=True))
            self.stdout.write(f"Vertrag {z['vertrag_id']} · {z['titel']} · "
                              f"{z['anzahl']}× (Rechnungen {ids})")
        self.stdout.write(self.style.ERROR(f'{len(zeilen)} Dublette(n) — bitte prüfen und stornieren.'))
        raise SystemExit(1)
