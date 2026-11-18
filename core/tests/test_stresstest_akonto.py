"""Stresstest 30.09.2026: Die NK-Abrechnung rechnet mit dem tatsächlich gestellten Akonto."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from ._helfer import _seed_konten, _test_organisation


class AkontoHistorieTests(TestCase):

    def setUp(self):
        _seed_konten()
        from crm.models import Mieter
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg
        from portfolio.models import Einheit, Liegenschaft
        from rentals.models import Mietvertrag
        self.lg = Liegenschaft.objects.create(organisation=_test_organisation(), strasse='Akonto 1',
                                              plz='4500', ort='SO', versicherungswert=Decimal('1'))
        self.e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung='W1', typ='whg',
                                        flaeche_m2=Decimal('80'))
        m = Mieter.objects.create(typ='person', vorname='A', nachname='B', strasse='W', plz='4500', ort='SO')
        self.v = Mietvertrag.objects.create(
            mieter=m, einheit=self.e, beginn=date(2025, 1, 1), status='aktiv',
            netto_mietzins=Decimal('1500'), nebenkosten=Decimal('200'), nk_abrechnungsart='akonto')
        self.p = AbrechnungsPeriode.objects.create(
            liegenschaft=self.lg, bezeichnung='NK 2025',
            start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        NebenkostenBeleg.objects.create(periode=self.p, text='Hauswart', betrag=Decimal('3000'),
                                        datum=date(2025, 6, 1), verteilschluessel='m2')

    def _sollstellung(self, monate):
        from core.services.automation import run_sollstellung
        for mm in monate:
            run_sollstellung(2025, mm)

    def _akonto(self):
        from core.utils.billing import berechne_abrechnung
        r = berechne_abrechnung(self.p.id)
        zeile = next(z for z in r['abrechnungen'] if z.get('vertrag_id') == self.v.id)
        return zeile['akonto']

    def test_ohne_sollstellung_gilt_wie_bisher_der_vertragswert(self):
        self.assertEqual(self._akonto(), Decimal('2400.00'))

    def test_gestelltes_akonto_ersetzt_den_heutigen_vertragswert(self):
        """Sollstellung lief mit 200; der Vertrag steht heute auf 250. Gutgeschrieben
        werden die 2400, die gestellt wurden — nicht 3000."""
        self._sollstellung(range(1, 13))
        self.v.nebenkosten = Decimal('250'); self.v.save()
        self.assertEqual(self._akonto(), Decimal('2400.00'),
                         'Die Engine rechnet mit dem heutigen Wert statt mit dem Gestellten.')

    def test_unterjaehrige_anpassung_fliesst_ein(self):
        """Sollstellung Januar–Juni mit 200, Juli–Dezember mit 250 → 1200 + 1500."""
        self._sollstellung(range(1, 7))
        self.v.nebenkosten = Decimal('250'); self.v.save()
        self._sollstellung(range(7, 13))
        self.assertEqual(self._akonto(), Decimal('2700.00'))

    def test_gratismonat_wird_nicht_gutgeschrieben(self):
        """Ein erlassener NK-Monat (Erlass 3091) wurde nie gestellt."""
        from finance.models import Buchung, DebitorenRechnung
        self._sollstellung(range(1, 13))
        r = DebitorenRechnung.objects.get(vertrag=self.v, titel='Miete & NK 03/2025')
        from finance.booking import buche
        buche('3091', '1100', Decimal('200.00'), 'NK-Erlass Test', datum=date(2025, 3, 1), debitor=r)
        self.assertEqual(self._akonto(), Decimal('2200.00'))

    def test_fehlender_monat_faellt_auf_den_vertragswert_zurueck(self):
        """Sollstellung nur für elf Monate: der Dezember zählt mit dem Vertragswert."""
        self._sollstellung(range(1, 12))
        self.assertEqual(self._akonto(), Decimal('2400.00'))

    def test_stornierte_forderung_zaehlt_nicht(self):
        from finance.models import DebitorenRechnung
        self._sollstellung(range(1, 13))
        DebitorenRechnung.objects.filter(vertrag=self.v, titel='Miete & NK 05/2025').update(status='storniert')
        # Der storniert markierte Monat fällt auf den Vertragswert zurück (200) — nicht auf 0.
        self.assertEqual(self._akonto(), Decimal('2400.00'))


def _akonto_referenz(vertrag, v_start, v_ende):
    """Der Rechenweg bis 15.11.2026, Monat für Monat mit eigenen Abfragen — als Referenz, gegen die der gebündelte Weg
    Rappen für Rappen verglichen wird. Bewusst eine Abschrift, kein Aufruf des Produktivcodes."""
    import calendar
    import datetime

    from django.db.models import Sum

    from finance.models import Buchung, DebitorenRechnung
    nk_monat = vertrag.nebenkosten or Decimal('0.00')
    gesamt, aus_buchungen = Decimal('0.00'), 0
    j, m = v_start.year, v_start.month
    while (j, m) <= (v_ende.year, v_ende.month):
        letzter = calendar.monthrange(j, m)[1]
        m_start, m_ende = datetime.date(j, m, 1), datetime.date(j, m, letzter)
        von, bis = max(v_start, m_start), min(v_ende, m_ende)
        tage = (bis - von).days + 1
        if tage > 0:
            rechnung = (DebitorenRechnung.alle_organisationen.filter(vertrag=vertrag, titel=f"Miete & NK {m:02d}/{j}")
                        .exclude(status='storniert').first())
            gestellt = None
            if rechnung is not None:
                basis = Buchung.alle_organisationen.filter(debitoren_rechnung=rechnung, ist_storno=False,
                                                           storniert_am__isnull=True)
                haben = basis.filter(haben_konto__nummer='3020').aggregate(s=Sum('betrag'))['s']
                if haben is not None:
                    erlass = basis.filter(soll_konto__nummer='3091').aggregate(s=Sum('betrag'))['s'] or Decimal('0')
                    gestellt = Decimal(haben) - Decimal(erlass)
            if gestellt is not None:
                v_von = max(vertrag.beginn, m_start)
                v_bis = min(vertrag.ende, m_ende) if vertrag.ende else m_ende
                v_tage = max((v_bis - v_von).days + 1, 1)
                gesamt += gestellt * Decimal(min(tage, v_tage)) / Decimal(v_tage)
                aus_buchungen += 1
            else:
                gesamt += nk_monat * Decimal(tage) / Decimal(letzter)
        m += 1
        if m == 13:
            j, m = j + 1, 1
    return gesamt, aus_buchungen


class GebuendelteAbfrageTests(AkontoHistorieTests):
    """Audit 15.11.2026: `akonto_gestellt` fragte je Kalendermonat bis zu dreimal ab (24 Abfragen je Vertrag und Jahr).
    Der gebündelte Weg braucht zwei Abfragen je Vertrag und muss dasselbe liefern.

    Gegenprobe: in `_gestellte_nk_je_monat` die Zeile `if titel not in gesehen` entfernen ->
    `test_doppelte_forderung_zaehlt_wie_bisher_die_erste` rot; den Filter `storniert_am__isnull=True` entfernen ->
    `test_gleichheit_ueber_alle_lagen` rot.
    """

    ZEITRAEUME = [(date(2025, 1, 1), date(2025, 12, 31)), (date(2025, 3, 15), date(2025, 9, 10)),
                  (date(2025, 5, 1), date(2025, 5, 31)), (date(2024, 11, 20), date(2026, 2, 3))]

    def _gleich(self, lage):
        from core.utils.billing import akonto_gestellt
        for von, bis in self.ZEITRAEUME:
            with self.subTest(lage=lage, von=von, bis=bis):
                self.assertEqual(akonto_gestellt(self.v, von, bis), _akonto_referenz(self.v, von, bis))

    def test_gleichheit_ueber_alle_lagen(self):
        from finance.booking import buche
        from finance.models import Buchung, DebitorenRechnung
        self._gleich('ohne Sollstellung')
        self._sollstellung(range(1, 7))
        self._gleich('halbes Jahr gestellt')
        self.v.nebenkosten = Decimal('250'); self.v.save()
        self._sollstellung(range(7, 13))
        self._gleich('Akonto unterjährig angepasst')
        maerz = DebitorenRechnung.objects.get(vertrag=self.v, titel='Miete & NK 03/2025')
        buche('3091', '1100', Decimal('80.00'), 'NK-Erlass Test', datum=date(2025, 3, 1), debitor=maerz)
        self._gleich('mit Erlass')
        DebitorenRechnung.objects.filter(vertrag=self.v, titel='Miete & NK 05/2025').update(status='storniert')
        self._gleich('eine Forderung storniert')
        juni = DebitorenRechnung.objects.get(vertrag=self.v, titel='Miete & NK 06/2025')
        Buchung.alle_organisationen.filter(debitoren_rechnung=juni).update(storniert_am=date(2025, 6, 20))
        self._gleich('Buchungen eines Monats storniert')
        self.v.ende = date(2025, 10, 15); self.v.save()
        self._gleich('Auszug mitten im Monat')

    def test_doppelte_forderung_zaehlt_wie_bisher_die_erste(self):
        """Zwei nicht stornierte Forderungen mit demselben Titel: Es zählt eine (die erste der Standardreihenfolge), nicht beide."""
        from core.utils.billing import akonto_gestellt
        from finance.models import DebitorenRechnung
        self._sollstellung(range(1, 4))
        DebitorenRechnung.objects.filter(vertrag=self.v, titel='Miete & NK 02/2025').update(titel='Miete & NK 03/2025')
        self._gleich('zwei Forderungen mit demselben Titel')
        betrag, monate = akonto_gestellt(self.v, date(2025, 3, 1), date(2025, 3, 31))
        self.assertEqual((betrag, monate), (Decimal('200.00'), 1))

    def test_zwei_abfragen_je_vertrag_unabhaengig_von_der_laenge(self):
        from core.utils.billing import akonto_gestellt
        self._sollstellung(range(1, 13))
        with self.assertNumQueries(2):
            akonto_gestellt(self.v, date(2025, 1, 1), date(2025, 12, 31))
        with self.assertNumQueries(2):
            akonto_gestellt(self.v, date(2024, 1, 1), date(2026, 12, 31))       # drei Jahre: gleich viele
        with self.assertNumQueries(1):                                          # ohne Forderung entfällt die zweite
            akonto_gestellt(self.v, date(2020, 1, 1), date(2020, 12, 31))
