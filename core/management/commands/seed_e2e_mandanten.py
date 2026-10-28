"""Zusätzliche Testdaten für `e2e/tests/profilmenue-mandant.spec.ts`.

Läuft NACH `seed_e2e` (siehe `e2e/run-server.sh`), idempotent, nur mit E2E-Datenbank gedacht.

* Der Benutzer `e2e-zwei` (Passwort `e2e-pass`) arbeitet für zwei Verwaltungen: «E2E Verwaltung AG»
  (die älteste, gilt ohne Auswahl) und eine zweite mit absichtlich sehr langem Namen — er prüft, dass
  das Profilmenü bei 390 px nicht aus dem Bild läuft.
* In der zweiten Verwaltung liegt eine eigene Liegenschaft, damit nach dem Wechsel sichtbar ist, in
  welchem Mandanten man steht.

Der Benutzer `e2e` bleibt bei einer Organisation (dort darf es keine Auswahl geben).
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

ZWEITE_FIRMA = "Zweite Verwaltung mit sehr langem Namen für den Telefontest und die Ellipse AG"
ZWEITE_STRASSE = "Mandantenweg 7"


class Command(BaseCommand):
    help = "E2E: Benutzer mit zwei Mitgliedschaften für das Profilmenü."

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        from core.tenancy import organisation_kontext
        from crm.models import Mitgliedschaft, Organisation
        from portfolio.models import Liegenschaft

        User = get_user_model()
        erste = Organisation.objects.get(firma="E2E Verwaltung AG")
        zweite, _ = Organisation.objects.get_or_create(
            firma=ZWEITE_FIRMA,
            defaults=dict(strasse="Zweitweg 2", plz="3000", ort="Bern", iban="CH9300762011623852957"))

        grp, _ = Group.objects.get_or_create(name="Verwalter")
        user, _ = User.objects.get_or_create(username="e2e-zwei", defaults={"is_staff": True})
        user.set_password("e2e-pass")
        user.is_active = True
        user.save()
        user.groups.add(grp)

        # Reihenfolge ist Absicht: Ohne Auswahl nimmt die Middleware die älteste Mitgliedschaft.
        for org in (erste, zweite):
            with organisation_kontext(org):
                Mitgliedschaft.objects.get_or_create(
                    benutzer=user, organisation=org,
                    defaults=dict(rolle=Mitgliedschaft.ROLLE_VERWALTER))
        with organisation_kontext(zweite):
            Liegenschaft.objects.get_or_create(
                strasse=ZWEITE_STRASSE, plz="3000", ort="Bern",
                defaults=dict(versicherungswert=Decimal("1000000")))

        self.stdout.write(self.style.SUCCESS(
            "E2E-Seed Mandanten bereit: Login e2e-zwei / e2e-pass · zwei Mitgliedschaften."))
