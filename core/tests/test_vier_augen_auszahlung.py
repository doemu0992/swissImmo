"""Vier-Augen-Prinzip für Auszahlungen ohne Rechnung und Summenregel im Zahllauf (Etappe 4).

DER BEFUND (vor dieser Etappe, an `main` gemessen): Eine Eigentümerauszahlung über CHF 20'000
liess ein einzelner Verwalter mit einem Klick buchen; ebenso die Rückerstattung eines
Mieterguthabens und die Rückzahlung einer Kaution (auch aus der Schlussabrechnung). Das Vier-Augen-Prinzip
(`finance/freigabe.py`) galt nur für Kreditorenrechnungen — und dort nur je Rechnung: Fünf Rechnungen
à CHF 4'000 desselben Lieferanten gingen in einem Zahllauf als CHF 20'000 an eine IBAN, ohne dass eine
zweite Person sie sah.

Gegenproben (je einmal gemacht, Ergebnis im Schlussbericht):
* In `core/services/eigentuemer_kontokorrent.py::buche_auszahlung` den Aufruf `auszahlung_pruefen` entfernen:
  `EigentuemerTests.test_ab_limit_wird_nicht_gebucht` und alle weiteren Eigentümertests sind rot.
* In `zahlungsklaerung.zurueckueberweisen`, `kautionen.fw_kaution_aktion` bzw. `fw_schlussabrechnung` ebenso
  der Aufruf: `GuthabenTests`, `KautionTests`, `SchlussabrechnungTests` sind rot.
* In `finance/freigabe.py::auszahlung_freigeben` den Vergleich mit dem Vorleger entfernen:
  `FreigabeWegTests.test_vorleger_gibt_nicht_selbst_frei` ist rot.
* In `auszahlung_pruefen` das Setzen von `verbraucht_am` entfernen: `test_freigabe_gilt_einmal` ist rot.
* In `kreditoren._auswahl` die Summenregel (`summenregel_gruppen`) entfernen: `SummenregelTests` sind rot.
"""
from datetime import date
from decimal import Decimal

from django.contrib.messages import get_messages
from django.utils import timezone

from ._parallel import NUR_POSTGRES, parallel
from ._rollen import RollenBasis, RollenBasisTransaktion

IBAN_EIGENTUEMER = 'CH9300762011623852957'
IBAN_ANDERE = 'CH4431999123000889012'
SEITE = '/neu/einstellungen/zahlungsfreigabe/auszahlungen/'


