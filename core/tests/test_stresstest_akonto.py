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
