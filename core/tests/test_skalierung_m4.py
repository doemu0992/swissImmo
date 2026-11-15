"""Ersatzplanung und Lieferantenkonten fragen nicht je Zeile (Audit P3, P4).

Gemessen am 15.11.2026: Ersatzplanung 1043 -> 3083 Abfragen (sechs je Gerät und Ausstattung: die
Lebensdauertabelle wurde je Nachschlag gelesen), das PDF 3383; Lieferantenkonten 185 -> 525 (eine je Rechnung).

Wie `test_skalierung_kernseiten`: keine feste Zahl, sondern die Eigenschaft — mit mehr Zeilen dieselbe Abfragezahl.

Gegenprobe (15.11.2026): `Lebensdauer.gemerkt()` in `berechne_ersatzplanung` entfernt -> Ersatzplanung rot;
`prefetch_related('zahlungen')` entfernt -> Lieferantenkonten rot.
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.tenancy import organisation_kontext
from finance.models import KreditorenRechnung
from portfolio.models import Ausstattung, Geraet, Lebensdauer

from ._isolation import MandantenFixture


class AbfragezahlTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        with organisation_kontext(cls.a.organisation):
            Lebensdauer.objects.get_or_create(kategorie='Backofen', defaults={'jahre': 15})
        cls._bestand(3, 0)

    @classmethod
    def _bestand(cls, n, ab):
        with organisation_kontext(cls.a.organisation):
            for i in range(ab, ab + n):
                Ausstattung.objects.create(einheit=cls.a.einheit, raum='Küche', kategorie='Backofen',
                                           einbau_datum=date(2015, 1, 1), neuwert=Decimal('1200'))
                Geraet.objects.create(einheit=cls.a.einheit, kategorie='Backofen',
                                      installations_datum=date(2015, 1, 1))
                KreditorenRechnung.objects.create(lieferant=f'Lieferant {i}', betrag=Decimal('100'),
                                                  datum=date(2025, 1, 10), liegenschaft=cls.a.liegenschaft)

    def _zaehlen(self, url):
        self.client.force_login(self.a.benutzer)
        with CaptureQueriesContext(connection) as c:
            antwort = self.client.get(url)
        self.assertEqual(antwort.status_code, 200, url)
        return len(c)

    def test_abfragezahl_waechst_nicht_mit_den_zeilen(self):
        seiten = ['/neu/ersatzplanung/', '/neu/ersatzplanung/?pdf=1', '/neu/lieferantenkonten/']
        for url in seiten:
            self._zaehlen(url)                                  # Aufwärmen
        klein = {url: self._zaehlen(url) for url in seiten}
        self._bestand(12, 100)
        for url in seiten:
            with self.subTest(url=url):
                self.assertEqual(self._zaehlen(url), klein[url])

    def test_ergebnis_gleich_mit_und_ohne_merker(self):
        """Der Merker ändert nur die Zahl der Abfragen, nicht die Antwort — auch bei anderer Schreibweise."""
        with organisation_kontext(self.a.organisation):
            ohne = [Lebensdauer.fuer_kategorie(k) for k in ('Backofen', ' backofen ', 'BACKOFEN', 'gibt es nicht', '')]
            with Lebensdauer.gemerkt():
                with self.assertNumQueries(1):
                    mit = [Lebensdauer.fuer_kategorie(k)
                           for k in ('Backofen', ' backofen ', 'BACKOFEN', 'gibt es nicht', '')]
        self.assertEqual(mit, ohne)
        self.assertEqual(mit[0], 15)

    def test_merker_trennt_die_verwaltungen(self):
        b = MandantenFixture('B', '3000', 'Bern')
        with organisation_kontext(b.organisation):
            Lebensdauer.objects.update_or_create(kategorie='Backofen', defaults={'jahre': 99})
        with Lebensdauer.gemerkt():
            with organisation_kontext(self.a.organisation):
                self.assertEqual(Lebensdauer.fuer_kategorie('Backofen'), 15)
            with organisation_kontext(b.organisation):
                self.assertEqual(Lebensdauer.fuer_kategorie('Backofen'), 99)
