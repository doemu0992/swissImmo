"""Preset «Banana Buchhaltung» im Buchungsjournal (Etappe 4).

Die Spezifikation (belegt am 29.10.2026 nach https://www.banana.ch/doc/en/node/9947): Datei «Text file with
column headers», Tabulator als Trennzeichen, Kopfzeile mit den englischen Feldnamen (Gross-/Kleinschreibung
zählt), Datum yyyy-mm-dd, Betrag mit Punkt, UTF-8, dazu `ExternalReference` eindeutig je Buchung.

Gegenproben: In `datenexport.journal_csv` das Trennzeichen des Presets auf `;` setzen: `test_trennzeichen_ist_tabulator`
ist rot. Die Kopfzeile ändern (`Doc` -> `doc`): `test_kopfzeile_nach_spezifikation` ist rot. Die ExternalReference
auf das Datum allein stützen (zwei Buchungen am selben Tag): `test_external_reference_ist_eindeutig` ist rot. Das BOM
beim Preset zulassen: `test_kein_bom_vor_der_kopfzeile` ist rot.
"""
import csv
import io
import re
from datetime import date
from decimal import Decimal

from core.services import datenexport
from core.tenancy import organisation_kontext

from .test_daten_export import EINSTELLUNG, JOURNAL, ZEITRAUM, _Basis

KOPF = ['Date', 'Doc', 'Description', 'AccountDebit', 'AccountCredit', 'Amount', 'VatCode', 'ExternalReference']


