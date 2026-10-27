"""Zusätzliche Testdaten für `e2e/tests/index-assistent.spec.ts` und `e2e/tests/staffel-mitteilung.spec.ts`.

Läuft NACH `seed_e2e` (siehe `e2e/run-server.sh`), idempotent, nur mit E2E-Datenbank gedacht.

* Ein Indexvertrag (Mieterin «Ida Indexmiete», Basis-LIK 100.0, Kanton ZH = Originalformular da)
  und ein zweiter ohne Kantonsoriginal (Mieterin «Ilse Indexluecke», Kanton LU).
* Ein Staffelvertrag («Sven Staffel») mit zwei Stufen: die erste liegt im Mitteilungsfenster,
  die zweite noch nicht. Die Daten liegen RELATIV zu heute.

Eigene Liegenschaften, damit die übrigen Specs (Vertrags-Assistent, Listen) ihre Auswahl behalten.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone


def _monat_plus(d, n):
    m0 = d.month - 1 + n
    return date(d.year + m0 // 12, m0 % 12 + 1, 1)


class Command(BaseCommand):
    help = "E2E: Index- und Staffelverträge für die Mietzins-Specs."

    def handle(self, *args, **options):
        from core.tenancy import organisation_kontext
        from crm.models import Mieter, Organisation
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag, Staffelstufe

        org = Organisation.objects.get(firma="E2E Verwaltung AG")
        heute = timezone.localdate()
        with organisation_kontext(org):
            def vertrag(strasse, kanton, einheit, vorname, nachname, **felder):
                lg, _ = Liegenschaft.objects.get_or_create(
                    strasse=strasse, plz="8000", ort="Zürich",
                    defaults=dict(versicherungswert=Decimal("1000000"), kanton=kanton))
                e, _ = Einheit.objects.get_or_create(
                    liegenschaft=lg, bezeichnung=einheit,
                    defaults=dict(typ="whg", nettomiete_aktuell=Decimal("2000"),
                                  nebenkosten_aktuell=Decimal("250"), flaeche_m2=Decimal("90")))
                m, _ = Mieter.objects.get_or_create(
                    email=f"{nachname.lower()}@example.ch",
                    defaults=dict(typ="person", vorname=vorname, nachname=nachname,
                                  strasse="Seeweg 3", plz="8000", ort="Zürich"))
                v, neu = Mietvertrag.objects.get_or_create(
                    mieter=m, einheit=e,
                    defaults=dict(status="aktiv", nebenkosten=Decimal("250"), **felder))
                return v, neu

            index_felder = dict(
                beginn=date(2024, 1, 1), ist_befristet=True, ende=date(2031, 12, 31),
                netto_mietzins=Decimal("2000.00"), mietzins_modell="index",
                basis_lik_punkte=Decimal("100.0"), basis_lik_stand=date(2020, 12, 1),
                index_weitergabe_prozent=Decimal("100.0"), index_intervall_monate=12)
            vertrag("E2E-Zinsweg 9", "ZH", "Index E2E", "Ida", "Indexmiete", **index_felder)
            vertrag("E2E-Zinsweg 11", "LU", "Index Luecke E2E", "Ilse", "Indexluecke", **index_felder)

            v, neu = vertrag("E2E-Zinsweg 13", "ZH", "Staffel E2E", "Sven", "Staffel",
                             beginn=date(2026, 1, 1), ist_befristet=True, ende=date(2031, 12, 31),
                             netto_mietzins=Decimal("1500.00"), mietzins_modell="staffel")
            if neu or not Staffelstufe.objects.filter(vertrag=v).exists():
                # Erste Stufe in drei Monaten: ihr Fenster (vier Monate davor) ist offen.
                # Zweite Stufe in 15 Monaten: noch nicht im Fenster.
                Staffelstufe.objects.create(vertrag=v, ab_datum=_monat_plus(heute, 3),
                                            netto_mietzins=Decimal("1550.00"), erhoehung_chf=Decimal("50.00"))
                Staffelstufe.objects.create(vertrag=v, ab_datum=_monat_plus(heute, 15),
                                            netto_mietzins=Decimal("1600.00"), erhoehung_chf=Decimal("50.00"))
        self.stdout.write("Mietzins-Seed: Index- und Staffelverträge bereit.")