class _Werkzeug:
    """Bausteine für beide Basisklassen (mit und ohne umschliessende Transaktion)."""

    def setUp(self):
        super().setUp()
        from core.tenancy import organisation_kontext
        from finance.booking import ensure_kontenplan
        self.org.iban = 'CH5604835012345678009'
        self.org.save(update_fields=['iban'])
        with organisation_kontext(self.org):
            ensure_kontenplan()

    # --- Anfragen -------------------------------------------------------------------------------
    def post(self, rolle, url, daten=None):
        antwort = self.client_von(rolle).post(url, daten or {})
        return antwort, [str(m) for m in get_messages(antwort.wsgi_request)]

    def setze_limit(self, limit):
        self.org.freigabelimit_kreditoren = limit
        self.org.save(update_fields=['freigabelimit_kreditoren'])

    # --- Ausgangslage ---------------------------------------------------------------------------
    def eigentuemer_mit_geld(self, betrag='30000.00'):
        """Eingegangene Mieten für den Eigentümer von A: auszahlbar sind `betrag`."""
        from core.tenancy import organisation_kontext
        from finance.booking import buche
        with organisation_kontext(self.org):
            e = self.a.eigentuemer
            e.iban = IBAN_EIGENTUEMER
            e.save(update_fields=['iban'])
            for soll, haben in (('1100', '3000'), ('1020', '1100')):
                buche(soll, haben, Decimal(betrag), 'Miete', datum=date(2026, 3, 1),
                      liegenschaft=self.a.liegenschaft)
        return e

    def guthaben(self, betrag='6000.00', iban=IBAN_EIGENTUEMER):
        """Ein Mieterguthaben (2030) auf dem Vertrag von A."""
        from core.tenancy import organisation_kontext
        from finance.booking import buche, konto
        from finance.models import Zahlungseingang
        with organisation_kontext(self.org):
            m = self.a.mieter
            m.iban = iban
            m.save(update_fields=['iban'])
            z = Zahlungseingang.objects.create(
                vertrag=self.a.vertrag, betrag=Decimal(betrag), datum_eingang=date(2026, 3, 1),
                buchungs_monat=date(2026, 3, 1), konto=konto('2030'), liegenschaft=self.a.liegenschaft,
                erstellt_von=self.benutzer['verwalter'], status='verbucht')
            buche('1020', '2030', Decimal(betrag), 'Überzahlung', datum=date(2026, 3, 1),
                  liegenschaft=self.a.liegenschaft, zahlung=z)
        return z

    def kaution(self, iban=IBAN_EIGENTUEMER):
        """Die Kaution von A (CHF 4'500) ist einbezahlt und bilanziert."""
        from core.services.automation import buche_kaution_einzahlung
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.org):
            v = self.a.vertrag
            v.kautions_art, v.kautions_einbezahlt_am = 'sperrkonto', date(2026, 1, 1)
            v.save()
            m = self.a.mieter
            m.iban = iban
            m.save(update_fields=['iban'])
            buche_kaution_einzahlung(v, date(2026, 1, 1))
        return v

    # --- Auslösen -------------------------------------------------------------------------------
    def eig_auszahlen(self, rolle, betrag, e=None):
        e = e or self.a.eigentuemer
        return self.post(rolle, f'/neu/mandate/{e.pk}/auszahlung/', {
            'betrag': str(betrag), 'konto_nummer': '1020', 'datum': timezone.localdate().isoformat()})

    def guthaben_zurueck(self, rolle, z):
        return self.post(rolle, '/neu/bankabgleich/guthaben/rueckerstatten/', {'zahlung_id': z.pk})

    def kaution_zurueck(self, rolle, v):
        return self.post(rolle, f'/neu/vertraege/{v.pk}/kaution/', {
            'aktion': 'rueckzahlung', 'abzug_betrag': '0',
            'zurueckbezahlt_am': timezone.localdate().isoformat()})

    def schluss(self, rolle, v):
        return self.post(rolle, f'/neu/vertraege/{v.pk}/schlussabrechnung/', {
            'auszug_datum': timezone.localdate().isoformat(), 'aktion': 'buchen', 'kaution_verrechnen': 'on'})

    # --- Befunde --------------------------------------------------------------------------------
    def anzahl_auszahlungen(self):
        from core.tenancy import organisation_kontext
        from finance.models import EigentuemerAuszahlung
        with organisation_kontext(self.org):
            return EigentuemerAuszahlung.objects.filter(status='verbucht').count()

    def buchungen(self, text):
        from core.tenancy import organisation_kontext
        from finance.models import Buchung
        with organisation_kontext(self.org):
            return Buchung.objects.filter(beleg_text__contains=text, ist_storno=False).count()

    def antrag(self, art, bezug_id):
        from core.tenancy import organisation_kontext
        from finance.models import AuszahlungsFreigabe
        with organisation_kontext(self.org):
            return AuszahlungsFreigabe.objects.filter(art=art, bezug_id=bezug_id).order_by('-id').first()

    def antraege(self):
        from core.tenancy import organisation_kontext
        from finance.models import AuszahlungsFreigabe
        with organisation_kontext(self.org):
            return list(AuszahlungsFreigabe.objects.order_by('id'))

    def freigeben(self, rolle, antrag, betrag=None, iban=None):
        return self.post(rolle, f'{SEITE}{antrag.pk}/freigeben/', {
            'betrag': str(antrag.betrag if betrag is None else betrag),
            'iban': antrag.iban if iban is None else iban})

    def protokoll(self, text):
        from core.models import AktivitaetsLog
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.org):
            return list(AktivitaetsLog.objects.filter(aktion__startswith=text).order_by('id'))


class _Basis(_Werkzeug, RollenBasis):
    pass


