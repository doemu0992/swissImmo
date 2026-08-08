"""Deterministischer Datensatz für die Playwright-E2E-Tests.

Legt einen bekannten Verwaltungs-Login (e2e / e2e-pass) plus eine kleine, stabile
Welt an (Liegenschaft, Einheit, Mieter, aktiver Vertrag, offene Debitorenrechnung,
Kontenplan). Idempotent: mehrfaches Ausführen ändert nichts Zusätzliches.

NUR für Test-/E2E-Datenbanken gedacht — nie gegen Produktion laufen lassen.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seedet einen deterministischen Datensatz für die Playwright-E2E-Tests."

    def handle(self, *args, **options):
        from django.contrib.auth.models import User, Group
        from crm.models import Verwaltung, Mieter
        from portfolio.models import Liegenschaft, Einheit
        from rentals.models import Mietvertrag
        from finance.models import DebitorenRechnung
        from finance.booking import ensure_kontenplan

        ensure_kontenplan()

        grp, _ = Group.objects.get_or_create(name="Verwaltung")
        user, created = User.objects.get_or_create(
            username="e2e", defaults={"is_staff": True})
        user.set_password("e2e-pass")
        user.is_active = True
        user.save()
        user.groups.add(grp)

        Verwaltung.objects.get_or_create(
            firma="E2E Verwaltung AG",
            defaults=dict(strasse="Teststrasse 1", plz="8000", ort="Zürich",
                          iban="CH9300762011623852957"))

        lg, _ = Liegenschaft.objects.get_or_create(
            strasse="E2E-Weg 1", plz="8000", ort="Zürich",
            defaults=dict(versicherungswert=Decimal("1000000")))
        e, _ = Einheit.objects.get_or_create(
            liegenschaft=lg, bezeichnung="3.5 Zi E2E",
            defaults=dict(typ="wohnung", nettomiete_aktuell=Decimal("1500"),
                          nebenkosten_aktuell=Decimal("200"), flaeche_m2=Decimal("80")))
        m, _ = Mieter.objects.get_or_create(
            email="e2e-mieter@example.ch",
            defaults=dict(typ="person", vorname="Erika", nachname="E2E",
                          strasse="Seeweg 3", plz="8000", ort="Zürich"))
        v, _ = Mietvertrag.objects.get_or_create(
            mieter=m, einheit=e,
            defaults=dict(beginn=date(2024, 1, 1), netto_mietzins=Decimal("1500"),
                          nebenkosten=Decimal("200"), status="aktiv",
                          kautions_betrag=Decimal("4500")))

        DebitorenRechnung.objects.get_or_create(
            vertrag=v, titel="E2E offene Miete",
            defaults=dict(liegenschaft=lg, einheit=e, datum=date(2024, 5, 1),
                          faellig_am=date(2024, 5, 5), betrag=Decimal("1700"),
                          status="offen"))

        # Eine Erfolgsbuchung im Jahr 2024, damit Erfolgsrechnung/Jahresabschluss
        # in der E2E-Welt etwas zu zeigen/abzuschliessen haben.
        from finance.models import Buchung
        if not Buchung.objects.filter(beleg_text="E2E Mietertrag 2024").exists():
            from finance.booking import buche
            buche("1100", "3000", Decimal("1500"), "E2E Mietertrag 2024",
                  datum=date(2024, 1, 31), liegenschaft=lg)

        self.stdout.write(self.style.SUCCESS(
            "E2E-Seed bereit: Login e2e / e2e-pass · 1 Liegenschaft, 1 Vertrag, 1 offene Rechnung."))
