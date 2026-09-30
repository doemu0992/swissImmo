"""Stresstest 30.09.2026: Heiz- und Nebenkostenabrechnung im komplexen Szenario.

Liegenschaft mit drei Wohnungen, Abrechnungsjahr 2025 (365 Tage):

  W1  ganzes Jahr vermietet
  W2  Mieterwechsel am 15. Mai (untermonatig): Mieter A bis 14.05., Mieter B ab 15.05.
  W3  seit September leer (Mieter bis 31.08.)

Verteilschlüssel: Heizung nach m³ (mit Heizgradtagen), Wasser nach m²,
Hauswartung pauschal je Wohnung. Das Akonto stammt aus der laufenden
Sollstellung, also aus dem, was den Mietern tatsächlich gestellt wurde.

Die erwarteten Werte stehen NICHT im Test als Zahlen, sondern werden hier
unabhängig von der Engine in exakten Brüchen (`Fraction`) hergeleitet. Ein
Test, der die Engine gegen ihre eigene Formel prüft, würde jeden Fehler
mitrechnen.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

from django.test import TestCase

from ._helfer import _seed_konten, _test_organisation

JAHR = 2025
TAGE_JAHR = 365
RAPPEN = Decimal('0.01')

# Schweizer Heizgradtage-Verteilung in Prozent je Monat (wie in core/utils/billing.py)
HGT_PROZENT = {1: 21, 2: 18, 3: 15, 4: 10, 5: 5, 6: 0, 7: 0, 8: 0, 9: 3, 10: 8, 11: 10, 12: 10}


def hgt(von, bis):
    """Anteil der Jahres-Heizgradtage im Zeitraum, tagesgenau, exakt."""
    summe, tag = Fraction(0), von
    while tag <= bis:
        dim = calendar.monthrange(tag.year, tag.month)[1]
        summe += Fraction(HGT_PROZENT[tag.month], dim)
        tag += timedelta(days=1)
    return summe / 100


def tage(von, bis):
    return (bis - von).days + 1


def cents(bruch):
    """Kaufmännisch auf den Rappen (Referenz; die Engine verteilt Restrappen zusätzlich)."""
    return Decimal(bruch.numerator) / Decimal(bruch.denominator)


class SzenarioHelfer:
    """Aufbau und Referenzrechnung, geteilt von den Testklassen unten."""

    START, ENDE = date(JAHR, 1, 1), date(JAHR, 12, 31)
    WECHSEL = date(JAHR, 5, 15)
    LEER_AB = date(JAHR, 9, 1)

    FLAECHE = {'W1': Fraction(80), 'W2': Fraction(60), 'W3': Fraction(100)}
    VOLUMEN = {'W1': Fraction(240), 'W2': Fraction(180), 'W3': Fraction(300)}
    HEIZUNG, WASSER, HAUSWART = Decimal('12000.00'), Decimal('2400.00'), Decimal('900.00')

    def _aufbauen(self, honorar='0', heizung_beleg=True):
        _seed_konten()
        from crm.models import Mieter
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag
        from core.services.automation import run_sollstellung

        _test_organisation(nk_honorar_prozent=Decimal(honorar))
        self.lg = Liegenschaft.objects.create(
            organisation=_test_organisation(), strasse='Stresstest 3', plz='4500', ort='SO',
            versicherungswert=Decimal('1'))
        self.einheit = {
            name: Einheit.objects.create(
                liegenschaft=self.lg, bezeichnung=name, typ='whg',
                flaeche_m2=Decimal(int(self.FLAECHE[name])), volumen_m3=Decimal(int(self.VOLUMEN[name])))
            for name in ('W1', 'W2', 'W3')
        }

        def vertrag(einheit, name, beginn, ende, nk, status):
            m = Mieter.objects.create(typ='person', vorname=name, nachname='Test',
                                      strasse='W', plz='4500', ort='SO')
            return Mietvertrag.objects.create(
                mieter=m, einheit=self.einheit[einheit], beginn=beginn, ende=ende, status=status,
                netto_mietzins=Decimal('1500'), nebenkosten=Decimal(nk), nk_abrechnungsart='akonto')

        alt = date(2024, 1, 1)
        self.v1 = vertrag('W1', 'Eins', alt, None, '250', 'aktiv')
        self.v2a = vertrag('W2', 'ZweiA', alt, self.WECHSEL - timedelta(days=1), '150', 'gekuendigt')
        self.v2b = vertrag('W2', 'ZweiB', self.WECHSEL, None, '180', 'aktiv')
        self.v3 = vertrag('W3', 'Drei', alt, self.LEER_AB - timedelta(days=1), '300', 'gekuendigt')

        # Das Jahr über lief die Sollstellung, solange die Verträge aktiv waren.
        for monat in range(1, 13):
            run_sollstellung(JAHR, monat)
        # Nach dem Auszug werden die Verträge archiviert.
        self.v2a.status = 'archiviert'; self.v2a.save()
        self.v3.status = 'archiviert'; self.v3.save()

        self.periode = AbrechnungsPeriode.objects.create(
            liegenschaft=self.lg, bezeichnung='NK 2025', start_datum=self.START, ende_datum=self.ENDE)
        for text, betrag, kat, schluessel in [
            *([('Heizöl/Wärme', self.HEIZUNG, 'heizung', 'm3')] if heizung_beleg else []),
            ('Wasser/Abwasser', self.WASSER, 'wasser', 'm2'),
            ('Hauswartung', self.HAUSWART, 'hauswart', 'einheit'),
        ]:
            NebenkostenBeleg.objects.create(periode=self.periode, text=text, betrag=betrag,
                                            kategorie=kat, verteilschluessel=schluessel,
                                            datum=date(JAHR, 6, 30))

    def _engine(self):
        from core.utils.billing import berechne_abrechnung
        return berechne_abrechnung(self.periode.id)

    @staticmethod
    def _zeile(r, vertrag):
        return next(z for z in r['abrechnungen'] if z.get('vertrag_id') == vertrag.id)

    def _erwartet(self, einheit, von, bis, honorar=Fraction(0)):
        """Kostenanteil einer Einheit im Zeitraum, exakt (ohne Rundung)."""
        tot_m2, tot_m3 = sum(self.FLAECHE.values()), sum(self.VOLUMEN.values())
        heizung = Fraction(self.HEIZUNG) * self.VOLUMEN[einheit] / tot_m3 * hgt(von, bis) / hgt(self.START, self.ENDE)
        wasser_pool = Fraction(self.WASSER) + (Fraction(self.HEIZUNG + self.WASSER + self.HAUSWART) * honorar)
        wasser = wasser_pool * self.FLAECHE[einheit] / tot_m2 * tage(von, bis) / TAGE_JAHR
        hauswart = Fraction(self.HAUSWART) / 3 * tage(von, bis) / TAGE_JAHR
        return heizung + wasser + hauswart



class NebenkostenSzenarioTests(SzenarioHelfer, TestCase):

    # ------------------------------------------------------------------

    def test_gesamtsumme_geht_auf_den_rappen_auf(self):
        self._aufbauen()
        r = self._engine()
        self.assertEqual(r['total_kosten'], Decimal('15300.00'))
        summe = sum((z['kosten_anteil'] for z in r['abrechnungen']), Decimal('0.00'))
        self.assertEqual(summe, Decimal('15300.00'),
                         'Mieter + Eigentümer müssen zusammen genau die Gesamtkosten ergeben.')
        self.assertEqual(r['differenz'], Decimal('0.00'))
        self.assertEqual(r['warnungen'], [])

    def test_leerstand_geht_zu_lasten_des_eigentuemers(self):
        """W3 steht seit September leer: Die Kosten ab 1.9. trägt der Eigentümer,
        mit Heizgradtagen für die Heizung (Sep–Dez = 31 % der Jahres-HGT)."""
        self._aufbauen()
        r = self._engine()
        leer = [z for z in r['abrechnungen'] if z['typ'] == 'leerstand']
        self.assertEqual([z['einheit'] for z in leer], ['W3'], 'Nur W3 hat Leerstand.')
        erwartet = self._erwartet('W3', self.LEER_AB, self.ENDE)
        self.assertLessEqual(abs(leer[0]['kosten_anteil'] - cents(erwartet)), RAPPEN)
        # Der Eigentümer zahlt ohne Akonto: Kosten = Saldo, als Nachzahlung ausgewiesen.
        self.assertEqual(leer[0]['akonto'], Decimal('0.00'))
        self.assertEqual(leer[0]['saldo'], leer[0]['kosten_anteil'])
        self.assertTrue(leer[0]['nachzahlung'])

    def test_mieterwechsel_wird_taggenau_abgerechnet(self):
        """15. Mai: Mieter A hat 134 Tage (1.1.–14.5.), Mieter B 231 Tage (15.5.–31.12.).
        Heizung nach Heizgradtagen, nicht nach Kalendertagen: Der Mai zählt 5 %,
        verteilt auf 31 Tage."""
        self._aufbauen()
        r = self._engine()
        a, b = self._zeile(r, self.v2a), self._zeile(r, self.v2b)
        self.assertEqual((a['von'], a['bis']), ('01.01.25', '14.05.25'))
        self.assertEqual((b['von'], b['bis']), ('15.05.25', '31.12.25'))
        ende_a = self.WECHSEL - timedelta(days=1)
        for zeile, erwartet in [(a, self._erwartet('W2', self.START, ende_a)),
                                (b, self._erwartet('W2', self.WECHSEL, self.ENDE))]:
            self.assertLessEqual(abs(zeile['kosten_anteil'] - cents(erwartet)), RAPPEN, zeile['name'])
        # Beide zusammen sind genau die ganze Wohnung W2 — kein Tag doppelt, keiner fehlt.
        self.assertLessEqual(
            abs(a['kosten_anteil'] + b['kosten_anteil'] - cents(self._erwartet('W2', self.START, self.ENDE))),
            RAPPEN)
        self.assertFalse([z for z in r['abrechnungen'] if z['typ'] == 'leerstand' and z['einheit'] == 'W2'],
                         'Im Wechselmonat entsteht kein Leerstand.')

    def test_ganzjahresmieter_traegt_seinen_vollen_anteil(self):
        self._aufbauen()
        z = self._zeile(self._engine(), self.v1)
        self.assertLessEqual(abs(z['kosten_anteil'] - cents(self._erwartet('W1', self.START, self.ENDE))), RAPPEN)

    def test_akonto_wird_abgezogen_wie_gestellt(self):
        """Gestellt (Sollstellung, untermonatig anteilig):
           W1  12 × 250                       = 3000.00
           W2a 4 × 150 + 150 × 14/31 (67.74)  =  667.74
           W2b 180 × 17/31 (98.71) + 7 × 180  = 1358.71
           W3  8 × 300                        = 2400.00"""
        self._aufbauen()
        r = self._engine()
        erwartet_akonto = {
            self.v1: Decimal('3000.00'), self.v2a: Decimal('667.74'),
            self.v2b: Decimal('1358.71'), self.v3: Decimal('2400.00'),
        }
        for v, akonto in erwartet_akonto.items():
            z = self._zeile(r, v)
            self.assertEqual(z['akonto'], akonto, f"Akonto {z['name']}")
            self.assertEqual(z['saldo'], (z['kosten_anteil'] - akonto).quantize(RAPPEN), f"Saldo {z['name']}")
            self.assertEqual(z['nachzahlung'], z['saldo'] > 0)

    def test_mit_verwaltungshonorar_bleibt_alles_auf_den_rappen_genau(self):
        """3 % Honorar auf 15'300 = 459.00; es kommt in den Flächen-Pool (m²)."""
        self._aufbauen(honorar='3')
        r = self._engine()
        self.assertEqual(r['total_kosten'], Decimal('15759.00'))
        summe = sum((z['kosten_anteil'] for z in r['abrechnungen']), Decimal('0.00'))
        self.assertEqual(summe, Decimal('15759.00'))
        z = self._zeile(r, self.v1)
        erwartet = self._erwartet('W1', self.START, self.ENDE, honorar=Fraction(3, 100))
        self.assertLessEqual(abs(z['kosten_anteil'] - cents(erwartet)), RAPPEN)

    def test_akonto_ohne_sollstellung_rechnet_monatlich_statt_mit_jahresformel(self):
        """Altbestand ohne Mietenlauf: Das Akonto ist eine Monatsgrösse. Die frühere
        Formel `nk × 12 / 365 × Tage` gab dem Vormieter 660.82 statt 667.74,
        dem Nachmieter 1367.01 statt 1358.71 und dem Mieter aus W3 2396.71 statt 2400.00."""
        from unittest import mock
        with mock.patch('core.services.automation.run_sollstellung', lambda *a, **k: 0):
            self._aufbauen()
        r = self._engine()
        for v, akonto in {self.v1: '3000.00', self.v2a: '667.74',
                          self.v2b: '1358.71', self.v3: '2400.00'}.items():
            self.assertEqual(self._zeile(r, v)['akonto'], Decimal(akonto), self._zeile(r, v)['name'])


