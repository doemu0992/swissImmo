"""Das Admin öffnet jede Seite (DESIGN-15).

Das Audit vom 28.10.2026 fand `/admin/crm/mieter/<id>/change/` mit 500: Das Fieldset nannte
`telefon`, das Modell kennt `telefon_privat`, `telefon_geschaeft` und `mobile`. Gleiche Klasse
Fehler, bei der Nachprüfung gefunden: `Handwerker` (`gewerk` statt `branche`), `Geraet`
(`typ` statt `kategorie`), `Zaehler` (`get_typ_display` bei einem Feld ohne Auswahl).

Zwei Sichten:

1. Ohne Daten: Jeder Name, den ein ModelAdmin für Liste, Fieldsets und Inlines nennt, muss sich
   auflösen lassen (Modellfeld, Eigenschaft oder Methode des Admins). Das findet den Tippfehler
   in einem Fieldset auch dann, wenn die Tabelle leer ist.
2. Mit Daten: Liste und Änderungsseite jedes Modells mit einem Datensatz im Fixture werden
   abgerufen und dürfen nicht abstürzen.

Die Anlegen-Seiten antworten mit 403 (`NurLesenMixin`): Das Admin ist ein Lesewerkzeug.
"""
from django.contrib import admin
from django.contrib.admin.utils import flatten_fieldsets, label_for_field
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase

from crm.models import Mitgliedschaft

from ._isolation import MandantenFixture


def _admins():
    return list(admin.site._registry.items())


class AdminNamenLoesenSichAufTests(TestCase):
    """Sicht 1: Kein Name in Liste, Fieldsets oder Inlines ohne Gegenstück."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_jeder_name_in_liste_fieldsets_und_inlines_ist_aufloesbar(self):
        from core.tenancy import organisation_kontext
        super_user = get_user_model().objects.create_superuser('su-namen', 'su@example.ch', 'x')
        anfrage = RequestFactory().get('/admin/')
        anfrage.user = super_user
        fehler, geprueft = [], 0
        # Die Formulare der Inlines lesen Auswahllisten aus der Datenbank: Mandantenkontext nötig.
        with organisation_kontext(self.a.organisation):
            for modell, ma in _admins():
                quellen = [(modell, ma)]
                quellen += [(inline.model, inline) for inline in ma.get_inline_instances(anfrage)]
                for m, quelle in quellen:
                    name_der_quelle = quelle.__class__.__name__
                    namen = list(getattr(quelle, 'list_display', ()) or ())
                    try:
                        namen += list(flatten_fieldsets(quelle.get_fieldsets(anfrage)))
                        # Felder, die erst das Formular kennt (z. B. Passwortfelder des Benutzer-Admins).
                        formular = (quelle.get_form(anfrage, None) if hasattr(quelle, 'get_form')
                                    else quelle.get_formset(anfrage).form)
                        formularfelder = set(formular.base_fields)
                    except Exception as e:                              # noqa: BLE001
                        fehler.append(f'{name_der_quelle}: Fieldsets/Formular nicht lesbar ({e})')
                        continue
                    for name in namen:
                        if name == '__str__' or callable(name) or name in formularfelder:
                            continue
                        geprueft += 1
                        try:
                            label_for_field(name, m, quelle)
                        except Exception as e:                          # noqa: BLE001
                            fehler.append(f'{name_der_quelle}.{name}: {e}')
        self.assertGreater(geprueft, 60, 'auffällig wenige Namen geprüft')
        self.maxDiff = None
        self.assertEqual(fehler, [], 'Namen, die weder Feld noch Methode sind')

    def test_der_tippfehler_telefon_waere_aufgefallen(self):
        """Selbstprüfung der Sicht: Der Fehler aus dem Audit ist für sie sichtbar."""
        from crm.models import Mieter
        with self.assertRaises(AttributeError):
            label_for_field('telefon', Mieter, admin.site._registry[Mieter])


class AdminSeitenOeffnenTests(TestCase):
    """Sicht 2: Liste und Änderungsseite jedes Modells mit Datensatz öffnen sich."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.super = get_user_model().objects.create_superuser('su-seiten', 'su2@example.ch', 'x')
        Mitgliedschaft.alle_organisationen.create(
            benutzer=cls.super, organisation=cls.a.organisation, rolle=Mitgliedschaft.ROLLE_INHABER)

    def setUp(self):
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.super)

    def test_listen_und_aenderungsseiten_stuerzen_nicht_ab(self):
        objekte = {}
        for o in self.a._alle_objekte():
            objekte.setdefault(type(o), o)
        abgestuerzt, geprueft = [], 0
        for modell, _ma in _admins():
            app, name = modell._meta.app_label, modell._meta.model_name
            urls = [f'/admin/{app}/{name}/']
            if modell in objekte:
                urls.append(f'/admin/{app}/{name}/{objekte[modell].pk}/change/')
            for url in urls:
                geprueft += 1
                antwort = self.client.get(url)
                if antwort.status_code >= 500:
                    abgestuerzt.append((antwort.status_code, url))
        self.assertGreater(geprueft, 40, 'auffällig wenige Seiten geprüft')
        self.assertEqual(abgestuerzt, [])

    def test_mieter_und_handwerker_zeigen_ihre_felder(self):
        mieter = self.client.get(f'/admin/crm/mieter/{self.a.mieter.pk}/change/')
        self.assertEqual(mieter.status_code, 200)
        self.assertContains(mieter, 'Telefon Privat')
        handwerker = self.client.get(f'/admin/crm/handwerker/{self.a.handwerker.pk}/change/')
        self.assertEqual(handwerker.status_code, 200)
        self.assertContains(handwerker, 'Branche')

    def test_kontakt_knoepfe_maskieren_eingaben(self):
        """Telefon und E-Mail stehen nicht ungeprüft im Markup (vorher: f-String in `format_html`)."""
        from crm.admin import _kontakt_html
        html = str(_kontakt_html('<script>x</script>', 'a@b.ch'))
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)


class AdminLogoTests(TestCase):
    def test_kein_bildaufruf_auf_einen_symbolnamen(self):
        """DESIGN-14: `SITE_ICON = "real_estate_agent"` wurde als Bildadresse geladen (404, gebrochenes Logo)."""
        a = MandantenFixture('A', '8000', 'Zürich')
        su = get_user_model().objects.create_superuser('su-logo', 'su4@example.ch', 'x')
        Mitgliedschaft.alle_organisationen.create(
            benutzer=su, organisation=a.organisation, rolle=Mitgliedschaft.ROLLE_INHABER)
        c = Client()
        c.force_login(su)
        inhalt = c.get('/admin/').content.decode()
        self.assertIn('SwissImmo', inhalt, 'die Admin-Startseite wurde nicht gerendert')
        self.assertNotIn('real_estate_agent', inhalt)


class AdminOhneMitgliedschaftTests(TestCase):
    """Ein Superuser ohne Mitgliedschaft hat keinen Mandanten: 403 mit Text statt Fehler 500."""

    def test_liste_ohne_mitgliedschaft_gibt_403(self):
        su = get_user_model().objects.create_superuser('su-ohne', 'su3@example.ch', 'x')
        c = Client(raise_request_exception=False)
        c.force_login(su)
        for url in ('/admin/crm/mieter/', '/admin/rentals/mietvertrag/', '/admin/portfolio/liegenschaft/'):
            with self.subTest(url=url):
                self.assertEqual(c.get(url).status_code, 403)
