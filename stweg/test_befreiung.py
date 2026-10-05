"""Abweichende Kostenverteilung (Art. 712h Abs. 3 ZGB): Befreiung einzelner Einheiten — mit Begründung, auf den Rappen."""
import random
from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.tests._helfer import _team_user
from stweg import integritaet
from stweg.models import StwegBefreiung
from stweg.schluessel import (SchluesselFehler, befreiung_aufheben, befreien, gewichte, kostenart_zuordnen, verteile)
from stweg.services import StwegAbrechnungService
from stweg.test_schluessel import konto
from stweg.tests import neue_stweg, rechnung

D = Decimal


class BefreiungTests(TestCase):
    def setUp(self):
        # Erdgeschoss 200/1000, dazu 300, 250, 250.
        self.lg, self.e = neue_stweg(quoten=(200, 300, 250, 250), status='aktiv')
        self.eg = self.e[0]

    def test_liftkosten_5000_ohne_erdgeschoss_auf_die_restlichen_800(self):
        s = befreien(self.lg, 'Lift', [self.eg], 'Reglement Art. 9: Das Erdgeschoss nutzt den Lift nicht')
        g = gewichte(s)
        self.assertEqual(g[self.eg.pk], 0)
        self.assertEqual(sum(g.values()), D('800'))                                   # neue Basis: 800 = 100 %
        anteile, _ = verteile(D('5000'), s)
        self.assertEqual(anteile[self.eg.pk], D('0.00'))
        self.assertEqual([anteile[e.pk] for e in self.e[1:]], [D('1875.00'), D('1562.50'), D('1562.50')])
        self.assertEqual(sum(anteile.values()), D('5000.00'))

    def test_durch_die_ganze_jahresabrechnung(self):
        k = konto('4200', 'Lift')
        kostenart_zuordnen(self.lg, k, befreien(self.lg, 'Lift', [self.eg], 'Reglement Art. 9'))
        rechnung(self.lg, 5000, date(2026, 5, 1), konto=k)
        a = StwegAbrechnungService(self.lg).abrechnen(2026)
        kosten = {p.einheit.bezeichnung: p.kostenanteil for p in a.positionen.select_related('einheit')}
        self.assertEqual(kosten, {'Whg 1': D('0.00'), 'Whg 2': D('1875.00'), 'Whg 3': D('1562.50'),
                                  'Whg 4': D('1562.50')})
        self.assertEqual(sum(kosten.values()), a.gesamtkosten)

    def test_keine_rundungsfehler_bei_beliebigen_betraegen_und_quoten(self):
        zufall = random.Random(2026)
        for _ in range(60):
            lg, e = neue_stweg(quoten=self._quoten(zufall), status='aktiv')
            s = befreien(lg, 'Lift', [e[0]], 'Reglement Art. 9')
            for _ in range(30):
                betrag = D(zufall.randrange(1, 9_000_000)) / 100
                anteile, g = verteile(betrag, s)
                self.assertEqual(anteile[e[0].pk], D('0.00'))
                self.assertEqual(sum(anteile.values()), betrag.quantize(D('0.01')), betrag)
                total = sum(g.values())
                for pk, a in anteile.items():
                    self.assertLessEqual(abs(a - betrag * g[pk] / total), D('0.01'))

    @staticmethod
    def _quoten(zufall):
        a = zufall.randrange(100, 300)
        rest = 1000 - a
        b = zufall.randrange(50, rest - 100)
        c = zufall.randrange(30, rest - b - 30)
        return (a, b, c, rest - b - c)

    def test_begruendung_ist_pflicht_und_wird_festgehalten(self):
        for grund in ('', '   ', None):
            with self.assertRaises(SchluesselFehler):
                befreien(self.lg, 'Lift', [self.eg], grund)
        self.assertFalse(self.lg.stweg_schluessel.filter(name='Lift').exists())       # nichts halb angelegt
        befreien(self.lg, 'Lift', [self.eg], 'Beschluss vom 3.5.2024, Traktandum 4')
        b = StwegBefreiung.objects.get()
        self.assertEqual((b.einheit, b.begruendung), (self.eg, 'Beschluss vom 3.5.2024, Traktandum 4'))

    def test_alle_befreien_verteilt_nichts(self):
        with self.assertRaises(SchluesselFehler):
            befreien(self.lg, 'Lift', self.e, 'Reglement')
        self.assertFalse(StwegBefreiung.objects.exists())

    def test_ohne_einheit_und_fremde_einheit(self):
        with self.assertRaises(SchluesselFehler):
            befreien(self.lg, 'Lift', [], 'Reglement')
        _, fremd = neue_stweg(name='Fremd', quoten=(500, 500), status='aktiv')
        with self.assertRaises(SchluesselFehler):
            befreien(self.lg, 'Lift', [fremd[0]], 'Reglement')

    def test_zweite_befreiung_ergaenzt_die_erste(self):
        befreien(self.lg, 'Lift', [self.eg], 'Reglement Art. 9')
        s = befreien(self.lg, 'Lift', [self.e[1]], 'Beschluss 2025')
        g = gewichte(s)
        self.assertEqual((g[self.e[0].pk], g[self.e[1].pk], g[self.e[2].pk]), (0, 0, 250))
        self.assertEqual(StwegBefreiung.objects.count(), 2)

    def test_aufheben_stellt_die_wertquote_wieder_her(self):
        s = befreien(self.lg, 'Lift', [self.eg], 'Reglement Art. 9')
        befreiung_aufheben(StwegBefreiung.objects.get())
        self.assertEqual(gewichte(s)[self.eg.pk], D('200'))

    def test_audit_warnt_vor_nullanteil_ohne_begruendung(self):
        from stweg.schluessel import lift_schluessel
        lift_schluessel(self.lg)                                                      # EG = 0, ohne Begründung
        self.eg.etage = 'EG'
        self.eg.save()
        lift_schluessel(self.lg, name='Lift2')
        self.assertTrue(any('ohne dass eine Begründung' in t for _, t in integritaet.pruefe(self.lg)))
        lift_schluessel(self.lg, name='Lift2', begruendung='Reglement Art. 9')
        lift_schluessel(self.lg, name='Lift', begruendung='Reglement Art. 9')
        self.assertFalse(any('ohne dass eine Begründung' in t for _, t in integritaet.pruefe(self.lg)))


