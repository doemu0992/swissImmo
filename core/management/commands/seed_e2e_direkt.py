"""Daten für `e2e/tests/zz-direktkanal.spec.ts` (Direktkanal Mieter <-> Handwerker, Terminabstimmung).

Läuft NACH `seed_e2e` (braucht Organisation, Liegenschaft, Mieterin «e2e-mieter»). Idempotent.
Nur für Test-/E2E-Datenbanken.

* «E2E Direkt Heizung»: von der Mieterin selbst gemeldet, mit Auftrag an «E2E Direkt Sanitär» (Termin offen)
  und einer Direktnachricht des Handwerkers.
* «E2E Fremd Ticket»: gemeldet von einer anderen Mieterin derselben Verwaltung (andere Einheit). Die
  Mieterin «e2e-mieter» darf es nie sehen (404) — die Gegenprobe.

Die Seed-Nachrichten stehen auf `gelesen=True`: Sonst zählt das Menüband sie als ungelesen, und Specs,
die Zähler messen, wären vom Seed abhängig.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Seedet Ticket mit Handwerkerauftrag und ein fremdes Ticket für die Direktkanal-Spec."

    def handle(self, *args, **options):
        from core.tenancy import organisation_kontext
        from crm.models import Handwerker, Mieter, Organisation
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag
        from tickets.models import HandwerkerAuftrag, SchadenMeldung, TicketNachricht

        org = Organisation.objects.filter(firma="E2E Verwaltung AG").first()
        if org is None:
            raise CommandError("Zuerst `seed_e2e` ausführen.")
        with organisation_kontext(org):
            m = Mieter.objects.filter(email="e2e-mieter@example.ch").first()
            if m is None:
                raise CommandError("Zuerst `seed_e2e` ausführen.")
            lg = Liegenschaft.objects.get(strasse="E2E-Weg 1", plz="8000", ort="Zürich")
            e = Einheit.objects.get(liegenschaft=lg, bezeichnung="3.5 Zi E2E")
            hw, _ = Handwerker.objects.get_or_create(firma="E2E Direkt Sanitär", defaults=dict(telefon="044 000 00 01"))
            ticket, _ = SchadenMeldung.objects.get_or_create(
                titel="E2E Direkt Heizung",
                defaults=dict(liegenschaft=lg, betroffene_einheit=e, status="in_bearbeitung", gemeldet_von=m, gelesen=True,
                              beschreibung="Die Heizung im Wohnzimmer bleibt kalt.", zutritt="telefon"))
            auftrag, _ = HandwerkerAuftrag.objects.get_or_create(
                ticket=ticket, handwerker=hw, defaults=dict(status="offen"))
            if not TicketNachricht.objects.filter(ticket=ticket, typ="direkt").exists():
                TicketNachricht.objects.create(
                    ticket=ticket, typ="direkt", auftrag=auftrag, seite="handwerker",
                    absender_name=hw.firma, nachricht="Guten Tag, wann passt es Ihnen?", gelesen=True,
                    is_intern=True)  # wie direktkanal.schreiben: nicht im allgemeinen Verlauf

            fremd, _ = Mieter.objects.get_or_create(
                email="e2e-fremd-mieter@example.ch",
                defaults=dict(typ="person", vorname="Franz", nachname="Fremd",
                              strasse="Seeweg 4", plz="8000", ort="Zürich"))
            e2, _ = Einheit.objects.get_or_create(
                liegenschaft=lg, bezeichnung="2.5 Zi E2E Fremd",
                defaults=dict(typ="whg", nettomiete_aktuell=Decimal("1200"),
                              nebenkosten_aktuell=Decimal("150"), flaeche_m2=Decimal("60")))
            Mietvertrag.objects.get_or_create(
                mieter=fremd, einheit=e2,
                defaults=dict(beginn=date(2024, 1, 1), netto_mietzins=Decimal("1200"),
                              nebenkosten=Decimal("150"), status="aktiv"))
            ft, _ = SchadenMeldung.objects.get_or_create(
                titel="E2E Fremd Ticket",
                defaults=dict(liegenschaft=lg, betroffene_einheit=e2, status="in_bearbeitung", gemeldet_von=fremd, gelesen=True,
                              beschreibung="Fremde Meldung.", zutritt="telefon"))
            fhw, _ = Handwerker.objects.get_or_create(firma="E2E Fremd Sanitär", defaults=dict(telefon="044 000 00 02"))
            HandwerkerAuftrag.objects.get_or_create(ticket=ft, handwerker=fhw, defaults=dict(status="offen"))
        self.stdout.write(self.style.SUCCESS("seed_e2e_direkt: Ticket mit Auftrag und fremdes Ticket angelegt."))
