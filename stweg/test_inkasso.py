"""STWEG-Inkasso: Mahnungen ohne Kündigungsandrohung, Retentionsrecht, Gemeinschaftspfandrecht mit 36-Monate-Kappung."""
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from pypdf import PdfReader

from core.tests._helfer import _team_user
from stweg import budget as bd
from stweg import inkasso
from stweg.models import (StwegAkonto, StwegBudget, StwegInkassoFall, StwegMahnung, StwegPfandrecht)
from stweg.schluessel import standard_schluessel
from stweg.test_budget import haus_mit_eigentuemern

D = Decimal
STICHTAG = date(2027, 3, 31)


def jahr_budget(lg, jahr, total=4000):
    """Genehmigtes Budget mit vier Quartalsraten (1.1., 1.4., 1.7., 1.10.). Einheit B (200/1000) zahlt 5 % je Rate."""
    b = StwegBudget.objects.create(liegenschaft=lg, jahr=jahr, raten=4, erste_faelligkeit=date(jahr, 1, 1))
    bd.position_setzen(b, f'Budget {jahr}', standard_schluessel(lg), D(total))
    bd.vorlegen(b)
    bd.budget_genehmigen(b)
    return b


def pdf_text(pdf):
    return ''.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


class ForderungenTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]                                           # 200/1000 → 200.00 je Quartal bei 4000/Jahr
        for j in (2023, 2024, 2025, 2026):
            jahr_budget(self.lg, j)

    def test_alle_raten_bis_zum_stichtag(self):
        f = inkasso.forderungen(self.b, STICHTAG)
        self.assertEqual(len(f), 16)
        self.assertEqual({c['betrag'] for c in f}, {D('200.00')})
        self.assertEqual(inkasso.offener_betrag(self.b, STICHTAG), D('3200.00'))

    def test_zukuenftige_raten_zaehlen_nicht(self):
        self.assertEqual(len(inkasso.forderungen(self.b, date(2023, 4, 1))), 2)        # 1.1. und 1.4.
        self.assertEqual(len(inkasso.forderungen(self.b, date(2022, 12, 31))), 0)

    def test_zahlungen_tilgen_die_aelteste_forderung_zuerst(self):
        StwegAkonto.objects.create(einheit=self.b, betrag=D('500'), datum=date(2024, 6, 1))
        f = inkasso.forderungen(self.b, STICHTAG)
        self.assertEqual([c['offen'] for c in f[:4]], [D('0.00'), D('0.00'), D('100.00'), D('200.00')])
        self.assertEqual(sum(c['bezahlt'] for c in f), D('500.00'))
        self.assertEqual(inkasso.offener_betrag(self.b, STICHTAG), D('2700.00'))

    def test_zahlung_nach_dem_stichtag_zaehlt_nicht(self):
        StwegAkonto.objects.create(einheit=self.b, betrag=D('500'), datum=date(2027, 6, 1))
        self.assertEqual(inkasso.offener_betrag(self.b, STICHTAG), D('3200.00'))

    def test_ueberzahlung_erzeugt_keine_negative_forderung(self):
        StwegAkonto.objects.create(einheit=self.b, betrag=D('9999'), datum=date(2024, 6, 1))
        self.assertEqual(inkasso.offener_betrag(self.b, STICHTAG), D('0.00'))
        self.assertTrue(all(c['offen'] >= 0 for c in inkasso.forderungen(self.b, STICHTAG)))

    def test_fondszahlung_tilgt_keine_akonto_forderung_und_umgekehrt(self):
        StwegAkonto.objects.create(einheit=self.b, betrag=D('800'), datum=date(2024, 6, 1), zweck='fonds')
        self.assertEqual(inkasso.offener_betrag(self.b, STICHTAG), D('3200.00'))      # kein Fonds-Anspruch, nichts getilgt

    def test_fonds_einlage_ist_eine_beitragsforderung(self):
        from stweg.fonds import jahreseinlage_belasten
        jahreseinlage_belasten(self.lg, 2026, D('10000'), datum=date(2026, 12, 31))
        art = {c['art'] for c in inkasso.forderungen(self.b, STICHTAG)}
        self.assertEqual(art, {'akonto', 'fonds'})
        self.assertEqual(inkasso.offener_betrag(self.b, STICHTAG), D('3200.00') + D('2000.00'))
        StwegAkonto.objects.create(einheit=self.b, betrag=D('2000'), datum=date(2027, 1, 5), zweck='fonds')
        self.assertEqual(inkasso.offener_betrag(self.b, STICHTAG), D('3200.00'))

    def test_abgeschlossene_abrechnung_ersetzt_die_raten_des_jahres(self):
        from stweg.services import StwegAbrechnungService
        from stweg.tests import rechnung
        rechnung(self.lg, 5000, date(2023, 6, 1))                  # Ist-Kosten 5000 statt Budget 4000
        a = StwegAbrechnungService(self.lg).abrechnen(2023)
        StwegAbrechnungService.abschliessen(a)
        f = [c for c in inkasso.forderungen(self.b, STICHTAG) if c['datum'].year == 2023]
        self.assertEqual([(c['art'], c['betrag']) for c in f], [('abrechnung', D('1000.00'))])   # 200/1000 von 5000


