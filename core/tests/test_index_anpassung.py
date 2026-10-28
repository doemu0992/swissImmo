"""Indexanpassung (Art. 269b OR, Art. 17 und 19 Abs. 2 VMWG) — Rechenkern, Fristen, Assistent.

Jede Klasse nennt, was sie festhält. Die Gegenproben stehen im Bericht zur Etappe:
Code zurückgebaut -> der genannte Test wird rot, wiederhergestellt -> grün.

Die LIK-Tabelle und das Datum werden festgesetzt (`TABELLE`, `HEUTE`), damit kein
Test vom Kalender oder vom nächsten BFS-Monat abhängt.
"""
import io
from datetime import date
from decimal import Decimal
from fractions import Fraction
from unittest import mock

from django.test import Client, SimpleTestCase, TestCase
from pypdf import PdfReader

from core.services import index_anpassung as ia

from ._helfer import _basis_objekte, _team_user, _test_organisation

D = Decimal

#: Feste Tabelle: Januar bis April 100, Mai 105, Juni 105 — Juli ist NICHT veröffentlicht.
TABELLE = {2026: [100.0, 100.0, 100.0, 100.0, 105.0, 105.0]}
SINKT = {2026: [100.0, 100.0, 100.0, 100.0, 95.0, 95.0]}
HEUTE = date(2026, 10, 27)


def _tabelle(tab):
    return mock.patch('core.services.lik.LIK_DEZ2020', tab)


def _heute():
    return mock.patch('django.utils.timezone.localdate', return_value=HEUTE)


# ---------------------------------------------------------------------------
# Rechenkern
# ---------------------------------------------------------------------------
class RechenkernTests(SimpleTestCase):
    """Art. 17 Abs. 1 und 2 VMWG: Höchstbetrag, Richtung, Rundung."""

    def test_erhoehung_hoechstens_die_zunahme(self):
        r = ia.rechne(D('1000'), D('100'), D('105'), D('100'))
        self.assertEqual(r.richtung, 'erhoehung')
        self.assertEqual(r.hoechst_netto, D('1050.00'))
        self.assertEqual(r.hoechst_erhoehung_chf, D('50.00'))
        self.assertFalse(r.ueberschreitet(D('1050.00')))
        self.assertTrue(r.ueberschreitet(D('1050.01')))      # Gegenprobe: ein Rappen zu viel

    def test_weitergabe_50_und_100_prozent(self):
        voll = ia.rechne(D('1000'), D('100'), D('110'), D('100'))
        halb = ia.rechne(D('1000'), D('100'), D('110'), D('50'))
        self.assertEqual(voll.hoechst_netto, D('1100.00'))
        self.assertEqual(halb.hoechst_netto, D('1050.00'))
        self.assertTrue(halb.ueberschreitet(D('1050.01')))
        self.assertFalse(voll.ueberschreitet(D('1050.01')))   # dieselbe Eingabe, andere Weitergabe

    def test_weitergabe_ueber_100_wird_auf_100_begrenzt(self):
        r = ia.rechne(D('1000'), D('100'), D('110'), D('150'))
        self.assertEqual(r.weitergabe_prozent, D('100'))
        self.assertEqual(r.hoechst_netto, D('1100.00'))

    def test_weitergabe_leer_ist_100_null_bleibt_null(self):
        self.assertEqual(ia.rechne(D('1000'), D('100'), D('110'), None).hoechst_netto, D('1100.00'))
        r = ia.rechne(D('1000'), D('100'), D('110'), D('0'))
        self.assertEqual(r.hoechst_netto, D('1000.00'))
        self.assertTrue(r.ueberschreitet(D('1000.01')))

    def test_lik_unveraendert_keine_erhoehung(self):
        r = ia.rechne(D('1000'), D('100'), D('100'), D('100'))
        self.assertEqual(r.richtung, 'unveraendert')
        self.assertTrue(r.ueberschreitet(D('1000.01')))
        self.assertIn('unverändert', ia.eingabe_fehler(r, D('1000.01')))
        self.assertEqual(ia.eingabe_fehler(r, D('1000.00')), '')

    def test_sinkender_lik_laesst_keinen_hoeheren_betrag_zu(self):
        """Art. 17 Abs. 2: Die Anpassung nach unten ist zwingend."""
        r = ia.rechne(D('1000'), D('100'), D('95'), D('100'))
        self.assertEqual(r.richtung, 'senkung')
        self.assertEqual(r.hoechst_netto, D('950.00'))
        self.assertEqual(r.vorschlag_netto, D('950.00'))
        self.assertTrue(r.ueberschreitet(D('950.01')))
        self.assertTrue(r.ueberschreitet(D('1000.00')))        # «bleibt wie bisher» ist hier nicht erlaubt
        self.assertIn('Art. 17 Abs. 2', ia.eingabe_fehler(r, D('1000.00')))
        self.assertEqual(ia.eingabe_fehler(r, D('950.00')), '')
        self.assertEqual(ia.eingabe_fehler(r, D('940.00')), '')  # mehr senken darf der Vermieter

    def test_vorschlag_wird_abgerundet_und_ueberschreitet_die_grenze_nie(self):
        """1480 × 107.3 / 105 = 1512.6666…: kaufmännisch gäbe 1512.65, abgerundet 1512.65 — und
        bei 1512.69 wäre aufgerundet 1512.70 über der Grenze gewesen."""
        for alt, basis, neu in ((D('1480'), D('105'), D('107.3')),
                                (D('1699.08'), D('106.9'), D('108.3')),
                                (D('1234.56'), D('101.5'), D('103.7')),
                                (D('1480'), D('105.0'), D('106.4'))):
            r = ia.rechne(alt, basis, neu, D('100'))
            exakt = Fraction(alt) * Fraction(neu) / Fraction(basis)
            self.assertEqual(r.vorschlag_netto % D('0.05'), 0)
            self.assertLessEqual(Fraction(r.vorschlag_netto), exakt)
            self.assertGreater(Fraction(r.vorschlag_netto) + Fraction(5, 100), exakt)  # und nicht tiefer als nötig
            self.assertFalse(r.ueberschreitet(r.vorschlag_netto))

    def test_rundung_exakt_wo_decimal_scheitern_wuerde(self):
        """1650 × 106.4 / 105 ist exakt 1672. In Decimal ergäbe die Rechnung 1671.999…, und das
        Abrunden auf 5 Rappen gäbe 1671.95 — fünf Rappen unter der Grenze."""
        r = ia.rechne(D('1650'), D('105'), D('106.4'), D('100'))
        self.assertEqual(r.vorschlag_netto, D('1672.00'))
        self.assertEqual(r.hoechst_netto, D('1672.00'))
        self.assertFalse(r.ueberschreitet(D('1672.00')))
        r2 = ia.rechne(D('1650'), D('108'), D('108.9'), D('100'))        # exakt 1663.75
        self.assertEqual(r2.vorschlag_netto, D('1663.75'))

    def test_basis_fehlt(self):
        with self.assertRaises(ValueError):
            ia.rechne(D('1000'), D('0'), D('105'), D('100'))

    def test_anzeige_zunahme(self):
        r = ia.rechne(D('1000'), D('106.9'), D('108.3'), D('80'))
        self.assertEqual(r.zunahme_prozent, D('1.31'))
        self.assertEqual(r.wirkung_prozent, D('1.05'))


