"""Kantonale Feiertage in der Fristenrechnung (Art. 78 OR): Der Kanton der Liegenschaft bestimmt die zusätzlichen Tage.

Quelle der Tabelle: Verzeichnis des Bundesamts für Justiz, Stand 1. Januar 2011 (`core/services/fristen.py`). Jeder Test
hat seine Gegenprobe: derselbe Tag ohne Kanton oder in einem Kanton, der ihn nicht führt, bleibt ein Werktag.
"""
from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from core.services import fristen
from core.services.fristen import feiertage, fristende, ist_werktag, kanton_von, naechster_werktag
from core.services.kantone import KANTON_NAMEN
from core.services.zahlungsverzug import definitives_fristende, fristende_von, provisorisches_fristende


class TabelleTests(SimpleTestCase):
    def test_alle_26_kantone_stehen_in_der_tabelle(self):
        self.assertEqual(set(fristen.KANTONALE_FEIERTAGE), set(KANTON_NAMEN))

    def test_zahl_der_zusatztage_je_kanton_wie_abgeschrieben(self):
        """Fällt ein Tag aus der Tabelle oder kommt einer dazu, schlägt das hier an: Die Änderung braucht die Quelle."""
        anzahl = {kt: len(tage) for kt, tage in fristen.KANTONALE_FEIERTAGE.items()}
        self.assertEqual(anzahl, {
            'ZH': 2, 'BE': 1, 'LU': 5, 'UR': 6, 'SZ': 6, 'OW': 6, 'NW': 6, 'GL': 2, 'ZG': 5, 'FR': 5, 'SO': 5, 'BS': 1,
            'BL': 1, 'SH': 2, 'AR': 0, 'AI': 5, 'SG': 2, 'GR': 0, 'AG': 6, 'TG': 2, 'TI': 8, 'VD': 2, 'VS': 6, 'NE': 2,
            'GE': 2, 'JU': 6})

    def test_jeder_eintrag_hat_einen_namen_und_ein_datum(self):
        for kt in fristen.KANTONALE_FEIERTAGE:
            with self.subTest(kanton=kt):
                tage = feiertage(2026, kt)
                self.assertGreaterEqual(len(tage), 8)
                self.assertTrue(all(tage.values()))

    def test_die_allgemeinen_tage_fallen_in_keinem_kanton_weg(self):
        """Das Wallis führt den Karfreitag nicht; er bleibt trotzdem frei — die Frist endet eher später als früher."""
        allgemein = set(feiertage(2026))
        for kt in fristen.KANTONALE_FEIERTAGE:
            self.assertTrue(allgemein <= set(feiertage(2026, kt)), kt)


