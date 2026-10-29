"""Gemeinsame Grundlage der Rollen-Tests (Etappe 2: Buchhaltung, Vier-Augen, Betreibung).

Eine Verwaltung A mit je einer Person pro Rolle und einer zweiten Person für die
Rollen, bei denen es auf «zweite Person» ankommt (Vier-Augen-Prinzip). Dazu die
Verwaltung B als Gegenprobe der Mandantentrennung.

Die Konten werden mit `force_login` angemeldet; die Mitgliedschaft trägt die
Rolle, wie im Betrieb (`core.auth.hat_rolle` liest nur sie).
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase

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


def _aufbau(ziel):
    """Legt Verwaltung A (alle Rollen) und B an und hängt sie an `ziel` (Klasse oder Instanz)."""
    from crm.models import Mitgliedschaft

    ziel.a = MandantenFixture('A', '8000', 'Zürich')
    ziel.b = MandantenFixture('B', '3000', 'Bern')
    ziel.org = ziel.a.organisation
    ziel.benutzer = {}
    for schluessel, rolle in ROLLEN_A.items():
        if schluessel == 'inhaber':
            u = ziel.a.benutzer      # das Fixture legt ihn als Inhaber an
        else:
            u = User.objects.create_user(username=f'a_{schluessel}', password='x',
                                         email=f'{schluessel}@example.ch')
            Mitgliedschaft.alle_organisationen.create(
                benutzer=u, organisation=ziel.org, rolle=rolle)
        ziel.benutzer[schluessel] = u


class _Werkzeug:
    """Bausteine für beide Basisklassen."""

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


class RollenBasis(_Werkzeug, TestCase):
    """Verwaltung A mit allen Rollen, Verwaltung B daneben (Daten je Klasse, Rollback je Test)."""

    @classmethod
    def setUpTestData(cls):
        _aufbau(cls)


class RollenBasisTransaktion(_Werkzeug, TransactionTestCase):
    """Wie `RollenBasis`, aber ohne umschliessende Transaktion: Für Tests mit echten Threads
    (eigene Datenbankverbindung je Thread), die die Daten committed sehen müssen."""

    def setUp(self):
        _aufbau(self)
