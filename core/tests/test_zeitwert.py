"""Zeitwert-Rechner (paritätische Lebensdauertabelle): Formel und Randfälle.

Feste Daten statt `date.today()`: Die Aussagen «6 von 10 Jahren = 40 %» und
«Lebensdauer abgelaufen = 0 CHF» dürfen nicht vom Tag des Testlaufs abhängen.
"""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from core.services import zeitwert as zw
from ._helfer import _basis_objekte


class MonateUndFaktorTests(SimpleTestCase):

    def test_volle_monate(self):
        self.assertEqual(zw.volle_monate(date(2020, 1, 15), date(2026, 1, 15)), 72)
        self.assertEqual(zw.volle_monate(date(2020, 1, 15), date(2026, 1, 14)), 71)
        self.assertEqual(zw.volle_monate(date(2026, 1, 1), date(2020, 1, 1)), 0)

    def test_teppich_zehn_jahre_nach_sechs_jahren_vierzig_prozent(self):
        faktor = zw.restwert_faktor(date(2020, 3, 1), 10, date(2026, 3, 1))
        self.assertEqual(faktor, Decimal('0.400000'))

    def test_brandfleck_teppich_belastet_vierzig_prozent(self):
        faktor = zw.restwert_faktor(date(2020, 3, 1), 10, date(2026, 3, 1))
        e = zw.mieteranteil(Decimal('1000'), faktor, verursacher='mieter')
        self.assertEqual(e.betrag, Decimal('400.00'))
        self.assertEqual(e.grundlage, zw.ZEITWERT)

    def test_faktor_nie_ueber_eins_und_nie_negativ(self):
        # Stichtag vor Einbau → noch neu
        self.assertEqual(zw.restwert_faktor(date(2026, 1, 1), 10, date(2025, 1, 1)), Decimal('1.000000'))
        # weit über der Lebensdauer → 0, nicht negativ
        self.assertEqual(zw.restwert_faktor(date(2000, 1, 1), 10, date(2026, 1, 1)), Decimal('0.000000'))

    def test_none_ist_nicht_null(self):
        self.assertIsNone(zw.restwert_faktor(None, 10, date(2026, 1, 1)))
        self.assertIsNone(zw.restwert_faktor(date(2020, 1, 1), None, date(2026, 1, 1)))

    def test_nur_mieterschaden_wird_belastet(self):
        for wer in ('abnutzung', 'vermieter'):
            e = zw.mieteranteil(Decimal('500'), Decimal('1'), verursacher=wer)
            self.assertEqual(e.betrag, Decimal('0.00'))
            self.assertEqual(e.grundlage, zw.KEIN_MIETERSCHADEN)

    def test_ohne_lebensdauer_voller_betrag_mit_benannter_grundlage(self):
        e = zw.mieteranteil(Decimal('300'), None, verursacher='mieter')
        self.assertEqual(e.betrag, Decimal('300.00'))
        self.assertEqual(e.grundlage, zw.OHNE_LEBENSDAUER)

    def test_rundung_auf_rappen_ohne_float(self):
        # 1/3 Restwert (40 von 120 Monaten) auf 100.00 → 33.33, kein float-Rauschen
        faktor = zw.restwert_faktor(date(2016, 1, 1), 10, date(2022, 1, 1)) # 72 Mt → 0.4
        self.assertEqual(faktor, Decimal('0.400000'))
        f3 = zw.restwert_faktor(date(2018, 1, 1), 12, date(2026, 1, 1))     # 96 Mt → 48/144
        self.assertEqual(zw.mieteranteil(Decimal('100'), f3, verursacher='mieter').betrag,
                         Decimal('33.33'))


