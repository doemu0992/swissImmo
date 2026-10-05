"""Handänderungs-Abrechnung: taggenaue Aufteilung (pro rata temporis) zwischen Verkäufer und Käufer."""
import io
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from pypdf import PdfReader

from core.tests._helfer import _team_user
from crm.models import Eigentuemer
from stweg import budget as bd
from stweg import eigentuemer, handaenderung, hauptbuch, vorgaben
from stweg.models import StwegAkonto, StwegBudget
from stweg.schluessel import standard_schluessel
from stweg.test_budget import haus_mit_eigentuemern
from stweg.test_inkasso import jahr_budget

D = Decimal


def monatsbudget(lg, jahr, total):
    b = StwegBudget.objects.create(liegenschaft=lg, jahr=jahr, raten=12, erste_faelligkeit=date(jahr, 1, 1))
    bd.position_setzen(b, f'Budget {jahr}', standard_schluessel(lg), D(total))
    bd.vorlegen(b)
    bd.budget_genehmigen(b)
    return b


class TageTests(TestCase):
    def test_tage_am_14_september(self):
        self.assertEqual(handaenderung.tage_aufteilung(2026, date(2026, 9, 14)), (256, 109, 365))   # 1.1.–13.9. | 14.9.–31.12.
        self.assertEqual(handaenderung.tage_aufteilung(2028, date(2028, 9, 14)), (257, 109, 366))   # Schaltjahr

    def test_grenzen_des_jahres(self):
        self.assertEqual(handaenderung.tage_aufteilung(2026, date(2026, 1, 1)), (0, 365, 365))      # alles der Käufer
        self.assertEqual(handaenderung.tage_aufteilung(2026, date(2026, 12, 31)), (364, 1, 365))    # ein Tag der Käufer


class AufteilungTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]                                     # 200/1000
        self.verkaeufer = self.eigs[1]
        self.kaeufer = Eigentuemer.objects.create(firma_oder_name='Kim Käufer', email='kim@x.ch')

    def _wechsel(self, datum):
        return eigentuemer.wechseln(self.b, self.kaeufer, datum)

    def test_12000_franken_verkauf_am_14_september(self):
        b = monatsbudget(self.lg, 2026, 60000)                 # 200/1000 → 12'000 im Jahr, 12 × 1000
        raten = list(b.vorschreibungen.filter(einheit=self.b).order_by('faellig_am'))
        self.assertEqual([v.betrag for v in raten], [D('1000.00')] * 12)
        w = self._wechsel(date(2026, 9, 14))
        for v in raten:                                         # jede Rate am Fälligkeitstag, vom damaligen Eigentümer
            hauptbuch.zahlung_erfassen(self.b, v.betrag, v.faellig_am, vorschreibung=v)
        a = handaenderung.aufteilung(w, stichtag=date(2026, 12, 31))
        self.assertEqual(a['jahresbetrag'], D('12000.00'))
        self.assertEqual((a['verkaeufer_tage'], a['kaeufer_tage']), (256, 109))
        self.assertEqual(a['verkaeufer_anteil'], D('8416.44'))        # 12000 × 256/365 = 8416.4383
        self.assertEqual(a['kaeufer_anteil'], D('3583.56'))
        self.assertEqual(a['verkaeufer_anteil'] + a['kaeufer_anteil'], D('12000.00'))
        self.assertEqual((a['akonto_verkaeufer'], a['akonto_kaeufer']), (D('9000.00'), D('3000.00')))   # Jan–Sep | Okt–Dez
        self.assertEqual(a['saldo_verkaeufer'], D('-583.56'))         # der Verkäufer hat zu viel bezahlt
        self.assertEqual(a['saldo_kaeufer'], D('583.56'))
        self.assertEqual(a['saldo_verkaeufer'] + a['saldo_kaeufer'], D('0.00'))   # alles bezahlt: der Rest ist null
        self.assertEqual(a['ausgleich_verkaeufer_an_kaeufer'], D('-583.56'))      # der Käufer erstattet dem Verkäufer

    def test_verkaeufer_hat_nicht_bezahlt_er_erstattet_dem_kaeufer(self):
        b = monatsbudget(self.lg, 2026, 60000)
        w = self._wechsel(date(2026, 9, 14))
        for v in b.vorschreibungen.filter(einheit=self.b, faellig_am__gte=date(2026, 9, 14)):   # nur der Käufer zahlt
            hauptbuch.zahlung_erfassen(self.b, v.betrag, v.faellig_am, vorschreibung=v)
        a = handaenderung.aufteilung(w)
        self.assertEqual(a['akonto_verkaeufer'], D('0.00'))
        self.assertEqual(a['saldo_verkaeufer'], D('8416.44'))
        self.assertEqual(a['ausgleich_verkaeufer_an_kaeufer'], D('8416.44'))       # der Verkäufer zahlt dem Käufer

    def test_die_anteile_ergeben_immer_den_jahresbetrag_und_wachsen_mit_dem_datum(self):
        letzter = D('-1')
        for tag in range(0, 365):
            datum = date(2026, 1, 1) + timedelta(days=tag)
            w = self._wechsel_neu(datum)
            a = handaenderung.aufteilung(w, jahresbetrag=D('1234.56'))
            self.assertEqual(a['verkaeufer_anteil'] + a['kaeufer_anteil'], D('1234.56'), datum)
            self.assertGreaterEqual(a['verkaeufer_anteil'], letzter, datum)
            letzter = a['verkaeufer_anteil']
        self.assertEqual(a['verkaeufer_anteil'], D('1231.18'))              # 1234.56 × 364/365 = 1231.1778

    def _wechsel_neu(self, datum):
        from stweg.models import StwegEigentuemerwechsel
        StwegEigentuemerwechsel.objects.filter(einheit=self.b).delete()
        return StwegEigentuemerwechsel.objects.create(einheit=self.b, datum=datum, bisheriger=self.verkaeufer,
                                                      neu=self.kaeufer)

    def test_rundung_kaeufer_traegt_den_rest(self):
        w = self._wechsel_neu(date(2026, 9, 14))
        a = handaenderung.aufteilung(w, jahresbetrag=D('1000'))
        self.assertEqual((a['verkaeufer_anteil'], a['kaeufer_anteil']), (D('701.37'), D('298.63')))   # 701.3699…

    def test_halber_rappen_beide_anteile_gerundet_waeren_ein_rappen_zu_viel(self):
        w = self._wechsel_neu(date(2028, 7, 2))                           # Schaltjahr: genau die Jahreshälfte (183/366)
        a = handaenderung.aufteilung(w, jahresbetrag=D('12.33'))           # 6.165 / 6.165 → beide 6.17 wären 12.34
        self.assertEqual((a['verkaeufer_anteil'], a['kaeufer_anteil']), (D('6.17'), D('6.16')))
        self.assertEqual(a['verkaeufer_anteil'] + a['kaeufer_anteil'], D('12.33'))

    def test_zahlung_am_uebergangstag_gehoert_dem_kaeufer(self):
        jahr_budget(self.lg, 2026, total=20000)
        w = self._wechsel(date(2026, 9, 14))
        hauptbuch.zahlung_erfassen(self.b, D('100'), date(2026, 9, 13))
        hauptbuch.zahlung_erfassen(self.b, D('40'), date(2026, 9, 14))
        a = handaenderung.aufteilung(w)
        self.assertEqual((a['akonto_verkaeufer'], a['akonto_kaeufer']), (D('100.00'), D('40.00')))

    def test_ohne_budget_steht_es_da(self):
        a = handaenderung.aufteilung(self._wechsel(date(2026, 9, 14)))
        self.assertEqual(a['jahresbetrag'], D('0.00'))
        self.assertIn('kein genehmigtes Budget', a['quelle'])

    def test_nur_das_kapital_zaehlt_als_akonto_zins_und_fonds_nicht(self):
        jahr_budget(self.lg, 2026, total=20000)                # B: 4 × 1000
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'}, bestaetigen=True)
        hauptbuch.zahlung_erfassen(self.b, D('1000'), date(2026, 3, 2))        # 8.22 davon Zins
        hauptbuch.zahlung_erfassen(self.b, D('300'), date(2026, 3, 3), zweck=StwegAkonto.FONDS)
        a = handaenderung.aufteilung(self._wechsel(date(2026, 9, 14)))
        self.assertEqual(a['akonto_verkaeufer'], D('991.78'))

    def test_zins_wird_am_uebergang_getrennt(self):
        jahr_budget(self.lg, 2026, total=20000)
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'}, bestaetigen=True)
        w = self._wechsel(date(2026, 3, 2))                     # Rate 1.1. (1000) ist offen, der Verkäufer schuldet sie
        a = handaenderung.aufteilung(w, stichtag=date(2026, 4, 1))
        self.assertEqual(a['zins_bis_uebergang'], D('8.08'))    # 1.1.→1.3. = 59 Tage: 1000 × 5 % × 59/365
        self.assertEqual(a['zins_danach'], D('4.25'))           # insgesamt 90 Tage: 12.33
        self.assertEqual(a['offen_verkaeufer_bei_uebergang'], D('1000.00'))

    def test_pdf_hat_zahlen_und_hinweis(self):
        from stweg.pdf import handaenderung_pdf
        monatsbudget(self.lg, 2026, 60000)
        w = self._wechsel(date(2026, 9, 14))
        text = ''.join(p.extract_text() for p in PdfReader(io.BytesIO(handaenderung_pdf(w))).pages)
        for erwartet in ('8’416.44', '3’583.56', '14.09.2026', 'Kim Käufer', 'ersetzt keine juristische Prüfung'):
            self.assertIn(erwartet.replace('’', "'"), text.replace('’', "'"))

    def test_seite_und_pdf_endpunkt(self):
        monatsbudget(self.lg, 2026, 60000)
        w = self._wechsel(date(2026, 9, 14))
        c = self.client_class()
        c.force_login(_team_user('Verwaltung'))
        r = c.get(f'/neu/stweg/handaenderung/{w.pk}/pdf/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertContains(c.get(f'/neu/stweg/{self.lg.pk}/einheiten/'), 'Handänderungs-Abrechnung (PDF)')
