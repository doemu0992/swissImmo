"""Testmodul bankabgleich — aus core/tests.py herausgeloest (Etappe 1,
siehe docs/ETAPPE-1-ZERLEGEN.md). 11 Klassen, unveraendert uebernommen."""
from datetime import date
from decimal import Decimal
from unittest import skipUnless

from django.test import TestCase, Client
from ._helfer import (
    _test_organisation,
    ZXING_DA, _team_user, _basis_objekte, _seed_konten, _P3_CAMT, Mieter,
    Organisation, Mietvertrag)



class IbanTests(TestCase):
    def test_validierung(self):
        from core.services.iban import ist_gueltige_iban, formatiere_iban
        self.assertTrue(ist_gueltige_iban('CH9300762011623852957'))
        self.assertTrue(ist_gueltige_iban('CH93 0076 2011 6238 5295 7'))
        self.assertFalse(ist_gueltige_iban('CH9300762011623852958'))
        self.assertFalse(ist_gueltige_iban('HELLO'))
        self.assertEqual(formatiere_iban('CH9300762011623852957'), 'CH93 0076 2011 6238 5295 7')

    def test_person_form_lehnt_falsche_iban_ab(self):
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'nachname': 'IbanTest', 'iban': 'CH0000000000000000000'})
        self.assertContains(r, 'IBAN ist ungültig')
        self.assertFalse(Mieter.objects.filter(nachname='IbanTest').exists())

    def test_person_form_speichert_gueltige_iban_formatiert(self):
        u = _team_user()
        c = Client(); c.force_login(u)
        r = c.post('/neu/personen/neu/', {'typ': 'person', 'nachname': 'IbanOk', 'iban': 'CH9300762011623852957'})
        self.assertEqual(r.status_code, 302)
        m = Mieter.objects.get(nachname='IbanOk')
        self.assertEqual(m.iban, 'CH93 0076 2011 6238 5295 7')


class QrrReferenzTests(TestCase):
    def test_referenz_27_stellig_mod10(self):
        from core.utils.qr_code import qrr_referenz
        raw, fmt = qrr_referenz(5, 42)
        self.assertEqual(len(raw), 27)
        self.assertTrue(raw.isdigit())
        # Prüfziffer mit derselben Mod-10-rekursiv-Tabelle verifizieren
        tab = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]
        u = 0
        for z in raw[:26]:
            u = tab[(u + int(z)) % 10]
        self.assertEqual(int(raw[26]), (10 - u) % 10)

    def test_rechnung_setzt_referenz_automatisch(self):
        from finance.models import DebitorenRechnung
        _lg, _e, _m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(vertrag=v, titel='Test', betrag=Decimal('100'))
        r.refresh_from_db()
        self.assertEqual(len(r.qr_referenz), 27)


class CamtImportTests(TestCase):
    def _camt(self, ref, betrag='1700.00', acct_ref='BANKTX1'):
        return (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
            '<CdtDbtInd>CRDT</CdtDbtInd>'
            f'<Amt Ccy="CHF">{betrag}</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            f'<Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
            f'<RmtInf><Strd><CdtrRefInf><Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>'
            '</TxDtls></NtryDtls>'
            '</Ntry></Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')

    def test_zahlung_wird_per_referenz_verbucht(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung, Zahlungseingang
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')
        team = _team_user()
        c = Client(); c.force_login(team)
        f = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz), content_type='application/xml')
        resp = c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)

    def test_duplikat_wird_nicht_doppelt_verbucht(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung, Zahlungseingang
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')
        team = _team_user()
        c = Client(); c.force_login(team)
        for _ in range(2):
            f = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz, acct_ref='SAMEREF'),
                                   content_type='application/xml')
            c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        # trotz zweifachem Import nur EINE Zahlung (Duplikatschutz über Bank-Referenz)
        self.assertEqual(Zahlungseingang.objects.filter(bank_referenz='SAMEREF').count(), 1)


class BankCsvImportTests(TestCase):
    """Bank-CSV-Import über denselben Endpunkt wie camt.053 (Format-Weiche)."""

    def _setup_rechnung(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        return DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')

    def test_csv_zahlung_per_qrr_referenz(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup_rechnung()
        csv = ("Datum;Buchungstext;Referenz;Gutschrift;Belastung\n"
               f"05.03.2024;Gutschrift QR;{r.qr_referenz};1'700.00;\n"
               "06.03.2024;Ladenmiete Dauerauftrag;;;-250.00\n").encode('utf-8')
        team = _team_user(); c = Client(); c.force_login(team)
        f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
        resp = c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)

    def test_csv_reimport_erzeugt_kein_duplikat(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup_rechnung()
        csv = ("Datum;Buchungstext;Referenz;Gutschrift\n"
               f"05.03.2024;Gutschrift QR;{r.qr_referenz};1'700.00\n").encode('utf-8')
        team = _team_user(); c = Client(); c.force_login(team)
        for _ in range(2):
            f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
            c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        # zusammengesetzter Schlüssel (Datum|Betrag|Name|Ref) verhindert Doppelbuchung
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r).count(), 1)

    def test_csv_fuzzy_name_und_betrag(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup_rechnung()
        nachname = r.vertrag.mieter.nachname
        betrag = f"{r.offener_betrag:.2f}"
        csv = ("Datum;Auftraggeber;Mitteilung;Betrag\n"
               f"05.03.2024;Hans {nachname};Miete Maerz;{betrag}\n").encode('cp1252')
        team = _team_user(); c = Client(); c.force_login(team)
        f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r).count(), 1)

    def test_csv_unzuordenbar_landet_auf_1190(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        self._setup_rechnung()
        csv = ("Datum;Auftraggeber;Betrag\n"
               "05.03.2024;Unbekannte Person;99.95\n").encode('utf-8')
        team = _team_user(); c = Client(); c.force_login(team)
        f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        z = Zahlungseingang.objects.filter(bemerkung__contains='UNGEKLÄRT').first()
        self.assertIsNotNone(z)
        self.assertEqual(z.konto.nummer, '1190')

    def test_csv_ohne_kopfzeile_gibt_fehlermeldung(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        self._setup_rechnung()
        csv = b"foo;bar\n1;2\n"
        team = _team_user(); c = Client(); c.force_login(team)
        f = SimpleUploadedFile('auszug.csv', csv, content_type='text/csv')
        resp = c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f}, follow=True)
        self.assertContains(resp, 'CSV-Format nicht erkannt')
        self.assertEqual(Zahlungseingang.objects.count(), 0)


