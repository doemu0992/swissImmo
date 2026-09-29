"""Vier Abostufen aus einer Quelle (docs/AUFTRAG-ABOSTUFEN.md, D7).

Geprüft wird, was beim Umbau von basis/aufbau/verwaltung/portfolio auf
start/team/professional/enterprise nicht passieren darf:

1. Eine Verwaltung verliert oder gewinnt eine Funktion. Die Vorgabestufe muss
   exakt die zehn Schlüssel freigeben, die vor dem Umbau frei waren.
2. Modell, Preisseite und Funktionsfreigabe laufen wieder auseinander.
3. Die Preisrechnung verkauft Professional mit Zusatzpaketen billiger als
   Enterprise, oder Start fasst mehr Einheiten, als es darf.
4. Die Preisseite verspricht Merkmale, die es nicht gibt (API, Speicher).

Gegenproben (je einmal eingebaut, rot gesehen, zurückgebaut):
- in core/funktionen.py 'eigentuemerportal' von «team» nach «professional»
  verschieben — `test_vorgabe_gibt_genau_die_zehn_schluessel_von_heute_frei`
  wird rot;
- in core/funktionen.py den Deckel von «team» auf `None` setzen —
  `test_team_fasst_hoechstens_300_einheiten` wird rot;
- in crm/models.py `ABO_CHOICES` eine fünfte Stufe von Hand anhängen —
  `test_auswahl_am_modell_ist_aus_funktionen_abgeleitet` wird rot.
"""
from decimal import Decimal

from django.test import Client, SimpleTestCase, TestCase

from core import funktionen as f
from crm.models import Organisation

from ._helfer import _team_user, _test_organisation

#: Die Freigabe vor dem Umbau, abgeschrieben aus der Stufe «verwaltung», die
#: bis 29.09.2026 für jede Verwaltung galt. Bewusst ausgeschrieben statt aus
#: `STUFEN` gelesen: Ein Test, der seine Erwartung aus dem Prüfling liest,
#: prüft nichts (bekannte-fallen, Nr. 12).
FREIGABE_VOR_DEM_UMBAU = frozenset({
    'akten', 'dokumente', 'monatslauf',
    'faelle', 'fristenwaechter', 'zulauf',
    'nebenkostenlauf', 'vor_ort', 'eigentuemerportal', 'mieterportal',
})


class _Org:
    """Genügt für `hat_funktion` — braucht kein echtes Modell."""


class VerhaltensneutralTests(SimpleTestCase):

    def test_vorgabe_gibt_genau_die_zehn_schluessel_von_heute_frei(self):
        frei = {k for k in f.FUNKTIONEN if f.hat_funktion(_Org(), k)}
        self.assertEqual(frei, FREIGABE_VOR_DEM_UMBAU)

    def test_vorgabestufe_ist_team(self):
        self.assertEqual(f.VORGABE_STUFE, 'team')

    def test_pflichtlaeufe_stehen_in_jeder_stufe(self):
        """`monatslauf` trägt Sollstellung, Bankabgleich, Mahnlauf, Zahllauf, MWST."""
        for stufe in f.STUFEN_REIHENFOLGE:
            with self.subTest(stufe=stufe):
                self.assertIn('monatslauf', f.STUFEN[stufe])
                self.assertIn('nebenkostenlauf', f.STUFEN[stufe])


class EineQuelleTests(TestCase):

    def test_stufencodes_sind_die_marktnamen(self):
        self.assertEqual(f.STUFEN_REIHENFOLGE,
                         ('start', 'team', 'professional', 'enterprise'))

    def test_jede_tabelle_kennt_genau_die_stufen(self):
        for name, tabelle in (('GRENZEN', f.GRENZEN), ('PREISE', f.PREISE),
                              ('STUFEN_NAMEN', f.STUFEN_NAMEN),
                              ('SUPPORT', f.SUPPORT)):
            with self.subTest(tabelle=name):
                self.assertEqual(set(tabelle), set(f.STUFEN_REIHENFOLGE))

    def test_auswahl_am_modell_ist_aus_funktionen_abgeleitet(self):
        self.assertEqual(
            [code for code, _name in Organisation.ABO_CHOICES],
            list(f.STUFEN_REIHENFOLGE))

    def test_vorgabe_am_modell_ist_die_vorgabestufe(self):
        self.assertEqual(Organisation._meta.get_field('abo_plan').default,
                         f.VORGABE_STUFE)

    def test_feld_fasst_den_laengsten_code(self):
        laenge = Organisation._meta.get_field('abo_plan').max_length
        self.assertGreaterEqual(laenge, max(map(len, f.STUFEN_REIHENFOLGE)))


