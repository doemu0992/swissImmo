"""Preset «bexio (über importly.ch)» im Buchungsjournal (Roadmap 4.2).

Die Spezifikation (belegt am 11.11.2026 nach https://importly.ch/blog/buchungen-importieren-manuelle-buchung): bexio importiert
Buchungen nicht selbst per CSV; der Zusatzdienst importly.ch liest eine CSV, deren Spalten über die Überschrift zugeordnet
werden: UTF-8, Komma als Trenner, Datum TT.MM.JJJJ, Betrag mit Punkt, Währung, `MWST Konto` Pflicht bei gesetztem `MWST Code`.

Gegenproben: das BOM zulassen -> `test_kein_bom_vor_der_kopfzeile` rot; das Datum auf yyyy-mm-dd -> `test_datum_ist_tt_mm_jjjj`
rot; `MWST Konto` leer lassen -> `test_mwst_konto_ist_pflicht_sobald_ein_code_steht` rot.
"""
import csv
import io
from datetime import date
from decimal import Decimal

from core.tenancy import organisation_kontext

from .test_daten_export import EINSTELLUNG, JOURNAL, ZEITRAUM, _Basis

KOPF = ['Belegnummer', 'Datum', 'Beschreibung', 'Betrag', 'Währung', 'Wechselkurs', 'Soll', 'Haben', 'MWST Code', 'MWST Konto']


class BexioTests(_Basis):

    def _export(self, rolle='verwalter', **zeitraum):
        daten = dict(zeitraum or ZEITRAUM)
        daten['preset'] = 'bexio'
        return self.client_von(rolle).post(JOURNAL, daten)

    def _zeilen(self, antwort=None):
        antwort = antwort or self._export()
        return list(csv.reader(io.StringIO(antwort.content.decode('utf-8')), delimiter=','))

    def test_kopfzeile_nach_spezifikation(self):
        self.assertEqual(self._zeilen()[0], KOPF)

    def test_komma_als_trenner_und_dateiname(self):
        antwort = self._export()
        self.assertEqual(antwort.content.decode('utf-8').split('\r\n')[0], ','.join(KOPF))
        self.assertIn('bexio_Buchungen_', antwort['Content-Disposition'])
        self.assertTrue(antwort['Content-Disposition'].endswith('.csv"'))

    def test_kein_bom_vor_der_kopfzeile(self):
        """Mit BOM hiesse das erste Feld «\\ufeffBelegnummer» und die Zuordnung über die Überschrift fände es nicht."""
        antwort = self._export()
        self.assertFalse(antwort.content.startswith(b'\xef\xbb\xbf'))
        self.assertTrue(antwort.content.startswith(b'Belegnummer,'))

    def test_datum_ist_tt_mm_jjjj_und_betrag_mit_punkt(self):
        jan = [z for z in self._zeilen() if z[2].startswith('Miete Januar')][0]
        self.assertEqual((jan[1], jan[3]), ('01.01.2024', '1500.00'))
        dez = [z for z in self._zeilen() if z[2] == 'Miete Dezember'][0]
        self.assertEqual(dez[3], '1500.50')

    def test_waehrung_chf_und_wechselkurs_leer(self):
        for z in self._zeilen()[1:]:
            self.assertEqual((z[4], z[5]), ('CHF', ''))

    def test_preset_ueberschreibt_die_einstellung_der_organisation(self):
        self.client_von('buchhaltung').post(EINSTELLUNG, {
            'trenner': ';', 'datumsformat': 'iso', 'dezimal': ',', 'konten': '', 'spalte_datum': 'Buchungsdatum'})
        zeilen = self._zeilen()
        self.assertEqual(zeilen[0], KOPF)
        jan = [z for z in zeilen if z[2].startswith('Miete Januar')][0]
        self.assertEqual((jan[1], jan[3]), ('01.01.2024', '1500.00'))

    def test_beschreibung_mit_komma_und_anfuehrungszeichen_bleibt_ein_feld(self):
        roh = self._export().content.decode('utf-8')
        zeilen = self._zeilen()
        jan = [z for z in zeilen if z[2].startswith('Miete Januar')][0]
        self.assertEqual(jan[2], 'Miete Januar; "Zürich"')                  # Umlaut unversehrt
        self.assertTrue(all(len(z) == 10 for z in zeilen), [len(z) for z in zeilen])
        self.assertIn('"Miete Januar; ""Zürich"""', roh)                    # Anführungszeichen verdoppelt

    def test_soll_haben_sind_die_kontonummern_der_zuordnung(self):
        self.client_von('buchhaltung').post(EINSTELLUNG, {
            'trenner': ';', 'datumsformat': 'ch', 'dezimal': '.', 'konten': '9101;1020\n9102;3000\n'})
        jan = [z for z in self._zeilen() if z[2].startswith('Miete Januar')][0]
        self.assertEqual((jan[6], jan[7]), ('1020', '3000'))

    def test_mwst_konto_ist_pflicht_sobald_ein_code_steht(self):
        self.client_von('buchhaltung').post(EINSTELLUNG, {
            'trenner': ';', 'datumsformat': 'ch', 'dezimal': '.', 'konten': '9101;1020\n9102;3000;VB81\n'})
        jan = [z for z in self._zeilen() if z[2].startswith('Miete Januar')][0]
        self.assertEqual((jan[8], jan[9]), ('VB81', '3000'))                 # Code vom Habenkonto -> MWST Konto = Habenkonto
        self.client_von('buchhaltung').post(EINSTELLUNG, {
            'trenner': ';', 'datumsformat': 'ch', 'dezimal': '.', 'konten': '9101;1020;VB22\n9102;3000\n'})
        jan = [z for z in self._zeilen() if z[2].startswith('Miete Januar')][0]
        self.assertEqual((jan[8], jan[9]), ('VB22', '1020'))                 # Code vom Sollkonto -> MWST Konto = Sollkonto
        for z in self._zeilen()[1:]:
            if z[8]:
                self.assertTrue(z[9], z)
            else:
                self.assertEqual(z[9], '')

    def test_laengster_text_bleibt_unversehrt_und_die_grenzen_gelten(self):
        """Das Buchungsfeld fasst höchstens 255 Zeichen (PostgreSQL lehnt mehr ab): genau so lang darf die Beschreibung sein."""
        from finance.models import Buchung
        with organisation_kontext(self.org):
            Buchung.objects.create(datum=date(2024, 3, 3), beleg_text='x' * 255, soll_konto=self.bank,
                                   haben_konto=self.ertrag, betrag=Decimal('5.00'))
        lang = [z for z in self._zeilen()[1:] if z[2].startswith('xxx')][0]
        self.assertEqual(len(lang[2]), 255)
        self.assertLessEqual(len(lang[0]), 100)

    def test_zeitraum_und_mandantentrennung(self):
        zeilen = self._zeilen(self._export(von='2000-01-01', bis='2100-01-01'))
        texte = [z[2] for z in zeilen[1:]]
        self.assertIn('Testbuchung A', texte)
        self.assertNotIn('Testbuchung B', texte)

    def test_format_erscheint_in_der_auswahl(self):
        antwort = self.client_von('buchhaltung').get('/neu/einstellungen/daten/export/')
        self.assertContains(antwort, 'data-testid="daten-preset-bexio"')
