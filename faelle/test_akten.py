"""Tests des Aktenregisters.

Der Zweck der Etappe ist eine einzige Zusage: **Wer eine Akte bedienen kann,
kann alle.** Dafür müssen zwei Dinge stimmen, und beide werden hier geprüft.

1. Jeder Aktentyp führt dieselben fünf Reiter in derselben Reihenfolge, plus
   höchstens einen eigenen. Ohne diesen Test wächst der Satz wieder auseinander,
   sobald jemand einen Reiter „nur für diesen einen Fall" ergänzt.
2. Kein heutiger Reiter fällt beim Übergang durch. Ein alter Reiter ohne Ziel
   verschwände stillschweigend aus der Oberfläche — und mit ihm sein Inhalt.

Die Tests arbeiten bewusst mit **konkreten Reitern**, nicht mit Gesamtzahlen.
Bei den vorangegangenen Etappen war das dreimal die Fehlerquelle: Eine Zählung
stimmt nur so lange, wie die Grundlage nicht wächst.
"""
from django.test import TestCase, override_settings

from core.tenancy import organisation_kontext as mandant
from core.tests._isolation import MandantenFixture
from faelle.akten import (
    AKTENTYPEN, BEZEICHNUNGEN, REITER_ENTITLEMENT, REITER_FIX, aus_alt,
    reiter_fuer, typ_von,
)

#: Die Reiter, die jede Detailseite heute führt — abgeschrieben aus den Views,
#: damit der Test merkt, wenn dort einer dazukommt.
HEUTE = {
    'liegenschaft': ['objekte', 'finanzen', 'technik', 'unterhalt', 'fristen',
                     'schaeden', 'dokumente'],
    'objekt': ['uebersicht', 'fotos', 'raumbuch', 'verhaeltnisse', 'mietzins',
               'geraete', 'zaehler', 'schluessel'],
    'mietverhaeltnis': ['uebersicht', 'finanzen', 'mietzins', 'schaeden',
                        'pendenzen', 'formulare', 'dokumente', 'verlauf'],
    'person': ['uebersicht', 'vertraege', 'finanzen', 'dokumente',
               'aktivitaet', 'verlauf'],
    'schaden': ['uebersicht', 'verlauf', 'handwerker', 'fotos'],
}


class RegisterTests(TestCase):
    #: Ausgeschrieben und nicht `REITER_FIX`, mit Absicht. Die erste Fassung
    #: verglich `typ.reiter[:5]` mit `REITER_FIX` — woraus `reiter` selbst
    #: gebaut wird. Der Vergleich war damit per Konstruktion immer wahr: Eine
    #: Gegenprobe, die die Reihenfolge in `REITER_FIX` vertauschte, blieb grün.
    #: Ein Test darf seine Erwartung nicht aus dem Prüfling ableiten.
    VEREINBART = ('chronik', 'stammdaten', 'finanzen', 'dokumente', 'faelle')

    def test_die_fuenf_festen_reiter_sind_die_vereinbarten(self):
        self.assertEqual(REITER_FIX, self.VEREINBART,
                         'Der feste Reitersatz weicht von KONZEPT-UI.md ab.')

    def test_jeder_typ_fuehrt_die_fuenf_festen_reiter(self):
        for schluessel, typ in AKTENTYPEN.items():
            with self.subTest(typ=schluessel):
                self.assertEqual(
                    typ.reiter[:5], self.VEREINBART,
                    'Die fünf festen Reiter stehen nicht vorn oder nicht in der '
                    'vereinbarten Reihenfolge.')

    def test_hoechstens_ein_eigener_reiter(self):
        for schluessel, typ in AKTENTYPEN.items():
            with self.subTest(typ=schluessel):
                self.assertLessEqual(len(typ.reiter), 6)

    def test_der_eigene_reiter_heisst_nicht_wie_ein_fester(self):
        for schluessel, typ in AKTENTYPEN.items():
            if not typ.eigener_reiter:
                continue
            with self.subTest(typ=schluessel):
                self.assertNotIn(typ.eigener_reiter[0], REITER_FIX)

    def test_jeder_feste_reiter_hat_eine_bezeichnung(self):
        for r in REITER_FIX:
            self.assertIn(r, BEZEICHNUNGEN)

    def test_unbekannter_typ_wirft_mit_hinweis(self):
        with self.assertRaises(KeyError) as fehler:
            typ_von('gibtsnicht')
        self.assertIn('Bekannt', str(fehler.exception))

    def test_modellangabe_ist_aufloesbar(self):
        """Ein Tippfehler im Modellnamen faellt sonst erst in 4a.6 auf."""
        from django.apps import apps
        for schluessel, typ in AKTENTYPEN.items():
            with self.subTest(typ=schluessel):
                app, modell = typ.modell.split('.')
                self.assertIsNotNone(apps.get_model(app, modell))


