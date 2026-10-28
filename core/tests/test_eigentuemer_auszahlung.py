"""Eigentümerauszahlung aus eingegangenem Geld (Etappe 0: FUNK-01, FIN-03) und
die Mandatsabrechnung nach dem Jahresabschluss (FUNK-02).

Vorher: Die Maske nannte «offen (auszahlbar)» auf Ertragsbasis — inklusive nie
bezahlter Mieten (CHF 21'700, Bankkonto bei 0) —, bot das Kautionssperrkonto 1015
als erste Bankwahl an, prüfte keine Deckung, und zwei gleichzeitige Auszahlungen
à 15'000 liessen die Bank auf −30'000 fallen.

Gegenproben stehen im Schlussbericht (je Test eine Zeile).
"""
from datetime import date
from decimal import Decimal

from django.contrib.messages import get_messages
from django.test import Client, TestCase, TransactionTestCase

from core.tests._helfer import _basis_objekte, _team_user, _test_organisation
from core.tests._parallel import NUR_POSTGRES, parallel


def _chf(x):
    return Decimal(str(x))


class _Basis:
    """Gemeinsame Bausteine für TestCase und TransactionTestCase."""

    def aufbau(self):
        from crm.models import Eigentuemer
        from finance.booking import ensure_kontenplan
        self.org = _test_organisation()
        self.benutzer = _team_user('Verwaltung')
        ensure_kontenplan()
        self.md = Eigentuemer.objects.create(firma_oder_name='Eigentum AG', iban='CH9300762011623852957')
        self.lg, self.einheit, self.mieter, self.vertrag = _basis_objekte()
        self.lg.eigentuemer = self.md
        self.lg.save()

    def buche(self, soll, haben, betrag, text='Test', lg=True, datum=date(2026, 3, 1)):
        from finance.booking import buche
        return buche(soll, haben, _chf(betrag), text, datum=datum, liegenschaft=self.lg if lg else None)

    def sollstellung(self, betrag):
        """Fällige Miete: gebucht, aber NICHT bezahlt (1100 an 3000)."""
        return self.buche('1100', '3000', betrag, 'Sollstellung')

    def mieteingang(self, betrag):
        """Bezahlte Miete (Bank an Forderungen)."""
        return self.buche('1020', '1100', betrag, 'Mieteingang')

    def liquiditaet(self):
        from core.services.eigentuemer_kontokorrent import liquiditaet
        return liquiditaet(self.md)

    def auszahlen(self, betrag, konto='1020', **extra):
        c = Client()
        c.force_login(self.benutzer)
        daten = {'betrag': str(betrag), 'konto_nummer': konto, 'datum': '2026-03-15'}
        daten.update(extra)
        antwort = c.post(f'/neu/mandate/{self.md.id}/auszahlung/', daten)
        return antwort, [str(m) for m in get_messages(antwort.wsgi_request)]

    def anzahl_auszahlungen(self):
        from finance.models import EigentuemerAuszahlung
        return EigentuemerAuszahlung.objects.filter(eigentuemer=self.md, status='verbucht').count()

    def saldo(self, nummer):
        from finance.booking import konto, kontosaldo
        return kontosaldo(konto(nummer))


