"""camt.054 (Einzelavisierung Gutschrift/Belastung) neben camt.053.

Schweizer Banken liefern QR-Eingänge oft als camt.054 pro Tag oder Eingang.
Der Import erkennt den Nachrichtentyp, ordnet per QRR zu und hält den Typ als
Quelle des Kontoauszugs fest (Nachweis, woher eine Buchung stammt).
"""
from decimal import Decimal

from core.views.fw.bankabgleich import _camt_parse, _camt_typ
from faelle.test_monatsabschluss import HEUTE, _Basis, _camt


def _camt054(referenz, betrag, acct_ref):
    return (
        '<?xml version="1.0"?>'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.054.001.08">'
        '<BkToCstmrDbtCdtNtfctn><Ntfctn><Id>N1</Id>'
        '<Acct><Id><IBAN>CH9300762011623852957</IBAN></Id></Acct>'
        f'<Ntry><CdtDbtInd>CRDT</CdtDbtInd><Amt Ccy="CHF">{betrag}</Amt>'
        f'<BookgDt><Dt>{HEUTE.isoformat()}</Dt></BookgDt>'
        f'<NtryDtls><TxDtls><Refs><AcctSvcrRef>{acct_ref}</AcctSvcrRef></Refs>'
        f'<RmtInf><Strd><CdtrRefInf><Ref>{referenz}</Ref></CdtrRefInf></Strd></RmtInf>'
        '</TxDtls></NtryDtls></Ntry></Ntfctn></BkToCstmrDbtCdtNtfctn></Document>'
    ).encode()


class Camt054Tests(_Basis):
    def test_typ_wird_erkannt(self):
        self.assertEqual(_camt_typ(_camt054('1', '1.00', 'T')), 'camt.054')
        self.assertEqual(_camt_typ(_camt([('1', '1.00', 'T')])), 'camt.053')
        self.assertEqual(_camt_typ(b'kein xml'), '')

    def test_parser_liest_eintrag_aus_avisierung(self):
        e = _camt_parse(_camt054('210000000003139471430009017', '1700.00', 'TX-054'))
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]['betrag'], Decimal('1700.00'))
        self.assertEqual(e[0]['referenz'], '210000000003139471430009017')

    def test_import_ordnet_zu_und_merkt_sich_den_typ(self):
        from finance.models import DebitorenRechnung, Kontoauszug
        self.sollstellung()
        r = DebitorenRechnung.objects.get(titel=f'Miete & NK {HEUTE.month:02d}/{HEUTE.year}')
        self.import_camt(_camt054(r.qr_referenz, '1700.00', 'TX-054'))
        r.refresh_from_db()
        self.assertEqual(r.status, 'bezahlt')
        self.assertEqual(Kontoauszug.alle_organisationen.latest('id').quelle, 'camt.054')

    def test_gegenprobe_falscher_betrag_bleibt_offen(self):
        from finance.models import DebitorenRechnung
        self.sollstellung()
        r = DebitorenRechnung.objects.get(titel=f'Miete & NK {HEUTE.month:02d}/{HEUTE.year}')
        self.import_camt(_camt054(r.qr_referenz, '100.00', 'TX-054B'))
        r.refresh_from_db()
        self.assertNotEqual(r.status, 'bezahlt')