class TilgungsbestimmungTests(TestCase):
    """Der Eigentümer sagt, welche Rate er bezahlt (Art. 86 OR); ohne Angabe gilt die älteste Forderung."""

    def setUp(self):
        from stweg.models import StwegVorschreibung
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        for j in (2023, 2024, 2025, 2026):
            jahr_budget(self.lg, j)
        self.rate = lambda jahr, nr: StwegVorschreibung.objects.get(einheit=self.b, budget__jahr=jahr, rate_nr=nr)

    def zahle(self, betrag, datum, **kw):
        from stweg import hauptbuch
        return hauptbuch.zahlung_erfassen(self.b, D(betrag), datum, **kw)

    def test_bestimmte_zahlung_tilgt_diese_rate_nicht_die_aelteste(self):
        self.zahle(200, date(2026, 11, 1), vorschreibung=self.rate(2026, 4))
        f = {c['datum']: c for c in inkasso.forderungen(self.b, STICHTAG)}
        self.assertEqual(f[date(2026, 10, 1)]['offen'], D('0.00'))
        self.assertEqual(f[date(2023, 1, 1)]['offen'], D('200.00'))                   # die älteste bleibt offen

    def test_ohne_angabe_gilt_die_aelteste(self):
        self.zahle(200, date(2026, 11, 1))
        f = {c['datum']: c for c in inkasso.forderungen(self.b, STICHTAG)}
        self.assertEqual(f[date(2023, 1, 1)]['offen'], D('0.00'))
        self.assertEqual(f[date(2026, 10, 1)]['offen'], D('200.00'))

    def test_der_unterschied_wirkt_auf_die_pfandsumme(self):
        self.zahle(200, date(2026, 11, 1), vorschreibung=self.rate(2026, 4))
        mit = inkasso.pfandberechtigt(self.b, STICHTAG)
        self.assertEqual((mit['pfandberechtigt'], mit['ausgeschlossen']), (D('2000.00'), D('1000.00')))
        StwegAkonto.objects.all().delete()
        self.zahle(200, date(2026, 11, 1))
        ohne = inkasso.pfandberechtigt(self.b, STICHTAG)
        self.assertEqual((ohne['pfandberechtigt'], ohne['ausgeschlossen']), (D('2200.00'), D('800.00')))

    def test_ueberschuss_einer_bestimmten_zahlung_geht_in_den_topf(self):
        self.zahle(500, date(2026, 11, 1), vorschreibung=self.rate(2026, 4))        # Rate 200, Rest 300
        f = {c['datum']: c for c in inkasso.forderungen(self.b, STICHTAG)}
        self.assertEqual(f[date(2026, 10, 1)]['offen'], D('0.00'))
        self.assertEqual((f[date(2023, 1, 1)]['offen'], f[date(2023, 4, 1)]['offen']), (D('0.00'), D('100.00')))

    def test_zahlung_fuer_ein_jahr_mit_abrechnung_tilgt_die_abrechnung(self):
        from stweg.services import StwegAbrechnungService
        from stweg.tests import rechnung
        rechnung(self.lg, 5000, date(2023, 6, 1))
        StwegAbrechnungService.abschliessen(StwegAbrechnungService(self.lg).abrechnen(2023))
        self.zahle(300, date(2024, 1, 5), vorschreibung=self.rate(2023, 2))
        f = [c for c in inkasso.forderungen(self.b, STICHTAG) if c['art'] == 'abrechnung']
        self.assertEqual((f[0]['betrag'], f[0]['bezahlt'], f[0]['offen']), (D('1000.00'), D('300.00'), D('700.00')))

    def test_rate_einer_anderen_einheit_und_fonds_werden_abgelehnt(self):
        from stweg import hauptbuch
        from stweg.models import StwegVorschreibung
        fremd = StwegVorschreibung.objects.filter(einheit=self.e[2]).first()
        with self.assertRaisesRegex(hauptbuch.HauptbuchFehler, 'anderen Einheit'):
            self.zahle(100, date(2026, 11, 1), vorschreibung=fremd)
        with self.assertRaisesRegex(hauptbuch.HauptbuchFehler, 'Akonto-Zahlung'):
            self.zahle(100, date(2026, 11, 1), vorschreibung=self.rate(2026, 1), zweck='fonds')
        with self.assertRaises(hauptbuch.HauptbuchFehler):
            self.zahle(0, date(2026, 11, 1))
        self.assertFalse(StwegAkonto.objects.exists())                               # alles oder nichts

    def test_ueber_die_oberflaeche(self):
        self.client.force_login(_team_user('Verwaltung'))
        r = self.client.post(f'/neu/stweg/{self.lg.pk}/akonto/neu/', {
            'einheit': self.b.pk, 'betrag': '200', 'datum': '2026-11-01', 'vorschreibung': self.rate(2026, 4).pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(StwegAkonto.objects.get().vorschreibung_id, self.rate(2026, 4).pk)
        r = self.client.post(f'/neu/stweg/{self.lg.pk}/akonto/neu/', {
            'einheit': self.b.pk, 'betrag': '100', 'datum': '2026-11-02', 'vorschreibung': self.e[2].pk}, follow=True)
        self.assertContains(r, 'gehört nicht zu dieser Einheit')
        self.assertEqual(StwegAkonto.objects.count(), 1)
        self.assertContains(self.client.get(f'/neu/stweg/{self.lg.pk}/abrechnung/'), 'Bezahlte Rate')


class PfandrechtKappungTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        for j in (2023, 2024, 2025, 2026):
            jahr_budget(self.lg, j)

    def test_nur_die_letzten_36_monate(self):
        p = inkasso.pfandberechtigt(self.b, STICHTAG)
        self.assertEqual(p['grenze'], date(2024, 3, 31))
        # Fällig nach dem 31.03.2024: 1.4., 1.7., 1.10.2024 + 4×2025 + 4×2026 = 11 Raten
        self.assertEqual(p['pfandberechtigt'], D('2200.00'))
        # Älter: 4×2023 + 1.1.2024 = 5 Raten
        self.assertEqual(p['ausgeschlossen'], D('1000.00'))
        self.assertEqual(p['gesamt'], D('3200.00'))
        self.assertEqual(p['pfandberechtigt'] + p['ausgeschlossen'], p['gesamt'])
        self.assertEqual(sum(1 for c in p['zeilen'] if c['pfandberechtigt']), 11)

    def test_genau_36_monate_zurueck_ist_nicht_mehr_pfandberechtigt(self):
        # Stichtag 01.04.2027 → Grenze 01.04.2024: die Rate vom 01.04.2024 liegt genau 36 Monate zurück
        p = inkasso.pfandberechtigt(self.b, date(2027, 4, 1))
        self.assertEqual(p['pfandberechtigt'] + p['ausgeschlossen'], p['gesamt'])           # keine Forderung doppelt
        self.assertEqual(sum(1 for c in p['zeilen'] if c['datum'] == date(2024, 4, 1)), 1)
        daten = {c['datum']: c['pfandberechtigt'] for c in p['zeilen']}
        self.assertFalse(daten[date(2024, 4, 1)])
        self.assertTrue(daten[date(2024, 7, 1)])
        p2 = inkasso.pfandberechtigt(self.b, date(2027, 3, 31))
        self.assertTrue({c['datum']: c['pfandberechtigt'] for c in p2['zeilen']}[date(2024, 4, 1)])   # einen Tag früher

    def test_schaltjahr_und_monatsende(self):
        # 29.02.2028 minus 36 Monate = 28.02.2025 (Monatsende begrenzt)
        self.assertEqual(inkasso.pfandberechtigt(self.b, date(2028, 2, 29))['grenze'], date(2025, 2, 28))

    def test_zahlungen_verringern_zuerst_den_ausgeschlossenen_teil(self):
        StwegAkonto.objects.create(einheit=self.b, betrag=D('1000'), datum=date(2024, 6, 1))
        p = inkasso.pfandberechtigt(self.b, STICHTAG)
        self.assertEqual((p['ausgeschlossen'], p['pfandberechtigt']), (D('0.00'), D('2200.00')))
        StwegAkonto.objects.create(einheit=self.b, betrag=D('400'), datum=date(2024, 7, 1))
        p = inkasso.pfandberechtigt(self.b, STICHTAG)
        self.assertEqual((p['ausgeschlossen'], p['pfandberechtigt']), (D('0.00'), D('1800.00')))

    def test_summe_geht_auf_den_rappen_auf_bei_ungeraden_betraegen(self):
        StwegAkonto.objects.create(einheit=self.b, betrag=D('333.33'), datum=date(2024, 6, 1))
        StwegAkonto.objects.create(einheit=self.b, betrag=D('0.01'), datum=date(2024, 6, 2))
        p = inkasso.pfandberechtigt(self.b, STICHTAG)
        self.assertEqual(p['pfandberechtigt'] + p['ausgeschlossen'], D('3200.00') - D('333.34'))

    def test_wenn_alles_aelter_ist_gibt_es_kein_pfandrecht(self):
        fall = StwegInkassoFall.objects.create(einheit=self.b)
        with self.assertRaisesRegex(inkasso.InkassoFehler, 'Keine pfandberechtigte Forderung'):
            inkasso.pfandrecht_anmelden(fall, stichtag=date(2031, 1, 1), ohne_mahnungen=True)
        self.assertFalse(StwegPfandrecht.objects.exists())


class MahnungTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        self.eig = self.eigs[1]
        jahr_budget(self.lg, 2026)

    def stufen(self, n, heute=date(2027, 1, 20)):
        for i in range(n):
            m = inkasso.mahnung_erstellen(self.b, heute=heute + timedelta(days=15 * i))
            with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True):
                inkasso.mahnung_versenden(m)
        return StwegMahnung.objects.order_by('stufe')

    def test_nichts_offen_keine_mahnung(self):
        StwegAkonto.objects.create(einheit=self.b, betrag=D('800'), datum=date(2026, 12, 1))
        with self.assertRaisesRegex(inkasso.InkassoFehler, 'nichts fällig'):
            inkasso.mahnung_erstellen(self.b, heute=date(2027, 1, 20))

    def test_drei_stufen_nicht_mehr_und_nicht_ohne_versand(self):
        m1 = inkasso.mahnung_erstellen(self.b, heute=date(2027, 1, 20))
        self.assertEqual((m1.stufe, m1.betrag, m1.frist_bis), (1, D('800.00'), date(2027, 1, 30)))
        with self.assertRaisesRegex(inkasso.InkassoFehler, 'noch nicht versendet'):
            inkasso.mahnung_erstellen(self.b, heute=date(2027, 2, 1))
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True):
            inkasso.mahnung_versenden(m1)
        m2 = inkasso.mahnung_erstellen(self.b, heute=date(2027, 2, 1))
        self.assertEqual(m2.stufe, 2)
        self.assertEqual(StwegInkassoFall.objects.count(), 1)                         # derselbe Fall
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True):
            inkasso.mahnung_versenden(m2)
        stufen = self.stufen(1, heute=date(2027, 2, 15))
        self.assertEqual([m.stufe for m in stufen], [1, 2, 3])

    def test_dritte_ist_die_letzte(self):
        self.stufen(3)
        with self.assertRaisesRegex(inkasso.InkassoFehler, 'dritte Mahnung'):
            inkasso.mahnung_erstellen(self.b, heute=date(2027, 3, 1))
        self.assertEqual(StwegMahnung.objects.count(), 3)

    def test_betrag_und_frist_validiert(self):
        with self.assertRaises(inkasso.InkassoFehler):
            inkasso.mahnung_erstellen(self.b, heute=date(2027, 1, 20), frist_tage=0)
        self.assertFalse(StwegInkassoFall.objects.filter(mahnungen__isnull=False).exists())

    def test_text_nennt_nie_eine_kuendigung_und_pdf_auch_nicht(self):
        from stweg.pdf import mahnung_pdf
        for m in self.stufen(3):
            zeilen = '\n'.join(inkasso.mahntext(m))
            text = pdf_text(mahnung_pdf(m))
            for t in (zeilen, text):
                self.assertNotIn('ündig', t, m.stufe)
                self.assertNotIn('257d', t, m.stufe)
            self.assertIn(f'{m.stufe}. Mahnung', text)
            self.assertIn("CHF 800.00", text)
        self.assertIn('Art. 712k ZGB', text)                    # dritte Stufe nennt die Sicherung
        self.assertIn('Art. 712i ZGB', text)

    def test_mail_hat_keine_kuendigung_und_geht_an_eigentuemer_und_miteigentuemer_in_kopie(self):
        from crm.models import Eigentuemer
        mit = Eigentuemer.objects.create(firma_oder_name='Mit', email='mit@x.ch')
        self.b.miteigentuemer.add(mit)
        m = inkasso.mahnung_erstellen(self.b, heute=date(2027, 1, 20))
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True) as sende:
            self.assertEqual(inkasso.mahnung_versenden(m), 'email')
        args, kw = sende.call_args
        self.assertEqual(args[0], self.eig.email)
        self.assertEqual(kw['cc_list'], ['mit@x.ch'])
        self.assertNotIn('ündig', args[2])
        self.assertNotIn('257d', args[2])
        self.assertEqual(args[4][:5], b'%PDF-')
        m.refresh_from_db()
        self.assertEqual((m.kanal, bool(m.versendet_am)), ('email', True))

    def test_ohne_email_per_post_und_fehlgeschlagen_bleibt_unversendet(self):
        self.eig.email = ''
        self.eig.save()
        m = inkasso.mahnung_erstellen(self.b, heute=date(2027, 1, 20))
        self.assertEqual(inkasso.mahnung_versenden(m), 'post')
        m.refresh_from_db()
        self.assertEqual(m.kanal, 'post')
        self.eig.email = 'a@x.ch'
        self.eig.save()
        m2 = inkasso.mahnung_erstellen(self.b, heute=date(2027, 2, 5))
        with mock.patch('core.utils.email_service.send_via_hoststar', return_value=False):
            self.assertEqual(inkasso.mahnung_versenden(m2), 'fehler')
        m2.refresh_from_db()
        self.assertIsNone(m2.versendet_am)

    def test_textfilter_bricht_ab(self):
        for text in ('Wir drohen mit der Kündigung.', 'Fristansetzung nach Art. 257d OR', 'KUENDIGUNG'):
            with self.assertRaises(inkasso.InkassoFehler):
                inkasso.ohne_kuendigung(text)
        inkasso.ohne_kuendigung('Retentionsrecht (Art. 712k ZGB) und Pfandrecht (Art. 712i ZGB)')

    def test_nach_zahlung_ist_der_fall_erledigt(self):
        self.stufen(1)
        fall = StwegInkassoFall.objects.get()
        StwegAkonto.objects.create(einheit=self.b, betrag=D('800'), datum=date(2027, 2, 1))
        inkasso.fall_pruefen(self.b, date(2027, 2, 2))
        fall.refresh_from_db()
        self.assertEqual((fall.status, fall.erledigt_am), ('erledigt', date(2027, 2, 2)))
        self.assertIsNone(inkasso.offener_fall(self.b))

    def test_teilzahlung_laesst_den_fall_offen(self):
        self.stufen(1)
        StwegAkonto.objects.create(einheit=self.b, betrag=D('300'), datum=date(2027, 2, 1))
        inkasso.fall_pruefen(self.b, date(2027, 2, 2))
        self.assertIsNotNone(inkasso.offener_fall(self.b))


class RetentionPfandrechtTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        for j in (2023, 2024, 2025, 2026):
            jahr_budget(self.lg, j)
        self.fall = StwegInkassoFall.objects.create(einheit=self.b, eigentuemer=self.eigs[1])

    def drei_mahnungen(self):
        for i in range(3):
            m = inkasso.mahnung_erstellen(self.b, heute=date(2027, 1, 5) + timedelta(days=20 * i))
            with mock.patch('core.utils.email_service.send_via_hoststar', return_value=True):
                inkasso.mahnung_versenden(m)

    def test_ohne_drei_mahnungen_keine_anmeldung_ausser_ausdruecklich(self):
        with self.assertRaisesRegex(inkasso.InkassoFehler, 'dritte Mahnung ist noch nicht versendet'):
            inkasso.pfandrecht_anmelden(self.fall, stichtag=STICHTAG)
        with self.assertRaises(inkasso.InkassoFehler):
            inkasso.retention_geltend_machen(self.fall, 'Möbel', heute=STICHTAG)
        self.assertFalse(StwegPfandrecht.objects.exists())
        pf = inkasso.pfandrecht_anmelden(self.fall, stichtag=STICHTAG, ohne_mahnungen=True)
        self.assertEqual(pf.betrag_pfandberechtigt, D('2200.00'))

    def test_anmeldung_speichert_die_momentaufnahme(self):
        self.drei_mahnungen()
        pf = inkasso.pfandrecht_anmelden(self.fall, stichtag=STICHTAG)
        self.assertEqual((pf.betrag_gesamt, pf.betrag_pfandberechtigt, pf.betrag_ausgeschlossen),
                         (D('3200.00'), D('2200.00'), D('1000.00')))
        self.assertEqual(sum(1 for z in pf.zeilen if z['pfandberechtigt']), 11)
        self.assertEqual(sum(D(z['offen']) for z in pf.zeilen if not z['pfandberechtigt']), D('1000.00'))
        from core.models import Pendenz
        self.assertTrue(Pendenz.objects.filter(quelle=f'stweg:inkasso:{self.fall.pk}:pfandrecht',
                                               erledigt=False).exists())
        # Eine spätere Zahlung ändert die gespeicherte Anmeldung nicht.
        StwegAkonto.objects.create(einheit=self.b, betrag=D('500'), datum=date(2027, 4, 1))
        pf.refresh_from_db()
        self.assertEqual(pf.betrag_pfandberechtigt, D('2200.00'))

    def test_pdf_fuers_grundbuchamt(self):
        from stweg.pdf import pfandrecht_pdf
        self.drei_mahnungen()
        pf = inkasso.pfandrecht_anmelden(self.fall, stichtag=STICHTAG)
        t = pdf_text(pfandrecht_pdf(pf))
        for erwartet in ('Grundbuchamt', 'Art. 712i ZGB', 'Pfandsumme: CHF 2\'200.00', '31.03.2027', '31.03.2024',
                         'Whg 1.OG', 'Bruno',
                         "Nicht pfandberechtigt (älter als drei Jahre), NICHT in der Pfandsumme: CHF 1'000.00",
                         'Unterschrift'):
            self.assertIn(erwartet, t)
        self.assertNotIn('ündig', t)
        # 11 pfandberechtigte Zeilen, die ältesten (2023) stehen nur im ausgeschlossenen Teil
        teil_pfand, teil_aus = t.split('Nicht pfandberechtigt')
        self.assertEqual(teil_pfand.count('Akonto 202'), 11)
        self.assertEqual(teil_aus.count('Akonto 2023'), 4)
        self.assertNotIn('Akonto 2023', teil_pfand)

    def test_retentionsrecht(self):
        from stweg.pdf import retention_pdf
        self.drei_mahnungen()
        inkasso.retention_geltend_machen(self.fall, 'Möbel und Hausrat in der Wohnung', heute=date(2027, 3, 1))
        self.fall.refresh_from_db()
        self.assertEqual(self.fall.retention_erklaert_am, date(2027, 3, 1))
        with self.assertRaises(inkasso.InkassoFehler):
            inkasso.retention_geltend_machen(self.fall, 'nochmals', heute=date(2027, 3, 2))        # nur einmal
        t = pdf_text(retention_pdf(self.fall))
        self.assertIn('Art. 712k ZGB', t)
        self.assertIn('Möbel und Hausrat', t)
        self.assertNotIn('257d', t)

    def test_retention_braucht_gegenstaende_und_offenen_fall(self):
        self.drei_mahnungen()
        with self.assertRaises(inkasso.InkassoFehler):
            inkasso.retention_geltend_machen(self.fall, '   ', heute=STICHTAG)
        self.fall.status = 'erledigt'
        self.fall.save()
        with self.assertRaises(inkasso.InkassoFehler):
            inkasso.pfandrecht_anmelden(self.fall, stichtag=STICHTAG, ohne_mahnungen=True)

    def test_eintragung_vermerken(self):
        pf = inkasso.pfandrecht_anmelden(self.fall, stichtag=STICHTAG, ohne_mahnungen=True)
        inkasso.pfandrecht_eingetragen(pf, date(2027, 5, 2))
        pf.refresh_from_db()
        self.assertEqual(pf.eingetragen_am, date(2027, 5, 2))


