"""Betreiber-Konsole, Etappe 1: die Kundenliste ist nur für den Betreiber, sieht alle Verwaltungen und nennt Befunde."""
from datetime import date

from django.contrib.auth import get_user_model
from django.core import mail
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

    def test_preise_freigegeben_betreiber_nicht_mwst_pflichtig(self):
        from django.conf import settings
        self.assertTrue(settings.ABO_PREISE_FESTGELEGT)
        self.assertFalse(settings.ABO_MWST_PFLICHTIG)
        self.assertIsNone(settings.ABO_MWST_SATZ)

    def test_keine_rechnung_vor_ende_der_testphase_dann_ohne_mwst(self):
        from datetime import date as d
        from decimal import Decimal

        from abo import dienst
        self.c.post('/betreiber/neu/', {**self.daten, 'abrechnung_ab': '2026-12-01'})
        org = Organisation.objects.get(firma='Testphase AG')
        abo = Abonnement.alle_organisationen.get(organisation=org)
        self.assertIsNone(dienst.rechnung_stellen(org, abo, heute=d(2026, 11, 20)))     # noch Testphase
        rechnung = dienst.rechnung_stellen(org, abo, heute=d(2026, 12, 1))
        self.assertIsNotNone(rechnung)
        self.assertIsNone(rechnung.mwst_satz)                      # nicht mehrwertsteuerpflichtig: keine MWST
        self.assertEqual((rechnung.netto, rechnung.mwst_betrag, rechnung.brutto),
                         (Decimal('119'), Decimal('0.00'), Decimal('119')))


class BetreiberSofortRechnungTests(TestCase):
    """Abo-Rechnungen sind im Voraus zu bezahlen: Ist «Abrechnung ab» erreicht, entsteht die Rechnung sofort."""

    def setUp(self):
        from django.utils import timezone
        self.heute = timezone.localdate()
        self.org = _test_organisation()
        self.abo = Abonnement.alle_organisationen.get_or_create(organisation=self.org)[0]
        self.c = Client()
        self.c.force_login(get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12))
        self.url = f'/betreiber/{self.org.pk}/'

    def _einstellen(self, datum):
        return self.c.post(self.url, {'aktion': 'einstellen', 'abrechnung_ab': datum.isoformat()}, follow=True)

    def test_erreichtes_datum_stellt_die_rechnung_sofort(self):
        from abo.models import AboRechnung
        antwort = self._einstellen(self.heute)
        r = AboRechnung.alle_organisationen.get(organisation=self.org)
        self.assertEqual(r.periode_von, self.heute)
        self.assertEqual(r.rechnungsdatum, self.heute)
        self.assertContains(antwort, r.nummer)
        self.assertContains(antwort, 'fällig am')

    def test_zweites_speichern_stellt_nichts_doppelt(self):
        from abo.models import AboRechnung
        self._einstellen(self.heute)
        self._einstellen(self.heute)
        self.assertEqual(AboRechnung.alle_organisationen.filter(organisation=self.org).count(), 1)

    def test_datum_weit_in_der_zukunft_stellt_nichts(self):
        from datetime import timedelta

        from abo.models import AboRechnung
        self._einstellen(self.heute + timedelta(days=40))
        self.assertFalse(AboRechnung.alle_organisationen.filter(organisation=self.org).exists())

    def test_im_vorlauf_wird_im_voraus_gestellt_und_ist_am_beginn_faellig(self):
        from datetime import timedelta

        from abo.models import AboRechnung
        beginn = self.heute + timedelta(days=5)
        self._einstellen(beginn)
        r = AboRechnung.alle_organisationen.get(organisation=self.org)
        self.assertEqual((r.rechnungsdatum, r.faellig_am), (self.heute, beginn))

    def test_beim_anlegen_eines_kunden_mit_erreichtem_datum(self):
        from abo.models import AboRechnung
        self.c.post('/betreiber/neu/', {'firma': 'Sofort AG', 'benutzer': 'sofort', 'email': 's@example.ch',
                                        'abrechnung_ab': self.heute.isoformat()})
        neu = Organisation.objects.get(firma='Sofort AG')
        self.assertTrue(AboRechnung.alle_organisationen.filter(organisation=neu).exists())


