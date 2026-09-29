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


class MonatsnamenFolgenDerSpracheTests(TestCase):
    """Die Sollstellung nennt den Monat in der gewählten Sprache.

    Vorher kam er aus `strftime('%B')` — das folgt dem Locale des Servers
    (dort «C», also Englisch), nicht der Sprache der Anfrage. Im deutschen
    UI stand deshalb «March» statt «März».

    Gegenprobe: `datum_format(..., 'F')` in core/views/fw/sollstellung.py
    zurück auf `strftime('%B')` — dann schlagen beide Tests fehl.
    """

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def test_deutsch(self):
        seite = self.c.get('/neu/sollstellung/?jahr=2026&monat=3', HTTP_ACCEPT_LANGUAGE='de-CH')
        self.assertContains(seite, 'März')
        self.assertNotContains(seite, 'March')

    def test_franzoesisch(self):
        self.c.post(SETLANG, {'language': 'fr', 'next': '/neu/'})
        seite = self.c.get('/neu/sollstellung/?jahr=2026&monat=3')
        self.assertContains(seite, 'mars')
        self.assertNotContains(seite, 'März')


class VertragsaktenMonatFolgtDerSpracheTests(TestCase):
    """Der Aktenkopf des Vertrags nennt den ältesten offenen Monat in der
    gewählten Sprache — derselbe Fehler wie in der Sollstellung, an zweiter
    Stelle: `strftime('%B %Y')` in core/views/fw/detailseiten.py lieferte
    «May 2024» auch in der deutschen Oberfläche.

    Gegenprobe: `dateformat.format(..., 'F Y')` zurück auf
    `strftime('%B %Y')` — beide Tests werden rot.
    """

    def setUp(self):
        from datetime import date
        from decimal import Decimal
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        DebitorenRechnung.objects.create(
            vertrag=v, liegenschaft=lg, einheit=e, titel='Miete 05/2024',
            datum=date(2024, 5, 1), faellig_am=date(2024, 5, 5),
            betrag=Decimal('1700'), status='offen')
        self.url = f'/neu/vertraege/{v.id}/'
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def test_deutsch(self):
        seite = self.c.get(self.url, HTTP_ACCEPT_LANGUAGE='de-CH')
        self.assertContains(seite, 'Mai 2024')
        self.assertNotContains(seite, 'May 2024')

    def test_franzoesisch(self):
        self.c.post(SETLANG, {'language': 'fr', 'next': '/neu/'})
        seite = self.c.get(self.url)
        self.assertContains(seite, 'mai 2024')
        self.assertNotContains(seite, 'May 2024')


class AuswertungMonatskuerzelFolgenDerSpracheTests(TestCase):
    """Die Monatsleiste der Auswertung kürzt in der gewählten Sprache.

    Vorher `strftime('%b')` in core/views/fw/listen.py — Server-Locale, also
    «Mar», «May», «Oct» auch in der deutschen Oberfläche.

    Gegenprobe: `dateformat.format(..., 'M')` zurück auf `strftime('%b')` —
    beide Tests werden rot.
    """

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def test_deutsch(self):
        seite = self.c.get('/neu/auswertung/', HTTP_ACCEPT_LANGUAGE='de-CH')
        self.assertContains(seite, '>Okt<')
        self.assertNotContains(seite, '>Oct<')

    def test_italienisch(self):
        # Italienisch statt Französisch: Dort heisst der Oktober «Oct» wie im
        # Englischen, und der Test könnte den Fehler nicht sehen.
        self.c.post(SETLANG, {'language': 'it', 'next': '/neu/'})
        seite = self.c.get('/neu/auswertung/')
        self.assertContains(seite, '>Ott<')
        self.assertNotContains(seite, '>Oct<')


class ArbeitsvorratReiterFolgenDerSpracheTests(TestCase):
    """Die Reiter des Arbeitsvorrats (Heute · Diese Woche · …) stehen in der
    gewählten Sprache.

    Vorher `gettext` auf Modulebene in core/views/fw/arbeit.py: einmal beim
    Import ausgewertet, also immer deutsch.

    Gegenprobe: `gettext_lazy` in ANSICHTEN zurück auf `_` (gettext) — der
    Test wird rot.
    """

    def test_franzoesisch(self):
        c = Client()
        c.force_login(_team_user('Verwalter'))
        c.post(SETLANG, {'language': 'fr', 'next': '/neu/'})
        seite = c.get('/neu/')
        self.assertContains(seite, 'Cette semaine')
        self.assertNotContains(seite, 'Diese Woche')


class WohnungsabnahmeFolgtDerSpracheTests(TestCase):
    """Das Formular «Wohnungsabnahme» steht in der gewählten Sprache — die
    gespeicherten Werte bleiben dabei unverändert: Raumnamen werden als Text
    gespeichert (keine `value`) und bleiben deshalb Deutsch, die übrigen
    Auswahlen tragen feste Schlüssel.

    Gegenprobe: `{% load i18n %}` und die Auszeichnung in
    fw/abnahme_neu.html entfernen — der französische Test wird rot.
    """

    def setUp(self):
        _lg, _e, _m, v = _basis_objekte()
        self.url = f'/neu/vertraege/{v.id}/abnahme/neu/'
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def test_franzoesisch(self):
        from core.views.fw.abnahme import ABNAHME_RAEUME
        self.c.post(SETLANG, {'language': 'fr', 'next': '/neu/'})
        seite = self.c.get(self.url)
        self.assertContains(seite, 'Relevés des compteurs')
        self.assertNotContains(seite, '>Zählerstände<')  # der HTML-Kommentar bleibt
        self.assertContains(seite, '<option value="mieter">Locataire</option>')
        self.assertContains(seite, f'<option>{ABNAHME_RAEUME[0]}</option>')

    def test_deutsch(self):
        seite = self.c.get(self.url, HTTP_ACCEPT_LANGUAGE='de-CH')
        self.assertContains(seite, '>Zählerstände<')


class VertragBearbeitenFolgtDerSpracheTests(TestCase):
    """Die Maske «Vertrag bearbeiten» steht in der gewählten Sprache. Der
    Sperrhinweis zum amtlichen Formular (Art. 269d OR) bleibt bis zur
    juristischen Durchsicht Deutsch.

    Gegenprobe: `{% load i18n %}` und die Auszeichnung in
    fw/vertrag_bearbeiten.html entfernen — der französische Test wird rot.
    """

    def setUp(self):
        _lg, _e, _m, v = _basis_objekte()  # aktiver Vertrag: gesperrt
        self.url = f'/neu/vertraege/{v.id}/bearbeiten/'
        self.c = Client()
        self.c.force_login(_team_user('Verwalter'))

    def test_franzoesisch(self):
        self.c.post(SETLANG, {'language': 'fr', 'next': '/neu/'})
        seite = self.c.get(self.url)
        self.assertContains(seite, 'Modifier le contrat')
        self.assertContains(seite, 'Durée et résiliation')
        self.assertNotContains(seite, '>Mietdauer &amp; Kündigung<')
        self.assertContains(seite, 'amtliche Formular (Art. 269d)')

    def test_deutsch(self):
        seite = self.c.get(self.url, HTTP_ACCEPT_LANGUAGE='de-CH')
        self.assertContains(seite, 'Vertrag bearbeiten')