class BananaTests(_Basis):

    def _export(self, rolle='verwalter', preset='banana', **zeitraum):
        daten = dict(zeitraum or ZEITRAUM)
        if preset:
            daten['preset'] = preset
        return self.client_von(rolle).post(JOURNAL, daten)

    def _zeilen(self, antwort=None):
        antwort = antwort or self._export()
        return list(csv.reader(io.StringIO(antwort.content.decode('utf-8')), delimiter='\t'))

    def test_kopfzeile_nach_spezifikation(self):
        self.assertEqual(self._zeilen()[0], KOPF)

    def test_trennzeichen_ist_tabulator(self):
        roh = self._export().content.decode('utf-8')
        kopf = roh.split('\r\n')[0]
        self.assertEqual(kopf, '\t'.join(KOPF))
        self.assertNotIn(';', kopf)
        for zeile in roh.split('\r\n')[1:]:
            if zeile:
                self.assertEqual(zeile.count('\t'), 7, zeile)

    def test_kein_bom_vor_der_kopfzeile(self):
        """Mit BOM hiesse das erste Feld «\\ufeffDate» und Banana fände es nicht."""
        self.assertFalse(self._export().content.startswith(b'\xef\xbb\xbf'))
        self.assertTrue(self._export().content.startswith(b'Date\t'))

    def test_datum_ist_yyyy_mm_dd(self):
        zeilen = self._zeilen()[1:]
        self.assertTrue(zeilen)
        for z in zeilen:
            self.assertRegex(z[0], r'^\d{4}-\d{2}-\d{2}$')
        jan = [z for z in zeilen if z[2].startswith('Miete Januar')][0]
        self.assertEqual(jan[0], '2024-01-01')

    def test_preset_ueberschreibt_die_einstellung_der_organisation(self):
        """Semikolon, Komma als Dezimalzeichen, TT.MM.JJJJ und eigene Überschriften der Organisation gelten nicht."""
        self.client_von('buchhaltung').post(EINSTELLUNG, {
            'trenner': ';', 'datumsformat': 'ch', 'dezimal': ',', 'konten': '', 'spalte_datum': 'Buchungsdatum'})
        zeilen = self._zeilen()
        self.assertEqual(zeilen[0], KOPF)
        jan = [z for z in zeilen if z[2].startswith('Miete Januar')][0]
        self.assertEqual((jan[0], jan[5]), ('2024-01-01', '1500.00'))

    def test_betrag_mit_punkt_ohne_tausendertrenner(self):
        dez = [z for z in self._zeilen() if z[2] == 'Miete Dezember'][0]
        self.assertEqual(dez[5], '1500.50')

    def test_felder_sind_die_der_buchung(self):
        jan = [z for z in self._zeilen() if z[2].startswith('Miete Januar')][0]
        self.assertEqual(jan[1], str(self.b_jan.beleg_nr))
        self.assertEqual(jan[2], 'Miete Januar; "Zürich"')           # Umlaut unversehrt, UTF-8
        self.assertEqual((jan[3], jan[4]), ('9101', '9102'))           # Soll = AccountDebit, Haben = AccountCredit

    def test_external_reference_ist_eindeutig(self):
        from finance.models import Buchung
        with organisation_kontext(self.org):
            for i in range(3):                                          # drei Buchungen am selben Tag, gleicher Betrag
                Buchung.objects.create(datum=date(2024, 5, 5), beleg_text='Gleich', soll_konto=self.bank,
                                       haben_konto=self.ertrag, betrag=Decimal('10.00'))
        zeilen = self._zeilen()[1:]
        refs = [z[7] for z in zeilen]
        self.assertEqual(len(refs), len(set(refs)), 'ExternalReference ist nicht eindeutig')
        for z in zeilen:
            self.assertRegex(z[7], r'^immoswiss-\d{4}-\d+$')
        self.assertIn(f'immoswiss-2024-{self.b_jan.pk}', refs)

    def test_external_reference_gilt_auch_fuer_storno_zeilen(self):
        from finance.booking import storniere_buchung
        with organisation_kontext(self.org):
            storniere_buchung(self.b_jan, datum=date(2024, 6, 1))
        zeilen = self._zeilen()[1:]
        refs = [z[7] for z in zeilen]
        self.assertEqual(len(refs), len(set(refs)))
        storno = [z for z in zeilen if z[2].startswith('Storno Beleg')]
        self.assertEqual(len(storno), 1)
        self.assertEqual(storno[0][3:6], ['9102', '9101', '1500.00'])

    def test_external_reference_ist_zwischen_exporten_stabil(self):
        """Zweimal exportiert: dieselbe Buchung trägt dieselbe Referenz (sonst gäbe es Dubletten in Banana)."""
        a = {z[1]: z[7] for z in self._zeilen()[1:]}
        b = {z[1]: z[7] for z in self._zeilen()[1:]}
        self.assertEqual(a, b)

    def test_tabulator_und_umbruch_im_text_verschieben_keine_spalten(self):
        from finance.models import Buchung
        with organisation_kontext(self.org):
            Buchung.objects.create(datum=date(2024, 3, 3), beleg_text='Miete\tMärz\r\nzweite Zeile',
                                   soll_konto=self.bank, haben_konto=self.ertrag, betrag=Decimal('5.00'))
        zeilen = self._zeilen()[1:]
        self.assertTrue(all(len(z) == 8 for z in zeilen), [len(z) for z in zeilen])
        self.assertIn('Miete März zweite Zeile', [z[2] for z in zeilen])

    def test_formel_im_text_wird_entschaerft(self):
        from finance.models import Buchung
        with organisation_kontext(self.org):
            Buchung.objects.create(datum=date(2024, 3, 3), beleg_text='=HYPERLINK("http://x")',
                                   soll_konto=self.bank, haben_konto=self.ertrag, betrag=Decimal('1'))
        self.assertIn('\'=HYPERLINK("http://x")', [z[2] for z in self._zeilen()[1:]])

    def test_kontenzuordnung_und_vatcode_gelten_weiter(self):
        self.client_von('buchhaltung').post(EINSTELLUNG, {
            'trenner': ';', 'datumsformat': 'ch', 'dezimal': '.', 'konten': '9101;1020\n9102;3000;M81\n'})
        jan = [z for z in self._zeilen() if z[2].startswith('Miete Januar')][0]
        self.assertEqual((jan[3], jan[4], jan[6]), ('1020', '3000', 'M81'))

    def test_zeitraum_und_mandantentrennung(self):
        zeilen = self._zeilen(self._export(von='2000-01-01', bis='2100-01-01'))
        texte = [z[2] for z in zeilen[1:]]
        self.assertIn('Testbuchung A', texte)
        self.assertNotIn('Testbuchung B', texte)
        self.assertNotIn('Miete 2025', [z[2] for z in self._zeilen()[1:]])

    def test_dateiname_typ_und_protokoll(self):
        from core.models import AktivitaetsLog
        antwort = self._export('buchhaltung')
        self.assertIn('.txt', antwort['Content-Disposition'])
        self.assertIn('Banana', antwort['Content-Disposition'])
        with organisation_kontext(self.org):
            eintrag = AktivitaetsLog.objects.get(aktion='Buchungsjournal exportiert')
        self.assertIn('Banana Buchhaltung', eintrag.details)

    def test_unbekanntes_preset_wird_abgewiesen(self):
        from core.models import AktivitaetsLog
        antwort = self._export(preset='abacus')
        self.assertEqual(antwort.status_code, 302)
        with organisation_kontext(self.org):
            self.assertFalse(AktivitaetsLog.objects.filter(aktion='Buchungsjournal exportiert').exists())

    def test_ohne_preset_bleibt_die_freie_zuordnung(self):
        """Das Preset ist zusätzlich: Ohne Wahl exportiert die Seite wie bisher (Semikolon, BOM, Vorgabe-Überschriften)."""
        antwort = self._export(preset=None)
        self.assertTrue(antwort.content.startswith(b'\xef\xbb\xbf'))
        kopf = antwort.content.decode('utf-8-sig').split('\r\n')[0]
        self.assertEqual(kopf, 'Buchungsdatum;Belegnummer;Soll;Haben;Betrag;Text;MWST-Code')

    def test_rollen(self):
        for rolle in ('inhaber', 'verwalter', 'buchhaltung'):
            self.assertEqual(self._export(rolle).status_code, 200, rolle)
        for rolle in ('sachbearbeiter', 'lesezugriff', 'hauswart'):
            self.assertEqual(self._export(rolle).status_code, 403, rolle)

    def test_dienst_kennt_genau_ein_preset(self):
        self.assertEqual(list(datenexport.PRESETS), ['banana'])
        self.assertEqual(list(datenexport.BANANA_SPALTEN), KOPF)

    def test_seite_bietet_das_preset_an_und_erklaert_den_importweg(self):
        html = self.client_von('buchhaltung').get('/neu/einstellungen/daten/export/').content.decode()
        self.assertIn('name="preset" value="banana"', html)
        self.assertIn('name="preset" value=""', html)
        self.assertIn('Aktionen > In Buchhaltung importieren > Text file with column headers', html)
        self.assertIn('ExternalReference', html)
        self.assertTrue(re.search(r'Banana Buchhaltung', html))
