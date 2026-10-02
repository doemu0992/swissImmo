"""MWST-Trennung: steuerfreie Wohnraummieten neben optiertem Gewerbe.

Eine Liegenschaft, zwei Wohnungen, ein optiertes Gewerbelokal, ein Rechnungslauf
(Sollstellung Oktober 2026). Geprüft wird, was der Mieter auf dem PDF sieht und
was im Hauptbuch steht:

- Wohnraum: keine MWST — weder auf der Rechnung noch auf 2200, auch wenn das Flag
  fälschlich gesetzt wurde (Option nach Art. 22 Abs. 2 lit. b MWSTG ausgeschlossen).
- Optiertes Gewerbe: Netto, Satz, MWST-Betrag und Brutto einzeln auf dem PDF;
  Miete UND Nebenkosten tragen die Steuer; die Steuer liegt auf 2200, der Ertrag
  bleibt netto auf 3010/3020.
"""
import io
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase, Client

from ._helfer import (_test_organisation, _team_user, _seed_konten, Mieter,
                      Liegenschaft, Einheit, Mietvertrag)


def _pdf_text(rechnung):
    from pypdf import PdfReader
    from core.services.debitor_qr import generate_debitor_qr_pdf
    pdf = generate_debitor_qr_pdf(rechnung)
    assert pdf and pdf.startswith(b'%PDF')
    return '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


