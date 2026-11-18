"""Kleine Härtungen aus dem Audit (L1–L3): Konfiguration, eine IP-Quelle, Postfach-Test.

Gegenprobe (15.11.2026): `core.auth.client_ip` wieder auf den linken Eintrag -> Test rot; `server_erlaubt` in
`verbinden` entfernt -> Test «interne Adresse» rot.
"""
import socket
from unittest import mock

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase

from core.auth import client_ip
from core.services import postfach_abruf
from core.services.postfach_abruf import AbrufFehler, server_erlaubt


class KonfigurationTests(SimpleTestCase):

    def test_keine_fremde_herkunft_gilt_als_vertraut(self):
        for herkunft in settings.CSRF_TRUSTED_ORIGINS:
            self.assertNotIn('*', herkunft, herkunft)

    def test_testmodus_haengt_am_unterbefehl(self):
        self.assertTrue(settings.TESTING)

    def test_ckeditor_ist_entfernt(self):
        self.assertNotIn('ckeditor', settings.INSTALLED_APPS)


class EineIpQuelleTests(SimpleTestCase):

    def test_protokoll_und_bremse_nehmen_denselben_eintrag(self):
        from core.utils.throttle import client_ip as bremse
        anfrage = RequestFactory().get('/', HTTP_X_FORWARDED_FOR='1.2.3.4, 203.0.113.9', REMOTE_ADDR='10.0.0.1')
        self.assertEqual(client_ip(anfrage), '203.0.113.9')          # nicht der frei wählbare linke Eintrag
        self.assertEqual(client_ip(anfrage), bremse(anfrage))

    def test_ohne_kopf_die_verbindungsadresse(self):
        self.assertEqual(client_ip(RequestFactory().get('/', REMOTE_ADDR='198.51.100.7')), '198.51.100.7')


class PostfachServerTests(SimpleTestCase):

    def test_interne_adressen_sind_nicht_zulaessig(self):
        for server in ('127.0.0.1', '10.1.2.3', '192.168.1.1', '169.254.169.254', '::1', '[::1]', 'localhost', ''):
            self.assertFalse(server_erlaubt(server), server)

    def test_oeffentliche_adresse_ist_zulaessig(self):
        self.assertTrue(server_erlaubt('8.8.8.8'))

    def test_name_der_auf_eine_interne_adresse_zeigt(self):
        intern = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', 0))]
        with mock.patch('socket.getaddrinfo', return_value=intern):
            self.assertFalse(server_erlaubt('imap.intern.example'))

    def test_nicht_aufloesbarer_name_scheitert_erst_beim_verbinden(self):
        with mock.patch('socket.getaddrinfo', side_effect=socket.gaierror):
            self.assertTrue(server_erlaubt('imap.gibt-es-nicht.example'))

    def _postfach(self, server):
        return mock.Mock(verfahren='passwort', VERFAHREN_OAUTH2='oauth2', ist_einsatzbereit=True, passwort='x',
                         server=server, port=993, benutzer='a@b.ch', pk=1)

    def test_verbinden_weist_interne_adresse_ab_ohne_zu_verbinden(self):
        with mock.patch.object(postfach_abruf.imaplib, 'IMAP4_SSL') as imap:
            with self.assertRaises(AbrufFehler):
                postfach_abruf.verbinden(self._postfach('127.0.0.1'))
        imap.assert_not_called()

    def test_die_meldung_verraet_den_grund_des_scheiterns_nicht(self):
        with mock.patch('socket.getaddrinfo', side_effect=socket.gaierror), \
                mock.patch.object(postfach_abruf.imaplib, 'IMAP4_SSL',
                                  side_effect=ConnectionRefusedError('[Errno 111] Connection refused')), \
                self.assertLogs('core.services.postfach_abruf', level='WARNING') as protokoll:
            with self.assertRaises(AbrufFehler) as fehler:
                postfach_abruf.verbinden(self._postfach('imap.example.ch'), zeitlimit=10)
        self.assertNotIn('refused', str(fehler.exception))
        self.assertIn('refused', protokoll.output[0])                 # der Grund steht im Protokoll
