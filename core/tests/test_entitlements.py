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
        erlaubt = {'./core/entitlements.py', './core/tests/test_entitlements.py',
                   './core/tests/test_entitlement_abdeckung.py'}
        self.assertEqual(
            set(treffer) - erlaubt, set(),
            'Die Entitlements werden bereits aufgerufen — dann ist Schritt 3 '
            'begonnen und dieser Test gehört gestrichen, nicht angepasst.')


class DekoratorTests(SimpleTestCase):
    """Der Mechanismus für Schritt 3 — gebaut, noch nirgends angewendet.

    Dass ihn keine Ansicht trägt, hält `test_entitlement_abdeckung` fest.
    Hier steht, dass er das Richtige TÄTE, wenn jemand ihn anwendet.
    """

    def setUp(self):
        from django.test import RequestFactory
        self.anfrage = RequestFactory().get('/irgendwo/')
        # `messages` braucht eine Ablage; ohne sie wirft der Dekorator beim
        # Sperren, und der Test misst dann das Fehlen der Ablage statt die
        # Sperre.
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.db import SessionStore
        self.anfrage.session = SessionStore()
        self.anfrage._messages = FallbackStorage(self.anfrage)

    def _ansicht(self, merkmal='eigentuemerportal'):
        from django.http import HttpResponse

        from core.entitlements import merkmal_erforderlich

        @merkmal_erforderlich(merkmal)
        def sicht(request):
            return HttpResponse('durchgelassen')
        return sicht

    class _Org:
        def __init__(self, plan):
            self.abo_plan = plan

    def test_die_marke_haengt_an_der_ansicht(self):
        from core.entitlements import MERKMAL_ATTRIBUT, merkmal_der_ansicht

        sicht = self._ansicht()
        self.assertEqual(merkmal_der_ansicht(sicht), 'eigentuemerportal')
        self.assertEqual(getattr(sicht, MERKMAL_ATTRIBUT), 'eigentuemerportal')

    def test_die_marke_ueberlebt_einen_aeusseren_dekorator(self):
        """Sonst fände der Sweep sie nicht, sobald `rolle_erforderlich`
        darüber steht — und die Abdeckung wäre ein Trugschluss.

        `functools.wraps` nimmt das `__dict__` mit; gemessen, nicht
        angenommen.
        """
        from functools import wraps

        from core.entitlements import merkmal_der_ansicht

        def aussen(f):
            @wraps(f)
            def g(*a, **k):
                return f(*a, **k)
            return g

        self.assertEqual(merkmal_der_ansicht(aussen(self._ansicht())),
                         'eigentuemerportal')

    def test_die_hoehere_stufe_kommt_durch(self):
        self.anfrage.organisation = self._Org('professional')
        antwort = self._ansicht()(self.anfrage)
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.content, b'durchgelassen')

    def test_die_tiefere_stufe_wird_zum_abo_geschickt_statt_abgewiesen(self):
        """Kein 403. Eine gesperrte Funktion soll verkaufen, nicht schimpfen —
        wer hier landet, hat sie ja gesucht."""
        self.anfrage.organisation = self._Org('start')
        antwort = self._ansicht()(self.anfrage)
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(antwort['Location'], '/neu/abonnement/')

    def test_die_meldung_nennt_die_funktion_beim_namen(self):
        """«Diese Funktion» hilft niemandem — der Name aus MARKT.md schon."""
        from django.contrib.messages import get_messages

        self.anfrage.organisation = self._Org('start')
        self._ansicht()(self.anfrage)
        texte = [str(m) for m in get_messages(self.anfrage)]
        self.assertTrue(any('Eigentümerportal' in t for t in texte), texte)

    def test_eine_unbekannte_stufe_wird_durchgelassen(self):
        """fail-open, und zwar bewusst.

        Eine Funktionssperre, die bei einem Fehler zuschlägt, sperrt eine
        zahlende Verwaltung aus etwas, wofür sie bezahlt hat. Der Schaden ist
        einseitig.

        Heute trifft das auf JEDE Organisation zu — `pro` und `premium` gibt
        es in STUFEN nicht. Ein weiterer Grund, den Dekorator noch nirgends
        anzuwenden.
        """
        for plan in ('pro', 'premium', None):
            with self.subTest(plan=plan):
                self.anfrage.organisation = self._Org(plan)
                antwort = self._ansicht()(self.anfrage)
                self.assertEqual(antwort.status_code, 200)

    def test_ohne_organisation_wird_ebenfalls_durchgelassen(self):
        """Dieselbe Begründung — und der Fall tritt vor dem Anmelden auf."""
        self.anfrage.organisation = None
        self.assertEqual(self._ansicht()(self.anfrage).status_code, 200)