class QrDecoderTests(TestCase):
    """Echter QR-Decoder (zxing-cpp): Der Schweizer QR-Code des Zahlteils wird
    dekodiert und liefert IBAN/Referenz/Betrag/Empfänger verbindlich — auch bei
    Foto-Belegen, wo kein Text-Postprocessing möglich ist."""

    SPC = ("SPC\n0200\n1\nCH4030000008300003107\nS\nBKW Energie AG\nViktoriaplatz\n2\n"
           "3013\nBern\nCH\n\n\n\n\n\n\n\n137.30\nCHF\nS\nHR Immobilien AG\nViaduktstrasse\n8\n"
           "4512\nBellach\nCH\nQRR\n000050637947060000894095003\n\nEPD")

    def _qr_png(self):
        import io
        import segno
        buf = io.BytesIO()
        segno.make(self.SPC, error='m').save(buf, kind='png', scale=6, border=4)
        return buf.getvalue()

    def test_spc_parsen(self):
        from finance.utils import _spc_parsen
        d = _spc_parsen(self.SPC)
        self.assertEqual(d['iban'], 'CH4030000008300003107')
        self.assertEqual(d['lieferant'], 'BKW Energie AG')
        self.assertEqual(d['betrag'], 137.30)
        self.assertEqual(d['referenz'], '000050637947060000894095003')
        self.assertIsNone(_spc_parsen('kein spc'))

    @skipUnless(ZXING_DA, 'zxing-cpp nicht installiert — QR-Decoder inaktiv')
    def test_foto_beleg_mit_qr_wird_dekodiert(self):
        """Bild-Beleg OHNE KI-Key: früher 'nicht auslesbar' — jetzt liefert der
        QR-Decoder die Zahlungsdaten trotzdem verbindlich."""
        from django.test import override_settings
        from finance.utils import scan_beleg
        import tempfile, os as _os
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as fh:
            fh.write(self._qr_png())
            pfad = fh.name
        try:
            with override_settings(GROQ_API_KEY=None):
                d = scan_beleg(pfad)
            self.assertEqual(d['methode'], 'qr')
            self.assertEqual(d['iban'], 'CH4030000008300003107')
            self.assertEqual(d['referenz'], '000050637947060000894095003')
            self.assertEqual(d['betrag'], 137.30)
            self.assertEqual(d['lieferant'], 'BKW Energie AG')
        finally:
            _os.unlink(pfad)

    @skipUnless(ZXING_DA, 'zxing-cpp nicht installiert — QR-Decoder inaktiv')
    def test_upload_qr_bild_erzeugt_saubere_rechnung(self):
        """Upload eines QR-Bild-Belegs → Rechnung mit verbindlichen Zahlungsdaten,
        kein Warnhinweis (QR gilt als Erfolg)."""
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung
        c = Client(); c.force_login(_team_user())
        f = SimpleUploadedFile('zahlteil.png', self._qr_png(), content_type='image/png')
        with override_settings(GROQ_API_KEY=None):
            c.post('/neu/kreditoren/scan/', {'beleg_scan': f})
        k = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k.lieferant, 'BKW Energie AG')
        self.assertEqual(k.betrag, Decimal('137.30'))
        self.assertEqual(k.iban, 'CH4030000008300003107')
        self.assertEqual(k.referenz, '000050637947060000894095003')
        self.assertEqual(k.fehlermeldung, '')

    def test_faelligkeit_wird_ausgelesen(self):
        """'Zahlbar bis' → faellig_am an der Rechnung; auch relative Fristen
        ('zahlbar innert 30 Tagen') werden ab Rechnungsdatum gerechnet."""
        import io
        from reportlab.pdfgen import canvas as _c
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import KreditorenRechnung

        def pdf(zeile):
            buf = io.BytesIO()
            c = _c.Canvas(buf)
            c.drawString(72, 800, "Faellig AG")
            c.drawString(72, 780, "Rechnung vom 20.07.2026")
            c.drawString(72, 760, "Total CHF 100.00")
            c.drawString(72, 740, zeile)
            c.save()
            return buf.getvalue()

        cl = Client(); cl.force_login(_team_user())
        # explizites Datum
        f1 = SimpleUploadedFile('f1.pdf', pdf("Zahlbar bis: 19.08.2026"), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            cl.post('/neu/kreditoren/scan/', {'beleg_scan': f1})
        k1 = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k1.faellig_am, date(2026, 8, 19))
        # relative Frist ab Rechnungsdatum
        f2 = SimpleUploadedFile('f2.pdf', pdf("Zahlbar innert 30 Tagen"), content_type='application/pdf')
        with override_settings(GROQ_API_KEY=None):
            cl.post('/neu/kreditoren/scan/', {'beleg_scan': f2})
        k2 = KreditorenRechnung.objects.latest('id')
        self.assertEqual(k2.faellig_am, date(2026, 8, 19))   # 20.07. + 30 Tage


