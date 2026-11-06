"""Daten für `e2e/tests/abnahme-vergleich.spec.ts` (Abnahme vor Ort: Vergleich mit dem Vorzustand, live im Browser).

Läuft NACH `seed_e2e`. Idempotent. Nur für Test-/E2E-Datenbanken.

Eine eigene Einheit «1.5 Zi E2E Vergleich» mit eigenem Vertrag, damit kein anderer Test an den Abnahmen oder
Raumbuch-Elementen der übrigen Einheiten etwas bemerkt:

* ein abgeschlossenes Einzugsprotokoll: Teppich «normale Abnutzung» (Rang 1), Bodenbelag «neu i.O.» (Rang 0);
* ein offener Auszug darauf, ohne Bewertung. Die Spec bewertet und liest die Zeile «gleich / schlechter / besser».
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Seedet Einzug (abgeschlossen) und offenen Auszug mit Raumbuch für die Vergleichs-Spec."

    def handle(self, *args, **options):
        from core.services.zustandsvergleich import raumbuch_aktualisieren
        from core.tenancy import organisation_kontext
        from crm.models import Mieter, Organisation
        from portfolio.models import Ausstattung, Einheit, Liegenschaft
        from rentals.models import AbnahmePosition, Abnahmeprotokoll, Mietvertrag

        org = Organisation.objects.filter(firma="E2E Verwaltung AG").first()
        if org is None:
            raise CommandError("Zuerst `seed_e2e` ausführen.")
        with organisation_kontext(org):
            lg = Liegenschaft.objects.get(strasse="E2E-Weg 1", plz="8000", ort="Zürich")
            m = Mieter.objects.get(email="e2e-mieter@example.ch")
            e, _ = Einheit.objects.get_or_create(
                liegenschaft=lg, bezeichnung="1.5 Zi E2E Vergleich",
                defaults=dict(typ="whg", nettomiete_aktuell=Decimal("900"), nebenkosten_aktuell=Decimal("100"),
                              flaeche_m2=Decimal("35")))
            v, _ = Mietvertrag.objects.get_or_create(
                mieter=m, einheit=e,
                defaults=dict(beginn=date(2021, 4, 1), netto_mietzins=Decimal("900"), nebenkosten=Decimal("100"),
                              status="aktiv"))
            if Abnahmeprotokoll.objects.filter(vertrag=v).exists():
                self.stdout.write("seed_e2e_abnahme: schon vorhanden.")
                return
            kats = (("Teppich", "normal"), ("Bodenbelag / Parkett", "io"))
            els = {k: Ausstattung.objects.create(einheit=e, raum="Wohnzimmer", kategorie=k, zustand="gut",
                                                 einbau_datum=date(2018, 5, 1), lebensdauer_jahre=15,
                                                 neuwert=Decimal("2400")) for k, _z in kats}
            ein = Abnahmeprotokoll.objects.create(vertrag=v, typ="einzug", datum=date(2021, 4, 1),
                                                  abgeschlossen=True, verwalter_name="E2E Verwaltung")
            for i, (k, z) in enumerate(kats):
                AbnahmePosition.objects.create(protokoll=ein, raum="Wohnzimmer", bezeichnung=k, ausstattung=els[k],
                                               zustand=z, sortierung=i)
            raumbuch_aktualisieren(ein)
            aus = Abnahmeprotokoll.objects.create(vertrag=v, typ="auszug", datum=date(2026, 11, 3), vorgaenger=ein,
                                                  verwalter_name="E2E Verwaltung")
            for i, (k, _z) in enumerate(kats):
                AbnahmePosition.objects.create(protokoll=aus, raum="Wohnzimmer", bezeichnung=k, ausstattung=els[k],
                                               zustand="", vorgaenger_position=ein.positionen.get(bezeichnung=k),
                                               sortierung=i)
        self.stdout.write(self.style.SUCCESS("seed_e2e_abnahme: Einzug und offener Auszug angelegt."))
