"""Jede Vorlage, die der Code rendert, gibt es auch.

Gefunden beim Telefon-Rundgang vom 29.09.2026: Zwei Seiten endeten seit
August in einem Serverfehler, weil ihre Vorlage fehlte.

- «Mahnstufen» eines Mandats (`/neu/mandate/<id>/mahnstufen/`, verlinkt aus
  Mandatsliste und Mandatsdetail): Ansicht und Fachlogik
  (`core/services/mahnstufen.py`) waren da, `fw/eigentuemer_mahnstufen.html`
  wurde nie eingecheckt.
- Eigentümer im Django-Admin: Bei der Umbenennung Mandant → Eigentümer wurde
  `crm/admin.py` angepasst, `admin/crm/mandant_header.html` aber nicht
  mitgenommen.

Kein Test hatte eine der beiden Seiten je aufgerufen. Der Wächter unten
braucht keinen Aufruf: Er sucht jeden Vorlagennamen, den der Code an
`render`, `render_to_string` oder `get_template` übergibt, und lädt ihn.

Gegenproben:
- `core/templates/fw/eigentuemer_mahnstufen.html` löschen —
  `test_jede_gerenderte_vorlage_existiert` und die Seitentests werden rot;
- in `crm/admin.py` den Namen `eigentuemer_header.html` in
  `mandant_header.html` ändern — `test_jede_gerenderte_vorlage_existiert`
  und `test_eigentuemer_im_admin` werden rot.
"""
import pathlib
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.test import Client, SimpleTestCase, TestCase

from core.tests._helfer import _team_user, _test_organisation

WURZEL = pathlib.Path(settings.BASE_DIR)
APPS = ('core', 'crm', 'portfolio', 'rentals', 'finance', 'tickets', 'faelle', 'mietprozess', 'benutzer')

#: Vorlagenname als Literal im ersten Argument (bzw. nach `request`).
AUFRUF = re.compile(
    r"""\b(?:render|render_to_string|get_template)\(\s*(?:request\s*,\s*)?"""
    r"""['"]([\w/.\-]+\.(?:html|txt|xml))['"]""")


class VorlagenWaechterTests(SimpleTestCase):

    def test_der_waechter_findet_aufrufe(self):
        """Ein Muster, das nichts findet, prüft nichts."""
        self.assertGreater(len(_aufrufe()), 100)

    def test_jede_gerenderte_vorlage_existiert(self):
        fehlend = []
        for datei, name in _aufrufe():
            try:
                get_template(name)
            except TemplateDoesNotExist:
                fehlend.append(f'{datei}: {name}')
        self.assertEqual(fehlend, [], 'Diese Vorlagen werden gerendert, existieren aber nicht.')


def _aufrufe():
    gefunden = []
    for app in APPS:
        for pfad in sorted((WURZEL / app).rglob('*.py')):
            if {'tests', 'migrations'} & set(pfad.parts):
                continue
            for m in AUFRUF.finditer(pfad.read_text(encoding='utf-8')):
                gefunden.append((str(pfad.relative_to(WURZEL)), m.group(1)))
    return gefunden


class MahnstufenSeiteTests(TestCase):

    def setUp(self):
        from crm.models import Eigentuemer
        self.md = Eigentuemer.objects.create(organisation=_test_organisation(), firma_oder_name='Stiftung Aare')
        self.c = Client()
        self.c.force_login(_team_user())

    def test_seite_zeigt_den_standard(self):
        antwort = self.c.get(f'/neu/mandate/{self.md.id}/mahnstufen/')
        self.assertEqual(antwort.status_code, 200)
        # Werte aus MAHN_KONFIG_DEFAULT, nicht aus der Vorlage
        seite = antwort.content.decode()
        self.assertRegex(seite, r'name="ab_tage_2"[^>]*value="30"')
        self.assertRegex(seite, r'name="gebuehr_3"[^>]*value="40.00"')

    def test_speichern_legt_die_konfiguration_ab(self):
        daten = {'aktiv_1': 'on', 'ab_tage_1': '10', 'gebuehr_1': '0',
                 'ab_tage_2': '30', 'gebuehr_2': '20.00',
                 'aktiv_3': 'on', 'ab_tage_3': '60', 'gebuehr_3': '40.00', 'kuendigung_3': 'on'}
        antwort = self.c.post(f'/neu/mandate/{self.md.id}/mahnstufen/', daten)
        self.assertEqual(antwort.status_code, 302)
        self.md.refresh_from_db()
        stufen = {c['stufe']: c for c in self.md.mahn_konfig}
        self.assertEqual(stufen[1]['ab_tage'], 10)
        self.assertFalse(stufen[2]['aktiv'])
        self.assertTrue(stufen[3]['kuendigung'])
        # und die Seite zeigt das Gespeicherte wieder an
        self.assertContains(self.c.get(f'/neu/mandate/{self.md.id}/mahnstufen/'), 'value="10"')

    def test_franzoesisch(self):
        self.c.cookies['django_language'] = 'fr'
        antwort = self.c.get(f'/neu/mandate/{self.md.id}/mahnstufen/')
        self.assertContains(antwort, 'Frais de rappel (CHF)')
        self.assertNotContains(antwort, 'Mahngebühr (CHF)')


class AdminEigentuemerTests(TestCase):

    def test_eigentuemer_im_admin(self):
        from crm.models import Eigentuemer
        md = Eigentuemer.objects.create(organisation=_test_organisation(), firma_oder_name='Stiftung Aare')
        admin = get_user_model().objects.create_superuser('admin_vorlagen', 'a@example.ch', 'x')
        c = Client()
        c.force_login(admin)
        antwort = c.get(f'/admin/crm/eigentuemer/{md.id}/change/')
        self.assertEqual(antwort.status_code, 200)
        self.assertContains(antwort, 'Stiftung Aare')
