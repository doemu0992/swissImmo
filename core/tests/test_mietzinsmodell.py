"""Regelquelle Index-/Staffelmiete (Art. 269b/269c OR): `core/services/mietzinsmodell.py`.

Jeder Test hat seine Gegenprobe im selben Test: Der gültige Fall bleibt ohne Sperre, die
Abwandlung um einen Tag bzw. einen Franken löst sie aus. Ein Test, der nur die Abwandlung
prüft, bliebe auch grün, wenn die Regel immer anschlägt.
"""
import json
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.template.loader import get_template
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from core.services import mietzinsmodell as mm
from core.services.mietrecht import pruefe_mietzinsmodell, staffel_pruefung
from core.tenancy import organisation_kontext
from core.tests._helfer import _basis_objekte, _team_user
from core.tests._isolation import MandantenFixture


class MandantenBasis(TestCase):
    """Zwei vollständige, getrennte Bestände A und B (wie die Isolationstests)."""

    @classmethod
    def setUpTestData(cls):
        cls.a = MandantenFixture('A', '8000', 'Zürich')
        cls.b = MandantenFixture('B', '3000', 'Bern')


def d(j, m, t):
    return date(j, m, t)


def regeln(befunde, nur_sperren=True):
    return [b.regel for b in (mm.sperren(befunde) if nur_sperren else befunde)]


def index_gueltig(**aenderung):
    """Ein Indexvertrag ohne Beanstandung: 1.3.2026 bis 28.2.2031, Basis Februar 2026 (107.6 Punkte)."""
    basis = dict(modell='index', beginn=d(2026, 3, 1), ende=d(2031, 2, 28), ist_befristet=True,
                 basis_lik_punkte=Decimal('107.6'), basis_lik_stand=d(2026, 2, 1),
                 weitergabe_prozent=Decimal('100'), intervall_monate=12, stufen=[])
    basis.update(aenderung)
    return mm.pruefe(**basis)


def staffel_gueltig(**aenderung):
    """Ein Staffelvertrag ohne Beanstandung: 1.1.2026 bis 31.12.2028, zwei Stufen je 12 Monate."""
    basis = dict(modell='staffel', beginn=d(2026, 1, 1), ende=d(2028, 12, 31), ist_befristet=True,
                 netto=Decimal('1000'), weitergabe_prozent=Decimal('100'), intervall_monate=12,
                 stufen=[{'ab': d(2027, 1, 1), 'erhoehung': '50'}, {'ab': d(2028, 1, 1), 'erhoehung': '50'}])
    basis.update(aenderung)
    return mm.pruefe(**basis)


class DauerTests(SimpleTestCase):

    def test_mindest_ende_ist_beginn_plus_jahre_minus_ein_tag(self):
        self.assertEqual(mm.mindest_ende(d(2026, 1, 1), 5), d(2030, 12, 31))
        self.assertEqual(mm.mindest_ende(d(2026, 1, 1), 3), d(2028, 12, 31))
        self.assertEqual(mm.mindest_ende(d(2026, 7, 15), 5), d(2031, 7, 14))
        # Gegenprobe: nicht Beginn + N Jahre selbst
        self.assertNotEqual(mm.mindest_ende(d(2026, 1, 1), 5), d(2031, 1, 1))

    def test_schalttag_jahrestag_faellt_auf_den_ersten_maerz(self):
        # 29.2.2024 + 5 Jahre: 2029 hat keinen 29. Februar → 1.3.2029, Ende am Vortag
        self.assertEqual(mm.mindest_ende(d(2024, 2, 29), 5), d(2029, 2, 28))
        # Gegenprobe: In einem Schaltjahr bleibt der 29. Februar
        self.assertEqual(mm.mindest_ende(d(2024, 2, 29), 4), d(2028, 2, 28))
        self.assertEqual(mm.mindest_ende(d(2020, 2, 29), 4), d(2024, 2, 28))

    def test_genau_fuenf_jahre_reichen_ein_tag_weniger_nicht(self):
        self.assertTrue(mm.dauer_erfuellt(d(2026, 1, 1), d(2030, 12, 31), True, None, 5))
        self.assertFalse(mm.dauer_erfuellt(d(2026, 1, 1), d(2030, 12, 30), True, None, 5))
        # Das Ende zählt mit: 31.12.2030 ist der letzte Tag, nicht der erste ausserhalb
        self.assertFalse(mm.dauer_erfuellt(d(2026, 1, 1), d(2030, 12, 31), True, None, 6))

    def test_drei_jahre_gleiche_grenze(self):
        self.assertTrue(mm.dauer_erfuellt(d(2026, 1, 1), d(2028, 12, 31), True, None, 3))
        self.assertFalse(mm.dauer_erfuellt(d(2026, 1, 1), d(2028, 12, 30), True, None, 3))

    def test_schaltjahr_im_zeitraum_verschiebt_die_grenze_nicht(self):
        # 1.3.2023 bis 29.2.2028 sind 5 Jahre (2024 und 2028 sind Schaltjahre); 28.2.2028 ist zu kurz
        self.assertTrue(mm.dauer_erfuellt(d(2023, 3, 1), d(2028, 2, 29), True, None, 5))
        self.assertFalse(mm.dauer_erfuellt(d(2023, 3, 1), d(2028, 2, 28), True, None, 5))

    def test_kuendigungsverzicht_ersetzt_die_befristung(self):
        self.assertTrue(mm.dauer_erfuellt(d(2026, 1, 1), None, False, d(2030, 12, 31), 5))
        self.assertFalse(mm.dauer_erfuellt(d(2026, 1, 1), None, False, d(2030, 12, 30), 5))
        self.assertFalse(mm.dauer_erfuellt(d(2026, 1, 1), None, False, None, 5))

    def test_ende_eines_unbefristeten_vertrags_ist_keine_feste_dauer(self):
        # `ende` bei ist_befristet=False stammt aus einer Kündigung
        self.assertIsNone(mm.fest_bis(d(2026, 1, 1), d(2035, 1, 1), False, None))
        self.assertEqual(mm.fest_bis(d(2026, 1, 1), d(2035, 1, 1), True, None), d(2035, 1, 1))
        # Ein Verzicht über das Ende hinaus verlängert einen befristeten Vertrag nicht
        self.assertEqual(mm.fest_bis(d(2026, 1, 1), d(2028, 1, 1), True, d(2040, 1, 1)), d(2028, 1, 1))
        self.assertEqual(mm.fest_bis(d(2026, 1, 1), None, False, d(2031, 1, 1)), d(2031, 1, 1))


