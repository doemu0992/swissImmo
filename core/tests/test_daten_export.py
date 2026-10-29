"""Gesamtexport und Buchungsjournal (Audit FUNK-13).

* Buchungsjournal als CSV: Spalten, Zeitraum, Storno, Einstellungen (Überschriften, Kontenzuordnung,
  MWST-Code), Buchungen werden nur gelesen
* Mandatsexport als ZIP: CSV und JSON je Tabelle, Dokumente, ohne Geheimnisse
* Zugriff: Journal Inhaber/Verwalter/Buchhaltung, Mandatsexport Inhaber/Verwalter
* Audit-Log: jeder Export steht davor im Protokoll; ohne Eintrag wird nichts ausgeliefert
* Mandantentrennung: nie Daten einer anderen Organisation, auch nicht mit Superuser
"""
import csv
import io
import json
import shutil
import tempfile
import zipfile
from datetime import date
from decimal import Decimal
from unittest import mock

from django.core.files.base import ContentFile
from django.test import override_settings

from core.services import datenexport
from core.tenancy import organisation_kontext

from ._rollen import RollenBasis

JOURNAL = '/neu/einstellungen/daten/export/journal/'
MANDAT = '/neu/einstellungen/daten/export/mandat/'
EINSTELLUNG = '/neu/einstellungen/daten/export/format/'
ZEITRAUM = {'von': '2024-01-01', 'bis': '2024-12-31'}


def _csv(antwort):
    text = antwort.content.decode('utf-8-sig')
    return list(csv.reader(io.StringIO(text), delimiter=';'))


class _Basis(RollenBasis):
    def setUp(self):
        super().setUp()
        from finance.models import Buchung, Buchungskonto
        with organisation_kontext(self.org):
            self.bank = Buchungskonto.objects.get(nummer='9101')
            self.ertrag = Buchungskonto.objects.get(nummer='9102')
            self.b_jan = Buchung.objects.create(datum=date(2024, 1, 1), beleg_text='Miete Januar; "Zürich"',
                                                soll_konto=self.bank, haben_konto=self.ertrag, betrag=Decimal('1500.00'))
            self.b_dez = Buchung.objects.create(datum=date(2024, 12, 31), beleg_text='Miete Dezember',
                                                soll_konto=self.bank, haben_konto=self.ertrag, betrag=Decimal('1500.50'))
            self.b_ausser = Buchung.objects.create(datum=date(2025, 1, 1), beleg_text='Miete 2025',
                                                   soll_konto=self.bank, haben_konto=self.ertrag, betrag=Decimal('99.00'))