class MietrechtTrennungTests(TestCase):
    """Das Mietmodell darf einen Stockwerkeigentümer nie mit einer Kündigungsandrohung erreichen."""

    def setUp(self):
        from core.tests._helfer import _basis_objekte, _seed_konten
        from crm.models import Eigentuemer
        from django.core.management import call_command
        from finance.models import DebitorenRechnung
        from portfolio.models import Liegenschaft
        _seed_konten()
        call_command('fallarten_anlegen', verbosity=0)
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        Liegenschaft.objects.filter(pk=self.lg.pk).update(typ='STWEG', status='entwurf')
        self.einheit.refresh_from_db()
        self.eigentuemer = Eigentuemer.objects.create(firma_oder_name='Hans Muster', email='hans@example.ch')
        self.einheit.stockwerkeigentuemer = self.eigentuemer
        self.einheit.save()
        heute = date.today()
        self.r = DebitorenRechnung.objects.create(
            vertrag=self.vertrag, titel='Beitrag', datum=heute - timedelta(days=70),
            faellig_am=heute - timedelta(days=70), betrag=D('1700.00'))

    def test_eigentuemer_als_mieter_wird_erkannt(self):
        from core.services.zahlungsverzug import eigentuemer_als_mieter
        self.assertEqual(eigentuemer_als_mieter(self.vertrag), self.eigentuemer)

    def test_echter_mieter_einer_vermieteten_eigentumswohnung_bleibt_mieter(self):
        from core.services.zahlungsverzug import eigentuemer_als_mieter
        self.eigentuemer.firma_oder_name, self.eigentuemer.email = 'Erika Eigentum', 'erika@x.ch'
        self.eigentuemer.save()
        self.assertIsNone(eigentuemer_als_mieter(self.vertrag))

    def test_gleicher_name_oder_gleiche_mail_genuegt(self):
        from core.services.zahlungsverzug import eigentuemer_als_mieter
        self.eigentuemer.email = 'anders@x.ch'
        self.eigentuemer.firma_oder_name = 'hans  MUSTER'
        self.eigentuemer.save()
        self.assertEqual(eigentuemer_als_mieter(self.vertrag), self.eigentuemer)
        self.eigentuemer.firma_oder_name, self.eigentuemer.email = 'Jemand', 'HANS@example.ch'
        self.eigentuemer.save()
        self.assertEqual(eigentuemer_als_mieter(self.vertrag), self.eigentuemer)

    def test_miteigentuemer_zaehlt_auch(self):
        from core.services.zahlungsverzug import eigentuemer_als_mieter
        from crm.models import Eigentuemer
        self.einheit.stockwerkeigentuemer = None
        self.einheit.save()
        mit = Eigentuemer.objects.create(firma_oder_name='X', email='hans@example.ch')
        self.einheit.miteigentuemer.add(mit)
        self.assertEqual(eigentuemer_als_mieter(self.vertrag), mit)

    def test_keine_eskalation_keine_pendenz_kein_fall(self):
        from core.models import Pendenz
        from core.services.automation import run_mahnlauf
        from core.services.zahlungsverzug import eskalation_257d
        from faelle.models import Fall
        self.assertIsNone(eskalation_257d(self.r))
        run_mahnlauf(send_email=False)
        self.assertFalse(Pendenz.objects.filter(quelle__startswith='257d-vorschlag:').exists())
        self.assertFalse(Fall.objects.filter(fallart__schluessel='zahlungsverzug').exists())

    def test_das_257d_schreiben_wird_nie_erzeugt(self):
        from core.views.email_views import generate_mahnung_combined_pdf_bytes
        from core.services.zahlungsverzug import EigentuemerSchutz
        with self.assertRaises(EigentuemerSchutz):
            generate_mahnung_combined_pdf_bytes(self.vertrag, self.vertrag.organisation, 'Januar 2027', '1700.00',
                                                date.today())

    def test_letzte_mahnstufe_wird_zur_gewoehnlichen_mahnung(self):
        from core.services.mahnbrief import mahnbrief_pdf
        pdf = mahnbrief_pdf(self.vertrag, self.vertrag.organisation, stufe=3, monat='Januar 2027', betrag='1700.00',
                            datum=date.today(), letzte_stufe=True, rechnung=self.r)
        t = pdf_text(pdf)
        self.assertNotIn('257d', t)
        self.assertNotIn('Kündigungsandrohung', t)

    def test_ansichten_antworten_403(self):
        from django.test import Client
        c = Client()
        c.force_login(_team_user('Verwalter'))
        r = c.post(f'/vertrag/{self.vertrag.pk}/mahnung/mail/', {'betrag': '1700.00', 'monat': 'Januar 2027'}, secure=True)
        self.assertEqual(r.status_code, 403)
        from django.core import mail
        self.assertEqual(len(mail.outbox), 0)

    def test_normale_mieter_sind_unberuehrt(self):
        from core.services.zahlungsverzug import eskalation_257d
        self.eigentuemer.firma_oder_name, self.eigentuemer.email = 'Erika Eigentum', 'erika@x.ch'
        self.eigentuemer.save()
        self.assertIsNotNone(eskalation_257d(self.r))