class EigentuemerTests(_Basis):

    def setUp(self):
        super().setUp()
        self.eigentuemer_mit_geld()

    def test_unter_dem_limit_wird_direkt_ausbezahlt(self):
        self.eig_auszahlen('verwalter', '4999.99')
        self.assertEqual(self.anzahl_auszahlungen(), 1)
        self.assertEqual(self.antraege(), [])

    def test_ab_limit_wird_nicht_gebucht(self):
        """Der Befund: 20'000 an einen Eigentümer, ein Verwalter, ein Klick."""
        _a, meldungen = self.eig_auszahlen('verwalter', '20000.00')
        self.assertEqual(self.anzahl_auszahlungen(), 0)
        self.assertTrue(any('zweiten Person' in m for m in meldungen), meldungen)

    def test_genau_am_limit_greift_die_freigabe(self):
        self.eig_auszahlen('verwalter', '5000.00')
        self.assertEqual(self.anzahl_auszahlungen(), 0)

    def test_sperre_legt_vor_und_protokolliert(self):
        self.eig_auszahlen('verwalter', '7500.00')
        antrag = self.antrag('eigentuemer', self.a.eigentuemer.pk)
        self.assertEqual(antrag.beantragt_von, self.benutzer['verwalter'])
        self.assertEqual(antrag.betrag, Decimal('7500.00'))
        self.assertEqual(antrag.iban, IBAN_EIGENTUEMER)
        self.assertEqual(antrag.organisation_id, self.org.pk)
        self.assertEqual(len(self.protokoll('Auszahlung zur Freigabe vorgelegt')), 1)
        self.assertEqual(len(self.protokoll('Auszahlung gesperrt')), 1)

    def test_gesperrter_versuch_bucht_nichts_im_hauptbuch(self):
        vorher = self.buchungen('Auszahlung Eigentümer')
        self.eig_auszahlen('verwalter', '9000.00')
        self.assertEqual(self.buchungen('Auszahlung Eigentümer'), vorher)

    def test_zweite_person_gibt_frei_dann_wird_ausbezahlt(self):
        self.eig_auszahlen('verwalter', '7500.00')
        antrag = self.antrag('eigentuemer', self.a.eigentuemer.pk)
        self.freigeben('verwalter2', antrag)
        self.eig_auszahlen('verwalter', '7500.00')
        self.assertEqual(self.anzahl_auszahlungen(), 1)
        self.assertEqual(self.buchungen('Auszahlung Eigentümer'), 1)
        self.assertIsNotNone(self.antrag('eigentuemer', self.a.eigentuemer.pk).verbraucht_am)
        self.assertEqual(len(self.protokoll('Auszahlung freigegeben')), 1)

    def test_freigabe_gilt_einmal(self):
        """Eine Freigabe, eine Auszahlung: Der zweite Klick (gleicher Betrag) braucht eine neue."""
        self.eig_auszahlen('verwalter', '6000.00')
        self.freigeben('verwalter2', self.antrag('eigentuemer', self.a.eigentuemer.pk))
        self.eig_auszahlen('verwalter', '6000.00')
        self.eig_auszahlen('verwalter', '6000.00')
        self.assertEqual(self.anzahl_auszahlungen(), 1)
        offen = [a for a in self.antraege() if a.verbraucht_am is None]
        self.assertEqual(len(offen), 1)
        self.assertIsNone(offen[0].freigegeben_von)

    def test_anderer_betrag_als_freigegeben_ist_gesperrt(self):
        self.eig_auszahlen('verwalter', '6000.00')
        self.freigeben('verwalter2', self.antrag('eigentuemer', self.a.eigentuemer.pk))
        _a, meldungen = self.eig_auszahlen('verwalter', '9000.00')
        self.assertEqual(self.anzahl_auszahlungen(), 0)
        self.assertTrue(any('nach der Freigabe geändert' in m for m in meldungen), meldungen)
        antrag = self.antrag('eigentuemer', self.a.eigentuemer.pk)
        self.assertIsNone(antrag.freigegeben_von)          # die alte Freigabe ist weg
        self.assertEqual(antrag.betrag, Decimal('9000.00'))

    def test_iban_aenderung_nach_der_freigabe_sperrt(self):
        """Der klassische Betrug: IBAN des Eigentümers tauschen, nachdem jemand freigegeben hat."""
        from core.tenancy import organisation_kontext
        from crm.models import Eigentuemer
        self.eig_auszahlen('verwalter', '6000.00')
        self.freigeben('verwalter2', self.antrag('eigentuemer', self.a.eigentuemer.pk))
        with organisation_kontext(self.org):
            Eigentuemer.objects.filter(pk=self.a.eigentuemer.pk).update(iban=IBAN_ANDERE)
        self.eig_auszahlen('verwalter', '6000.00')
        self.assertEqual(self.anzahl_auszahlungen(), 0)

    def test_erneutes_ausloesen_aendert_den_vorleger_nicht(self):
        self.eig_auszahlen('verwalter', '6000.00')
        self.eig_auszahlen('verwalter2', '6000.00')
        self.assertEqual(self.antrag('eigentuemer', self.a.eigentuemer.pk).beantragt_von, self.benutzer['verwalter'])
        self.assertEqual(len(self.antraege()), 1)

    def test_limit_je_organisation(self):
        """Das Limit der anderen Verwaltung gilt hier nicht."""
        from crm.models import Organisation
        Organisation.objects.filter(pk=self.b.organisation.pk).update(freigabelimit_kreditoren=Decimal('1.00'))
        self.eig_auszahlen('verwalter', '4000.00')
        self.assertEqual(self.anzahl_auszahlungen(), 1)

    def test_ohne_limit_kein_vier_augen(self):
        self.setze_limit(None)
        self.eig_auszahlen('verwalter', '20000.00')
        self.assertEqual(self.anzahl_auszahlungen(), 1)

    def test_aenderung_der_limite_wirkt_sofort(self):
        self.setze_limit(Decimal('100000.00'))
        self.eig_auszahlen('verwalter', '20000.00')
        self.assertEqual(self.anzahl_auszahlungen(), 1)

    def test_fehler_vor_der_freigabe_haben_vorrang(self):
        """Mehr als auszahlbar: die Meldung nennt das Geld, es entsteht kein Antrag."""
        self.eig_auszahlen('verwalter', '50000.00')
        self.assertEqual(self.antraege(), [])

    def test_ausloesen_ist_nur_per_post(self):
        antwort = self.client_von('verwalter').get(f'/neu/mandate/{self.a.eigentuemer.pk}/auszahlung/')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(self.antraege(), [])