# ---------------------------------------------------------------------------
# Veröffentlichter Stand (a, d)
# ---------------------------------------------------------------------------
class StandTests(SimpleTestCase):
    """a) Nur ein Monat, der in der Tabelle steht, kann Grundlage sein (Art. 19 Abs. 2 VMWG)."""

    def test_veroeffentlichter_monat_ist_zulaessig(self):
        with _tabelle(TABELLE):
            self.assertEqual(ia.stand_fehler(date(2026, 6, 1), HEUTE), '')
            self.assertEqual(ia.lik_punkte(date(2026, 6, 1)), D('105.0'))

    def test_nicht_veroeffentlichter_monat_wird_mit_letztem_monat_gemeldet(self):
        with _tabelle(TABELLE):
            fehler = ia.stand_fehler(date(2026, 7, 1), HEUTE)
        self.assertIn('nicht veröffentlicht', fehler)
        self.assertIn('Art. 19 Abs. 2 VMWG', fehler)
        self.assertIn('Juni 2026', fehler)            # der letzte verfügbare Monat

    def test_monat_ausserhalb_der_tabelle_und_leerer_eintrag(self):
        tab = {2026: [None, 101.0]}
        with _tabelle(tab):
            self.assertNotEqual(ia.stand_fehler(date(2026, 1, 1), HEUTE), '')   # None in der Tabelle
            self.assertNotEqual(ia.stand_fehler(date(2030, 1, 1), date(2031, 1, 1)), '')  # ganz ausserhalb
            self.assertEqual(ia.stand_fehler(date(2026, 2, 1), HEUTE), '')

    def test_zukuenftiger_monat_kann_nicht_bekannt_sein(self):
        """Auch wenn jemand den Wert voreilig in die Tabelle schrieb."""
        with _tabelle({2026: [100.0] * 12}):
            self.assertNotEqual(ia.stand_fehler(date(2026, 12, 1), HEUTE), '')
            self.assertEqual(ia.stand_fehler(date(2026, 10, 1), HEUTE), '')
            self.assertEqual(ia.letzter_stand(bis=HEUTE), date(2026, 10, 1))

    def test_stand_vor_dem_bisherigen_wird_abgelehnt(self):
        with _tabelle(TABELLE):
            self.assertNotEqual(ia.stand_fehler(date(2026, 3, 1), HEUTE, alt_stand=date(2026, 5, 1)), '')
            self.assertEqual(ia.stand_fehler(date(2026, 5, 1), HEUTE, alt_stand=date(2026, 5, 1)), '')

    def test_stand_aus_text(self):
        self.assertEqual(ia.stand_aus_text('2026-06'), date(2026, 6, 1))
        self.assertIsNone(ia.stand_aus_text('Juni'))
        self.assertIsNone(ia.stand_aus_text(''))


