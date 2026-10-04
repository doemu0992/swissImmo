"""Einheiten, Wertquoten und Eigentümer einer STWEG zuteilen — und der Weg dorthin."""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from core.tests._helfer import _team_user, _test_organisation
from crm.models import Eigentuemer
from portfolio.models import Einheit, Liegenschaft
from stweg.tests import neue_stweg


class EinheitenSeiteTests(TestCase):
    def setUp(self):
        self.lg, self.e = neue_stweg(quoten=(200, 300, 500))             # Entwurf
        self.client.force_login(_team_user('Verwaltung'))
        self.url = f'/neu/stweg/{self.lg.pk}/einheiten/'
        self.anna = Eigentuemer.objects.create(firma_oder_name='Anna', email='a@x.ch')
        self.bruno = Eigentuemer.objects.create(firma_oder_name='Bruno')

    def test_seite_zeigt_stand_und_einheiten(self):
        seite = self.client.get(self.url)
        self.assertContains(seite, 'Wertquoten 1000 / 1000')
        self.assertContains(seite, 'Whg 1')
        self.assertContains(seite, '3 Einheit(en) ohne Eigentümer')
        self.assertContains(seite, 'Gemeinschaft aktivieren')

    def test_speichern_setzt_quote_und_eigentuemer(self):
        self.client.post(self.url + 'speichern/', {
            f'quote_{self.e[0].pk}': '250', f'eig_{self.e[0].pk}': self.anna.pk,
            f'quote_{self.e[1].pk}': '250', f'eig_{self.e[1].pk}': self.bruno.pk,
            f'quote_{self.e[2].pk}': '500,00', f'eig_{self.e[2].pk}': ''})
        for e in self.e:
            e.refresh_from_db()
        self.assertEqual([e.wertquote for e in self.e], [Decimal('250'), Decimal('250'), Decimal('500')])
        self.assertEqual([e.stockwerkeigentuemer for e in self.e], [self.anna, self.bruno, None])

    def test_eine_ungueltige_eingabe_verwirft_alles(self):
        r = self.client.post(self.url + 'speichern/', {
            f'quote_{self.e[0].pk}': '250', f'eig_{self.e[0].pk}': self.anna.pk,
            f'quote_{self.e[1].pk}': 'viel'}, follow=True)
        self.assertContains(r, 'ungültig')
        self.e[0].refresh_from_db()
        self.assertEqual((self.e[0].wertquote, self.e[0].stockwerkeigentuemer), (Decimal('200'), None))

    def test_negative_und_riesige_quoten_werden_abgelehnt(self):
        for wert in ('-5', '1000000'):
            self.client.post(self.url + 'speichern/', {f'quote_{self.e[0].pk}': wert})
        self.e[0].refresh_from_db()
        self.assertEqual(self.e[0].wertquote, Decimal('200'))

    def test_fremder_eigentuemer_ist_nicht_zuteilbar(self):
        from core.tenancy import organisation_kontext
        from crm.models import Organisation
        fremd = Organisation.objects.create(firma='Fremd AG', strasse='X 1', plz='9000', ort='SG')
        with organisation_kontext(fremd):
            f_eig = Eigentuemer.objects.create(firma_oder_name='Fritz')
        r = self.client.post(self.url + 'speichern/', {f'eig_{self.e[0].pk}': f_eig.pk}, follow=True)
        self.assertContains(r, 'nicht (mehr) erfasst')
        self.e[0].refresh_from_db()
        self.assertIsNone(self.e[0].stockwerkeigentuemer)

    def test_einheit_hinzufuegen(self):
        self.client.post(self.url + 'neu/', {'bezeichnung': 'Whg 4', 'wertquote': '0', 'etage': '2. OG',
                                             'eigentuemer': self.anna.pk})
        e = Einheit.objects.get(bezeichnung='Whg 4')
        self.assertEqual((e.typ, e.wertquote, e.stockwerkeigentuemer, e.liegenschaft), ('stwe', 0, self.anna, self.lg))
        self.client.post(self.url + 'neu/', {'bezeichnung': '', 'wertquote': '5'})
        self.client.post(self.url + 'neu/', {'bezeichnung': 'X', 'wertquote': 'abc'})
        self.assertEqual(Einheit.objects.filter(liegenschaft=self.lg).count(), 4)

    def test_eigentuemer_erfassen(self):
        self.client.post(self.url.replace('einheiten/', 'eigentuemer/neu/'),
                         {'name': 'Carla Muster', 'email': 'c@x.ch', 'sprache': 'fr'})
        c = Eigentuemer.objects.get(firma_oder_name='Carla Muster')
        self.assertEqual((c.email, c.sprache), ('c@x.ch', 'fr'))
        self.assertContains(self.client.get(self.url), 'Carla Muster')
        self.client.post(self.url.replace('einheiten/', 'eigentuemer/neu/'), {'name': ' ', 'sprache': 'xx'})
        self.assertEqual(Eigentuemer.objects.filter(firma_oder_name=' ').count(), 0)

    def test_aktivieren_nur_wenn_die_summe_aufgeht(self):
        self.e[0].wertquote = Decimal('199')
        self.e[0].save()
        r = self.client.post(f'/neu/stweg/{self.lg.pk}/aktivieren/', follow=True)
        self.assertContains(r, '999/1000')
        self.lg.refresh_from_db()
        self.assertEqual(self.lg.status, 'entwurf')
        self.client.post(self.url + 'speichern/', {f'quote_{self.e[0].pk}': '200'})
        r = self.client.post(f'/neu/stweg/{self.lg.pk}/aktivieren/', follow=True)
        self.assertContains(r, 'Die Gemeinschaft ist aktiv')
        self.lg.refresh_from_db()
        self.assertEqual(self.lg.status, 'aktiv')

    def test_nebenraeume_werden_getrennt_angezeigt_und_nicht_gezaehlt(self):
        Einheit.objects.create(liegenschaft=self.lg, bezeichnung='Keller 1', typ='bas', gehoert_zu=self.e[0])
        seite = self.client.get(self.url)
        self.assertContains(seite, 'Keller 1 → Whg 1')
        self.assertContains(seite, 'Wertquoten 1000 / 1000')
        self.assertNotContains(seite, 'name="quote_%d"' % Einheit.objects.get(bezeichnung='Keller 1').pk)

    def test_lesezugriff_darf_nicht_aendern(self):
        self.client.force_login(_team_user('Lesend'))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        for pfad in ('einheiten/speichern/', 'einheiten/neu/', 'eigentuemer/neu/', 'aktivieren/'):
            self.assertEqual(self.client.post(f'/neu/stweg/{self.lg.pk}/{pfad}', {}).status_code, 403, pfad)

    def test_mietliegenschaft_hat_keine_einheitenseite(self):
        miete = Liegenschaft.objects.create(strasse='M 1', plz='8000', ort='Z', organisation=_test_organisation())
        self.assertEqual(self.client.get(f'/neu/stweg/{miete.pk}/einheiten/').status_code, 404)


