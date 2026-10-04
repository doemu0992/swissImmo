"""Verteilschlüssel: Lift ohne Erdgeschoss, Heizung nach Fläche, Allgemeines nach Wertquote."""
import random
from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.tests._helfer import _test_organisation
from finance.models import Buchungskonto
from portfolio.models import Einheit, Liegenschaft
from stweg.models import StwegAbrechnungAnteil, StwegSchluessel
from stweg.schluessel import (SchluesselFehler, gewichte, kostenart_zuordnen, lift_schluessel,
                              manuellen_schluessel_setzen, standard_schluessel, verteile)
from stweg.services import AbrechnungsFehler, StwegAbrechnungService
from stweg.tests import rechnung

D = Decimal


def haus():
    """Fünf Einheiten, 1000/1000. EG, 1. OG, 2. OG, 3. OG, Attika."""
    lg = Liegenschaft.objects.create(strasse='Liftweg 5', plz='8000', ort='Zürich', typ='STWEG',
                                     status='entwurf', wertquote_total=1000,
                                     organisation=_test_organisation())
    daten = [('Whg EG', 'EG', 150, 60), ('Whg 1.OG', '1. OG', 200, 80), ('Whg 2.OG', '2. OG', 250, 100),
             ('Whg 3.OG', '3. OG', 200, 80), ('Attika', 'Attika', 200, 80)]
    einheiten = [Einheit.objects.create(liegenschaft=lg, bezeichnung=b, typ='stwe', etage=et,
                                        wertquote=D(q), flaeche_m2=D(m2), volumen_m3=D(m2) * 3)
                 for b, et, q, m2 in daten]
    lg.status = 'aktiv'
    lg.save()
    return lg, einheiten


def konto(nummer, name):
    return Buchungskonto.objects.create(organisation=_test_organisation(), nummer=nummer,
                                        bezeichnung=name, typ='aufwand')


class SchluesselTests(TestCase):
    def setUp(self):
        self.lg, self.e = haus()
        self.eg = self.e[0]

    def test_lift_schluessel_schliesst_das_erdgeschoss_aus(self):
        s = lift_schluessel(self.lg)
        g = gewichte(s)
        self.assertEqual(g[self.eg.pk], 0)
        self.assertEqual([g[e.pk] for e in self.e[1:]], [200, 250, 200, 200])

    def test_eg_zahlt_nie_einen_rappen_lift(self):
        s = lift_schluessel(self.lg)
        zufall = random.Random(7)
        for _ in range(400):
            betrag = D(zufall.randrange(1, 10_000_000)) / 100
            anteile, _ = verteile(betrag, s)
            self.assertEqual(anteile[self.eg.pk], D('0.00'), betrag)
            self.assertEqual(sum(anteile.values()), betrag.quantize(D('0.01')), betrag)

    def test_jeder_schluessel_geht_auf_den_rappen_auf(self):
        zufall = random.Random(11)
        flaeche = StwegSchluessel.objects.create(liegenschaft=self.lg, name='Heizung m²', art='flaeche')
        volumen = StwegSchluessel.objects.create(liegenschaft=self.lg, name='Heizung m³', art='volumen')
        standard = standard_schluessel(self.lg)
        for s in (flaeche, volumen, standard, lift_schluessel(self.lg)):
            for _ in range(200):
                betrag = D(zufall.randrange(1, 5_000_000)) / 100
                anteile, g = verteile(betrag, s)
                self.assertEqual(sum(anteile.values()), betrag.quantize(D('0.01')))
                # Nie weiter als 1 Rappen vom exakten Anteil entfernt.
                total = sum(g.values())
                for pk, a in anteile.items():
                    self.assertLessEqual(abs(a - betrag * g[pk] / total), D('0.01'))

    def test_fehlende_flaeche_ist_ein_fehler_keine_stille_null(self):
        self.e[2].flaeche_m2 = None
        self.e[2].save()
        s = StwegSchluessel.objects.create(liegenschaft=self.lg, name='Heizung', art='flaeche')
        with self.assertRaises(SchluesselFehler) as ctx:
            gewichte(s)
        self.assertIn('Whg 2.OG', str(ctx.exception))

    def test_fehlender_anteil_im_manuellen_schluessel_ist_ein_fehler(self):
        s = manuellen_schluessel_setzen(self.lg, 'Garten', {self.e[1]: 1, self.e[2]: 1})
        with self.assertRaises(SchluesselFehler):
            gewichte(s)

    def test_nur_ein_standardschluessel_und_fremde_einheit_abgelehnt(self):
        from django.db import IntegrityError, transaction
        standard_schluessel(self.lg)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StwegSchluessel.objects.create(liegenschaft=self.lg, name='Zweiter', ist_standard=True)
        fremd_lg, fremd_e = haus()
        with self.assertRaises(SchluesselFehler):
            manuellen_schluessel_setzen(self.lg, 'X', {fremd_e[0]: 1})

    def test_unbegrenzt_viele_schluessel(self):
        for i in range(25):
            manuellen_schluessel_setzen(self.lg, f'Schlüssel {i}', {e: i + 1 for e in self.e})
        self.assertEqual(self.lg.stweg_schluessel.count(), 25)


