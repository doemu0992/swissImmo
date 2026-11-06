"""Die alte Django-Admin ist weg: Es gibt nur noch einen Anmeldeweg, und der verlangt den zweiten Faktor.

Befund (Analysebericht 06.11.2026): `/admin/login/` meldete mit Benutzername und Passwort an, ohne je nach dem Code
zu fragen. Danach setzte `ZweiFaktorPflichtMiddleware` den Sitzungsmerker, sobald ein Faktor *existierte*, und der
Konto-Inhaber kam ohne TOTP nach `/neu/`. Die Middleware prüft die Einrichtungspflicht, nicht den Code; den Code fragt
nur `zweifaktor_login` ab. Ein zweiter Passwort-Login macht die 2FA wirkungslos.

Gegenprobe: in `swiss_immo/urls.py` `path('admin/', admin.site.urls)` wieder eintragen -> alle Tests hier werden rot.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import get_resolver


class AdminEntferntTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.benutzer = get_user_model().objects.create_superuser('su-admin-weg', 'su-weg@example.ch', 'geheim-123')

    def test_keine_route_beginnt_mit_admin(self):
        """Bauformprüfung: Auch eine neu hinzugefügte Admin-Route würde hier auffallen."""
        muster = [str(p.pattern) for p in get_resolver().url_patterns]
        self.assertEqual([m for m in muster if m.startswith(('admin', '^admin'))], [])

    def test_admin_adressen_gibt_es_nicht(self):
        c = Client()
        for url in ('/admin/', '/admin/login/', '/admin/update-marktdaten/', '/admin/crm/mieter/'):
            with self.subTest(url=url):
                self.assertEqual(c.get(url).status_code, 404)

    def test_anmeldung_ueber_admin_gibt_keine_sitzung(self):
        """Der eigentliche Angriff: gültiges Passwort an `/admin/login/` -> keine angemeldete Sitzung."""
        c = Client()
        r = c.post('/admin/login/', {'username': 'su-admin-weg', 'password': 'geheim-123', 'next': '/neu/'})
        self.assertEqual(r.status_code, 404)
        self.assertNotIn('_auth_user_id', c.session)
        self.assertEqual(c.get('/neu/').status_code, 302)          # weiter anonym: Umleitung zur Anmeldung

    def test_der_normale_anmeldeweg_bleibt(self):
        """Kein Kollateralschaden: `/login/` ist erreichbar."""
        self.assertEqual(Client().get('/login/').status_code, 200)