class GuthabenTests(_Basis):

    def setUp(self):
        super().setUp()
        self.z = self.guthaben('6000.00')

    def test_unter_dem_limit_wird_direkt_zurueckerstattet(self):
        self.setze_limit(Decimal('6000.01'))
        self.guthaben_zurueck('verwalter', self.z)
        self.assertEqual(self.buchungen(f'[Z{self.z.pk}]'), 1)

    def test_ab_limit_wird_nicht_zurueckerstattet(self):
        _a, meldungen = self.guthaben_zurueck('verwalter', self.z)
        self.assertEqual(self.buchungen(f'[Z{self.z.pk}]'), 0)
        self.assertTrue(any('zweiten Person' in m for m in meldungen), meldungen)
        antrag = self.antrag('guthaben', self.z.pk)
        self.assertEqual(antrag.beantragt_von, self.benutzer['verwalter'])
        self.assertEqual(antrag.iban, IBAN_EIGENTUEMER)

    def test_mit_freigabe_einmal_zurueckerstattet(self):
        self.guthaben_zurueck('verwalter', self.z)
        self.freigeben('verwalter2', self.antrag('guthaben', self.z.pk))
        self.guthaben_zurueck('verwalter', self.z)
        self.assertEqual(self.buchungen(f'[Z{self.z.pk}]'), 1)
        self.guthaben_zurueck('verwalter', self.z)          # zweite Rückzahlung: gibt es nicht mehr
        self.assertEqual(self.buchungen(f'[Z{self.z.pk}]'), 1)

    def test_iban_des_mieters_geaendert_sperrt(self):
        from core.tenancy import organisation_kontext
        from crm.models import Mieter
        self.guthaben_zurueck('verwalter', self.z)
        self.freigeben('verwalter2', self.antrag('guthaben', self.z.pk))
        with organisation_kontext(self.org):
            Mieter.objects.filter(pk=self.a.mieter.pk).update(iban=IBAN_ANDERE)
        self.guthaben_zurueck('verwalter', self.z)
        self.assertEqual(self.buchungen(f'[Z{self.z.pk}]'), 0)

    def test_selbstfreigabe_ist_nicht_moeglich(self):
        self.guthaben_zurueck('verwalter', self.z)
        self.freigeben('verwalter', self.antrag('guthaben', self.z.pk))
        self.guthaben_zurueck('verwalter', self.z)
        self.assertEqual(self.buchungen(f'[Z{self.z.pk}]'), 0)


class KautionTests(_Basis):

    def setUp(self):
        super().setUp()
        self.setze_limit(Decimal('4000.00'))          # die Kaution des Fixtures ist CHF 4'500
        self.v = self.kaution()

    def beleg(self):
        return self.buchungen(f'Kaution Auflösung [V{self.v.pk}]')

    def test_unter_dem_limit_wird_direkt_zurueckgezahlt(self):
        self.setze_limit(Decimal('4500.01'))
        self.kaution_zurueck('verwalter', self.v)
        self.assertEqual(self.beleg(), 2)             # Sperrkonto freigeben + Rückzahlung an den Mieter

    def test_ab_limit_wird_nichts_gebucht(self):
        _a, meldungen = self.kaution_zurueck('verwalter', self.v)
        self.assertEqual(self.beleg(), 0)
        self.assertTrue(any('zweiten Person' in m for m in meldungen), meldungen)
        antrag = self.antrag('kaution', self.v.pk)
        self.assertEqual(antrag.betrag, Decimal('4500.00'))
        self.assertEqual(antrag.beantragt_von, self.benutzer['verwalter'])
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.org):
            self.v.refresh_from_db()
        self.assertIsNone(self.v.kautions_zurueckbezahlt_am, 'Der Vertrag gilt nicht als zurückbezahlt.')

    def test_mit_freigabe_einmal_zurueckgezahlt(self):
        self.kaution_zurueck('verwalter', self.v)
        self.freigeben('verwalter2', self.antrag('kaution', self.v.pk))
        self.kaution_zurueck('verwalter', self.v)
        self.assertEqual(self.beleg(), 2)
        self.assertIsNotNone(self.antrag('kaution', self.v.pk).verbraucht_am)

    def test_anderer_betrag_als_freigegeben_sperrt(self):
        """Rückzahlung 4'500 freigegeben; mit 1'000 Einbehalt (Rückzahlung 3'500) ist es ein anderer Betrag."""
        self.setze_limit(Decimal('3000.00'))
        self.kaution_zurueck('verwalter', self.v)
        self.freigeben('verwalter2', self.antrag('kaution', self.v.pk))
        self.post('verwalter', f'/neu/vertraege/{self.v.pk}/kaution/', {
            'aktion': 'rueckzahlung', 'abzug_betrag': '1000', 'abzug_grund': 'Schaden',
            'zurueckbezahlt_am': timezone.localdate().isoformat()})
        self.assertEqual(self.beleg(), 0)

    def test_einbehalt_unter_dem_limit_braucht_keine_freigabe(self):
        """Nur die Rückzahlung an den Mieter ist ein Geldabfluss; ein Einbehalt (Ertrag) ist es nicht."""
        self.setze_limit(Decimal('2000.00'))
        self.post('verwalter', f'/neu/vertraege/{self.v.pk}/kaution/', {
            'aktion': 'rueckzahlung', 'abzug_betrag': '3000', 'abzug_grund': 'Schaden',
            'zurueckbezahlt_am': timezone.localdate().isoformat()})
        self.assertEqual(self.beleg(), 3)             # Freigabe + Rückzahlung 1'500 + Einbehalt


