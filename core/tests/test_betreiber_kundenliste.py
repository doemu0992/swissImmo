"""Betreiber-Konsole, Etappe 1: die Kundenliste ist nur für den Betreiber, sieht alle Verwaltungen und nennt Befunde."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from abo.models import Abonnement
from core.services import betreiber
from crm.models import Organisation

from ._helfer import _team_user, _test_organisation

URL = '/betreiber/'


class BetreiberKundenlisteTests(TestCase):

    def setUp(self):
        self.eigene = _test_organisation()
        self.zweite = Organisation.objects.create(firma='Zweite Verwaltung AG', strasse='Weg 2', plz='3000', ort='Bern')
        self.betreiber = get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12)
        self.c = Client()
        self.c.force_login(self.betreiber)

    def test_nur_der_betreiber_kommt_hinein(self):
        team = Client()
        team.force_login(_team_user())
        self.assertEqual(team.get(URL).status_code, 403)          # auch der Inhaber einer Verwaltung nicht
        self.assertEqual(Client().get(URL).status_code, 302)      # nicht angemeldet: zur Anmeldung
        self.assertEqual(self.c.get(URL).status_code, 200)

    def test_alle_verwaltungen_stehen_in_der_liste(self):
        antwort = self.c.get(URL)
        self.assertContains(antwort, 'Zweite Verwaltung AG')
        self.assertContains(antwort, self.eigene.firma)

    def test_befunde_fehlendes_abo_inhaber_und_mail(self):
        kunden = {k.organisation.pk: k for k in betreiber.kunden()}
        k = kunden[self.zweite.pk]
        text = ' '.join(k.befunde)
        self.assertIn('Keine Abonnement-Zeile', text)
        self.assertIn('Kein Inhaber', text)
        self.assertIn('Keine E-Mail-Adresse', text)

    def test_vollstaendige_verwaltung_ohne_befund(self):
        from crm.models import Mitgliedschaft
        self.zweite.email = 'info@zweite.ch'
        self.zweite.save()
        u = get_user_model().objects.create_user('inh', 'i@example.ch', 'x' * 12)
        Mitgliedschaft.alle_organisationen.create(benutzer=u, organisation=self.zweite, rolle=Mitgliedschaft.ROLLE_INHABER)
        Abonnement.alle_organisationen.create(organisation=self.zweite, abrechnung_ab=date(2026, 12, 1))
        k = {k.organisation.pk: k for k in betreiber.kunden()}[self.zweite.pk]
        self.assertEqual(k.befunde, [])

    def test_keine_mieterdaten_in_der_liste(self):
        from ._helfer import _basis_objekte
        _basis_objekte()
        antwort = self.c.get(URL)
        self.assertNotContains(antwort, 'Muster')                 # Name des Test-Mieters
        self.assertNotContains(antwort, 'Teststrasse')            # Adresse der Test-Liegenschaft


class BetreiberKundeAnlegenTests(TestCase):
    """Etappe 2: Kunde anlegen über die Oberfläche."""

    def setUp(self):
        _test_organisation()
        self.betreiber = get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12)
        self.c = Client()
        self.c.force_login(self.betreiber)
        self.daten = {'firma': 'Neue Verwaltung AG', 'benutzer': 'neuinhaber', 'email': 'neu@example.ch',
                      'vorname': 'Nora', 'nachname': 'Neu'}

    def test_nur_der_betreiber(self):
        team = Client()
        team.force_login(_team_user())
        self.assertEqual(team.get('/betreiber/neu/').status_code, 403)
        self.assertEqual(team.post('/betreiber/neu/', self.daten).status_code, 403)
        self.assertFalse(Organisation.objects.filter(firma='Neue Verwaltung AG').exists())

    def test_anlegen_macht_organisation_inhaber_abo_kontenplan_und_mail(self):
        from django.core import mail

        from core.tenancy import organisation_kontext
        from crm.models import Mitgliedschaft
        from finance.models import Buchungskonto
        antwort = self.c.post('/betreiber/neu/', self.daten)
        self.assertEqual(antwort.status_code, 302)
        org = Organisation.objects.get(firma='Neue Verwaltung AG')
        self.assertEqual(org.email, 'neu@example.ch')                        # Rechnungen gehen nicht ins Leere
        self.assertTrue(Abonnement.alle_organisationen.filter(organisation=org).exists())
        self.assertEqual(Mitgliedschaft.alle_organisationen.filter(organisation=org, rolle='Inhaber').count(), 1)
        with organisation_kontext(org):
            self.assertTrue(Buchungskonto.objects.exists())                  # Kontenplan von Anfang an
        inhaber = get_user_model().objects.get(username='neuinhaber')
        self.assertFalse(inhaber.has_usable_password())                      # kein Passwort vom Betreiber
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['neu@example.ch'])

    def test_logbuch_der_neuen_verwaltung(self):
        from core.models import AktivitaetsLog
        from core.tenancy import organisation_kontext
        self.c.post('/betreiber/neu/', self.daten)
        org = Organisation.objects.get(firma='Neue Verwaltung AG')
        with organisation_kontext(org):
            self.assertTrue(AktivitaetsLog.objects.filter(aktion='Kunde angelegt').exists())

    def test_fehlende_angaben_legen_nichts_an(self):
        antwort = self.c.post('/betreiber/neu/', {**self.daten, 'email': ''})
        self.assertEqual(antwort.status_code, 200)
        self.assertFalse(Organisation.objects.filter(firma='Neue Verwaltung AG').exists())
        self.assertFalse(get_user_model().objects.filter(username='neuinhaber').exists())


class BetreiberAboVerwaltungTests(TestCase):
    """Etappe 3: Stufe, Module, Abrechnung, Zahlung und Storno einer Verwaltung."""

    def setUp(self):
        from datetime import date
        from decimal import Decimal

        from abo.models import AboRechnung
        self.org = _test_organisation()
        self.abo = Abonnement.alle_organisationen.get_or_create(organisation=self.org)[0]
        self.rechnung = AboRechnung.alle_organisationen.create(
            organisation=self.org, nummer='AB-2026-000001', periode_von=date(2026, 11, 1), periode_bis=date(2026, 11, 30),
            stufe='team', intervall='monatlich', einheiten=10, netto=Decimal('119'), brutto=Decimal('119'),
            rechnungsdatum=date(2026, 11, 1), faellig_am=date(2026, 11, 30))
        self.betreiber = get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12)
        self.c = Client()
        self.c.force_login(self.betreiber)
        self.url = f'/betreiber/{self.org.pk}/'

    def test_nur_der_betreiber(self):
        team = Client()
        team.force_login(_team_user())
        self.assertEqual(team.get(self.url).status_code, 403)
        self.assertEqual(team.post(self.url, {'aktion': 'bezahlt', 'rechnung': self.rechnung.pk}).status_code, 403)
        self.rechnung.refresh_from_db()
        self.assertEqual(self.rechnung.status, 'offen')
        self.assertEqual(self.c.get(self.url).status_code, 200)

    def test_unbekannte_verwaltung_ist_404(self):
        self.assertEqual(self.c.get('/betreiber/999999/').status_code, 404)

    def test_zahlung_bestaetigen_und_stornieren(self):
        from datetime import date

        from abo.models import AboRechnung
        self.c.post(self.url, {'aktion': 'bezahlt', 'rechnung': self.rechnung.pk, 'datum': '2026-11-05'})
        self.rechnung.refresh_from_db()
        self.assertEqual((self.rechnung.status, str(self.rechnung.bezahlt_am)), ('bezahlt', '2026-11-05'))
        # eine bezahlte Rechnung lässt sich nicht mehr stornieren
        self.c.post(self.url, {'aktion': 'storno', 'rechnung': self.rechnung.pk})
        self.rechnung.refresh_from_db()
        self.assertEqual(self.rechnung.status, 'bezahlt')
        zweite = AboRechnung.alle_organisationen.get(pk=self.rechnung.pk)
        zweite.pk, zweite.nummer, zweite.status, zweite.bezahlt_am = None, 'AB-2026-000002', 'offen', None
        zweite.periode_von, zweite.periode_bis = date(2026, 12, 1), date(2026, 12, 31)
        zweite.save()
        self.c.post(self.url, {'aktion': 'storno', 'rechnung': zweite.pk})
        zweite.refresh_from_db()
        self.assertEqual(zweite.status, 'storniert')

    def test_fremde_rechnung_wird_abgelehnt(self):
        from datetime import date
        from decimal import Decimal

        from abo.models import AboRechnung
        andere = Organisation.objects.create(firma='Andere AG', strasse='x', plz='1', ort='y')
        fremd = AboRechnung.alle_organisationen.create(
            organisation=andere, nummer='AB-2026-000099', periode_von=date(2026, 11, 1), periode_bis=date(2026, 11, 30),
            stufe='team', intervall='monatlich', einheiten=1, netto=Decimal('1'), brutto=Decimal('1'),
            rechnungsdatum=date(2026, 11, 1), faellig_am=date(2026, 11, 30))
        self.c.post(self.url, {'aktion': 'bezahlt', 'rechnung': fremd.pk})
        fremd.refresh_from_db()
        self.assertEqual(fremd.status, 'offen')                      # über die falsche Verwaltung geht nichts

    def test_module_abrechnung_und_bestandsschutz_speichern(self):
        self.c.post(self.url, {'aktion': 'einstellen', 'module': ['signatur', 'unsinn'], 'abrechnung_ab': '2026-12-01',
                               'bestandsschutz': 'on'})
        self.abo.refresh_from_db()
        self.assertEqual(self.abo.zusatzmodule, ['signatur'])               # Unbekanntes wird verworfen
        self.assertEqual(str(self.abo.abrechnung_ab), '2026-12-01')
        self.assertTrue(self.abo.uneingeschraenkt)

    def test_planwechsel_zeigt_folgen_und_verlangt_bestaetigung(self):
        self.abo.uneingeschraenkt = False
        self.abo.save()
        self.org.abo_plan = 'professional'
        self.org.save(update_fields=['abo_plan'])
        antwort = self.c.post(self.url, {'aktion': 'plan', 'stufe': 'start', 'intervall': 'monatlich'})
        self.assertContains(antwort, 'Trotzdem wechseln')
        self.org.refresh_from_db()
        self.assertEqual(self.org.abo_plan, 'professional')                 # noch nichts geändert
        self.c.post(self.url, {'aktion': 'plan', 'stufe': 'start', 'intervall': 'jaehrlich', 'bestaetigt': '1'})
        self.org.refresh_from_db()
        self.assertEqual((self.org.abo_plan, self.org.abo_jaehrlich), ('start', True))

    def test_aenderungen_stehen_im_logbuch_der_verwaltung(self):
        from core.models import AktivitaetsLog
        from core.tenancy import organisation_kontext
        self.c.post(self.url, {'aktion': 'bezahlt', 'rechnung': self.rechnung.pk})
        with organisation_kontext(self.org):
            self.assertTrue(AktivitaetsLog.objects.filter(aktion='Zahlung bestätigt').exists())


class BetreiberPortalTests(TestCase):
    """Das Betreiber-Portal ist ein eigener Bereich wie das Eigentümer- und das Mieterportal."""

    def setUp(self):
        _test_organisation()

    def test_betreiberkonto_ohne_mitgliedschaft_landet_im_betreiber_portal(self):
        u = get_user_model().objects.create_superuser('nur_betreiber', 'n@example.ch', 'x' * 12)
        c = Client()
        c.force_login(u)
        self.assertRedirects(c.get('/nach-login/'), '/betreiber/', fetch_redirect_response=False)

    def test_superuser_mit_mitgliedschaft_bleibt_in_der_verwaltung(self):
        from crm.models import Mitgliedschaft
        u = get_user_model().objects.create_superuser('beides', 'bb@example.ch', 'x' * 12)
        Mitgliedschaft.alle_organisationen.create(benutzer=u, organisation=_test_organisation(), rolle='Inhaber')
        c = Client()
        c.force_login(u)
        self.assertEqual(c.get('/nach-login/')['Location'], '/neu/')

    def test_das_portal_zeigt_keine_verwaltungs_navigation_und_keine_adressen(self):
        from ._helfer import _basis_objekte
        _basis_objekte()
        u = get_user_model().objects.create_superuser('nur_betreiber', 'n@example.ch', 'x' * 12)
        c = Client()
        c.force_login(u)
        for url in ('/betreiber/', '/betreiber/sicherheit/', '/betreiber/neu/'):
            antwort = c.get(url)
            self.assertEqual(antwort.status_code, 200, url)
            self.assertContains(antwort, 'pSidebar')              # Hülle der Portale
            self.assertNotContains(antwort, 'Ganzer Bestand')     # kein Bestandsfilter der Verwaltung
            self.assertNotContains(antwort, 'Teststrasse')

    def test_login_seite_ist_erreichbar(self):
        self.assertEqual(Client().get('/betreiber/login/').status_code, 200)


class BetreiberTestphaseTests(TestCase):
    """«Abrechnung ab» ist das Ende der Testphase: gesetzt beim Anlegen, sichtbar, und Pflichtbefund, wenn leer."""

    def setUp(self):
        _test_organisation()
        self.c = Client()
        self.c.force_login(get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12))
        self.daten = {'firma': 'Testphase AG', 'benutzer': 'tp_inhaber', 'email': 'tp@example.ch'}

    def test_beim_anlegen_wird_das_ende_der_testphase_gesetzt(self):
        self.c.post('/betreiber/neu/', {**self.daten, 'abrechnung_ab': '2026-12-15'})
        org = Organisation.objects.get(firma='Testphase AG')
        self.assertEqual(str(Abonnement.alle_organisationen.get(organisation=org).abrechnung_ab), '2026-12-15')
        self.assertContains(self.c.get('/betreiber/'), '15.12.2026')

    def test_ohne_datum_gibt_es_den_befund(self):
        self.c.post('/betreiber/neu/', self.daten)
        org = Organisation.objects.get(firma='Testphase AG')
        k = {k.organisation.pk: k for k in betreiber.kunden()}[org.pk]
        self.assertTrue(any('Abrechnung ab' in b for b in k.befunde))

    def test_ungueltiges_datum_legt_nichts_an(self):
        antwort = self.c.post('/betreiber/neu/', {**self.daten, 'abrechnung_ab': '31.02.xx'})
        self.assertEqual(antwort.status_code, 200)
        self.assertFalse(Organisation.objects.filter(firma='Testphase AG').exists())

    def test_preise_freigegeben_und_mwst_8_1(self):
        from decimal import Decimal

        from django.conf import settings
        self.assertTrue(settings.ABO_PREISE_FESTGELEGT)
        self.assertEqual(settings.ABO_MWST_SATZ, Decimal('8.1'))

    def test_keine_rechnung_vor_ende_der_testphase_dann_mit_mwst(self):
        from datetime import date as d
        from decimal import Decimal

        from abo import dienst
        self.c.post('/betreiber/neu/', {**self.daten, 'abrechnung_ab': '2026-12-01'})
        org = Organisation.objects.get(firma='Testphase AG')
        abo = Abonnement.alle_organisationen.get(organisation=org)
        self.assertIsNone(dienst.rechnung_stellen(org, abo, heute=d(2026, 11, 20)))     # noch Testphase
        rechnung = dienst.rechnung_stellen(org, abo, heute=d(2026, 12, 1))
        self.assertIsNotNone(rechnung)
        self.assertEqual(rechnung.mwst_satz, Decimal('8.1'))
        self.assertEqual(rechnung.netto, Decimal('119'))
        self.assertEqual(rechnung.mwst_betrag, Decimal('9.64'))
