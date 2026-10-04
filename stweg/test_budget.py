"""Budget → Beschluss → Akonto-Vorschreibung → Kontokorrent."""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from crm.models import Eigentuemer
from stweg import budget as bd
from stweg.beschluss import BeschlussFehler, anwesenheit_setzen, feststellen, stimme_abgeben
from stweg.konto import fonds_stand, kontokorrent
from stweg.models import (StwegAbrechnung, StwegAkonto, StwegBudget, StwegSchluessel, StwegVorschreibung,
                          Traktandum, Versammlung)
from stweg.schluessel import lift_schluessel, standard_schluessel
from stweg.services import StwegAbrechnungService
from stweg.test_schluessel import haus, konto
from stweg.tests import rechnung

D = Decimal


def haus_mit_eigentuemern(iban=''):
    lg, e = haus()
    eigs = []
    for einheit, name in zip(e, ('Anna', 'Bruno', 'Carla', 'Dario', 'Elena')):
        eig = Eigentuemer.objects.create(firma_oder_name=name, email=f'{name.lower()}@x.ch')
        einheit.stockwerkeigentuemer = eig
        einheit.save()
        eigs.append(eig)
    if iban:
        lg.iban = iban
        lg.save()
    return lg, e, eigs


def budget_2026(lg, **kw):
    b = StwegBudget.objects.create(liegenschaft=lg, jahr=2026, erste_faelligkeit=date(2026, 1, 1), **kw)
    bd.position_setzen(b, 'Versicherung und Hauswart', standard_schluessel(lg), D('1000'))
    bd.position_setzen(b, 'Liftwartung', lift_schluessel(lg), D('850'))
    return b


class BudgetTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()

    def test_jahresbetrag_nach_zwei_schluesseln_und_eg_ohne_lift(self):
        b = budget_2026(self.lg)
        j = {e.bezeichnung: d for e, d in bd.jahresbetraege(b).items()}
        # Allgemein 1000 nach Quote (150/200/250/200/200) + Lift 850 nach (0/200/250/200/200)
        self.assertEqual([j[n]['summe'] for n in ('Whg EG', 'Whg 1.OG', 'Whg 2.OG', 'Whg 3.OG', 'Attika')],
                         [D('150.00'), D('400.00'), D('500.00'), D('400.00'), D('400.00')])
        self.assertEqual(j['Whg EG']['aufteilung'],
                         [{'schluessel': 'Allgemeine Wertquote', 'betrag': '150.00'},
                          {'schluessel': 'Lift', 'betrag': '0.00'}])

    def test_genehmigen_schreibt_raten_vor_die_aufgehen(self):
        b = budget_2026(self.lg, raten=3)
        b.positionen.create(bezeichnung='Rest', schluessel=standard_schluessel(self.lg), betrag=D('0.01'))
        bd.vorlegen(b)
        bd.budget_genehmigen(b)
        for e in self.e:
            vs = StwegVorschreibung.objects.filter(einheit=e)
            self.assertEqual(vs.count(), 3)
            self.assertEqual(sum(v.betrag for v in vs), vs[0].jahresbetrag)
        self.assertEqual(sum(v.jahresbetrag for v in StwegVorschreibung.objects.filter(rate_nr=1)),
                         b.total)
        eg = StwegVorschreibung.objects.filter(einheit=self.e[0])
        self.assertTrue(all(all(t['schluessel'] != 'Lift' or t['betrag'] == '0.00' for t in v.aufteilung)
                            for v in eg))

    def test_faelligkeiten(self):
        b = budget_2026(self.lg)
        bd.vorlegen(b)
        bd.budget_genehmigen(b)
        self.assertEqual(sorted({v.faellig_am for v in StwegVorschreibung.objects.all()}),
                         [date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)])

    def test_nur_ein_vorgelegtes_budget_wird_genehmigt_und_nur_einmal(self):
        b = budget_2026(self.lg)
        with self.assertRaises(bd.BudgetFehler):
            bd.budget_genehmigen(b)                  # Entwurf
        bd.vorlegen(b)
        bd.budget_genehmigen(b)
        with self.assertRaises(bd.BudgetFehler):
            bd.budget_genehmigen(b)                  # zweimal
        self.assertEqual(StwegVorschreibung.objects.count(), 5 * 4)
        with self.assertRaises(bd.BudgetFehler):
            bd.position_setzen(b, 'Nachtrag', standard_schluessel(self.lg), D('1'))

    def test_aenderung_nach_dem_vorlegen_verlangt_neues_vorlegen(self):
        b = budget_2026(self.lg)
        bd.vorlegen(b)
        bd.position_setzen(b, 'Nachtrag', standard_schluessel(self.lg), D('50'))
        b.refresh_from_db()
        self.assertEqual(b.status, 'entwurf')

    def test_unvollstaendiger_schluessel_verhindert_das_vorlegen(self):
        self.e[1].flaeche_m2 = None
        self.e[1].save()
        b = StwegBudget.objects.create(liegenschaft=self.lg, jahr=2026)
        heiz = StwegSchluessel.objects.create(liegenschaft=self.lg, name='Heizung', art='flaeche')
        bd.position_setzen(b, 'Heizöl', heiz, D('900'))
        with self.assertRaises(bd.BudgetFehler):
            bd.vorlegen(b)

    def test_leeres_budget_und_negative_position(self):
        b = StwegBudget.objects.create(liegenschaft=self.lg, jahr=2026)
        with self.assertRaises(bd.BudgetFehler):
            bd.vorlegen(b)
        with self.assertRaises(bd.BudgetFehler):
            bd.position_setzen(b, 'x', standard_schluessel(self.lg), D('-5'))

    def test_fremder_schluessel_wird_abgelehnt(self):
        fremd, _ = haus()
        b = StwegBudget.objects.create(liegenschaft=self.lg, jahr=2026)
        with self.assertRaises(bd.BudgetFehler):
            bd.position_setzen(b, 'x', standard_schluessel(fremd), D('5'))


class BudgetBeschlussTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.v = Versammlung.objects.create(liegenschaft=self.lg, titel='OV 2026',
                                            datum=timezone.now() + timedelta(days=30), status='durchgefuehrt')
        self.t = Traktandum.objects.create(versammlung=self.v, nr=1, titel='Budget-Genehmigung',
                                           mehrheitsart='doppelt_aller')
        self.b = budget_2026(self.lg)
        bd.an_traktandum_haengen(self.t, self.b)
        for e in self.e:
            anwesenheit_setzen(self.v, e, 'anwesend')

    def test_angenommen_loest_die_akonto_rechnungen_aus(self):
        for e in self.e:
            stimme_abgeben(self.t, e, 'ja')
        feststellen(self.t, 'angenommen')
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, 'genehmigt')
        self.assertEqual(StwegVorschreibung.objects.count(), 20)

    def test_abgelehnt_schreibt_nichts_vor(self):
        for e in self.e:
            stimme_abgeben(self.t, e, 'nein')
        feststellen(self.t, 'abgelehnt')
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, 'abgelehnt')
        self.assertFalse(StwegVorschreibung.objects.exists())

    def test_vertagt_laesst_alles_offen(self):
        feststellen(self.t, 'vertagt')
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, 'vorgelegt')
        self.assertFalse(StwegVorschreibung.objects.exists())

    def test_beschluss_scheitert_ganz_wenn_das_budget_nicht_genehmigbar_ist(self):
        self.e[1].flaeche_m2 = None
        heiz = StwegSchluessel.objects.create(liegenschaft=self.lg, name='Heizung', art='flaeche')
        self.e[1].save()
        self.b.positionen.create(bezeichnung='Heizöl', schluessel=heiz, betrag=D('900'))   # nach dem Vorlegen
        with self.assertRaises(BeschlussFehler):
            feststellen(self.t, 'angenommen')
        self.t.refresh_from_db()
        self.assertEqual(self.t.ergebnis, 'offen')                 # atomar zurückgerollt
        self.assertFalse(StwegVorschreibung.objects.exists())

    def test_budget_einer_anderen_gemeinschaft_nicht_anhaengbar(self):
        fremd, _, _ = haus_mit_eigentuemern()
        fb = budget_2026(fremd)
        t2 = Traktandum.objects.create(versammlung=self.v, nr=2, titel='Anderes')
        with self.assertRaises(bd.BudgetFehler):
            bd.an_traktandum_haengen(t2, fb)


class KontokorrentTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = budget_2026(self.lg)
        bd.vorlegen(self.b)
        bd.budget_genehmigen(self.b)
        self.eg, self.og1 = self.e[0], self.e[1]

    def test_saldo_vorschreibung_minus_zahlung(self):
        k = kontokorrent(self.og1, heute=date(2026, 4, 15))
        self.assertEqual(k['saldo_faellig'], D('200.00'))        # 2 Raten à 100 fällig
        self.assertEqual(k['saldo_total'], D('400.00'))
        self.assertEqual(k['kuenftig'], D('200.00'))
        StwegAkonto.objects.create(einheit=self.og1, betrag=D('100'), datum=date(2026, 1, 5))
        k = kontokorrent(self.og1, heute=date(2026, 4, 15))
        self.assertEqual(k['saldo_faellig'], D('100.00'))
        self.assertEqual([b['art'] for b in k['bewegungen']].count('zahlung'), 1)

    def test_nach_dem_abschluss_ist_der_saldo_kostenanteil_minus_zahlungen(self):
        k_lift = konto('4200', 'Lift')
        from stweg.schluessel import kostenart_zuordnen
        kostenart_zuordnen(self.lg, k_lift, lift_schluessel(self.lg, name='Lift'))
        rechnung(self.lg, 1000, date(2026, 3, 1))
        rechnung(self.lg, 1000, date(2026, 4, 1), konto=k_lift)       # mehr als budgetiert (850)
        for e in self.e:
            StwegAkonto.objects.create(einheit=e, betrag=D('200'), datum=date(2026, 6, 1))
        a = StwegAbrechnungService(self.lg).abrechnen(2026)
        StwegAbrechnungService.abschliessen(a)
        for e in self.e:
            p = a.positionen.get(einheit=e)
            k = kontokorrent(e, heute=date(2027, 1, 1))
            self.assertEqual(k['saldo_total'], p.saldo, e.bezeichnung)
        self.assertEqual(kontokorrent(self.eg, heute=date(2027, 1, 1))['saldo_total'], D('150.00') - 200)

    def test_entwurf_der_abrechnung_zaehlt_nicht(self):
        rechnung(self.lg, 3000, date(2026, 3, 1))
        StwegAbrechnungService(self.lg).abrechnen(2026)
        self.assertNotIn('abgleich', [b['art'] for b in kontokorrent(self.og1)['bewegungen']])

    def test_fonds_stand(self):
        from stweg.fonds import entnahme_buchen, jahreseinlage_belasten
        self.assertEqual(fonds_stand(self.lg, [self.eg])['bestand'], D('0.00'))
        jahreseinlage_belasten(self.lg, 2026, D('10000'))
        entnahme_buchen(self.lg, 2026, D('1000'), 'Dach')
        s = fonds_stand(self.lg, self.e)
        self.assertEqual(s['bestand'], D('9000.00'))
        je = {x['einheit'].bezeichnung: x for x in s['einheiten']}
        self.assertEqual(je['Whg EG']['einlagen'], D('1500.00'))
        self.assertEqual(je['Whg EG']['anteil'], D('1350.00'))
        self.assertEqual(sum(x['anteil'] for x in s['einheiten']), D('9000.00'))


class VorschreibungPdfTests(TestCase):
    IBAN = 'CH9300762011623852957'

    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern(iban=self.IBAN)
        self.b = budget_2026(self.lg)
        bd.vorlegen(self.b)
        bd.budget_genehmigen(self.b)

    def seiten(self, pdf):
        from pypdf import PdfReader
        import io
        return len(PdfReader(io.BytesIO(pdf)).pages)

    def test_pdf_mit_einem_zahlteil_je_rate(self):
        from stweg.pdf import vorschreibung_pdf
        self.assertEqual(self.seiten(vorschreibung_pdf(self.b, self.eigs[1])), 1 + 4)

    def test_ohne_iban_kein_zahlteil(self):
        from stweg.pdf import vorschreibung_pdf
        self.lg.iban = ''
        self.lg.save()
        self.assertEqual(self.seiten(vorschreibung_pdf(self.b, self.eigs[1])), 1)

    def test_versand_einmal_je_eigentuemer_und_post_ohne_adresse(self):
        self.eigs[4].email = ''
        self.eigs[4].save()
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True) as m:
            r = bd.vorschreibungen_versenden(self.b)
            self.assertEqual(m.call_count, 4)
            self.assertEqual([x.firma_oder_name for x in r['post']], ['Elena'])
            r2 = bd.vorschreibungen_versenden(self.b)
            self.assertEqual(m.call_count, 4)              # die vier haben sie schon
            self.assertEqual(len(r2['gesendet']), 0)

    def test_fehlgeschlagener_versand_wird_wiederholt(self):
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=False):
            self.assertEqual(len(bd.vorschreibungen_versenden(self.b)['fehler']), 5)
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True) as m:
            self.assertEqual(len(bd.vorschreibungen_versenden(self.b)['gesendet']), 5)

    def test_versand_vor_der_genehmigung_verweigert(self):
        b2 = StwegBudget.objects.create(liegenschaft=self.lg, jahr=2027)
        with self.assertRaises(bd.BudgetFehler):
            bd.vorschreibungen_versenden(b2)
