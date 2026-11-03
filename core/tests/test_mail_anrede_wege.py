"""Weitere Mailwege mit persönlichem Gruss (Fortsetzung von `test_mail_anrede`): Webformular, Mahnung,
Fristen-Übersicht.

Gegenproben:
- `core/views/ticket_public.py`: `melder_anrede=anrede,` entfernen -> `test_webformular_speichert_die_anrede` rot;
- `core/views/email_views.py`: im Kopie-Mail `mieter_gruss(...)` durch `'Guten Tag'` ersetzen ->
  `test_mahnung_kopie_gruesst_mit_anrede` rot; im Template `{{ gruss }}` durch `Guten Tag {{ mieter_name }}` ->
  `test_mahnung_257d_html_gruesst_mit_anrede` rot;
- `fristen_digest._gruss`: `len(empfaenger) != 1` auf `False` stellen -> `test_..._mehreren_empfaengern_bleibt_neutral` rot;
  `benutzer_gruss(...)` durch `mail_gruss(sprache='de')` ersetzen -> `test_..._einzigen_empfaenger` rot.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.utils import timezone

from core.models import Pendenz
from core.services.anrede import mieter_gruss
from crm.models import Mitgliedschaft
from finance.models import DebitorenRechnung

from ._helfer import _basis_objekte, _team_user, _test_organisation
from .test_mail_anrede import _klar
from .test_mailwege_schaden import _text, sofort


class _Basis(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        mail.outbox.clear()


class FormularUndMahnungTests(_Basis):

    def test_webformular_speichert_die_anrede(self):
        lg, e, m, v = _basis_objekte()
        with sofort():
            Client().post('/schaden/melden/', {
                'kategorie': 'schaden', 'raum': 'Küche', 'objekt': 'Herd', 'beschreibung': 'Defekt',
                'anrede': 'Herr', 'vorname': 'Max', 'nachname': 'Beispiel', 'email': 'max@example.ch',
                'telefon': '079 1', 'liegenschaft_id': lg.id})
        from tickets.models import SchadenMeldung
        t = SchadenMeldung.objects.get(email_melder='max@example.ch')
        self.assertEqual(t.melder_anrede, 'Herr')
        an_melder = [x for x in mail.outbox if x.to == ['max@example.ch']][0]
        self.assertIn('Guten Tag Herr Beispiel', _text(an_melder))

    def test_mahnung_kopie_gruesst_mit_anrede(self):
        _lg, _e, m, v = _basis_objekte()
        m.anrede = 'Frau'
        m.save()
        faellig = timezone.localdate() - timedelta(days=40)
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=v.einheit.liegenschaft, titel='Miete', betrag=Decimal('1700'),
            datum=faellig, faellig_am=faellig, status='offen')
        c = Client()
        c.force_login(_team_user())
        c.post(f'/vertrag/{v.id}/mahnung/mail/', {'monat': faellig.strftime('%m/%Y'), 'betrag': '1700.00'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].body.startswith('Guten Tag Frau Muster, im Anhang'))

    def test_mahnung_aus_der_mahnliste_gruesst_mit_anrede(self):
        _lg, _e, m, v = _basis_objekte()
        m.anrede = 'Frau'
        m.save()
        faellig = timezone.localdate() - timedelta(days=40)
        r = DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=v.einheit.liegenschaft, titel='Miete', betrag=Decimal('1700'),
            datum=faellig, faellig_am=faellig, status='offen')
        c = Client()
        c.force_login(_team_user())
        c.post(f'/vertrag/{v.id}/mahnung/mail/', {'rechnung': r.pk, 'stufe': '1'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].body.startswith('Guten Tag Frau Muster, im Anhang'))

    def test_mahnung_257d_html_gruesst_mit_anrede(self):
        html = render_to_string('emails/email_mahnung.html', {
            'gruss': mieter_gruss(SimpleNamespace(typ='person', anrede='Frau', vorname='Eva', nachname='Muster',
                                                  firmen_name='', kontaktperson=''), 'de'),
            'firma_name': 'V AG', 'objekt_name': 'x', 'monat': '10/2026', 'betrag': '1.00', 'logo_url': ''})
        self.assertIn('<p>Guten Tag Frau Muster,</p>', html)


class FristenDigestTests(_Basis):

    def _team(self, anzahl):
        for i in range(anzahl):
            u = get_user_model().objects.create_user(
                username=f'chef{i}x', password='x', email=f'chef{i}x@example.ch',
                first_name='Rita', last_name='Roth')
            Mitgliedschaft.objects.create(benutzer=u, organisation=_test_organisation(),
                                          rolle=Mitgliedschaft.ROLLE_VERWALTER)
        Pendenz.objects.create(titel='Frist', kategorie='frist',
                               faellig_am=timezone.localdate() + timedelta(days=2))
        call_command('fristen_digest', '--tage', '7')

    def test_fristen_digest_gruesst_den_einzigen_empfaenger(self):
        self._team(1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].body.startswith('Guten Tag Rita Roth\n'))
        self.assertIn('<p>Guten Tag Rita Roth</p>', mail.outbox[0].alternatives[0][0])

    def test_fristen_digest_mit_mehreren_empfaengern_bleibt_neutral(self):
        self._team(2)
        self.assertTrue(mail.outbox[0].body.startswith('Guten Tag\n'))


class ZugangUndEingangTests(_Basis):

    def test_portal_zugang_eigentuemer(self):
        from crm.models import Eigentuemer
        benutzer = _team_user()          # legt auch die Verwaltung und den Kontext an
        eig = Eigentuemer.objects.create(firma_oder_name='Bau AG', kontaktperson='Anna Meier', anrede='Frau',
                                         email='bau@example.ch')
        c = Client()
        c.force_login(benutzer)
        c.post(f'/neu/mandate/{eig.pk}/portal-zugang/')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('<p>Guten Tag Frau Meier</p>', _text(mail.outbox[0]))

    def test_portal_zugang_mieter(self):
        _lg, _e, m, _v = _basis_objekte()
        c = Client()
        c.force_login(_team_user())
        c.post(f'/neu/personen/{m.pk}/portal-zugang/')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('<p>Guten Tag Herr Muster</p>', _text(mail.outbox[0]))
        # Ohne Anrede: Vorname und Nachname (früher nur der Nachname).
        m.anrede = ''
        m.save()
        mail.outbox.clear()
        c.post(f'/neu/personen/{m.pk}/portal-zugang/')
        self.assertIn('<p>Guten Tag Hans Muster</p>', _text(mail.outbox[0]))

    def test_eingangsbestaetigung_des_portals_franzoesisch(self):
        from tickets.meldung_mails import eingangsbestaetigung_text
        from .test_ticket_workflow import _ticket
        t = _ticket()
        _betreff, text = eingangsbestaetigung_text(t, 'fr')
        self.assertTrue(text.startswith('Bonjour Monsieur Muster\n'))
        _betreff, text = eingangsbestaetigung_text(t, 'de')
        self.assertTrue(text.startswith('Guten Tag Herr Muster\n'))

    def test_intern_erfasst_gruesst_mit_dem_namen_der_erfassung(self):
        lg, e, m, _v = _basis_objekte()
        c = Client()
        c.force_login(_team_user())
        c.post('/neu/schaeden/neu/', {'titel': 'Leck', 'liegenschaft_id': lg.id, 'einheit_id': e.id,
                                      'email_melder': 'eva@example.ch', 'melder_vorname': 'Eva',
                                      'melder_nachname': 'Test'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(_klar(mail.outbox[0]).startswith('Guten Tag Eva Test\n'))

    def test_intern_erfasst_ohne_namen_nie_mieter(self):
        lg, e, m, _v = _basis_objekte()
        c = Client()
        c.force_login(_team_user())
        c.post('/neu/schaeden/neu/', {'titel': 'Leck', 'liegenschaft_id': lg.id, 'einheit_id': e.id,
                                      'email_melder': 'unbekannt@example.ch'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(_klar(mail.outbox[0]).split('\n')[0].strip(), 'Guten Tag')