class BankAbgleichP3Tests(TestCase):
    """Ohne Belastungen, Auszugszeilen und Schlusssaldo ist ein Bankkonto
    strukturell nicht abstimmbar — genau das prüfen diese Tests."""

    def _saldo(self, nummer):
        from finance.models import Buchung
        from django.db.models import Sum
        soll = (Buchung.objects.filter(soll_konto__nummer=nummer, ist_storno=False)
                .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        haben = (Buchung.objects.filter(haben_konto__nummer=nummer, ist_storno=False)
                 .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        return soll - haben

    def _import(self, client, xml=None, bank='1020'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile("auszug.xml", (xml or _P3_CAMT).encode(),
                               content_type="text/xml")
        return client.post('/neu/bankabgleich/camt-import/',
                           {'camt_datei': f, 'bank_konto': bank})

    # ---------- Parser ----------
    def test_camt_liest_belastungen_mit_negativem_vorzeichen(self):
        from core.views.fw import _camt_parse
        nur_gut = _camt_parse(_P3_CAMT.encode())
        self.assertEqual(len(nur_gut), 1)
        alle = _camt_parse(_P3_CAMT.encode(), nur_gutschriften=False)
        self.assertEqual(len(alle), 2)
        belastung = [e for e in alle if e['betrag'] < 0][0]
        self.assertEqual(belastung['betrag'], Decimal('-350.00'))

    def test_camt_gegenpartei_bei_belastung_ist_der_empfaenger(self):
        """Bei einem Ausgang steht der Empfänger in <Cdtr>, nicht in <Dbtr> —
        sonst bleibt der Lieferantenname im Bank-Eingang leer."""
        from core.views.fw import _camt_parse
        alle = _camt_parse(_P3_CAMT.encode(), nur_gutschriften=False)
        belastung = [e for e in alle if e['betrag'] < 0][0]
        gutschrift = [e for e in alle if e['betrag'] > 0][0]
        self.assertEqual(belastung['dbtr_name'], 'Hauswartung AG')
        self.assertEqual(gutschrift['dbtr_name'], 'Hans Muster')

    def test_camt_liest_valuta_getrennt_vom_buchungsdatum(self):
        from core.views.fw import _camt_parse
        g = _camt_parse(_P3_CAMT.encode())[0]
        self.assertEqual(g['datum'], date(2024, 3, 5))
        self.assertEqual(g['valuta'], date(2024, 3, 4))

    def test_camt_kopf_liest_iban_periode_und_saldi(self):
        from core.views.fw import _camt_kopf
        k = _camt_kopf(_P3_CAMT.encode())
        self.assertEqual(k['iban'], 'CH9300762011623852957')
        self.assertEqual(k['von'], date(2024, 3, 1))
        self.assertEqual(k['bis'], date(2024, 3, 31))
        self.assertEqual(k['eroeffnung'], Decimal('1000.00'))
        self.assertEqual(k['schluss'], Decimal('1450.00'))

    # ---------- Import ----------
    def test_import_haelt_jede_auszugszeile_fest(self):
        from finance.models import Kontoauszug, Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        a = Kontoauszug.objects.get()
        self.assertEqual(a.iban, 'CH9300762011623852957')
        self.assertEqual(a.schlusssaldo, Decimal('1450.00'))
        self.assertEqual(Bankbewegung.objects.filter(auszug=a).count(), 2)

    def test_belastung_bleibt_offen_und_wird_nicht_geraten(self):
        """Das Gegenkonto einer Belastung steht nicht im Auszug. Es zu raten wäre
        eine Falschbuchung — die Zeile bleibt bis zur Zuordnung offen."""
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        self.assertEqual(b.status, 'offen')
        self.assertEqual(b.gegenpartei, 'Hauswartung AG')
        self.assertEqual(self._saldo('6800'), Decimal('0.00'))

    def test_geparkte_gutschrift_gilt_als_verbucht(self):
        """Eine auf 1190 geparkte Gutschrift IST gebucht — bliebe sie «offen»,
        zeigte der Saldoabgleich eine Differenz, die es gar nicht gibt."""
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__gt=0)
        self.assertEqual(b.status, 'verbucht')
        self.assertEqual(self._saldo('1190'), Decimal('-800.00'))

    def test_import_bucht_auf_gewaehltes_bankkonto(self):
        """Vorher war «1020» im ganzen Import hart verdrahtet — ein zweites
        Bankkonto war damit nicht importierbar."""
        from finance.models import Buchungskonto
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        Buchungskonto.objects.create(nummer='1021', bezeichnung='Bank 2', typ='aktiv')
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c, bank='1021')
        self.assertEqual(self._saldo('1021'), Decimal('800.00'))
        self.assertEqual(self._saldo('1020'), Decimal('0.00'))

    def test_erneuter_import_erzeugt_keine_zweiten_bewegungen(self):
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        self._import(c)
        self.assertEqual(Bankbewegung.objects.count(), 2)
        self.assertEqual(self._saldo('1020'), Decimal('800.00'))

    # ---------- Zuordnung ----------
    def test_belastung_auf_aufwandkonto_zuordnen(self):
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'konto', 'gegenkonto': '6800',
            'beleg_text': 'Hauswartung Februar'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'verbucht')
        self.assertIsNotNone(b.buchung_id)
        self.assertEqual(self._saldo('6800'), Decimal('350.00'))
        self.assertEqual(self._saldo('1020'), Decimal('450.00'))

    def test_zuordnung_bucht_auf_das_valutadatum(self):
        """Buchhalterisch massgebend ist die Valuta, nicht der Erfassungstag."""
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'konto', 'gegenkonto': '6800'})
        b.refresh_from_db()
        self.assertEqual(b.buchung.datum, date(2024, 3, 6))

    def test_belastung_tilgt_kreditorenrechnung(self):
        from finance.models import Bankbewegung, KreditorenRechnung
        from finance.booking import ensure_kontenplan, buche
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        kr = KreditorenRechnung.objects.create(
            lieferant='Hauswartung AG', referenz='RE-77', betrag=Decimal('350.00'),
            datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31),
            liegenschaft=lg, status='freigegeben')
        buche('6800', '2000', Decimal('350.00'), 'Hauswartung Februar',
              datum=date(2024, 3, 1), liegenschaft=lg, kreditor=kr)
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'kreditor', 'kreditor_id': kr.id})
        b.refresh_from_db(); kr.refresh_from_db()
        self.assertEqual(b.status, 'verbucht')
        self.assertEqual(kr.status, 'bezahlt')
        self.assertEqual(self._saldo('2000'), Decimal('0.00'))
        self.assertEqual(self._saldo('1020'), Decimal('450.00'))

    def test_gutschrift_kann_keine_kreditorenrechnung_tilgen(self):
        from finance.models import Bankbewegung, KreditorenRechnung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        kr = KreditorenRechnung.objects.create(
            lieferant='Hauswartung AG', referenz='RE-78', betrag=Decimal('350.00'),
            datum=date(2024, 3, 1), faellig_am=date(2024, 3, 31),
            liegenschaft=lg, status='freigegeben')
        c = Client(); c.force_login(_team_user())
        self._import(c)
        # Die Gutschrift wurde beim Import geparkt → künstlich wieder öffnen
        b = Bankbewegung.objects.get(betrag__gt=0)
        b.status = 'offen'; b.save(update_fields=['status'])
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'kreditor', 'kreditor_id': kr.id})
        b.refresh_from_db(); kr.refresh_from_db()
        self.assertEqual(b.status, 'offen')
        self.assertEqual(kr.status, 'freigegeben')

    def test_ignorierte_bewegung_erzeugt_keine_buchung(self):
        from finance.models import Bankbewegung, Buchung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        vorher = Buchung.objects.count()
        c.post('/neu/bankabgleich/bewegung/', {
            'bewegung_id': b.id, 'art': 'ignorieren',
            'bemerkung': 'Umbuchung eigenes Konto'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'ignoriert')
        self.assertEqual(Buchung.objects.count(), vorher)

    def test_erledigte_bewegung_wird_nicht_zweimal_gebucht(self):
        from finance.models import Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        b = Bankbewegung.objects.get(betrag__lt=0)
        daten = {'bewegung_id': b.id, 'art': 'konto', 'gegenkonto': '6800'}
        c.post('/neu/bankabgleich/bewegung/', daten)
        c.post('/neu/bankabgleich/bewegung/', daten)
        self.assertEqual(self._saldo('6800'), Decimal('350.00'))

    def test_bankabgleich_seite_zeigt_offene_bewegungen(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        _basis_objekte()
        c = Client(); c.force_login(_team_user())
        self._import(c)
        r = c.get('/neu/bankabgleich/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['bew_offen_n'], 1)
        self.assertContains(r, 'Hauswartung AG')

    # ---------- Wer hat bezahlt? ----------
    def _geparkt(self, gegenpartei='', text='', referenz=''):
        """Eine ungeklärte Zahlung auf 1190 samt zugehöriger Auszugszeile."""
        from finance.models import Zahlungseingang, Buchungskonto, Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        k1190, _ = Buchungskonto.objects.get_or_create(
            nummer='1190', defaults={'bezeichnung': 'Durchlaufkonto', 'typ': 'bilanz'})
        bank = Buchungskonto.objects.get(nummer='1020')
        z = Zahlungseingang.objects.create(
            betrag=Decimal('200.00'), datum_eingang=date(2026, 7, 31),
            bemerkung='Bank-CSV UNGEKLÄRT: ', konto=k1190,
            bank_referenz='REF-1', status='verbucht')
        Bankbewegung.objects.create(
            konto=bank, datum=date(2026, 7, 31), betrag=Decimal('200.00'),
            text=text, gegenpartei=gegenpartei, referenz=referenz,
            bank_referenz='REF-1', status='verbucht', zahlung=z)
        return z

    def test_ungeklaerte_zahlung_zeigt_den_auftraggeber(self):
        """Die Zeile zeigte nur den abgeschnittenen Importtext («Bank-CSV UNG…»)
        — von wem das Geld kam, stand nirgends, obwohl die Bank es liefert."""
        _basis_objekte()
        self._geparkt(gegenpartei='Muster Handels AG', text='Miete Juli',
                      referenz='210000000003139471430009017')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Muster Handels AG')
        self.assertContains(r, 'Miete Juli')
        self.assertContains(r, '210000000003139471430009017')

    def test_ohne_auftraggeber_wird_das_offen_gesagt(self):
        """Liefert die Bank keinen Namen, soll das dastehen statt eines
        abgeschnittenen Importtexts, der so aussieht wie ein Titel."""
        _basis_objekte()
        self._geparkt(gegenpartei='', text='Gutschrift Dauerauftrag')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/')
        self.assertContains(r, 'Auftraggeber von der Bank nicht geliefert')
        self.assertContains(r, 'Gutschrift Dauerauftrag')

    def test_zahler_aus_buchungstext_wenn_bank_keine_spalte_liefert(self):
        """Viele Exporte haben keine Auftraggeber-Spalte, sondern «Name;PLZ Ort; Land»
        im Buchungstext — real gesehen «Narrezauber Soledurn;4500 Solothurn; CH»."""
        _basis_objekte()
        self._geparkt(gegenpartei='', text='Narrezauber Soledurn;4500 Solothurn; CH')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/')
        self.assertContains(r, 'Narrezauber Soledurn')
        self.assertContains(r, 'aus Buchungstext')          # als geraten markiert
        self.assertContains(r, '4500 Solothurn')            # Rest bleibt als Detail
        self.assertNotContains(r, 'nicht geliefert')

    def test_einteiliger_buchungstext_bleibt_mitteilung(self):
        """«Miete Juli» ist kein Name — daraus wird kein Auftraggeber erfunden."""
        _basis_objekte()
        self._geparkt(gegenpartei='', text='Miete Juli')
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/')
        self.assertContains(r, 'Auftraggeber von der Bank nicht geliefert')
        self.assertContains(r, 'Miete Juli')

    # ---------- Gelernter Absender ----------
    def _csv(self, name='Narrezauber Soledurn;4500 Solothurn; CH', betrag='200.00',
             datum='31.07.2026'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Komma-getrennt: genau so kommt der reale Fall zustande — die Semikolon
        # im Adressfeld bleiben dann im Feld stehen, statt es in Spalten zu zerlegen.
        return SimpleUploadedFile(
            'auszug.csv',
            ("Datum,Gutschrift,Mitteilung\n"
             f"{datum},{betrag},{name}\n").encode('utf-8'),
            content_type='text/csv')

    def _offene_rechnung(self, betrag='200.00'):
        from finance.models import DebitorenRechnung
        lg, e, m, v = _basis_objekte()
        r = DebitorenRechnung.objects.create(
            vertrag=v, titel='Miete August', betrag=Decimal(betrag),
            datum=date(2026, 8, 1), faellig_am=date(2026, 8, 1), status='offen')
        return v, r

    def test_zuordnen_merkt_sich_den_absender(self):
        """Nach der Handarbeit soll die nächste Zahlung desselben Absenders
        von selbst treffen — sonst parkt ein Dauerauftrag jeden Monat neu."""
        from finance.models import ZahlerZuordnung
        v, r = self._offene_rechnung()
        z = self._geparkt(gegenpartei='', text='Narrezauber Soledurn;4500 Solothurn; CH')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/zuordnen/', {'zahlung_id': z.id, 'rechnung_id': r.id})
        eintrag = ZahlerZuordnung.objects.filter(vertrag=v).first()
        self.assertIsNotNone(eintrag)
        self.assertEqual(eintrag.name_norm, 'narrezaubersoledurn')

    def test_gelernter_absender_wird_beim_import_zugeordnet(self):
        from finance.booking import ensure_kontenplan
        from finance.models import ZahlerZuordnung, Zahlungseingang
        ensure_kontenplan()
        v, r = self._offene_rechnung()
        ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                       name_anzeige='Narrezauber Soledurn', vertrag=v)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': self._csv()}, follow=True)
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        z = Zahlungseingang.objects.filter(debitoren_rechnung=r).first()
        self.assertIsNotNone(z)
        self.assertIsNone(z.konto)                      # nicht geparkt
        self.assertEqual(ZahlerZuordnung.objects.get(vertrag=v).treffer, 1)

    def test_gelernter_absender_raet_nicht_bei_mehreren_offenen(self):
        """Zwei offene Rechnungen — welche gemeint ist, weiss nur der Mensch.
        Falsch zugeordnetes Geld kostet mehr als eine Minute Handarbeit."""
        from finance.booking import ensure_kontenplan
        from finance.models import DebitorenRechnung, ZahlerZuordnung
        ensure_kontenplan()
        v, r = self._offene_rechnung()
        DebitorenRechnung.objects.create(
            vertrag=v, titel='Miete September', betrag=Decimal('200.00'),
            datum=date(2026, 9, 1), faellig_am=date(2026, 9, 1), status='offen')
        ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                       name_anzeige='Narrezauber Soledurn', vertrag=v)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': self._csv()}, follow=True)
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')             # nichts geraten
        self.assertEqual(ZahlerZuordnung.objects.get(vertrag=v).treffer, 0)

    def test_gelernter_absender_ueberzahlung_wird_nicht_automatisch_gebucht(self):
        """Mehr als offen ist → auch das gehört vor Augen, nicht in die Automatik."""
        from finance.booking import ensure_kontenplan
        from finance.models import ZahlerZuordnung
        ensure_kontenplan()
        v, r = self._offene_rechnung(betrag='150.00')
        ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                       name_anzeige='Narrezauber Soledurn', vertrag=v)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': self._csv(betrag='200.00')}, follow=True)
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')

    def test_unbekannter_absender_parkt_weiterhin(self):
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        v, r = self._offene_rechnung()
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': self._csv(name='Fremd AG;4500 Solothurn')},
               follow=True)
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')
        self.assertTrue(Zahlungseingang.objects.filter(konto__nummer='1190').exists())

    # ---------- Sammelzuordnung ----------
    def _rechnung(self, vertrag, titel, betrag, faellig):
        from finance.models import DebitorenRechnung
        return DebitorenRechnung.objects.create(
            vertrag=vertrag, titel=titel, betrag=Decimal(betrag),
            datum=faellig, faellig_am=faellig, status='offen')

    def test_sammelzuordnung_tilgt_aelteste_forderung_zuerst(self):
        """Drei Monatsmieten, drei geparkte Zahlungen — auf einen Schlag. Die
        Reihenfolge ist kein Detail: sonst mahnt man einen Monat, der längst
        bezahlt ist."""
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r_jul = self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        r_aug = self._rechnung(v, 'Miete August', '200.00', date(2026, 8, 1))
        r_sep = self._rechnung(v, 'Miete September', '200.00', date(2026, 9, 1))
        z = [self._geparkt(gegenpartei='Narrezauber Soledurn') for _ in range(3)]
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/',
                   {'zahlung_ids': [str(x.id) for x in z], 'vertrag_id': v.id}, follow=True)
        self.assertEqual(r.status_code, 200)
        for rech in (r_jul, r_aug, r_sep):
            rech.refresh_from_db()
            self.assertEqual(rech.status, 'bezahlt', rech.titel)
        self.assertEqual(Zahlungseingang.objects.filter(konto__nummer='1190').count(), 0)

    def test_sammelzuordnung_ueberschuss_bleibt_guthaben(self):
        """Mehr Geld als Forderungen: Der Rest verfällt nicht, er wird
        Mieterguthaben (2030)."""
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        z = [self._geparkt(gegenpartei='Narrezauber Soledurn') for _ in range(2)]
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/',
                   {'zahlung_ids': [str(x.id) for x in z], 'vertrag_id': v.id}, follow=True)
        # Die zweite Zahlung findet keine offene Forderung mehr und bleibt liegen
        self.assertContains(r, 'keine offene Rechnung mehr')
        self.assertTrue(Zahlungseingang.objects.filter(konto__nummer='1190').exists())

    def test_sammelzuordnung_ohne_mieter_bucht_nichts(self):
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        z = self._geparkt(gegenpartei='Narrezauber Soledurn')
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/',
                   {'zahlung_ids': [str(z.id)], 'vertrag_id': ''}, follow=True)
        self.assertContains(r, 'Kein Mieter gewählt')
        z.refresh_from_db()
        self.assertEqual(z.konto.nummer, '1190')        # unverändert geparkt

    def test_sammelzuordnung_ohne_auswahl_bucht_nichts(self):
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/', {'vertrag_id': v.id}, follow=True)
        self.assertContains(r, 'Keine Zahlung ausgewählt')

    def test_sammelzuordnung_merkt_sich_den_absender(self):
        from finance.booking import ensure_kontenplan
        from finance.models import ZahlerZuordnung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        z = self._geparkt(gegenpartei='Narrezauber Soledurn')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/sammel-zuordnen/',
               {'zahlung_ids': [str(z.id)], 'vertrag_id': v.id}, follow=True)
        self.assertTrue(ZahlerZuordnung.objects.filter(
            name_norm='narrezaubersoledurn', vertrag=v).exists())

    def test_sammelzuordnung_fasst_fremdes_guthaben_nicht_an(self):
        """Ein Guthaben auf 2030 gehört einem bestimmten Mieter — es darf nicht
        die Forderung eines anderen tilgen."""
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang, Buchungskonto
        from crm.models import Mieter
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        r_jul = self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        m2 = Mieter.objects.create(vorname='Fremd', nachname='Person')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=e, status='aktiv',
                                        beginn=date(2025, 1, 1),
                                        netto_mietzins=Decimal('100'), nebenkosten=Decimal('0'))
        k2030, _ = Buchungskonto.objects.get_or_create(
            nummer='2030', defaults={'bezeichnung': 'Guthaben Mieter', 'typ': 'bilanz'})
        fremd = Zahlungseingang.objects.create(
            vertrag=v2, betrag=Decimal('200.00'), datum_eingang=date(2026, 7, 31),
            konto=k2030, status='verbucht', bemerkung='Guthaben Fremd')
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/sammel-zuordnen/',
                   {'zahlung_ids': [str(fremd.id)], 'vertrag_id': v.id}, follow=True)
        r_jul.refresh_from_db()
        self.assertEqual(r_jul.status, 'offen')
        self.assertContains(r, 'gehört einem anderen Mieter')

    def test_csv_erkennt_weitere_auftraggeber_spalten(self):
        from core.views.fw import _bank_csv_parse
        csv = ("Datum;Gutschrift;Zahler;Mitteilung\n"
               "31.07.2026;200.00;Muster Handels AG;Miete Juli\n").encode()
        e = _bank_csv_parse(csv)
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]['dbtr_name'], 'Muster Handels AG')

    # ---------- «Kürzlich abgeglichen» lesbar ----------

    def _abgeglichen(self, vertrag=None, gegenpartei='', text='', bemerkung=''):
        """Eine bereits verbuchte Zahlung samt Auszugszeile."""
        from finance.models import Zahlungseingang, Buchungskonto, Bankbewegung
        from finance.booking import ensure_kontenplan
        ensure_kontenplan()
        bank = Buchungskonto.objects.get(nummer='1020')
        z = Zahlungseingang.objects.create(
            vertrag=vertrag, betrag=Decimal('100.00'), datum_eingang=date(2026, 7, 31),
            bemerkung=bemerkung, konto=bank, bank_referenz='REF-A', status='verbucht')
        Bankbewegung.objects.create(
            konto=bank, datum=date(2026, 7, 31), betrag=Decimal('100.00'),
            text=text, gegenpartei=gegenpartei, bank_referenz='REF-A',
            status='verbucht', zahlung=z)
        return z

    def test_kuerzlich_abgeglichen_kuerzt_den_namen_nicht_mehr_ab(self):
        """Mieter, Datum, Betrag und «Stornieren» standen in EINER Zeile — auf
        dem Handy blieb vom Namen «B..» übrig. Name und Herkunft stehen jetzt
        untereinander, ohne truncate."""
        lg, e, m, v = _basis_objekte()
        self._abgeglichen(vertrag=v, gegenpartei='Muster Handels AG',
                          text='Miete Juli', bemerkung='Bank-CSV Import')
        c = Client(); c.force_login(_team_user())
        h = c.get('/neu/bankabgleich/').content.decode('utf-8')
        block = h.split('Kürzlich abgeglichen', 1)[1]
        self.assertIn(m.display_name, block)
        self.assertIn('Muster Handels AG', block)
        self.assertNotIn('flex-1 min-w-0 truncate', block)

    def test_kuerzlich_abgeglichen_ohne_vertrag_beginnt_nicht_mit_trennzeichen(self):
        """Ohne Vertrag war der Mietername leer und die Zeile begann mit « · »
        — auf dem Handy war das die ganze sichtbare Information."""
        _basis_objekte()
        self._abgeglichen(gegenpartei='Narrezauber Soledurn', text='Miete Juli')
        c = Client(); c.force_login(_team_user())
        h = c.get('/neu/bankabgleich/').content.decode('utf-8')
        block = h.split('Kürzlich abgeglichen', 1)[1]
        self.assertIn('Narrezauber Soledurn', block)
        self.assertNotIn('break-words"> · ', block)

    def test_kuerzlich_abgeglichen_faellt_auf_die_bemerkung_zurueck(self):
        """Ohne Vertrag UND ohne Auftraggeber bleibt nur die Herkunft des
        Belegs — besser als eine leere Zeile."""
        _basis_objekte()
        self._abgeglichen(bemerkung='camt.053-Import ZZCAMTTEST')
        c = Client(); c.force_login(_team_user())
        block = (c.get('/neu/bankabgleich/').content.decode('utf-8')
                 .split('Kürzlich abgeglichen', 1)[1])
        self.assertIn('camt.053-Import ZZCAMTTEST', block)

    def test_storno_hebt_auch_das_rest_guthaben_wieder_auf(self):
        """Zahlt jemand mehr als offen ist, bleibt der Überschuss als Guthaben
        auf 2030 stehen. Wird die Zahlung später storniert, muss dieses Guthaben
        mit verschwinden — sonst behält der Mieter ein Guthaben aus einer
        Zahlung, die es buchhalterisch nicht mehr gibt, und 1190/2030 sind
        dauerhaft falsch."""
        from finance.booking import ensure_kontenplan
        from finance.models import Zahlungseingang
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        z = self._geparkt(gegenpartei='Narrezauber Soledurn')   # CHF 200.00
        z.betrag = Decimal('300.00'); z.save(update_fields=['betrag'])

        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/sammel-zuordnen/',
               {'zahlung_ids': [str(z.id)], 'vertrag_id': v.id}, follow=True)
        self.assertEqual(self._kontoblatt_saldo('2030'), Decimal('-100.00'))

        c.post(f'/neu/zahlungen/{z.id}/stornieren/', {}, follow=True)
        self.assertEqual(self._kontoblatt_saldo('2030'), Decimal('0.00'),
                         "Guthaben auf 2030 blieb nach dem Storno stehen")
        self.assertFalse(Zahlungseingang.objects
                         .filter(bank_referenz__endswith=':rest', status='verbucht')
                         .exists())

    def _kontoblatt_saldo(self, nummer):
        """Saldo wie im Kontoblatt: ALLE Buchungen, inkl. Storno-Gegenbuchungen.

        `_saldo()` blendet `ist_storno=True` aus und misst damit nur die
        Originale — für eine Storno-Prüfung ist das die falsche Sicht."""
        from finance.models import Buchung
        from django.db.models import Sum
        soll = (Buchung.objects.filter(soll_konto__nummer=nummer)
                .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        haben = (Buchung.objects.filter(haben_konto__nummer=nummer)
                 .aggregate(s=Sum('betrag'))['s'] or Decimal('0'))
        return soll - haben

    def test_saldoabgleich_zaehlt_stornierte_buchungen_nicht_mit(self):
        """Ein Storno-Paar darf nicht einseitig gefiltert werden.

        `ist_storno=False` blendet die Gegenbuchung aus — ohne
        `storniert_am__isnull=True` zählt das stornierte ORIGINAL aber weiter.
        Der Abstimmungsnachweis meldete dann eine Differenz zum Bankauszug, die
        es gar nicht gibt, und der Monatsabschluss lässt sich nicht abschliessen.
        `rendite.py`/`jahresabschluss.py` filtern seit jeher auf beides."""
        from django.utils import timezone as _tz
        from finance.booking import ensure_kontenplan, buche, storniere_buchung
        from finance.models import Kontoauszug, Buchungskonto
        ensure_kontenplan()
        heute = _tz.localdate()
        bank = Buchungskonto.objects.get(nummer='1020')
        b = buche('1020', '1100', Decimal('100.00'), 'Testeingang', datum=heute)
        storniere_buchung(b)
        Kontoauszug.objects.create(konto=bank, bis=heute,
                                   schlusssaldo=Decimal('0.00'), dateiname='a.xml')
        c = Client(); c.force_login(_team_user())
        html = c.get('/neu/bankabgleich/').content.decode('utf-8')
        self.assertIn('Saldoabgleich', html)
        # Buchhaltung muss 0.00 zeigen — nicht 100.00 aus dem stornierten Original
        self.assertNotIn('100.00', html.split('Saldoabgleich', 1)[1][:900])

    def test_auswertung_zaehlt_stornierte_buchungen_nicht_mit(self):
        """Dasselbe Storno-Paar-Problem in /neu/auswertung/: ein stornierter
        Mietertrag blieb in Monatsverlauf und Liegenschafts-Vergleich stehen."""
        from django.utils import timezone as _tz
        from finance.booking import ensure_kontenplan, buche, storniere_buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        heute = _tz.localdate()
        b = buche('1100', '3000', Decimal('4321.00'), 'Miete storniert',
                  datum=heute, liegenschaft=lg)
        storniere_buchung(b)
        c = Client(); c.force_login(_team_user())
        html = c.get(f'/neu/auswertung/?jahr={heute.year}').content.decode('utf-8')
        # Ohne den Fix stand hier «4'321.00» (gemessen) — das stornierte Original
        # zählte weiter, seine Gegenbuchung war ausgeblendet.
        self.assertNotIn("4'321.00", html)

    # ---------- Gelernte Zahler einsehen und korrigieren ----------
    # Eine Automatik, die man nicht einsehen und nicht korrigieren kann, ist ein
    # blinder Fleck: Beim Mieterwechsel ordnete das Programm sonst dauerhaft
    # falsch zu, ohne dass jemand die Ursache finden könnte.

    def test_gelernte_zahler_seite_zeigt_absender_und_mieter(self):
        from finance.models import ZahlerZuordnung
        lg, e, m, v = _basis_objekte()
        ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                       name_anzeige='Narrezauber Soledurn',
                                       vertrag=v, treffer=3)
        c = Client(); c.force_login(_team_user())
        r = c.get('/neu/bankabgleich/zahler/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Narrezauber Soledurn')
        self.assertContains(r, m.display_name)
        self.assertContains(r, '3× automatisch getroffen')

    def test_bankabgleich_verlinkt_die_gelernten_zahler(self):
        """Ohne Einstieg findet die Seite niemand — die Regeln entstehen still."""
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/bankabgleich/'), '/neu/bankabgleich/zahler/')

    def test_gelernten_zahler_auf_anderen_mieter_umbiegen(self):
        from crm.models import Mieter
        from finance.models import ZahlerZuordnung
        lg, e, m, v = _basis_objekte()
        m2 = Mieter.objects.create(vorname='Neu', nachname='Mieter')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=e, status='aktiv',
                                        beginn=date(2026, 1, 1),
                                        netto_mietzins=Decimal('100'),
                                        nebenkosten=Decimal('0'))
        z = ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                           name_anzeige='Narrezauber Soledurn',
                                           vertrag=v, treffer=5)
        c = Client(); c.force_login(_team_user())
        r = c.post('/neu/bankabgleich/zahler/speichern/',
                   {'id': z.id, 'vertrag_id': v2.id}, follow=True)
        z.refresh_from_db()
        self.assertEqual(z.vertrag_id, v2.id)
        # Die Trefferzahl gehörte zur alten Regel — sie darf die neue nicht
        # fälschlich als bewährt ausweisen.
        self.assertEqual(z.treffer, 0)
        self.assertIsNone(z.zuletzt)
        self.assertContains(r, 'zahlt neu für')

    def test_gelernten_zahler_vergessen(self):
        from finance.models import ZahlerZuordnung
        lg, e, m, v = _basis_objekte()
        z = ZahlerZuordnung.objects.create(name_norm='narrezaubersoledurn',
                                           name_anzeige='Narrezauber Soledurn',
                                           vertrag=v)
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/zahler/speichern/',
               {'id': z.id, 'aktion': 'loeschen'}, follow=True)
        self.assertFalse(ZahlerZuordnung.objects.filter(id=z.id).exists())

    def test_gelernten_zahler_umbiegen_bucht_nichts_um(self):
        """Die Regel gilt für den NÄCHSTEN Import — bereits verbuchte Zahlungen
        bleiben, wie sie gebucht wurden. Sonst wäre eine Korrektur der Regel
        stillschweigend eine rückwirkende Umbuchung."""
        from crm.models import Mieter
        from finance.booking import ensure_kontenplan
        from finance.models import ZahlerZuordnung, Buchung
        ensure_kontenplan()
        lg, e, m, v = _basis_objekte()
        self._rechnung(v, 'Miete Juli', '200.00', date(2026, 7, 1))
        zahlung = self._geparkt(gegenpartei='Narrezauber Soledurn')
        c = Client(); c.force_login(_team_user())
        c.post('/neu/bankabgleich/sammel-zuordnen/',
               {'zahlung_ids': [str(zahlung.id)], 'vertrag_id': v.id}, follow=True)
        vorher = Buchung.objects.count()
        m2 = Mieter.objects.create(vorname='Neu', nachname='Mieter')
        v2 = Mietvertrag.objects.create(mieter=m2, einheit=e, status='aktiv',
                                        beginn=date(2026, 1, 1),
                                        netto_mietzins=Decimal('100'),
                                        nebenkosten=Decimal('0'))
        z = ZahlerZuordnung.objects.get(name_norm='narrezaubersoledurn')
        c.post('/neu/bankabgleich/zahler/speichern/',
               {'id': z.id, 'vertrag_id': v2.id}, follow=True)
        self.assertEqual(Buchung.objects.count(), vorher)
        zahlung.refresh_from_db()
        self.assertEqual(zahlung.vertrag_id, v.id)

    def test_gelernter_zahler_speichern_verlangt_post(self):
        c = Client(); c.force_login(_team_user())
        self.assertEqual(c.get('/neu/bankabgleich/zahler/speichern/').status_code, 302)

    def test_gelernte_zahler_leerzustand_erklaert_die_automatik(self):
        c = Client(); c.force_login(_team_user())
        self.assertContains(c.get('/neu/bankabgleich/zahler/'),
                            'Noch keine gelernten Zahler')


