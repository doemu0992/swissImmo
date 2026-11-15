"""Ablesung, Mandate und Kreditorenliste fragen nicht je Zeile (Audit P9, P10).

Gemessen am 15.11.2026: `/neu/ablesung/` 69 -> 169 Abfragen (fünf je Liegenschaft), `/neu/mandate/` 28 -> 48 (eine je
Mandat), Kreditorenliste 75 bei 50 Zeilen. Geprüft wird die Eigenschaft (gleiche Zahl bei mehr Zeilen) und dass die
Zahlen der Ablesung dieselben sind wie zuvor je Liegenschaft gerechnet.

Gegenprobe (15.11.2026): `annotate(anzahl_lg=…)` durch die Zählabfrage je Mandat ersetzt -> Mandate rot;
`'weiterverrechnungen'` aus dem Prefetch entfernt -> Kreditoren rot.
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.tenancy import organisation_kontext
from crm.models import Eigentuemer
from finance.models import KreditorenRechnung
from portfolio.models import Liegenschaft, Zaehler

from ._grossbestand import grossbestand_anlegen
from ._isolation import MandantenFixture

SEITEN = ['/neu/ablesung/', '/neu/mandate/', '/neu/kreditoren/']


class AbfragezahlTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls._mehr(2, 0)

    @classmethod
    def _mehr(cls, n, ab):
        grossbestand_anlegen(cls.a.organisation, n, 2, ab=ab)
        with organisation_kontext(cls.a.organisation):
            for i in range(ab, ab + n):
                e = Eigentuemer.objects.create(firma_oder_name=f'Mandat {i}')
                lg = Liegenschaft.objects.create(strasse=f'Mandatweg {i}', plz='8000', ort='Zürich', eigentuemer=e)
                Zaehler.objects.create(liegenschaft=lg, typ='Strom', zaehler_nummer=f'A{i}')
                KreditorenRechnung.objects.create(lieferant=f'Lieferant {i}', betrag=Decimal('100'),
                                                  datum=date(2025, 1, 10), liegenschaft=lg, status='freigegeben')

    def _zaehlen(self, url):
        self.client.force_login(self.a.benutzer)
        with CaptureQueriesContext(connection) as c:
            antwort = self.client.get(url)
        self.assertEqual(antwort.status_code, 200, url)
        return len(c), antwort

    def test_abfragezahl_waechst_nicht_mit_den_zeilen(self):
        for url in SEITEN:
            self._zaehlen(url)
        klein = {url: self._zaehlen(url)[0] for url in SEITEN}
        self._mehr(6, 50)
        for url in SEITEN:
            with self.subTest(url=url):
                self.assertEqual(self._zaehlen(url)[0], klein[url])

    def test_ablesung_zeigt_dieselben_zahlen_wie_je_liegenschaft_gerechnet(self):
        from core.views.fw.ablesung import _empfaenger
        zeilen = self._zaehlen('/neu/ablesung/')[1].context['zeilen']
        self.assertGreater(len(zeilen), 3)
        with organisation_kontext(self.a.organisation):
            for z in zeilen:
                lg = z['lg']
                erwartet = (Zaehler.objects.filter(einheit__liegenschaft=lg).count()
                            + Zaehler.objects.filter(liegenschaft=lg).count())
                self.assertEqual(z['zaehler'], erwartet, lg)
                self.assertEqual(z['empfaenger'], len(_empfaenger(lg)), lg)
        self.assertTrue(any(z['zaehler'] for z in zeilen))

    def test_mandate_zaehlen_die_liegenschaften(self):
        rows = self._zaehlen('/neu/mandate/')[1].context['rows']
        je = {r['md'].firma_oder_name: r['anzahl_lg'] for r in rows}
        self.assertEqual(je['Mandat 0'], 1)