class IndexRegelnTests(TestCase):

    def test_gueltiger_vertrag_hat_keine_sperre(self):
        self.assertEqual(regeln(index_gueltig()), [])

    def test_dauer_unter_fuenf_jahren(self):
        self.assertEqual(regeln(index_gueltig(ende=d(2031, 2, 27))), ['index_dauer'])
        # Gegenprobe: genau fünf Jahre
        self.assertEqual(regeln(index_gueltig(ende=d(2031, 2, 28))), [])

    def test_dauer_fix_setzt_das_mindestende(self):
        b = mm.sperren(index_gueltig(ende=d(2029, 1, 1)))[0]
        self.assertEqual(b.artikel, 'Art. 269b OR, Art. 17 Abs. 4 VMWG')
        self.assertEqual(b.fix['feld'], 'ende')
        self.assertEqual(b.fix['wert'], '2031-02-28')
        self.assertEqual(b.feld, 'ende')

    def test_unbefristet_ohne_verzicht_wird_gesperrt_mit_verzicht_nicht(self):
        offen = index_gueltig(ende=None, ist_befristet=False, verzicht_bis=None)
        self.assertEqual(regeln(offen), ['index_dauer'])
        b = mm.sperren(offen)[0]
        self.assertEqual(b.fix['feld'], 'vermieter_kuendigungsverzicht_bis')
        self.assertEqual(b.fix['wert'], '2031-02-28')
        self.assertEqual(regeln(index_gueltig(ende=None, ist_befristet=False, verzicht_bis=d(2031, 2, 28))), [])
        self.assertEqual(regeln(index_gueltig(ende=None, ist_befristet=False, verzicht_bis=d(2031, 2, 27))),
                         ['index_dauer'])

    def test_ende_ohne_befristung_zaehlt_nicht(self):
        self.assertEqual(regeln(index_gueltig(ist_befristet=False, ende=d(2040, 1, 1))), ['index_dauer'])

    def test_basis_punkte_fehlen_oder_sind_null(self):
        for leer in (None, '', 0, Decimal('0')):
            with self.subTest(wert=leer):
                self.assertEqual(regeln(index_gueltig(basis_lik_punkte=leer)), ['index_basis_punkte'])
        # Gegenprobe: ein echter Wert
        self.assertEqual(regeln(index_gueltig(basis_lik_punkte=Decimal('107.6'))), [])

    def test_basis_stand_fehlt_mit_vorschlag_des_vormonats(self):
        b = mm.sperren(index_gueltig(basis_lik_stand=None))[0]
        self.assertEqual(b.regel, 'index_basis_stand')
        self.assertEqual(b.fix['feld'], 'basis_lik_stand')
        self.assertEqual(b.fix['wert'], '2026-02')    # Monat vor dem Mietbeginn (1.3.2026)

    def test_basis_nicht_nach_dem_mietbeginn_monat(self):
        # Gleicher Monat ist erlaubt, der Monat danach nicht
        self.assertEqual(regeln(index_gueltig(basis_lik_stand=d(2026, 3, 1), basis_lik_punkte=Decimal('107.8'))), [])
        b = mm.sperren(index_gueltig(basis_lik_stand=d(2026, 4, 1), basis_lik_punkte=Decimal('108.1')))
        self.assertEqual([x.regel for x in b], ['index_basis_nach_beginn'])
        self.assertEqual(b[0].fix['wert'], '2026-02')

    def test_abweichung_von_der_tabelle_ist_nur_ein_hinweis(self):
        befunde = index_gueltig(basis_lik_punkte=Decimal('107.5'))
        self.assertEqual(regeln(befunde), [])
        hinweis = [b for b in befunde if b.regel == 'index_basis_abweichung']
        self.assertEqual(len(hinweis), 1)
        self.assertEqual(hinweis[0].stufe, 'hinweis')
        self.assertEqual(hinweis[0].fix['wert'], '107.6')
        # Gegenprobe: stimmt der Wert mit der Tabelle, kein Hinweis
        self.assertEqual([b for b in index_gueltig() if b.regel == 'index_basis_abweichung'], [])

    def test_weitergabe_grenzen(self):
        for wert, gesperrt in ((None, True), (0, True), (-5, True), (Decimal('0.1'), False),
                               (80, False), (100, False), (Decimal('100.1'), True), (150, True)):
            with self.subTest(wert=wert):
                erwartet = ['index_weitergabe'] if gesperrt else []
                self.assertEqual(regeln(index_gueltig(weitergabe_prozent=wert)), erwartet)

    def test_weitergabe_ueber_hundert_bietet_hundert_an(self):
        b = mm.sperren(index_gueltig(weitergabe_prozent=120))[0]
        self.assertEqual(b.fix, {'feld': 'index_weitergabe_prozent', 'wert': '100', 'label': b.fix['label']})

    def test_nur_der_lik_ist_ein_index(self):
        self.assertEqual(regeln(index_gueltig(index_art='hev')), ['index_art'])
        self.assertEqual(regeln(index_gueltig(index_art='lik')), [])
        self.assertEqual(regeln(index_gueltig(index_art=None)), [])

    def test_intervall_unter_einem_monat(self):
        self.assertEqual(regeln(index_gueltig(intervall_monate=0)), ['index_intervall'])
        self.assertEqual(regeln(index_gueltig(intervall_monate=1)), [])

    def test_keine_staffelstufen_neben_dem_index(self):
        stufe = [{'ab': d(2027, 3, 1), 'erhoehung': 20}]
        b = mm.sperren(index_gueltig(stufen=stufe))
        self.assertEqual([x.regel for x in b], ['index_staffel_kombination'])
        self.assertIn('BGE 124 III 57', b[0].artikel)
        self.assertEqual(regeln(index_gueltig(stufen=[])), [])

    def test_ankuendigung_ist_ein_hinweis_mit_artikel(self):
        hinweise = [b for b in index_gueltig() if b.regel == 'index_anpassung']
        self.assertEqual(len(hinweise), 1)
        self.assertEqual(hinweise[0].stufe, 'hinweis')
        self.assertIn('Art. 17 Abs. 2 und 3', hinweise[0].artikel)

    def test_sperren_stehen_vor_den_hinweisen(self):
        befunde = index_gueltig(weitergabe_prozent=0)
        stufen = [b.stufe for b in befunde]
        self.assertEqual(stufen, sorted(stufen, key=lambda s: s != 'sperre'))
        self.assertEqual(stufen[0], 'sperre')


