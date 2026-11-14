"""Aufträge im Hintergrund: anlegen, abarbeiten, Fehler, Absturz, Mandantenkontext, Sicht."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from core.models import Auftrag
from core.services import auftraege
from core.tenancy import aktuelle_organisation
from crm.models import Organisation


@auftraege.auftragsart('test_ok', 'Testart')
def _ok(auftrag, fortschritt):
    fortschritt(50, 'halb')
    return f'fertig mit Kontext {aktuelle_organisation().pk}'


@auftraege.auftragsart('test_fehler', 'Fehlerart')
def _fehler(auftrag, fortschritt):
    raise ValueError('kaputt')


class AblaufTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organisation = Organisation.objects.create(firma='Auftragsverwaltung AG')

    def test_ein_auftrag_laeuft_im_kontext_seiner_organisation_und_endet_fertig(self):
        a = auftraege.anlegen('test_ok', organisation=self.organisation)
        self.assertEqual(a.zustand, Auftrag.ZUSTAND_WARTET)
        self.assertEqual(auftraege.abarbeiten(), 1)
        a = Auftrag.alle_organisationen.get(pk=a.pk)
        self.assertEqual((a.zustand, a.fortschritt, a.versuche), (Auftrag.ZUSTAND_FERTIG, 100, 1))
        self.assertEqual(a.ergebnis, f'fertig mit Kontext {self.organisation.pk}')
        self.assertIsNotNone(a.beendet_am)

    def test_ein_fehler_endet_im_auftrag_und_haelt_den_lauf_nicht_an(self):
        schlecht = auftraege.anlegen('test_fehler', organisation=self.organisation)
        gut = auftraege.anlegen('test_ok', organisation=self.organisation)
        self.assertEqual(auftraege.abarbeiten(), 2)
        schlecht = Auftrag.alle_organisationen.get(pk=schlecht.pk)
        self.assertEqual(schlecht.zustand, Auftrag.ZUSTAND_FEHLER)
        self.assertIn('kaputt', schlecht.fehler)
        self.assertEqual(Auftrag.alle_organisationen.get(pk=gut.pk).zustand, Auftrag.ZUSTAND_FERTIG)

    def test_eine_unbekannte_art_wird_beim_anlegen_abgewiesen(self):
        with self.assertRaises(auftraege.UnbekannteArt):
            auftraege.anlegen('gibt_es_nicht', organisation=self.organisation)

    def test_ohne_organisation_wird_nichts_angelegt(self):
        with self.assertRaises(ValueError):
            auftraege.anlegen('test_ok')

    def test_ein_gesperrtes_abo_fuehrt_keine_hintergrundarbeit_aus(self):
        a = auftraege.anlegen('test_ok', organisation=self.organisation)
        with mock.patch('core.funktionen.hintergrund_erlaubt', return_value=False):
            auftraege.abarbeiten()
        a = Auftrag.alle_organisationen.get(pk=a.pk)
        self.assertEqual(a.zustand, Auftrag.ZUSTAND_FEHLER)
        self.assertIn('Abonnement', a.fehler)

    def test_ein_abgestuerzter_auftrag_wartet_erneut_und_nach_drei_versuchen_nicht_mehr(self):
        a = auftraege.anlegen('test_ok', organisation=self.organisation)
        alt = timezone.now() - timedelta(minutes=auftraege.LAEUFT_HOECHSTENS_MINUTEN + 5)
        Auftrag.alle_organisationen.filter(pk=a.pk).update(zustand=Auftrag.ZUSTAND_LAEUFT, gestartet_am=alt, versuche=1)
        auftraege._abgestuerzte_wieder_einreihen(timezone.now())
        self.assertEqual(Auftrag.alle_organisationen.get(pk=a.pk).zustand, Auftrag.ZUSTAND_WARTET)
        Auftrag.alle_organisationen.filter(pk=a.pk).update(zustand=Auftrag.ZUSTAND_LAEUFT, gestartet_am=alt,
                                                           versuche=auftraege.MAX_VERSUCHE)
        auftraege._abgestuerzte_wieder_einreihen(timezone.now())
        self.assertEqual(Auftrag.alle_organisationen.get(pk=a.pk).zustand, Auftrag.ZUSTAND_FEHLER)

    def test_ein_frisch_laufender_auftrag_wird_nicht_angefasst(self):
        a = auftraege.anlegen('test_ok', organisation=self.organisation)
        Auftrag.alle_organisationen.filter(pk=a.pk).update(zustand=Auftrag.ZUSTAND_LAEUFT, gestartet_am=timezone.now())
        auftraege._abgestuerzte_wieder_einreihen(timezone.now())
        self.assertEqual(Auftrag.alle_organisationen.get(pk=a.pk).zustand, Auftrag.ZUSTAND_LAEUFT)
        self.assertEqual(auftraege.abarbeiten(), 0)

    def test_die_grenze_beschraenkt_einen_durchlauf(self):
        for _i in range(3):
            auftraege.anlegen('test_ok', organisation=self.organisation)
        self.assertEqual(auftraege.abarbeiten(grenze=2), 2)
        self.assertEqual(Auftrag.alle_organisationen.filter(zustand=Auftrag.ZUSTAND_WARTET).count(), 1)

    def test_die_sollstellung_ist_eine_bekannte_art(self):
        self.assertIn('sollstellung', auftraege.ARTEN)
        self.assertIn('Sollstellung', str(auftraege.bezeichnung('sollstellung')))


class SeiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.tests._isolation import MandantenFixture
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        cls.org_a, cls.org_b = cls.a.organisation, cls.b.organisation
        Auftrag.alle_organisationen.create(organisation=cls.org_a, art='sollstellung', zustand='fehler',
                                           fehler='Konto fehlt in A')
        Auftrag.alle_organisationen.create(organisation=cls.org_b, art='sollstellung', zustand='fehler',
                                           fehler='Konto fehlt in B')

    def test_die_seite_zeigt_nur_die_auftraege_der_eigenen_verwaltung(self):
        from crm.models import Mitgliedschaft
        m = Mitgliedschaft.alle_organisationen.filter(organisation=self.org_a).first()
        self.assertIsNotNone(m, 'Das Fixture legt kein Mitglied an.')
        self.client.force_login(m.benutzer)
        antwort = self.client.get('/neu/auftraege/')
        self.assertEqual(antwort.status_code, 200)
        inhalt = antwort.content.decode()
        self.assertIn('Konto fehlt in A', inhalt)
        self.assertNotIn('Konto fehlt in B', inhalt)

    def test_ohne_anmeldung_keine_seite(self):
        self.assertEqual(self.client.get('/neu/auftraege/').status_code, 302)