class HeizkostenOelUndHkvoTests(SzenarioHelfer, TestCase):
    """Dasselbe Haus, die Heizung aber aus der Öl-Bestandesrechnung und nach HKVO.

    Öl: Anfangsbestand 4000 l zu CHF 3600, Zukauf 6000 l zu CHF 6600 (Kreditor),
    Endbestand 2500 l. Gewogener Preis (3600 + 6600) / 10000 = 1.02 je Liter,
    Endbestand 2500 × 1.02 = 2550, effektiver Verbrauch 10200 − 2550 = 7650.
    """

    OEL_KOSTEN = Fraction(7650)

    def _oel_aufbauen(self, honorar='0', endbestand='2500'):
        self._aufbauen(honorar=honorar, heizung_beleg=False)
        from finance.models import KreditorenRechnung
        KreditorenRechnung.objects.create(
            liegenschaft=self.lg, lieferant='Oel AG', is_hnk_relevant=True, status='bezahlt',
            menge_liter=Decimal('6000'), betrag=Decimal('6600.00'), datum=date(JAHR, 3, 10))
        self.periode.anfangsbestand_liter = Decimal('4000')
        self.periode.anfangsbestand_chf = Decimal('3600.00')
        self.periode.endbestand_liter = Decimal(endbestand)
        self.periode.save()

    def _hkvo_aufbauen(self, verbrauch):
        from portfolio.models import Zaehler, ZaehlerStand
        self.lg.hkvo_aktiv = True
        self.lg.hkvo_grundkosten_prozent = 40
        self.lg.save()
        for name, menge in verbrauch.items():
            z = Zaehler.objects.create(einheit=self.einheit[name], typ='Wärmezähler', zaehler_nummer=name)
            ZaehlerStand.objects.create(zaehler=z, datum=self.START, wert=Decimal('1000'))
            ZaehlerStand.objects.create(zaehler=z, datum=self.ENDE, wert=Decimal('1000') + Decimal(menge))

    def _heizung_erwartet(self, einheit, von, bis, pool, verbrauch=None):
        tot_m3 = sum(self.VOLUMEN.values())
        zeit = hgt(von, bis) / hgt(self.START, self.ENDE)
        if verbrauch is None:
            return pool * self.VOLUMEN[einheit] / tot_m3 * zeit
        grund = pool * Fraction(2, 5) * self.VOLUMEN[einheit] / tot_m3
        var = pool * Fraction(3, 5) * Fraction(verbrauch[einheit]) / sum(map(Fraction, verbrauch.values()))
        return (grund + var) * zeit

    def _nicht_heizung(self, einheit, von, bis):
        wasser = Fraction(self.WASSER) * self.FLAECHE[einheit] / sum(self.FLAECHE.values())
        hauswart = Fraction(self.HAUSWART) / 3
        return (wasser + hauswart) * tage(von, bis) / TAGE_JAHR

    # --- Öl ---------------------------------------------------------

    def test_oel_bestandesrechnung_geht_mit_gewogenem_preis_auf(self):
        self._oel_aufbauen()
        r = self._engine()
        oel = next(b for b in r['belege_details'] if b['quelle'] == 'Bestand')
        self.assertEqual(oel['betrag'], Decimal('7650.00'))
        self.assertEqual(r['total_kosten'], Decimal('10950.00'))     # 7650 + 2400 + 900
        summe = sum((z['kosten_anteil'] for z in r['abrechnungen']), Decimal('0.00'))
        self.assertEqual(summe, Decimal('10950.00'))
        self.assertEqual(r['differenz'], Decimal('0.00'))

    def test_oel_im_mieterwechsel_und_leerstand_taggenau(self):
        """Öl-Verbrauch wird wie jede Heizung nach m³ und Heizgradtagen verteilt:
        Wechsel am 15.5., Leerstand W3 ab 1.9. zu Lasten des Eigentümers."""
        self._oel_aufbauen()
        r = self._engine()
        vor, nach = self.WECHSEL - timedelta(days=1), self.WECHSEL
        fall = [
            (self._zeile(r, self.v1), 'W1', self.START, self.ENDE),
            (self._zeile(r, self.v2a), 'W2', self.START, vor),
            (self._zeile(r, self.v2b), 'W2', nach, self.ENDE),
            (self._zeile(r, self.v3), 'W3', self.START, self.LEER_AB - timedelta(days=1)),
            (next(z for z in r['abrechnungen'] if z['typ'] == 'leerstand'), 'W3', self.LEER_AB, self.ENDE),
        ]
        for zeile, einheit, von, bis in fall:
            erwartet = self._heizung_erwartet(einheit, von, bis, self.OEL_KOSTEN) + self._nicht_heizung(einheit, von, bis)
            self.assertLessEqual(abs(zeile['kosten_anteil'] - cents(erwartet)), RAPPEN, f"{zeile['name']} {einheit}")

    def test_oel_mit_honorar_summiert_sich_auf_den_rappen(self):
        self._oel_aufbauen(honorar='3')
        r = self._engine()
        self.assertEqual(r['total_kosten'], Decimal('11278.50'))     # 10950 × 1.03
        summe = sum((z['kosten_anteil'] for z in r['abrechnungen']), Decimal('0.00'))
        self.assertEqual(summe, Decimal('11278.50'))

    def test_endbestand_ueber_dem_vorrat_wird_gemeldet_statt_verschluckt(self):
        """Mehr Öl im Tank als je da war ist ein Erfassungsfehler. Die Engine liess
        den Öl-Posten stumm weg und wies eine Abrechnung ohne Heizkosten aus."""
        self._oel_aufbauen(endbestand='12000')
        r = self._engine()
        self.assertTrue(any('Endbestand' in w for w in r['warnungen']), r['warnungen'])

    # --- HKVO -------------------------------------------------------

    def test_hkvo_grund_und_verbrauchskosten_je_einheit(self):
        verbrauch = {'W1': '5000', 'W2': '3000', 'W3': '2000'}
        self._aufbauen()
        self._hkvo_aufbauen(verbrauch)
        r = self._engine()
        self.assertTrue(r['hkvo_angewendet'])
        pool = Fraction(self.HEIZUNG)
        vor = self.WECHSEL - timedelta(days=1)
        for zeile, einheit, von, bis in [
            (self._zeile(r, self.v1), 'W1', self.START, self.ENDE),
            (self._zeile(r, self.v2a), 'W2', self.START, vor),
            (self._zeile(r, self.v2b), 'W2', self.WECHSEL, self.ENDE),
            (next(z for z in r['abrechnungen'] if z['typ'] == 'leerstand'), 'W3', self.LEER_AB, self.ENDE),
        ]:
            erwartet = self._heizung_erwartet(einheit, von, bis, pool, verbrauch) + self._nicht_heizung(einheit, von, bis)
            self.assertLessEqual(abs(zeile['kosten_anteil'] - cents(erwartet)), RAPPEN, f"{zeile['name']} {einheit}")
        summe = sum((z['kosten_anteil'] for z in r['abrechnungen']), Decimal('0.00'))
        self.assertEqual(summe, Decimal('15300.00'))

    def test_hkvo_ohne_zaehler_faellt_auf_m3_zurueck_und_sagt_es(self):
        """HKVO eingeschaltet, aber keine verwertbaren Zählerstände: Die Kosten
        verschwinden nicht, und die Abrechnung meldet, dass HKVO NICHT angewendet wurde."""
        self._aufbauen()
        self.lg.hkvo_aktiv = True; self.lg.save()
        r = self._engine()
        self.assertFalse(r['hkvo_angewendet'])
        self.assertEqual(sum((z['kosten_anteil'] for z in r['abrechnungen']), Decimal('0.00')),
                         Decimal('15300.00'))
        self.assertTrue(any('HKVO' in w or 'Zähler' in w for w in r['warnungen']), r['warnungen'])

    def test_hkvo_einheit_ohne_zaehler_wird_gemeldet(self):
        """W3 hat keinen Zähler: Ihr Verbrauchsanteil ist 0, die Kosten fallen auf die
        anderen. Das gehört in die Warnungen, nicht in die Stille."""
        self._aufbauen()
        self._hkvo_aufbauen({'W1': '5000', 'W2': '3000'})
        r = self._engine()
        self.assertTrue(any('W3' in w for w in r['warnungen']), r['warnungen'])
        self.assertEqual(sum((z['kosten_anteil'] for z in r['abrechnungen']), Decimal('0.00')),
                         Decimal('15300.00'))
