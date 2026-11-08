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