class MischlaufTests(TestCase):
    def setUp(self):
        from finance.booking import ensure_kontenplan
        org = _test_organisation(firma='V AG', strasse='W 1', plz='8000', ort='ZH',
                                 iban='CH9300762011623852957', mwst_uid='CHE-123.456.789 MWST')
        ensure_kontenplan()
        self.lg = Liegenschaft.objects.create(organisation=org, strasse='Mischhaus 1', plz='8000',
                                              ort='Zürich', versicherungswert=Decimal('1'))

        def vertrag(bez, typ, vorname, netto, nk, **extra):
            e = Einheit.objects.create(liegenschaft=self.lg, bezeichnung=bez, typ=typ,
                                       flaeche_m2=Decimal('80'))
            m = Mieter.objects.create(typ='person', vorname=vorname, nachname='Test',
                                      email=f'{vorname.lower()}@example.ch',
                                      strasse='Seeweg 3', plz='8000', ort='Zürich')
            return Mietvertrag.objects.create(
                mieter=m, einheit=e, beginn=date(2026, 1, 1), status='aktiv',
                netto_mietzins=Decimal(netto), nebenkosten=Decimal(nk), **extra)

        self.whg_a = vertrag('2.5 Zi', 'whg', 'Anna', '1500', '200')
        # Fehlerfall: Flag versehentlich auch bei Wohnraum gesetzt.
        self.whg_b = vertrag('3.5 Zi', 'whg', 'Beat', '1800', '250',
                             mwst_pflichtig=True, mwst_satz=Decimal('8.1'))
        self.gewerbe = vertrag('Laden EG', 'gew', 'Carla', '2000', '300',
                               mwst_pflichtig=True, mwst_satz=Decimal('8.1'))

    def _lauf(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        self.assertEqual(run_sollstellung(2026, 10), 3)
        return {v: DebitorenRechnung.objects.get(vertrag=v, titel='Miete & NK 10/2026')
                for v in (self.whg_a, self.whg_b, self.gewerbe)}

    def _saldo(self, nummer, rechnung=None, seite='haben'):
        from finance.models import Buchung
        qs = Buchung.objects.filter(**{f'{seite}_konto__nummer': nummer})
        if rechnung is not None:
            qs = qs.filter(debitoren_rechnung=rechnung)
        return qs.aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')

    def test_flag_bei_wohnraum_wird_serverseitig_zurueckgesetzt(self):
        self.whg_b.refresh_from_db()
        self.assertFalse(self.whg_b.mwst_pflichtig)
        self.assertEqual(self.whg_b.mwst_satz_wirksam, Decimal('0'))
        self.assertEqual(self.gewerbe.mwst_satz_wirksam, Decimal('8.1'))

    def test_wohnraum_rechnung_ohne_mwst_auf_pdf_und_im_buch(self):
        rechnungen = self._lauf()
        for v, netto in ((self.whg_a, '1700.00'), (self.whg_b, '2050.00')):
            r = rechnungen[v]
            self.assertEqual(r.betrag, Decimal(netto))
            self.assertEqual(r.mwst_betrag, Decimal('0.00'))
            self.assertEqual(r.mwst_satz, Decimal('0.0'))
            text = _pdf_text(r)
            self.assertNotIn('MWST', text.upper().replace('MWST-NR', 'MWST'), text)
            self.assertNotIn('Netto', text)
            self.assertNotIn('Brutto', text)
            self.assertEqual(self._saldo('2200', r), Decimal('0.00'))

    def test_gewerbe_weist_netto_satz_mwst_und_brutto_aus(self):
        r = self._lauf()[self.gewerbe]
        # (2000 + 300) × 8.1 % = 186.30 — Nebenkosten tragen die MWST mit.
        self.assertEqual(r.mwst_betrag, Decimal('186.30'))
        self.assertEqual(r.mwst_satz, Decimal('8.1'))
        self.assertEqual(r.netto_betrag, Decimal('2300.00'))
        self.assertEqual(r.betrag, Decimal('2486.30'))
        text = _pdf_text(r)
        for erwartet in ('Nettobetrag', "CHF 2'300.00", 'MWST 8.1 %', 'CHF 186.30',
                         'Bruttobetrag', "CHF 2'486.30", 'CHE-123.456.789 MWST'):
            self.assertIn(erwartet, text)

    def test_buchhaltung_trennt_umsatz_und_geschuldete_mwst(self):
        r = self._lauf()[self.gewerbe]
        # Ertrag netto: Miete 3010, Nebenkosten 3020 …
        self.assertEqual(self._saldo('3010', r), Decimal('2000.00'))
        self.assertEqual(self._saldo('3020', r), Decimal('300.00'))
        # … Steuer auf dem Passivkonto 2200 (geschuldete MWST), nicht im Ertrag.
        self.assertEqual(self._saldo('2200', r), Decimal('186.30'))
        # Debitor schuldet brutto.
        self.assertEqual(self._saldo('1100', r, 'soll'), Decimal('2486.30'))
        # Auf 2200 liegt ausschliesslich die Steuer des Gewerbes.
        self.assertEqual(self._saldo('2200'), Decimal('186.30'))

    def test_nk_nachzahlung_gewerbe_mit_mwst_wohnraum_ohne(self):
        from finance.models import AbrechnungsPeriode, NebenkostenBeleg, DebitorenRechnung
        for v in (self.whg_a, self.gewerbe):
            v.nebenkosten = Decimal('0'); v.nk_abrechnungsart = 'akonto'; v.save()
        p = AbrechnungsPeriode.objects.create(
            liegenschaft=self.lg, bezeichnung='NK 2025',
            start_datum=date(2025, 1, 1), ende_datum=date(2025, 12, 31))
        for v in (self.whg_a, self.gewerbe):
            v.beginn = date(2024, 1, 1); v.save()
        self.whg_b.beginn = date(2030, 1, 1); self.whg_b.save()   # keine Beteiligung 2025
        NebenkostenBeleg.objects.create(periode=p, text='Heizung', betrag=Decimal('1200'),
                                        datum=date(2025, 6, 1), verteilschluessel='m2')
        c = Client(); c.force_login(_team_user())
        c.post(f'/neu/nebenkosten/{p.id}/verbuchen/')
        wohn = DebitorenRechnung.objects.get(vertrag=self.whg_a, titel__icontains='Nachzahlung')
        gew = DebitorenRechnung.objects.get(vertrag=self.gewerbe, titel__icontains='Nachzahlung')
        self.assertEqual(wohn.mwst_betrag, Decimal('0.00'))
        self.assertEqual(wohn.betrag, wohn.netto_betrag)
        self.assertEqual(self._saldo('2200', wohn), Decimal('0.00'))
        self.assertGreater(gew.mwst_betrag, Decimal('0'))
        self.assertEqual(gew.mwst_betrag, (gew.netto_betrag * Decimal('8.1') / 100).quantize(Decimal('0.01')))
        self.assertEqual(self._saldo('2200', gew), gew.mwst_betrag)
        self.assertEqual(self._saldo('3020', gew), gew.netto_betrag)

    def test_lauf_ist_idempotent_und_mwst_verdoppelt_sich_nicht(self):
        from core.services.automation import run_sollstellung
        self._lauf()
        self.assertEqual(run_sollstellung(2026, 10), 0)
        self.assertEqual(self._saldo('2200'), Decimal('186.30'))