class AuszahlbarTests(_Basis, TestCase):
    """Was als «auszahlbar» gilt — die Liquiditätsbasis."""

    def setUp(self):
        self.aufbau()

    def test_nichts_eingegangen_nichts_auszahlbar(self):
        """FUNK-01: Zehn Mieten à 2'000 fällig, kein Franken bezahlt: Das Kontokorrent
        (Sollbasis) nennt 20'000, auszahlbar ist 0."""
        for _ in range(10):
            self.sollstellung('2000')
        liq = self.liquiditaet()
        self.assertEqual(liq['kontokorrent_offen'], Decimal('20000.00'))
        self.assertEqual(liq['eingegangen'], Decimal('0.00'))
        self.assertEqual(liq['auszahlbar'], Decimal('0.00'))

    def test_maske_zeigt_null_statt_der_sollbasis(self):
        for _ in range(10):
            self.sollstellung('2000')
        c = Client()
        c.force_login(self.benutzer)
        r = c.get(f'/neu/mandate/{self.md.id}/kontokorrent/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['liq']['auszahlbar'], Decimal('0.00'))
        self.assertContains(r, 'Auszahlbar (eingegangene Mittel)')
        self.assertContains(r, 'Zurzeit ist nichts auszahlbar.')
        # Das Betragsfeld ist NICHT mit der Sollbasis (20'000) vorbefüllt.
        self.assertNotContains(r, 'value="20\'000.00"')

    def test_eingegangene_miete_wird_auszahlbar(self):
        for _ in range(10):
            self.sollstellung('2000')
        self.mieteingang('3000')
        liq = self.liquiditaet()
        self.assertEqual(liq['eingegangen'], Decimal('3000.00'))
        self.assertEqual(liq['auszahlbar'], Decimal('3000.00'))

    def test_unbezahlte_rechnung_senkt_ueber_die_ertragsbasis(self):
        """Miete 24'000 bezahlt; eine freigegebene, noch unbezahlte Rechnung über 2'000
        ist Aufwand. Die Liquidität (24'000) sieht sie nicht, die Ertragsbasis (22'000) schon:
        auszahlbar ist das Kleinere."""
        self.sollstellung('24000')
        self.mieteingang('24000')
        self.buche('4000', '2000', '2000', 'Rechnung Handwerker')
        liq = self.liquiditaet()
        self.assertEqual(liq['verfuegbar'], Decimal('24000.00'))
        self.assertEqual(liq['kontokorrent_offen'], Decimal('22000.00'))
        self.assertEqual(liq['auszahlbar'], Decimal('22000.00'))

    def test_bezahlte_rechnung_senkt_die_liquiditaet(self):
        self.sollstellung('24000')
        self.mieteingang('24000')
        self.buche('4000', '2000', '2000', 'Rechnung Handwerker')
        self.buche('2000', '1020', '2000', 'Zahlung Handwerker')
        liq = self.liquiditaet()
        self.assertEqual(liq['bezahlt'], Decimal('2000.00'))
        self.assertEqual(liq['verfuegbar'], Decimal('22000.00'))
        self.assertEqual(liq['auszahlbar'], Decimal('22000.00'))

    def test_kautionen_zaehlen_nicht(self):
        """Kaution einbezahlt (1015 an 2010), freigegeben (1020 an 1015) und an den
        Mieter zurückgezahlt (2010 an 1020) — Geld der Mieter, kein Ertrag."""
        self.sollstellung('1000')
        self.mieteingang('1000')
        self.buche('1015', '2010', '4500', 'Kaution Einzahlung')
        self.buche('1020', '1015', '4500', 'Kaution Sperrkonto freigegeben')
        self.buche('2010', '1020', '4000', 'Kaution Rückzahlung')
        liq = self.liquiditaet()
        self.assertEqual(liq['eingegangen'], Decimal('1000.00'))
        self.assertEqual(liq['bezahlt'], Decimal('0.00'))
        self.assertEqual(liq['auszahlbar'], Decimal('1000.00'))

    def test_ueberzahlung_und_ungeklaertes_zaehlt_erst_nach_zuordnung(self):
        self.sollstellung('1000')
        self.buche('1020', '2030', '300', 'Überzahlung Mieter')        # Mieterguthaben
        self.buche('1020', '1190', '500', 'Ungeklärt', lg=False)      # Fremdeingang
        self.assertEqual(self.liquiditaet()['auszahlbar'], Decimal('0.00'))
        # Zuordnung des Fremdeingangs auf die Miete: ab jetzt eingegangen.
        self.buche('1190', '1100', '500', 'Zuordnung')
        self.assertEqual(self.liquiditaet()['auszahlbar'], Decimal('500.00'))

    def test_abschlussbuchungen_veraendern_die_liquiditaet_nicht(self):
        from core.services.jahresabschluss import buche_jahresabschluss
        self.sollstellung('1000')
        self.mieteingang('1000')
        vorher = self.liquiditaet()['auszahlbar']
        buche_jahresabschluss(2026, liegenschaft=self.lg)
        self.assertEqual(self.liquiditaet()['auszahlbar'], vorher)

    def test_storno_der_zahlung_nimmt_die_liquiditaet_zurueck(self):
        from finance.booking import storniere_buchung
        self.sollstellung('1000')
        zahlung = self.mieteingang('1000')
        self.assertEqual(self.liquiditaet()['auszahlbar'], Decimal('1000.00'))
        storniere_buchung(zahlung)
        self.assertEqual(self.liquiditaet()['auszahlbar'], Decimal('0.00'))

    def test_fremder_eigentuemer_zaehlt_nicht(self):
        """Das Geld einer anderen Liegenschaft (anderer Eigentümer) ist nicht auszahlbar."""
        from crm.models import Eigentuemer
        from portfolio.models import Liegenschaft
        anderer = Eigentuemer.objects.create(firma_oder_name='Andere AG')
        fremd = Liegenschaft.objects.create(strasse='Fremdweg 9', plz='8000', ort='Zürich',
                                            organisation=self.org, eigentuemer=anderer)
        from finance.booking import buche
        buche('1100', '3000', Decimal('5000'), 'Soll fremd', liegenschaft=fremd)
        buche('1020', '1100', Decimal('5000'), 'Eingang fremd', liegenschaft=fremd)
        self.assertEqual(self.liquiditaet()['auszahlbar'], Decimal('0.00'))


class AuszahlenTests(_Basis, TestCase):
    """Die Buchung: nur aus eingegangenem Geld, nie vom Kautionskonto, nur gedeckt."""

    def setUp(self):
        self.aufbau()

    def test_auszahlung_ohne_eingang_wird_abgewiesen(self):
        """FIN-03: vorher wurden 15'000 gebucht und das Bankkonto stand bei −15'000."""
        for _ in range(10):
            self.sollstellung('2000')
        antwort, meldungen = self.auszahlen('15000')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(self.anzahl_auszahlungen(), 0)
        self.assertEqual(self.saldo('1020'), Decimal('0.00'))
        self.assertEqual(self.saldo('2850'), Decimal('0.00'))
        self.assertTrue(any('Auszahlbar' in m for m in meldungen), meldungen)

    def test_auszahlung_bis_zur_obergrenze_geht_darueber_nicht(self):
        self.sollstellung('5000')
        self.mieteingang('3000')
        antwort, _ = self.auszahlen('3000.01')
        self.assertEqual(self.anzahl_auszahlungen(), 0)
        antwort, _ = self.auszahlen('3000.00')
        self.assertEqual(self.anzahl_auszahlungen(), 1)
        self.assertEqual(self.saldo('1020'), Decimal('0.00'))
        self.assertEqual(self.liquiditaet()['auszahlbar'], Decimal('0.00'))
        # Nichts mehr da: die nächste wird abgewiesen.
        self.auszahlen('1.00')
        self.assertEqual(self.anzahl_auszahlungen(), 1)

    def test_kautionssperrkonto_ist_nie_quelle(self):
        """FUNK-01: 1015 stand als erste Wahl in der Liste; per POST liess sich
        `Soll 2850 / Haben 1015` buchen."""
        self.sollstellung('5000')
        self.mieteingang('5000')
        self.buche('1015', '2010', '9000', 'Kaution', lg=False)           # Sperrkonto ist gut gefüllt
        antwort, meldungen = self.auszahlen('1000', konto='1015')
        self.assertEqual(self.anzahl_auszahlungen(), 0)
        self.assertEqual(self.saldo('1015'), Decimal('9000.00'))
        self.assertTrue(any('1015' in m for m in meldungen), meldungen)

    def test_unbekanntes_bankkonto_wird_nicht_still_ersetzt(self):
        self.sollstellung('5000')
        self.mieteingang('5000')
        antwort, meldungen = self.auszahlen('1000', konto='9999')
        self.assertEqual(self.anzahl_auszahlungen(), 0)
        self.assertTrue(any('9999' in m for m in meldungen), meldungen)

    def test_kein_ertragskonto_als_bank(self):
        self.sollstellung('5000')
        self.mieteingang('5000')
        self.auszahlen('1000', konto='3000')
        self.assertEqual(self.anzahl_auszahlungen(), 0)

    def test_deckung_gegen_das_bankkonto(self):
        """Der Eigentümer hätte 5'000 zugut, aber das Bankkonto trägt wegen anderer
        Abflüsse (Fremdgelder, ohne Liegenschaft gebucht) nur 500."""
        self.sollstellung('5000')
        self.mieteingang('5000')
        self.buche('2000', '1020', '4500', 'Abfluss ohne Liegenschaft', lg=False)
        self.assertEqual(self.liquiditaet()['auszahlbar'], Decimal('5000.00'))
        self.assertEqual(self.saldo('1020'), Decimal('500.00'))
        antwort, meldungen = self.auszahlen('1000')
        self.assertEqual(self.anzahl_auszahlungen(), 0)
        self.assertTrue(any('deckt' in m for m in meldungen), meldungen)
        self.auszahlen('500')
        self.assertEqual(self.anzahl_auszahlungen(), 1)

    def test_doppelklick_mit_stand_der_maske(self):
        self.sollstellung('9000')
        self.mieteingang('9000')
        c = Client()
        c.force_login(self.benutzer)
        seite = c.get(f'/neu/mandate/{self.md.id}/kontokorrent/')
        stand = seite.context['auszahlungs_stand']
        self.auszahlen('1000', stand=stand)
        antwort, meldungen = self.auszahlen('1000', stand=stand)
        self.assertEqual(self.anzahl_auszahlungen(), 1)
        self.assertTrue(any('Seite neu laden' in m for m in meldungen), meldungen)

    def test_zweite_echte_auszahlung_mit_frischem_stand_geht(self):
        self.sollstellung('9000')
        self.mieteingang('9000')
        c = Client()
        c.force_login(self.benutzer)
        self.auszahlen('1000', stand=c.get(f'/neu/mandate/{self.md.id}/kontokorrent/').context['auszahlungs_stand'])
        frisch = c.get(f'/neu/mandate/{self.md.id}/kontokorrent/').context['auszahlungs_stand']
        self.auszahlen('1000', stand=frisch)
        self.assertEqual(self.anzahl_auszahlungen(), 2)

    def test_periodensperre_gilt_weiter(self):
        self.sollstellung('5000')
        self.mieteingang('5000')
        self.org.buchung_gesperrt_bis = date(2026, 12, 31)
        self.org.save()
        antwort, meldungen = self.auszahlen('1000')
        self.assertEqual(self.anzahl_auszahlungen(), 0)
        self.assertTrue(any('gesperrt' in m for m in meldungen), meldungen)

    def test_maske_bietet_1015_nicht_an_und_waehlt_1020_vor(self):
        self.sollstellung('5000')
        self.mieteingang('5000')
        c = Client()
        c.force_login(self.benutzer)
        r = c.get(f'/neu/mandate/{self.md.id}/kontokorrent/')
        self.assertNotContains(r, 'value="1015"')
        self.assertContains(r, '<option value="1020" selected>')

    def test_nur_verwaltung_darf_auszahlen(self):
        self.sollstellung('5000')
        self.mieteingang('5000')
        c = Client()
        c.force_login(_team_user('Lesend'))
        antwort = c.post(f'/neu/mandate/{self.md.id}/auszahlung/', {'betrag': '100', 'konto_nummer': '1020'})
        self.assertEqual(antwort.status_code, 403)
        self.assertEqual(self.anzahl_auszahlungen(), 0)

    def test_fremder_mandant_bekommt_404(self):
        from core.tests._isolation import MandantenFixture
        fremd = MandantenFixture('Z', '3000', 'Bern')
        c = Client()
        c.force_login(self.benutzer)
        antwort = c.post(f'/neu/mandate/{fremd.eigentuemer.pk}/auszahlung/', {'betrag': '100', 'konto_nummer': '1020'})
        self.assertEqual(antwort.status_code, 404)


@NUR_POSTGRES
class AuszahlungParallelTests(_Basis, TransactionTestCase):

    def setUp(self):
        self.aufbau()

    def _parallel_auszahlen(self, anzahl, betrag, md_ids=None):
        def lauf(i):
            md = self.md if not md_ids else md_ids[i]
            c = Client()
            c.force_login(self.benutzer)
            antwort = c.post(f'/neu/mandate/{getattr(md, "id", md)}/auszahlung/',
                             {'betrag': str(betrag), 'konto_nummer': '1020', 'datum': '2026-03-15'})
            return antwort.status_code
        return parallel(anzahl, lauf)

    def test_zwei_parallele_auszahlungen_ueberschreiten_die_deckung_nicht(self):
        """FIN-03: vorher beide gebucht, Bank 1020 = −30'000."""
        self.sollstellung('20000')
        self.mieteingang('20000')
        ergebnisse = self._parallel_auszahlen(2, '15000')
        for e in ergebnisse:
            self.assertEqual(e, 302, e)
        self.assertEqual(self.anzahl_auszahlungen(), 1)
        self.assertGreaterEqual(self.saldo('1020'), Decimal('0.00'))
        self.assertEqual(self.saldo('1020'), Decimal('5000.00'))

    def test_zwei_parallele_auszahlungen_im_dienst(self):
        """Dasselbe Szenario ohne Anfrage-Rauschen davor: Beide Threads rufen den Dienst
        im selben Moment auf. Genau einer bucht, der andere wird abgewiesen."""
        from core.services.eigentuemer_kontokorrent import AuszahlungNichtMoeglich, buche_auszahlung
        from core.tenancy import organisation_kontext
        from finance.models import Buchungskonto
        self.sollstellung('20000')
        self.mieteingang('20000')
        bank = Buchungskonto.objects.get(nummer='1020')

        def lauf(i):
            with organisation_kontext(self.org):
                try:
                    buche_auszahlung(self.md, Decimal('15000'), bank=bank, datum=date(2026, 3, 15))
                    return 'gebucht'
                except AuszahlungNichtMoeglich:
                    return 'abgewiesen'
        ergebnisse = parallel(2, lauf)
        self.assertEqual(sorted(ergebnisse), ['abgewiesen', 'gebucht'], ergebnisse)
        self.assertEqual(self.anzahl_auszahlungen(), 1)
        self.assertEqual(self.saldo('1020'), Decimal('5000.00'))

    def test_viele_parallele_auszahlungen_zahlen_hoechstens_den_bestand_aus(self):
        self.sollstellung('10000')
        self.mieteingang('10000')
        self._parallel_auszahlen(8, '3000')
        self.assertEqual(self.anzahl_auszahlungen(), 3)            # 3 x 3'000 <= 10'000 < 4 x 3'000
        self.assertEqual(self.saldo('1020'), Decimal('1000.00'))

    def test_zwei_eigentuemer_teilen_sich_ein_bankkonto(self):
        """Beide Eigentümer haben je 15'000 zugut, das gemeinsame Bankkonto trägt nur
        20'000 (anderer Abfluss ohne Liegenschaft): Es darf nur eine Auszahlung durch."""
        from crm.models import Eigentuemer
        from finance.booking import buche
        from portfolio.models import Liegenschaft
        md_b = Eigentuemer.objects.create(firma_oder_name='Zweite AG')
        lg_b = Liegenschaft.objects.create(strasse='Zweiweg 2', plz='8000', ort='Zürich',
                                           organisation=self.org, eigentuemer=md_b)
        self.sollstellung('15000')
        self.mieteingang('15000')
        buche('1100', '3000', Decimal('15000'), 'Soll B', datum=date(2026, 3, 1), liegenschaft=lg_b)
        buche('1020', '1100', Decimal('15000'), 'Eingang B', datum=date(2026, 3, 1), liegenschaft=lg_b)
        buche('2000', '1020', Decimal('10000'), 'Abfluss ohne Liegenschaft', datum=date(2026, 3, 1))
        self.assertEqual(self.saldo('1020'), Decimal('20000.00'))
        self._parallel_auszahlen(2, '15000', md_ids=[self.md, md_b])
        from finance.models import EigentuemerAuszahlung
        self.assertEqual(EigentuemerAuszahlung.objects.filter(status='verbucht').count(), 1)
        self.assertGreaterEqual(self.saldo('1020'), Decimal('0.00'))


# ======================================================================
# FUNK-02: Mandatsabrechnung nach dem Jahresabschluss
# ======================================================================
class MandatsabrechnungNachAbschlussTests(_Basis, TestCase):
    """Vorher: Ertrag 0, Aufwand 0, Saldo 0 auf Seite und PDF, während das
    Kontokorrent weiter 8'000 nannte."""

    def setUp(self):
        self.aufbau()
        self.buche('1020', '3000', '10000', 'Miete 2026', datum=date(2026, 5, 1))
        self.buche('4000', '1020', '2000', 'Reparatur 2026', datum=date(2026, 6, 1))
        self.client_ = Client()
        self.client_.force_login(self.benutzer)

    def _stand(self):
        from core.services.eigentuemer_kontokorrent import kontokorrent
        seite = self.client_.get(f'/neu/mandate/{self.md.id}/abrechnung/?jahr=2026')
        kk = kontokorrent(self.md, jahr=2026)
        return seite, kk

    def _pdf_text(self):
        import io
        import pdfplumber
        antwort = self.client_.get(f'/neu/mandate/{self.md.id}/abrechnung/?jahr=2026&pdf=1')
        self.assertEqual(antwort['Content-Type'], 'application/pdf')
        with pdfplumber.open(io.BytesIO(antwort.content)) as pdf:
            return '\n'.join(seite.extract_text() or '' for seite in pdf.pages)

    def test_seite_pdf_und_kontokorrent_vor_und_nach_dem_abschluss_identisch(self):
        from core.services.jahresabschluss import buche_jahresabschluss
        seite, kk = self._stand()
        vorher = (seite.context['totals'], kk['ertrag'], kk['aufwand'], kk['ergebnis'])
        pdf_vorher = self._pdf_text()
        self.assertEqual(seite.context['totals']['saldo'], Decimal('8000.00'))
        self.assertIn("10'000.00", pdf_vorher)
        self.assertIn("8'000.00", pdf_vorher)

        n, _ = buche_jahresabschluss(2026, liegenschaft=self.lg)
        self.assertGreater(n, 0, 'Testaufbau: Der Abschluss hat nichts gebucht.')

        seite, kk = self._stand()
        self.assertEqual((seite.context['totals'], kk['ertrag'], kk['aufwand'], kk['ergebnis']), vorher)
        self.assertEqual(seite.context['totals']['ertrag'], Decimal('10000.00'))
        self.assertEqual(seite.context['totals']['aufwand'], Decimal('2000.00'))
        self.assertEqual(seite.context['totals']['saldo'], Decimal('8000.00'))
        pdf_nachher = self._pdf_text()
        self.assertIn("10'000.00", pdf_nachher)
        self.assertIn("8'000.00", pdf_nachher)
        self.assertEqual(pdf_vorher.count("10'000.00"), pdf_nachher.count("10'000.00"))

    def test_zeilen_je_liegenschaft_bleiben_gleich(self):
        from core.services.jahresabschluss import buche_jahresabschluss
        seite, _ = self._stand()
        vorher = [(z['lg'].pk, z['ertrag'], z['aufwand'], z['saldo']) for z in seite.context['zeilen']]
        buche_jahresabschluss(2026, liegenschaft=self.lg)
        seite, _ = self._stand()
        nachher = [(z['lg'].pk, z['ertrag'], z['aufwand'], z['saldo']) for z in seite.context['zeilen']]
        self.assertEqual(vorher, nachher)
        self.assertEqual(nachher[0][1:], (Decimal('10000.00'), Decimal('2000.00'), Decimal('8000.00')))

    def test_auswertung_zeigt_nach_dem_abschluss_denselben_mietertrag(self):
        """Der Zwilling von FUNK-02: `/neu/auswertung/` rechnete mit derselben
        Lücke und zeigte für ein abgeschlossenes Jahr Mietertrag 0."""
        from core.services.jahresabschluss import buche_jahresabschluss
        vorher = self.client_.get('/neu/auswertung/?jahr=2026&typ=mietertrag').context['total']
        self.assertEqual(vorher, Decimal('10000.00'))
        buche_jahresabschluss(2026)
        nachher = self.client_.get('/neu/auswertung/?jahr=2026&typ=mietertrag').context['total']
        self.assertEqual(nachher, vorher)

    def test_auch_nach_ruecknahme_des_abschlusses(self):
        """Der Storno einer Abschlussbuchung beginnt mit «Storno Beleg…» — er darf
        die Abrechnung ebenfalls nicht verändern."""
        from core.services.jahresabschluss import buche_jahresabschluss, nimm_zurueck
        buche_jahresabschluss(2026, liegenschaft=self.lg)
        nimm_zurueck(2026, liegenschaft=self.lg)
        seite, _ = self._stand()
        self.assertEqual(seite.context['totals']['saldo'], Decimal('8000.00'))
