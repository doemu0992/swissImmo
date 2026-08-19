"""Tests der Funktionsfreigabe (`core.funktionen`).

Die Naht ist klein, aber sie entscheidet ab Phase 4a, welche Funktion sichtbar
ist. Zwei Fehlerarten sind hier teuer und werden deshalb einzeln geprüft:

1. Ein Schlüssel, den niemand kennt, wird stillschweigend zu «gesperrt».
2. Der Katalog und die Stufen laufen auseinander — eine Stufe verweist auf
   eine Funktion, die es nicht gibt, oder eine Funktion steht in keiner Stufe
   und ist damit unerreichbar.
"""
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from core.funktionen import (
    FUNKTIONEN, GRENZ_ARTEN, GRENZEN, MODULE, STUFEN, STUFEN_REIHENFOLGE,
    UnbekannteFunktion, grenze, hat_funktion, stufe_von,
)


class _Org:
    """Genügt für dieses Modul — `hat_funktion` braucht kein echtes Modell."""


class KatalogTests(TestCase):
    def test_jede_stufe_verweist_nur_auf_bekannte_funktionen(self):
        for stufe, schluessel in STUFEN.items():
            with self.subTest(stufe=stufe):
                unbekannt = schluessel - set(FUNKTIONEN)
                self.assertEqual(
                    unbekannt, set(),
                    f'Stufe {stufe} nennt Funktionen, die nicht im Katalog stehen.')

    def test_jede_funktion_ist_in_mindestens_einer_stufe_erreichbar(self):
        erreichbar = set().union(*STUFEN.values())
        verwaist = set(FUNKTIONEN) - erreichbar
        self.assertEqual(
            verwaist, set(),
            'Diese Funktionen stehen im Katalog, aber in keiner Stufe — '
            'niemand kann sie je nutzen.')

    def test_stufen_bauen_aufeinander_auf(self):
        """Eine höhere Stufe darf nie weniger können als die darunter."""
        for tiefer, hoeher in zip(STUFEN_REIHENFOLGE, STUFEN_REIHENFOLGE[1:]):
            with self.subTest(von=tiefer, nach=hoeher):
                self.assertTrue(
                    STUFEN[tiefer] <= STUFEN[hoeher],
                    f'{hoeher} kann weniger als {tiefer} — die Reihenfolge stimmt nicht.')

    def test_grenzen_wachsen_mit_der_stufe(self):
        for was in ('einheiten', 'nutzer'):
            werte = [GRENZEN[s][was] for s in STUFEN_REIHENFOLGE]
            with self.subTest(was=was):
                self.assertEqual(werte, sorted(werte),
                                 f'Die Grenze {was} wird bei einer höheren Stufe kleiner.')

    def test_funktionen_und_module_ueberschneiden_sich_nicht(self):
        """Sonst entschiede die Reihenfolge in `hat_funktion` über das Ergebnis."""
        self.assertEqual(set(FUNKTIONEN) & set(MODULE), set())

    def test_jeder_schluessel_hat_einen_klartext(self):
        for schluessel, text in {**FUNKTIONEN, **MODULE}.items():
            with self.subTest(schluessel=schluessel):
                self.assertTrue(text and text.strip(),
                                'Ohne Klartext weiss später niemand, was der Schlüssel meint.')


class FreigabeTests(TestCase):
    def setUp(self):
        self.org = _Org()

    def test_unbekannter_schluessel_wirft(self):
        """Der wichtigste Test dieses Moduls.

        Gäbe `hat_funktion` bei einem Tippfehler `False` zurück, wäre die
        Schaltfläche einfach weg und niemand merkte es.
        """
        with self.assertRaises(UnbekannteFunktion):
            hat_funktion(self.org, 'faelle_erweitert')

    def test_ohne_organisation_gesperrt(self):
        self.assertFalse(hat_funktion(None, 'akten'))
        self.assertFalse(hat_funktion(None, 'faelle'))

    def test_ohne_organisation_wirft_trotzdem_bei_tippfehler(self):
        """Die Prüfung des Schlüssels darf nicht erst nach der Stufe kommen."""
        with self.assertRaises(UnbekannteFunktion):
            hat_funktion(None, 'gibtsnicht')

    @override_settings(SWISSIMMO_VORGABE_STUFE='basis')
    def test_basis_hat_keine_faelle(self):
        self.assertTrue(hat_funktion(self.org, 'akten'))
        self.assertFalse(hat_funktion(self.org, 'faelle'))
        self.assertFalse(hat_funktion(self.org, 'nebenkostenlauf'))

    @override_settings(SWISSIMMO_VORGABE_STUFE='aufbau')
    def test_aufbau_hat_faelle_aber_kein_portal(self):
        self.assertTrue(hat_funktion(self.org, 'faelle'))
        self.assertTrue(hat_funktion(self.org, 'fristenwaechter'))
        self.assertFalse(hat_funktion(self.org, 'eigentuemerportal'))

    @override_settings(SWISSIMMO_VORGABE_STUFE='verwaltung')
    def test_verwaltung_hat_portale_aber_keine_rentabilitaet(self):
        self.assertTrue(hat_funktion(self.org, 'eigentuemerportal'))
        self.assertTrue(hat_funktion(self.org, 'vor_ort'))
        self.assertFalse(hat_funktion(self.org, 'mandatsrentabilitaet'))

    @override_settings(SWISSIMMO_VORGABE_STUFE='portfolio')
    def test_portfolio_hat_alles(self):
        for schluessel in FUNKTIONEN:
            with self.subTest(schluessel=schluessel):
                self.assertTrue(hat_funktion(self.org, schluessel))

    def test_module_haengen_nicht_an_der_stufe(self):
        with override_settings(SWISSIMMO_VORGABE_STUFE='basis'):
            self.assertTrue(hat_funktion(self.org, 'signatur'))
        self.assertFalse(hat_funktion(None, 'signatur'))