class WegDorthinTests(TestCase):
    """Liegenschaft anlegen → Art STWEG → Zuteilung."""
    BASIS = {'strasse': 'Neuweg 5', 'plz': '8000', 'ort': 'Zürich'}

    def setUp(self):
        self.client.force_login(_team_user('Verwaltung'))
        self.mandat = Eigentuemer.objects.create(firma_oder_name='Altmandat')

    def test_stweg_ignoriert_den_eigentuemer_und_leitet_zur_zuteilung(self):
        r = self.client.post('/neu/liegenschaften/neu/', {**self.BASIS, 'typ': 'STWEG',
                                                        'eigentuemer_id': self.mandat.pk})
        lg = Liegenschaft.objects.get(strasse='Neuweg 5')
        self.assertRedirects(r, f'/neu/stweg/{lg.pk}/einheiten/')
        self.assertEqual((lg.typ, lg.status, lg.eigentuemer), ('STWEG', 'entwurf', None))

    def test_miete_behaelt_ihren_eigentuemer_und_den_alten_weg(self):
        r = self.client.post('/neu/liegenschaften/neu/', {**self.BASIS, 'typ': 'MIETE',
                                                        'eigentuemer_id': self.mandat.pk})
        lg = Liegenschaft.objects.get(strasse='Neuweg 5')
        self.assertRedirects(r, f'/neu/liegenschaften/{lg.pk}/')
        self.assertEqual(lg.eigentuemer, self.mandat)

    def test_formular_blendet_eigentuemer_bei_stweg_aus(self):
        seite = self.client.get('/neu/liegenschaften/neu/')
        self.assertContains(seite, 'id="eigentuemer_block"')
        self.assertContains(seite, 'id="stweg_hinweis"')

    def test_neue_einheit_einer_stweg_im_objektformular_hat_quote_null(self):
        lg, _ = neue_stweg()
        self.client.post('/neu/objekte/neu/', {'liegenschaft_id': lg.pk, 'bezeichnung': 'Neu', 'typ': 'stwe'})
        self.assertEqual(Einheit.objects.get(bezeichnung='Neu').wertquote, Decimal('0'))
        self.client.post('/neu/objekte/neu/', {'liegenschaft_id': lg.pk, 'bezeichnung': 'Mit', 'typ': 'stwe',
                                               'wertquote': '75'})
        self.assertEqual(Einheit.objects.get(bezeichnung='Mit').wertquote, Decimal('75'))

    def test_neue_einheit_einer_mietliegenschaft_behaelt_die_vorgabe(self):
        miete = Liegenschaft.objects.create(strasse='M 1', plz='8000', ort='Z', organisation=_test_organisation())
        self.client.post('/neu/objekte/neu/', {'liegenschaft_id': miete.pk, 'bezeichnung': 'Miet', 'typ': 'whg'})
        self.assertEqual(Einheit.objects.get(bezeichnung='Miet').wertquote, Decimal('10'))

    def test_gwr_import_setzt_nur_neu_importierte_einheiten_einer_stweg_auf_null(self):
        def import_(lg):
            Einheit.objects.create(liegenschaft=lg, bezeichnung='GWR 1', typ='whg')
            Einheit.objects.create(liegenschaft=lg, bezeichnung='GWR 2', typ='whg')
            return {'egid_found': '123', 'units_created': 2, 'error': None}
        with mock.patch('portfolio.services.sync_liegenschaft_with_gwr', side_effect=import_):
            self.client.post('/neu/liegenschaften/neu/', {**self.BASIS, 'typ': 'STWEG', 'gwr_import': 'on'})
        for name in ('GWR 1', 'GWR 2'):
            e = Einheit.objects.get(bezeichnung=name)
            self.assertEqual((e.wertquote, e.typ), (Decimal('0'), 'stwe'), name)

    def test_gwr_import_laesst_eine_mietliegenschaft_unberuehrt(self):
        def import_(lg):
            Einheit.objects.create(liegenschaft=lg, bezeichnung='GWR M', typ='whg')
            return {'egid_found': '9', 'units_created': 1, 'error': None}
        with mock.patch('portfolio.services.sync_liegenschaft_with_gwr', side_effect=import_):
            self.client.post('/neu/liegenschaften/neu/', {**self.BASIS, 'gwr_import': 'on'})
        e = Einheit.objects.get(bezeichnung='GWR M')
        self.assertEqual((e.wertquote, e.typ), (Decimal('10'), 'whg'))

    def test_gwr_import_fasst_bereits_vorhandene_einheiten_nicht_an(self):
        lg, e = neue_stweg(quoten=(10, 990))                       # echte Quote 10 bei Einheit 1
        def import_(lg_):
            Einheit.objects.create(liegenschaft=lg_, bezeichnung='GWR neu', typ='whg')
            return {'egid_found': '5', 'units_created': 1, 'error': None}
        with mock.patch('portfolio.services.sync_liegenschaft_with_gwr', side_effect=import_):
            self.client.post(f'/neu/liegenschaften/{lg.pk}/bearbeiten/',
                             {**self.BASIS, 'typ': 'STWEG', 'gwr_import': 'on'})
        e[0].refresh_from_db()
        self.assertEqual(e[0].wertquote, Decimal('10'))             # blieb stehen
        self.assertEqual(Einheit.objects.get(bezeichnung='GWR neu').wertquote, Decimal('0'))