class OberflaecheTests(TestCase):
    def setUp(self):
        self.lg, self.e = neue_stweg(quoten=(200, 300, 250, 250), status='aktiv')
        self.c = self.client_class()
        self.c.force_login(_team_user('Verwaltung'))
        self.url = f'/neu/stweg/{self.lg.pk}/schluessel/befreien/'

    def test_befreien_ueber_die_seite(self):
        r = self.c.post(self.url, {'name': 'Lift', 'einheit': [self.e[0].pk], 'begruendung': 'Reglement Art. 9'},
                        follow=True)
        self.assertContains(r, 'Befreiung festgehalten')
        self.assertContains(r, 'Reglement Art. 9')
        self.assertEqual(StwegBefreiung.objects.count(), 1)
        b = StwegBefreiung.objects.get()
        r = self.c.post(f'/neu/stweg/befreiung/{b.pk}/aufheben/', follow=True)
        self.assertContains(r, 'Befreiung aufgehoben')
        self.assertFalse(StwegBefreiung.objects.exists())

    def test_ohne_begruendung_wird_nichts_gespeichert(self):
        r = self.c.post(self.url, {'name': 'Lift', 'einheit': [self.e[0].pk], 'begruendung': ''}, follow=True)
        self.assertContains(r, 'braucht die Begründung')
        self.assertFalse(StwegBefreiung.objects.exists())

    def test_lesende_duerfen_nicht(self):
        c = self.client_class()
        c.force_login(_team_user('Lesend'))
        c.post(self.url, {'name': 'Lift', 'einheit': [self.e[0].pk], 'begruendung': 'x'})
        self.assertFalse(StwegBefreiung.objects.exists())

    def test_unbekannte_befreiung_ist_404(self):
        self.assertEqual(self.c.post('/neu/stweg/befreiung/999999/aufheben/').status_code, 404)
