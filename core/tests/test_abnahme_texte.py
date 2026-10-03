"""Wortlaut der Schlussbestimmungen je Verwaltung (Einstellung und PDF).

Der Standardtext ist der einer einzelnen Verwaltung. Jede muss ihren eigenen
hinterlegen können, ohne den einer anderen zu berühren.
"""
from datetime import date

from django.test import Client, TestCase

from core.services import abnahme_texte as T
from ._helfer import _basis_objekte, _team_user
from ._isolation import MandantenFixture
from .test_abnahme_kette import _protokoll

URL = '/neu/abnahme-texte/'


def _eigene():
    from rentals.models import AbnahmeText
    return dict(AbnahmeText.objects.values_list('schluessel', 'text'))


class TexteEinstellungTests(TestCase):

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())

    def test_seite_zeigt_den_standard(self):
        r = self.c.get(URL)
        self.assertEqual(r.status_code, 200)
        for k, (_titel, standard) in T.ABSAETZE.items():
            self.assertContains(r, standard[:60])
        self.assertNotContains(r, 'Eigener Wortlaut')

    def test_abweichender_text_wird_gespeichert_und_angezeigt(self):
        self.c.post(URL, {'text_haftung': '  Eigene   Haftungsklausel.  '})
        self.assertEqual(_eigene(), {'haftung': 'Eigene Haftungsklausel.'})
        r = self.c.get(URL)
        self.assertContains(r, 'Eigene Haftungsklausel.')
        self.assertContains(r, 'Eigener Wortlaut')

    def test_leer_oder_standardtext_stellt_den_standard_wieder_her(self):
        self.c.post(URL, {'text_haftung': 'Eigen', 'text_depot': 'Eigen2'})
        self.assertEqual(set(_eigene()), {'haftung', 'depot'})
        self.c.post(URL, {'text_haftung': '', 'text_depot': T.MIETZINSDEPOT})
        self.assertEqual(_eigene(), {})

    def test_zu_langer_text_wird_nicht_gespeichert(self):
        r = self.c.post(URL, {'text_haftung': 'x' * (T.MAX_LAENGE + 1), 'text_depot': 'ok'}, follow=True)
        self.assertEqual(_eigene(), {'depot': 'ok'})              # der gültige geht durch, der lange nicht
        self.assertContains(r, 'Zu lang')

    def test_lesezugriff_sieht_aber_aendert_nichts_und_fremde_kommen_nicht_hinein(self):
        c = Client(); c.force_login(_team_user('Lesend'))
        self.assertEqual(c.get(URL).status_code, 200)
        c.post(URL, {'text_haftung': 'x'})
        self.assertEqual(_eigene(), {})
        from django.contrib.auth import get_user_model
        fremd = get_user_model().objects.create_user(username='ohne_mitgliedschaft', password='x')
        c2 = Client(); c2.force_login(fremd)
        self.assertEqual(c2.get(URL).status_code, 403)
        self.assertEqual(c2.post(URL, {'text_haftung': 'x'}).status_code, 403)
        self.assertEqual(_eigene(), {})


class TexteImProtokollTests(TestCase):

    def setUp(self):
        self.lg, self.einheit, self.mieter, self.v1 = _basis_objekte()

    def _absaetze(self, typ='auszug'):
        prot = _protokoll(self.v1, typ, date(2026, 6, 30), [('Bad', 'Dusche', 'io', '')])
        return dict(T.schlussbestimmungen(prot))

    def test_ohne_eigenen_text_gilt_der_standard(self):
        a = self._absaetze()
        self.assertEqual(a['Haftung'], T.HAFTUNG)
        self.assertEqual(a['Mietzinsdepot'], T.MIETZINSDEPOT)
        self.assertEqual(self._absaetze('einzug')['Mängel'], T.MAENGEL_EINZUG)

    def test_eigener_text_ersetzt_nur_diesen_absatz(self):
        from rentals.models import AbnahmeText
        AbnahmeText.objects.create(schluessel='haftung', text='Unser Wortlaut.')
        a = self._absaetze()
        self.assertEqual(a['Haftung'], 'Unser Wortlaut.')
        self.assertEqual(a['Mietzinsdepot'], T.MIETZINSDEPOT)

    def test_eigener_text_steht_im_pdf(self):
        import io
        import pdfplumber
        from core.services.abnahme_pdf import generate_abnahme_pdf
        from rentals.models import AbnahmeText
        AbnahmeText.objects.create(schluessel='haftung', text='Unser Wortlaut zur Haftung.')
        prot = _protokoll(self.v1, 'auszug', date(2026, 6, 30), [('Bad', 'Dusche', 'io', '')])
        with pdfplumber.open(io.BytesIO(generate_abnahme_pdf(prot))) as d:
            text = '\n'.join(s.extract_text() or '' for s in d.pages)
        self.assertIn('Unser Wortlaut zur Haftung.', text)
        self.assertNotIn(T.HAFTUNG[:40], text)


class TexteMandantenTests(TestCase):
    """Verwaltung A schreibt; Verwaltung B bleibt unberührt."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')

    def test_text_von_a_gilt_nicht_fuer_b(self):
        from core.tenancy import organisation_kontext
        from rentals.models import Abnahmeprotokoll, AbnahmeText
        with organisation_kontext(self.a.organisation):
            AbnahmeText.objects.create(schluessel='haftung', text='Wortlaut von A')
        with organisation_kontext(self.b.organisation):
            prot_b = Abnahmeprotokoll.objects.create(vertrag=self.b.vertrag, typ='auszug', datum=date(2026, 6, 30))
            self.assertEqual(dict(T.schlussbestimmungen(prot_b))['Haftung'], T.HAFTUNG)
        with organisation_kontext(self.a.organisation):
            prot_a = Abnahmeprotokoll.objects.create(vertrag=self.a.vertrag, typ='auszug', datum=date(2026, 6, 30))
            self.assertEqual(dict(T.schlussbestimmungen(prot_a))['Haftung'], 'Wortlaut von A')

    def test_speichern_in_a_aendert_b_nicht_und_b_sieht_a_nicht(self):
        from core.tenancy import organisation_kontext
        from rentals.models import AbnahmeText
        ca = Client(); ca.force_login(self.a.benutzer)
        cb = Client(); cb.force_login(self.b.benutzer)
        ca.post(URL, {'text_haftung': 'Nur für A'})
        with organisation_kontext(self.b.organisation):
            self.assertEqual(AbnahmeText.objects.count(), 0)
        self.assertNotContains(cb.get(URL), 'Nur für A')
        self.assertContains(ca.get(URL), 'Nur für A')
        cb.post(URL, {'text_haftung': 'Nur für B'})
        with organisation_kontext(self.a.organisation):
            self.assertEqual(AbnahmeText.objects.get(schluessel='haftung').text, 'Nur für A')