class BetreiberRechnungVersandTests(TestCase):
    """PDF der Abo-Rechnung, erneut senden und Zahlungserinnerung im Betreiber-Portal."""

    STELLER = {'name': 'Plattform AG', 'strasse': 'Bahnhofstrasse 1', 'plz': '8001', 'ort': 'Zürich',
               'iban': 'CH9300762011623852957', 'uid': '', 'email': 'abo@example.ch'}

    def setUp(self):
        from datetime import date
        from decimal import Decimal

        from abo.models import AboRechnung
        self.org = _test_organisation()
        type(self.org).objects.filter(pk=self.org.pk).update(email='verwaltung@example.ch')
        self.org.refresh_from_db()
        Abonnement.alle_organisationen.get_or_create(organisation=self.org)
        self.rechnung = AboRechnung.alle_organisationen.create(
            organisation=self.org, nummer='AB-2026-000001', periode_von=date(2026, 10, 1), periode_bis=date(2026, 10, 31),
            stufe='team', intervall='monatlich', einheiten=10, netto=Decimal('119'), brutto=Decimal('119'),
            rechnungsdatum=date(2026, 10, 1), faellig_am=date(2026, 10, 1))
        self.betreiber = get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12)
        self.c = Client()
        self.c.force_login(self.betreiber)
        self.url = f'/betreiber/{self.org.pk}/'
        self.pdf = f'/betreiber/{self.org.pk}/rechnung/{self.rechnung.pk}/pdf/'
        mail.outbox.clear()

    def test_pdf_nur_fuer_den_betreiber(self):
        from django.test import override_settings
        team = Client()
        team.force_login(_team_user())
        with override_settings(ABO_RECHNUNGSSTELLER=self.STELLER):
            self.assertEqual(team.get(self.pdf).status_code, 403)
            antwort = self.c.get(self.pdf)
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort['Content-Type'], 'application/pdf')
        self.assertTrue(antwort.content.startswith(b'%PDF'))

    def test_pdf_ohne_iban_leitet_mit_hinweis_zurueck(self):
        from django.test import override_settings
        with override_settings(ABO_RECHNUNGSSTELLER={**self.STELLER, 'iban': ''}):
            antwort = self.c.get(self.pdf)
        self.assertRedirects(antwort, self.url, fetch_redirect_response=False)

    def test_pdf_einer_fremden_rechnung_ist_404(self):
        from datetime import date
        from decimal import Decimal

        from abo.models import AboRechnung
        from crm.models import Organisation
        andere = Organisation.objects.create(firma='Andere AG')
        fremd = AboRechnung.alle_organisationen.create(
            organisation=andere, nummer='AB-2026-000099', periode_von=date(2026, 10, 1), periode_bis=date(2026, 10, 31),
            stufe='team', intervall='monatlich', einheiten=1, netto=Decimal('1'), brutto=Decimal('1'),
            rechnungsdatum=date(2026, 10, 1), faellig_am=date(2026, 10, 1))
        self.assertEqual(self.c.get(f'/betreiber/{self.org.pk}/rechnung/{fremd.pk}/pdf/').status_code, 404)

    def test_erneut_senden_schickt_das_pdf(self):
        from django.test import override_settings
        with override_settings(ABO_RECHNUNGSSTELLER=self.STELLER):
            self.c.post(self.url, {'aktion': 'senden', 'rechnung': self.rechnung.pk})
        self.assertEqual(len(mail.outbox), 1)
        nachricht = mail.outbox[0]
        self.assertEqual(nachricht.to, ['verwaltung@example.ch'])
        self.assertIn('AB-2026-000001', nachricht.subject)
        self.assertEqual(nachricht.attachments[0][0], 'AB-2026-000001.pdf')
        self.assertTrue(nachricht.attachments[0][1].startswith(b'%PDF'))
        self.rechnung.refresh_from_db()
        self.assertIsNone(self.rechnung.erinnert_am, 'Erneut senden ist keine Mahnung')

    def test_erinnerung_setzt_das_datum(self):
        from django.test import override_settings
        with override_settings(ABO_RECHNUNGSSTELLER=self.STELLER):
            self.c.post(self.url, {'aktion': 'erinnern', 'rechnung': self.rechnung.pk})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Zahlungserinnerung', mail.outbox[0].subject)
        self.rechnung.refresh_from_db()
        self.assertIsNotNone(self.rechnung.erinnert_am)

    def test_ohne_adresse_oder_iban_geht_nichts_hinaus(self):
        from django.test import override_settings
        with override_settings(ABO_RECHNUNGSSTELLER={**self.STELLER, 'iban': ''}):
            self.c.post(self.url, {'aktion': 'senden', 'rechnung': self.rechnung.pk})
        type(self.org).objects.filter(pk=self.org.pk).update(email='')
        with override_settings(ABO_RECHNUNGSSTELLER=self.STELLER):
            self.c.post(self.url, {'aktion': 'senden', 'rechnung': self.rechnung.pk})
        self.assertEqual(len(mail.outbox), 0)

    def test_bezahlte_rechnung_wird_nicht_mehr_gesendet(self):
        from django.test import override_settings
        from abo import dienst
        dienst.als_bezahlt(self.rechnung)
        with override_settings(ABO_RECHNUNGSSTELLER=self.STELLER):
            self.c.post(self.url, {'aktion': 'senden', 'rechnung': self.rechnung.pk})
        self.assertEqual(len(mail.outbox), 0)

    def test_neue_rechnung_im_lauf_geht_mit_pdf_hinaus(self):
        """Der tägliche Lauf schickt die frisch gestellte Rechnung selbst — kein Warten auf einen Klick."""
        from datetime import date

        from django.test import override_settings
        from abo import dienst
        abo = Abonnement.alle_organisationen.get(organisation=self.org)
        abo.uneingeschraenkt, abo.abrechnung_ab, abo.abgerechnet_bis = False, date(2026, 12, 1), self.rechnung.periode_bis
        abo.save()
        with override_settings(ABO_RECHNUNGSSTELLER=self.STELLER, ABO_PREISE_FESTGELEGT=True):
            bericht = dienst.abrechnen(type(self.org).objects.get(pk=self.org.pk), heute=date(2026, 11, 25))
        self.assertTrue(bericht.get('versandt'), bericht)
        # Daneben geht die Mitteilung zum Zahlungszustand hinaus (die Oktoberrechnung ist überfällig): nur eine Mail trägt das PDF.
        mit_pdf = [m for m in mail.outbox if m.attachments]
        self.assertEqual(len(mit_pdf), 1)
        self.assertEqual(mit_pdf[0].attachments[0][0], f'{bericht["rechnung"]}.pdf')


