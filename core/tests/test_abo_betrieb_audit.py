"""Abo und Betrieb (Audit K4–K7).

K4  Eine rückdatierte Zahlung öffnet eine gesperrte Verwaltung nicht.
K5  Bei Bestandsschutz stellt auch der Tageslauf keine Rechnung (wie in der Kundenliste des Betreibers).
K6  Ein arbeitender Läufer gilt als lebendig, auch wenn der Auftrag länger als der Puls-Zeitraum dauert.
K7  Die Mandantenwahl gilt für alle angezeigten Verwaltungen, nicht nur für die ältesten fünf.
"""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from abo import dienst
from abo.models import AboRechnung
from abo.test_zahlungsausfall import HEUTE, Basis, _abo, _ueberfaellig
from core.middleware_tenancy import SESSION_SCHLUESSEL, _organisation_fuer


class RueckdatierteZahlungTests(Basis):

    def test_rueckdatierte_zahlung_oeffnet_die_gesperrte_verwaltung_nicht(self):
        _abo(self.a)
        org = self.a.organisation
        alte = _ueberfaellig(self.a, settings.ABO_LESEMODUS_NACH_TAGEN + 3)      # längst überfällig
        juengere = _ueberfaellig(self.a, 5)
        with mock.patch('abo.dienst.datum_heute', return_value=HEUTE):
            self.assertEqual(dienst.zustand_aktualisieren(org, HEUTE)[1], 'lesemodus')
            # Die jüngere Rechnung wird mit einem Datum bezahlt, das VOR der Fälligkeit der alten liegt.
            dienst.als_bezahlt(juengere, alte.faellig_am - timedelta(days=30))
        self.assertEqual(type(org).objects.get(pk=org.pk).abonnement.zustand, 'lesemodus',
                         'Die rückdatierte Zahlung hat die gesperrte Verwaltung geöffnet.')

    def test_gegenprobe_zahlung_der_aeltesten_oeffnet(self):
        _abo(self.a)
        org = self.a.organisation
        alte = _ueberfaellig(self.a, settings.ABO_LESEMODUS_NACH_TAGEN + 3)
        with mock.patch('abo.dienst.datum_heute', return_value=HEUTE):
            dienst.zustand_aktualisieren(org, HEUTE)
            dienst.als_bezahlt(alte, HEUTE)
        self.assertEqual(type(org).objects.get(pk=org.pk).abonnement.zustand, 'aktiv')


class BestandsschutzAbrechnungTests(Basis):

    def test_bestandsschutz_stellt_keine_rechnung_auch_mit_abrechnungsbeginn(self):
        abo = _abo(self.a, uneingeschraenkt=True, abrechnung_ab=HEUTE - timedelta(days=10))
        org = self.a.organisation
        self.assertIsNone(dienst.rechnung_stellen(org, abo, HEUTE, trotz_platzhalter=True))
        self.assertFalse(AboRechnung.alle_organisationen.filter(organisation=org).exists())

    def test_gegenprobe_ohne_bestandsschutz_wird_gestellt(self):
        abo = _abo(self.a, uneingeschraenkt=False, abrechnung_ab=HEUTE - timedelta(days=10))
        org = self.a.organisation
        self.assertIsNotNone(dienst.rechnung_stellen(org, abo, HEUTE, trotz_platzhalter=True))


class LaeuferPulsTests(TestCase):

    def test_ein_arbeitender_auftrag_haelt_den_puls_aufrecht(self):
        from core.services import auftraege
        cache.delete(auftraege.PULS_SCHLUESSEL)
        self.assertFalse(auftraege.laeufer_aktiv())
        auftraege._lebenszeichen_geben(SimpleNamespace(pk=99, versuche=1, gestartet_am=None))
        self.assertTrue(auftraege.laeufer_aktiv(), 'Ein arbeitender Läufer gilt als abgestürzt (K6).')


class MandantenwahlSechsteTests(TestCase):

    def test_die_sechste_verwaltung_ist_waehlbar(self):
        from core.tests._isolation import MandantenFixture
        from crm.models import Mitgliedschaft, Organisation
        a = MandantenFixture('A', '8000', 'Zürich')
        weitere = []
        for i in range(5):
            o = Organisation.objects.create(firma=f'Verwaltung {i} AG', strasse='Weg 1', plz='6000', ort='Luzern')
            Mitgliedschaft.alle_organisationen.create(
                benutzer=a.benutzer, organisation=o, rolle=Mitgliedschaft.ROLLE_VERWALTER)
            weitere.append(o)
        sechste = weitere[-1]
        ergebnis = _organisation_fuer(a.benutzer, {SESSION_SCHLUESSEL: sechste.id})
        self.assertEqual(ergebnis.id, sechste.id, 'Die sechste Verwaltung wurde ignoriert (K7).')

    def test_gegenprobe_fremde_verwaltung_bleibt_gesperrt(self):
        from core.tests._isolation import MandantenFixture
        from crm.models import Mitgliedschaft, Organisation
        a, b = MandantenFixture('A', '8000', 'Zürich'), MandantenFixture('B', '3000', 'Bern')
        for i in range(5):
            o = Organisation.objects.create(firma=f'Verwaltung {i} AG', strasse='Weg 1', plz='6000', ort='Luzern')
            Mitgliedschaft.alle_organisationen.create(
                benutzer=a.benutzer, organisation=o, rolle=Mitgliedschaft.ROLLE_VERWALTER)
        ergebnis = _organisation_fuer(a.benutzer, {SESSION_SCHLUESSEL: b.organisation.id})
        self.assertNotEqual(ergebnis.id, b.organisation.id)