class PreisrechnungTests(SimpleTestCase):

    def test_die_szenarien_aus_dem_marktaudit(self):
        erwartet = {
            20:   ('start', Decimal('39')),
            50:   ('team', Decimal('119')),          # Start endet bei 25
            150:  ('team', Decimal('119')),
            200:  ('team', Decimal('179')),          # + 1 Paket à 60
            400:  ('professional', Decimal('329')),  # Team endet bei 300
            1000: ('professional', Decimal('554')),  # + 5 Pakete à 45
            2500: ('enterprise', Decimal('899')),    # + 5 Pakete à 30
        }
        for einheiten, (stufe, preis) in erwartet.items():
            with self.subTest(einheiten=einheiten):
                self.assertEqual(f.passende_stufe(einheiten), stufe)
                self.assertEqual(f.monatspreis(stufe, einheiten), preis)

    def test_team_fasst_hoechstens_300_einheiten(self):
        self.assertIsNotNone(f.monatspreis('team', 300))
        self.assertIsNone(f.monatspreis('team', 301))

    def test_professional_endet_bei_1000_und_verdraengt_enterprise_nicht(self):
        self.assertIsNone(f.monatspreis('professional', 1001))
        self.assertEqual(f.passende_stufe(1001), 'enterprise')

    def test_start_hat_keine_zusatzpakete(self):
        self.assertIsNone(f.monatspreis('start', 26))

    def test_angefangene_100_zaehlen_als_paket(self):
        self.assertEqual(f.monatspreis('team', 151), Decimal('179'))
        self.assertEqual(f.monatspreis('team', 250), Decimal('179'))
        self.assertEqual(f.monatspreis('team', 251), Decimal('239'))

    def test_deckel_liegt_nie_unter_dem_grundumfang(self):
        for stufe, preis in f.PREISE.items():
            if preis['deckel'] is not None:
                with self.subTest(stufe=stufe):
                    self.assertGreaterEqual(preis['deckel'],
                                            f.GRENZEN[stufe]['einheiten'])

    def test_unbekannte_stufe_meldet_sich_verstaendlich(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            f.monatspreis('premium', 10)


class PreisseiteTests(TestCase):

    def setUp(self):
        _test_organisation(firma='V AG')
        self.client = Client()
        self.client.force_login(_team_user('Inhaber'))

    def _seite(self):
        return self.client.get('/neu/abonnement/').content.decode()

    def test_keine_phantommerkmale(self):
        body = self._seite()
        for verboten in ('API', ' GB', 'KI-Analysen', 'Premium'):
            with self.subTest(verboten=verboten):
                self.assertNotIn(verboten, body)

    def test_preise_und_hinweis_kommen_aus_der_quelle(self):
        body = self._seite()
        for stufe, preis in f.PREISE.items():
            with self.subTest(stufe=stufe):
                self.assertIn(f'CHF {preis["monat"]}', body)
        self.assertIn(f'Einführungspreise, Stand {f.PREISSTAND}', body)

    def test_ohne_einheiten_ist_start_empfohlen(self):
        body = self._seite()
        self.assertIn('Für deinen Bestand: CHF 39/Monat', body)

    def test_zahlen_mit_schweizer_tausendertrennzeichen(self):
        body = self._seite()
        self.assertIn("2'000 Einheiten inklusive", body)
        self.assertIn("bis 1'000", body)

    def test_eigentuemerportal_erst_ab_team(self):
        """Die Merkmalsliste entsteht aus dem Katalog, nicht aus freiem Text."""
        from core.views.fw.profil import _abo_plaene
        plaene = {p['key']: p for p in _abo_plaene(0, False, 'team')}
        portal = f.FUNKTIONEN['eigentuemerportal']
        self.assertNotIn(portal, plaene['start']['features'])
        self.assertIn(portal, plaene['team']['features'])
        self.assertEqual(plaene['team']['alles_aus'], 'Start')
