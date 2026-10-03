"""Mietzinsanpassung: Referenzzins (Überwälzungstabelle BWO/HEV), LIK 40 %, Kostenpauschale,
5-Wohnungen-Massenanpassung und die Begründung im amtlichen Formular."""
import io
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from pypdf import PdfReader

from core.services import mietzins_rechner as rz

from ._helfer import _basis_objekte

D = Decimal


class ReferenzzinsTabelleTests(SimpleTestCase):
    def test_senkung_folgt_der_ueberwaelzungstabelle(self):
        # Ausgangssatz 1.50 → Zeile der HEV-Tabelle; 2.91 / 5.66 / 8.26 / 10.71 / 13.04
        for neu, soll in (('1.25', '-2.91'), ('1.00', '-5.66'), ('0.75', '-8.26'),
                          ('0.50', '-10.71'), ('0.25', '-13.04')):
            self.assertEqual(rz.referenzzins_prozent(D('1.50'), D(neu)), D(soll), neu)

    def test_erhoehung_ist_drei_prozent_je_schritt(self):
        for neu, soll in (('1.50', '3.00'), ('1.75', '6.00'), ('2.50', '15.00')):
            self.assertEqual(rz.referenzzins_prozent(D('1.25'), D(neu)), D(soll), neu)

    def test_unveraendert(self):
        self.assertEqual(rz.referenzzins_prozent(D('1.25'), D('1.25')), D('0.00'))

    def test_lik_vierzig_prozent_der_veraenderung(self):
        self.assertEqual(rz.lik_prozent(D('100.0'), D('105.0')), D('2.00'))
        self.assertEqual(rz.lik_prozent(D('104.4'), D('108.3')), D('1.49'))   # 3.736 % × 0.4
        self.assertEqual(rz.lik_prozent(D('105.0'), D('105.0')), D('0.00'))

    def test_lik_rueckgang_wird_verrechnet(self):
        self.assertEqual(rz.lik_prozent(D('100.0'), D('95.0')), D('-2.00'))

    def test_kostenpauschale_pro_jahr(self):
        self.assertEqual(rz.kostensteigerung_pauschal_pct(date(2024, 1, 1), date(2026, 1, 1)), D('1.00'))
        self.assertEqual(rz.kostensteigerung_pauschal_pct(date(2024, 1, 1), date(2024, 7, 1)), D('0.25'))
        self.assertEqual(rz.kostensteigerung_pauschal_pct(date(2024, 1, 15), date(2025, 1, 14)), D('0.46'))
        self.assertEqual(rz.kostensteigerung_pauschal_pct(None, date(2026, 1, 1)), D('0.00'))