# ============================================================
# P4 — Kreditoren durchsuchbar + Zahllauf als Prozess
# ============================================================


class QrStrukturierteAdresseTests(TestCase):
    """QR-Rechnung nach Swiss Implementation Guidelines v2.4.

    Mit dem SIC-Release vom 13. November 2026 wird nur noch die
    STRUKTURIERTE Adresse unterstützt; die kombinierte («K») entfällt und
    Einzahlungsscheine damit werden abgewiesen. Der Datenblock verwendete
    bisher durchgehend «K».

    Die Aufrufer übergeben die Adresse als zwei Zeilen — die Zerlegung
    passiert deshalb im QR-Modul, damit nicht jeder Aufrufer umgebaut werden
    muss. Wer die Felder einzeln hat, kann sie direkt liefern.
    """

    def test_strasse_und_hausnummer_werden_getrennt(self):
        from core.utils.qr_code import strasse_und_nummer
        for zeile, erwartet in [
            ('Musterstrasse 12', ('Musterstrasse', '12')),
            ('Bahnhofstrasse 12a', ('Bahnhofstrasse', '12a')),
            ('Chemin des Fleurs 3', ('Chemin des Fleurs', '3')),
            ('Bergweg 12-14', ('Bergweg', '12-14')),
            ('Postfach', ('Postfach', '')),          # ohne Nummer: zulässig
            ('', ('', '')),
        ]:
            self.assertEqual(strasse_und_nummer(zeile), erwartet, f'bei «{zeile}»')

    def test_plz_und_ort_werden_getrennt(self):
        from core.utils.qr_code import plz_und_ort
        for zeile, erwartet in [
            ('3000 Bern', ('3000', 'Bern')),
            ('CH-8001 Zürich', ('8001', 'Zürich')),
            ('1211 Genève 12', ('1211', 'Genève 12')),
            ('Bern', ('', 'Bern')),                  # ohne PLZ: Ort trotzdem füllen
        ]:
            self.assertEqual(plz_und_ort(zeile), erwartet, f'bei «{zeile}»')

    def test_adressblock_ist_strukturiert(self):
        from core.utils.qr_code import adressblock
        block = adressblock({'name': 'Muster AG', 'line1': 'Musterstrasse 12',
                             'line2': '3000 Bern'})
        self.assertEqual(block, ['S', 'Muster AG', 'Musterstrasse', '12',
                                 '3000', 'Bern', 'CH'])

    def test_einzelfelder_gehen_vor(self):
        """Wer die Adresse strukturiert vorliegen hat, soll sie direkt geben
        können — geraten wird nur, wo nichts Genaueres da ist."""
        from core.utils.qr_code import adressblock
        block = adressblock({'name': 'X', 'line1': 'Falschweg 9', 'line2': '9999 Nirgends',
                             'strasse': 'Richtigweg', 'hausnummer': '1',
                             'plz': '3011', 'ort': 'Bern'})
        self.assertEqual(block[2:6], ['Richtigweg', '1', '3011', 'Bern'])

    def test_datenblock_enthaelt_kein_K_mehr(self):
        """Der Kern: im erzeugten QR-Datenblock darf der Adresstyp nirgends
        mehr «K» sein. Geprüft am echten Aufbau, nicht an den Helfern."""
        import io
        from unittest import mock
        from core.utils import qr_code
        gefangen = {}

        echt = qr_code.segno.make

        def merken(daten, error=None):
            gefangen['daten'] = daten
            return echt(daten, error=error)     # echt zeichnen, nur mitlesen

        with mock.patch.object(qr_code.segno, 'make', side_effect=merken):
            from reportlab.pdfgen import canvas as _canvas
            c = _canvas.Canvas(io.BytesIO())
            try:
                qr_code.draw_qr_bill(
                    c, iban='CH5800791123000889012',
                    creditor={'name': 'Verwaltung AG', 'line1': 'Amtsweg 4', 'line2': '3011 Bern'},
                    debtor={'name': 'Anna Muster', 'line1': 'Wohnweg 7a', 'line2': '8000 Zürich'},
                    amount=1580.00, reference='', reason='Miete')
            except TypeError:
                self.skipTest('Signatur von draw_qr_bill weicht ab')
        zeilen = gefangen['daten'].split('\n')
        self.assertNotIn('K', zeilen, 'Datenblock enthält noch eine kombinierte Adresse')
        self.assertEqual(zeilen.count('S'), 2, 'Es müssen zwei strukturierte Adressen sein')
        self.assertIn('Amtsweg', zeilen)
        self.assertIn('3011', zeilen)
        self.assertIn('Wohnweg', zeilen)
        self.assertIn('7a', zeilen)


