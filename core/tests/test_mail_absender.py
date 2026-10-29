"""Absender und Antwortadresse je Verwaltung (FUNK-12).

Geprüft wird, was der Empfänger sieht: Der Anzeigename nennt die schreibende Verwaltung, die
Adresse im From bleibt die des SMTP-Kontos (SPF/DKIM), und die Antwort geht an die Verwaltung
und nie an die eines anderen Mandanten.
"""
from email.header import decode_header, make_header
from email.utils import parseaddr
from unittest import mock

from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from core.tenancy import organisation_kontext
from core.utils import absender
from core.utils.email_service import send_report_mail, send_via_hoststar
from core.models import Postfach
from crm.models import Organisation

KONTO = 'immoswiss <info@immoswiss.app>'


def _name(kopf):
    """Anzeigename eines From-Headers, lesbar (Django kodiert Nicht-ASCII nach RFC 2047)."""
    return str(make_header(decode_header(parseaddr(kopf)[0])))


@override_settings(DEFAULT_FROM_EMAIL=KONTO, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AbsenderTests(TestCase):
    def setUp(self):
        self.a = Organisation.objects.create(firma='Muster Verwaltung AG', email='mieter@muster.ch')
        self.b = Organisation.objects.create(firma='Beispiel Treuhand', email='info@beispiel.ch')
        mail.outbox = []

    def test_anzeigename_ist_die_firma_die_adresse_bleibt_die_des_kontos(self):
        name, adresse = parseaddr(absender.absender(self.a))
        name = _name(absender.absender(self.a))
        self.assertEqual(adresse, 'info@immoswiss.app')
        self.assertIn('Muster Verwaltung AG', name)

    def test_ohne_organisation_gilt_das_konto_unveraendert(self):
        self.assertEqual(absender.absender(None), KONTO)

    def test_mandantenkontext_ersetzt_die_organisation(self):
        with organisation_kontext(self.b):
            self.assertIn('Beispiel Treuhand', _name(absender.absender()))

    def test_firma_kann_keine_kopfzeile_einschleusen(self):
        boese = Organisation.objects.create(firma='Evil\r\nBcc: opfer@example.org <x@y.ch>', email='e@e.ch')
        wert = absender.absender(boese)
        self.assertNotIn('\n', wert)
        self.assertNotIn('\r', wert)
        self.assertEqual(parseaddr(wert)[1], 'info@immoswiss.app')

    def test_reply_to_ist_die_adresse_der_verwaltung(self):
        self.assertEqual(absender.antwortadresse(self.a), ['mieter@muster.ch'])
        self.assertEqual(absender.antwortadresse(self.b), ['info@beispiel.ch'])

    def test_antwortpostfach_geht_vor_der_verwaltungsadresse(self):
        Postfach.alle_organisationen.create(
            organisation=self.a, zweck=Postfach.ZWECK_ANTWORTEN, aktiv=True,
            benutzer='antworten@muster.ch', server='imap.example.ch')
        self.assertEqual(absender.antwortadresse(self.a), ['antworten@muster.ch'])
        self.assertEqual(absender.antwortadresse(self.b), ['info@beispiel.ch'])

    def test_ausdrueckliche_adresse_geht_vor_allem(self):
        self.assertEqual(absender.antwortadresse(self.a, reply_to='x@y.ch'), ['x@y.ch'])

    def test_ohne_adresse_der_verwaltung_gilt_die_globale(self):
        leer = Organisation.objects.create(firma='Leer AG', email='')
        with mock.patch.dict('os.environ', {'EMAIL_REPLY_USER': 'reply@plattform.ch'}):
            self.assertEqual(absender.antwortadresse(leer), ['reply@plattform.ch'])

    def test_versand_traegt_firma_und_reply_to_der_verwaltung(self):
        self.assertTrue(send_via_hoststar('mieter@example.ch', 'Betreff', '<p>x</p>', organisation=self.a))
        m = mail.outbox[0]
        self.assertIn('Muster Verwaltung AG', _name(m.from_email))
        self.assertEqual(parseaddr(m.from_email)[1], 'info@immoswiss.app')
        self.assertEqual(m.reply_to, ['mieter@muster.ch'])

    def test_versand_im_mandantenkontext_ohne_angabe(self):
        with organisation_kontext(self.b):
            send_via_hoststar('mieter@example.ch', 'Betreff', '<p>x</p>')
        self.assertEqual(mail.outbox[0].reply_to, ['info@beispiel.ch'])

    def test_reportmail_geht_mit_der_verwaltung_raus(self):
        self.assertTrue(send_report_mail('eig@example.ch', 'Report', '<p>x</p>', organisation=self.b))
        self.assertEqual(mail.outbox[0].reply_to, ['info@beispiel.ch'])
        self.assertIn('Beispiel Treuhand', _name(mail.outbox[0].from_email))


class KeinStillerRueckfallTests(SimpleTestCase):
    def test_alle_sendepfade_setzen_kopfzeilen_ueber_den_helfer(self):
        """Wächter: Wer eine Mail baut, nimmt `kopfzeilen()` und nicht `DEFAULT_FROM_EMAIL` roh.

        Ausnahmen sind benannt: die Test-Mail aus den Einstellungen (Plattform an sich selbst).
        """
        import os
        from pathlib import Path
        wurzel = Path(__file__).resolve().parents[2]
        ausserhalb = {'.git', '.claude', 'node_modules', 'migrations', 'tests', '__pycache__', 'static', 'staticfiles'}
        erlaubt = {'swiss_immo/settings.py', 'core/utils/absender.py', 'core/views/fw/profil.py'}
        funde = []
        for ordner, unterordner, dateien in os.walk(wurzel):
            unterordner[:] = [d for d in unterordner if d not in ausserhalb]
            for datei in dateien:
                if not datei.endswith('.py') or datei.startswith('test_'):
                    continue
                pfad = Path(ordner) / datei
                rel = pfad.relative_to(wurzel).as_posix()
                if rel in erlaubt:
                    continue
                if 'from_email=settings.DEFAULT_FROM_EMAIL' in pfad.read_text(encoding='utf-8'):
                    funde.append(rel)
        self.assertEqual(funde, [], 'Absender ohne Verwaltung (FUNK-12): kopfzeilen() aus core/utils/absender.py nehmen')
