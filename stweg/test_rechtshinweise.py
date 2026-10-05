"""Rechtliche Hinweise auf Dokumenten und Seiten, Zinsabrechnung — und die 36-Monate-Regel über alle Stichtage."""
import calendar
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase
from pypdf import PdfReader

from core.tests._helfer import _team_user
from crm.models import Eigentuemer
from stweg import eigentuemer, hauptbuch, inkasso, vorgaben
from stweg.models import StwegInkassoFall
from stweg.pdf import HINWEIS_RECHT, handaenderung_pdf, pfandrecht_pdf, retention_pdf, zinsabrechnung_pdf
from stweg.test_budget import haus_mit_eigentuemern
from stweg.test_inkasso import jahr_budget

D = Decimal
KERN = 'ersetzt keine juristische Prüfung'


def text(pdf):
    return ' '.join(' '.join(p.extract_text().split()) for p in PdfReader(io.BytesIO(pdf)).pages)


class HinweisTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern(iban='CH9300762011623852957')
        self.b = self.e[1]
        jahr_budget(self.lg, 2025)
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'}, bestaetigen=True)
        self.fall = StwegInkassoFall.objects.create(einheit=self.b, eroeffnet_am=date(2026, 3, 1))

    def test_der_hinweis_nennt_die_36_monate_und_den_zins(self):
        for wort in (KERN, '36-Monats-Frist', 'Zinsberechnung', 'Fachperson'):
            self.assertIn(wort, HINWEIS_RECHT)

    def test_pfandrecht_pdf_hat_den_hinweis_oben_und_unten(self):
        pf = inkasso.pfandrecht_anmelden(self.fall, stichtag=date(2026, 3, 1), ohne_mahnungen=True)
        t = text(pfandrecht_pdf(pf))
        self.assertEqual(t.count(KERN), 2)                      # oben fett, unten noch einmal
        self.assertLess(t.index(KERN), t.index('Antrag auf Eintragung'))   # zuerst gelesen
        self.assertIn('Zinsen und Kosten sind nicht in der Pfandsumme', t)

    def test_retention_zinsabrechnung_und_handaenderung(self):
        self.fall.retention_erklaert_am, self.fall.retention_gegenstaende = date(2026, 3, 2), 'Fahrrad'
        self.fall.save()
        self.assertIn(KERN, text(retention_pdf(self.fall)))
        self.assertEqual(text(zinsabrechnung_pdf(self.b, date(2026, 3, 2))).count(KERN), 2)
        kim = Eigentuemer.objects.create(firma_oder_name='Kim Käufer')
        w = eigentuemer.wechseln(self.b, kim, date(2026, 9, 14))
        self.assertEqual(text(handaenderung_pdf(w)).count(KERN), 2)

    def test_mahnung_an_den_schuldner_traegt_keinen_juristischen_hinweis(self):
        from stweg.pdf import mahnung_pdf
        m = inkasso.mahnung_erstellen(self.b, heute=date(2026, 3, 1))
        self.assertNotIn(KERN, text(mahnung_pdf(m)))            # ein Brief an den Eigentümer, keine interne Auswertung

    def test_seiten_zeigen_den_hinweis(self):
        self.client.force_login(_team_user('Verwaltung'))
        self.assertContains(self.client.get(f'/neu/stweg/{self.lg.pk}/inkasso/'), KERN)
        self.assertContains(self.client.get(f'/neu/stweg/{self.lg.pk}/einheiten/'), KERN)


class ZinsabrechnungTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        jahr_budget(self.lg, 2026, total=20000)
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'}, bestaetigen=True)
        hauptbuch.zahlung_erfassen(self.b, D('1000'), date(2026, 3, 2))

    def test_pdf_zeigt_zins_abschnitte_und_anrechnung(self):
        t = text(zinsabrechnung_pdf(self.b, date(2026, 3, 2)))
        for erwartet in ('60 Tage auf CHF 1\'000.00 = CHF 8.22', 'Kosten 0.00, Zinsen 8.22, Kapital 991.78',
                         'Art. 85 Abs. 1 OR', '5 % pro Jahr', 'Gesamtschuld CHF 8.22'):
            self.assertIn(erwartet, t.replace('’', "'"))

    def test_endpunkt_und_fremde_einheit(self):
        c = self.client_class()
        c.force_login(_team_user('Verwaltung'))
        r = c.get(f'/neu/stweg/{self.lg.pk}/inkasso/zinsabrechnung/{self.b.pk}/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        _, ae, _ = haus_mit_eigentuemern()
        self.assertEqual(c.get(f'/neu/stweg/{self.lg.pk}/inkasso/zinsabrechnung/{ae[1].pk}/').status_code, 404)


class DreiJahreRegelTests(SimpleTestCase):
    """Unabhängiger Beweis der 36-Monate-Regel: für JEDEN Stichtag von 2020 bis 2032 zählt eine Forderung genau dann,
    wenn ihr Datum strikt nach dem gleichen Kalendertag drei Jahre früher liegt (29.02. → 28.02.)."""

    @staticmethod
    def grenze(stichtag):
        j = stichtag.year - 3
        return date(j, stichtag.month, min(stichtag.day, calendar.monthrange(j, stichtag.month)[1]))

    def test_jeder_stichtag(self):
        tag = date(2020, 1, 1)
        while tag <= date(2032, 12, 31):
            g = self.grenze(tag)
            claims = [{'datum': g + timedelta(days=d), 'text': f'F{d}', 'betrag': D('10'), 'bezahlt': D('0'),
                       'offen': D('10'), 'art': 'akonto'} for d in (-366, -2, -1, 0, 1, 2, 366) if g + timedelta(days=d) <= tag]
            with mock.patch('stweg.inkasso.forderungen', return_value=claims):
                p = inkasso.pfandberechtigt(mock.Mock(), tag)
            drin = {c['datum'] for c in p['zeilen'] if c['pfandberechtigt']}
            erwartet = {c['datum'] for c in claims if c['datum'] > g}
            self.assertEqual(drin, erwartet, tag)
            self.assertEqual(p['grenze'], g, tag)
            self.assertEqual(p['pfandberechtigt'] + p['ausgeschlossen'], p['gesamt'], tag)
            tag += timedelta(days=1)

    def test_schalttag_und_monatsende(self):
        for stichtag, grenze in ((date(2028, 2, 29), date(2025, 2, 28)), (date(2027, 3, 31), date(2024, 3, 31)),
                                 (date(2026, 2, 28), date(2023, 2, 28)), (date(2024, 2, 29), date(2021, 2, 28))):
            self.assertEqual(self.grenze(stichtag), grenze)
            self.assertEqual(inkasso._plus_monate(stichtag, -inkasso.PFANDRECHT_MONATE), grenze)

    def test_der_wert_ist_36_monate(self):
        self.assertEqual(inkasso.PFANDRECHT_MONATE, 36)
