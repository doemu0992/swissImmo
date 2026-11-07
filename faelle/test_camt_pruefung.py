"""Roadmap Nr. 13: Währung und IBAN des Kontoauszugs werden geprüft, bevor gebucht wird."""
from django.core.files.uploadedfile import SimpleUploadedFile

from core.views.fw.bankabgleich import _camt_waehrungen, auszug_pruefen
from faelle.test_monatsabschluss import HEUTE, _Basis

IBAN_A = 'CH9300762011623852957'
IBAN_B = 'CH5604835012345678009'


def _auszug(referenz, betrag, iban=IBAN_A, ccy='CHF', acct_ref='TX-P1'):
    return (
        '<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt>'
        f'<Acct><Id><IBAN>{iban}</IBAN></Id></Acct>'
        f'<Ntry><CdtDbtInd>CRDT</CdtDbtInd><Amt Ccy="{ccy}">{betrag}</Amt>'
        f'<BookgDt><Dt>{HEUTE.isoformat()}</Dt></BookgDt>'
        f'<NtryDtls><TxDtls><Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
        f'<RmtInf><Strd><CdtrRefInf><Ref>{referenz}</Ref></CdtrRefInf></Strd></RmtInf>'
        '</TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>'
    ).encode()


class PruefungEinheitTests(_Basis):
    def test_chf_und_gleiche_iban_sind_in_ordnung(self):
        self.assertIsNone(auszug_pruefen({'iban': IBAN_A}, {'CHF'}, IBAN_A))
        self.assertIsNone(auszug_pruefen({'iban': IBAN_A}, set(), ''))

    def test_fremdwaehrung_wird_abgewiesen(self):
        meldung = auszug_pruefen({'iban': IBAN_A}, {'CHF', 'EUR'}, IBAN_A)
        self.assertIn('EUR', meldung)

    def test_ungueltige_iban_wird_abgewiesen(self):
        self.assertIn('ungültig', auszug_pruefen({'iban': 'CH0000000000000000000'}, {'CHF'}, ''))

    def test_andere_iban_als_bisher_wird_abgewiesen_ausser_bei_wechsel(self):
        self.assertIn(IBAN_B, auszug_pruefen({'iban': IBAN_B}, {'CHF'}, IBAN_A))
        self.assertIsNone(auszug_pruefen({'iban': IBAN_B}, {'CHF'}, IBAN_A, iban_wechsel=True))

    def test_leerzeichen_und_kleinschreibung_spielen_keine_rolle(self):
        self.assertIsNone(auszug_pruefen({'iban': 'ch93 0076 2011 6238 5295 7'}, {'CHF'}, IBAN_A))

    def test_waehrungen_aus_xml(self):
        self.assertEqual(_camt_waehrungen(_auszug('1', '1.00', ccy='eur')), {'EUR'})
        self.assertEqual(_camt_waehrungen(b'kein xml'), set())


class ImportTests(_Basis):
    def _rechnung(self):
        from finance.models import DebitorenRechnung
        self.sollstellung()
        return DebitorenRechnung.objects.get(titel=f'Miete & NK {HEUTE.month:02d}/{HEUTE.year}')

    def test_euro_auszug_bucht_nichts(self):
        from finance.models import Kontoauszug
        r = self._rechnung()
        vorher = Kontoauszug.alle_organisationen.count()
        self.import_camt(_auszug(r.qr_referenz, '1700.00', ccy='EUR'))
        r.refresh_from_db()
        self.assertNotEqual(r.status, 'bezahlt')
        self.assertEqual(Kontoauszug.alle_organisationen.count(), vorher)

    def test_chf_auszug_wird_gebucht(self):
        r = self._rechnung()
        self.import_camt(_auszug(r.qr_referenz, '1700.00'))
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')

    def test_falsches_bankkonto_wird_erkannt(self):
        from finance.models import Kontoauszug
        r = self._rechnung()
        self.import_camt(_auszug(r.qr_referenz, '100.00', acct_ref='TX-A'))              # erster Import: IBAN A
        n = Kontoauszug.alle_organisationen.count()
        self.import_camt(_auszug(r.qr_referenz, '1600.00', iban=IBAN_B, acct_ref='TX-B'))
        self.assertEqual(Kontoauszug.alle_organisationen.count(), n)                      # abgewiesen
        r.refresh_from_db()
        self.assertNotEqual(r.status, 'bezahlt')

    def test_bewusster_wechsel_geht_mit_bestaetigung(self):
        from finance.models import Kontoauszug
        r = self._rechnung()
        self.import_camt(_auszug(r.qr_referenz, '100.00', acct_ref='TX-A'))
        n = Kontoauszug.alle_organisationen.count()
        self.c.post('/neu/bankabgleich/camt-import/', {
            'camt_datei': SimpleUploadedFile(
                'w.xml', _auszug(r.qr_referenz, '1600.00', iban=IBAN_B, acct_ref='TX-B')),
            'iban_wechsel': '1'}, follow=True)
        self.assertEqual(Kontoauszug.alle_organisationen.count(), n + 1)
