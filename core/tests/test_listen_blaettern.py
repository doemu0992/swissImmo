"""Lange Listen zeigen eine Seite, nicht den ganzen Bestand (Audit P6).

Gemessen am 15.11.2026: Dokumente 2,1 MB HTML, Kontoblatt 1,8 MB — beides wuchs linear mit den Zeilen. Dokumente,
Schadensfälle, Pendenzen und Kontoblatt blättern jetzt mit `core/views/fw/_liste.blaettern`. Gezählt, gefiltert und
saldiert wird weiterhin über alles; nur die Anzeige ist eine Seite.

Gegenprobe (15.11.2026): `blaettern` in der jeweiligen Ansicht umgangen (ganze Liste übergeben) -> der Test der
Seite wird rot (60 statt 50 Zeilen, keine zweite Seite).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.auth import _rollen_des_pfads, darf_oeffnen
from core.models import Pendenz
from core.tenancy import organisation_kontext
from finance.models import Buchung
from portfolio.models import Dokument as LgDokument
from portfolio.models import Liegenschaft
from tickets.models import SchadenMeldung

from ._isolation import MandantenFixture


class ListenBlaetternTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def setUp(self):
        self.client.force_login(self.a.benutzer)

    def _seite(self, url):
        antwort = self.client.get(url)
        self.assertEqual(antwort.status_code, 200, url)
        return antwort

    def test_dokumente(self):
        with organisation_kontext(self.a.organisation):
            for i in range(60):
                LgDokument.objects.create(liegenschaft=self.a.liegenschaft, titel=f'Blattprobe {i:02d}',
                                          datei=f'dok/p{i}.pdf')
        eins = self._seite('/neu/dokumente/?q=Blattprobe')
        self.assertEqual(eins.content.decode().count('Blattprobe '), 50)
        self.assertEqual(eins.context['anzahl'], 60)                   # gezählt wird über alles
        self.assertContains(eins, 'q=Blattprobe&amp;seite=2')          # der Filter bleibt beim Blättern
        zwei = self._seite('/neu/dokumente/?q=Blattprobe&seite=2')
        self.assertEqual(zwei.content.decode().count('Blattprobe '), 10)

    def test_schadensfaelle(self):
        with organisation_kontext(self.a.organisation):
            for i in range(60):
                SchadenMeldung.objects.create(liegenschaft=self.a.liegenschaft, betroffene_einheit=self.a.einheit,
                                              titel=f'Tropfprobe {i:02d}', beschreibung='x')
        eins = self._seite('/neu/schaeden/?q=Tropfprobe&sicht=')
        self.assertEqual(len(eins.context['rows']), 50)
        self.assertEqual(eins.context['seite'].paginator.count, 60)
        self.assertEqual(eins.context['kopf']['offen'], 60)            # der Kopf zählt den ganzen Bestand
        zwei = self._seite('/neu/schaeden/?q=Tropfprobe&sicht=&seite=2')
        self.assertEqual(len(zwei.context['rows']), 10)

    def test_pendenzen_blaettern_nach_gruppen(self):
        from core.views.fw.pendenzen import PENDENZ_GRUPPEN_JE_SEITE
        with organisation_kontext(self.a.organisation):
            for i in range(PENDENZ_GRUPPEN_JE_SEITE + 5):
                lg = Liegenschaft.objects.create(strasse=f'Gruppenweg {i}', plz='8000', ort='Zürich',
                                                 eigentuemer=self.a.eigentuemer)
                for n in range(2):
                    Pendenz.objects.create(titel=f'Aufgabe {i}-{n}', kategorie='aufgabe', liegenschaft=lg,
                                           faellig_am=date(2030, 1, 1))
        eins = self._seite('/neu/pendenzen/')
        self.assertEqual(len(eins.context['gruppen']), PENDENZ_GRUPPEN_JE_SEITE)
        for g in eins.context['gruppen']:
            if g['titel'].startswith('Gruppenweg'):
                self.assertEqual(len(g['pendenzen']), 2)               # eine Gruppe wird nie geteilt
        zwei = self._seite('/neu/pendenzen/?seite=2')
        self.assertGreaterEqual(len(zwei.context['gruppen']), 5)

    def test_kontoblatt_der_saldo_laeuft_ueber_die_seiten(self):
        from core.views.fw.buchhaltung import KONTOBLATT_ZEILEN_JE_SEITE as N
        # Die Fixture bucht schon einmal 1500 auf dieses Konto (01.02.2024); Buchungen sind nicht löschbar.
        with organisation_kontext(self.a.organisation):
            for i in range(N + 10):
                Buchung.objects.create(beleg_text=f'Lauf {i}', soll_konto=self.a.konto_soll,
                                       haben_konto=self.a.konto_haben, betrag=Decimal('10'), datum=date(2024, 3, 1))
        url = f'/neu/buchhaltung/konto/{self.a.konto_soll.nummer}/?jahr=2024'
        eins = self._seite(url)
        self.assertEqual(len(eins.context['zeilen']), N)
        zwei = self._seite(url + '&seite=2')
        zeilen = list(zwei.context['zeilen'])
        self.assertEqual(len(zeilen), 11)
        start = zwei.context['eroeffnung'] + Decimal('1500')
        self.assertEqual(zeilen[0]['saldo'], start + Decimal('10') * N)        # nicht bei null neu begonnen
        self.assertEqual(zwei.context['endsaldo'], start + Decimal('10') * (N + 10))

class RollenDesPfadsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_der_pfad_wird_einmal_aufgeloest(self):
        _rollen_des_pfads.cache_clear()
        with organisation_kontext(self.a.organisation):
            for _ in range(5):
                darf_oeffnen(self.a.benutzer, '/neu/benutzer/neu/?x=1', set())
        info = _rollen_des_pfads.cache_info()
        self.assertEqual((info.misses, info.hits), (1, 4))

    def test_unbekannter_pfad_bleibt_offen_und_geschuetzter_gesperrt(self):
        self.assertTrue(darf_oeffnen(self.a.benutzer, '/gibt/es/nicht/', set()))
        self.assertFalse(darf_oeffnen(self.a.benutzer, '/neu/benutzer/neu/', set()))
