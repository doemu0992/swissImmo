"""Vollmachten: erteilen, widerrufen, und was sie an der Versammlung bewirken."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.tests._helfer import _team_user
from stweg import beschluss
from stweg.models import Anwesenheit, Vollmacht
from stweg.test_versammlung import sonnenblick, versammlung
from stweg.versammlung import durchfuehren, einladung_versenden
from stweg.vollmacht import VollmachtFehler, erteilen, gueltige, widerrufen

User = get_user_model()


class VollmachtServiceTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = versammlung(self.lg)

    def test_erst_nach_der_einladung(self):
        with self.assertRaises(VollmachtFehler):
            erteilen(self.v, self.e[0], 'Max')
        einladung_versenden(self.v)
        self.assertEqual(erteilen(self.v, self.e[0], 'Max').bevollmaechtigter, 'Max')

    def test_neue_vollmacht_ersetzt_die_alte_und_die_alte_bleibt_belegt(self):
        einladung_versenden(self.v)
        erteilen(self.v, self.e[0], 'Max')
        erteilen(self.v, self.e[0], 'Moritz')
        self.assertEqual([x.bevollmaechtigter for x in gueltige(self.v)], ['Moritz'])
        self.assertEqual(Vollmacht.objects.filter(einheit=self.e[0]).count(), 2)

    def test_name_pflicht_und_einheit_der_gemeinschaft(self):
        from stweg.tests import neue_stweg
        einladung_versenden(self.v)
        with self.assertRaises(VollmachtFehler):
            erteilen(self.v, self.e[0], '  ')
        fremd_lg, fremd_e = neue_stweg(name='Andere')
        with self.assertRaises(VollmachtFehler):
            erteilen(self.v, fremd_e[0], 'Max')

    def test_widerruf_und_sperre_nach_der_versammlung(self):
        einladung_versenden(self.v)
        vm = erteilen(self.v, self.e[0], 'Max')
        widerrufen(vm)
        self.assertEqual(gueltige(self.v).count(), 0)
        vm2 = erteilen(self.v, self.e[1], 'Eva')
        durchfuehren(self.v)
        with self.assertRaises(VollmachtFehler):
            widerrufen(vm2)
        with self.assertRaises(VollmachtFehler):
            erteilen(self.v, self.e[2], 'Zu spät')

    def test_durchfuehren_erfasst_vertretene_einheiten_die_dann_stimmen_duerfen(self):
        einladung_versenden(self.v)
        erteilen(self.v, self.e[0], 'Max')
        durchfuehren(self.v)
        a = Anwesenheit.objects.get(versammlung=self.v, einheit=self.e[0])
        self.assertEqual((a.art, a.vertreter), ('vertreten', 'Max'))
        self.assertEqual(Anwesenheit.objects.get(versammlung=self.v, einheit=self.e[1]).art, 'abwesend')
        t = self.v.traktanden.get()
        beschluss.stimme_abgeben(t, self.e[0], 'ja')                  # vertreten → stimmberechtigt
        with self.assertRaises(beschluss.BeschlussFehler):
            beschluss.stimme_abgeben(t, self.e[1], 'ja')              # abwesend → nicht

    def test_widerrufene_vollmacht_zaehlt_nicht(self):
        einladung_versenden(self.v)
        widerrufen(erteilen(self.v, self.e[0], 'Max'))
        durchfuehren(self.v)
        self.assertEqual(Anwesenheit.objects.get(versammlung=self.v, einheit=self.e[0]).art, 'abwesend')


class VollmachtOberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = versammlung(self.lg)
        einladung_versenden(self.v)
        self.client.force_login(_team_user('Verwaltung'))

    def test_verwaltung_erfasst_und_widerruft(self):
        r = self.client.post(f'/neu/stweg/versammlung/{self.v.pk}/vollmacht/neu/',
                             {'einheit': self.e[0].pk, 'bevollmaechtigter': 'Max Muster'}, follow=True)
        self.assertContains(r, 'Max Muster')
        vm = Vollmacht.objects.get()
        self.assertEqual(vm.kanal, 'verwaltung')
        self.client.post(f'/neu/stweg/vollmacht/{vm.pk}/widerrufen/')
        vm.refresh_from_db()
        self.assertFalse(vm.gueltig)

    def test_lesezugriff_darf_nicht(self):
        self.client.force_login(_team_user('Lesend'))
        r = self.client.post(f'/neu/stweg/versammlung/{self.v.pk}/vollmacht/neu/', {})
        self.assertEqual(r.status_code, 403)


class VollmachtPortalTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = sonnenblick()
        self.v = versammlung(self.lg)
        einladung_versenden(self.v)
        self.c = {}
        for eig in self.eigs:
            u = User.objects.create_user(username=f'v_{eig.firma_oder_name}', password='x')
            eig.benutzer = u
            eig.save()
            cl = Client()
            cl.force_login(u)
            self.c[eig.firma_oder_name] = cl

    def test_eigentuemer_erteilt_und_widerruft(self):
        r = self.c['Anna'].post(f'/portal/stweg/vollmacht/{self.v.pk}/erteilen/',
                                {'einheit': self.e[0].pk, 'bevollmaechtigter': 'Tante Trudi'}, follow=True)
        self.assertContains(r, 'Tante Trudi')
        vm = Vollmacht.objects.get()
        self.assertEqual((vm.erteilt_von, vm.kanal), (self.eigs[0], 'portal'))
        self.c['Anna'].post(f'/portal/stweg/vollmacht/{vm.pk}/widerrufen/')
        vm.refresh_from_db()
        self.assertFalse(vm.gueltig)

    def test_nur_fuer_die_eigene_einheit(self):
        r = self.c['Anna'].post(f'/portal/stweg/vollmacht/{self.v.pk}/erteilen/',
                                {'einheit': self.e[1].pk, 'bevollmaechtigter': 'Eindringling'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Vollmacht.objects.count(), 0)

    def test_fremde_vollmacht_nicht_widerrufbar(self):
        vm = erteilen(self.v, self.e[0], 'Max')                      # Annas Vollmacht
        r = self.c['Bruno'].post(f'/portal/stweg/vollmacht/{vm.pk}/widerrufen/')
        self.assertEqual(r.status_code, 404)
        vm.refresh_from_db()
        self.assertTrue(vm.gueltig)

    def test_nach_der_versammlung_keine_vollmacht_mehr(self):
        durchfuehren(self.v)
        r = self.c['Anna'].post(f'/portal/stweg/vollmacht/{self.v.pk}/erteilen/',
                                {'einheit': self.e[0].pk, 'bevollmaechtigter': 'Zu spät'}, follow=True)
        self.assertEqual(Vollmacht.objects.count(), 0)
        self.assertContains(r, 'nach der Einladung und vor der Versammlung')
