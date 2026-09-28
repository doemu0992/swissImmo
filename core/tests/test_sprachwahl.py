"""Die Sprache lässt sich in der Oberfläche wählen — nicht nur im Browser.

Bis 28.09.2026 bestimmte allein die Browser-Einstellung die Sprache
(`LocaleMiddleware` liest `Accept-Language`). Die Kataloge für FR/IT/EN
lagen bereit, aber wer einen deutschen Browser hatte, kam nicht an sie heran:
Es gab weder einen Knopf noch die Route `set_language`.

Jetzt: Baustein `core/_sprachwahl.html` (DE · FR · IT · EN) in der
Verwaltung, in beiden Portalen und auf beiden Anmeldeseiten; er schickt die
Wahl an `/i18n/setlang/`, das Cookie hat Vorrang vor dem Browser.

Gegenprobe: Ohne die Route in swiss_immo/urls.py sind alle Tests rot
(`NoReverseMatch` beim Rendern des Bausteins bzw. 404 beim Umstellen).
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.tests._helfer import _basis_objekte, _team_user

SETLANG = '/i18n/setlang/'


def _hat_sprachwahl(antwort):
    inhalt = antwort.content.decode()
    return SETLANG in inhalt and all(f'value="{c}"' in inhalt for c in ('de', 'fr', 'it', 'en'))


class SprachwahlSichtbarTests(TestCase):

    def test_verwaltung(self):
        c = Client(); c.force_login(_team_user('Verwalter'))
        self.assertTrue(_hat_sprachwahl(c.get('/neu/')))

    def test_anmeldeseiten(self):
        for pfad in ('/login/', '/portal/login/'):
            with self.subTest(pfad=pfad):
                antwort = Client().get(pfad, follow=True)
                self.assertEqual(antwort.status_code, 200)
                self.assertTrue(_hat_sprachwahl(antwort))

    def test_mieterportal(self):
        _lg, _e, m, _v = _basis_objekte()
        m.benutzer = get_user_model().objects.create_user(username='mieter_sw', password='x')
        m.save()
        c = Client(); c.force_login(m.benutzer)
        self.assertTrue(_hat_sprachwahl(c.get('/mieter/')))

    def test_eigentuemerportal(self):
        from crm.models import Eigentuemer
        lg, _e, _m, _v = _basis_objekte()
        eig = Eigentuemer.objects.create(firma_oder_name='Eigentümer SW')
        eig.benutzer = get_user_model().objects.create_user(username='eig_sw', password='x')
        eig.save()
        lg.eigentuemer = eig
        lg.save()
        c = Client(); c.force_login(eig.benutzer)
        self.assertTrue(_hat_sprachwahl(c.get('/portal/')))


class SprachwahlWirktTests(TestCase):

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def test_ohne_wahl_gilt_der_browser(self):
        """Gegenstück: Ohne Cookie bleibt es bei `Accept-Language`."""
        self.assertContains(self.c.get('/neu/', HTTP_ACCEPT_LANGUAGE='de-CH'), 'Arbeitsvorrat')

    def test_wahl_schlaegt_den_browser(self):
        antwort = self.c.post(SETLANG, {'language': 'fr', 'next': '/neu/'})
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort['Location'], '/neu/')
        seite = self.c.get('/neu/', HTTP_ACCEPT_LANGUAGE='de-CH')
        self.assertContains(seite, 'Charge de travail')
        self.assertContains(seite, 'aria-pressed="true"', count=1)

    def test_zurueck_auf_deutsch(self):
        self.c.post(SETLANG, {'language': 'it', 'next': '/neu/'})
        self.assertContains(self.c.get('/neu/'), 'Carico di lavoro')
        self.c.post(SETLANG, {'language': 'de', 'next': '/neu/'})
        self.assertContains(self.c.get('/neu/', HTTP_ACCEPT_LANGUAGE='en'), 'Arbeitsvorrat')

    def test_kein_offener_redirect(self):
        """`next` darf nicht auf eine fremde Adresse führen."""
        antwort = self.c.post(SETLANG, {'language': 'fr', 'next': 'https://evil.example/'})
        self.assertNotIn('evil.example', antwort.get('Location', ''))
