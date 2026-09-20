"""Die Tabellen in `core/entitlements.py` sagen dasselbe wie `docs/MARKT.md`.

WARUM DAS EIN TEST IST UND KEIN KOMMENTAR

Die Zuschnitte stehen zweimal: kaufmännisch begründet in MARKT.md, maschinen-
lesbar im Code. Zwei Quellen für dieselbe Zahl sind die Stelle, an der
Preisseite und Programm auseinanderlaufen — nicht sofort, sondern beim
übernächsten Mal, wenn jemand eine Zeile ändert und die andere vergisst.

Dieser Test liest die Markdown-Tabellen WIRKLICH und vergleicht sie. Eine
Kopie der Zahlen im Test zu prüfen wäre eine dritte Quelle und schlimmer als
keine.

WAS ER ZUSÄTZLICH FESTHÄLT

Dass noch keine Sperre eingezogen ist. Schritt 1 des Entwurfs ist die Tabelle,
Schritt 3 sind die Sperren; dazwischen steht ein Entscheid. Ein Modul, das
schon still wirkt, obwohl der Entscheid aussteht, wäre eine unangekündigte
Änderung am Produkt.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

from core.entitlements import (GRENZEN, MERKMALE, NICHT_DURCHGESETZT, STUFEN,
                               UnbekannteStufe, UnbekanntesMerkmal, darf,
                               grenze, grenze_durchsetzbar, stufe_mindestens)

WURZEL = pathlib.Path(settings.BASE_DIR)
MARKT = WURZEL / 'docs' / 'MARKT.md'


def _zeilen(text, kopf_beginnt_mit):
    """Die Zeilen EINER Markdown-Tabelle, erkannt an ihrer Kopfzeile."""
    gefunden, aus = False, []
    for zeile in text.split('\n'):
        if zeile.startswith(kopf_beginnt_mit):
            gefunden = True
            continue
        if gefunden:
            if not zeile.startswith('|'):
                break
            felder = [f.strip() for f in zeile.strip('|').split('|')]
            if set(''.join(felder)) <= {'-'}:      # die Trennzeile
                continue
            aus.append(felder)
    if not gefunden:
        raise AssertionError(
            f'Die Tabelle «{kopf_beginnt_mit}…» steht nicht mehr in MARKT.md. '
            f'Dann prüft dieser Test nichts — er wird lieber rot.')
    return aus


class TabellenStimmenUeberein(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.text = MARKT.read_text(encoding='utf-8')

    def test_die_stufen_heissen_dort_genauso(self):
        kopf = _zeilen(self.text, '| | **Start**')
        # Die Kopfzeile selbst ist verbraucht; die Namen stehen darin.
        zeile = [z for z in self.text.split('\n') if z.startswith('| | **Start**')][0]
        namen = [f.strip().strip('*').lower()
                 for f in zeile.strip('|').split('|')[1:]]
        self.assertEqual(list(STUFEN), namen)
        self.assertTrue(kopf, 'Die Stufentabelle hat keine Zeilen.')

    def test_einheiten_und_nutzer_stimmen_zahl_fuer_zahl(self):
        tabelle = {z[0]: z[1:] for z in _zeilen(self.text, '| | **Start**')}

        def zahlen(beschriftung):
            aus = []
            for feld in tabelle[beschriftung]:
                roh = feld.replace("'", '').replace(' GB', '')
                aus.append(None if roh == 'unbegrenzt' else int(roh))
            return aus

        for art, beschriftung in (('einheiten', 'Einheiten'),
                                  ('nutzer', 'Nutzer'),
                                  ('speicher', 'Speicher')):
            with self.subTest(grenze=art):
                self.assertEqual(
                    [GRENZEN[art][s] for s in STUFEN], zahlen(beschriftung),
                    f'GRENZEN[{art!r}] weicht von MARKT.md ab.')

    def test_jedes_merkmal_steht_mit_derselben_stufe_in_markt_md(self):
        """Beide Richtungen — sonst fällt nur die eine Sorte Abweichung auf."""
        dort = {}
        for stufe, funktion, _bestand in _zeilen(self.text, '| Ab Stufe | Funktion'):
            dort[funktion] = stufe.lower()

        # Die Enterprise-Zeile ist organisatorisch und bewusst nicht im Code;
        # ohne diese Ausnahme wäre der Vergleich unten falsch.
        dort.pop('SLA, Premium-Support, Onboarding inklusive', None)

        hier = {bezeichnung: ab for ab, bezeichnung in MERKMALE.values()}
        self.assertEqual(
            hier, dort,
            'MERKMALE und die Tabelle in MARKT.md sagen Verschiedenes.')

    def test_die_enterprise_zeile_ist_bewusst_draussen(self):
        """Nicht vergessen, sondern ausgeschlossen — mit dem Beleg dafür."""
        dort = {f for _s, f, _b in _zeilen(self.text, '| Ab Stufe | Funktion')}
        self.assertIn('SLA, Premium-Support, Onboarding inklusive', dort)
        self.assertNotIn('SLA, Premium-Support, Onboarding inklusive',
                         {b for _a, b in MERKMALE.values()})


class AbfragenTests(SimpleTestCase):

    class _Org:
        def __init__(self, plan):
            self.abo_plan = plan

    def test_die_ordnung_ist_aufsteigend(self):
        self.assertTrue(stufe_mindestens('professional', 'team'))
        self.assertTrue(stufe_mindestens('team', 'team'))
        self.assertFalse(stufe_mindestens('start', 'team'))

    def test_eine_hoehere_stufe_traegt_alles_aus_den_tieferen(self):
        """Sonst wäre die Reihenfolge in STUFEN Dekoration."""
        for merkmal in MERKMALE:
            with self.subTest(merkmal=merkmal):
                self.assertTrue(darf(self._Org('enterprise'), merkmal))

    def test_start_traegt_keines_der_gesperrten_merkmale(self):
        for merkmal in MERKMALE:
            with self.subTest(merkmal=merkmal):
                self.assertFalse(darf(self._Org('start'), merkmal))

    def test_team_traegt_die_team_merkmale_und_nicht_die_hoeheren(self):
        for merkmal, (ab, _b) in MERKMALE.items():
            with self.subTest(merkmal=merkmal):
                self.assertEqual(darf(self._Org('team'), merkmal), ab == 'team')

    def test_ein_heutiger_plan_wirft_statt_zu_raten(self):
        """`pro` und `premium` gibt es in der neuen Struktur nicht.

        Raten wäre in beide Richtungen falsch: «alles erlauben» verschenkt
        den Ertrag, «sperren» sperrt einen zahlenden Kunden aus. Solange die
        Zuordnung offen ist, ist die laute Absage das ehrliche Ergebnis.
        """
        for plan in ('pro', 'premium', None, ''):
            with self.subTest(plan=plan):
                with self.assertRaises(UnbekannteStufe):
                    darf(self._Org(plan), 'eigentuemerportal')

    def test_ein_tippfehler_geht_nicht_als_erlaubt_durch(self):
        with self.assertRaises(UnbekanntesMerkmal):
            darf(self._Org('team'), 'eigentuemerprotal')

    def test_grenzen_kommen_je_stufe(self):
        self.assertEqual(grenze(self._Org('team'), 'einheiten'), 150)
        self.assertIsNone(grenze(self._Org('enterprise'), 'nutzer'))

    def test_der_speicher_steht_da_und_ist_nicht_durchsetzbar(self):
        """Die Zahl gehört zur Struktur, die Sperre gibt es nicht.

        Es existiert keine Stelle im Bestand, die Speicher je Organisation
        zählt. Wer die Grenze prüfte, prüfte gegen eine Zahl, die niemand
        erhebt.
        """
        self.assertEqual(grenze(self._Org('team'), 'speicher'), 50)
        self.assertFalse(grenze_durchsetzbar('speicher'))
        self.assertTrue(grenze_durchsetzbar('einheiten'))
        self.assertTrue(grenze_durchsetzbar('nutzer'))
        self.assertEqual(NICHT_DURCHGESETZT, {'speicher'})


class NochKeineSperreTests(SimpleTestCase):
    """Schritt 1 ist die Tabelle, nicht die Sperre.

    Ein Modul, das schon still wirkt, obwohl der Entscheid darüber aussteht,
    wäre eine unangekündigte Änderung am Produkt. Dieser Test hält fest, dass
    es das nicht tut — und wird rot, sobald jemand die erste Sperre einzieht.
    Dann gehört er gestrichen, zusammen mit dem Entscheid im Rücken.
    """

    def test_kein_fachcode_ruft_die_entitlements_auf(self):
        import subprocess

        treffer = subprocess.run(
            ['grep', '-rln', '--include=*.py', '--include=*.html',
             'core.entitlements\\|from core import entitlements', '.'],
            cwd=WURZEL, capture_output=True, text=True).stdout.split()
        erlaubt = {'./core/entitlements.py', './core/tests/test_entitlements.py'}
        self.assertEqual(
            set(treffer) - erlaubt, set(),
            'Die Entitlements werden bereits aufgerufen — dann ist Schritt 3 '
            'begonnen und dieser Test gehört gestrichen, nicht angepasst.')
