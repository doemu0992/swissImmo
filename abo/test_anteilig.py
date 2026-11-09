"""Anteilsmässige Verrechnung: Kalendermonate, angebrochene erste Periode, Aufwertung (Zusatzrechnung), Abwertung (Gutschrift)."""
from datetime import date
from decimal import Decimal

from django.test import override_settings

from abo import dienst
from abo.models import AboGutschrift, AboRechnung
from abo.test_abrechnung import FESTGELEGT, Basis, _verwaltet
from core import funktionen as f


@override_settings(**FESTGELEGT)
class AnteilTests(Basis):

    def _abo_mit_rechnung(self, ab, heute, stufe='team'):
        abo = _verwaltet(self.a, stufe=stufe, ab=ab)
        dienst.abrechnen(self.org(), heute=heute, mail=False)
        return abo

    def _rechnungen(self):
        return list(AboRechnung.alle_organisationen.filter(organisation=self.a.organisation).order_by('periode_von', 'pk'))

    def test_erste_periode_reicht_bis_monatsende_und_ist_anteilig(self):
        self._abo_mit_rechnung(date(2026, 12, 15), date(2026, 12, 15))
        r, = self._rechnungen()
        self.assertEqual((r.periode_von, r.periode_bis), (date(2026, 12, 15), date(2026, 12, 31)))
        voll = f.monatspreis('team', r.einheiten)
        erwartet = (voll * Decimal(17) / Decimal(31)).quantize(Decimal('0.01'))
        self.assertEqual(r.netto, erwartet)
        self.assertEqual(sum(Decimal(p['betrag']) for p in r.positionen), r.netto)
        self.assertIn('anteilig 17 von 31 Tagen', r.positionen[0]['text'])

    def test_danach_volle_kalendermonate(self):
        abo = self._abo_mit_rechnung(date(2026, 12, 15), date(2026, 12, 15))
        dienst.abrechnen(self.org(), heute=date(2026, 12, 22), mail=False)    # Vorlauf: Jan. wird gestellt
        erste, zweite = self._rechnungen()
        self.assertEqual((zweite.periode_von, zweite.periode_bis), (date(2027, 1, 1), date(2027, 1, 31)))
        self.assertEqual(zweite.netto, f.monatspreis('team', zweite.einheiten))
        abo.refresh_from_db()
        self.assertEqual(abo.abgerechnet_bis, date(2027, 1, 31))

    def test_beginn_am_ersten_ist_ein_voller_monat(self):
        self._abo_mit_rechnung(date(2026, 12, 1), date(2026, 12, 1))
        r, = self._rechnungen()
        self.assertEqual(r.netto, f.monatspreis('team', r.einheiten))
        self.assertNotIn('anteilig', r.positionen[0]['text'])

    def test_aufwertung_stellt_zusatzrechnung_fuer_die_restlichen_tage(self):
        self._abo_mit_rechnung(date(2026, 12, 1), date(2026, 12, 1))
        org = self.org()
        dienst.plan_wechseln(org, 'professional', False, heute=date(2026, 12, 11))     # 21 von 31 Tagen
        basis, zusatz = self._rechnungen()
        self.assertEqual(zusatz.art, AboRechnung.ART_ZUSATZ)
        diff = f.monatspreis('professional', zusatz.einheiten) - f.monatspreis('team', zusatz.einheiten)
        self.assertEqual(zusatz.netto, (diff * Decimal(21) / Decimal(31)).quantize(Decimal('0.01')))
        self.assertEqual((zusatz.periode_von, zusatz.periode_bis), (date(2026, 12, 11), date(2026, 12, 31)))
        self.assertEqual(basis.art, AboRechnung.ART_ABO)
        self.assertTrue(zusatz.qr_referenz)

    def test_modul_zubuchen_stellt_zusatzrechnung(self):
        abo = self._abo_mit_rechnung(date(2026, 12, 1), date(2026, 12, 1))
        dienst.module_setzen(self.org(), abo, ['signatur'], heute=date(2026, 12, 16))   # 16 von 31 Tagen
        zusatz = self._rechnungen()[-1]
        self.assertEqual(zusatz.art, AboRechnung.ART_ZUSATZ)
        self.assertEqual(zusatz.netto, (Decimal(9) * Decimal(16) / Decimal(31)).quantize(Decimal('0.01')))
        self.assertIn('Modul', zusatz.positionen[0]['text'])

    def test_abwertung_gibt_gutschrift_die_die_naechste_rechnung_mindert(self):
        self._abo_mit_rechnung(date(2026, 12, 1), date(2026, 12, 1), stufe='professional')
        org = self.org()
        dienst.plan_wechseln(org, 'team', False, heute=date(2026, 12, 11))
        self.assertEqual(len(self._rechnungen()), 1)                                    # keine Zusatzrechnung
        g, = AboGutschrift.alle_organisationen.filter(organisation=self.a.organisation)
        einheiten = self._rechnungen()[0].einheiten
        diff = f.monatspreis('professional', einheiten) - f.monatspreis('team', einheiten)
        self.assertEqual(g.betrag, (diff * Decimal(21) / Decimal(31)).quantize(Decimal('0.01')))
        dienst.abrechnen(self.org(), heute=date(2026, 12, 22), mail=False)
        folge = self._rechnungen()[-1]
        self.assertEqual(folge.periode_von, date(2027, 1, 1))
        preis = f.monatspreis('team', folge.einheiten)
        self.assertEqual(folge.netto, max(preis - g.betrag, Decimal('0.00')))   # Guthaben übersteigt den Monat: Rest bleibt
        self.assertEqual(sum(Decimal(p['betrag']) for p in folge.positionen), folge.netto)
        g.refresh_from_db()
        self.assertEqual(g.offen, max(g.betrag - preis, Decimal('0')))

    def test_gutschrift_macht_rechnung_nie_negativ_und_bleibt_als_rest(self):
        self._abo_mit_rechnung(date(2026, 12, 1), date(2026, 12, 1))
        AboGutschrift.alle_organisationen.create(
            organisation=self.a.organisation, datum=date(2026, 12, 5), text='Test', betrag=Decimal('1000'))
        dienst.abrechnen(self.org(), heute=date(2026, 12, 22), mail=False)
        folge = self._rechnungen()[-1]
        self.assertEqual(folge.netto, Decimal('0.00'))
        g = AboGutschrift.alle_organisationen.get(organisation=self.a.organisation)
        self.assertEqual(g.offen, Decimal('1000') - f.monatspreis('team', folge.einheiten))

    def test_ohne_laufende_periode_oder_ohne_aenderung_nichts(self):
        abo = _verwaltet(self.a, ab=date(2027, 3, 1))                                   # noch nichts gestellt
        dienst.plan_wechseln(self.org(), 'professional', False, heute=date(2026, 12, 11))
        dienst.module_setzen(self.org(), abo, ['signatur'], heute=date(2026, 12, 11))
        self.assertEqual(self._rechnungen(), [])
        self.assertFalse(AboGutschrift.alle_organisationen.filter(organisation=self.a.organisation).exists())

    def test_intervallwechsel_wird_nicht_anteilig_verrechnet(self):
        self._abo_mit_rechnung(date(2026, 12, 1), date(2026, 12, 1))
        dienst.plan_wechseln(self.org(), 'team', True, heute=date(2026, 12, 11))
        self.assertEqual(len(self._rechnungen()), 1)

    def test_zusatzrechnung_zaehlt_im_zahlungszustand(self):
        self._abo_mit_rechnung(date(2026, 12, 1), date(2026, 12, 1))
        dienst.plan_wechseln(self.org(), 'professional', False, heute=date(2026, 12, 11))
        zusatz = self._rechnungen()[-1]
        zusatz.faellig_am = date(2026, 12, 12)
        zusatz.save(update_fields=['faellig_am'])
        alt, neu = dienst.zustand_aktualisieren(self.org(), heute=date(2026, 12, 14))
        self.assertEqual(neu, f.ZUSTAND_MAHNUNG)

    def test_jaehrlich_gutschrift_und_zusatz_ueber_die_restlichen_tage(self):
        abo = _verwaltet(self.a, jaehrlich=True, ab=date(2026, 12, 1))
        dienst.abrechnen(self.org(), heute=date(2026, 12, 1), mail=False)
        dienst.module_setzen(self.org(), abo, ['signatur'], heute=date(2027, 6, 1))
        zusatz = self._rechnungen()[-1]
        rest = (date(2027, 11, 30) - date(2027, 6, 1)).days + 1
        jahr = Decimal(365)
        netto_modul = (Decimal(9) * 12 * (1 - f.JAHRESRABATT) * rest / jahr).quantize(Decimal('0.01'))
        self.assertEqual(zusatz.netto, netto_modul)