class StaffelRegelnTests(TestCase):

    def test_gueltiger_vertrag_hat_keine_sperre(self):
        self.assertEqual(regeln(staffel_gueltig()), [])

    def test_dauer_unter_drei_jahren(self):
        self.assertEqual(regeln(staffel_gueltig(ende=d(2028, 12, 30), stufen=[
            {'ab': d(2027, 1, 1), 'erhoehung': 50}])), ['staffel_dauer'])
        self.assertEqual(regeln(staffel_gueltig(ende=d(2028, 12, 31), stufen=[
            {'ab': d(2027, 1, 1), 'erhoehung': 50}])), [])

    def test_dauer_ueber_kuendigungsverzicht_und_analog_gekennzeichnet(self):
        offen = staffel_gueltig(ende=None, ist_befristet=False, verzicht_bis=None)
        self.assertIn('staffel_dauer', regeln(offen))
        b = [x for x in offen if x.regel == 'staffel_dauer'][0]
        self.assertIn('analog', b.artikel)
        self.assertEqual(b.fix['feld'], 'vermieter_kuendigungsverzicht_bis')
        self.assertEqual(b.fix['wert'], '2028-12-31')
        self.assertNotIn('staffel_dauer', regeln(staffel_gueltig(ende=None, ist_befristet=False,
                                                                 verzicht_bis=d(2028, 12, 31))))

    def test_mindestens_eine_stufe(self):
        self.assertEqual(regeln(staffel_gueltig(stufen=[])), ['staffel_stufen_fehlen'])
        # Unbekannte Stufen (None) sind etwas anderes als keine Stufen
        self.assertEqual(regeln(staffel_gueltig(stufen=None)), [])
        # Vollständig leere Eingabezeilen zählen nicht als Stufe
        self.assertEqual(regeln(staffel_gueltig(stufen=[{}, {'ab': '', 'erhoehung': ''}])),
                         ['staffel_stufen_fehlen'])

    def test_erhoehung_in_chf_muss_positiv_sein(self):
        for wert in (0, '0.00', -10, None):
            with self.subTest(erhoehung=wert):
                befunde = mm.sperren(staffel_gueltig(stufen=[{'ab': d(2027, 1, 1), 'erhoehung': wert}]))
                self.assertEqual([b.regel for b in befunde], ['staffel_erhoehung'])
                self.assertEqual(befunde[0].zeile, 0)
        # Gegenprobe: ein Rappen genügt
        self.assertEqual(regeln(staffel_gueltig(stufen=[{'ab': d(2027, 1, 1), 'erhoehung': '0.01'}])), [])

    def test_befund_nennt_die_zeile_der_stufe(self):
        befunde = mm.sperren(staffel_gueltig(stufen=[
            {'ab': d(2027, 1, 1), 'erhoehung': 50}, {'ab': d(2028, 1, 1), 'erhoehung': 0}]))
        self.assertEqual([(b.regel, b.zeile) for b in befunde], [('staffel_erhoehung', 1)])

    def test_prozent_ist_nicht_zulaessig(self):
        befunde = mm.sperren(staffel_gueltig(stufen=[
            {'ab': d(2027, 1, 1), 'prozent': '3'}, {'ab': d(2028, 1, 1), 'erhoehung': 50}]))
        self.assertEqual([(b.regel, b.zeile) for b in befunde], [('staffel_prozent', 0)])
        self.assertEqual(befunde[0].artikel, 'Art. 269c lit. c OR')
        # Prozent 0 oder leer ist keine Prozent-Eingabe
        self.assertEqual(regeln(staffel_gueltig(stufen=[
            {'ab': d(2027, 1, 1), 'erhoehung': 50, 'prozent': '0'}])), [])

    def test_datum_der_stufe_fehlt(self):
        self.assertEqual([b.regel for b in mm.sperren(staffel_gueltig(stufen=[{'erhoehung': 50}]))],
                         ['staffel_datum'])

    def test_abstand_zum_mietbeginn_genau_zwoelf_monate(self):
        gut = [{'ab': d(2027, 1, 1), 'erhoehung': 50}]
        zu_frueh = [{'ab': d(2026, 12, 31), 'erhoehung': 50}]
        self.assertEqual(regeln(staffel_gueltig(stufen=gut)), [])
        befunde = mm.sperren(staffel_gueltig(stufen=zu_frueh))
        self.assertEqual([b.regel for b in befunde], ['staffel_jahresabstand'])
        self.assertEqual(befunde[0].fix['wert'], '2027-01-01')
        self.assertEqual(befunde[0].fix['zeile'], 0)
        self.assertEqual(befunde[0].artikel, 'Art. 269c lit. b OR')

    def test_abstand_zwischen_zwei_stufen_genau_zwoelf_monate(self):
        gut = [{'ab': d(2027, 1, 1), 'erhoehung': 50}, {'ab': d(2028, 1, 1), 'erhoehung': 50}]
        zu_frueh = [{'ab': d(2027, 1, 1), 'erhoehung': 50}, {'ab': d(2027, 12, 31), 'erhoehung': 50}]
        self.assertEqual(regeln(staffel_gueltig(stufen=gut)), [])
        befunde = mm.sperren(staffel_gueltig(stufen=zu_frueh))
        self.assertEqual([(b.regel, b.zeile) for b in befunde], [('staffel_jahresabstand', 1)])

    def test_zwei_stufen_am_selben_tag(self):
        befunde = mm.sperren(staffel_gueltig(stufen=[
            {'ab': d(2027, 1, 1), 'erhoehung': 50}, {'ab': d(2027, 1, 1), 'erhoehung': 20}]))
        self.assertEqual([b.regel for b in befunde], ['staffel_jahresabstand'])

    def test_abstand_gilt_unabhaengig_von_der_eingabereihenfolge(self):
        befunde = mm.sperren(staffel_gueltig(stufen=[
            {'ab': d(2028, 1, 1), 'erhoehung': 50}, {'ab': d(2027, 12, 1), 'erhoehung': 50}]))
        self.assertEqual([(b.regel, b.zeile) for b in befunde], [('staffel_jahresabstand', 0)])

    def test_abstand_bei_schalttag_als_beginn(self):
        # Beginn 29.2.2024: der Jahrestag 2025 ist der 1. März
        vorher = staffel_gueltig(beginn=d(2024, 2, 29), ende=d(2027, 2, 28), stufen=[
            {'ab': d(2025, 2, 28), 'erhoehung': 50}])
        self.assertEqual(regeln(vorher), ['staffel_jahresabstand'])
        nachher = staffel_gueltig(beginn=d(2024, 2, 29), ende=d(2027, 2, 28), stufen=[
            {'ab': d(2025, 3, 1), 'erhoehung': 50}])
        self.assertEqual(regeln(nachher), [])

    def test_keine_stufe_nach_dem_ende_der_festen_dauer(self):
        ok = [{'ab': d(2027, 1, 1), 'erhoehung': 50}, {'ab': d(2028, 12, 31), 'erhoehung': 50}]
        nach = [{'ab': d(2027, 1, 1), 'erhoehung': 50}, {'ab': d(2029, 1, 1), 'erhoehung': 50}]
        self.assertEqual(regeln(staffel_gueltig(stufen=ok)), [])
        befunde = mm.sperren(staffel_gueltig(stufen=nach))
        self.assertEqual([(b.regel, b.zeile) for b in befunde], [('staffel_nach_ende', 1)])

    def test_stufe_nach_dem_verzichtsende(self):
        nach = staffel_gueltig(ende=None, ist_befristet=False, verzicht_bis=d(2028, 12, 31), stufen=[
            {'ab': d(2027, 1, 1), 'erhoehung': 50}, {'ab': d(2029, 6, 1), 'erhoehung': 50}])
        self.assertEqual([b.regel for b in mm.sperren(nach)], ['staffel_nach_ende'])

    def test_keine_indexfelder_bei_der_staffel(self):
        self.assertEqual(regeln(staffel_gueltig(weitergabe_prozent=Decimal('80'))), ['staffel_index_felder'])
        b = mm.sperren(staffel_gueltig(intervall_monate=6))[0]
        self.assertEqual((b.regel, b.fix['feld'], b.fix['wert']), ('staffel_index_felder', 'index_intervall_monate', '12'))
        self.assertEqual(regeln(staffel_gueltig(weitergabe_prozent=None, intervall_monate=None)), [])

    def test_mitteilung_und_zeitplan_sind_hinweise(self):
        befunde = staffel_gueltig(hat_zeitplan=True)
        hinweise = {b.regel: b for b in befunde if b.stufe == 'hinweis'}
        self.assertEqual(set(hinweise), {'staffel_mitteilung', 'staffel_zeitplan'})
        self.assertEqual(hinweise['staffel_mitteilung'].artikel, 'Art. 269d Abs. 5 OR, Art. 19a VMWG')
        self.assertNotIn('staffel_zeitplan', [b.regel for b in staffel_gueltig()])


class FestUndRandfaelleTests(TestCase):

    def test_fest_ohne_stufen_ist_in_ordnung_und_braucht_keine_indexfelder(self):
        self.assertEqual(mm.pruefe(modell='fest', beginn=d(2026, 1, 1), stufen=[]), [])
        self.assertEqual(mm.pruefe(modell='fest', beginn=d(2026, 1, 1), weitergabe_prozent=None,
                                   basis_lik_punkte=None, stufen=None), [])

    def test_fest_mit_staffelstufen_wird_gesperrt(self):
        befunde = mm.pruefe(modell='fest', beginn=d(2026, 1, 1),
                            stufen=[{'ab': d(2027, 1, 1), 'erhoehung': 50}])
        self.assertEqual(regeln(befunde), ['fest_staffelstufen'])

    def test_ohne_beginn_oder_unbekanntes_modell_nichts_zu_beurteilen(self):
        self.assertEqual(mm.pruefe(modell='index', beginn=None), [])
        self.assertEqual(mm.pruefe(modell='gibtsnicht', beginn=d(2026, 1, 1)), [])

    def test_ist_befristet_none_leitet_aus_dem_ende_ab(self):
        self.assertEqual(regeln(mm.pruefe(modell='staffel', beginn=d(2026, 1, 1), ende=d(2028, 12, 31),
                                          stufen=[{'ab': d(2027, 1, 1), 'erhoehung': 5}])), [])
        self.assertEqual(regeln(mm.pruefe(modell='staffel', beginn=d(2026, 1, 1), ende=None,
                                          stufen=[{'ab': d(2027, 1, 1), 'erhoehung': 5}])), ['staffel_dauer'])

    def test_befund_ist_serialisierbar(self):
        b = mm.sperren(index_gueltig(weitergabe_prozent=0))[0]
        json.dumps(b.als_dict())
        self.assertEqual(set(b.als_dict()), {'regel', 'stufe', 'text', 'artikel', 'feld', 'fix', 'zeile'})
        self.assertIn(b.artikel, b.volltext)
        self.assertNotIn(b.artikel, b.text)


