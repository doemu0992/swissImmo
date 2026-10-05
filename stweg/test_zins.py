"""Zins-Rechner (Kontokorrent) und Tilgungs-Wasserfall (Art. 85 Abs. 1 OR)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from stweg import hauptbuch, inkasso, integritaet, vorgaben, zins
from stweg.models import StwegAkonto
from stweg.test_budget import haus_mit_eigentuemern
from stweg.test_inkasso import jahr_budget

D = Decimal


def kapital(stand, jahr_monat_tag):
    return [c for c in stand if c['art'] == 'akonto' and c['datum'] == jahr_monat_tag][0]


class ZinsRechnerTests(TestCase):
    """Bruno (200/1000) zahlt je Quartal 1000.00: Budget 20'000, Raten am 1.1., 1.4., 1.7., 1.10."""

    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        jahr_budget(self.lg, 2026, total=20000)
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'}, bestaetigen=True)

    def _zahle(self, betrag, datum, **kw):
        return hauptbuch.zahlung_erfassen(self.b, D(betrag), datum, **kw)

    def test_1000_nach_60_tagen_der_zins_bleibt_als_forderung_stehen(self):
        z = self._zahle('1000', date(2026, 3, 2))                    # 1.1. + 60 Tage
        self.assertEqual((z.an_kosten, z.an_zins, z.kapital), (D('0'), D('8.22'), D('991.78')))
        stand = inkasso.forderungen(self.b, date(2026, 3, 2))
        zinsschuld = [c for c in stand if c['art'] == 'zins']
        self.assertEqual(len(zinsschuld), 1)                         # eigene Forderung …
        self.assertEqual((zinsschuld[0]['betrag'], zinsschuld[0]['bezahlt'], zinsschuld[0]['offen']),
                         (D('8.22'), D('8.22'), D('0.00')))          # … 1000 × 5 % × 60/365 = 8.2192 → 8.22
        self.assertEqual(kapital(stand, date(2026, 1, 1))['offen'], D('8.22'))   # Art. 85: Zins zuerst, Kapital bleibt

    def test_wasserfall_zuerst_zins_dann_kapital(self):
        z = self._zahle('5.00', date(2026, 3, 2))                    # weniger als der Zins von 8.22
        self.assertEqual((z.an_zins, z.kapital), (D('5.00'), D('0.00')))
        stand = inkasso.forderungen(self.b, date(2026, 3, 2))
        self.assertEqual(kapital(stand, date(2026, 1, 1))['offen'], D('1000.00'))      # Kapital unangetastet
        self.assertEqual([c['offen'] for c in stand if c['art'] == 'zins'], [D('3.22')])

    def test_kein_zins_auf_zinsen(self):
        self._zahle('1000', date(2026, 3, 2))                        # Kapital 8.22 offen, Zins getilgt
        stand = inkasso.forderungen(self.b, date(2026, 4, 1))        # 30 Tage später: Zins nur auf die 8.22 Kapital
        zinsen = [c for c in stand if c['art'] == 'zins' and c['datum'] == date(2026, 1, 1)]
        self.assertEqual(zinsen[0]['betrag'], D('8.22') + (D('8.22') * D('0.05') * 30 / 365).quantize(D('0.01')))
        self.assertEqual(zinsen[0]['betrag'], D('8.25'))             # +0.03 auf 8.22 Kapital, nicht auf die 8.22 Zins

    def test_zwei_teilzahlungen_der_zins_laeuft_nur_auf_das_offene_kapital(self):
        z1 = self._zahle('500', date(2026, 1, 31))                   # Zins 30 Tage auf 1000: 4.11
        self.assertEqual((z1.an_zins, z1.kapital), (D('4.11'), D('495.89')))
        z2 = self._zahle('300', date(2026, 3, 2))                    # 30 Tage auf 504.11: 2.07
        self.assertEqual((z2.an_zins, z2.kapital), (D('2.07'), D('297.93')))
        stand = inkasso.forderungen(self.b, date(2026, 3, 2))
        self.assertEqual(kapital(stand, date(2026, 1, 1))['offen'], D('206.18'))
        self.assertEqual([c['offen'] for c in stand if c['art'] == 'zins'], [D('0.00')])
        self.assertEqual(sum(c['betrag'] for c in stand if c['art'] == 'zins'), D('6.18'))

    def test_pünktliche_zahlung_kostet_keinen_zins(self):
        for tag in (date(2025, 12, 20), date(2026, 1, 1)):           # vor und am Fälligkeitstag
            StwegAkonto.objects.all().delete()
            z = self._zahle('1000', tag)
            self.assertEqual(z.an_zins, D('0.00'))
        self.assertEqual([c for c in inkasso.forderungen(self.b, date(2026, 1, 20)) if c['art'] == 'zins'], [])

    def test_teilzahlung_am_faelligkeitstag_wird_nur_einmal_abgezogen(self):
        self._zahle('400', date(2026, 1, 1))
        stand = inkasso.forderungen(self.b, date(2026, 1, 31))              # 30 Tage auf die restlichen 600
        self.assertEqual(sum(c['betrag'] for c in stand if c['art'] == 'zins'), D('2.47'))   # 600 × 5 % × 30/365

    def test_zahlung_auf_eine_bestimmte_rate_zinst_deren_verspaetung(self):
        from stweg.models import StwegVorschreibung
        rate2 = StwegVorschreibung.objects.filter(einheit=self.b).order_by('faellig_am')[1]
        z = self._zahle('1000', date(2026, 5, 1), vorschreibung=rate2)       # bezahlt bewusst Rate 2 (1.4.)
        stand = inkasso.forderungen(self.b, date(2026, 5, 1))
        self.assertEqual(kapital(stand, date(2026, 4, 1))['offen'], D('1000.00') - z.kapital)
        self.assertEqual(kapital(stand, date(2026, 1, 1))['offen'], D('1000.00'))     # Rate 1 bleibt offen

    def test_ohne_satz_und_ohne_bestaetigung_kein_zins(self):
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '4.5'})              # Änderung nimmt Bestätigung zurück
        z = self._zahle('1000', date(2026, 3, 2))
        self.assertEqual((z.an_zins, z.kapital), (D('0'), D('1000.00')))
        self.assertFalse([c for c in inkasso.forderungen(self.b, date(2026, 3, 2)) if c['art'] == 'zins'])
        self.assertTrue(zins.satz_unbestaetigt(self.lg))
        vorgaben.speichern(self.lg, {'verzugszins_prozent': ''}, bestaetigen=True)
        self.assertIsNone(zins.satz(self.lg))

    def test_reihenfolge_ist_art_85_kosten_zins_kapital(self):
        self.assertEqual(zins.TILGUNGSREIHENFOLGE, ('kosten', 'zins', 'kapital'))

    def test_umgekehrte_reihenfolge_ist_waehlbar(self):
        # Kapital zuerst: der ganze Betrag tilgt das Kapital, der Zins bleibt offen.
        self.assertEqual(zins.zuordnen(self.b, D('5'), date(2026, 3, 2), reihenfolge=('kapital', 'zins', 'kosten')),
                         (D('0.00'), D('0.00'), D('5.00')))
        self.assertEqual(zins.zuordnen(self.b, D('5'), date(2026, 3, 2)), (D('0.00'), D('5.00'), D('0.00')))

    def test_pfandsumme_enthaelt_nie_zinsen(self):
        self._zahle('600', date(2026, 3, 2))
        p = inkasso.pfandberechtigt(self.b, date(2026, 6, 30))
        self.assertGreater(p['zinsen_kosten'], 0)
        self.assertEqual(p['pfandberechtigt'] + p['ausgeschlossen'], p['gesamt'])
        self.assertTrue(all(c['art'] in zins.KAPITAL_ARTEN for c in p['zeilen']))
        self.assertGreater(inkasso.offener_betrag(self.b, date(2026, 6, 30)), p['gesamt'])      # Gesamtschuld > Kapital


