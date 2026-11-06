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


class AdminKontaktTests(TestCase):
    """Die Admin-Seiten selbst gibt es nicht mehr (Route entfernt, siehe test_admin_entfernt); die Hilfsfunktion bleibt
    bis zum Aufräumen der Admin-Klassen geprüft."""

    def test_kontakt_knoepfe_maskieren_eingaben(self):
        """Telefon und E-Mail stehen nicht ungeprüft im Markup (vorher: f-String in `format_html`)."""
        from crm.admin import _kontakt_html
        html = str(_kontakt_html('<script>x</script>', 'a@b.ch'))
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