class StufenBerechnenTests(SimpleTestCase):

    def test_stufen_bauen_aufeinander_auf_und_sind_exakt(self):
        stufen = [{'ab': d(2028, 1, 1), 'erhoehung': '30.58'}, {'ab': d(2027, 1, 1), 'erhoehung': '50.13'}]
        ergebnis = mm.stufen_berechnen(Decimal('1000.00'), stufen)
        # Gegenprobe zur Rundung: weder 1050.15 noch 1080.70 (Fünfrappenrundung)
        self.assertEqual(ergebnis, [
            (d(2027, 1, 1), Decimal('50.13'), Decimal('1050.13')),
            (d(2028, 1, 1), Decimal('30.58'), Decimal('1080.71'))])

    def test_zeilen_ohne_datum_oder_erhoehung_entfallen(self):
        stufen = [{'ab': d(2027, 1, 1), 'erhoehung': 50}, {'ab': None, 'erhoehung': 5}, {'ab': d(2028, 1, 1)}]
        self.assertEqual(len(mm.stufen_berechnen(1000, stufen)), 1)

    def test_unbekanntes_startnetto_gibt_kein_neues_netto(self):
        ergebnis = mm.stufen_berechnen(None, [{'ab': d(2027, 1, 1), 'erhoehung': 50}])
        self.assertEqual(ergebnis, [(d(2027, 1, 1), Decimal('50'), None)])

    def test_objekte_mit_ab_datum_werden_gelesen(self):
        class S:
            ab_datum = d(2027, 1, 1)
            erhoehung_chf = Decimal('25')
        self.assertEqual(mm.stufen_berechnen(100, [S()]), [(d(2027, 1, 1), Decimal('25'), Decimal('125'))])


class LikVorschlagTests(SimpleTestCase):

    def test_stand_ist_der_monat_vor_dem_mietbeginn(self):
        self.assertEqual(mm.basis_lik_vorschlag(d(2026, 3, 15)), (d(2026, 2, 1), Decimal('107.6')))
        self.assertEqual(mm.basis_lik_vorschlag(d(2022, 1, 1)), (d(2021, 12, 1), Decimal('101.5')))
        # Gegenprobe: nicht der aktuelle Stand der Tabelle
        self.assertNotEqual(mm.basis_lik_vorschlag(d(2022, 1, 1))[1], Decimal('108.3'))

    def test_noch_nicht_veroeffentlichter_monat_nimmt_den_neuesten_davor(self):
        stand, punkte = mm.basis_lik_vorschlag(d(2027, 5, 1))
        self.assertEqual((stand, punkte), (d(2026, 9, 1), Decimal('108.5')))   # seit MIET-14: Tabelle bis September 2026

    def test_vor_der_tabelle_kein_vorschlag(self):
        self.assertEqual(mm.basis_lik_vorschlag(d(2020, 12, 1)), (None, None))
        self.assertEqual(mm.basis_lik_vorschlag(d(2020, 1, 1)), (None, None))
        self.assertEqual(mm.basis_lik_vorschlag(None), (None, None))
        self.assertEqual(mm.basis_lik_vorschlag(d(2021, 1, 1)), (d(2020, 12, 1), Decimal('100.0')))


class AltaufruferTests(SimpleTestCase):
    """`pruefe_mietzinsmodell` und `staffel_pruefung` behalten ihre Signatur und delegieren."""

    def test_genau_fuenf_jahre_werden_nicht_mehr_als_59_monate_abgelehnt(self):
        # Der Fehler: _monate_zwischen ignorierte den Tag, 1.1.2026 bis 31.12.2030 = «59 Monate»
        self.assertEqual(pruefe_mietzinsmodell('index', d(2026, 1, 1), d(2030, 12, 31)), [])
        hinweise = pruefe_mietzinsmodell('index', d(2026, 1, 1), d(2030, 12, 30))
        self.assertEqual(len(hinweise), 1)
        self.assertIn('Art. 269b OR', hinweise[0])

    def test_staffel_dauer_mit_tagesgenauigkeit(self):
        self.assertEqual(pruefe_mietzinsmodell('staffel', d(2026, 1, 1), d(2028, 12, 31)), [])
        self.assertEqual(len(pruefe_mietzinsmodell('staffel', d(2026, 1, 1), d(2028, 12, 30))), 1)

    def test_ohne_ende_wird_gewarnt_mit_verzicht_nicht(self):
        self.assertEqual(len(pruefe_mietzinsmodell('index', d(2026, 1, 1), None)), 1)
        self.assertEqual(len(pruefe_mietzinsmodell('staffel', d(2026, 1, 1), None)), 1)
        self.assertEqual(pruefe_mietzinsmodell('index', d(2026, 1, 1), None, ist_befristet=False,
                                               verzicht_bis=d(2030, 12, 31)), [])

    def test_fest_und_leerer_beginn_ohne_hinweis(self):
        self.assertEqual(pruefe_mietzinsmodell('fest', d(2026, 1, 1), None), [])
        self.assertEqual(pruefe_mietzinsmodell('index', None, None), [])

    def test_staffel_pruefung_zaehlt_tage_nicht_monatsnummern(self):
        class S:
            def __init__(self, dt):
                self.ab_datum = dt
        # 31.1.2025 bis 1.1.2026: elf Monate und ein Tag; die Monatsnummern ergäben «12»
        self.assertEqual(len(staffel_pruefung([S(d(2025, 1, 31)), S(d(2026, 1, 1))])), 1)
        self.assertEqual(staffel_pruefung([S(d(2025, 1, 1)), S(d(2026, 1, 1)), S(d(2027, 1, 1))]), [])
        self.assertEqual(len(staffel_pruefung([S(d(2025, 1, 1)), S(d(2025, 12, 31))])), 1)
        self.assertEqual(staffel_pruefung([]), [])


def _vertrag(modell='fest', **felder):
    """Ein gespeicherter Vertrag in der Test-Organisation."""
    from rentals.models import Mietvertrag
    lg, e, m, v = _basis_objekte()
    basis = dict(mieter=m, einheit=e, beginn=d(2026, 3, 1), netto_mietzins=Decimal('1000'),
                 nebenkosten=Decimal('0'), status='entwurf', mietzins_modell=modell,
                 ist_befristet=True, ende=d(2031, 2, 28), basis_lik_punkte=Decimal('107.6'),
                 basis_lik_stand=d(2026, 2, 1))
    basis.update(felder)
    return Mietvertrag.objects.create(**basis)


