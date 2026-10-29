"""Art. 78 OR: Fristende auf Samstag, Sonntag oder Feiertag rückt auf den nächsten Werktag (Audit MIET-10).

Jeder Test hat seine Gegenprobe: dasselbe Datum, einen Tag früher oder später, bleibt stehen. Ohne sie wäre ein
Test grün, der alles verschiebt.
"""
from datetime import date

from django.test import SimpleTestCase

from core.services.fristen import feiertage, fristende, ist_werktag, naechster_werktag, ostersonntag


class OsternTests(SimpleTestCase):
    def test_ostersonntag_bekannter_jahre(self):
        # Quelle: gregorianischer Kalender (Computus), unabhängig nachgeschlagen.
        erwartet = {2000: date(2000, 4, 23), 2024: date(2024, 3, 31), 2025: date(2025, 4, 20),
                    2026: date(2026, 4, 5), 2027: date(2027, 3, 28), 2038: date(2038, 4, 25)}
        for jahr, tag in erwartet.items():
            with self.subTest(jahr=jahr):
                self.assertEqual(ostersonntag(jahr), tag)

    def test_bewegliche_feiertage_2026(self):
        f = feiertage(2026)
        self.assertEqual(f[date(2026, 4, 3)], 'Karfreitag')
        self.assertEqual(f[date(2026, 4, 6)], 'Ostermontag')
        self.assertEqual(f[date(2026, 5, 14)], 'Auffahrt')
        self.assertEqual(f[date(2026, 5, 25)], 'Pfingstmontag')
        self.assertEqual(f[date(2026, 8, 1)], 'Bundesfeiertag')
        # Gegenprobe: der Gründonnerstag ist kein bundesweiter Feiertag.
        self.assertNotIn(date(2026, 4, 2), f)


class NaechsterWerktagTests(SimpleTestCase):
    def test_sonntag_rueckt_auf_montag(self):
        self.assertEqual(naechster_werktag(date(2026, 12, 6)), date(2026, 12, 7))      # Sonntag
        self.assertEqual(naechster_werktag(date(2026, 12, 7)), date(2026, 12, 7))      # Montag bleibt

    def test_samstag_rueckt_auf_montag_konservativ(self):
        """Die Zahlungsfrist des Vermieters ist eine private Frist; der Samstag wird trotzdem übersprungen, weil
        ein zu spät freigegebenes Kündigungsrecht kein Schaden ist, ein zu früh freigegebenes schon."""
        self.assertEqual(naechster_werktag(date(2026, 12, 5)), date(2026, 12, 7))
        self.assertEqual(naechster_werktag(date(2026, 12, 4)), date(2026, 12, 4))      # Freitag bleibt

    def test_bundesfeiertag_am_samstag_und_unter_der_woche(self):
        self.assertEqual(naechster_werktag(date(2026, 8, 1)), date(2026, 8, 3))        # Sa 1.8. -> Mo
        self.assertEqual(naechster_werktag(date(2025, 8, 1)), date(2025, 8, 4))        # Fr 1.8. -> Mo
        self.assertEqual(naechster_werktag(date(2025, 7, 31)), date(2025, 7, 31))      # Do davor bleibt

    def test_ostern_langes_wochenende(self):
        # Karfreitag 3.4.2026 (Fr) -> Sa, So, Ostermontag 6.4. -> Dienstag 7.4.
        self.assertEqual(naechster_werktag(date(2026, 4, 3)), date(2026, 4, 7))
        self.assertEqual(naechster_werktag(date(2026, 4, 2)), date(2026, 4, 2))        # Gegenprobe: Donnerstag

    def test_weihnachten_und_neujahr_ueber_den_jahreswechsel(self):
        # 25.12.2026 ist ein Freitag: Weihnachten, Sa, So, dann Montag 28.12.
        self.assertEqual(naechster_werktag(date(2026, 12, 25)), date(2026, 12, 28))
        # 26.12.2027 (So) -> Mo 27.12.2027
        self.assertEqual(naechster_werktag(date(2027, 12, 26)), date(2027, 12, 27))
        # 31.12.2027 (Fr) bleibt; 1.1.2028 (Sa, Neujahr) -> Mo 3.1.2028
        self.assertEqual(naechster_werktag(date(2027, 12, 31)), date(2027, 12, 31))
        self.assertEqual(naechster_werktag(date(2028, 1, 1)), date(2028, 1, 3))

    def test_ist_werktag(self):
        self.assertTrue(ist_werktag(date(2026, 10, 28)))        # Mittwoch
        self.assertFalse(ist_werktag(date(2026, 10, 31)))       # Samstag
        self.assertFalse(ist_werktag(date(2026, 11, 1)))        # Sonntag


class FristendeTests(SimpleTestCase):
    def test_schaltjahr_30_tage_ab_30_januar(self):
        """30.1.2024 + 30 Tage = 29.2.2024 (Schaltjahr, Donnerstag); im Jahr darauf 1.3.2025 (Samstag) -> Montag."""
        self.assertEqual(fristende(date(2024, 1, 30), 30), date(2024, 2, 29))
        self.assertEqual(fristende(date(2025, 1, 30), 30), date(2025, 3, 3))

    def test_monatsende(self):
        # 1.11.2026 + 30 = 1.12.2026 (Dienstag)
        self.assertEqual(fristende(date(2026, 11, 1), 30), date(2026, 12, 1))
        # 31.10.2026 + 30 = 30.11.2026 (Montag)
        self.assertEqual(fristende(date(2026, 10, 31), 30), date(2026, 11, 30))

    def test_fristende_am_sonntag_geht_auf_montag(self):
        # Zugang Freitag 6.11.2026 + 30 = Sonntag 6.12.2026 -> Montag 7.12.
        self.assertEqual(fristende(date(2026, 11, 6), 30), date(2026, 12, 7))
        # Gegenprobe: Zugang Samstag 7.11. + 30 = Montag 7.12. (bleibt)
        self.assertEqual(fristende(date(2026, 11, 7), 30), date(2026, 12, 7))
        # Gegenprobe: Zugang Donnerstag 5.11. + 30 = Samstag 5.12. -> Montag 7.12.
        self.assertEqual(fristende(date(2026, 11, 5), 30), date(2026, 12, 7))
        # Zugang Mittwoch 4.11. + 30 = Freitag 4.12. bleibt
        self.assertEqual(fristende(date(2026, 11, 4), 30), date(2026, 12, 4))