class JournalTests(_Basis):
    def _export(self, rolle='verwalter', **zeitraum):
        return self.client_von(rolle).post(JOURNAL, zeitraum or ZEITRAUM)

    def test_spalten_zeitraum_und_betrag(self):
        antwort = self._export()
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('text/csv', antwort['Content-Type'])
        zeilen = _csv(antwort)
        self.assertEqual(zeilen[0], ['Buchungsdatum', 'Belegnummer', 'Soll', 'Haben', 'Betrag', 'Text', 'MWST-Code'])
        # Fixture-Buchung vom 01.02.2024 + zwei neue im Zeitraum; die vom 01.01.2025 nicht
        texte = [z[5] for z in zeilen[1:]]
        self.assertEqual(sorted(texte), sorted(['Testbuchung A', 'Miete Januar; "Zürich"', 'Miete Dezember']))
        jan = [z for z in zeilen if z[5].startswith('Miete Januar')][0]
        self.assertEqual(jan[:5], ['01.01.2024', str(self.b_jan.beleg_nr), '9101', '9102', '1500.00'])
        self.assertEqual(jan[6], '')

    def test_grenzen_sind_eingeschlossen(self):
        zeilen = _csv(self._export(von='2024-12-31', bis='2024-12-31'))
        self.assertEqual([z[5] for z in zeilen[1:]], ['Miete Dezember'])
        zeilen = _csv(self._export(von='2025-01-01', bis='2025-01-01'))
        self.assertEqual([z[5] for z in zeilen[1:]], ['Miete 2025'])

    def test_storno_steht_als_eigene_zeile(self):
        from finance.booking import storniere_buchung
        with organisation_kontext(self.org):
            storniere_buchung(self.b_jan, datum=date(2024, 6, 1))
        zeilen = _csv(self._export())
        storno = [z for z in zeilen if z[5].startswith('Storno Beleg')]
        self.assertEqual(len(storno), 1)
        self.assertEqual(storno[0][2:5], ['9102', '9101', '1500.00'])      # Soll/Haben vertauscht, Betrag positiv

    def test_nur_eigene_buchungen(self):
        """Die Buchung von B steht nie im Journal von A (auch mit passendem Datum)."""
        zeilen = _csv(self._export(von='2000-01-01', bis='2100-01-01'))
        texte = [z[5] for z in zeilen[1:]]
        self.assertIn('Testbuchung A', texte)
        self.assertNotIn('Testbuchung B', texte)
        b_zeilen = _csv(self.client_von('verwalter').post(JOURNAL, {'von': '2000-01-01', 'bis': '2100-01-01'}))
        self.assertNotIn('9201', [c for z in b_zeilen for c in z[2:4]])        # Konten von B (9201/9202)

    def test_buchungen_werden_nur_gelesen(self):
        from finance.models import Buchung
        with organisation_kontext(self.org):
            vorher = list(Buchung.objects.order_by('pk').values_list('pk', 'betrag', 'storniert_am', 'beleg_nr'))
        self._export()
        with organisation_kontext(self.org):
            self.assertEqual(list(Buchung.objects.order_by('pk').values_list('pk', 'betrag', 'storniert_am', 'beleg_nr')), vorher)

    def test_lesen_ohne_schreibzugriff_auf_buchungen(self):
        """Der Export ruft nirgends save/update/delete der Buchung auf."""
        from finance.models import Buchung
        with mock.patch.object(Buchung, 'save', side_effect=AssertionError('Buchung geschrieben')), \
                mock.patch('finance.models.BuchungQuerySet.update', side_effect=AssertionError('update')), \
                mock.patch('finance.models.BuchungQuerySet.delete', side_effect=AssertionError('delete')):
            self.assertEqual(self._export().status_code, 200)

    def test_rollen(self):
        for rolle in ('inhaber', 'verwalter', 'buchhaltung', 'buchhaltung2'):
            self.assertEqual(self._export(rolle).status_code, 200, rolle)
        for rolle in ('sachbearbeiter', 'lesezugriff', 'hauswart'):
            self.assertEqual(self._export(rolle).status_code, 403, rolle)

    def test_get_liefert_keinen_export(self):
        antwort = self.client_von('verwalter').get(JOURNAL)
        self.assertEqual(antwort.status_code, 302)

    def test_ungueltiger_zeitraum(self):
        from core.models import AktivitaetsLog
        for roh in ({'von': '', 'bis': ''}, {'von': '31.13.2024', 'bis': '2024-12-31'},
                    {'von': '2024-12-31', 'bis': '2024-01-01'}):
            antwort = self.client_von('verwalter').post(JOURNAL, roh)
            self.assertEqual(antwort.status_code, 302, roh)
        with organisation_kontext(self.org):
            self.assertFalse(AktivitaetsLog.objects.filter(aktion='Buchungsjournal exportiert').exists())

    def test_audit_log_mit_zeitraum_und_benutzer(self):
        from core.models import AktivitaetsLog
        self._export('buchhaltung')
        with organisation_kontext(self.org):
            eintrag = AktivitaetsLog.objects.get(aktion='Buchungsjournal exportiert')
        self.assertEqual(eintrag.benutzer, self.benutzer['buchhaltung'])
        self.assertEqual(eintrag.kategorie, 'sicherheit')
        self.assertIn('01.01.2024 bis 31.12.2024', eintrag.details)
        self.assertIn('3 Buchungen', eintrag.details)
        self.assertEqual(eintrag.organisation_id, self.org.pk)
        with organisation_kontext(self.b.organisation):
            self.assertFalse(AktivitaetsLog.objects.filter(aktion='Buchungsjournal exportiert').exists())

    def test_ohne_audit_eintrag_keine_auslieferung(self):
        from core.models import AktivitaetsLog
        c = self.client_von('verwalter')
        with mock.patch.object(AktivitaetsLog.objects.__class__, 'create', side_effect=RuntimeError('Log kaputt')):
            antwort = c.post(JOURNAL, ZEITRAUM)
        self.assertEqual(antwort.status_code, 500)
        self.assertNotIn(b'Buchungsdatum', antwort.content)

    def test_formel_in_buchungstext_wird_entschaerft(self):
        from finance.models import Buchung
        with organisation_kontext(self.org):
            Buchung.objects.create(datum=date(2024, 3, 3), beleg_text='=HYPERLINK("http://x")', soll_konto=self.bank,
                                   haben_konto=self.ertrag, betrag=Decimal('1'))
        texte = [z[5] for z in _csv(self._export())]
        self.assertIn('\'=HYPERLINK("http://x")', texte)


