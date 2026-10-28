"""Gemeinsame Grundlage der Rollen-Tests (Etappe 2: Buchhaltung, Vier-Augen, Betreibung).

Eine Verwaltung A mit je einer Person pro Rolle und einer zweiten Person für die
Rollen, bei denen es auf «zweite Person» ankommt (Vier-Augen-Prinzip). Dazu die
Verwaltung B als Gegenprobe der Mandantentrennung.

Die Konten werden mit `force_login` angemeldet; die Mitgliedschaft trägt die
Rolle, wie im Betrieb (`core.auth.hat_rolle` liest nur sie).
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from ._isolation import MandantenFixture

User = get_user_model()

ROLLEN_A = {
    'inhaber': 'Inhaber',
    'verwalter': 'Verwalter',
    'verwalter2': 'Verwalter',
    'sachbearbeiter': 'Sachbearbeiter',
    'buchhaltung': 'Buchhaltung',
    'buchhaltung2': 'Buchhaltung',
    'lesezugriff': 'Lesezugriff',
    'hauswart': 'Hauswart',
}


class RollenBasis(TestCase):
    """Verwaltung A mit allen Rollen, Verwaltung B daneben."""

    @classmethod
    def setUpTestData(cls):
        from crm.models import Mitgliedschaft

        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        cls.org = cls.a.organisation
        cls.benutzer = {}
        for schluessel, rolle in ROLLEN_A.items():
            if schluessel == 'inhaber':
                u = cls.a.benutzer
                Mitgliedschaft.alle_organisationen.filter(benutzer=u).update(rolle=rolle)
            else:
                u = User.objects.create_user(username=f'a_{schluessel}', password='x',
                                             email=f'{schluessel}@example.ch')
                Mitgliedschaft.alle_organisationen.create(
                    benutzer=u, organisation=cls.org, rolle=rolle)
            cls.benutzer[schluessel] = u

    def client_von(self, schluessel):
        c = Client(raise_request_exception=False)
        c.force_login(self.benutzer[schluessel])
        return c

    def kreditor(self, betrag='800.00', status='freigegeben', **kw):
        """Eine Kreditorenrechnung in Verwaltung A (Standard: freigegeben, zahlbar)."""
        from core.tenancy import organisation_kontext
        from finance.models import KreditorenRechnung
        from datetime import date

        werte = dict(
            lieferant='Muster Handwerk AG', betrag=Decimal(betrag), status=status,
            iban='CH9300762011623852957', liegenschaft=self.a.liegenschaft,
            lieferant_strasse='Werkstrasse', lieferant_hausnummer='4',
            lieferant_plz='8000', lieferant_ort='Zürich', lieferant_land='CH',
            datum=date(2026, 10, 1), faellig_am=date(2026, 11, 1), referenz='R-1')
        werte.update(kw)
        with organisation_kontext(self.org):
            return KreditorenRechnung.objects.create(**werte)
