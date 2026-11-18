"""Zwei-Faktor-Anmeldung für Eigentümer: freiwillig, im Portal-Rahmen, und danach fragt die Portal-Anmeldung den Code."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import ZweiterFaktor
from core.services import totp
from core.tenancy import organisation_kontext
from crm.models import Eigentuemer

from ._helfer import _team_user, _test_organisation

PASSWORT = 'ein-langes-Passwort-42'


class EigentuemerZweiFaktorTests(TestCase):
    def setUp(self):
        self.org = _test_organisation(firma='V AG')
        with organisation_kontext(self.org):
            self.eig = Eigentuemer.objects.create(firma_oder_name='Erika Eigner')
        self.benutzer = get_user_model().objects.create_user('erika', password=PASSWORT)
        self.eig.benutzer = self.benutzer
        with organisation_kontext(self.org):
            self.eig.save()
        self.c = Client()
        self.c.force_login(self.benutzer)

    def _einrichten(self):
        self.c.get(reverse('zweifaktor_einrichten'))
        geheimnis = self.c.session['zweifaktor_neues_geheimnis']
        return geheimnis, self.c.post(reverse('zweifaktor_einrichten'), {'code': totp.code(geheimnis)})

    def test_das_profil_bietet_die_einrichtung_an_und_zwingt_niemanden(self):
        antwort = self.c.get('/portal/profil/')
        self.assertEqual(antwort.status_code, 200)             # ohne Faktor frei zugänglich: freiwillig
        self.assertContains(antwort, 'data-testid="zf-einrichten"')
        self.assertContains(antwort, reverse('zweifaktor_einrichten'))

    def test_die_konto_seiten_erscheinen_im_portal_rahmen_ohne_navigation_der_verwaltung(self):
        for url in (reverse('zweifaktor_uebersicht'), reverse('zweifaktor_einrichten')):
            inhalt = self.c.get(url).content.decode()
            self.assertNotIn('id="fwSchiene"', inhalt, url)
            self.assertNotIn('href="/neu/einstellungen/', inhalt, url)
        self.assertContains(self.c.get(reverse('zweifaktor_uebersicht')), 'href="/portal/profil/"')

    def test_das_team_sieht_die_seiten_weiter_im_rahmen_der_verwaltung(self):
        team = Client()
        team.force_login(_team_user('Verwalter'))
        inhalt = team.get(reverse('zweifaktor_uebersicht')).content.decode()
        self.assertIn('href="/neu/einstellungen/', inhalt)
        self.assertNotIn('Zurück zum Portal', inhalt)

    def test_einrichten_aktiviert_den_faktor_und_das_profil_zeigt_ihn(self):
        _geheimnis, antwort = self._einrichten()
        self.assertContains(antwort, 'Notfallcodes')
        self.assertNotIn('id="fwSchiene"', antwort.content.decode())
        self.assertTrue(ZweiterFaktor.objects.get(benutzer=self.benutzer).ist_aktiv)
        profil = self.c.get('/portal/profil/')
        self.assertContains(profil, 'Aktiv:')
        self.assertNotContains(profil, 'data-testid="zf-einrichten"')

    def test_danach_reicht_das_passwort_an_der_portal_anmeldung_nicht_mehr(self):
        geheimnis, _antwort = self._einrichten()
        neu = Client()
        neu.post(reverse('portal_login'), {'username': 'erika', 'password': PASSWORT})
        self.assertNotIn('_auth_user_id', neu.session)         # noch nicht angemeldet
        self.assertEqual(neu.get('/portal/profil/').status_code, 302)
        import time
        spaeter = time.time() + totp.SCHRITT                   # ein frisches Zeitfenster (kein Wiederverwenden)
        from unittest import mock
        with mock.patch('time.time', return_value=spaeter):
            neu.post(reverse('zweifaktor_bestaetigen'), {'code': totp.code(geheimnis, spaeter)})
        self.assertIn('_auth_user_id', neu.session)

    def test_ohne_faktor_meldet_das_passwort_allein_weiter_an(self):
        neu = Client()
        neu.post(reverse('portal_login'), {'username': 'erika', 'password': PASSWORT})
        self.assertIn('_auth_user_id', neu.session)


class MieterZweiFaktorTests(TestCase):
    def setUp(self):
        from crm.models import Mieter
        self.org = _test_organisation(firma='V AG')
        self.benutzer = get_user_model().objects.create_user('mia', password=PASSWORT)
        with organisation_kontext(self.org):
            self.mieter = Mieter.objects.create(typ='person', vorname='Mia', nachname='Muster', benutzer=self.benutzer)
        self.c = Client()
        self.c.force_login(self.benutzer)

    def test_meine_daten_bietet_die_einrichtung_an(self):
        antwort = self.c.get('/mieter/daten/')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'data-testid="zf-einrichten"')

    def test_die_konto_seite_fuehrt_zurueck_zu_meine_daten(self):
        inhalt = self.c.get(reverse('zweifaktor_uebersicht')).content.decode()
        self.assertIn('href="/mieter/daten/"', inhalt)
        self.assertNotIn('id="fwSchiene"', inhalt)

    def test_einrichten_aktiviert_und_die_seite_zeigt_es(self):
        self.c.get(reverse('zweifaktor_einrichten'))
        geheimnis = self.c.session['zweifaktor_neues_geheimnis']
        self.c.post(reverse('zweifaktor_einrichten'), {'code': totp.code(geheimnis)})
        self.assertTrue(ZweiterFaktor.objects.get(benutzer=self.benutzer).ist_aktiv)
        antwort = self.c.get('/mieter/daten/')
        self.assertContains(antwort, 'Aktiv:')
        self.assertNotContains(antwort, 'data-testid="zf-einrichten"')