class EinstellungTests(_Basis):
    def _speichere(self, rolle='buchhaltung', **felder):
        daten = {'trenner': ';', 'datumsformat': 'ch', 'dezimal': '.', 'konten': ''}
        daten.update(felder)
        return self.client_von(rolle).post(EINSTELLUNG, daten)

    def test_ueberschriften_und_formate_wirken(self):
        antwort = self._speichere(spalte_datum='Date', spalte_beleg='Doc', spalte_soll='AccountDebit',
                                  spalte_haben='AccountCredit', spalte_betrag='Amount', spalte_text='Description',
                                  spalte_mwst='VatCode', trenner=',', datumsformat='iso', dezimal=',')
        self.assertEqual(antwort.status_code, 302)
        export = self.client_von('verwalter').post(JOURNAL, ZEITRAUM)
        text = export.content.decode('utf-8-sig')
        zeilen = list(csv.reader(io.StringIO(text), delimiter=','))
        self.assertEqual(zeilen[0], ['Date', 'Doc', 'AccountDebit', 'AccountCredit', 'Amount', 'Description', 'VatCode'])
        dez = [z for z in zeilen if z[5] == 'Miete Dezember'][0]
        self.assertEqual((dez[0], dez[4]), ('2024-12-31', '1500,50'))

    def test_kontenzuordnung_und_mwst_code(self):
        self._speichere(konten='9101;1020\n9102;3000;M81\n')
        zeilen = _csv(self.client_von('verwalter').post(JOURNAL, ZEITRAUM))
        jan = [z for z in zeilen if z[5].startswith('Miete Januar')][0]
        self.assertEqual((jan[2], jan[3], jan[6]), ('1020', '3000', 'M81'))

    def test_nicht_zugeordnete_konten_werden_im_log_genannt(self):
        from core.models import AktivitaetsLog
        self._speichere(konten='9101;1020\n')
        self.client_von('verwalter').post(JOURNAL, ZEITRAUM)
        with organisation_kontext(self.org):
            eintrag = AktivitaetsLog.objects.get(aktion='Buchungsjournal exportiert')
        self.assertIn('Konten ohne Zuordnung: 9102', eintrag.details)

    def test_ungueltige_zuordnung_wird_abgewiesen_und_nichts_gespeichert(self):
        from core.models import DatenExportEinstellung
        for text in ('9101', '9101;1020\n9101;1030', 'a;b;c;d', ';1020', '9101;' + 'x' * 31):
            self._speichere(konten=text)
        with organisation_kontext(self.org):
            self.assertFalse(DatenExportEinstellung.objects.exists())

    def test_doppelte_ueberschrift_wird_abgewiesen(self):
        from core.models import DatenExportEinstellung
        self._speichere(spalte_soll='Konto', spalte_haben='Konto')
        with organisation_kontext(self.org):
            self.assertFalse(DatenExportEinstellung.objects.exists())

    def test_einstellungen_gehoeren_der_organisation(self):
        """B sieht und nutzt die Zuordnung von A nicht."""
        self._speichere(konten='9201;4711\n', spalte_text='Beschreibung')
        zeilen = _csv(self.client_von('verwalter').post(JOURNAL, ZEITRAUM))
        self.assertEqual(zeilen[0][5], 'Beschreibung')
        b_client = self.client_von('verwalter')
        # Ein Verwalter von B existiert im Fixture nicht; B bekommt die Vorgaben über den Dienst.
        with organisation_kontext(self.b.organisation):
            b_einst = datenexport.einstellung_holen()
        self.assertIsNone(b_einst.pk)
        self.assertEqual(datenexport.spalten_von(b_einst)['text'], 'Text')
        self.assertEqual(b_einst.konten, {})
        del b_client

    def test_nur_finanzrollen_aendern_einstellungen(self):
        from core.models import DatenExportEinstellung
        for rolle in ('sachbearbeiter', 'lesezugriff', 'hauswart'):
            self.assertEqual(self._speichere(rolle, konten='9101;1020').status_code, 403, rolle)
        with organisation_kontext(self.org):
            self.assertFalse(DatenExportEinstellung.objects.exists())

    def test_aenderung_steht_im_audit_log(self):
        from core.models import AktivitaetsLog
        self._speichere(konten='9101;1020\n')
        with organisation_kontext(self.org):
            self.assertTrue(AktivitaetsLog.objects.filter(aktion='Export-Einstellungen geändert').exists())

    def test_seite_zeigt_gespeicherte_werte(self):
        self._speichere(konten='9101;1020\n', spalte_text='Beschreibung')
        seite = self.client_von('buchhaltung').get('/neu/einstellungen/daten/export/')
        self.assertContains(seite, '9101;1020')
        self.assertContains(seite, 'value="Beschreibung"')


