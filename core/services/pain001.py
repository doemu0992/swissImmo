"""ISO-20022 pain.001.001.09 Zahlungsauftrag (Credit Transfer) für den
e-Banking-Massenupload. Erzeugt aus freigegebenen Kreditorenrechnungen eine
XML-Datei, die im Schweizer e-Banking als Sammelzahlung eingelesen werden kann.

Bewusst schlank gehalten (CGI/SIX-kompatible Kernstruktur): eine PmtInf mit
mehreren CdtTrfTxInf. Strukturierte QR-Referenz (SCOR) wird gesetzt, wenn die
Kreditor-Referenz eine QR-Referenz (27 Ziffern) ist, sonst unstrukturierter
Verwendungszweck.
"""
import io
import re
from decimal import Decimal
from xml.etree import ElementTree as ET
from xml.dom import minidom

NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"


def _iban_clean(iban):
    return re.sub(r'\s+', '', (iban or '')).upper()


def _is_qrr(ref):
    r = re.sub(r'\s+', '', ref or '')
    return r.isdigit() and len(r) == 27


def _el(parent, tag, text=None):
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e


def generate_pain001(rechnungen, debtor_name, debtor_iban, msg_id, exec_date, now_iso):
    """rechnungen: iterable von KreditorenRechnung (mit iban, betrag, lieferant,
    referenz). Gibt (xml_bytes, anzahl, summe, skipped) zurück.
    skipped = Liste (id, grund) für Rechnungen ohne gültige IBAN/Betrag.
    now_iso / exec_date werden übergeben (keine Zeitfunktion im Service)."""
    debtor_iban = _iban_clean(debtor_iban)
    gueltig, skipped = [], []
    for r in rechnungen:
        iban = _iban_clean(r.iban)
        if not iban or not r.betrag or r.betrag <= 0:
            skipped.append((r.id, "keine IBAN oder Betrag"))
            continue
        gueltig.append(r)

    summe = sum((Decimal(str(r.betrag)) for r in gueltig), Decimal('0.00'))

    root = ET.Element("Document", xmlns=NS)
    cstmr = _el(root, "CstmrCdtTrfInitn")

    # --- Group Header ---
    grp = _el(cstmr, "GrpHdr")
    _el(grp, "MsgId", msg_id)
    _el(grp, "CreDtTm", now_iso)
    _el(grp, "NbOfTxs", len(gueltig))
    _el(grp, "CtrlSum", f"{summe:.2f}")
    initg = _el(grp, "InitgPty")
    _el(initg, "Nm", (debtor_name or "Immobilienverwaltung")[:70])

    # --- Payment Information (eine Sammelposition) ---
    pmt = _el(cstmr, "PmtInf")
    _el(pmt, "PmtInfId", msg_id)
    _el(pmt, "PmtMtd", "TRF")
    _el(pmt, "BtchBookg", "true")
    _el(pmt, "NbOfTxs", len(gueltig))
    _el(pmt, "CtrlSum", f"{summe:.2f}")
    # Kein SvcLvl/SEPA — das gilt nur für EUR-SEPA; hier CHF-Inlandzahlung (CH-Typ 3).
    _el(pmt, "ReqdExctnDt").append(ET.Element("Dt"))
    pmt.find("ReqdExctnDt/Dt").text = exec_date
    dbtr = _el(pmt, "Dbtr")
    _el(dbtr, "Nm", (debtor_name or "Immobilienverwaltung")[:70])
    dbtr_acct = _el(pmt, "DbtrAcct")
    dbtr_id = _el(dbtr_acct, "Id")
    _el(dbtr_id, "IBAN", debtor_iban)
    dbtr_agt = _el(pmt, "DbtrAgt")
    fininst = _el(dbtr_agt, "FinInstnId")
    othr = _el(fininst, "Othr")
    _el(othr, "Id", "NOTPROVIDED")

    for i, r in enumerate(gueltig, start=1):
        betrag = Decimal(str(r.betrag)).quantize(Decimal('0.01'))
        tx = _el(pmt, "CdtTrfTxInf")
        pid = _el(tx, "PmtId")
        _el(pid, "InstrId", f"{msg_id}-{i}")
        _el(pid, "EndToEndId", (r.referenz or f"{msg_id}-{i}")[:35])
        amt = _el(tx, "Amt")
        _el(amt, "InstdAmt", f"{betrag:.2f}").set("Ccy", "CHF")
        cdtr = _el(tx, "Cdtr")
        _el(cdtr, "Nm", (r.lieferant or "Kreditor")[:70])
        cdtr_acct = _el(tx, "CdtrAcct")
        cid = _el(cdtr_acct, "Id")
        _el(cid, "IBAN", _iban_clean(r.iban))
        rmt = _el(tx, "RmtInf")
        if _is_qrr(r.referenz):
            strd = _el(rmt, "Strd")
            cdtr_ref = _el(strd, "CdtrRefInf")
            tp = _el(cdtr_ref, "Tp")
            org = _el(tp, "CdOrPrtry")
            _el(org, "Prtry", "QRR")
            _el(cdtr_ref, "Ref", re.sub(r'\s+', '', r.referenz))
        else:
            zweck = r.referenz or f"Rechnung {r.lieferant}"
            _el(rmt, "Ustrd", zweck[:140])

    xml = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(xml).toprettyxml(indent="  ", encoding="utf-8")
    return pretty, len(gueltig), summe, skipped