class BetreiberKundenkarteiTests(TestCase):
    """Kundenkartei im Betreiber-Portal: Stammdaten, Ansprechperson, Verlauf, Finanzen."""

    def setUp(self):
        from datetime import date
        from decimal import Decimal

        from abo.models import AboRechnung
        self.org = _test_organisation()
        Abonnement.alle_organisationen.get_or_create(organisation=self.org)
        self.betreiber = get_user_model().objects.create_superuser('betreiber', 'b@example.ch', 'x' * 12)
        self.c = Client()
        self.c.force_login(self.betreiber)
        self.url = f'/betreiber/{self.org.pk}/'
        self.heute = date(2026, 11, 9)

        def rechnung(nr, von, bis, faellig, status='offen', bezahlt=None, mahn='0'):
            return AboRechnung.alle_organisationen.create(
                organisation=self.org, nummer=nr, periode_von=von, periode_bis=bis, stufe='team', intervall='monatlich',
                einheiten=1, netto=Decimal('100'), brutto=Decimal('100'), rechnungsdatum=von, faellig_am=faellig,
                status=status, bezahlt_am=bezahlt, mahngebuehr=Decimal(mahn))
        self.r_bezahlt = rechnung('AB-1', date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 1), 'bezahlt', date(2026, 8, 6))
        self.r_offen = rechnung('AB-2', date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 1), mahn='20')
        self.r_zukunft = rechnung('AB-3', date(2026, 12, 1), date(2026, 12, 31), date(2026, 12, 1))
        self.r_storno = rechnung('AB-4', date(2026, 7, 1), date(2026, 7, 31), date(2026, 7, 1), 'storniert')

    def _stamm(self, **aenderungen):
        werte = {'aktion': 'stamm', 'firma': 'AlDo Immobilien AG', 'strasse': 'Hauptstrasse 1', 'plz': '4500',
                 'ort': 'Solothurn', 'telefon': '032 111 22 33', 'natel': '079 111 22 33', 'email': 'info@aldo.ch',
                 'website': 'aldo.ch', 'mwst_uid': '', 'status': 'kunde', 'rechnung_email': '',
                 'ansprechperson': 'Anna Muster', 'ansprech_funktion': 'Geschäftsleitung', 'ansprech_email': 'anna@aldo.ch',
                 'ansprech_telefon': '032 111 22 44', 'ansprech_natel': '079 999 88 77', 'notizen': 'zahlt pünktlich'}
        werte.update(aenderungen)
        return self.c.post(self.url, werte)

    def test_die_kartei_entsteht_beim_ersten_oeffnen(self):
        from abo.models import Kundenstamm
        self.assertFalse(Kundenstamm.alle_organisationen.filter(organisation=self.org).exists())
        antwort = self.c.get(self.url)
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, f'K-{self.org.pk:04d}')
        self.assertTrue(Kundenstamm.alle_organisationen.filter(organisation=self.org).exists())

    def test_stammdaten_speichern(self):
        from abo.models import Kundenstamm
        self._stamm()
        self.org.refresh_from_db()
        stamm = Kundenstamm.alle_organisationen.get(organisation=self.org)
        self.assertEqual((self.org.firma, self.org.ort, self.org.telefon, self.org.email),
                         ('AlDo Immobilien AG', 'Solothurn', '032 111 22 33', 'info@aldo.ch'))
        self.assertEqual((stamm.ansprechperson, stamm.ansprech_natel, stamm.natel, stamm.notizen),
                         ('Anna Muster', '079 999 88 77', '079 111 22 33', 'zahlt pünktlich'))

    def test_pflichtfeld_oder_falsche_mail_aendert_nichts(self):
        vorher = self.org.firma
        self._stamm(firma='')
        self._stamm(ansprech_email='keine-mail')
        self._stamm(status='unbekannt')
        self.org.refresh_from_db()
        self.assertEqual(self.org.firma, vorher)
        from abo.models import Kundenstamm
        self.assertFalse(Kundenstamm.alle_organisationen.filter(organisation=self.org, ansprechperson='Anna Muster').exists())

    def test_nur_der_betreiber_aendert_etwas(self):
        team = Client()
        team.force_login(_team_user())
        antwort = team.post(self.url, {'aktion': 'stamm', 'firma': 'Gehackt', 'strasse': 'x', 'plz': '1', 'ort': 'x'})
        self.assertEqual(antwort.status_code, 403)
        self.org.refresh_from_db()
        self.assertNotEqual(self.org.firma, 'Gehackt')

    def test_kontakteintrag_hinzufuegen_und_loeschen(self):
        from abo.models import KundenKontakt
        self.c.post(self.url, {'aktion': 'kontakt', 'art': 'anruf', 'text': 'Rückruf wegen Rechnung'})
        eintrag = KundenKontakt.alle_organisationen.get(organisation=self.org)
        self.assertEqual((eintrag.art, eintrag.erfasst_von), ('anruf', 'betreiber'))
        self.assertContains(self.c.get(self.url), 'Rückruf wegen Rechnung')
        self.c.post(self.url, {'aktion': 'kontakt', 'art': 'anruf', 'text': '   '})
        self.c.post(self.url, {'aktion': 'kontakt', 'art': 'unsinn', 'text': 'x'})
        self.assertEqual(KundenKontakt.alle_organisationen.filter(organisation=self.org).count(), 1)
        self.c.post(self.url, {'aktion': 'kontakt_loeschen', 'eintrag': eintrag.pk})
        self.assertFalse(KundenKontakt.alle_organisationen.filter(organisation=self.org).exists())

    def test_fremder_eintrag_laesst_sich_nicht_loeschen(self):
        from django.utils import timezone

        from abo.models import KundenKontakt
        andere = Organisation.objects.create(firma='Andere AG', strasse='x', plz='1', ort='x')
        fremd = KundenKontakt.alle_organisationen.create(organisation=andere, zeitpunkt=timezone.now(), text='geheim')
        self.c.post(self.url, {'aktion': 'kontakt_loeschen', 'eintrag': fremd.pk})
        self.assertTrue(KundenKontakt.alle_organisationen.filter(pk=fremd.pk).exists())

    def test_verlauf_zeigt_notizen_und_systemereignisse(self):
        from core.auth import log_aktion
        from core.services import betreiber
        from core.tenancy import organisation_kontext
        self.c.post(self.url, {'aktion': 'kontakt', 'art': 'mail', 'text': 'Angebot geschickt'})
        with organisation_kontext(self.org):
            from django.test import RequestFactory
            anfrage = RequestFactory().get('/')
            anfrage.user = self.betreiber
            log_aktion(anfrage, 'Rechnung gesendet', objekt=self.org.firma, details='AB-2', kategorie='sicherheit')
            log_aktion(anfrage, 'Anmeldung fehlgeschlagen', objekt='x', kategorie='sicherheit')
        texte = [e['text'] for e in betreiber.verlauf(self.org)]
        self.assertIn('Angebot geschickt', texte)
        self.assertIn('Rechnung gesendet: AB-2', texte)
        self.assertFalse([t for t in texte if 'Anmeldung fehlgeschlagen' in t], 'nur Aktionen des Betreibers')

    def test_finanzen(self):
        from decimal import Decimal

        from core.services import betreiber
        z = betreiber.finanzen(self.org, heute=self.heute)
        self.assertEqual(z['anzahl'], 3, 'stornierte Rechnungen zählen nicht')
        self.assertEqual(z['bezahlt'], Decimal('100'))
        self.assertEqual(z['offen'], Decimal('220'), 'inklusive Mahngebühr')
        self.assertEqual(z['ueberfaellig'], Decimal('120'), 'AB-3 ist noch nicht fällig')
        self.assertEqual(z['zahlungsdauer'], 5.0)
        self.assertEqual([x['tage'] for x in z['zahlungen']], [5])

    def test_rechnungen_gehen_an_die_abweichende_adresse(self):
        from django.core import mail
        from django.test import override_settings

        from abo import dienst
        type(self.org).objects.filter(pk=self.org.pk).update(email='info@aldo.ch')
        self.org.refresh_from_db()
        steller = {'name': 'P AG', 'strasse': 'x', 'plz': '8000', 'ort': 'Zürich', 'iban': 'CH9300762011623852957',
                   'uid': '', 'email': 'abo@example.ch'}
        with override_settings(ABO_RECHNUNGSSTELLER=steller):
            dienst.rechnung_senden(self.r_offen)
            self._stamm(rechnung_email='buchhaltung@aldo.ch')
            dienst.rechnung_senden(self.r_offen)
        self.assertEqual([m.to for m in mail.outbox], [['info@aldo.ch'], ['buchhaltung@aldo.ch']])

    def test_kundenliste_zeigt_ansprechperson_und_nummer(self):
        self._stamm()
        seite = self.c.get('/betreiber/')
        self.assertContains(seite, 'Anna Muster')
        self.assertContains(seite, '079 999 88 77')
        self.assertContains(seite, f'K-{self.org.pk:04d}')

    def test_interne_notizen_verlassen_die_installation_nicht_per_export(self):
        """Datenexport und Datenreset kennen die Kartei nicht: Notizen des Betreibers gehören nie zum Kunden."""
        from core.services import datenexport, datenreset
        beschriftungen = {m._meta.label for m in datenexport.exportierbare_modelle()}
        self.assertFalse({'abo.Kundenstamm', 'abo.KundenKontakt'} & beschriftungen)
        betroffen = {m._meta.label for m in datenreset.betroffene_modelle()}
        self.assertFalse({'abo.Kundenstamm', 'abo.KundenKontakt'} & betroffen)

