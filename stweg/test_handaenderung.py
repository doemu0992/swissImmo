"""Handänderung, Verzugszins (Vorgabe), Fonds-offen im Portal, Datenprüfung auf der Gemeinschaftsseite."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.tests._helfer import _team_user
from crm.models import Eigentuemer
from stweg import eigentuemer, inkasso, vorgaben
from stweg.models import StwegAkonto, StwegEigentuemerwechsel
from stweg.test_budget import haus_mit_eigentuemern
from stweg.test_inkasso import jahr_budget, pdf_text

D = Decimal
HEUTE = date(2026, 6, 30)


class WechselTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]                                    # Bruno, 200.00 je Quartalsrate
        self.neu = Eigentuemer.objects.create(firma_oder_name='Nina Neu', email='nina@x.ch')
        jahr_budget(self.lg, 2026)                            # Raten 1.1., 1.4., 1.7., 1.10.

    def test_eigentuemer_am_vor_und_nach_dem_wechsel(self):
        eigentuemer.wechseln(self.b, self.neu, date(2026, 4, 1))
        self.assertEqual(eigentuemer.eigentuemer_am(self.b, date(2026, 3, 31)), self.eigs[1].pk)
        self.assertEqual(eigentuemer.eigentuemer_am(self.b, date(2026, 4, 1)), self.neu.pk)     # Übergang 00:00
        self.assertEqual(eigentuemer.eigentuemer_am(self.b, date(2027, 1, 1)), self.neu.pk)
        self.b.refresh_from_db()
        self.assertEqual(self.b.stockwerkeigentuemer, self.neu)

    def test_ohne_wechsel_aendert_sich_nichts(self):
        self.assertEqual(eigentuemer.eigentuemer_am(self.b, date(2020, 1, 1)), self.eigs[1].pk)

    def test_zwei_wechsel_hintereinander(self):
        dritte = Eigentuemer.objects.create(firma_oder_name='Dora Drittens')
        eigentuemer.wechseln(self.b, self.neu, date(2026, 4, 1))
        eigentuemer.wechseln(self.b, dritte, date(2026, 8, 1))
        self.assertEqual([eigentuemer.eigentuemer_am(self.b, d) for d in
                          (date(2026, 1, 1), date(2026, 5, 1), date(2026, 7, 31), date(2026, 8, 1), date(2026, 9, 1))],
                         [self.eigs[1].pk, self.neu.pk, self.neu.pk, dritte.pk, dritte.pk])

    def test_ungueltige_wechsel(self):
        with self.assertRaises(eigentuemer.WechselFehler):
            eigentuemer.wechseln(self.b, self.eigs[1], date(2026, 4, 1))          # derselbe
        with self.assertRaises(eigentuemer.WechselFehler):
            eigentuemer.wechseln(self.b, self.neu, None)
        eigentuemer.wechseln(self.b, self.neu, date(2026, 4, 1))
        with self.assertRaises(eigentuemer.WechselFehler):                         # nicht nach dem letzten
            eigentuemer.wechseln(self.b, self.eigs[0], date(2026, 3, 1))
        self.assertEqual(StwegEigentuemerwechsel.objects.count(), 1)

    def test_miteigentuemer_werden_geloescht(self):
        self.b.miteigentuemer.add(self.eigs[2])
        eigentuemer.wechseln(self.b, self.neu, date(2026, 4, 1))
        self.assertEqual(self.b.miteigentuemer.count(), 0)

    def test_schuldner_je_forderung_und_mahnung_nur_an_den_aktuellen(self):
        eigentuemer.wechseln(self.b, self.neu, date(2026, 4, 1))
        f = inkasso.forderungen(self.b, HEUTE)
        self.assertEqual([c['schuldner'] for c in f], [self.eigs[1].pk, self.neu.pk])   # 1.1. alt, 1.4. neu
        self.assertEqual(inkasso.offener_betrag(self.b, HEUTE), D('400.00'))
        self.assertEqual(inkasso.offener_betrag_eigentuemer(self.b, HEUTE), D('200.00'))
        m = inkasso.mahnung_erstellen(self.b, heute=HEUTE)
        self.assertEqual(m.betrag, D('200.00'))
        text = '\n'.join(inkasso.mahntext(m))
        self.assertIn('01.04.2026', text)
        self.assertNotIn('01.01.2026', text)

    def test_nur_altforderung_keine_mahnung_aber_pfandrecht(self):
        StwegAkonto.objects.create(einheit=self.b, betrag=D('200'), datum=date(2026, 4, 2))   # tilgt die älteste
        eigentuemer.wechseln(self.b, self.neu, date(2026, 5, 1))
        # offen bleibt die Rate vom 1.4.? Nein: FIFO tilgte 1.1.; 1.4. (Schuldner: bisheriger) bleibt offen
        self.assertEqual(inkasso.offener_betrag_eigentuemer(self.b, HEUTE), D('0.00'))
        with self.assertRaises(inkasso.InkassoFehler) as ctx:
            inkasso.mahnung_erstellen(self.b, heute=HEUTE)
        self.assertIn('früheren Eigentümer', str(ctx.exception))
        fall = inkasso.StwegInkassoFall.objects.create(einheit=self.b, eroeffnet_am=HEUTE)
        pf = inkasso.pfandrecht_anmelden(fall, stichtag=HEUTE, ohne_mahnungen=True)
        self.assertEqual(pf.betrag_pfandberechtigt, D('200.00'))                  # haftet am Anteil

    def test_abrechnung_nimmt_den_eigentuemer_der_abrechnung(self):
        from stweg.models import StwegAbrechnung, StwegAbrechnungPosition
        a = StwegAbrechnung.objects.create(liegenschaft=self.lg, jahr=2025, status=StwegAbrechnung.STATUS_ABGESCHLOSSEN)
        StwegAbrechnungPosition.objects.create(abrechnung=a, einheit=self.b, eigentuemer=self.eigs[1],
                                               wertquote=200, wertquote_total=1000, kostenanteil=D('500'), akonto=D('0'), saldo=D('500'))
        eigentuemer.wechseln(self.b, self.neu, date(2025, 6, 1))                  # vor dem 31.12.2025
        f = [c for c in inkasso.forderungen(self.b, HEUTE) if c['art'] == 'abrechnung']
        self.assertEqual(f[0]['schuldner'], self.eigs[1].pk)                     # steht so in der Abrechnung


class VerzugszinsTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        jahr_budget(self.lg, 2026)

    def test_ohne_satz_keine_zinsen(self):
        self.assertIsNone(inkasso.verzugszins(self.b, HEUTE))

    def test_zins_auf_offenen_betrag_tage_durch_365(self):
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'})
        z = inkasso.verzugszins(self.b, date(2026, 4, 11))      # Rate 1.1. (200): 100 Tage
        self.assertEqual(z['zeilen'][0]['tage'], 100)
        self.assertEqual(z['zeilen'][0]['zins'], (D('200') * D('0.05') * 100 / 365).quantize(D('0.01')))
        self.assertEqual(z['zeilen'][0]['zins'], D('2.74'))
        self.assertEqual(len(z['zeilen']), 2)                   # 1.4.: 10 Tage
        self.assertFalse(z['bestaetigt'])

    def test_bezahlte_raten_verzinsen_nicht(self):
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'})
        StwegAkonto.objects.create(einheit=self.b, betrag=D('400'), datum=date(2026, 4, 5))
        self.assertEqual(inkasso.verzugszins(self.b, date(2026, 4, 11))['total'], D('0.00'))

    def test_mahnung_nennt_zins_erst_nach_bestaetigung(self):
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'})
        m = inkasso.mahnung_erstellen(self.b, heute=date(2026, 4, 11))
        self.assertNotIn('Verzugszins', '\n'.join(inkasso.mahntext(m)))
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'}, bestaetigen=True)
        text = '\n'.join(inkasso.mahntext(m))
        self.assertIn('Verzugszins von 5 %', text)
        self.assertNotIn('ündig', text)

    def test_aenderung_nimmt_die_bestaetigung_zurueck(self):
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'}, bestaetigen=True)
        v = vorgaben.speichern(self.lg, {'verzugszins_prozent': '4.5'})
        self.assertIsNone(v.bestaetigt_am)

    def test_ungueltiger_satz(self):
        for roh in ('abc', '-1', '101'):
            with self.assertRaises(vorgaben.VorgabenFehler):
                vorgaben.speichern(self.lg, {'verzugszins_prozent': roh})

    def test_pfandsumme_enthaelt_nie_zinsen(self):
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'}, bestaetigen=True)
        p = inkasso.pfandberechtigt(self.b, date(2026, 12, 31))
        self.assertEqual(p['pfandberechtigt'], inkasso.offener_betrag(self.b, date(2026, 12, 31)))


class OberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        self.neu = Eigentuemer.objects.create(firma_oder_name='Nina Neu')
        self.client.force_login(_team_user('Verwaltung'))

    def test_wechsel_ueber_die_seite(self):
        r = self.client.post(f'/neu/stweg/{self.lg.pk}/einheiten/wechsel/',
                             {'einheit': self.b.pk, 'neu': self.neu.pk, 'datum': '2026-04-01'}, follow=True)
        self.assertContains(r, 'Handänderung erfasst')
        self.b.refresh_from_db()
        self.assertEqual(self.b.stockwerkeigentuemer, self.neu)
        self.assertContains(self.client.get(f'/neu/stweg/{self.lg.pk}/einheiten/'), 'Nina Neu')

    def test_lesende_duerfen_nicht_wechseln(self):
        c = self.client_class()
        c.force_login(_team_user('Lesend'))
        c.post(f'/neu/stweg/{self.lg.pk}/einheiten/wechsel/',
               {'einheit': self.b.pk, 'neu': self.neu.pk, 'datum': '2026-04-01'})
        self.assertEqual(StwegEigentuemerwechsel.objects.count(), 0)

    def test_fremde_einheit_wird_nicht_gewechselt(self):
        _, ae, _ = haus_mit_eigentuemern()
        self.client.post(f'/neu/stweg/{self.lg.pk}/einheiten/wechsel/',
                         {'einheit': ae[1].pk, 'neu': self.neu.pk, 'datum': '2026-04-01'})
        self.assertEqual(StwegEigentuemerwechsel.objects.count(), 0)

    def test_gemeinschaftsseite_zeigt_befunde(self):
        self.e[0].wertquote = self.e[0].wertquote + 1
        self.e[0].save()
        self.assertContains(self.client.get(f'/neu/stweg/{self.lg.pk}/'), 'Prüfung der Daten')

    def test_vorgabenseite_speichert_den_zinssatz(self):
        self.client.post(f'/neu/stweg/{self.lg.pk}/vorgaben/speichern/', {'verzugszins_prozent': '5'})
        self.assertEqual(vorgaben.vorgaben_von(self.lg).verzugszins_prozent, D('5'))

    def test_inkassoseite_zeigt_altforderung_und_zins(self):
        jahr_budget(self.lg, 2025)
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'})
        eigentuemer.wechseln(self.b, self.neu, date(2025, 5, 1))
        r = self.client.get(f'/neu/stweg/{self.lg.pk}/inkasso/')
        self.assertContains(r, 'früheren Eigentümer')
        self.assertContains(r, 'Verzugszins zu 5')


class PortalFondsOffenTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from stweg.fonds import jahreseinlage_belasten
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        u = get_user_model().objects.create_user(username='bruno_portal', password='x')
        self.eigs[1].benutzer = u
        self.eigs[1].save()
        self.client.force_login(u)
        jahreseinlage_belasten(self.lg, 2026, D('10000'), datum=date(2026, 1, 15))    # Bruno: 200/1000 = 2000

    def test_offene_einlage_steht_im_portal_und_verschwindet_nach_zahlung(self):
        self.assertContains(self.client.get('/portal/stweg/'), 'davon noch offen CHF')
        StwegAkonto.objects.create(einheit=self.b, betrag=D('2000'), datum=date(2026, 2, 5), zweck='fonds')
        self.assertNotContains(self.client.get('/portal/stweg/'), 'davon noch offen')
