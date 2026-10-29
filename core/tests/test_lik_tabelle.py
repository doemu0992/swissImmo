"""MIET-14: Die LIK-Tabelle (Basis Dezember 2020) darf nicht hinter dem Kalender zurückfallen.

Die Tabelle in `core/services/lik.py` wird von Hand nachgeführt. Endete sie im Juni 2026, blieben
Indexanpassungen für Juli bis September 2026 stillschweigend aus. Der Wächter unten schlägt an, sobald
die Tabelle mehr als drei Monate hinter dem Kalender liegt, und sagt, was zu tun ist.

Der Wächter hängt am heutigen Datum — und das ist Absicht: Er ist die Erinnerung, die Tabelle zu pflegen.
Die übrigen Tests rechnen mit festen Daten und sind von der Uhr unabhängig.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase

from core.services import lik


class TabellenInhaltTests(SimpleTestCase):

    def test_juli_bis_september_2026_sind_eingetragen(self):
        self.assertEqual(lik.lik_punkte_fuer(2026, 7), Decimal('108.2'))
        self.assertEqual(lik.lik_punkte_fuer(2026, 8), Decimal('108.6'))
        self.assertEqual(lik.lik_punkte_fuer(2026, 9), Decimal('108.5'))

    def test_oktober_2026_ist_noch_nicht_veroeffentlicht_und_nicht_erfunden(self):
        """Das BFS veröffentlicht den Oktober Anfang November: Ohne Wert bleibt die Anpassung gesperrt."""
        self.assertIsNone(lik.lik_punkte_fuer(2026, 10))

    def test_bestehende_werte_unveraendert(self):
        self.assertEqual(lik.lik_punkte_fuer(2026, 6), Decimal('108.3'))
        self.assertEqual(lik.lik_punkte_fuer(2025, 12), Decimal('106.9'))
        self.assertEqual(lik.lik_punkte_fuer(2021, 1), Decimal('100.1'))

    def test_letzter_monat_wird_gefunden(self):
        self.assertEqual(lik.letzter_tabellenmonat(), (2026, 9))

    def test_indexanpassung_kennt_die_neuen_monate(self):
        """Die Anpassung rechnete bis Juni 2026 und meldete danach «kein Wert»."""
        from core.services import index_anpassung as ia
        self.assertEqual(ia.letzter_stand(), date(2026, 9, 1))
        self.assertEqual(ia.lik_punkte(date(2026, 9, 1)), Decimal('108.5'))
        self.assertIn(date(2026, 8, 1), ia.verfuegbare_staende())

    def test_aktueller_wert_ohne_netz_ist_september_2026(self):
        stand, punkte, basis = lik.aktueller_lik_wert(live=False)
        self.assertEqual((stand, punkte, basis), (date(2026, 9, 1), Decimal('108.5'), 'Dezember 2020'))


class RueckstandTests(SimpleTestCase):
    """Die Regel des Wächters, an festen Daten."""

    def test_drei_monate_sind_noch_in_ordnung(self):
        # Tabelle bis September 2026: Dezember 2026 liegt drei Monate dahinter.
        self.assertEqual(lik.tabelle_rueckstand_monate(date(2026, 12, 31)), 3)
        self.assertEqual(lik.tabelle_hinweis(date(2026, 12, 31)), '')

    def test_vier_monate_loesen_den_hinweis_aus(self):
        self.assertEqual(lik.tabelle_rueckstand_monate(date(2027, 1, 1)), 4)
        hinweis = lik.tabelle_hinweis(date(2027, 1, 1))
        self.assertIn('September 2026', hinweis)
        self.assertIn('LIK_DEZ2020', hinweis)

    def test_tabelle_mit_luecke_im_aktuellen_monat_ist_ein_hinweis_kein_absturz(self):
        gekuerzt = {j: list(r) for j, r in lik.LIK_DEZ2020.items()}
        gekuerzt[2026] = gekuerzt[2026][:6]            # wie vor dieser Änderung: bis Juni 2026
        with mock.patch.dict(lik.LIK_DEZ2020, gekuerzt, clear=True):
            self.assertEqual(lik.letzter_tabellenmonat(), (2026, 6))
            self.assertEqual(lik.tabelle_rueckstand_monate(date(2026, 10, 28)), 4)
            self.assertIn('Juni 2026', lik.tabelle_hinweis(date(2026, 10, 28)))
            # Fail-safe wie bisher: kein Wert statt einer Ausnahme
            self.assertIsNone(lik.lik_punkte_fuer(2026, 9))

    def test_leere_tabelle_gibt_einen_hinweis(self):
        with mock.patch.dict(lik.LIK_DEZ2020, {}, clear=True):
            self.assertIsNone(lik.letzter_tabellenmonat())
            self.assertIn('kein Monat', lik.tabelle_hinweis(date(2026, 10, 28)))


class WaechterTests(SimpleTestCase):

    def test_die_tabelle_liegt_nicht_mehr_als_drei_monate_hinter_dem_kalender(self):
        """Wächter. Schlägt er an: Monatswerte des BFS (Landesindex der Konsumentenpreise, Basis Dezember 2020)
        in `LIK_DEZ2020` nachtragen — Quelle und Abrufdatum in den Kommentar. Nicht Werte raten."""
        from django.utils import timezone
        heute = timezone.localdate()
        hinweis = lik.tabelle_hinweis(heute)
        self.assertEqual(hinweis, '', hinweis)
