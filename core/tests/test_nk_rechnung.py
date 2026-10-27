"""Rechentests zum Nebenkosten-Wizard (Modul 1, 27.10.2026): die Fehler a–e und E2/E3.

Jede Zahl in den Erwartungen ist VON HAND nachgerechnet und steht mit dem Rechenweg im
Docstring. Gerechnet wird nur in der Engine (`core.utils.billing.berechne_abrechnung`);
diese Tests lesen ihre Ausgabe.

Grundaufbau: zwei Wohnungen, Abrechnungsjahr 2025 (365 Tage), Honorar 0 % (ausser bei e).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from ._helfer import Einheit, Liegenschaft, Mieter, Mietvertrag, _seed_konten, _test_organisation

START, ENDE = date(2025, 1, 1), date(2025, 12, 31)


class _Haus(TestCase):
    honorar = '0'

    def setUp(self):
        from finance.models import AbrechnungsPeriode
        _seed_konten()
        self.org = _test_organisation(nk_honorar_prozent=Decimal(self.honorar))
        self.lg = Liegenschaft.objects.create(organisation=self.org, strasse='Rechenweg 1', plz='8000',
                                              ort='Zürich', versicherungswert=Decimal('1'))
        self.p = AbrechnungsPeriode.objects.create(liegenschaft=self.lg, bezeichnung='NK 2025',
                                                   start_datum=START, ende_datum=ENDE)

    def einheit(self, name, m2, m3=None):
        return Einheit.objects.create(liegenschaft=self.lg, bezeichnung=name, typ='whg',
                                      flaeche_m2=Decimal(m2) if m2 is not None else None,
                                      volumen_m3=Decimal(m3) if m3 is not None else None)

    def vertrag(self, e, name, beginn=date(2024, 1, 1), ende=None, art='akonto', personen=1, **kw):
        m = Mieter.objects.create(typ='person', vorname=name, nachname='Test', strasse='x', plz='8000', ort='Zürich')
        return Mietvertrag.objects.create(mieter=m, einheit=e, beginn=beginn, ende=ende, status='aktiv',
                                          netto_mietzins=Decimal('1000'), nebenkosten=Decimal('0'),
                                          nk_abrechnungsart=art, anzahl_personen=personen, **kw)

    def beleg(self, betrag, kategorie='hauswart', schluessel='m2'):
        from finance.models import NebenkostenBeleg
        return NebenkostenBeleg.objects.create(periode=self.p, text=kategorie, kategorie=kategorie,
                                               verteilschluessel=schluessel, betrag=Decimal(betrag),
                                               datum=date(2025, 6, 1))

    def rechnen(self):
        from core.utils.billing import berechne_abrechnung
        r = berechne_abrechnung(self.p.id)
        self.assertNotIn('error', r)
        return r

    @staticmethod
    def zeile(r, vertrag=None, typ=None):
        for z in r['abrechnungen']:
            if vertrag is not None and z.get('vertrag_id') == vertrag.id:
                return z
            if typ is not None and z['typ'] == typ:
                return z
        raise AssertionError(f'Zeile fehlt: {vertrag or typ} in {r["abrechnungen"]}')


class DirektzahlerTests(_Haus):
    """Fehler a: «direkt» zählte die Tage, erzeugte aber keine Zeile.

    W1 60 m², W2 40 m², Hauswartung 1000 nach m².
    W1 (Akonto)  1000 × 60/100 = 600.00
    W2 (direkt)  1000 × 40/100 = 400.00 → Eigentümerzeile, nicht verschwunden
    Total 1000.00, Differenz 0.00.
    """

    def test_anteil_des_direktzahlers_geht_auf_den_eigentuemer(self):
        w1, w2 = self.einheit('W1', '60'), self.einheit('W2', '40')
        v1, v2 = self.vertrag(w1, 'Akonto'), self.vertrag(w2, 'Direkt', art='direkt')
        self.beleg('1000')
        r = self.rechnen()
        self.assertEqual(self.zeile(r, v1)['kosten_anteil'], Decimal('600.00'))
        eig = self.zeile(r, typ='eigentuemer')
        self.assertEqual(eig['kosten_anteil'], Decimal('400.00'))
        self.assertEqual(eig['bezug_vertrag_id'], v2.id)
        self.assertNotIn('vertrag_id', eig, 'Eine Eigentümerzeile darf nicht verbucht oder versandt werden.')
        self.assertEqual(r['kontroll_summe'], Decimal('1000.00'))
        self.assertEqual(r['differenz'], Decimal('0.00'))


class VolumenTeilweiseTests(_Haus):
    """Fehler b: Fehlt das Volumen nur bei einem Teil, ergaben die Anteile über 100 %.

    W1 60 m² / 180 m³, W2 40 m² ohne m³, Heizung 1000.
    Vorher: Summe m³ = 180, W1 180/180 = 1000.00, W2 (Rückfall auf 40 m²) 40/180 = 222.22 → 122 %.
    Jetzt einheitlich nach Fläche: W1 600.00, W2 400.00 — und eine Warnung nennt W2.
    """

    def test_alle_einheiten_nach_flaeche_und_gewarnt(self):
        w1, w2 = self.einheit('W1', '60', '180'), self.einheit('W2', '40')
        v1, v2 = self.vertrag(w1, 'Eins'), self.vertrag(w2, 'Zwei')
        self.beleg('1000', kategorie='heizung', schluessel='m3')
        r = self.rechnen()
        self.assertEqual(self.zeile(r, v1)['kosten_anteil'], Decimal('600.00'))
        self.assertEqual(self.zeile(r, v2)['kosten_anteil'], Decimal('400.00'))
        self.assertEqual(r['kontroll_summe'], Decimal('1000.00'))
        self.assertEqual(r['volumen_basis'], 'm2')
        warn = [w for w, a in zip(r['warnungen'], r['warnung_arten']) if a == 'volumen']
        self.assertEqual(len(warn), 1)
        self.assertIn('W2', warn[0])

    def test_keller_ohne_jedes_mass_loest_nichts_aus(self):
        """Eine Einheit ohne m² und ohne m³ trägt 0 und kippt die Basis nicht auf m²."""
        w1, w2 = self.einheit('W1', '60', '180'), self.einheit('W2', '40', '120')
        self.einheit('Keller', None)
        v1, _v2 = self.vertrag(w1, 'Eins'), self.vertrag(w2, 'Zwei')
        self.beleg('1000', kategorie='heizung', schluessel='m3')
        r = self.rechnen()
        self.assertEqual(r['volumen_basis'], 'm3')
        self.assertEqual(self.zeile(r, v1)['kosten_anteil'], Decimal('600.00'))
        self.assertNotIn('volumen', r['warnung_arten'])


class AbgrenzungTests(_Haus):
    """Fehler c: Kreditor mit Leistungsperiode 01.07.2024–30.06.2025 (365 Tage), CHF 730.00.

    In 2025 fallen 181 Tage (Jan 31 + Feb 28 + Mär 31 + Apr 30 + Mai 31 + Jun 30).
    Anteil 730 × 181/365 = 362.00. W1 (60 %) 217.20, W2 (40 %) 144.80.
    Vorher zählte die volle Rechnung (730.00).
    """

    def _kreditor(self, betrag='730.00', von=date(2024, 7, 1), bis=date(2025, 6, 30), datum=date(2024, 7, 5)):
        from finance.booking import konto
        from finance.models import KreditorenRechnung
        return KreditorenRechnung.objects.create(
            lieferant='Hauswart Jahresvertrag', betrag=Decimal(betrag), liegenschaft=self.lg,
            is_hnk_relevant=True, konto=konto('4120'), status='bezahlt', datum=datum,
            leistungs_von=von, leistungs_bis=bis)

    def test_anteilig_nach_tagen(self):
        w1, w2 = self.einheit('W1', '60'), self.einheit('W2', '40')
        v1, v2 = self.vertrag(w1, 'Eins'), self.vertrag(w2, 'Zwei')
        self._kreditor()
        r = self.rechnen()
        self.assertEqual(r['total_kosten'], Decimal('362.00'))
        self.assertEqual(self.zeile(r, v1)['kosten_anteil'], Decimal('217.20'))
        self.assertEqual(self.zeile(r, v2)['kosten_anteil'], Decimal('144.80'))
        fibu = [b for b in r['belege_details'] if b['quelle'] == 'FiBu']
        self.assertIn('181/365', fibu[0]['text'])

    def test_ohne_leistungsperiode_bleibt_der_ganze_betrag(self):
        w1 = self.einheit('W1', '60')
        self.vertrag(w1, 'Eins')
        self._kreditor(von=None, bis=None, datum=date(2025, 3, 1))
        self.assertEqual(self.rechnen()['total_kosten'], Decimal('730.00'))


class HeizoelPositionenTests(_Haus):
    """Fehler d: Öl-Rechnung 1000 L, CHF 1300.00 — davon 1200.00 Heizöl (4100, HNK) und
    100.00 Tankrevision (4000, nicht HNK). Bestand Anfang 0, Ende 0.
    Verbrauch = 1200.00 (nicht 1300.00). Nach m³ 180/120: W1 720.00, W2 480.00.
    """

    def test_nur_die_hnk_positionen_fliessen_in_den_bestand(self):
        from finance.booking import konto
        from finance.models import KreditorenRechnung, KreditorPosition
        w1, w2 = self.einheit('W1', '60', '180'), self.einheit('W2', '40', '120')
        v1, v2 = self.vertrag(w1, 'Eins'), self.vertrag(w2, 'Zwei')
        k = KreditorenRechnung.objects.create(lieferant='Öl AG', betrag=Decimal('1300.00'), liegenschaft=self.lg,
                                              is_hnk_relevant=True, status='bezahlt', datum=date(2025, 2, 1),
                                              menge_liter=Decimal('1000'))
        KreditorPosition.objects.create(rechnung=k, konto=konto('4100'), betrag=Decimal('1200.00'), is_hnk_relevant=True)
        KreditorPosition.objects.create(rechnung=k, konto=konto('4000'), betrag=Decimal('100.00'), is_hnk_relevant=False)
        r = self.rechnen()
        self.assertEqual(r['total_kosten'], Decimal('1200.00'))
        self.assertEqual(self.zeile(r, v1)['kosten_anteil'], Decimal('720.00'))
        self.assertEqual(self.zeile(r, v2)['kosten_anteil'], Decimal('480.00'))


class HonorarHeizkostenTests(_Haus):
    """Fehler e: Honorar 10 %, Heizung 1000, Hauswartung 1000 (m²). HKVO, Grundkosten 40 %.
    W1 50 m² / 180 m³ / Verbrauch 300, W2 50 m² / 120 m³ / Verbrauch 700.

    Heiztopf 1000 + 100 Honorar = 1100:
      W1 1100 × (0.4 × 0.6 + 0.6 × 0.3) = 1100 × 0.42 = 462.00
      W2 1100 × (0.4 × 0.4 + 0.6 × 0.7) = 1100 × 0.58 = 638.00
    Flächentopf 1000 + 100 Honorar = 1100 → je 550.00.
    W1 1012.00, W2 1188.00, Total 2200.00.
    Vorher (ganzes Honorar nach m²): W1 420 + 600 = 1020.00, W2 580 + 600 = 1180.00.
    """
    honorar = '10'

    def test_honorar_auf_heizkosten_folgt_der_hkvo(self):
        from portfolio.models import Zaehler, ZaehlerStand
        self.lg.hkvo_aktiv = True
        self.lg.hkvo_grundkosten_prozent = 40
        self.lg.save()
        w1, w2 = self.einheit('W1', '50', '180'), self.einheit('W2', '50', '120')
        v1, v2 = self.vertrag(w1, 'Eins'), self.vertrag(w2, 'Zwei')
        for e, verbrauch in ((w1, 300), (w2, 700)):
            z = Zaehler.objects.create(einheit=e, typ='Wärmezähler', zaehler_nummer=e.bezeichnung)
            ZaehlerStand.objects.create(zaehler=z, datum=START, wert=Decimal('1000'))
            ZaehlerStand.objects.create(zaehler=z, datum=ENDE, wert=Decimal(1000 + verbrauch))
        self.beleg('1000', kategorie='heizung', schluessel='m3')
        self.beleg('1000')
        r = self.rechnen()
        self.assertTrue(r['hkvo_angewendet'])
        self.assertEqual(r['total_kosten'], Decimal('2200.00'))
        self.assertEqual(self.zeile(r, v1)['kosten_anteil'], Decimal('1012.00'))
        self.assertEqual(self.zeile(r, v2)['kosten_anteil'], Decimal('1188.00'))
        honorar = [b for b in r['belege_details'] if b['kategorie'] == 'Verwaltung']
        self.assertEqual(sorted(b['betrag'] for b in honorar), [Decimal('100.00'), Decimal('100.00')])


class ZwischenstandTests(_Haus):
    """HKVO mit Mieterwechsel in W2 am 01.05.2025. Heizung 1000, Grundkosten 40 %.
    W1 180 m³ / Verbrauch 300. W2 120 m³: 2000 → 2500 (30.04., Zwischenstand) → 2700.

    W2: Grund 1000 × 0.4 × 0.4 = 160, Verbrauch 1000 × 0.6 × 700/1000 = 420.
    Heizgradtage Jan–Apr 21 + 18 + 15 + 10 = 64 %.
      A (bis 30.04.)  160 × 0.64 + 420 × 500/700 = 102.40 + 300.00 = 402.40
      B (ab 01.05.)   160 × 0.36 + 420 × 200/700 =  57.60 + 120.00 = 177.60
    Ohne Zwischenstand wie bisher nach Heizgradtagen: A 580 × 0.64 = 371.20, B 580 × 0.36 = 208.80.
    W1 1000 × (0.4 × 0.6 + 0.6 × 0.3) = 420.00.
    """

    def _aufbau(self, mit_zwischenstand):
        from portfolio.models import Zaehler, ZaehlerStand
        self.lg.hkvo_aktiv = True
        self.lg.hkvo_grundkosten_prozent = 40
        self.lg.save()
        w1, w2 = self.einheit('W1', '60', '180'), self.einheit('W2', '40', '120')
        self.v1 = self.vertrag(w1, 'Eins')
        self.va = self.vertrag(w2, 'Alt', ende=date(2025, 4, 30))
        self.vb = self.vertrag(w2, 'Neu', beginn=date(2025, 5, 1))
        z1 = Zaehler.objects.create(einheit=w1, typ='Wärmezähler', zaehler_nummer='W1')
        ZaehlerStand.objects.create(zaehler=z1, datum=START, wert=Decimal('1000'))
        ZaehlerStand.objects.create(zaehler=z1, datum=ENDE, wert=Decimal('1300'))
        z2 = Zaehler.objects.create(einheit=w2, typ='Wärmezähler', zaehler_nummer='W2')
        ZaehlerStand.objects.create(zaehler=z2, datum=START, wert=Decimal('2000'), art='anfang')
        if mit_zwischenstand:
            ZaehlerStand.objects.create(zaehler=z2, datum=date(2025, 4, 30), wert=Decimal('2500'), art='zwischen')
        ZaehlerStand.objects.create(zaehler=z2, datum=ENDE, wert=Decimal('2700'), art='ende')
        self.beleg('1000', kategorie='heizung', schluessel='m3')
        return self.rechnen()

    def test_mit_zwischenstand_nach_zaehler(self):
        r = self._aufbau(True)
        a, b = self.zeile(r, self.va), self.zeile(r, self.vb)
        self.assertEqual(a['kosten_anteil'], Decimal('402.40'))
        self.assertEqual(b['kosten_anteil'], Decimal('177.60'))
        self.assertEqual(self.zeile(r, self.v1)['kosten_anteil'], Decimal('420.00'))
        self.assertEqual((a['heiz_basis'], b['heiz_basis']), ('zaehler', 'zaehler'))
        self.assertEqual(r['hinweise'], [])

    def test_ohne_zwischenstand_wie_bisher_und_gekennzeichnet(self):
        r = self._aufbau(False)
        a, b = self.zeile(r, self.va), self.zeile(r, self.vb)
        self.assertEqual(a['kosten_anteil'], Decimal('371.20'))
        self.assertEqual(b['kosten_anteil'], Decimal('208.80'))
        self.assertEqual((a['heiz_basis'], b['heiz_basis']), ('heizgradtage', 'heizgradtage'))
        self.assertTrue(any('W2' in h for h in r['hinweise']), r['hinweise'])


class AusgeschlosseneKostenartTests(_Haus):
    """E2: W1 schliesst «Lift» aus. Lift 1000 und Hauswartung 500, beide nach m² 60/40.
    W1   Hauswartung 500 × 0.6 = 300.00 (Lift trägt er nicht)
    Eigentümer (für W1) Lift 1000 × 0.6 = 600.00
    W2   Lift 400.00 + Hauswartung 200.00 = 600.00
    Total 1500.00.
    """

    def test_ausgeschlossene_kostenart_geht_auf_den_eigentuemer(self):
        w1, w2 = self.einheit('W1', '60'), self.einheit('W2', '40')
        v1 = self.vertrag(w1, 'Eins', ausgeschlossene_kostenarten=['lift'])
        v2 = self.vertrag(w2, 'Zwei')
        self.beleg('1000', kategorie='lift')
        self.beleg('500')
        r = self.rechnen()
        z1 = self.zeile(r, v1)
        self.assertEqual(z1['kosten_anteil'], Decimal('300.00'))
        self.assertEqual(z1['aufschluesselung'], [{'kostenart': 'hauswartung', 'betrag': Decimal('300.00')}])
        self.assertEqual(z1['ausgeschlossen'], ['lift'])
        eig = self.zeile(r, typ='eigentuemer')
        self.assertEqual(eig['kosten_anteil'], Decimal('600.00'))
        self.assertIn('lift', eig['info'])
        self.assertEqual(self.zeile(r, v2)['kosten_anteil'], Decimal('600.00'))
        self.assertEqual(r['kontroll_summe'], Decimal('1500.00'))


class LeerstandPersonenTests(_Haus):
    """E3: Kehricht 1000 nach Personen. W1 ganzjährig 2 Personen (730 Personentage),
    W2 4 Personen bis 30.06. (181 Tage = 724 Personentage), ab 01.07. leer (184 Tage).

    «keine» (bisher): Total 1454 Personentage.
      W1 1000 × 730/1454 = 502.06, W2 1000 × 724/1454 = 497.94, Leerstand 0.
    «durchschnitt»: Belegung Ø 1454/546; Leerstand 184 × 1454/546 Personentage;
    Total 1454 × 730/546.
      W1 1000 × 546/1454 = 375.52
      W2 1000 × 724 × 546 / (1454 × 730) = 372.43
      Leerstand 1000 × 184/730 = 252.05            Summe 1000.00
    """

    def _aufbau(self, modus):
        self.p.leerstand_personen = modus
        self.p.save()
        w1, w2 = self.einheit('W1', '60'), self.einheit('W2', '40')
        self.v1 = self.vertrag(w1, 'Eins', personen=2)
        self.v2 = self.vertrag(w2, 'Zwei', personen=4, ende=date(2025, 6, 30))
        self.beleg('1000', kategorie='kehricht', schluessel='personen')
        return self.rechnen()

    def test_keine_wie_bisher(self):
        r = self._aufbau('keine')
        self.assertEqual(self.zeile(r, self.v1)['kosten_anteil'], Decimal('502.06'))
        self.assertEqual(self.zeile(r, self.v2)['kosten_anteil'], Decimal('497.94'))
        self.assertFalse([z for z in r['abrechnungen'] if z['typ'] == 'leerstand'])
        self.assertEqual(r['personen_leer_tage'], 184)

    def test_durchschnitt_laesst_den_leerstand_tragen(self):
        r = self._aufbau('durchschnitt')
        self.assertEqual(self.zeile(r, self.v1)['kosten_anteil'], Decimal('375.52'))
        self.assertEqual(self.zeile(r, self.v2)['kosten_anteil'], Decimal('372.43'))
        self.assertEqual(self.zeile(r, typ='leerstand')['kosten_anteil'], Decimal('252.05'))
        self.assertEqual(r['kontroll_summe'], Decimal('1000.00'))
        self.assertEqual(r['leerstand_personen'], 'durchschnitt')


class AufschluesselungTests(_Haus):
    """Die Aufschlüsselung einer Zeile summiert sich auf ihren Kostenanteil, auch wenn
    gerundet wird: 100.00 Hauswartung + 100.00 Lift auf drei gleiche Einheiten."""

    def test_summe_der_positionen_ist_der_kostenanteil(self):
        for i in range(3):
            self.vertrag(self.einheit(f'W{i}', '50'), f'M{i}')
        self.beleg('100.00')
        self.beleg('100.00', kategorie='lift')
        r = self.rechnen()
        for z in r['abrechnungen']:
            self.assertEqual(sum((x['betrag'] for x in z['aufschluesselung']), Decimal('0')), z['kosten_anteil'])
