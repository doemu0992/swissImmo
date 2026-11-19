"""Toast mit «Rückgängig» (UI-Zielbild, Entscheid 19.11.2026): Schritt erledigt → Knopf → wieder offen.

Die Handlung läuft sofort; der Knopf ruft die Rücknahme. Mandantentrennung: ein fremder Schritt ist nicht erreichbar.
"""
from django.test import Client, TestCase

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from core.templatetags.zeichen import rueckgaengig_url
from types import SimpleNamespace

from .test_arbeitsvorrat import _fall_mit_frist


class RueckgaengigToastTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def setUp(self):
        with mandant(self.a.organisation):
            self.fall, self.schritt = _fall_mit_frist(self.a.organisation, 2, 'Abhaken')
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def _frisch(self):
        self.schritt.refresh_from_db()
        return self.schritt

    def test_erledigt_zeigt_den_toast_mit_rueckgaengig(self):
        with mandant(self.a.organisation):
            r = self.c.post(f'/neu/fallschritte/{self.schritt.pk}/erledigen/', follow=True)
        self.assertContains(r, 'Rückgängig')
        self.assertContains(r, f'/neu/fallschritte/{self.schritt.pk}/wiederoeffnen/')
        self.assertIsNotNone(self._frisch().erledigt_am)

    def test_rueckgaengig_oeffnet_den_schritt_wieder(self):
        with mandant(self.a.organisation):
            self.c.post(f'/neu/fallschritte/{self.schritt.pk}/erledigen/')
            r = self.c.post(f'/neu/fallschritte/{self.schritt.pk}/wiederoeffnen/', follow=True)
        self.assertEqual(r.status_code, 200)
        s = self._frisch()
        self.assertIsNone(s.erledigt_am)
        self.assertIsNone(s.erledigt_durch)
        self.assertContains(r, 'ist wieder offen')

    def test_zweimal_rueckgaengig_aendert_nichts(self):
        with mandant(self.a.organisation):
            r = self.c.post(f'/neu/fallschritte/{self.schritt.pk}/wiederoeffnen/', follow=True)
        self.assertContains(r, 'ist schon offen')

    def test_get_ist_nicht_erlaubt(self):
        with mandant(self.a.organisation):
            r = self.c.get(f'/neu/fallschritte/{self.schritt.pk}/wiederoeffnen/')
        self.assertEqual(r.status_code, 405)

    def test_ein_fremder_mandant_kommt_nicht_heran(self):
        with mandant(self.a.organisation):
            self.c.post(f'/neu/fallschritte/{self.schritt.pk}/erledigen/')
        fremd = Client()
        fremd.force_login(self.b.benutzer)
        with mandant(self.b.organisation):
            r = fremd.post(f'/neu/fallschritte/{self.schritt.pk}/wiederoeffnen/')
        self.assertEqual(r.status_code, 404)
        self.assertIsNotNone(self._frisch().erledigt_am)

    def test_filter_nimmt_nur_interne_pfade(self):
        ok = SimpleNamespace(extra_tags='rueckgaengig:/neu/x/')
        self.assertEqual(rueckgaengig_url(ok), '/neu/x/')
        for boese in ('rueckgaengig:https://evil.example/', 'rueckgaengig://evil.example/', 'rueckgaengig:/andere/'):
            self.assertEqual(rueckgaengig_url(SimpleNamespace(extra_tags=boese)), '', boese)
        self.assertEqual(rueckgaengig_url(SimpleNamespace(extra_tags='')), '')