class SchlussabrechnungTests(_Basis):
    """Die Schlussabrechnung zahlt Kaution UND Guthaben an den Mieter: derselbe Geldabfluss."""

    def setUp(self):
        super().setUp()
        self.setze_limit(Decimal('4000.00'))
        self.v = self.kaution()

    def beleg(self):
        return self.buchungen(f'Kaution Schlussabrechnung [V{self.v.pk}]')

    def test_ab_limit_wird_nichts_gebucht(self):
        _a, meldungen = self.schluss('verwalter', self.v)
        self.assertEqual(self.beleg(), 0)
        self.assertTrue(any('zweiten Person' in m for m in meldungen), meldungen)
        antrag = self.antrag('schlussabrechnung', self.v.pk)
        self.assertEqual(antrag.betrag, Decimal('4500.00'))

    def test_mit_freigabe_wird_verbucht(self):
        self.schluss('verwalter', self.v)
        self.freigeben('verwalter2', self.antrag('schlussabrechnung', self.v.pk))
        self.schluss('verwalter', self.v)
        self.assertEqual(self.beleg(), 2)

    def test_kaution_und_guthaben_zaehlen_zusammen(self):
        """Kaution 4'500 + Guthaben 600: Die Summe (5'100) ist massgebend, nicht jeder Teil für sich."""
        self.setze_limit(Decimal('5000.00'))
        self.guthaben('600.00')
        self.schluss('verwalter', self.v)
        self.assertEqual(self.beleg(), 0)
        antrag = self.antrag('schlussabrechnung', self.v.pk)
        self.assertEqual(antrag.betrag, Decimal('5100.00'))


class FreigabeWegTests(_Basis):
    """Die Seite «Auszahlungen» und die Regeln des Freigabewegs."""

    def setUp(self):
        super().setUp()
        self.eigentuemer_mit_geld()
        self.eig_auszahlen('verwalter', '7500.00')
        self.antrag_e = self.antrag('eigentuemer', self.a.eigentuemer.pk)

    def stand(self):
        return self.antrag('eigentuemer', self.a.eigentuemer.pk)

    def test_vorleger_gibt_nicht_selbst_frei(self):
        _a, meldungen = self.freigeben('verwalter', self.antrag_e)
        self.assertIsNone(self.stand().freigegeben_von)
        self.assertTrue(any('nicht selbst' in m for m in meldungen), meldungen)
        self.assertEqual(len(self.protokoll('Auszahlungsfreigabe abgelehnt')), 1)

    def test_inhaber_gibt_frei(self):
        self.freigeben('inhaber', self.antrag_e)
        self.assertEqual(self.stand().freigegeben_von, self.benutzer['inhaber'])
        self.assertEqual(self.stand().freigabe_betrag, Decimal('7500.00'))
        self.assertEqual(self.stand().freigabe_iban, IBAN_EIGENTUEMER)

    def test_nur_verwaltung_gibt_frei(self):
        for rolle in ('buchhaltung', 'sachbearbeiter', 'lesezugriff', 'hauswart'):
            with self.subTest(rolle=rolle):
                antwort, _m = self.freigeben(rolle, self.antrag_e)
                self.assertEqual(antwort.status_code, 403)
                self.assertIsNone(self.stand().freigegeben_von)

    def test_freigeber_bestaetigt_betrag_und_iban_die_er_sah(self):
        """Wurde der Antrag zwischen Anzeige und Klick geändert, gilt die Freigabe nicht."""
        _a, meldungen = self.freigeben('verwalter2', self.antrag_e, betrag='1000.00')
        self.assertIsNone(self.stand().freigegeben_von)
        self.assertTrue(any('geändert' in m for m in meldungen), meldungen)
        self.freigeben('verwalter2', self.antrag_e, iban=IBAN_ANDERE)
        self.assertIsNone(self.stand().freigegeben_von)
        self.freigeben('verwalter2', self.antrag_e, betrag='abc')
        self.assertIsNone(self.stand().freigegeben_von)

    def test_freigabe_unter_dem_limit_ist_unnoetig(self):
        self.setze_limit(Decimal('100000.00'))
        _a, meldungen = self.freigeben('verwalter2', self.antrag_e)
        self.assertIsNone(self.stand().freigegeben_von)

    def test_zuruecknehmen_sperrt_wieder(self):
        self.freigeben('verwalter2', self.antrag_e)
        self.post('verwalter', f'{SEITE}{self.antrag_e.pk}/zuruecknehmen/')
        self.assertEqual(self.antraege(), [])
        self.eig_auszahlen('verwalter', '7500.00')
        self.assertEqual(self.anzahl_auszahlungen(), 0)
        self.assertEqual(len(self.protokoll('Auszahlungsfreigabe zurückgenommen')), 1)

    def test_get_aendert_nichts(self):
        for ende in ('freigeben/', 'zuruecknehmen/'):
            with self.subTest(ende=ende):
                antwort = self.client_von('verwalter2').get(f'{SEITE}{self.antrag_e.pk}/{ende}')
                self.assertEqual(antwort.status_code, 302)
        self.assertIsNone(self.stand().freigegeben_von)
        self.assertEqual(len(self.antraege()), 1)

    def test_fremder_antrag_ist_ein_404(self):
        """Mandantentrennung: Verwaltung B sieht, gibt frei und nimmt den Antrag von A nicht zurück."""
        from django.test import Client
        c = Client(raise_request_exception=False)
        c.force_login(self.b.benutzer)
        for ende in ('freigeben/', 'zuruecknehmen/'):
            with self.subTest(ende=ende):
                self.assertEqual(c.post(f'{SEITE}{self.antrag_e.pk}/{ende}').status_code, 404)
        self.assertIsNone(self.stand().freigegeben_von)
        self.assertEqual(len(self.antraege()), 1)
        seite = c.get(SEITE).content.decode()
        self.assertNotIn('Eigentuemer A', seite)

    def test_seite_zeigt_den_antrag_und_die_knoepfe_je_person(self):
        html = self.client_von('verwalter2').get(SEITE).content.decode()
        self.assertIn('Eigentuemer A', html)
        self.assertIn('7&#x27;500.00', html.replace("'", '&#x27;'))
        self.assertIn(f'{SEITE}{self.antrag_e.pk}/freigeben/', html)
        html = self.client_von('verwalter').get(SEITE).content.decode()
        self.assertNotIn(f'{SEITE}{self.antrag_e.pk}/freigeben/', html)       # der Vorleger sieht keinen Knopf
        self.assertIn('vorgelegt', html)
        html = self.client_von('buchhaltung').get(SEITE).content.decode()
        self.assertNotIn(f'{SEITE}{self.antrag_e.pk}/freigeben/', html)

    def test_leere_seite_sagt_es(self):
        self.post('verwalter', f'{SEITE}{self.antrag_e.pk}/zuruecknehmen/')
        html = self.client_von('verwalter').get(SEITE).content.decode()
        self.assertIn('Keine Auszahlung wartet auf Freigabe', html)

    def test_seite_gesperrt_fuer_fremde_rollen(self):
        for rolle in ('sachbearbeiter', 'lesezugriff', 'hauswart'):
            with self.subTest(rolle=rolle):
                self.assertEqual(self.client_von(rolle).get(SEITE).status_code, 403)

    def test_einstellungsseite_zaehlt_offene_auszahlungen(self):
        html = self.client_von('inhaber').get('/neu/einstellungen/zahlungsfreigabe/').content.decode()
        self.assertIn('1 Auszahlung wartet auf Freigabe', html)


