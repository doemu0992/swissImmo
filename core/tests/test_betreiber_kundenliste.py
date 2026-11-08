"""Betreiber-Konsole, Etappe 1: die Kundenliste ist nur für den Betreiber, sieht alle Verwaltungen und nennt Befunde."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from abo.models import Abonnement
from core.services import betreiber
from crm.models import Organisation

from ._helfer import _team_user, _test_organisation

URL = '/neu/betreiber/'


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
        Abonnement.alle_organisationen.create(organisation=self.zweite)
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
        self.assertEqual(team.get('/neu/betreiber/neu/').status_code, 403)
        self.assertEqual(team.post('/neu/betreiber/neu/', self.daten).status_code, 403)
        self.assertFalse(Organisation.objects.filter(firma='Neue Verwaltung AG').exists())

    def test_anlegen_macht_organisation_inhaber_abo_kontenplan_und_mail(self):
        from django.core import mail

        from core.tenancy import organisation_kontext
        from crm.models import Mitgliedschaft
        from finance.models import Buchungskonto
        antwort = self.c.post('/neu/betreiber/neu/', self.daten)
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
        self.c.post('/neu/betreiber/neu/', self.daten)
        org = Organisation.objects.get(firma='Neue Verwaltung AG')
        with organisation_kontext(org):
            self.assertTrue(AktivitaetsLog.objects.filter(aktion='Kunde angelegt').exists())

    def test_fehlende_angaben_legen_nichts_an(self):
        antwort = self.c.post('/neu/betreiber/neu/', {**self.daten, 'email': ''})
        self.assertEqual(antwort.status_code, 200)
        self.assertFalse(Organisation.objects.filter(firma='Neue Verwaltung AG').exists())
        self.assertFalse(get_user_model().objects.filter(username='neuinhaber').exists())