class MassenanpassungSzenarioTests(TestCase):
    """Liegenschaft mit 5 Wohnungen, Referenzzins 1.50 % → 1.25 %."""

    NETTO = ('1450.00', '1620.00', '1875.00', '2210.00', '990.00')

    def _fuenf(self):
        from crm.models import Mieter
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag
        lg, _e, _m, v0 = _basis_objekte()
        v0.delete()
        vertraege = []
        for i, netto in enumerate(self.NETTO, start=1):
            e = Einheit.objects.create(liegenschaft=lg, bezeichnung=f'{i}. OG', typ='whg',
                                       nettomiete_aktuell=D(netto), nebenkosten_aktuell=D('200'))
            m = Mieter.objects.create(typ='person', vorname='M', nachname=f'Mieter{i}',
                                      email=f'm{i}@example.ch', strasse='X 1', plz='8000', ort='Zürich')
            vertraege.append(Mietvertrag.objects.create(
                mieter=m, einheit=e, beginn=date(2023, 1, 1), netto_mietzins=D(netto),
                nebenkosten=D('200'), status='aktiv', basis_referenzzinssatz=D('1.50'),
                basis_lik_punkte=D('106.2'), basis_lik_stand=date(2023, 12, 1)))
        return vertraege

    def test_senkungsanspruch_2_91_und_rappenrundung(self):
        from rentals.services import berechne_mietpotenzial
        for v in self._fuenf():
            r = berechne_mietpotenzial(v, D('1.25'), D('106.2'))     # LIK unverändert
            self.assertEqual(r['zins_pct'], D('-2.91'))
            self.assertEqual(r['delta_prozent'], D('-2.91'))
            self.assertEqual(r['action'], 'DOWN')
            self.assertEqual(r['neu_chf'] % D('0.05'), 0, r['neu_chf'])
            exakt = v.netto_mietzins * (1 - D('0.0291'))
            self.assertLessEqual(abs(r['neu_chf'] - exakt), D('0.025'))

    def test_teuerung_verrechnet_basis_lik_mit_aktuellem_lik(self):
        from rentals.services import berechne_mietpotenzial
        v = self._fuenf()[0]
        r = berechne_mietpotenzial(v, D('1.25'), D('108.3'))         # 106.2 → 108.3 = +1.977 %
        self.assertEqual(r['lik_pct'], D('0.79'))                    # 40 % davon
        self.assertEqual(r['delta_prozent'], D('-2.12'))             # -2.91 + 0.79
        self.assertEqual(r['neu_chf'], D('1419.25'))                 # 1450 × 0.9788 = 1419.26

    def test_bereits_weitergegebener_schritt_wird_nicht_doppelt_verrechnet(self):
        from rentals.models import MietzinsAnpassung
        from rentals.services import berechne_mietpotenzial
        v = self._fuenf()[0]
        MietzinsAnpassung.objects.create(
            vertrag=v, wirksam_ab=date(2026, 1, 1), neuer_netto_mietzins=D('1407.80'),
            alter_netto_mietzins=D('1450.00'), alter_referenzzinssatz=D('1.50'),
            neuer_referenzzinssatz=D('1.25'), alter_lik_index=D('106.2'), neuer_lik_index=D('106.2'))
        v = type(v).objects.get(pk=v.pk)
        v.netto_mietzins = D('1407.80')
        r = berechne_mietpotenzial(v, D('1.25'), D('106.2'))
        self.assertEqual(r['zins_pct'], D('0.00'))
        self.assertEqual(r['action'], 'OK')

    def test_anteile_summieren_exakt_zum_total(self):
        from rentals.services import berechne_mietpotenzial
        v = self._fuenf()[2]
        r = berechne_mietpotenzial(v, D('1.50'), D('108.3'), D('0.5'))
        self.assertEqual(r['zins_pct'] + r['lik_pct'] + r['kosten_pct'], r['delta_prozent'])


class FormularBegruendungTests(TestCase):
    def _daten(self, v, **extra):
        from rentals.services import berechne_mietpotenzial
        v.basis_referenzzinssatz = D('1.50'); v.basis_lik_punkte = D('106.2')
        pot = berechne_mietpotenzial(v, D('1.25'), D('108.3'), D('0.5'))
        d = {'alt_netto': v.netto_mietzins, 'neu_netto': pot['neu_chf'], 'nebenkosten': v.nebenkosten,
             'alt_zins': D('1.50'), 'neu_zins': D('1.25'), 'alt_lik': D('106.2'), 'neu_lik': D('108.3'),
             'zins_pct': pot['zins_pct'], 'lik_pct': pot['lik_pct'], 'kosten_pct': pot['kosten_pct'],
             'total_pct': pot['delta_prozent'], 'wirksam_ab': date(2027, 1, 1), 'begruendung': ''}
        d.update(extra)
        return d, pot

    def _text(self, pdf):
        return ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)

    def test_pdf_nennt_alte_neue_miete_anteile_und_rechtsmittel(self):
        from core.services.mietzins_formular import generate_amtliches_formular_pdf
        _lg, _e, _m, v = _basis_objekte()
        d, pot = self._daten(v)
        text = self._text(generate_amtliches_formular_pdf(v, d))
        self.assertIn("1'500.00", text)                                   # alte Miete
        self.assertIn(f"{pot['neu_chf']:,.2f}".replace(',', "'"), text)   # neue Miete
        self.assertIn('-2.91 %', text)                                    # Anteil Referenzzins
        self.assertIn('+0.79 %', text)                                    # Anteil Teuerung
        self.assertIn('+0.50 %', text)                                    # Anteil Kosten
        self.assertIn('Rechtsmittelbelehrung', text)
        self.assertIn('30 Tagen', text)

    def test_so_formular_nennt_anteile_und_rechtsmittel(self):
        from core.services.amtliche_formulare_so import mietzins_so_pdf
        _lg, _e, _m, v = _basis_objekte()
        d, _pot = self._daten(v)
        text = self._text(mietzins_so_pdf(v, d))
        self.assertIn('-2.91 %', text)
        self.assertIn('Rechtsmittelbelehrung', text)
        self.assertIn('1500.00', text.replace("'", ''))                # alte Miete