class MandatExportTests(_Basis):
    def setUp(self):
        super().setUp()
        self.medien = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.medien, True)

    def _zip(self, rolle='verwalter', **daten):
        antwort = self.client_von(rolle).post(MANDAT, daten or {'dokumente': 'on'})
        self.assertEqual(antwort.status_code, 200)
        inhalt = b''.join(antwort.streaming_content)
        return zipfile.ZipFile(io.BytesIO(inhalt)), antwort

    def test_inhalt_csv_und_json_je_tabelle(self):
        zf, antwort = self._zip()
        self.assertIn('application/zip', antwort['Content-Type'])
        namen = set(zf.namelist())
        for n in ('daten/crm_Mieter.csv', 'daten/crm_Mieter.json', 'daten/portfolio_Liegenschaft.csv',
                  'daten/rentals_Mietvertrag.json', 'daten/finance_Buchung.csv', 'daten/team.csv',
                  'daten/organisation.json', 'LIESMICH.txt'):
            self.assertIn(n, namen)
        zeilen = json.loads(zf.read('daten/crm_Mieter.json'))
        self.assertEqual([z['nachname'] for z in zeilen], ['A'])
        csv_zeilen = list(csv.reader(io.StringIO(zf.read('daten/crm_Mieter.csv').decode('utf-8-sig')), delimiter=';'))
        self.assertIn('nachname', csv_zeilen[0])
        self.assertEqual(len(csv_zeilen), 2)
        self.assertIn('Zeilen', zf.read('LIESMICH.txt').decode())

    def test_nur_daten_der_eigenen_organisation(self):
        """Weder Namen noch Texte noch IDs der Organisation B kommen im Paket vor."""
        zf, _a = self._zip()
        gesamt = b''.join(zf.read(n) for n in zf.namelist()).decode('utf-8', 'replace')
        for fremd in ('Verwaltung B AG', 'Eigentuemer B', 'B-Weg 7', 'Testbuchung B', 'eig-b@example.ch',
                      'mieter-b@example.ch', 'Wasserschaden B', 'Bern'):
            self.assertNotIn(fremd, gesamt, fremd)
        for eigenes in ('Eigentuemer A', 'A-Weg 7', 'Testbuchung A'):
            self.assertIn(eigenes, gesamt, eigenes)
        buchungen = json.loads(zf.read('daten/finance_Buchung.json'))
        self.assertEqual({b['beleg_text'] for b in buchungen if 'Testbuchung' in b['beleg_text']}, {'Testbuchung A'})

    def test_keine_geheimnisse_und_keine_ahv(self):
        from crm.models import Mieter
        with organisation_kontext(self.org):
            Mieter.objects.filter(pk=self.a.mieter.pk).update(notizen='x')
        zf, _a = self._zip()
        gesamt = b''.join(zf.read(n) for n in zf.namelist()).decode('utf-8', 'replace').lower()
        kopf_mieter = json.loads(zf.read('daten/crm_Mieter.json'))[0]
        self.assertNotIn('ahv_nummer', kopf_mieter)
        for verboten in ('passwort_geheim', 'refresh_token', 'token_hash', 'code_hash', 'portal_feed_token', 'password'):
            self.assertNotIn(verboten, gesamt, verboten)
        self.assertNotIn('daten/core_Postfach.json', zf.namelist())

    def test_dokumente_im_paket_und_fehlende_im_index(self):
        from rentals.models import Dokument
        with override_settings(MEDIA_ROOT=self.medien):
            with organisation_kontext(self.org):
                d = Dokument.objects.get(pk=self.a.dokument_rentals.pk)
                d.datei.save('vertrag.pdf', ContentFile(b'%PDF-1.4 Inhalt A'), save=True)
                Dokument.objects.create(vertrag=self.a.vertrag, datei='organisation/9/weg.pdf', kategorie='vertrag')
            zf, _a = self._zip(dokumente='on')
        index = list(csv.reader(io.StringIO(zf.read('dokumente/index.csv').decode('utf-8-sig')), delimiter=';'))
        zeilen = {z[4]: z for z in index[1:]}
        ok = [z for z in index[1:] if z[5] == 'ok' and z[0] == 'rentals.Dokument']
        self.assertEqual(len(ok), 1)
        self.assertEqual(zf.read(ok[0][3]), b'%PDF-1.4 Inhalt A')
        self.assertEqual(zeilen['organisation/9/weg.pdf'][5], 'fehlt')

    def test_ohne_dokumente(self):
        zf, _a = self._zip(dokumente='')
        self.assertFalse([n for n in zf.namelist() if n.startswith('dokumente/')])
        self.assertIn('ohne Dokumente', zf.read('LIESMICH.txt').decode())

    def test_fremdes_dokument_gelangt_nicht_ins_paket(self):
        from rentals.models import Dokument
        with override_settings(MEDIA_ROOT=self.medien):
            with organisation_kontext(self.b.organisation):
                d = Dokument.objects.get(pk=self.b.dokument_rentals.pk)
                d.datei.save('geheim-b.pdf', ContentFile(b'GEHEIM B'), save=True)
            zf, _a = self._zip(dokumente='on')
        for n in zf.namelist():
            self.assertNotIn(b'GEHEIM B', zf.read(n), n)

    def test_rollen(self):
        for rolle in ('inhaber', 'verwalter'):
            self.assertEqual(self.client_von(rolle).post(MANDAT, {}).status_code, 200, rolle)
        for rolle in ('buchhaltung', 'sachbearbeiter', 'lesezugriff', 'hauswart'):
            self.assertEqual(self.client_von(rolle).post(MANDAT, {}).status_code, 403, rolle)

    def test_get_liefert_keinen_export(self):
        self.assertEqual(self.client_von('verwalter').get(MANDAT).status_code, 302)

    def test_audit_log_vor_der_auslieferung(self):
        from core.models import AktivitaetsLog
        self._zip('inhaber')
        with organisation_kontext(self.org):
            e = AktivitaetsLog.objects.get(aktion='Mandatsexport erstellt')
        self.assertEqual((e.benutzer, e.kategorie, e.organisation_id), (self.benutzer['inhaber'], 'sicherheit', self.org.pk))
        self.assertIn('Tabellen', e.details)

    def test_ohne_audit_eintrag_keine_auslieferung(self):
        from core.models import AktivitaetsLog
        with mock.patch.object(AktivitaetsLog.objects.__class__, 'create', side_effect=RuntimeError('Log kaputt')):
            antwort = self.client_von('verwalter').post(MANDAT, {})
        self.assertEqual(antwort.status_code, 500)
        self.assertNotEqual(antwort.get('Content-Type'), 'application/zip')

    def test_superuser_exportiert_nur_die_aktive_organisation(self):
        from django.contrib.auth import get_user_model
        from django.test import Client
        from crm.models import Mitgliedschaft
        su = get_user_model().objects.create_superuser('root', 'root@example.ch', 'x')
        Mitgliedschaft.alle_organisationen.create(benutzer=su, organisation=self.org, rolle='Inhaber')
        c = Client()
        c.force_login(su)
        antwort = c.post(MANDAT, {})
        self.assertEqual(antwort.status_code, 200)
        zf = zipfile.ZipFile(io.BytesIO(b''.join(antwort.streaming_content)))
        gesamt = b''.join(zf.read(n) for n in zf.namelist()).decode('utf-8', 'replace')
        self.assertNotIn('Eigentuemer B', gesamt)
        self.assertIn('Eigentuemer A', gesamt)

    def test_ohne_kontext_wird_nicht_exportiert(self):
        with self.assertRaises(RuntimeError):
            datenexport.mandat_zip(self.org, io.BytesIO())

    def test_kontext_einer_anderen_organisation_wird_abgewiesen(self):
        with organisation_kontext(self.b.organisation):
            with self.assertRaises(RuntimeError):
                datenexport.mandat_zip(self.org, io.BytesIO())

    def test_leere_organisation_ergibt_gueltiges_paket(self):
        from crm.models import Organisation
        leer = Organisation.objects.create(firma='Leer AG')
        with organisation_kontext(leer):
            puffer = io.BytesIO()
            stat = datenexport.mandat_zip(leer, puffer)
        zf = zipfile.ZipFile(puffer)
        self.assertIn('LIESMICH.txt', zf.namelist())
        self.assertNotIn('daten/crm_Mieter.csv', zf.namelist())
        self.assertEqual(stat['dokumente'], 0)

    def test_kommandozeile(self):
        import os
        from django.core.management import call_command
        from django.core.management.base import CommandError
        ziel = os.path.join(self.medien, 'paket.zip')
        call_command('mandat_exportieren', organisation=self.org.pk, ziel=ziel, ohne_dokumente=True, stdout=io.StringIO())
        zf = zipfile.ZipFile(ziel)
        self.assertIn('daten/crm_Mieter.json', zf.namelist())
        self.assertNotIn('Eigentuemer B', zf.read('daten/crm_Eigentuemer.json').decode())
        with self.assertRaises(CommandError):                       # überschreibt nichts
            call_command('mandat_exportieren', organisation=self.org.pk, ziel=ziel, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command('mandat_exportieren', organisation=999999, ziel=ziel + '2', stdout=io.StringIO())
        from core.models import AktivitaetsLog
        with organisation_kontext(self.org):
            self.assertTrue(AktivitaetsLog.objects.filter(aktion='Mandatsexport erstellt', details__startswith='Kommandozeile').exists())


class ExportWaechterTests(_Basis):
    def test_jedes_exportierte_modell_filtert_ueber_den_mandantenmanager(self):
        """Wächter: Der Export zieht Daten über `_default_manager`. Ein Modell, dessen Standardmanager
        nicht auf die Organisation filtert, wäre ein Leck über die Mandantengrenze."""
        from core.tenancy import TenantManager
        for modell in datenexport.exportierbare_modelle():
            self.assertIsInstance(modell._default_manager, TenantManager, modell._meta.label)

    def test_jedes_modell_laesst_sich_exportieren_und_zeigt_nur_eigene_zeilen(self):
        """Das Fixture füllt mehr als hundert Modelle; der Export von A läuft ohne Fehler und enthält nie
        Zeilen mit der Organisation von B (wird über die Zeilenzahl je Modell gegengeprüft)."""
        with organisation_kontext(self.org):
            puffer = io.BytesIO()
            stat = datenexport.mandat_zip(self.org, puffer, mit_dokumenten=False)
        self.assertGreater(len(stat['tabellen']), 40)
        for modell in datenexport.exportierbare_modelle():
            with organisation_kontext(self.org):
                eigene = modell._default_manager.count()
            if eigene:
                self.assertEqual(stat['tabellen'].get(modell._meta.label), eigene, modell._meta.label)
            else:
                self.assertNotIn(modell._meta.label, stat['tabellen'])

    def test_modell_ohne_tabelle_bricht_den_export_nicht(self):
        """Ein in der Registry stehendes Modell ohne Tabelle (Testmodell) wird übersprungen."""
        from django.db import connection
        namen = set(connection.introspection.table_names()) - {'core_mieter'}
        with mock.patch.object(connection.introspection, 'table_names', return_value=list(namen)):
            labels = [m._meta.label for m in datenexport.exportierbare_modelle()]
        self.assertNotIn('crm.Mieter', labels)
        self.assertIn('crm.Eigentuemer', labels)

    def test_ausgenommen_ist_begruendet(self):
        self.assertTrue(all(datenexport.AUSGENOMMEN_MODELLE.values()))
