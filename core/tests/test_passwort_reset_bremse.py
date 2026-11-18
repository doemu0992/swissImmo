"""Passwort vergessen: Bremse je IP und je Adresse; Mindestlänge 12."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase


class PasswortResetBremseTests(TestCase):
    def setUp(self):
        cache.clear()
        get_user_model().objects.create_user('anna', email='anna@example.ch', password='Ein-langes-Passwort-1')

    def _anfrage(self, adresse='anna@example.ch', ip='203.0.113.7'):
        return Client().post('/passwort/vergessen/', {'email': adresse}, REMOTE_ADDR=ip)

    def test_normale_anfrage_schickt_eine_mail(self):
        antwort = self._anfrage()
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    def test_je_adresse_hoechstens_drei_mails_pro_stunde(self):
        for _ in range(6):
            antwort = self._anfrage()
            self.assertEqual(antwort.status_code, 302)          # nach aussen immer dieselbe Antwort
        self.assertEqual(len(mail.outbox), 3)

    def test_je_ip_hoechstens_zehn_anfragen_pro_stunde(self):
        for i in range(14):
            self._anfrage(adresse=f'x{i}@example.ch', ip='198.51.100.9')
        self.assertLessEqual(len(mail.outbox), 0)               # keine bekannte Adresse: nie eine Mail
        self._anfrage(ip='198.51.100.9')                         # bekannte Adresse, aber die IP ist über dem Limit
        self.assertEqual(len(mail.outbox), 0)
        self._anfrage(ip='198.51.100.10')                        # andere IP: geht durch
        self.assertEqual(len(mail.outbox), 1)


class PasswortLaengeTests(TestCase):
    def test_unter_zwoelf_zeichen_werden_abgelehnt(self):
        with self.assertRaises(ValidationError):
            validate_password('Elf-zeich-1')                    # 11 Zeichen
        validate_password('Zwoelf-Zei-1x')                       # 13 Zeichen: gültig
