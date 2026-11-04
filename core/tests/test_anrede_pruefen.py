"""Liste «Anrede prüfen» in der Personenliste: Privatpersonen mit unbestätigtem «Herr».

Bis PR #161 war «Herr» die Vorgabe der Anrede; ein bestehendes «Herr» kann falsch sein. Die Liste zeigt
genau diese Personen, je Zeile eine Schnellauswahl (POST), und exportiert sie als CSV.
"""
import csv
import io

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.models import AktivitaetsLog
from core.tenancy import organisation_kontext
from crm.models import Mieter, Mitgliedschaft

from ._isolation import MandantenFixture

LISTE = '/neu/personen/?anrede=pruefen'


def _mieter(fix, **felder):
    with organisation_kontext(fix.organisation):
        return Mieter.objects.create(**felder)


def _frisch(fix, m):
    with organisation_kontext(fix.organisation):
        return Mieter.objects.get(pk=m.pk)


class AnredePruefenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')
        cls.herr = _mieter(cls.a, typ='person', vorname='Hans', nachname='Zzaltherr', anrede='Herr',
                           email='hans@example.ch')
        cls.frau = _mieter(cls.a, typ='person', vorname='Eva', nachname='Zzfrau', anrede='Frau')
        cls.leer = _mieter(cls.a, typ='person', vorname='Kim', nachname='Zzleer', anrede='')
        cls.firma = _mieter(cls.a, typ='firma', firmen_name='Muster AG', anrede='Herr')
        cls.verein = _mieter(cls.a, typ='verein', firmen_name='Verein Gelb', anrede='Herr')
        cls.bestaetigt = _mieter(cls.a, typ='person', vorname='Otto', nachname='Zzbestaetigt',
                                 anrede='Herr', anrede_geprueft=True)
        # Die Mieter der Fixture tragen «Herr»; sie sollen die Zählungen unten nicht stören.
        for fix in (cls.a, cls.b):
            with organisation_kontext(fix.organisation):
                Mieter.objects.filter(pk=fix.mieter.pk).update(anrede_geprueft=True)
        cls.fremd = _mieter(cls.b, typ='person', vorname='Franz', nachname='Zzfremd', anrede='Herr')

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.a.benutzer)

    def _zeile(self, m):
        return f'action="/neu/personen/{m.pk}/anrede/"'

    def _liste(self, url=LISTE):
        return self.c.get(url).content.decode()

    # --- Liste ---------------------------------------------------------------

    def test_zeigt_nur_unbestaetigte_herr_privatpersonen_der_eigenen_verwaltung(self):
        html = self._liste()
        self.assertIn('Zzaltherr', html)
        for nicht in ('Zzfrau', 'Zzleer', 'Muster AG', 'Verein Gelb', 'Zzbestaetigt', 'Zzfremd'):
            self.assertNotIn(nicht, html, f'«{nicht}» gehört nicht in die Liste «Anrede prüfen».')

    def test_reiter_nennt_die_anzahl_und_fremde_zaehlen_nicht(self):
        # `herr` aus A; die Fixture-Mieter beider Verwaltungen tragen keine Anrede.
        html = self._liste('/neu/personen/')
        self.assertIn('Anrede prüfen (1)', html)

    def test_reiter_fehlt_wenn_nichts_zu_pruefen_ist(self):
        c = Client()
        c.force_login(self.b.benutzer)
        with organisation_kontext(self.b.organisation):
            Mieter.objects.filter(pk=self.fremd.pk).update(anrede_geprueft=True)
        self.assertNotIn('Anrede prüfen', c.get('/neu/personen/').content.decode())

    def test_leerer_zustand(self):
        c = Client()
        c.force_login(self.b.benutzer)
        with organisation_kontext(self.b.organisation):
            Mieter.objects.filter(pk=self.fremd.pk).update(anrede='')
        html = c.get(LISTE).content.decode()
        self.assertIn('Alles geprüft', html)

    def test_zeile_hat_drei_schaltflaechen_und_csrf(self):
        html = self._liste()
        self.assertIn(f'action="/neu/personen/{self.herr.pk}/anrede/"', html)
        for wert in ('Herr', 'Frau', ''):
            self.assertIn(f'name="anrede" value="{wert}"', html)
        self.assertIn('csrfmiddlewaretoken', html)

    # --- Schnellauswahl ------------------------------------------------------

    def _setzen(self, m, wert, **extra):
        return self.c.post(f'/neu/personen/{m.pk}/anrede/', {'anrede': wert, 'zurueck': LISTE, **extra})

    def test_frau_waehlen(self):
        r = self._setzen(self.herr, 'Frau')
        self.assertRedirects(r, LISTE, fetch_redirect_response=False)
        m = _frisch(self.a, self.herr)
        self.assertEqual((m.anrede, m.anrede_geprueft), ('Frau', True))
        self.assertNotIn(self._zeile(self.herr), self._liste())

    def test_herr_bestaetigen_bleibt_herr_und_verschwindet(self):
        self._setzen(self.herr, 'Herr')
        m = _frisch(self.a, self.herr)
        self.assertEqual((m.anrede, m.anrede_geprueft), ('Herr', True))
        self.assertNotIn(self._zeile(self.herr), self._liste())

    def test_keine_anrede(self):
        self._setzen(self.herr, '')
        m = _frisch(self.a, self.herr)
        self.assertEqual((m.anrede, m.anrede_geprueft), ('', True))
        self.assertNotIn(self._zeile(self.herr), self._liste())

    def test_wahl_wird_protokolliert(self):
        self._setzen(self.herr, 'Frau')
        with organisation_kontext(self.a.organisation):
            eintrag = AktivitaetsLog.objects.filter(aktion='Anrede geprüft').get()
        self.assertIn('Herr → Frau', eintrag.details)

    def test_ungueltiger_wert_aendert_nichts(self):
        self._setzen(self.herr, 'Familie')
        m = _frisch(self.a, self.herr)
        self.assertEqual((m.anrede, m.anrede_geprueft), ('Herr', False))

    def test_nur_post(self):
        self.assertEqual(self.c.get(f'/neu/personen/{self.herr.pk}/anrede/').status_code, 405)

    def test_ohne_csrf_token_abgewiesen(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.a.benutzer)
        r = c.post(f'/neu/personen/{self.herr.pk}/anrede/', {'anrede': 'Frau'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(_frisch(self.a, self.herr).anrede, 'Herr')

    def test_firma_hat_keine_anrede(self):
        self.assertEqual(self._setzen(self.firma, 'Frau').status_code, 404)
        self.assertEqual(_frisch(self.a, self.firma).anrede, 'Herr')

    def test_lesezugriff_darf_nicht_schreiben(self):
        u = get_user_model().objects.create_user(username='nur_lesen', password='x', email='l@example.ch')
        Mitgliedschaft.objects.create(benutzer=u, organisation=self.a.organisation,
                                      rolle=Mitgliedschaft.ROLLE_LESEZUGRIFF)
        c = Client()
        c.force_login(u)
        r = c.post(f'/neu/personen/{self.herr.pk}/anrede/', {'anrede': 'Frau'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(_frisch(self.a, self.herr).anrede, 'Herr')

    def test_kein_offener_redirect(self):
        for ziel in ('https://boese.example/', '//boese.example/', '/neu/dashboard/'):
            r = self._setzen(self.herr, 'Herr', zurueck=ziel)
            self.assertEqual(r['Location'], LISTE, ziel)

    # --- Mandantengrenze -----------------------------------------------------

    def test_fremde_person_ist_404_und_unveraendert(self):
        r = self._setzen(self.fremd, 'Frau')
        self.assertEqual(r.status_code, 404)
        with organisation_kontext(self.b.organisation):
            m = Mieter.objects.get(pk=self.fremd.pk)
        self.assertEqual((m.anrede, m.anrede_geprueft), ('Herr', False))

    # --- CSV -----------------------------------------------------------------

    def test_csv_enthaelt_dieselbe_liste(self):
        r = self.c.get(LISTE + '&export=csv')
        self.assertEqual(r.status_code, 200)
        zeilen = list(csv.reader(io.StringIO(r.content.decode('utf-8-sig')), delimiter=';'))
        self.assertEqual(zeilen[0], ['Name', 'Objekt', 'Anrede', 'E-Mail'])
        self.assertEqual(len(zeilen), 2, zeilen)
        self.assertIn('Zzaltherr', zeilen[1][0])
        self.assertEqual(zeilen[1][2:], ['Herr', 'hans@example.ch'])
        with organisation_kontext(self.a.organisation):
            self.assertTrue(AktivitaetsLog.objects.filter(aktion__contains='Anrede prüfen').exists())

    # --- Anrede aus dem Personenformular ------------------------------------

    def _form(self, m=None, **felder):
        daten = {'typ': 'person', 'nachname': 'Neu', 'vorname': 'Nora', 'anrede': '', **felder}
        url = f'/neu/personen/{m.pk}/bearbeiten/' if m else '/neu/personen/neu/'
        return self.c.post(url, {**daten, 'dublette_ok': '1'})

    def test_neue_person_mit_gewaehlter_anrede_gilt_als_geprueft(self):
        self._form(anrede='Herr')
        with organisation_kontext(self.a.organisation):
            m = Mieter.objects.get(nachname='Neu')
        self.assertEqual((m.anrede, m.anrede_geprueft), ('Herr', True))

    def test_neue_person_ohne_anrede_bleibt_ungeprueft(self):
        self._form()
        with organisation_kontext(self.a.organisation):
            m = Mieter.objects.get(nachname='Neu')
        self.assertEqual((m.anrede, m.anrede_geprueft), ('', False))

    def test_bearbeiten_ohne_anredeaenderung_bestaetigt_nicht(self):
        self._form(self.herr, nachname='Zzaltherr', vorname='Hans', anrede='Herr', ort='Bern')
        m = _frisch(self.a, self.herr)
        self.assertEqual((m.ort, m.anrede, m.anrede_geprueft), ('Bern', 'Herr', False))

    def test_bearbeiten_mit_anredeaenderung_gilt_als_geprueft(self):
        self._form(self.herr, nachname='Zzaltherr', vorname='Hans', anrede='Frau')
        m = _frisch(self.a, self.herr)
        self.assertEqual((m.anrede, m.anrede_geprueft), ('Frau', True))