class GrenzenTests(TestCase):
    def setUp(self):
        self.org = _Org()

    @override_settings(SWISSIMMO_VORGABE_STUFE='verwaltung')
    def test_grenzen_der_aktuellen_stufe(self):
        self.assertEqual(grenze(self.org, 'einheiten'), 250)
        self.assertEqual(grenze(self.org, 'nutzer'), 5)

    def test_unbekannte_grenze_wirft(self):
        with self.assertRaises(UnbekannteFunktion):
            grenze(self.org, 'liegenschaften')

    def test_ohne_organisation_null(self):
        self.assertEqual(grenze(None, 'einheiten'), 0)

    def test_ohne_organisation_wirft_trotzdem_bei_tippfehler(self):
        """Das Gegenstück zum gleichnamigen Test bei `hat_funktion`.

        Der fehlte zuerst, und die Funktion hatte den Fehler prompt: Ohne
        Organisation kam die Stufenprüfung zuerst und lieferte bei einem
        Tippfehler schweigend 0 zurück. 0 ist von einer echten Grenze nicht
        zu unterscheiden — gesperrt wäre alles, ohne Hinweis worauf.
        """
        with self.assertRaises(UnbekannteFunktion):
            grenze(None, 'liegenschaften')

    def test_jede_stufe_kennt_jede_grenzart(self):
        """Sonst wirft `grenze` bei einer Stufe, die eine Art nicht führt."""
        for stufe, werte in GRENZEN.items():
            with self.subTest(stufe=stufe):
                self.assertEqual(set(werte), set(GRENZ_ARTEN))


class NahtTests(TestCase):
    """Was Phase 3 antreffen muss.

    Diese Klasse hält fest, dass die feste Hinterlegung an genau einer Stelle
    sitzt. Wandert sie, schlägt der Test fehl und jemand muss entscheiden statt
    zu reparieren.
    """

    def test_nur_stufe_von_ist_fest_hinterlegt(self):
        import inspect

        from core import funktionen
        quelle = inspect.getsource(funktionen)
        self.assertEqual(
            quelle.count('SWISSIMMO_VORGABE_STUFE'), 1,
            'Die Vorgabestufe wird an mehr als einer Stelle gelesen. '
            'Phase 3 müsste dann mehrere Stellen ersetzen statt einer.')

    @override_settings(SWISSIMMO_VORGABE_STUFE='aufbau')
    def test_stufe_ist_ueber_einstellungen_uebersteuerbar(self):
        self.assertEqual(stufe_von(_Org()), 'aufbau')

    @override_settings(SWISSIMMO_VORGABE_STUFE='premium')
    def test_unbekannte_stufe_meldet_sich_verstaendlich(self):
        """Vorher kam hier ein nacktes `KeyError('premium')` heraus.

        Ab Phase 3 liefert `stufe_von` echte Abodaten. Eine umbenannte,
        abgelaufene oder falsch geschriebene Stufe ist dann ein realistischer
        Fall — und muss sagen, was sie ist, statt tief im Modul als
        Wörterbuchzugriff zu scheitern. `UnbekannteFunktion` erbt von
        `KeyError`; ein blosses `assertRaises(KeyError)` würde beides
        verwechseln, deshalb hier ausdrücklich `ImproperlyConfigured`.
        """
        with self.assertRaises(ImproperlyConfigured) as fehler:
            stufe_von(_Org())
        self.assertIn('premium', str(fehler.exception))
        self.assertIn('basis', str(fehler.exception))

    @override_settings(SWISSIMMO_VORGABE_STUFE='premium')
    def test_unbekannte_stufe_schlaegt_auch_bei_den_aufrufern_durch(self):
        with self.assertRaises(ImproperlyConfigured):
            hat_funktion(_Org(), 'akten')
        with self.assertRaises(ImproperlyConfigured):
            grenze(_Org(), 'einheiten')