class SummenregelTests(_Basis):
    """Summe der Rechnungen desselben Kreditors in einem Zahllauf >= Limite => Freigabe nötig."""

    def _datei(self, rolle, *ks):
        return self.post(rolle, '/neu/zahllauf/', {
            'aktion': 'datei', 'rechnung_ids': [k.pk for k in ks],
            'ausfuehrungsdatum': timezone.localdate().isoformat()})

    def _bezahlt(self, rolle, *ks):
        return self.post(rolle, '/neu/zahllauf/', {'aktion': 'bezahlt', 'rechnung_ids': [k.pk for k in ks]})

    def stand(self, k):
        from core.tenancy import organisation_kontext
        with organisation_kontext(self.org):
            k.refresh_from_db()
        return k

    def drei(self, **kw):
        return [self.kreditor('2000.00', referenz=f'R-{i}', **kw) for i in (1, 2, 3)]

    def ist_datei(self, antwort):
        return antwort.get('Content-Type', '').startswith('application/xml')

    def test_die_stueckelung_geht_heute_durch_die_einzelregel(self):
        """Zur Dokumentation des Befunds: Jede Rechnung allein liegt unter dem Limit."""
        from finance.freigabe import braucht_zahlungsfreigabe
        from core.tenancy import organisation_kontext
        ks = self.drei()
        with organisation_kontext(self.org):
            self.assertEqual([braucht_zahlungsfreigabe(k, self.org) for k in ks], [False] * 3)

    def test_drei_mal_2000_desselben_kreditors_brauchen_die_freigabe(self):
        ks = self.drei()
        antwort, meldungen = self._datei('buchhaltung', *ks)
        self.assertFalse(self.ist_datei(antwort), meldungen)
        for k in ks:
            self.assertEqual(self.stand(k).status, 'freigegeben')

    def test_die_meldung_erklaert_welche_rechnungen_zusammen_die_limite_erreichen(self):
        ks = self.drei()
        _a, meldungen = self._datei('buchhaltung', *ks)
        text = ' '.join(meldungen)
        for nummer in ('R-1', 'R-2', 'R-3'):
            self.assertIn(nummer, text)
        self.assertIn("6'000.00", text)
        self.assertIn("5'000.00", text)
        self.assertIn('Muster Handwerk AG', text)

    def test_zwei_mal_2000_bleiben_darunter(self):
        k1, k2, _k3 = self.drei()
        antwort, meldungen = self._datei('buchhaltung', k1, k2)
        self.assertTrue(self.ist_datei(antwort), meldungen)
        self.assertEqual(self.stand(k1).status, 'in_zahlung')

    def test_verschiedene_kreditoren_zaehlen_nicht_zusammen(self):
        ibans = (IBAN_EIGENTUEMER, 'CH6600762011623852958', 'CH3908704016075473007')
        ks = [self.kreditor('2000.00', lieferant=f'Firma {i}', iban=iban, referenz=f'R-{i}')
              for i, iban in enumerate(ibans)]
        antwort, meldungen = self._datei('buchhaltung', *ks)
        self.assertTrue(self.ist_datei(antwort), meldungen)

    def test_derselbe_name_in_zwei_schreibweisen_zaehlt_zusammen(self):
        ks = [self.kreditor('2000.00', lieferant=name, referenz=f'R-{i}')
              for i, name in enumerate(('Muster Handwerk AG', 'MUSTER HANDWERK', 'muster handwerk ag.'))]
        antwort, _m = self._datei('buchhaltung', *ks)
        self.assertFalse(self.ist_datei(antwort))

    def test_dieselbe_iban_unter_anderem_namen_zaehlt_zusammen(self):
        ks = [self.kreditor('2000.00', lieferant=name, referenz=f'R-{i}')
              for i, name in enumerate(('Alpha GmbH', 'Beta GmbH', 'Gamma GmbH'))]
        antwort, _m = self._datei('buchhaltung', *ks)
        self.assertFalse(self.ist_datei(antwort))

    def test_nur_die_ausgewaehlten_zaehlen(self):
        """Die Summe bildet sich über den Lauf, nicht über alle offenen Rechnungen des Kreditors."""
        k1, k2, _k3 = self.drei()
        antwort, _m = self._datei('buchhaltung', k1, k2)
        self.assertTrue(self.ist_datei(antwort))

    def test_mit_freigabe_jeder_rechnung_geht_der_lauf(self):
        ks = self.drei()
        self._datei('buchhaltung', *ks)                           # legt vor
        for k in ks:
            self.assertEqual(self.stand(k).zahlung_beantragt_von, self.benutzer['buchhaltung'])
            self.assertEqual(self.stand(k).zahlung_gruppensumme, Decimal('6000.00'))
            self.post('verwalter', f'/neu/kreditoren/{k.pk}/zahlung-freigeben/')
        antwort, meldungen = self._datei('buchhaltung', *ks)
        self.assertTrue(self.ist_datei(antwort), meldungen)
        for k in ks:
            self.assertEqual(self.stand(k).status, 'in_zahlung')

    def test_teilweise_freigegeben_nimmt_nur_diese_mit(self):
        k1, k2, k3 = self.drei()
        self._datei('buchhaltung', k1, k2, k3)
        self.post('verwalter', f'/neu/kreditoren/{k1.pk}/zahlung-freigeben/')
        antwort, _m = self._datei('buchhaltung', k1, k2, k3)
        self.assertTrue(self.ist_datei(antwort))
        xml = antwort.content.decode()
        self.assertIn('R-1', xml)
        self.assertNotIn('R-2', xml)
        self.assertEqual(self.stand(k1).status, 'in_zahlung')
        self.assertEqual(self.stand(k2).status, 'freigegeben')

    def test_sammelbestaetigung_umgeht_die_summenregel_nicht(self):
        from core.tenancy import organisation_kontext
        from finance.models import KreditorenZahlung
        ks = self.drei()
        self._bezahlt('buchhaltung', *ks)
        with organisation_kontext(self.org):
            self.assertEqual(KreditorenZahlung.objects.filter(status='verbucht').count(), 0)

    def test_freigabe_im_kreditorenfenster_ist_moeglich(self):
        """Die Vorlage der Summenregel ist unter dem Rechnungslimit: Freigeben muss trotzdem gehen."""
        ks = self.drei()
        self._datei('buchhaltung', *ks)
        _a, meldungen = self.post('verwalter', f'/neu/kreditoren/{ks[0].pk}/zahlung-freigeben/')
        self.assertIsNotNone(self.stand(ks[0]).zahlung_freigegeben_von, meldungen)

    def test_zuruecknehmen_loescht_die_summe(self):
        ks = self.drei()
        self._datei('buchhaltung', *ks)
        self.post('buchhaltung', f'/neu/kreditoren/{ks[0].pk}/zahlung-zuruecknehmen/')
        self.assertIsNone(self.stand(ks[0]).zahlung_gruppensumme)

    def test_hebt_der_inhaber_die_limite_an_fallen_die_rechnungen_frei(self):
        ks = self.drei()
        self._datei('buchhaltung', *ks)
        self.setze_limit(Decimal('7000.00'))
        antwort, _m = self._datei('buchhaltung', *ks)
        self.assertTrue(self.ist_datei(antwort))

    def test_ohne_limit_keine_summenregel(self):
        self.setze_limit(None)
        antwort, _m = self._datei('buchhaltung', *self.drei())
        self.assertTrue(self.ist_datei(antwort))

    def test_zahllauf_seite_erklaert_die_summenregel_vorab(self):
        self.drei()
        html = self.client_von('buchhaltung').get('/neu/zahllauf/').content.decode()
        self.assertIn('Summenregel', html)
        for nummer in ('R-1', 'R-2', 'R-3'):
            self.assertIn(nummer, html)

    def test_zahllauf_seite_ohne_gruppe_hat_keinen_hinweis(self):
        self.kreditor('2000.00')
        html = self.client_von('buchhaltung').get('/neu/zahllauf/').content.decode()
        self.assertNotIn('zahllauf-summenregel', html)

    def test_gruppen_dienst_ohne_organisation_limit(self):
        from finance.freigabe import summenregel_gruppen
        self.assertEqual(summenregel_gruppen(self.drei(), None), [])