class UebergangTests(TestCase):
    def test_jeder_alte_reiter_hat_ein_ziel(self):
        """Der wichtigste Test dieser Etappe.

        Ein alter Reiter ohne Ziel verschwände stillschweigend — und der Inhalt
        dahinter wäre über die Oberfläche nicht mehr erreichbar.
        """
        for typ_schluessel, alte in HEUTE.items():
            typ = typ_von(typ_schluessel)
            for alt in alte:
                with self.subTest(typ=typ_schluessel, reiter=alt):
                    self.assertIn(
                        alt, typ.alt,
                        f'{alt!r} hat kein Ziel im neuen Satz von {typ_schluessel!r}.')

    def test_jedes_ziel_ist_ein_reiter_dieses_typs(self):
        for typ_schluessel, typ in AKTENTYPEN.items():
            for alt, ziel in typ.alt.items():
                with self.subTest(typ=typ_schluessel, von=alt):
                    self.assertIn(
                        ziel, typ.reiter,
                        f'{alt!r} zeigt auf {ziel!r}, das dieser Typ gar nicht führt.')

    def test_beide_eingabeformen_werden_verstanden(self):
        """Views liefern Tupel, Pruefungen oft nur die Schluessel."""
        als_schluessel = aus_alt('mietverhaeltnis', HEUTE['mietverhaeltnis'])
        als_tupel = aus_alt('mietverhaeltnis',
                            [(k, k.title(), None) for k in HEUTE['mietverhaeltnis']])
        self.assertEqual([e[0] for e in als_schluessel], [e[0] for e in als_tupel])

    def test_umwandlung_liefert_das_format_der_oberflaeche(self):
        neu = aus_alt('mietverhaeltnis', HEUTE['mietverhaeltnis'])
        self.assertTrue(all(len(e) == 3 for e in neu))
        self.assertEqual([e[0] for e in neu][:5], list(REITER_FIX))

    def test_zaehler_werden_addiert_nicht_ueberschrieben(self):
        """Zwei alte Reiter auf einen neuen — die zweite Zahl darf nicht verfallen."""
        alt = [('schaeden', 'Schäden', 3), ('pendenzen', 'Pendenzen', 4)]
        neu = dict((e[0], e[2]) for e in aus_alt('mietverhaeltnis', alt))
        self.assertEqual(neu['faelle'], 7)

    def test_null_zaehler_wird_zu_none(self):
        alt = [('finanzen', 'Finanzen', 0)]
        neu = dict((e[0], e[2]) for e in aus_alt('mietverhaeltnis', alt))
        self.assertIsNone(neu['finanzen'])

    def test_alter_reiter_ohne_ziel_wirft_statt_zu_schweigen(self):
        with self.assertRaises(KeyError) as fehler:
            aus_alt('mietverhaeltnis', [('erfunden', 'Erfunden', 1)])
        self.assertIn('kein Ziel', str(fehler.exception))

    def test_reihenfolge_ist_ueber_alle_typen_gleich(self):
        reihenfolgen = {
            t: [e[0] for e in reiter_fuer(t)][:5] for t in AKTENTYPEN}
        self.assertEqual(len(set(map(tuple, reihenfolgen.values()))), 1,
                         'Die festen Reiter stehen nicht überall gleich.')


class EntitlementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')

    def test_ohne_organisation_werden_alle_reiter_gezeigt(self):
        """Kein Kontext heisst nicht: sperren. Die Prüfung greift erst mit Organisation."""
        namen = [e[0] for e in reiter_fuer('mietverhaeltnis')]
        self.assertIn('faelle', namen)

    @override_settings(SWISSIMMO_VORGABE_STUFE='verwaltung')
    def test_mit_berechtigung_erscheint_der_faelle_reiter(self):
        with mandant(self.a.organisation):
            namen = [e[0] for e in reiter_fuer(
                'mietverhaeltnis', organisation=self.a.organisation)]
            self.assertIn('faelle', namen)

    @override_settings(SWISSIMMO_VORGABE_STUFE='basis')
    def test_ohne_berechtigung_faellt_er_weg_statt_auszugrauen(self):
        with mandant(self.a.organisation):
            namen = [e[0] for e in reiter_fuer(
                'mietverhaeltnis', organisation=self.a.organisation)]
            self.assertNotIn('faelle', namen)
            self.assertIn('stammdaten', namen)

    def test_jeder_geforderte_schluessel_ist_bekannt(self):
        from core.funktionen import FUNKTIONEN, MODULE
        for reiter, schluessel in REITER_ENTITLEMENT.items():
            with self.subTest(reiter=reiter):
                self.assertIn(schluessel, {**FUNKTIONEN, **MODULE})
