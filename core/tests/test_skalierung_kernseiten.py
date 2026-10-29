"""Kernseiten skalieren nicht mit der Zahl der Einheiten (Audit SICH-09, Etappe 2).

Gemessen am 28.10.2026 bei 1 100 Einheiten: `/neu/portfolio/` 6 833 Abfragen,
`/neu/mahnwesen/` 4 421, `/neu/mahnwesen/trockenlauf/` 4 418, `/neu/debitoren/` 75.
Ursachen: Mietzins-Methoden ohne Prefetch je Vertrag, `r.organisation` und
`offener_betrag` je Rechnung, die Rollenprüfung `|darf` je Zeile und Knopf,
Zustellnachweis und Gebührenstand je Mahnzeile.

Der Test misst NICHT eine feste Zahl (die ändert sich mit jeder Kopfzeile), sondern
die Eigenschaft: Mit dem kleinen Bestand wird die Abfragezahl gezählt, mit dem
grossen muss sie GENAU gleich sein (`assertNumQueries`). Wächst eine Seite mit den
Zeilen, ist der Test rot, ohne dass jemand eine Zahl nachtragen muss.

Gegenprobe (28.10.2026): Prefetch in `soll_jahresmieten`, `organisation` im
Mahnwesen und die Memo-Rollenprüfung in `templatetags/rechte.py` je einzeln
entfernt -> der Test der betroffenen Seite wird rot (Wortlaut im Schlussbericht).
"""
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from ._grossbestand import grossbestand_anlegen
from ._isolation import MandantenFixture

SEITEN = ['/neu/portfolio/', '/neu/mahnwesen/', '/neu/mahnwesen/trockenlauf/', '/neu/debitoren/', '/neu/']


class AbfragezahlUnabhaengigVomBestandTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        grossbestand_anlegen(cls.a.organisation, 2, 3)           # 6 Einheiten

    def _zaehlen(self, url):
        self.client.force_login(self.a.benutzer)
        with CaptureQueriesContext(connection) as c:
            antwort = self.client.get(url)
        self.assertEqual(antwort.status_code, 200, url)
        return len(c)

    def test_abfragezahl_waechst_nicht_mit_den_einheiten(self):
        for url in SEITEN:
            self._zaehlen(url)              # Aufwärmen: die erste Anfrage lädt Sitzung und Caches nach
        klein = {url: self._zaehlen(url) for url in SEITEN}
        grossbestand_anlegen(self.a.organisation, 5, 6, ab=10)    # +30 Einheiten
        self.client.force_login(self.a.benutzer)
        for url in SEITEN:
            with self.subTest(url=url):
                with self.assertNumQueries(klein[url]):
                    antwort = self.client.get(url)
                self.assertEqual(antwort.status_code, 200)

    def test_gegenprobe_der_messung_ein_n_plus_eins_wuerde_auffallen(self):
        """Die Messung ist empfindlich: Eine Abfrage je Liegenschaft ist sichtbar."""
        from core.services import rendite
        original = rendite.betriebsaufwaende_12m

        def je_liegenschaft(liegenschaften, bis=None):
            out = {}
            for lg in liegenschaften:
                out.update(original([lg], bis))
            return out

        self._zaehlen('/neu/portfolio/')
        klein = self._zaehlen('/neu/portfolio/')
        grossbestand_anlegen(self.a.organisation, 4, 2, ab=10)
        with mock.patch.object(rendite, 'betriebsaufwaende_12m', je_liegenschaft):
            gross = self._zaehlen('/neu/portfolio/')
        self.assertGreater(gross, klein)


class MahnwesenBlaetternTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        grossbestand_anlegen(cls.a.organisation, 2, 5)           # 10 Einheiten, 8 im Mahnverzug

    def test_mahnfaelle_werden_seitenweise_gezeigt(self):
        self.client.force_login(self.a.benutzer)
        with mock.patch('core.views.fw.mahnwesen.PRO_SEITE', 3):
            erste = self.client.get('/neu/mahnwesen/')
            zweite = self.client.get('/neu/mahnwesen/?seite=2')
            letzte = self.client.get('/neu/mahnwesen/?seite=99')
        self.assertEqual(len(erste.context['rows']), 3)
        self.assertEqual(len(zweite.context['rows']), 3)
        self.assertEqual(erste.context['anzahl_positionen'], 8)
        self.assertEqual(letzte.context['seite'].number, 3)
        self.assertEqual(len(letzte.context['rows']), 2)
        ids = lambda a: {r['r'].pk for r in a.context['rows']}          # noqa: E731
        self.assertFalse(ids(erste) & ids(zweite))
        self.assertContains(erste, 'Seite 1 von 3')

    def test_summen_stammen_aus_allen_mahnfaellen_nicht_nur_von_der_seite(self):
        self.client.force_login(self.a.benutzer)
        ganz = self.client.get('/neu/mahnwesen/').context['total']
        with mock.patch('core.views.fw.mahnwesen.PRO_SEITE', 3):
            seite = self.client.get('/neu/mahnwesen/').context['total']
        self.assertEqual(ganz, seite)

    def test_stufenfilter_bleibt_beim_blaettern_erhalten(self):
        self.client.force_login(self.a.benutzer)
        with mock.patch('core.views.fw.mahnwesen.PRO_SEITE', 1):
            antwort = self.client.get('/neu/mahnwesen/?stufe=2')
        self.assertContains(antwort, 'stufe=2&amp;seite=2')

    def test_leerer_zustand(self):
        from core.tenancy import organisation_kontext
        from finance.models import DebitorenRechnung
        with organisation_kontext(self.a.organisation):
            DebitorenRechnung.objects.update(status='bezahlt')
        self.client.force_login(self.a.benutzer)
        antwort = self.client.get('/neu/mahnwesen/')
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.context['rows'], [])
        self.assertContains(antwort, 'Keine offenen Mahnfälle')