@NUR_POSTGRES
class ParallelTests(_Werkzeug, RollenBasisTransaktion):
    """Echte Threads gegen PostgreSQL (SQLite serialisiert Schreiber und verdeckt Rennen)."""

    def test_vier_parallele_ausloesungen_mit_einer_freigabe_buchen_einmal(self):
        self.eigentuemer_mit_geld()
        self.eig_auszahlen('verwalter', '6000.00')
        self.freigeben('verwalter2', self.antrag('eigentuemer', self.a.eigentuemer.pk))
        ergebnisse = parallel(4, lambda i: self.eig_auszahlen('verwalter', '6000.00')[0].status_code)
        self.assertEqual([e for e in ergebnisse if isinstance(e, BaseException)], [])
        self.assertEqual(self.anzahl_auszahlungen(), 1)
        self.assertEqual(self.buchungen('Auszahlung Eigentümer'), 1)

    def test_gleichzeitiges_vorlegen_zweier_personen_ergibt_einen_antrag(self):
        self.eigentuemer_mit_geld()
        rollen = ['verwalter', 'verwalter2']
        ergebnisse = parallel(2, lambda i: self.eig_auszahlen(rollen[i], '6000.00')[0].status_code)
        self.assertEqual([e for e in ergebnisse if isinstance(e, BaseException)], [])
        antraege = self.antraege()
        self.assertEqual(len(antraege), 1)
        self.assertIn(antraege[0].beantragt_von, (self.benutzer['verwalter'], self.benutzer['verwalter2']))
        self.assertEqual(len(self.protokoll('Auszahlung zur Freigabe vorgelegt')), 1)

    def test_gleichzeitige_freigabe_und_zuruecknehmen_enden_konsistent(self):
        self.eigentuemer_mit_geld()
        self.eig_auszahlen('verwalter', '6000.00')
        antrag = self.antrag('eigentuemer', self.a.eigentuemer.pk)

        def arbeit(i):
            if i == 0:
                return self.freigeben('verwalter2', antrag)[0].status_code
            return self.post('inhaber', f'{SEITE}{antrag.pk}/zuruecknehmen/')[0].status_code

        ergebnisse = parallel(2, arbeit)
        self.assertEqual([e for e in ergebnisse if isinstance(e, BaseException)], [])
        self.assertEqual(ergebnisse, [302, 302], 'Keine der beiden Anfragen darf mit einem Serverfehler enden.')
        # Entweder ist der Antrag weg, oder er ist freigegeben — nie halb.
        for a in self.antraege():
            if a.freigegeben_von_id:
                self.assertEqual(a.freigabe_betrag, a.betrag)

    def test_parallele_rueckzahlung_der_kaution_bucht_einmal(self):
        self.setze_limit(Decimal('4000.00'))
        v = self.kaution()
        self.kaution_zurueck('verwalter', v)
        self.freigeben('verwalter2', self.antrag('kaution', v.pk))
        ergebnisse = parallel(4, lambda i: self.kaution_zurueck('verwalter', v)[0].status_code)
        self.assertEqual([e for e in ergebnisse if isinstance(e, BaseException)], [])
        self.assertEqual(self.buchungen(f'Kaution Auflösung [V{v.pk}]'), 2)

    def test_parallele_rueckerstattung_des_guthabens_bucht_einmal(self):
        self.setze_limit(Decimal('4000.00'))
        z = self.guthaben('6000.00')
        self.guthaben_zurueck('verwalter', z)
        self.freigeben('verwalter2', self.antrag('guthaben', z.pk))
        ergebnisse = parallel(4, lambda i: self.guthaben_zurueck('verwalter', z)[0].status_code)
        self.assertEqual([e for e in ergebnisse if isinstance(e, BaseException)], [])
        self.assertEqual(self.buchungen(f'[Z{z.pk}]'), 1)