# ---------------------------------------------------------------------------
# Frist (c)
# ---------------------------------------------------------------------------
class FristTests(SimpleTestCase):
    """c) Mindestens 30 Tage, auf ein Monatsende (Art. 17 Abs. 3 VMWG)."""

    def test_genau_30_tage_bis_zum_monatsende_reichen(self):
        # Zugang 1.12.2026 + 30 Tage = 31.12.2026: das Monatsende selbst genügt.
        self.assertEqual(ia.fruehestes_monatsende(date(2026, 12, 1)), date(2026, 12, 31))

    def test_29_tage_bis_zum_monatsende_reichen_nicht(self):
        # Zugang 2.12.2026: bis 31.12. sind es 29 Tage -> erst Monatsende Januar.
        self.assertEqual(ia.fruehestes_monatsende(date(2026, 12, 2)), date(2027, 1, 31))

    def test_wirksam_ist_der_erste_nach_dem_monatsende(self):
        self.assertEqual(ia.frueheste_wirksamkeit(date(2026, 12, 1), puffer_tage=0), date(2027, 1, 1))
        self.assertEqual(ia.frueheste_wirksamkeit(date(2026, 12, 2), puffer_tage=0), date(2027, 2, 1))

    def test_monatsende_dreissig_einunddreissig_tage_monate(self):
        # 31.12. + 30 = 30.1. -> 31.1. ; 1.1. + 30 = 31.1. -> 31.1.
        self.assertEqual(ia.fruehestes_monatsende(date(2026, 12, 31)), date(2027, 1, 31))
        self.assertEqual(ia.fruehestes_monatsende(date(2027, 1, 1)), date(2027, 1, 31))
        self.assertEqual(ia.fruehestes_monatsende(date(2027, 1, 2)), date(2027, 2, 28))

    def test_schaltjahr_und_normaljahr(self):
        # 2028 ist ein Schaltjahr: 30.1. + 30 = 29.2. = Monatsende.
        self.assertEqual(ia.fruehestes_monatsende(date(2028, 1, 30)), date(2028, 2, 29))
        self.assertEqual(ia.frueheste_wirksamkeit(date(2028, 1, 30), puffer_tage=0), date(2028, 3, 1))
        self.assertEqual(ia.fruehestes_monatsende(date(2028, 1, 31)), date(2028, 3, 31))
        # 2027 nicht: 29.1. + 30 = 28.2. = Monatsende; 30.1. + 30 = 1.3.
        self.assertEqual(ia.fruehestes_monatsende(date(2027, 1, 29)), date(2027, 2, 28))
        self.assertEqual(ia.fruehestes_monatsende(date(2027, 1, 30)), date(2027, 3, 31))

    def test_zustellpuffer_verschiebt_den_termin(self):
        # Versand 25.11.2026: ohne Puffer Zugang 25.11. -> 31.12.; mit Puffer (7 Tage) Zugang 2.12. -> 31.1.
        self.assertEqual(ia.frueheste_wirksamkeit(date(2026, 11, 25), puffer_tage=0), date(2027, 1, 1))
        self.assertEqual(ia.frueheste_wirksamkeit(date(2026, 11, 25)), date(2027, 2, 1))

    def test_bestaetigter_zugang_ersetzt_den_puffer(self):
        self.assertEqual(ia.frueheste_wirksamkeit(date(2026, 11, 25), zugang_am=date(2026, 11, 30)),
                         date(2027, 1, 1))

    def test_termin_fehler(self):
        versand = date(2026, 11, 25)
        frueh = ia.frueheste_wirksamkeit(versand)
        self.assertEqual(ia.termin_fehler(frueh, versand), '')
        zu_frueh = ia.termin_fehler(date(2027, 1, 1), versand)
        self.assertIn('zu früh', zu_frueh)
        self.assertIn('01.02.2027', zu_frueh)                  # nennt den frühesten Termin
        self.assertIn('Monatsende', ia.termin_fehler(date(2027, 2, 15), versand))   # nicht der Erste
        self.assertNotEqual(ia.termin_fehler(None, versand), '')
        self.assertEqual(ia.termin_fehler(date(2027, 3, 1), versand), '')            # später ist immer erlaubt

    def test_terminliste_beginnt_beim_fruehesten_und_zaehlt_monate(self):
        liste = ia.termine_ab(date(2027, 1, 1), anzahl=14)
        self.assertEqual((liste[0], liste[1], liste[12], liste[13]),
                         (date(2027, 1, 1), date(2027, 2, 1), date(2028, 1, 1), date(2028, 2, 1)))