class KantonaleTageTests(SimpleTestCase):
    def test_tag_der_arbeit_in_zuerich_nicht_in_bern(self):
        tag = date(2026, 5, 1)                                  # Freitag
        self.assertFalse(ist_werktag(tag, 'ZH'))
        self.assertTrue(ist_werktag(tag, 'BE'))
        self.assertTrue(ist_werktag(tag))

    def test_fronleichnam_in_luzern_nicht_in_zuerich(self):
        tag = date(2026, 6, 4)                                  # Donnerstag, 60 Tage nach Ostersonntag (5.4.2026)
        self.assertEqual(feiertage(2026, 'LU')[tag], 'Fronleichnam')
        self.assertTrue(ist_werktag(tag, 'ZH'))

    def test_bettagsmontag_waadt_und_genfer_bettag(self):
        self.assertFalse(ist_werktag(date(2026, 9, 21), 'VD'))  # Montag nach dem dritten Sonntag im September (20.9.)
        self.assertTrue(ist_werktag(date(2026, 9, 21), 'GE'))
        self.assertFalse(ist_werktag(date(2026, 9, 10), 'GE'))  # Donnerstag nach dem ersten Sonntag im September (6.9.)
        self.assertTrue(ist_werktag(date(2026, 9, 10), 'VD'))
        self.assertFalse(ist_werktag(date(2026, 12, 31), 'GE'))
        self.assertTrue(ist_werktag(date(2026, 12, 31), 'ZH'))

    def test_neuenburg_zweiter_januar_nur_nach_einem_sonntag(self):
        self.assertIn(date(2023, 1, 2), feiertage(2023, 'NE'))      # 1.1.2023 war ein Sonntag
        self.assertNotIn(date(2026, 1, 2), feiertage(2026, 'NE'))   # 1.1.2026 ist ein Donnerstag
        self.assertIn(date(2026, 1, 2), feiertage(2026, 'BE'))

    def test_fristende_rueckt_ueber_den_kantonalen_feiertag(self):
        # 8.11.2026 + 30 Tage = Dienstag, 8.12.2026 (Mariä Empfängnis in Luzern).
        self.assertEqual(fristende(date(2026, 11, 8), 30, 'LU'), date(2026, 12, 9))
        self.assertEqual(fristende(date(2026, 11, 8), 30, 'ZH'), date(2026, 12, 8))
        self.assertEqual(fristende(date(2026, 11, 8), 30), date(2026, 12, 8))
        self.assertEqual(naechster_werktag(date(2026, 12, 8), 'lu '), date(2026, 12, 9))

    def test_unbekanntes_kuerzel_zaehlt_wie_kein_kanton(self):
        self.assertEqual(feiertage(2026, 'XX'), feiertage(2026))
        self.assertEqual(feiertage(2026, None), feiertage(2026))


class KantonVonTests(SimpleTestCase):
    def setUp(self):
        self.lg = SimpleNamespace(kanton='lu')
        self.vertrag = SimpleNamespace(einheit_id=1, einheit=SimpleNamespace(liegenschaft=self.lg))

    def test_aus_liegenschaft_vertrag_und_pendenz(self):
        self.assertEqual(kanton_von(self.lg), 'LU')
        self.assertEqual(kanton_von(self.vertrag), 'LU')
        self.assertEqual(kanton_von(SimpleNamespace(liegenschaft_id=3, liegenschaft=self.lg, vertrag=None)), 'LU')
        self.assertEqual(kanton_von(SimpleNamespace(liegenschaft_id=None, vertrag=self.vertrag)), 'LU')

    def test_ohne_angabe_leer(self):
        self.assertEqual(kanton_von(None), '')
        self.assertEqual(kanton_von(SimpleNamespace(kanton='')), '')
        self.assertEqual(kanton_von(SimpleNamespace(liegenschaft_id=None, vertrag=None)), '')
        self.assertEqual(kanton_von(SimpleNamespace(einheit_id=None)), '')


class ZahlungsfristTests(SimpleTestCase):
    """Art. 257d OR: Die Zahlungsfrist endet am Ort der Liegenschaft nicht an einem kantonalen Feiertag."""

    def test_definitives_und_provisorisches_fristende(self):
        self.assertEqual(definitives_fristende(date(2026, 11, 8), 30, 'LU'), date(2026, 12, 9))
        self.assertEqual(definitives_fristende(date(2026, 11, 8), 30), date(2026, 12, 8))
        ohne = provisorisches_fristende(date(2026, 10, 31), 30)
        self.assertEqual(ohne, date(2026, 12, 8))               # 31.10. + 1 + 7 + 30 Tage
        self.assertEqual(provisorisches_fristende(date(2026, 10, 31), 30, 'LU'), date(2026, 12, 9))

    def test_fristende_einer_pendenz_liest_den_kanton_der_liegenschaft(self):
        def pendenz(kanton):
            return SimpleNamespace(faellig_am=date(2026, 12, 8), zugang_am=date(2026, 11, 8), versand_am=None,
                                   frist_tage=30, liegenschaft_id=1, liegenschaft=SimpleNamespace(kanton=kanton),
                                   vertrag=None)
        self.assertEqual(fristende_von(pendenz('LU')), date(2026, 12, 9))
        self.assertEqual(fristende_von(pendenz('ZH')), date(2026, 12, 8))
        self.assertEqual(fristende_von(pendenz('')), date(2026, 12, 8))