class StaffelstufeModellTests(TestCase):

    def test_netto_folgt_aus_vorstufe_und_erhoehung(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel', ende=d(2029, 2, 28))
        s1 = Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), erhoehung_chf=Decimal('50'),
                                         netto_mietzins=Decimal('1'))
        s2 = Staffelstufe.objects.create(vertrag=v, ab_datum=d(2028, 3, 1), erhoehung_chf=Decimal('30.50'),
                                         netto_mietzins=Decimal('1'))
        s1.refresh_from_db(), s2.refresh_from_db()
        self.assertEqual(s1.netto_mietzins, Decimal('1050.00'))
        self.assertEqual(s2.netto_mietzins, Decimal('1080.50'))

    def test_netto_darf_beim_anlegen_ganz_fehlen_wenn_die_erhoehung_gesetzt_ist(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel', ende=d(2029, 2, 28))
        s = Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), erhoehung_chf=Decimal('50'))
        self.assertEqual(s.netto_mietzins, Decimal('1050'))
        s.refresh_from_db()
        self.assertEqual(s.netto_mietzins, Decimal('1050.00'))

    def test_einschieben_zieht_die_folgenden_stufen_nach(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel', ende=d(2029, 2, 28))
        spaet = Staffelstufe.objects.create(vertrag=v, ab_datum=d(2028, 3, 1), erhoehung_chf=Decimal('30'),
                                            netto_mietzins=Decimal('0'))
        spaet.refresh_from_db()
        self.assertEqual(spaet.netto_mietzins, Decimal('1030.00'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), erhoehung_chf=Decimal('50'),
                                    netto_mietzins=Decimal('0'))
        spaet.refresh_from_db()
        self.assertEqual(spaet.netto_mietzins, Decimal('1080.00'))      # 1000 + 50 + 30

    def test_loeschen_zieht_die_folgenden_stufen_nach(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel', ende=d(2029, 2, 28))
        erste = Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), erhoehung_chf=Decimal('50'),
                                            netto_mietzins=Decimal('0'))
        zweite = Staffelstufe.objects.create(vertrag=v, ab_datum=d(2028, 3, 1), erhoehung_chf=Decimal('30'),
                                             netto_mietzins=Decimal('0'))
        erste.delete()
        zweite.refresh_from_db()
        self.assertEqual(zweite.netto_mietzins, Decimal('1030.00'))

    def test_ohne_erhoehung_bleibt_der_betrag_stehen_altweg(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel')
        s = Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), netto_mietzins=Decimal('1234.50'))
        s.refresh_from_db()
        self.assertEqual(s.netto_mietzins, Decimal('1234.50'))
        self.assertIsNone(s.erhoehung_chf)
        # Gegenprobe: mit Erhöhung wird der Betrag überschrieben
        s.erhoehung_chf = Decimal('10')
        s.save()
        s.refresh_from_db()
        self.assertEqual(s.netto_mietzins, Decimal('1010.00'))

    def test_effektiver_netto_folgt_den_abgeleiteten_stufen(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel')
        Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), erhoehung_chf=Decimal('75'),
                                    netto_mietzins=Decimal('0'), mitteilung_versandt_am=d(2027, 1, 15))
        # MIET-09: Die Stufe wirkt mit belegter, rechtzeitiger Mitteilung (Art. 269d Abs. 5 OR).
        self.assertEqual(v.effektiver_netto_mietzins(d(2027, 6, 1)), Decimal('1075.00'))
        self.assertEqual(v.effektiver_netto_mietzins(d(2027, 2, 1)), Decimal('1000'))

    def test_datenbank_lehnt_erhoehung_null_und_negativ_ab_aber_nicht_leer(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel')
        for wert in (Decimal('0'), Decimal('-1')):
            with self.subTest(erhoehung=wert), self.assertRaises(IntegrityError), transaction.atomic():
                Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), erhoehung_chf=wert,
                                            netto_mietzins=Decimal('1000'))
        # Gegenprobe: NULL (Altstufen) und ein positiver Betrag gehen durch
        Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), netto_mietzins=Decimal('1000'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=d(2028, 3, 1), erhoehung_chf=Decimal('0.01'),
                                    netto_mietzins=Decimal('1000'))
        self.assertEqual(Staffelstufe.objects.filter(vertrag=v).count(), 2)

    def test_constraint_greift_auch_am_update_vorbei_an_save(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel')
        s = Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), erhoehung_chf=Decimal('5'),
                                        netto_mietzins=Decimal('0'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Staffelstufe.objects.filter(pk=s.pk).update(erhoehung_chf=Decimal('0'))


class VertragCleanTests(TestCase):

    def test_neuer_indexvertrag_mit_zu_kurzer_dauer_wird_abgelehnt(self):
        from rentals.models import Mietvertrag
        lg, e, m, _v = _basis_objekte()
        neu = Mietvertrag(mieter=m, einheit=e, beginn=d(2026, 3, 1), ende=d(2029, 2, 28), ist_befristet=True,
                          netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'), mietzins_modell='index',
                          basis_lik_punkte=Decimal('107.6'), basis_lik_stand=d(2026, 2, 1))
        with self.assertRaises(ValidationError) as ctx:
            neu.clean()
        self.assertIn('Art. 269b OR', ' '.join(ctx.exception.messages))
        self.assertEqual(ctx.exception.error_list[0].code, 'index_dauer')
        # Gegenprobe: fünf Jahre
        neu.ende = d(2031, 2, 28)
        neu.clean()

    def test_fester_vertrag_wird_nie_beanstandet(self):
        v = _vertrag('fest', ist_befristet=False, ende=None)
        self.assertIsNone(v.clean())     # `clean` wirft ValidationError, wenn es etwas beanstandet

    def test_altvertrag_wird_nicht_blockiert_solange_die_modellfelder_gleich_bleiben(self):
        v = _vertrag('index', ist_befristet=False, ende=None)    # Altverstoss: keine feste Dauer
        v.besondere_vereinbarungen = 'Nur eine Notiz geändert'
        v.clean()                                                # unverändert → kein Fehler
        v.index_weitergabe_prozent = Decimal('90')               # Modellfeld berührt → volle Prüfung
        with self.assertRaises(ValidationError):
            v.clean()

    def test_save_bleibt_unveraendert_und_bricht_keine_altdaten(self):
        v = _vertrag('index', ist_befristet=False, ende=None)
        v.save()
        v.refresh_from_db()
        self.assertEqual(v.mietzins_modell, 'index')

    def test_gespeicherte_stufen_werden_mitgeprueft(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel', ende=d(2029, 2, 28))
        Staffelstufe.objects.create(vertrag=v, ab_datum=d(2026, 6, 1), erhoehung_chf=Decimal('10'),
                                    netto_mietzins=Decimal('0'))
        v.ende = d(2029, 3, 31)                                  # Modellfeld geändert → volle Prüfung
        with self.assertRaises(ValidationError) as ctx:
            v.clean()
        self.assertEqual({e.code for e in ctx.exception.error_list}, {'staffel_jahresabstand'})
        v.ende = d(2029, 2, 27)                                  # zusätzlich einen Tag unter drei Jahren
        with self.assertRaises(ValidationError) as ctx:
            v.clean()
        self.assertEqual({e.code for e in ctx.exception.error_list}, {'staffel_jahresabstand', 'staffel_dauer'})
        # Gegenprobe: ohne zu frühe Stufe ist derselbe Vertrag in Ordnung
        Staffelstufe.objects.filter(vertrag=v).update(ab_datum=d(2027, 3, 1))
        v.ende = d(2029, 3, 31)
        v.clean()


class BearbeitenFormularTests(TestCase):

    def _form(self, vertrag, **daten):
        from rentals.forms import VertragBearbeitenForm
        post = {'ende': daten.pop('ende', ''), 'kuendigungsfrist': '3', 'anzahl_personen': '1', **daten}
        return VertragBearbeitenForm(post, entwurf=False, beginn=vertrag.beginn, vertrag=vertrag)

    def test_ende_unter_fuenf_jahren_beim_aktiven_indexvertrag_wird_abgelehnt(self):
        v = _vertrag('index', status='aktiv')
        zu_kurz = self._form(v, ende='2031-02-27')
        self.assertFalse(zu_kurz.is_valid())
        self.assertIn('Art. 269b OR', ' '.join(zu_kurz.non_field_errors()))
        # Gegenprobe: genau fünf Jahre
        self.assertTrue(self._form(v, ende='2031-02-28').is_valid())

    def test_altvertrag_mit_gleichen_modellfeldern_wird_nicht_blockiert(self):
        v = _vertrag('index', status='aktiv', ist_befristet=False, ende=None)    # Altverstoss
        self.assertTrue(self._form(v, ende='').is_valid())
        # Gegenprobe: wer das Ende anfasst und weiter zu kurz bleibt, wird gestoppt
        v2 = _vertrag('index', status='aktiv', ist_befristet=False, ende=None)
        self.assertFalse(self._form(v2, ende='2028-01-01').is_valid())

    def test_ohne_vertrag_verhaelt_sich_das_formular_wie_zuvor(self):
        from rentals.forms import VertragBearbeitenForm
        f = VertragBearbeitenForm({'ende': '2027-01-01', 'kuendigungsfrist': '3', 'anzahl_personen': '1'},
                                  entwurf=False, beginn=d(2026, 3, 1))
        self.assertTrue(f.is_valid())

    def test_kuendigungsverzicht_aus_dem_formular_wird_gewertet(self):
        v = _vertrag('index', status='aktiv', ist_befristet=False, ende=None,
                     vermieter_kuendigungsverzicht_bis=d(2031, 2, 28))
        gut = self._form(v, ende='', vermieter_kuendigungsverzicht_bis='2031-02-28', index_weitergabe_prozent='90')
        self.assertTrue(gut.is_valid(), gut.errors)
        kurz = self._form(v, ende='', vermieter_kuendigungsverzicht_bis='2030-12-31', index_weitergabe_prozent='90')
        self.assertFalse(kurz.is_valid())


class StaffelAddTests(TestCase):
    """`fw_staffel_add` (Objektseite): die Erhöhung folgt aus dem Netto, die Regeln gelten hart."""

    def _vertrag_gewerbe(self, **felder):
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        lg, _e, m, _v = _basis_objekte()
        e = Einheit.objects.create(liegenschaft=lg, bezeichnung='Büro 1', typ='gew',
                                   nettomiete_aktuell=Decimal('2000'))
        basis = dict(mieter=m, einheit=e, beginn=d(2025, 1, 1), netto_mietzins=Decimal('2000'),
                     nebenkosten=Decimal('0'), status='aktiv', ist_befristet=True, ende=d(2027, 12, 31))
        basis.update(felder)
        return Mietvertrag.objects.create(**basis)

    def setUp(self):
        self.client = Client()
        self.client.force_login(_team_user())

    def _post(self, v, ab, netto):
        c = self.client
        return c.post('/neu/staffel/', {'vertrag_id': v.id, 'ab_datum': ab, 'netto_mietzins': netto})

    def test_gueltige_stufe_wird_mit_erhoehung_gespeichert(self):
        v = self._vertrag_gewerbe()
        self._post(v, '2026-01-01', '2100')
        v.refresh_from_db()
        self.assertEqual(v.mietzins_modell, 'staffel')
        s = v.staffelstufen.get()
        self.assertEqual((s.erhoehung_chf, s.netto_mietzins), (Decimal('100.00'), Decimal('2100.00')))

    def test_unbefristeter_vertrag_ohne_verzicht_wird_nicht_zum_staffelvertrag(self):
        v = self._vertrag_gewerbe(ist_befristet=False, ende=None)
        self._post(v, '2026-01-01', '2100')
        v.refresh_from_db()
        self.assertEqual(v.mietzins_modell, 'fest')
        self.assertEqual(v.staffelstufen.count(), 0)
        # Gegenprobe: mit Kündigungsverzicht über drei Jahre geht es
        v2 = self._vertrag_gewerbe(ist_befristet=False, ende=None, vermieter_kuendigungsverzicht_bis=d(2027, 12, 31))
        self._post(v2, '2026-01-01', '2100')
        v2.refresh_from_db()
        self.assertEqual(v2.mietzins_modell, 'staffel')

    def test_stufe_ohne_erhoehung_wird_abgelehnt(self):
        v = self._vertrag_gewerbe()
        self._post(v, '2026-01-01', '2000')            # gleicher Betrag = Erhöhung 0
        self._post(v, '2026-01-01', '1900')            # niedriger = negative Erhöhung
        self.assertEqual(v.staffelstufen.count(), 0)

    def test_stufe_unter_zwoelf_monaten_wird_abgelehnt(self):
        v = self._vertrag_gewerbe()
        self._post(v, '2025-12-31', '2100')
        self.assertEqual(v.staffelstufen.count(), 0)
        self._post(v, '2026-01-01', '2100')
        self.assertEqual(v.staffelstufen.count(), 1)

    def test_bestehender_staffelvertrag_wird_nur_wegen_neuer_verstoesse_blockiert(self):
        from rentals.models import Staffelstufe
        # Altvertrag: Staffel ohne feste Dauer (Altverstoss) — eine saubere weitere Stufe darf dazu
        v = self._vertrag_gewerbe(mietzins_modell='staffel', ist_befristet=False, ende=None)
        Staffelstufe.objects.create(vertrag=v, ab_datum=d(2026, 1, 1), erhoehung_chf=Decimal('100'),
                                    netto_mietzins=Decimal('0'))
        self._post(v, '2027-01-01', '2200')
        self.assertEqual(v.staffelstufen.count(), 2)
        # eine zu frühe Stufe dagegen nicht
        self._post(v, '2027-06-01', '2300')
        self.assertEqual(v.staffelstufen.count(), 2)


class EndpunktTests(MandantenBasis):
    URL = '/neu/vertraege/mietzinsmodell/pruefen/'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from django.contrib.auth import get_user_model
        from crm.models import Mitgliedschaft
        cls.rollen = {}
        for rolle in ('Inhaber', 'Verwalter', 'Sachbearbeiter', 'Lesezugriff', 'Hauswart'):
            u = get_user_model().objects.create_user(username=f'mm_{rolle}', password='x')
            Mitgliedschaft.objects.create(benutzer=u, organisation=cls.a.organisation, rolle=rolle)
            cls.rollen[rolle] = u
        cls.mieter_user = get_user_model().objects.create_user(username='mm_mieter', password='x')

    def _get(self, user=None, **params):
        c = Client()
        if user is not None:
            c.force_login(user)
        return c.get(self.URL, params)

    def test_url_ist_benannt(self):
        self.assertEqual(reverse('fw_mietzinsmodell_pruefen'), self.URL)

    def test_team_rollen_duerfen(self):
        for rolle in ('Inhaber', 'Verwalter', 'Sachbearbeiter', 'Lesezugriff'):
            with self.subTest(rolle=rolle):
                self.assertEqual(self._get(self.rollen[rolle], modell='fest').status_code, 200)

    def test_hauswart_mieter_und_anonym_nicht(self):
        self.assertEqual(self._get(self.rollen['Hauswart'], modell='fest').status_code, 403)
        self.assertEqual(self._get(self.mieter_user, modell='fest').status_code, 403)
        antwort = self._get(None, modell='fest')
        self.assertEqual(antwort.status_code, 302)
        self.assertIn('/login/', antwort['Location'])

    def test_nur_get(self):
        c = Client()
        c.force_login(self.rollen['Inhaber'])
        self.assertEqual(c.post(self.URL, {'modell': 'fest'}).status_code, 405)

    def test_antwortformat(self):
        j = self._get(self.rollen['Inhaber'], modell='staffel', beginn='2026-01-01', ende='2028-12-31',
                      ist_befristet='1', netto='1000',
                      staffel_ab=['2027-01-01', '2028-01-01'], staffel_erhoehung=['50', '30.5']).json()
        self.assertEqual(set(j), {'befunde', 'sperre', 'abgeleitet', 'unlesbar'})
        self.assertEqual(set(j['abgeleitet']), {'fest_bis', 'mindest_ende', 'stufen', 'basis_lik'})
        self.assertEqual(j['abgeleitet']['fest_bis'], '2028-12-31')
        self.assertEqual(j['abgeleitet']['mindest_ende'], '2028-12-31')
        self.assertEqual(j['abgeleitet']['stufen'], [
            {'ab': '2027-01-01', 'erhoehung': '50', 'neu': '1050'},
            {'ab': '2028-01-01', 'erhoehung': '30.5', 'neu': '1080.5'}])
        self.assertFalse(j['sperre'])
        for b in j['befunde']:
            self.assertEqual(set(b), {'regel', 'stufe', 'text', 'artikel', 'feld', 'fix', 'zeile'})

    def test_sperre_bei_einem_tag_zu_kurz_und_nicht_bei_genau_fuenf_jahren(self):
        zu_kurz = self._get(self.rollen['Inhaber'], modell='index', beginn='2026-01-01', ende='2030-12-30',
                            ist_befristet='1', basis_lik_punkte='106.9', basis_lik_stand='2025-12',
                            index_weitergabe_prozent='100', index_intervall_monate='12').json()
        self.assertTrue(zu_kurz['sperre'])
        self.assertIn('index_dauer', [b['regel'] for b in zu_kurz['befunde']])
        genau = self._get(self.rollen['Inhaber'], modell='index', beginn='2026-01-01', ende='2030-12-31',
                          ist_befristet='1', basis_lik_punkte='106.9', basis_lik_stand='2025-12',
                          index_weitergabe_prozent='100', index_intervall_monate='12').json()
        self.assertFalse(genau['sperre'], genau['befunde'])
        self.assertEqual(genau['abgeleitet']['mindest_ende'], '2030-12-31')

    def test_basis_lik_vorschlag_ist_der_stand_vor_dem_mietbeginn(self):
        j = self._get(self.rollen['Inhaber'], modell='index', beginn='2022-01-01').json()
        self.assertEqual(j['abgeleitet']['basis_lik'], {'punkte': '101.5', 'stand': '2021-12'})
        # Gegenprobe: nicht der aktuelle Stand
        self.assertNotEqual(j['abgeleitet']['basis_lik']['stand'], '2026-06')

    def test_halb_ausgefuellt_ist_kein_fehler(self):
        for params in ({}, {'modell': 'index'}, {'modell': 'staffel', 'beginn': '2026-01-01'},
                       {'modell': 'staffel', 'beginn': '2026-01-01', 'staffel_ab': ['2027-01-01']},
                       {'modell': 'staffel', 'beginn': '2026-01-01', 'staffel_ab': ['', ''],
                        'staffel_erhoehung': ['', '']}):
            with self.subTest(params=params):
                antwort = self._get(self.rollen['Inhaber'], **params)
                self.assertEqual(antwort.status_code, 200)
                antwort.json()

    def test_unlesbare_eingaben_werden_gemeldet_nicht_geworfen(self):
        j = self._get(self.rollen['Inhaber'], modell='staffel', beginn='kein-datum', ende='2028-13-45',
                      netto='NaN', staffel_ab=['2027-01-01', '99999-01-01'],
                      staffel_erhoehung=['1e999999', 'Infinity'], basis_lik_stand='abc').json()
        self.assertEqual(set(j['unlesbar']), {'beginn', 'ende', 'netto', 'basis_lik_stand', 'staffel_erhoehung[0]',
                                              'staffel_ab[1]', 'staffel_erhoehung[1]'})

    def test_unbekanntes_modell_wird_gemeldet(self):
        j = self._get(self.rollen['Inhaber'], modell='hypothek').json()
        self.assertIn('modell', j['unlesbar'])

    def test_schweizer_zahlenformat_wird_gelesen(self):
        j = self._get(self.rollen['Inhaber'], modell='staffel', beginn='2026-01-01', ende='2028-12-31',
                      ist_befristet='1', netto="1'200.50", staffel_ab=['2027-01-01'],
                      staffel_erhoehung=['50,25']).json()
        self.assertEqual(j['abgeleitet']['stufen'], [{'ab': '2027-01-01', 'erhoehung': '50.25', 'neu': '1250.75'}])

    def test_prozent_und_zeile_kommen_im_befund_an(self):
        j = self._get(self.rollen['Inhaber'], modell='staffel', beginn='2026-01-01', ende='2028-12-31',
                      ist_befristet='1', staffel_ab=['2027-01-01', '2028-01-01'],
                      staffel_erhoehung=['50', ''], staffel_prozent=['', '3']).json()
        prozent = [b for b in j['befunde'] if b['regel'] == 'staffel_prozent']
        self.assertEqual([b['zeile'] for b in prozent], [1])

    def test_mandanten_der_endpunkt_liest_keine_datensaetze(self):
        """Fremde IDs im Querystring ändern nichts, und es wird keine Fachtabelle gelesen."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        c = Client()
        c.force_login(self.a.benutzer)
        ohne = c.get(self.URL, {'modell': 'index', 'beginn': '2026-01-01'}).json()
        with CaptureQueriesContext(connection) as sql:
            mit = c.get(self.URL, {'modell': 'index', 'beginn': '2026-01-01',
                                   'vertrag_id': self.b.vertrag.pk, 'lg': self.b.liegenschaft.pk,
                                   'einheit': self.b.einheit.pk}).json()
        self.assertEqual(ohne, mit)
        fachtabellen = ('core_mietvertrag', 'core_staffelstufe', 'crm_mieter', 'portfolio_', 'rentals_')
        gelesen = [q['sql'] for q in sql.captured_queries if any(t in q['sql'] for t in fachtabellen)]
        self.assertEqual(gelesen, [])
        self.assertNotIn(self.b.mieter.nachname + '"', json.dumps(mit))

    def test_benutzer_von_b_sieht_dieselbe_antwort_aber_nur_mit_eigener_rolle(self):
        c = Client()
        c.force_login(self.b.benutzer)
        self.assertEqual(c.get(self.URL, {'modell': 'fest'}).status_code, 200)

    def test_view_traegt_die_team_rollen(self):
        from core.auth import TEAM_ROLLEN
        from core.views.fw.mietzinsmodell_pruefen import fw_mietzinsmodell_pruefen
        self.assertEqual(fw_mietzinsmodell_pruefen.benoetigte_rollen, tuple(TEAM_ROLLEN))


class VertragstextTests(TestCase):

    def _html(self, v, mit_zeitplan=False):
        from core.services.pdf_service import render_vertrag_html
        return render_vertrag_html(v, mit_unterschrift=False)

    def test_indexklausel_nennt_lik_basis_weitergabe_ankuendigung_und_dauer(self):
        v = _vertrag('index', index_weitergabe_prozent=Decimal('80.0'), index_intervall_monate=12)
        html = self._html(v)
        for muster in ('Indexklausel (Art. 269b OR)', 'Landesindex der Konsumentenpreise (LIK)',
                       'Bundesamts für Statistik', 'Februar 2026 mit 107,6 Punkten', 'Dezember 2020 = 100',
                       '80 Prozent der Indexveränderung', 'Sinkt der Index', 'mindestens 30 Tage',
                       'amtlichen Formular', 'Monatsende', 'öffentlichen Bekanntgabe',
                       'bis zum 28.02.2031 fest abgeschlossen'):
            with self.subTest(muster=muster):
                self.assertIn(muster, html)
        self.assertNotIn('Staffelmietklausel', html)

    def test_indexklausel_mit_kuendigungsverzicht(self):
        v = _vertrag('index', ist_befristet=False, ende=None, vermieter_kuendigungsverzicht_bis=d(2031, 2, 28))
        html = self._html(v)
        self.assertIn('Der Vermieter verzichtet bis zum 28.02.2031 auf die Kündigung', html)
        self.assertIn('Art. 17 Abs. 4 VMWG', html)
        self.assertNotIn('fest abgeschlossen', html)

    def test_ohne_feste_dauer_steht_sichtbar_dass_sie_fehlt(self):
        v = _vertrag('index', ist_befristet=False, ende=None)
        self.assertIn('ist noch nicht festgelegt', self._html(v))

    def test_staffelklausel_hat_erhoehung_in_chf_und_den_richtigen_mitteilungssatz(self):
        from rentals.models import Staffelstufe
        v = _vertrag('staffel', ende=d(2029, 2, 28), netto_mietzins=Decimal('1200'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), erhoehung_chf=Decimal('50'),
                                    netto_mietzins=Decimal('0'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=d(2028, 3, 1), erhoehung_chf=Decimal('30.5'),
                                    netto_mietzins=Decimal('0'))
        html = self._html(v)
        for muster in ('Staffelmietklausel (Art. 269c OR)', 'CHF 1\'200.00', 'Erhöhung um CHF 50.00',
                       'neu CHF 1\'250.00', 'Erhöhung um CHF 30.50', 'neu CHF 1\'280.50',
                       'höchstens einmal jährlich', 'schriftlich', 'frühestens vier Monate',
                       'Art. 269d Abs. 5 OR', 'Art. 19a VMWG'):
            with self.subTest(muster=muster):
                self.assertIn(muster, html)
        self.assertNotIn('bedarf es nicht', html)
        self.assertNotIn('Indexklausel (Art', html)

    def test_der_falsche_satz_steht_nirgends_mehr(self):
        import pathlib
        from django.conf import settings
        treffer = [str(p) for p in (pathlib.Path(settings.BASE_DIR) / 'core' / 'templates').rglob('*.html')
                   if 'bedarf es nicht' in p.read_text(encoding='utf-8')]
        self.assertEqual(treffer, [])

    def test_auch_der_zeitplan_abschnitt_behauptet_keine_entfallene_mitteilung(self):
        from rentals.models import VertragMietzins
        v = _vertrag('fest')
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=d(2026, 3, 1), netto_mietzins=Decimal('1000'),
                                       rabatt_netto=Decimal('1000'))
        VertragMietzins.objects.create(vertrag=v, gueltig_ab=d(2026, 4, 1), netto_mietzins=Decimal('1000'))
        html = self._html(v)
        self.assertIn('Gestaffelter Mietzins / Gratismonate', html)
        self.assertNotIn('bedarf es nicht', html)

    def test_fester_vertrag_traegt_keine_modellklausel(self):
        html = self._html(_vertrag('fest'))
        self.assertNotIn('Indexklausel', html)
        self.assertNotIn('Staffelmietklausel', html)

    def test_garagenvertrag_traegt_die_klausel_ebenfalls(self):
        from portfolio.models import Einheit
        from rentals.models import Staffelstufe
        lg, _e, m, _v = _basis_objekte()
        gar = Einheit.objects.create(liegenschaft=lg, bezeichnung='Garage 1', typ='gar',
                                     nettomiete_aktuell=Decimal('150'))
        v = _vertrag('staffel', einheit=gar, mieter=m, ende=d(2029, 2, 28), netto_mietzins=Decimal('150'))
        Staffelstufe.objects.create(vertrag=v, ab_datum=d(2027, 3, 1), erhoehung_chf=Decimal('10'),
                                    netto_mietzins=Decimal('0'))
        html = self._html(v)
        self.assertIn('Staffelmietklausel (Art. 269c OR)', html)
        self.assertIn('Erhöhung um CHF 10.00', html)
        # Gegenprobe: derselbe Garagenvertrag fest
        fest = _vertrag('fest', einheit=gar, mieter=m)
        self.assertNotIn('Staffelmietklausel', self._html(fest))

    def test_klausel_braucht_keinen_kontext_der_aufrufenden_stelle(self):
        """DocuSeal und PDF bauen verschiedene Kontexte; der Tag liest nur den Vertrag."""
        v = _vertrag('index')
        html = get_template('core/mietvertrag_pdf.html').render({'vertrag': v, 'einheit': v.einheit})
        self.assertIn('Indexklausel (Art. 269b OR)', html)
        self.assertIn('107,6 Punkten', html)

    def test_vorschau_stufen_aus_dem_formular(self):
        v = _vertrag('staffel', ende=d(2029, 2, 28))
        v.vorschau_stufen = [{'ab': d(2027, 3, 1), 'erhoehung': '40'}]
        html = self._html(v)
        self.assertIn('Erhöhung um CHF 40.00', html)
        self.assertIn('neu CHF 1\'040.00', html)


class BestandsberichtTests(MandantenBasis):

    def setUp(self):
        from rentals.models import Mietvertrag, Staffelstufe
        with organisation_kontext(self.a.organisation):
            self.va = Mietvertrag.objects.create(
                mieter=self.a.mieter, einheit=self.a.einheit, beginn=d(2026, 1, 1),
                netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'), status='aktiv',
                mietzins_modell='staffel', ist_befristet=False)
            Staffelstufe.objects.create(vertrag=self.va, ab_datum=d(2027, 1, 1), netto_mietzins=Decimal('1000'))
            self.gut_a = Mietvertrag.objects.create(
                mieter=self.a.mieter, einheit=self.a.einheit, beginn=d(2026, 1, 1),
                netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'), status='aktiv',
                mietzins_modell='fest')
        with organisation_kontext(self.b.organisation):
            self.vb = Mietvertrag.objects.create(
                mieter=self.b.mieter, einheit=self.b.einheit, beginn=d(2026, 3, 1),
                netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'), status='aktiv',
                mietzins_modell='index', ist_befristet=False)

    def _json(self, *args):
        out = StringIO()
        call_command('mietzinsmodell_bestand', '--json', *args, stdout=out)
        return json.loads(out.getvalue())

    def _org(self, bestand):
        return [o for o in self._json()['organisationen'] if o['organisation_id'] == bestand.organisation.pk][0]

    def test_jede_organisation_nur_mit_ihren_vertraegen(self):
        # Das Fixture selbst trägt je Mandant einen FESTEN Vertrag mit einer Staffelstufe (fest_staffelstufen)
        a, b = self._org(self.a), self._org(self.b)
        self.assertEqual({x['vertrag_id'] for x in a['verstoesse']}, {self.a.vertrag.pk, self.va.pk})
        self.assertEqual({x['vertrag_id'] for x in b['verstoesse']}, {self.b.vertrag.pk, self.vb.pk})
        self.assertNotIn(self.b.mieter.display_name, json.dumps(a))
        self.assertNotIn(self.a.mieter.display_name, json.dumps(b))
        # Der feste Vertrag ohne Staffelstufen wird gar nicht erst geprüft
        self.assertEqual(a['geprueft'], 2)

    def test_regel_und_artikel_stehen_im_bericht(self):
        a = self._org(self.a)
        je_regel = {x['regel'] for x in a['verstoesse'] if x['vertrag_id'] == self.va.pk}
        self.assertEqual(je_regel, {'staffel_dauer', 'staffel_erhoehung'})     # Altstufe ohne Erhöhung
        for x in a['verstoesse']:
            self.assertTrue(x['artikel'].startswith('Art. 269c'), x['artikel'])
        b = self._org(self.b)
        self.assertIn('index_dauer', {x['regel'] for x in b['verstoesse'] if x['vertrag_id'] == self.vb.pk})

    def test_nur_eine_organisation(self):
        j = self._json('--organisation', str(self.b.organisation.pk))
        self.assertEqual([o['organisation_id'] for o in j['organisationen']], [self.b.organisation.pk])

    def test_tabelle_nennt_regel_und_artikel_und_aendert_nichts(self):
        from rentals.models import Mietvertrag, Staffelstufe
        vorher = (list(Mietvertrag.alle_organisationen.order_by('pk').values()),
                  list(Staffelstufe.alle_organisationen.order_by('pk').values()))
        out = StringIO()
        call_command('mietzinsmodell_bestand', stdout=out)
        text = out.getvalue()
        self.assertIn('staffel_dauer', text)
        self.assertIn('index_dauer', text)
        self.assertIn('Art. 269c', text)
        self.assertIn('Es wurde nichts verändert', text)
        nachher = (list(Mietvertrag.alle_organisationen.order_by('pk').values()),
                   list(Staffelstufe.alle_organisationen.order_by('pk').values()))
        self.assertEqual(vorher, nachher)

    def test_archivierte_nur_mit_schalter(self):
        from rentals.models import Mietvertrag
        Mietvertrag.alle_organisationen.filter(pk__in=[self.va.pk, self.a.vertrag.pk]).update(status='archiviert')
        self.assertEqual(self._org(self.a)['verstoesse'], [])
        a2 = [o for o in self._json('--mit-archiviert')['organisationen']
              if o['organisation_id'] == self.a.organisation.pk][0]
        self.assertNotEqual(a2['verstoesse'], [])

    def test_sauberer_bestand_meldet_nichts(self):
        from rentals.models import Mietvertrag, Staffelstufe
        Mietvertrag.alle_organisationen.filter(pk=self.va.pk).update(ist_befristet=True, ende=d(2028, 12, 31))
        Staffelstufe.alle_organisationen.filter(vertrag__in=[self.va, self.a.vertrag]).delete()
        with organisation_kontext(self.a.organisation):
            Staffelstufe.objects.create(vertrag=self.va, ab_datum=d(2027, 1, 1), erhoehung_chf=Decimal('50'),
                                        netto_mietzins=Decimal('0'))
        self.assertEqual(self._org(self.a)['verstoesse'], [])
        # Gegenprobe: mit der Altstufe ohne Erhöhung war der Bestand nicht sauber (siehe oben)


class HilfeEintraegeTests(SimpleTestCase):

    def test_schluessel_und_artikel(self):
        from core.hilfe import HILFE
        erwartet = {'indexmiete': 'Art. 269b OR', 'staffelmiete': 'Art. 269c OR',
                    'index_staffel_kombination': 'BGE 124 III 57', 'kuendigungsverzicht': 'Art. 17 Abs. 4 VMWG',
                    'staffel_mitteilung': 'Art. 269d Abs. 5 OR'}
        for schluessel, artikel in erwartet.items():
            with self.subTest(schluessel=schluessel):
                self.assertIn(schluessel, HILFE)
                self.assertIn(artikel, str(HILFE[schluessel][1]))

    def test_fr_it_en_uebersetzt(self):
        from django.utils import translation
        from core.hilfe import HILFE
        for schluessel in ('index_staffel_kombination', 'kuendigungsverzicht', 'staffel_mitteilung'):
            for sprache, marke in (('fr', 'art.'), ('it', 'art.'), ('en', 'Art.')):
                with self.subTest(schluessel=schluessel, sprache=sprache), translation.override(sprache):
                    text = str(HILFE[schluessel][1])
                    self.assertIn(marke, text)
                    self.assertNotIn('Vermieter', text)
                    self.assertNotIn('Mieter', text)

    def test_befunde_sind_uebersetzt(self):
        from django.utils import translation
        with translation.override('de'):
            de = mm.sperren(index_gueltig(weitergabe_prozent=0))[0].text
        with translation.override('fr'):
            fr = mm.sperren(index_gueltig(weitergabe_prozent=0))[0].text
            staffel = mm.sperren(staffel_gueltig(stufen=[{'ab': d(2027, 1, 1), 'erhoehung': 0}]))[0]
        self.assertEqual(de, 'Die Weitergabe muss über 0 % liegen.')
        self.assertEqual(fr, 'La répercussion doit être supérieure à 0 %.')
        self.assertTrue(staffel.text.startswith('Palier 1'))