class AbgelaufeneLebensdauerTests(TestCase):
    """Edge-Case: Auszug, Bauteil über seiner Lebensdauer."""

    def _mangel(self, einbau, kategorie_jahre, *, kosten='1800', vorsaetzlich=False,
                auszug=date(2026, 6, 30), kategorie='Wände / Anstrich'):
        from portfolio.models import Ausstattung
        from rentals.models import Abnahmeprotokoll, AbnahmeMangel
        _lg, e, _m, v = _basis_objekte()
        el = Ausstattung.objects.create(einheit=e, raum='Wohnen', kategorie=kategorie,
                                        einbau_datum=einbau, lebensdauer_jahre=kategorie_jahre)
        prot = Abnahmeprotokoll.objects.create(vertrag=v, typ='auszug', datum=auszug)
        return AbnahmeMangel(protokoll=prot, raum='Wohnen', beschreibung='Wände vergilbt',
                             verursacher='mieter', ausstattung=el,
                             kostenschaetzung=Decimal(kosten), vorsaetzlich=vorsaetzlich)

    def test_waende_nach_zehn_jahren_kosten_null(self):
        # Lebensdauer Anstrich 8 Jahre, Mietdauer 10 Jahre → 0 CHF
        m = self._mangel(date(2016, 6, 30), 8)
        self.assertEqual(m.berechne_mieteranteil(), Decimal('0.00'))
        self.assertEqual(m.berechne_ergebnis().grundlage, zw.ABGESCHRIEBEN)

    def test_lebensdauer_aus_tabelle_wenn_kein_manueller_wert(self):
        # Ohne manuelle Lebensdauer greift die geseedete Tabelle (Wände / Anstrich = 8 J.)
        from portfolio.models import Lebensdauer
        from ._helfer import _test_organisation
        Lebensdauer.objects.update_or_create(
            kategorie='Wände / Anstrich', organisation=_test_organisation(),
            defaults={'jahre': 8})
        m = self._mangel(date(2016, 6, 30), None)
        self.assertEqual(m.berechne_mieteranteil(), Decimal('0.00'))

    def test_genau_am_ende_der_lebensdauer_null(self):
        m = self._mangel(date(2018, 6, 30), 8)
        self.assertEqual(m.berechne_mieteranteil(), Decimal('0.00'))

    def test_einen_monat_vor_ende_nur_restanteil(self):
        # 95 von 96 Monaten verbraucht → 1/96 von 1800 = 18.75
        m = self._mangel(date(2018, 7, 30), 8, auszug=date(2026, 6, 30))
        self.assertEqual(m.berechne_mieteranteil(), Decimal('18.75'))
        # Einen Tag später eingebaut → der 95. Monat ist noch nicht voll: 2/96 = 37.50
        m = self._mangel(date(2018, 7, 31), 8, auszug=date(2026, 6, 30))
        self.assertEqual(m.berechne_mieteranteil(), Decimal('37.50'))

    def test_absichtliche_beschaedigung_voller_betrag_trotz_abgelaufen(self):
        m = self._mangel(date(2016, 6, 30), 8, vorsaetzlich=True)
        self.assertEqual(m.berechne_mieteranteil(), Decimal('1800.00'))
        self.assertEqual(m.berechne_ergebnis().grundlage, zw.VORSATZ)

    def test_vorsatz_ohne_mieter_als_verursacher_bleibt_null(self):
        m = self._mangel(date(2016, 6, 30), 8, vorsaetzlich=True)
        m.verursacher = 'abnutzung'
        self.assertEqual(m.berechne_mieteranteil(), Decimal('0.00'))

    def test_view_speichert_vorsatz_und_nullbetrag(self):
        from django.test import Client
        from portfolio.models import Ausstattung
        from rentals.models import AbnahmeMangel
        from ._helfer import _team_user
        _lg, e, _m, v = _basis_objekte()
        el = Ausstattung.objects.create(einheit=e, raum='Wohnen', kategorie='Wände / Anstrich',
                                        einbau_datum=date(2010, 1, 1), lebensdauer_jahre=8)
        c = Client(); c.force_login(_team_user())

        def post(beschreibung, vorsatz):
            return c.post(f'/neu/vertraege/{v.id}/abnahme/neu/', {
                'typ': 'auszug', 'datum': '2026-06-30',
                'm_raum': ['Wohnen'], 'm_beschreibung': [beschreibung],
                'm_verursacher': ['mieter'], 'm_kosten': ['1800'],
                'm_ausstattung': [str(el.id)], 'm_neuwert': [''], 'm_vorsatz': [vorsatz]})

        self.assertEqual(post('vergilbt', '').status_code, 302)
        self.assertEqual(post('mutwillig bemalt', '1').status_code, 302)
        self.assertEqual(AbnahmeMangel.objects.get(beschreibung='vergilbt').mieteranteil,
                         Decimal('0.00'))
        absicht = AbnahmeMangel.objects.get(beschreibung='mutwillig bemalt')
        self.assertTrue(absicht.vorsaetzlich)
        self.assertEqual(absicht.mieteranteil, Decimal('1800.00'))


class HinweisOhneLebensdauerTests(TestCase):
    """Mieterschaden ohne Alter/Lebensdauer: voller Betrag, aber sichtbar gemacht."""

    def _post(self, c, v, element_id):
        return c.post(f'/neu/vertraege/{v.id}/abnahme/neu/', {
            'typ': 'auszug', 'datum': '2026-06-30',
            'm_raum': ['Wohnen'], 'm_beschreibung': ['Loch in Wand'],
            'm_verursacher': ['mieter'], 'm_kosten': ['300'],
            'm_ausstattung': [element_id], 'm_neuwert': [''], 'm_vorsatz': ['']},
            follow=True)

    def test_warnung_und_hinweis_ohne_element(self):
        from django.test import Client
        from ._helfer import _team_user
        _lg, _e, _m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = self._post(c, v, '')
        self.assertContains(r, 'ohne Alter oder Lebensdauer')
        self.assertContains(r, 'Alter/Lebensdauer fehlt')

    def test_keine_warnung_wenn_zeitwert_berechnet(self):
        from django.test import Client
        from portfolio.models import Ausstattung
        from ._helfer import _team_user
        _lg, e, _m, v = _basis_objekte()
        el = Ausstattung.objects.create(einheit=e, raum='Wohnen', kategorie='Wände / Anstrich',
                                        einbau_datum=date(2024, 1, 1), lebensdauer_jahre=8)
        c = Client(); c.force_login(_team_user())
        r = self._post(c, v, str(el.id))
        self.assertNotContains(r, 'ohne Alter oder Lebensdauer')
        self.assertNotContains(r, 'Alter/Lebensdauer fehlt')
