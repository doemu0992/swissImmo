"""Deterministische Testdaten für die e2e-Spec zur Funktionsfreigabe (nur für die E2E-Datenbank).

Zwei eigene Verwaltungen, damit die übrigen Specs nicht berührt werden:

* «E2E Abo Start AG», Login `e2e-abo` / `e2e-pass`: Stufe Start (Module gesperrt), Inhaber.
* «E2E Abo Lesemodus AG», Login `e2e-lese` / `e2e-pass`: Zahlung lange überfällig (Lesemodus).
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.tenancy import organisation_kontext
from core.zeit import datum_heute

PASSWORT = 'e2e-pass'


class Command(BaseCommand):
    help = 'Legt zwei Verwaltungen für die e2e-Spec zur Funktionsfreigabe an (idempotent).'

    def handle(self, *args, **opts):
        from abo.dienst import abonnement_anlegen, zustand_aktualisieren
        from abo.models import AboRechnung
        from crm.models import Mitgliedschaft, Organisation
        from portfolio.models import Liegenschaft

        Benutzer = get_user_model()
        heute = datum_heute()
        for firma, benutzername, lesemodus in (('E2E Abo Start AG', 'e2e-abo', False),
                                               ('E2E Abo Lesemodus AG', 'e2e-lese', True)):
            org, _neu = Organisation.objects.get_or_create(
                firma=firma, defaults=dict(strasse='Abostrasse 1', plz='8000', ort='Zürich',
                                           email=f'{benutzername}@example.ch'))
            org.abo_plan = 'start'
            org.save(update_fields=['abo_plan'])
            abo = abonnement_anlegen(org)
            user, _n = Benutzer.objects.get_or_create(username=benutzername, defaults=dict(email=f'{benutzername}@example.ch'))
            user.set_password(PASSWORT)
            user.is_active = True
            user.save()
            with organisation_kontext(org):
                Mitgliedschaft.objects.get_or_create(
                    benutzer=user, organisation=org, defaults=dict(rolle=Mitgliedschaft.ROLLE_INHABER))
                Liegenschaft.objects.get_or_create(
                    strasse='Abostrasse 7', plz='8000', ort='Zürich',
                    defaults=dict(versicherungswert=Decimal('1000000'), organisation=org))
            if lesemodus:
                AboRechnung.alle_organisationen.get_or_create(
                    organisation=org, periode_von=heute - timedelta(days=90),
                    defaults=dict(periode_bis=heute - timedelta(days=60), stufe='start', intervall='monatlich',
                                  einheiten=1, netto=Decimal('39'), brutto=Decimal('39'),
                                  rechnungsdatum=heute - timedelta(days=90), faellig_am=heute - timedelta(days=60),
                                  platzhalter=True))
                zustand_aktualisieren(org, heute)
            del abo
        self.stdout.write(self.style.SUCCESS('E2E-Seed Abo bereit: e2e-abo (Start), e2e-lese (Lesemodus) / e2e-pass.'))
