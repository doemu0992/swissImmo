"""Einladungslink statt Initialpasswort (Analysebericht 06.11.2026, Nr. 6).

Bisher vergab der Inhaber beim Anlegen eines Kontos ein Passwort und gab es weiter. Jetzt bekommt das neue Konto ein
unbrauchbares Passwort, und die Person setzt es selbst über einen Link in einer Mail.

Gegenproben: in `fw_benutzer_form` `ziel.set_unusable_password()` entfernen -> `test_das_neue_konto_hat_kein_passwort`
rot; den Aufruf von `einladung_senden` entfernen -> `test_die_mail_enthaelt_einen_link_der_funktioniert` rot; die
E-Mail-Prüfung entfernen -> `test_ohne_email_wird_kein_konto_angelegt` rot.
"""
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings

from crm.models import Mitgliedschaft

from ._isolation import MandantenFixture

User = get_user_model()
MAIL = override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')


class EinladungBasis(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)               # Inhaber von A
        mail.outbox.clear()

    def anlegen(self, **ueber):
        daten = {'username': 'neue_person', 'email': 'neue@example.ch', 'rolle': 'Sachbearbeiter',
                 'first_name': 'Nora', 'last_name': 'Neu'}
        daten.update(ueber)
        return self.c.post('/neu/benutzer/neu/', daten)

    def link_aus_mail(self):
        text = mail.outbox[0].body
        treffer = re.search(r'(https?://[^\s<>"\']+/passwort/neu/[^\s<>"\']+)', text)
        self.assertIsNotNone(treffer, f'kein Link in der Mail: {text[:300]}')
        return treffer.group(1)


@MAIL
class NeuesKontoTests(EinladungBasis):
    def test_das_neue_konto_hat_kein_passwort(self):
        self.anlegen()
        neu = User.objects.get(username='neue_person')
        self.assertFalse(neu.has_usable_password(), 'Das Konto hat ein Passwort, das der Inhaber kennen könnte.')

    def test_das_formular_verlangt_kein_passwort_mehr(self):
        html = self.c.get('/neu/benutzer/neu/').content.decode()
        self.assertNotIn('name="passwort"', html)
        self.assertIn('Link', html)

    def test_ein_mitgeschicktes_passwort_wird_ignoriert(self):
        self.anlegen(passwort='vom-inhaber-gewaehlt')
        neu = User.objects.get(username='neue_person')
        self.assertFalse(neu.check_password('vom-inhaber-gewaehlt'))

    def test_die_mail_enthaelt_einen_link_der_funktioniert(self):
        """Der ganze Weg: Mail → Link → eigenes Passwort → Anmeldung."""
        self.anlegen()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['neue@example.ch'])
        link = self.link_aus_mail()
        pfad = link.split('://', 1)[1].split('/', 1)[1]
        person = Client()
        antwort = person.get('/' + pfad, follow=True)            # Django leitet auf die Eingabeseite um
        self.assertEqual(antwort.status_code, 200)
        eingabe = antwort.redirect_chain[-1][0] if antwort.redirect_chain else '/' + pfad
        r = person.post(eingabe, {'new_password1': 'Mein-eigenes-Passwort-77', 'new_password2': 'Mein-eigenes-Passwort-77'})
        self.assertIn(r.status_code, (302, 200))
        neu = User.objects.get(username='neue_person')
        self.assertTrue(neu.check_password('Mein-eigenes-Passwort-77'),
                        'Die Person konnte über den Link kein Passwort setzen.')

    def test_der_link_gilt_nur_einmal(self):
        self.anlegen()
        pfad = '/' + self.link_aus_mail().split('://', 1)[1].split('/', 1)[1]
        person = Client()
        weiter = person.get(pfad).headers['Location']
        person.post(weiter, {'new_password1': 'Erstes-Passwort-88', 'new_password2': 'Erstes-Passwort-88'})
        zweiter = Client().get(pfad)
        # Nach dem Setzen ist das Token entwertet: Django zeigt die Seite «Link ungültig» (200, kein Formular).
        self.assertNotIn('new_password1', zweiter.content.decode())

    def test_ohne_email_wird_kein_konto_angelegt(self):
        antwort = self.anlegen(email='')
        self.assertEqual(antwort.status_code, 302)
        self.assertFalse(User.objects.filter(username='neue_person').exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_die_rolle_bleibt_wie_bisher(self):
        self.anlegen()
        neu = User.objects.get(username='neue_person')
        self.assertEqual(Mitgliedschaft.alle_organisationen.get(benutzer=neu, organisation=self.a.organisation).rolle,
                         'Sachbearbeiter')

    def test_scheitert_die_mail_steht_der_link_zum_weitergeben_da(self):
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=False):
            antwort = self.anlegen()
        self.assertEqual(antwort.status_code, 302)
        texte = ' '.join(str(m) for m in self.c.get('/neu/benutzer/').context['messages'])
        self.assertIn('/passwort/neu/', texte)
        self.assertTrue(User.objects.filter(username='neue_person').exists())

    def test_der_versand_steht_im_logbuch(self):
        from core.models import AktivitaetsLog
        self.anlegen()
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.a.organisation):
            self.assertTrue(AktivitaetsLog.objects.filter(aktion='Einladungslink gesendet').exists())


@MAIL
class BestehendesKontoTests(EinladungBasis):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.m = User.objects.create_user(username='kollege', password='alt-passwort-1', email='k@example.ch')
        Mitgliedschaft.alle_organisationen.create(benutzer=cls.m, organisation=cls.a.organisation, rolle='Sachbearbeiter')

    def _bearbeiten(self, **ueber):
        daten = {'rolle': 'Sachbearbeiter', 'email': 'k@example.ch', **ueber}
        return self.c.post(f'/neu/benutzer/{self.m.pk}/bearbeiten/', daten)

    def test_link_senden_auf_wunsch(self):
        self._bearbeiten(link_senden='on')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/passwort/neu/', mail.outbox[0].body)

    def test_ohne_haekchen_geht_keine_mail_raus(self):
        self._bearbeiten()
        self.assertEqual(len(mail.outbox), 0)

    def test_das_passwort_bleibt_beim_link_senden_gueltig(self):
        """Der Link ändert nichts, bis die Person ihn benutzt."""
        self._bearbeiten(link_senden='on')
        self.m.refresh_from_db()
        self.assertTrue(self.m.check_password('alt-passwort-1'))

    def test_bei_geteiltem_konto_gibt_es_keinen_link(self):
        """Das Konto gehört der Person und ihren anderen Verwaltungen: kein Link von hier."""
        andere = MandantenFixture('B', '3000', 'Bern').organisation
        Mitgliedschaft.alle_organisationen.create(benutzer=self.m, organisation=andere, rolle='Inhaber')
        self._bearbeiten(link_senden='on')
        self.assertEqual(len(mail.outbox), 0)