class ZinsBuchungTests(TestCase):
    def setUp(self):
        self.lg, self.e, self.eigs = haus_mit_eigentuemern()
        self.b = self.e[1]
        jahr_budget(self.lg, 2026, total=20000)
        vorgaben.speichern(self.lg, {'verzugszins_prozent': '5'}, bestaetigen=True)
        from stweg import budget  # noqa: F401  (Vorschreibungen sind gebucht, wenn das Budget genehmigt wird)

    def _saldo(self, nummer):
        return integritaet._saldo(self.lg, nummer)

    def test_zinsanteil_ist_ertrag_nicht_forderung(self):
        z = hauptbuch.zahlung_erfassen(self.b, D('1000'), date(2026, 3, 2))
        self.assertEqual(self._saldo('3120'), D('-8.22'))                       # Ertrag
        self.assertEqual(self._saldo('1110') - self._saldo_vor(), D('-991.78'))   # Forderung sinkt nur um das Kapital
        self.assertTrue(integritaet.abgestimmt(self.lg), integritaet.abstimmung_hauptbuch(self.lg))
        self.assertEqual(z.zins_buchung.betrag, D('8.22'))

    def _saldo_vor(self):
        from stweg.models import StwegVorschreibung
        return sum((v.betrag for v in StwegVorschreibung.objects.filter(budget__liegenschaft=self.lg)), D('0'))

    def test_storno_hebt_beide_buchungen_auf(self):
        z = hauptbuch.zahlung_erfassen(self.b, D('1000'), date(2026, 3, 2))
        hauptbuch.zahlung_stornieren(z)
        self.assertEqual(self._saldo('3120'), D('0.00'))
        self.assertTrue(integritaet.abgestimmt(self.lg), integritaet.abstimmung_hauptbuch(self.lg))

    def test_ohne_zins_keine_zweite_buchung(self):
        z = hauptbuch.zahlung_erfassen(self.b, D('1000'), date(2026, 1, 1))
        self.assertIsNone(z.zins_buchung)

    def test_abrechnung_und_kontokorrent_rechnen_nur_das_kapital_an(self):
        from stweg import konto
        from stweg.services import StwegAbrechnungService
        hauptbuch.zahlung_erfassen(self.b, D('1000'), date(2026, 3, 2))
        self.assertEqual(konto.kontokorrent(self.b, date(2026, 3, 2))['saldo_total'], D('4000.00') - D('991.78'))
        self.assertEqual(StwegAbrechnungService(self.lg).akonto_je_einheit(2026)[self.b.pk], D('991.78'))