# ---------------------------------------------------------------------------
# Vertragliche Grenzen (e)
# ---------------------------------------------------------------------------
class VertragsgrenzenTests(TestCase):

    def test_mindestintervall_ist_ein_hinweis_kein_gesetz(self):
        _lg, _e, _m, v = _basis_objekte()
        v.index_intervall_monate = 12
        v.index_letzte_anpassung = date(2026, 3, 1)
        g = ia.vertragsgrenzen(v)
        self.assertEqual(g['fruehestens'], date(2027, 3, 1))
        hinweis = ia.intervall_hinweis(v, date(2027, 1, 1))
        self.assertIn('Vertragliche Grenze', hinweis)
        self.assertIn('kein Gesetzeswert', hinweis)
        self.assertEqual(ia.intervall_hinweis(v, date(2027, 3, 1)), '')

    def test_ohne_letzte_anpassung_kein_hinweis(self):
        _lg, _e, _m, v = _basis_objekte()
        v.index_letzte_anpassung = None
        self.assertEqual(ia.intervall_hinweis(v, date(2026, 1, 1)), '')


# ---------------------------------------------------------------------------
# Vorschlag (mietrecht.index_anpassung_vorschlag)
# ---------------------------------------------------------------------------
def _index_vertrag(kanton='ZH', basis='100.0', weitergabe='100.0', netto='1000.00'):
    _test_organisation(aktueller_referenzzinssatz=D('1.50'), aktueller_lik_punkte=D('100'))
    lg, e, m, v = _basis_objekte()
    if kanton is not None:
        lg.kanton = kanton
        lg.save()
    v.mietzins_modell = 'index'
    v.basis_lik_punkte = D(basis)
    v.index_weitergabe_prozent = D(weitergabe)
    v.netto_mietzins = D(netto)
    v.ist_befristet = True
    v.beginn = date(2024, 1, 1)
    v.ende = date(2030, 1, 1)
    v.save()
    return v


