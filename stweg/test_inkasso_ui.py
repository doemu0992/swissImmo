"""Inkasso-Oberfläche, Integritätsprüfung, Stockwerk-Liftschlüssel, Zahlungserfassung."""
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.tests._helfer import _team_user
from stweg import hauptbuch, integritaet, inkasso
from stweg.models import StwegAkonto, StwegInkassoFall, StwegPfandrecht
from stweg.schluessel import SchluesselFehler, etage_nummer, gewichte, lift_nach_stockwerk
from stweg.test_budget import haus_mit_eigentuemern
from stweg.test_inkasso import jahr_budget, pdf_text

D = Decimal


class EtageNummerTests(TestCase):
    def test_lesbare_schreibweisen(self):
        for text, nr in [('EG', 0), ('Erdgeschoss', 0), ('Parterre', 0), ('0', 0), ('1. OG', 1), ('2.OG', 2),
                         ('3 OG', 3), ('4', 4)]:
            self.assertEqual(etage_nummer(text), nr, text)

    def test_unlesbares_wird_nicht_geraten(self):
        for text in ('Attika', 'DG', 'UG', '', None, 'Maisonette'):
            self.assertIsNone(etage_nummer(text), text)


class LiftNachStockwerkTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()

    def test_gewicht_ist_die_stockwerknummer(self):
        for i, e in enumerate(self.e):
            e.etage = ['EG', '1. OG', '2. OG', '3. OG', '4. OG'][i]
            e.save()
        s = lift_nach_stockwerk(self.lg)
        self.assertEqual(sorted(gewichte(s).values()), [D('0'), D('1'), D('2'), D('3'), D('4')])

    def test_unlesbare_etage_bricht_ab_und_nennt_sie(self):
        self.e[0].etage = 'Attika'
        self.e[0].save()
        with self.assertRaises(SchluesselFehler) as ctx:
            lift_nach_stockwerk(self.lg)
        self.assertIn('Attika', str(ctx.exception))


class ZahlungErfassenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]

    def test_betrag_muss_positiv_sein(self):
        with self.assertRaises(Exception):
            hauptbuch.zahlung_erfassen(self.b, D('0'), date(2026, 1, 5))

    def test_fremde_rate_wird_abgelehnt(self):
        bud = jahr_budget(self.lg, 2026)
        fremd = bud.vorschreibungen.exclude(einheit=self.b).first()
        with self.assertRaises(Exception):
            hauptbuch.zahlung_erfassen(self.b, D('100'), date(2026, 1, 5), vorschreibung=fremd)
        self.assertEqual(StwegAkonto.objects.count(), 0)


class IntegritaetTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        jahr_budget(self.lg, 2026)

    def test_sauberes_haus_ohne_fehler(self):
        stufen = [s for s, _ in integritaet.pruefe(self.lg)]
        self.assertNotIn(integritaet.FEHLER, stufen)

    def test_wertquote_ungleich_1000_ist_fehler(self):
        self.e[0].wertquote = self.e[0].wertquote + 1
        self.e[0].save()
        self.assertIn(integritaet.FEHLER, [s for s, _ in integritaet.pruefe(self.lg)])

    def test_einheit_ohne_eigentuemer_warnt(self):
        self.e[2].stockwerkeigentuemer = None
        self.e[2].save()
        self.assertIn(integritaet.WARNUNG, [s for s, _ in integritaet.pruefe(self.lg)])

    def test_zahlung_ohne_buchung_wird_gefunden(self):
        StwegAkonto.objects.create(einheit=self.e[1], betrag=D('50'), datum=date(2026, 2, 1))
        self.assertTrue(any('Buchung' in t for _, t in integritaet.pruefe(self.lg)))

    def test_hauptbuch_differenz_wird_gefunden(self):
        hauptbuch.zahlung_erfassen(self.e[1], D('50'), date(2026, 2, 1))
        self.assertTrue(integritaet.abgestimmt(self.lg))
        StwegAkonto.objects.filter(einheit=self.e[1]).update(betrag=D('60'))     # Fachtabelle weicht ab
        self.assertFalse(integritaet.abgestimmt(self.lg))

    def test_kommando_meldet_fehler_per_exit_code(self):
        call_command('stweg_audit', liegenschaft=self.lg.pk, stdout=StringIO())
        self.e[0].wertquote = self.e[0].wertquote + 1
        self.e[0].save()
        with self.assertRaises(SystemExit):
            call_command('stweg_audit', liegenschaft=self.lg.pk, stdout=StringIO())


class InkassoOberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern(iban='CH9300762011623852957')
        self.b = self.e[1]
        jahr_budget(self.lg, 2025)
        self.client.force_login(_team_user('Verwaltung'))
        self.basis = f'/neu/stweg/{self.lg.pk}/inkasso/'

    def test_seite_zeigt_offene_einheit_und_keine_kuendigung(self):
        r = self.client.get(self.basis)
        self.assertContains(r, self.b.bezeichnung)
        self.assertNotContains(r, '257d')
        self.assertContains(r, 'keine Kündigungsandrohung')

    def test_mahnen_retention_pfandrecht_und_pdfs(self):
        self.client.post(self.basis + 'mahnen/', {'einheit': self.b.pk, 'frist_tage': '10'})
        fall = StwegInkassoFall.objects.get()
        m = fall.mahnungen.get()
        r = self.client.get(f'/neu/stweg/mahnung/{m.pk}/pdf/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertNotIn('ündig', pdf_text(r.content))
        self.client.post(self.basis + 'retention/', {'einheit': self.b.pk, 'gegenstaende': 'Fahrrad im Keller',
                                                     'ohne_mahnungen': '1'})
        fall.refresh_from_db()
        self.assertIsNotNone(fall.retention_erklaert_am)
        self.assertEqual(self.client.get(f'/neu/stweg/inkassofall/{fall.pk}/pdf/')['Content-Type'], 'application/pdf')
        self.client.post(self.basis + 'pfandrecht/', {'einheit': self.b.pk, 'ohne_mahnungen': '1'})
        pf = StwegPfandrecht.objects.get()
        self.assertIn('Pfandsumme', pdf_text(self.client.get(f'/neu/stweg/pfandrecht/{pf.pk}/pdf/').content))
        self.client.post(f'/neu/stweg/pfandrecht/{pf.pk}/eingetragen/', {'datum': '2026-06-01'})
        pf.refresh_from_db()
        self.assertIsNotNone(pf.eingetragen_am)

    def test_pfandrecht_ohne_fall_wird_abgelehnt(self):
        self.client.post(self.basis + 'pfandrecht/', {'einheit': self.b.pk})
        self.assertEqual(StwegPfandrecht.objects.count(), 0)

    def test_nur_lesende_duerfen_nichts_ausloesen(self):
        c = self.client_class()
        c.force_login(_team_user('Lesend'))
        c.post(self.basis + 'mahnen/', {'einheit': self.b.pk})
        self.assertEqual(StwegInkassoFall.objects.count(), 0)

    def test_einheit_ausserhalb_der_gemeinschaft_wird_nicht_gemahnt(self):
        andere, ae, _ = haus_mit_eigentuemern()
        self.client.post(self.basis + 'mahnen/', {'einheit': ae[1].pk})
        self.assertEqual(StwegInkassoFall.objects.count(), 0)
        self.assertEqual(inkasso.offener_fall(ae[1]), None)