class AbrechnungMitSchluesselnTests(TestCase):
    def setUp(self):
        self.lg, self.e = haus()
        self.k_allg, self.k_lift, self.k_heiz = (konto('4100', 'Versicherung'), konto('4200', 'Lift'),
                                                 konto('4300', 'Heizung'))
        kostenart_zuordnen(self.lg, self.k_lift, lift_schluessel(self.lg))
        heiz = StwegSchluessel.objects.create(liegenschaft=self.lg, name='Heizkosten (m²)', art='flaeche')
        kostenart_zuordnen(self.lg, self.k_heiz, heiz)
        self.d = date(2026, 5, 1)

    def abrechnen(self):
        return StwegAbrechnungService(self.lg).abrechnen(2026)

    def betraege(self, a):
        return {p.einheit.bezeichnung: p.kostenanteil for p in a.positionen.select_related('einheit')}

    def test_drei_schluessel_in_einer_abrechnung(self):
        rechnung(self.lg, 1000, self.d, konto=self.k_allg)        # → Wertquote (Standard)
        rechnung(self.lg, 850, self.d, konto=self.k_lift)         # → Lift (EG = 0)
        rechnung(self.lg, 900, self.d, konto=self.k_heiz)         # → Fläche
        a = self.abrechnen()
        self.assertEqual(a.gesamtkosten, D('2750.00'))
        self.assertEqual(self.betraege(a), {
            'Whg EG': D('285.00'), 'Whg 1.OG': D('580.00'), 'Whg 2.OG': D('725.00'),
            'Whg 3.OG': D('580.00'), 'Attika': D('580.00')})
        self.assertEqual(sum(p.kostenanteil for p in a.positionen.all()), a.gesamtkosten)

    def test_eg_traegt_keine_liftkosten_und_der_beleg_zeigt_es(self):
        rechnung(self.lg, 850, self.d, konto=self.k_lift)
        a = self.abrechnen()
        p = a.positionen.get(einheit=self.e[0])
        self.assertEqual(p.kostenanteil, D('0.00'))
        t = StwegAbrechnungAnteil.objects.get(position=p)
        self.assertEqual((t.schluessel_name, t.gewicht, t.kosten_total, t.betrag),
                         ('Lift', D('0'), D('850.00'), D('0.00')))

    def test_ohne_zuordnung_verhaelt_es_sich_wie_bisher(self):
        rechnung(self.lg, 1000, self.d)                           # kein Konto
        a = self.abrechnen()
        self.assertEqual(self.betraege(a)['Whg EG'], D('150.00'))
        self.assertEqual(a.kostenzeilen.get().schluessel_name, 'Allgemeine Wertquote')

    def test_positionen_einer_rechnung_laufen_je_konto_zum_eigenen_schluessel(self):
        from finance.models import KreditorPosition, KreditorenRechnung
        r = KreditorenRechnung.objects.create(liegenschaft=self.lg, lieferant='Hauswart AG',
                                              betrag=D('1850'), datum=self.d, status='freigegeben')
        KreditorPosition.objects.create(rechnung=r, konto=self.k_allg, liegenschaft=self.lg,
                                        betrag=D('1000'), bezeichnung='Reinigung')
        KreditorPosition.objects.create(rechnung=r, konto=self.k_lift, liegenschaft=self.lg,
                                        betrag=D('850'), bezeichnung='Liftservice')
        a = self.abrechnen()
        self.assertEqual(self.betraege(a)['Whg EG'], D('150.00'))      # nur der allgemeine Teil
        self.assertEqual(self.betraege(a)['Whg 2.OG'], D('500.00'))    # 250 + 250

    def test_lueckenhafter_schluessel_verhindert_die_abrechnung(self):
        self.e[1].flaeche_m2 = None
        self.e[1].save()
        rechnung(self.lg, 900, self.d, konto=self.k_heiz)
        with self.assertRaises(AbrechnungsFehler):
            self.abrechnen()
        self.assertFalse(self.lg.stweg_abrechnungen.exists())

    def test_beliebige_beträge_summieren_sich_exakt(self):
        zufall = random.Random(3)
        for _ in range(30):
            from finance.models import KreditorenRechnung
            KreditorenRechnung.objects.all().delete()
            for k in (self.k_allg, self.k_lift, self.k_heiz):
                rechnung(self.lg, D(zufall.randrange(100, 999_999)) / 100, self.d, konto=k)
            a = self.abrechnen()
            self.assertEqual(sum(p.kostenanteil for p in a.positionen.all()), a.gesamtkosten)
            self.assertEqual(a.positionen.get(einheit=self.e[0]).schluesselanteile
                             .get(schluessel_name='Lift').betrag, D('0.00'))