class VorschlagTests(TestCase):

    def test_vorschlag_nur_fuer_veroeffentlichten_stand(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = _index_vertrag()
        with _tabelle(TABELLE):
            ok = index_anpassung_vorschlag(v, stand=date(2026, 6, 1))
            fehlt = index_anpassung_vorschlag(v, stand=date(2026, 7, 1))
        self.assertEqual(ok['neu_netto'], D('1050.00'))
        self.assertEqual(ok['hoechst_netto'], D('1050.00'))
        self.assertIsNone(fehlt)                           # Gegenprobe: derselbe Aufruf, anderer Monat

    def test_vorschlag_bei_unveraendertem_lik_ist_leer(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = _index_vertrag()
        with _tabelle(TABELLE):
            self.assertIsNone(index_anpassung_vorschlag(v, stand=date(2026, 4, 1)))   # 100 = Basis

    def test_vorschlag_bei_sinkendem_lik(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = _index_vertrag()
        with _tabelle(SINKT):
            r = index_anpassung_vorschlag(v, stand=date(2026, 6, 1))
        self.assertEqual((r['richtung'], r['neu_netto']), ('senkung', D('950.00')))

    def test_vorschlag_mit_weitergabe_50(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = _index_vertrag(weitergabe='50.0')
        with _tabelle(TABELLE):
            r = index_anpassung_vorschlag(v, stand=date(2026, 6, 1))
        self.assertEqual(r['neu_netto'], D('1025.00'))
        self.assertIn('Weitergabe 50', r['begruendung'])

    def test_vorschlag_ueberschreitet_die_grenze_auch_bei_krummen_betraegen_nicht(self):
        from core.services.mietrecht import index_anpassung_vorschlag
        v = _index_vertrag(basis='105.0', netto='1480.00')
        r = index_anpassung_vorschlag(v, aktuell_lik=D('107.3'))
        exakt = Fraction(D('1480.00')) * Fraction(D('107.3')) / Fraction(D('105.0'))
        self.assertLessEqual(Fraction(r['neu_netto']), exakt)
        self.assertEqual(r['neu_netto'] % D('0.05'), 0)


# ---------------------------------------------------------------------------
# Der Assistent: GET
# ---------------------------------------------------------------------------
class AssistentSeiteTests(TestCase):

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())

    def _get(self, v, **params):
        with _tabelle(TABELLE), _heute():
            return self.c.get(f'/neu/mietzins/{v.id}/anpassung/', params)

    def test_index_zweig_bietet_keine_ordentlichen_gruende(self):
        """g) Referenzzins, Kostensteigerung und Vorbehalt gibt es bei der Indexmiete nicht."""
        v = _index_vertrag()
        body = self._get(v).content.decode()
        for name in ('neu_zins', 'kosten_pct', 'mit_vorbehalt', 'vorbehalt_betrag', 'basis_zins'):
            self.assertNotIn(f'name="{name}"', body, name)
        for name in ('lik_stand', 'basis_lik', 'neu_netto', 'wirksam_ab'):
            self.assertIn(f'name="{name}"', body, name)

    def test_festmiete_behaelt_ihre_gruende(self):
        """Gegenprobe zur vorigen: derselbe Assistent, anderes Modell -> die Felder sind da."""
        v = _index_vertrag()
        v.mietzins_modell = 'fest'
        v.save()
        body = self._get(v).content.decode()
        for name in ('neu_zins', 'kosten_pct', 'mit_vorbehalt'):
            self.assertIn(f'name="{name}"', body, name)
        self.assertNotIn('name="lik_stand"', body)

    def test_seite_nennt_hoechstbetrag_und_fruehesten_termin(self):
        v = _index_vertrag()
        r = self._get(v)
        idx = r.context['idx']
        self.assertEqual(idx['rechnung'].hoechst_netto, D('1050.00'))
        self.assertEqual(idx['frueh'], date(2027, 1, 1))           # heute 27.10. + 7 Zustell + 30 -> 31.12.
        self.assertEqual(r.context['neu_netto'], D('1050.00'))
        self.assertEqual(idx['termine'][0], date(2027, 1, 1))
        self.assertIn('Höchstens', r.content.decode())

    def test_gesenkter_lik_zeigt_pflicht_zur_senkung(self):
        v = _index_vertrag()
        with _tabelle(SINKT), _heute():
            r = self.c.get(f'/neu/mietzins/{v.id}/anpassung/')
        self.assertEqual(r.context['idx']['rechnung'].richtung, 'senkung')
        self.assertEqual(r.context['neu_netto'], D('950.00'))
        self.assertNotIn('iz-senkung" class="fw-hinweis warn rounded-lg hidden', r.content.decode())

    def test_stand_ohne_veroeffentlichung_zeigt_meldung_mit_letztem_monat(self):
        v = _index_vertrag()
        r = self._get(v, lik_stand='2026-07')
        idx = r.context['idx']
        self.assertIsNone(idx['rechnung'])
        self.assertIn('nicht veröffentlicht', idx['stand_fehler'])
        self.assertIn('Juni 2026', idx['stand_fehler'])
        self.assertIn('Keine Anpassung möglich', r.content.decode())

    def test_formularluecke_wird_genannt_ohne_pdf_knopf(self):
        """f) Kanton ohne Original: die Lücke steht da, es gibt keinen PDF-Knopf."""
        v = _index_vertrag(kanton='LU')
        body = self._get(v).content.decode()
        self.assertIn('id="iz-luecke"', body)
        self.assertIn('Lücke', body)
        self.assertIn('Luzern', body)
        self.assertNotIn('value="pdf"', body)

    def test_kanton_mit_original_hat_pdf_knopf_und_keine_luecke(self):
        v = _index_vertrag(kanton='ZH')
        body = self._get(v).content.decode()
        self.assertNotIn('id="iz-luecke"', body)
        self.assertIn('value="pdf"', body)

    def test_kantone_mit_original(self):
        self.assertEqual(ia.kantone_mit_original(), ['BE', 'SO', 'ZH'])

    def test_vertragliche_grenzen_stehen_als_solche_da(self):
        v = _index_vertrag()
        v.index_intervall_monate = 18
        v.save()
        body = self._get(v).content.decode()
        self.assertIn('Vertragliche Grenzen', body)
        self.assertIn('nicht aus dem Gesetz', body)
        self.assertIn('18 Monate', body)


# ---------------------------------------------------------------------------
# Der Assistent: Live-Nachrechnung
# ---------------------------------------------------------------------------
class RechnenEndpunktTests(TestCase):

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())

    def _json(self, v, **params):
        with _tabelle(TABELLE), _heute():
            r = self.c.get(f'/neu/mietzins/{v.id}/anpassung/rechnen/', params)
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_hoechstbetrag_und_termine(self):
        v = _index_vertrag()
        j = self._json(v, lik_stand='2026-06')
        self.assertTrue(j['index'])
        self.assertEqual((j['hoechst_netto'], j['vorschlag_netto'], j['richtung']), ('1050.00', '1050.00', 'erhoehung'))
        self.assertEqual(j['fruehester_termin'], '2027-01-01')
        self.assertEqual(j['termine'][0]['wert'], '2027-01-01')
        self.assertEqual(j['stand_fehler'], '')

    def test_versanddatum_verschiebt_den_termin(self):
        v = _index_vertrag()
        j = self._json(v, lik_stand='2026-06', versand_am='2026-10-20')   # Zugang 27.10. -> 26.11. -> 30.11.
        self.assertEqual(j['fruehester_termin'], '2026-12-01')

    def test_unveroeffentlichter_stand(self):
        v = _index_vertrag()
        j = self._json(v, lik_stand='2026-07')
        self.assertIn('nicht veröffentlicht', j['stand_fehler'])
        self.assertIsNone(j['hoechst_netto'])

    def test_basis_aus_dem_formular_ueberschreibt_nur_ohne_anpassung(self):
        v = _index_vertrag(basis='105.0')
        j = self._json(v, lik_stand='2026-06', basis_lik='100')
        self.assertEqual(j['hoechst_netto'], '1050.00')                   # mit der eingegebenen Basis gerechnet
        from rentals.models import MietzinsAnpassung
        MietzinsAnpassung.objects.create(
            vertrag=v, wirksam_ab=date(2026, 1, 1), neuer_netto_mietzins=D('1000.00'),
            alter_netto_mietzins=D('1000.00'), neuer_lik_index=D('105.0'))
        j2 = self._json(v, lik_stand='2026-06', basis_lik='100')
        self.assertEqual(j2['hoechst_netto'], '1000.00')                  # die Anpassung geht vor


# ---------------------------------------------------------------------------
# Der Assistent: Speichern (Server, Gegenprobe zum UI)
# ---------------------------------------------------------------------------
class AssistentServerTests(TestCase):
    """b), c) und d) werden auf dem Server erzwungen — auch gegen einen Browser, der sie umgeht."""

    def setUp(self):
        self.c = Client()
        self.c.force_login(_team_user())

    def _post(self, v, tabelle=TABELLE, **daten):
        felder = {'aktion': 'entwurf', 'lik_stand': '2026-06', 'wirksam_ab': '2027-01-01',
                  'neu_netto': '1050.00'}
        felder.update(daten)
        with _tabelle(tabelle), _heute():
            return self.c.post(f'/neu/mietzins/{v.id}/anpassung/', felder, follow=True)

    def _meldungen(self, r):
        return ' | '.join(str(m) for m in r.context['messages'])

    def _entwuerfe(self, v):
        from rentals.models import MietzinsAnpassung
        return MietzinsAnpassung.objects.filter(vertrag=v)

    def test_hoechstbetrag_wird_angenommen(self):
        v = _index_vertrag()
        r = self._post(v)
        anp = self._entwuerfe(v).get()
        self.assertEqual((anp.status, anp.neuer_netto_mietzins, anp.wirksam_ab),
                         ('entwurf', D('1050.00'), date(2027, 1, 1)))
        self.assertEqual((anp.neuer_lik_stand, anp.neuer_lik_index), (date(2026, 6, 1), D('105.0')))
        self.assertIn('Entwurf gespeichert', self._meldungen(r))

    def test_hoehere_eingabe_wird_abgelehnt(self):
        """b) Gegenprobe zum vorigen: ein Rappen mehr, und es entsteht nichts."""
        v = _index_vertrag()
        r = self._post(v, neu_netto='1050.01')
        self.assertEqual(self._entwuerfe(v).count(), 0)
        self.assertIn('Art. 17 Abs. 1 VMWG', self._meldungen(r))
        self.assertIn('1050.00', self._meldungen(r))

    def test_hoehere_eingabe_bei_teil_weitergabe_wird_abgelehnt(self):
        v = _index_vertrag(weitergabe='50.0')
        self._post(v, neu_netto='1025.01')
        self.assertEqual(self._entwuerfe(v).count(), 0)
        self._post(v, neu_netto='1025.00')
        self.assertEqual(self._entwuerfe(v).get().neuer_netto_mietzins, D('1025.00'))

    def test_bei_sinkendem_lik_ist_nur_die_senkung_zulaessig(self):
        v = _index_vertrag()
        r = self._post(v, tabelle=SINKT, neu_netto='1000.00')           # «keine Änderung» ist nicht erlaubt
        self.assertEqual(self._entwuerfe(v).count(), 0)
        self.assertIn('Art. 17 Abs. 2 VMWG', self._meldungen(r))
        self._post(v, tabelle=SINKT, neu_netto='950.01')
        self.assertEqual(self._entwuerfe(v).count(), 0)
        self._post(v, tabelle=SINKT, neu_netto='950.00')
        anp = self._entwuerfe(v).get()
        self.assertEqual(anp.neuer_netto_mietzins, D('950.00'))
        self.assertIn('Senkung', anp.begruendung)

    def test_nicht_veroeffentlichter_stand_wird_abgelehnt(self):
        """a) Dieselbe Eingabe wie im ersten Test, nur ein Monat, den es nicht gibt."""
        v = _index_vertrag()
        r = self._post(v, lik_stand='2026-07')
        self.assertEqual(self._entwuerfe(v).count(), 0)
        self.assertIn('nicht veröffentlicht', self._meldungen(r))
        self.assertIn('Juni 2026', self._meldungen(r))

    def test_ohne_stand_wird_abgelehnt(self):
        v = _index_vertrag()
        self._post(v, lik_stand='')
        self.assertEqual(self._entwuerfe(v).count(), 0)

    def test_der_lik_kommt_aus_der_tabelle_nicht_aus_dem_formular(self):
        """Ein mitgeschickter «neu_lik» ändert nichts: Gerechnet wird mit dem Tabellenwert."""
        v = _index_vertrag()
        self._post(v, neu_lik='200', neu_zins='9.99', kosten_pct='50')
        anp = self._entwuerfe(v).get()
        self.assertEqual(anp.neuer_lik_index, D('105.0'))
        self.assertIsNone(anp.kosten_prozent)
        self.assertIsNone(anp.zins_prozent)

    def test_termin_vor_der_30_tage_frist_wird_abgelehnt(self):
        """c) Heute 27.10.2026 + 7 Tage Zustellung + 30 Tage -> 31.12.; der 1.12. ist zu früh."""
        v = _index_vertrag()
        r = self._post(v, wirksam_ab='2026-12-01')
        self.assertEqual(self._entwuerfe(v).count(), 0)
        self.assertIn('zu früh', self._meldungen(r))
        self.assertIn('01.01.2027', self._meldungen(r))

    def test_termin_mitten_im_monat_wird_abgelehnt(self):
        v = _index_vertrag()
        r = self._post(v, wirksam_ab='2027-01-15')
        self.assertEqual(self._entwuerfe(v).count(), 0)
        self.assertIn('Monatsende', self._meldungen(r))

    def test_spaeterer_monatserster_ist_erlaubt(self):
        v = _index_vertrag()
        self._post(v, wirksam_ab='2027-03-01')
        self.assertEqual(self._entwuerfe(v).get().wirksam_ab, date(2027, 3, 1))

    def test_unveraenderter_betrag_ist_nichts_mitzuteilen(self):
        v = _index_vertrag()
        r = self._post(v, neu_netto='1000.00')
        self.assertEqual(self._entwuerfe(v).count(), 0)
        self.assertIn('nichts mitzuteilen', self._meldungen(r))

    def test_begruendung_nennt_index_und_keine_40_prozent(self):
        v = _index_vertrag()
        self._post(v, begruendung='Auf Wunsch des Mieters.')
        anp = self._entwuerfe(v).get()
        self.assertIn('Art. 269b OR', anp.begruendung)
        self.assertIn('LIK 100.0 Punkte', anp.begruendung)
        self.assertIn('105.0 Punkte (Juni 2026', anp.begruendung)
        self.assertIn('Weitergabe 100 %', anp.begruendung)
        self.assertTrue(anp.begruendung.endswith('Auf Wunsch des Mieters.'))
        # Der Zusatz wird beim erneuten Öffnen vom erzeugten Satz getrennt.
        self.assertEqual(ia.zusatz_aus(anp.begruendung), 'Auf Wunsch des Mieters.')

    def test_zweites_speichern_schreibt_den_entwurf_fort(self):
        v = _index_vertrag()
        self._post(v)
        self._post(v, neu_netto='1040.00')
        anp = self._entwuerfe(v).get()
        self.assertEqual(anp.neuer_netto_mietzins, D('1040.00'))

    def test_pdf_nur_mit_kantonsoriginal(self):
        """f) ZH: PDF; LU: kein PDF, keine Nachbildung."""
        v = _index_vertrag(kanton='ZH')
        with _tabelle(TABELLE), _heute():
            r = self.c.post(f'/neu/mietzins/{v.id}/anpassung/', {
                'aktion': 'pdf', 'lik_stand': '2026-06', 'wirksam_ab': '2027-01-01', 'neu_netto': '1050.00'})
        self.assertEqual(r['Content-Type'], 'application/pdf')
        feld = ' '.join(str(f.get('/V', '')) for f in PdfReader(io.BytesIO(r.content)).get_fields().values())
        self.assertIn('Landesindex', feld)
        self.assertNotIn('40 % anrechenbar', feld)
        self.assertNotIn('Referenzzins', feld)

    def test_pdf_ohne_original_wird_nicht_ersetzt(self):
        v = _index_vertrag(kanton='LU')
        with _tabelle(TABELLE), _heute():
            r = self.c.post(f'/neu/mietzins/{v.id}/anpassung/', {
                'aktion': 'pdf', 'nachbildung_bestaetigt': 'on', 'lik_stand': '2026-06',
                'wirksam_ab': '2027-01-01', 'neu_netto': '1050.00'}, follow=True)
        self.assertNotEqual(r.get('Content-Type'), 'application/pdf')     # auch nicht nach «Bestätigung»
        self.assertIn('kein Ersatzformular', self._meldungen(r))

    def test_versand_ohne_original_nur_mit_bestaetigung(self):
        v = _index_vertrag(kanton='LU')
        r = self._post(v, aktion='versandt', versand_am=HEUTE.isoformat())
        self.assertEqual(self._entwuerfe(v).get().status, 'entwurf')       # Entwurf ja, gebucht nein
        self.assertIn('kein amtliches Originalformular', self._meldungen(r))
        self._post(v, aktion='versandt', versand_am=HEUTE.isoformat(), nachbildung_bestaetigt='on')
        self.assertEqual(self._entwuerfe(v).get().status, 'versandt')

    def test_versand_bucht_und_setzt_letzte_indexanpassung(self):
        v = _index_vertrag(kanton='ZH')
        self._post(v, aktion='versandt', versand_am=HEUTE.isoformat())
        anp = self._entwuerfe(v).get()
        self.assertEqual(anp.status, 'versandt')
        v.refresh_from_db()
        self.assertEqual(v.index_letzte_anpassung, date(2027, 1, 1))

    def test_sollmietzins_bemerkung_passt_in_das_feld(self):
        """PostgreSQL lehnt einen Wert über `max_length` ab, SQLite nicht: Die Bemerkung der
        Sollmietzins-Zeile (Begründung + Mietername) muss auf die Feldlänge gekürzt werden."""
        from portfolio.models import Sollmietzins
        v = _index_vertrag(kanton='ZH')
        self._post(v, aktion='versandt', versand_am=HEUTE.isoformat())
        anp = self._entwuerfe(v).get()
        anp.begruendung = 'Anpassung an den Landesindex der Konsumentenpreise. ' * 12
        anp.save()
        notiz = Sollmietzins.objects.get(quelle_anpassung=anp).notiz
        grenze = Sollmietzins._meta.get_field('notiz').max_length
        self.assertLessEqual(len(notiz), grenze)
        self.assertTrue(notiz.startswith('Amtliche Mietzinsanpassung'))
        self.assertTrue(notiz.endswith('…'))

    def test_versand_mit_bestaetigtem_zugang_darf_frueher_wirken_als_ein_entwurf(self):
        """Ein bestätigter Zugang ersetzt den Puffer: Beim Versand zählt das echte Datum, beim
        Entwurf (Versand «heute», Zustellpuffer) ist derselbe Termin noch zu früh."""
        v = _index_vertrag(kanton='ZH')
        # Zugang 26.10. + 30 Tage = 25.11. -> Monatsende 30.11. -> wirksam 1.12.
        self._post(v, aktion='entwurf', wirksam_ab='2026-12-01')
        self.assertEqual(self._entwuerfe(v).count(), 0)
        self._post(v, aktion='versandt', versand_am='2026-10-26', zugang_am='2026-10-26',
                   wirksam_ab='2026-12-01')
        self.assertEqual(self._entwuerfe(v).get().status, 'versandt')

    def test_versand_erfassen_prueft_30_tage_mit_dem_echten_datum(self):
        """Zweite Schicht: `versand_erfassen` lehnt einen zu frühen Termin auch ab, wenn die Ansicht
        umgangen wird (Massenweg, Statusansicht)."""
        from core.services import mietzinsanpassung as ablauf
        from rentals.models import MietzinsAnpassung
        v = _index_vertrag(kanton='ZH')
        anp = MietzinsAnpassung.objects.create(
            vertrag=v, wirksam_ab=date(2026, 12, 1), neuer_netto_mietzins=D('1050.00'),
            alter_netto_mietzins=D('1000.00'), status='entwurf')
        with _heute():
            with self.assertRaises(ValueError) as fehler:
                ablauf.versand_erfassen(anp, date(2026, 10, 27))          # Zugang vermutet 3.11. -> frühestens 1.1.
            self.assertIn('Art. 17 Abs. 3 VMWG', str(fehler.exception))
            anp.refresh_from_db()
            self.assertEqual(anp.status, 'entwurf')
            ablauf.versand_erfassen(anp, date(2026, 10, 27), zugang_am=date(2026, 10, 27))   # Zugang 27.10. -> 26.11. -> 1.12.
        anp.refresh_from_db()
        self.assertEqual(anp.status, 'versandt')

    def test_festmiete_behaelt_die_bisherige_frist(self):
        """Der Index-Zweig lässt den Rest unberührt: Bei einer Festmiete gilt Art. 269d weiter."""
        from core.services import mietzinsanpassung as ablauf
        from rentals.models import MietzinsAnpassung
        v = _index_vertrag(kanton='ZH')
        v.mietzins_modell = 'fest'
        v.save()
        anp = MietzinsAnpassung.objects.create(
            vertrag=v, wirksam_ab=date(2026, 12, 1), neuer_netto_mietzins=D('1050.00'),
            alter_netto_mietzins=D('1000.00'), status='entwurf')
        with _heute():
            fehler = ablauf.fristfehler(anp, date(2026, 10, 27))
        self.assertIn('Art. 269d OR', fehler)

    def test_unbekannter_vertrag_und_fremder_mandant(self):
        """Mandantentrennung: Der Index-Endpunkt eines fremden Vertrags antwortet 404."""
        from ._isolation import MandantenFixture
        a = MandantenFixture('A', '8001', 'Zürich')
        b = MandantenFixture('B', '3001', 'Bern')
        c = Client()
        c.force_login(a.benutzer)
        for url in (f'/neu/mietzins/{b.vertrag.pk}/anpassung/rechnen/',
                    f'/neu/mietzins/{b.vertrag.pk}/anpassung/'):
            self.assertEqual(c.get(url).status_code, 404, url)
        self.assertEqual(c.post(f'/neu/mietzins/{b.vertrag.pk}/anpassung/', {'aktion': 'entwurf'}).status_code, 404)