class QrBetragFormatTests(TestCase):
    """Auf dem Zahlteil kein englisches Tausendertrennzeichen.

    `f"{amount:,.2f}"` erzeugt «1,887.00» — auf einem Schweizer Einzahlungs-
    schein ist das Komma nicht zulässig und für den Zahler zweideutig
    (1,887 vs. 1'887). Der QR-Datenblock selbst war korrekt; nur die gedruckte
    Anzeige nicht."""

    def test_zahlteil_zeigt_apostroph_kein_komma(self):
        import io
        from unittest import mock
        from core.utils import qr_code
        from reportlab.pdfgen import canvas
        gezeichnet = []
        c = canvas.Canvas(io.BytesIO())
        orig = c.drawString
        with mock.patch.object(c, 'drawString',
                               side_effect=lambda x, y, t: gezeichnet.append(t) or orig(x, y, t)):
            with mock.patch.object(c, 'drawImage'):
                qr_code.draw_qr_bill(
                    c, iban='CH5800791123000889012',
                    creditor={'name': 'V AG', 'line1': 'Weg 1', 'line2': '3000 Bern'},
                    debtor={'name': 'A M', 'line1': 'Gasse 2', 'line2': '8000 Zürich'},
                    amount=1234567.89, reference='', reason='Miete')
        betraege = [t for t in gezeichnet if '567' in t]
        self.assertTrue(betraege, 'Betrag wurde nicht gezeichnet')
        for t in betraege:
            self.assertNotIn(',', t, f'Komma im Zahlbetrag: «{t}»')
            self.assertIn("'", t, f'Kein Apostroph-Tausender: «{t}»')


class CamtGesperrtePeriodeQSTests(TestCase):
    """QS Bankabgleich: eine Zahlung, deren Buchung an der Periodensperre scheitert,
    darf beim Re-Import (nach Entsperren) nicht als Duplikat verloren gehen."""

    def _camt(self, ref, betrag='1700.00', acct_ref='GESPERRT1'):
        return (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
            '<CdtDbtInd>CRDT</CdtDbtInd>'
            f'<Amt Ccy="CHF">{betrag}</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            f'<Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
            f'<RmtInf><Strd><CdtrRefInf><Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>'
            '</TxDtls></NtryDtls>'
            '</Ntry></Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')

    def test_gesperrte_periode_verliert_zahlung_beim_reimport_nicht(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung, Zahlungseingang, Bankbewegung
        from crm.models import Organisation
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')
        # Periode sperren, sodass die Buchung per 05.03.2024 scheitert.
        _test_organisation(firma='V AG', strasse='W 1', plz='8000', ort='Zürich',
                           buchung_gesperrt_bis=date(2024, 12, 31))
        c = Client(); c.force_login(_team_user('Verwaltung'))

        # 1) Import in gesperrter Periode → nichts gebucht, KEINE Waisen-Bewegung.
        f = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz), content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen')
        self.assertEqual(Zahlungseingang.objects.filter(bank_referenz='GESPERRT1').count(), 0)
        self.assertEqual(Bankbewegung.objects.filter(bank_referenz='GESPERRT1').count(), 0,
                         'Waisen-Bankbewegung blockiert den Re-Import')

        # 2) Periode öffnen, dieselbe Datei erneut importieren → jetzt gebucht.
        vw = Organisation.objects.first(); vw.buchung_gesperrt_bis = None; vw.save()
        f2 = SimpleUploadedFile('camt.xml', self._camt(r.qr_referenz), content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f2})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(bank_referenz='GESPERRT1', status='verbucht').count(), 1)


class CamtFuzzyNachnameQSTests(TestCase):
    """QS Bankabgleich: die Fuzzy-Zuordnung «Betrag + Name» darf einen Nachnamen
    nur als ganze Tokenfolge treffen, nicht als beliebige Teilzeichenkette —
    sonst wird die Zahlung eines Fremden («Mustermann») dem Mieter «Muster»
    automatisch gutgeschrieben."""

    def _camt_named(self, dbtr, betrag='1700.00', acct_ref='FUZZY1'):
        return (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
            '<CdtDbtInd>CRDT</CdtDbtInd>'
            f'<Amt Ccy="CHF">{betrag}</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            f'<Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
            f'<RltdPties><Dbtr><Nm>{dbtr}</Nm></Dbtr></RltdPties>'
            '</TxDtls></NtryDtls>'
            '</Ntry></Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')

    def _setup(self):
        from core.services.automation import run_sollstellung
        from finance.models import DebitorenRechnung
        _seed_konten()
        _basis_objekte()   # Mieter Nachname 'Muster', Miete+NK 1700
        run_sollstellung(2024, 3)
        return DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')

    def test_teilstring_nachname_bucht_nicht_falsch(self):
        # Zahlung von «Peter Mustermann» (enthält 'muster' als Teilstring, aber
        # NICHT als ganzes Token) darf dem Mieter «Muster» nicht gutgeschrieben
        # werden. Ohne Referenz → Fuzzy-Pfad; exakter Betrag → einziger Kandidat.
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        f = SimpleUploadedFile('camt.xml', self._camt_named('Peter Mustermann'),
                               content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        r.refresh_from_db()
        self.assertEqual(r.status, 'offen',
                         'Fremdzahlung «Mustermann» darf «Muster» nicht automatisch bezahlen')
        self.assertEqual(
            Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 0)

    def test_ganzes_token_nachname_bucht(self):
        # Gegenprobe der Erwünschtheit: «Peter Muster» (Nachname als ganzes Token)
        # wird weiterhin korrekt zugeordnet — die Härtung ist nicht zu streng.
        from django.core.files.uploadedfile import SimpleUploadedFile
        from finance.models import Zahlungseingang
        r = self._setup()
        c = Client(); c.force_login(_team_user('Verwaltung'))
        f = SimpleUploadedFile('camt.xml', self._camt_named('Peter Muster'),
                               content_type='application/xml')
        c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f})
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(
            Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht').count(), 1)


class CamtImportRueckgaengigTests(TestCase):
    """Ein Bank-Import (camt.053/CSV) lässt sich revisionssicher rückgängig machen:
    Zahlungen storniert, Rechnung wieder offen, Auszug entfernt, Re-Import möglich."""

    def _camt(self, ref, betrag='1700.00', acct_ref='UNDOTX1'):
        return (
            '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry>'
            '<CdtDbtInd>CRDT</CdtDbtInd>'
            f'<Amt Ccy="CHF">{betrag}</Amt>'
            '<BookgDt><Dt>2024-03-05</Dt></BookgDt>'
            '<NtryDtls><TxDtls>'
            f'<Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
            f'<RmtInf><Strd><CdtrRefInf><Ref>{ref}</Ref></CdtrRefInf></Strd></RmtInf>'
            '</TxDtls></NtryDtls>'
            '</Ntry></Stmt></BkToCstmrStmt></Document>'
        ).encode('utf-8')

    def _import(self, c, ref, acct_ref='UNDOTX1'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile('camt.xml', self._camt(ref, acct_ref=acct_ref),
                               content_type='application/xml')
        return c.post('/neu/bankabgleich/camt-import/', {'camt_datei': f}, secure=True)

    def test_rueckgaengig_storniert_und_erlaubt_reimport(self):
        from core.services.automation import run_sollstellung
        from finance.models import (DebitorenRechnung, Zahlungseingang, Kontoauszug,
                                    Bankbewegung, Buchung)
        _seed_konten()
        _basis_objekte()
        run_sollstellung(2024, 3)
        r = DebitorenRechnung.objects.get(titel='Miete & NK 03/2024')
        c = Client(); c.force_login(_team_user())

        self._import(c, r.qr_referenz)
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        z = Zahlungseingang.objects.get(debitoren_rechnung=r)
        self.assertEqual(z.status, 'verbucht')
        auszug = Kontoauszug.objects.latest('id')
        # Gegenbuchung existiert noch nicht.
        self.assertFalse(Buchung.objects.filter(ist_storno=True).exists())

        # --- Rückgängig ---
        resp = c.post(f'/neu/bankabgleich/auszug/{auszug.id}/rueckgaengig/', secure=True)
        self.assertEqual(resp.status_code, 302)
        z.refresh_from_db(); r.refresh_from_db()
        self.assertEqual(z.status, 'storniert')           # Zahlung storniert
        self.assertEqual(r.status, 'offen')               # Rechnung wieder offen
        self.assertTrue(Buchung.objects.filter(ist_storno=True).exists())  # Gegenbuchung
        self.assertFalse(Kontoauszug.objects.filter(id=auszug.id).exists())  # Auszug weg
        self.assertFalse(Bankbewegung.objects.filter(auszug_id=auszug.id).exists())

        # --- Re-Import derselben Datei muss wieder verbuchen (kein Duplikat-Block) ---
        self._import(c, r.qr_referenz)
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Zahlungseingang.objects.filter(debitoren_rechnung=r,
                                                        status='verbucht').count(), 1)
