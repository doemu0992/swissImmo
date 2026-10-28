"""ISO-20022 pain.001.001.09 Zahlungsauftrag (Credit Transfer) für den
e-Banking-Massenupload. Erzeugt aus freigegebenen Kreditorenrechnungen eine
XML-Datei, die im Schweizer e-Banking als Sammelzahlung eingelesen werden kann.

Bewusst schlank gehalten (CGI/SIX-kompatible Kernstruktur): eine PmtInf mit
mehreren CdtTrfTxInf.

WAS DIE DATEI NACH DEN SWISS PAYMENT STANDARDS (SPS 2026, ab 14.11.2026)
ERFÜLLEN MUSS UND WIE DIESES MODUL ES UMSETZT

* Strukturierte Anschrift (`PstlAdr`: StrtNm, BldgNb, PstCd, TwnNm, Ctry) bei
  Zahlungspflichtigem (`Dbtr`) und Begünstigtem (`Cdtr`), mindestens Ort und
  Land. Reihenfolge und Längen sind die des ISO-Schemas (Max70Text, Max16Text,
  Max16Text, Max35Text, CountryCode).
* Die Referenzart hängt an der IBAN: QR-Referenz (`Prtry` = QRR, 27 Ziffern mit
  Prüfziffer) NUR bei einer QR-IBAN, bei einer QR-IBAN NUR die QR-Referenz
  (kein `Ustrd`). Bei normaler IBAN steht die Referenz im unstrukturierten
  Verwendungszweck (`Ustrd`, höchstens 140 Zeichen).
* Die IBAN besteht die Prüfsumme (Mod 97).

Eine Zahlung, die das nicht erfüllt, wird NICHT stillschweigend ausgelassen
oder umgebogen: `pruefe_zahlungen` meldet sie je Rechnung, `generate_pain001`
erzeugt dann gar keine Datei (`ZahlungsdateiFehler`). Der Zahllauf zeigt die
Liste vor der Dateierzeugung (core/views/fw/kreditoren.py).

NICHT UMGESETZT, WEIL NICHT BELEGT (siehe Bericht, «mit Hausbank klären»):
strukturierte Referenz nach ISO 11649 (SCOR, `Issr`-Regel), `ChrgBr`,
Anschrift beim Auftraggeber der Nachricht (`InitgPty`), Auslandzahlungen
(`CdtrAgt`), Stichtag für das Ausführungsdatum, der genaue Umfang des
SPS-Zeichensatzes (hier die vorsichtige Teilmenge in `_text`).
"""
import re
import unicodedata
from collections import namedtuple
from decimal import Decimal
from xml.etree import ElementTree as ET
from xml.dom import minidom

from django.utils.translation import gettext as _

from core.services.iban import (ist_gueltige_iban, ist_qr_iban, normalisiere_iban,
                                qrr_pruefziffer_ok)

NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"

#: Obergrenze eines Einzelbetrags: 999 999 999.99 (SPS; ISO erlaubt mehr).
BETRAG_MAX = Decimal('999999999.99')

#: Ein Problem je Rechnung. `codes` sind stabile Schlüssel (name, betrag, iban,
#: adresse, referenz), `texte` die Meldungen in der Sprache des Benutzers.
Problem = namedtuple('Problem', 'rechnung_id lieferant codes texte')


class ZahlungsdateiFehler(ValueError):
    """Die Datei wird nicht erzeugt: mindestens eine Zahlung (oder der
    Auftraggeber) ist unvollständig. `probleme` ist eine Liste von `Problem`;
    `rechnung_id` None steht für den Auftraggeber."""

    def __init__(self, probleme):
        self.probleme = list(probleme)
        super().__init__('; '.join(f"{p.lieferant}: {', '.join(p.texte)}" for p in self.probleme))


def _iban_clean(iban):
    return normalisiere_iban(iban)


def _ref_clean(ref):
    return ''.join((ref or '').split())


def _is_qrr(ref):
    """27 Ziffern mit gültiger Prüfziffer (Modulo 10 rekursiv)."""
    return qrr_pruefziffer_ok(ref)


# Zeichensatz. Die SPS lassen nur einen Latin-Zeichensatz zu; seinen genauen
# Umfang konnte dieser Stand nicht an der Quelle belegen. Gewählt ist deshalb
# eine VORSICHTIGE TEILMENGE: druckbares ASCII und die Buchstaben/Zeichen von
# Latin-1 (ä, ö, ü, é, è, à, ç, … bleiben erhalten). Alles andere wird auf die
# Grundbuchstaben zurückgeführt (ł -> l, ő -> o) oder weggelassen. XML-
# Steuerzeichen (die der Serialisierer sonst unbemerkt in eine ungültige Datei
# schriebe) verschwinden in jedem Fall.
_SONDER = str.maketrans({
    'ł': 'l', 'Ł': 'L', 'đ': 'd', 'Đ': 'D', 'ħ': 'h', 'Ħ': 'H', 'ı': 'i',
    'œ': 'oe', 'Œ': 'OE', 'ẞ': 'SS',
    '‘': "'", '’': "'", '‚': "'", '“': '"', '”': '"',
    '„': '"', '–': '-', '—': '-', '−': '-', '…': '...',
    '€': 'EUR',
})


def _erlaubt(zeichen):
    code = ord(zeichen)
    return 0x20 <= code <= 0x7E or 0xA0 <= code <= 0xFF


def _text(wert, maxlaenge):
    """Bereinigt einen Text für die Datei und kürzt auf `maxlaenge` Zeichen."""
    s = unicodedata.normalize('NFC', str(wert or '')).translate(_SONDER)
    # Zeilenumbrüche und Tabulatoren sind Leerraum, keine Steuerzeichen.
    s = re.sub(r'[\t\r\n  ]+', ' ', s)
    aus = []
    for z in s:
        if _erlaubt(z):
            aus.append(z)
        else:
            # Zeichen mit Grundbuchstaben (ő -> o, ž -> z); sonst weglassen.
            zerlegt = unicodedata.normalize('NFKD', z)
            aus.extend(c for c in zerlegt if _erlaubt(c) and not unicodedata.combining(c))
    s = re.sub(r' {2,}', ' ', ''.join(aus)).strip()
    return s[:maxlaenge].strip()


def _el(parent, tag, text=None):
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e


def _adresse_normalisiert(adresse):
    adresse = adresse or {}
    return {
        'strasse': _text(adresse.get('strasse'), 70),
        'hausnummer': _text(adresse.get('hausnummer'), 16),
        'plz': _text(adresse.get('plz'), 16),
        'ort': _text(adresse.get('ort'), 35),
        'land': (adresse.get('land') or '').strip().upper(),
    }


def _fehlende_adressangaben(adresse):
    a = _adresse_normalisiert(adresse)
    fehlt = []
    if not a['ort']:
        fehlt.append(_('Ort'))
    if not re.fullmatch(r'[A-Z]{2}', a['land']):
        fehlt.append(_('Land'))
    return fehlt


def _postadresse(parent, adresse):
    """`PstlAdr` in der Reihenfolge des ISO-Schemas; leere Felder fehlen ganz
    (das Schema verlangt mindestens ein Zeichen)."""
    a = _adresse_normalisiert(adresse)
    pa = _el(parent, "PstlAdr")
    if a['strasse']:
        _el(pa, "StrtNm", a['strasse'])
    if a['hausnummer']:
        _el(pa, "BldgNb", a['hausnummer'])
    if a['plz']:
        _el(pa, "PstCd", a['plz'])
    _el(pa, "TwnNm", a['ort'])
    _el(pa, "Ctry", a['land'])


def adresse_der_rechnung(r):
    """Anschrift des Begünstigten aus den Feldern `lieferant_*` der Rechnung."""
    return {
        'strasse': getattr(r, 'lieferant_strasse', ''),
        'hausnummer': getattr(r, 'lieferant_hausnummer', ''),
        'plz': getattr(r, 'lieferant_plz', ''),
        'ort': getattr(r, 'lieferant_ort', ''),
        'land': getattr(r, 'lieferant_land', ''),
    }


def auftraggeber_adresse(organisation):
    """Anschrift der Verwaltung als Zahlungspflichtige aus `Organisation`
    (`strasse` = «Strasse & Nr.», `plz`, `ort`). Das Land hat die Organisation
    nicht als Feld: Es folgt dem Land der IBAN (CH oder LI), sonst «CH» — die
    Verwaltung führt ein Schweizer Konto, von dem die Datei zahlt."""
    from core.utils.qr_code import strasse_und_nummer
    if organisation is None:
        return {}
    strasse, nummer = strasse_und_nummer(getattr(organisation, 'strasse', ''))
    iban = _iban_clean(getattr(organisation, 'iban', ''))
    return {
        'strasse': strasse, 'hausnummer': nummer,
        'plz': (getattr(organisation, 'plz', '') or '').strip(),
        'ort': (getattr(organisation, 'ort', '') or '').strip(),
        'land': iban[:2] if iban[:2] in ('CH', 'LI') else 'CH',
    }


def pruefe_zahlung(r):
    """Alles, was gegen die Aufnahme einer Rechnung in die Zahlungsdatei
    spricht, als Liste von (code, text). Leer = zahlbar."""
    probleme = []
    if not _text(r.lieferant, 70):
        probleme.append(('name', _('Lieferantenname fehlt')))
    betrag = r.betrag
    if not betrag or betrag <= 0:
        probleme.append(('betrag', _('Betrag fehlt oder ist nicht positiv')))
    elif betrag > BETRAG_MAX:
        probleme.append(('betrag', _('Betrag über CHF 999 999 999.99')))
    iban = _iban_clean(r.iban)
    if not iban:
        probleme.append(('iban', _('IBAN fehlt')))
    elif not ist_gueltige_iban(iban):
        probleme.append(('iban', _('IBAN ungültig (Prüfziffer oder Länge stimmt nicht)')))
    fehlt = _fehlende_adressangaben(adresse_der_rechnung(r))
    if fehlt:
        probleme.append(('adresse', _('Anschrift unvollständig: %(felder)s fehlt') % {
            'felder': ', '.join(fehlt)}))
    if iban and ist_gueltige_iban(iban) and ist_qr_iban(iban) and not _is_qrr(r.referenz):
        # Eine QR-IBAN verlangt die QR-Referenz. Ohne sie lehnt die Bank die
        # Zahlung ab; ein freier Text daneben ist nach SPS ebenfalls nicht erlaubt.
        probleme.append(('referenz', _(
            'QR-IBAN, aber keine gültige QR-Referenz (27 Ziffern, Prüfziffer)')))
    return probleme


def pruefe_auftraggeber(debtor_name, debtor_iban, debtor_adresse):
    """Wie `pruefe_zahlung`, für die Verwaltung als Zahlungspflichtige."""
    probleme = []
    if not _text(debtor_name, 70):
        probleme.append(('name', _('Name der Verwaltung fehlt')))
    iban = _iban_clean(debtor_iban)
    if not iban:
        probleme.append(('iban', _('IBAN der Verwaltung fehlt')))
    elif not ist_gueltige_iban(iban):
        probleme.append(('iban', _('IBAN der Verwaltung ungültig (Prüfziffer oder Länge stimmt nicht)')))
    fehlt = _fehlende_adressangaben(debtor_adresse)
    if fehlt:
        probleme.append(('adresse', _('Anschrift der Verwaltung unvollständig: %(felder)s fehlt') % {
            'felder': ', '.join(fehlt)}))
    return probleme


def pruefe_zahlungen(rechnungen, debtor_name='', debtor_iban='', debtor_adresse=None,
                     auftraggeber_pruefen=True):
    """Prüft Auftraggeber und alle Rechnungen. Gibt eine Liste `Problem` zurück
    (leer = die Datei kann erzeugt werden)."""
    ergebnis = []
    if auftraggeber_pruefen:
        p = pruefe_auftraggeber(debtor_name, debtor_iban, debtor_adresse)
        if p:
            ergebnis.append(Problem(None, _('Verwaltung (Auftraggeber)'),
                                    [c for c, _t in p], [t for _c, t in p]))
    for r in rechnungen:
        p = pruefe_zahlung(r)
        if p:
            ergebnis.append(Problem(r.id, r.lieferant or _('(ohne Namen)'),
                                    [c for c, _t in p], [t for _c, t in p]))
    return ergebnis


def _verwendungszweck(r):
    zweck = (r.referenz or '').strip() or f"Rechnung {r.lieferant}"
    return _text(zweck, 140) or "Rechnung"


def generate_pain001(rechnungen, debtor_name, debtor_iban, msg_id, exec_date, now_iso,
                     debtor_adresse=None):
    """rechnungen: iterable von KreditorenRechnung (mit iban, betrag, lieferant,
    referenz, lieferant_strasse … lieferant_land). `debtor_adresse`: Wörterbuch
    strasse, hausnummer, plz, ort, land der Verwaltung. Gibt
    (xml_bytes, anzahl, summe) zurück.

    Wirft `ZahlungsdateiFehler`, wenn der Auftraggeber oder eine Zahlung die
    Voraussetzungen nicht erfüllt (siehe `pruefe_zahlungen`) — es gibt keine
    Teildatei. now_iso / exec_date werden übergeben (keine Zeitfunktion im
    Service)."""
    rechnungen = list(rechnungen)
    probleme = pruefe_zahlungen(rechnungen, debtor_name, debtor_iban, debtor_adresse)
    if probleme:
        raise ZahlungsdateiFehler(probleme)
    if not rechnungen:
        raise ZahlungsdateiFehler([Problem(None, _('Zahllauf'), ['leer'], [_('Keine Zahlung in der Auswahl')])])
    debtor_iban = _iban_clean(debtor_iban)
    name_dbtr = _text(debtor_name, 70)

    summe = sum((Decimal(str(r.betrag)).quantize(Decimal('0.01')) for r in rechnungen),
                Decimal('0.00'))

    root = ET.Element("Document", xmlns=NS)
    cstmr = _el(root, "CstmrCdtTrfInitn")

    # --- Group Header ---
    grp = _el(cstmr, "GrpHdr")
    _el(grp, "MsgId", msg_id)
    _el(grp, "CreDtTm", now_iso)
    _el(grp, "NbOfTxs", len(rechnungen))
    _el(grp, "CtrlSum", f"{summe:.2f}")
    initg = _el(grp, "InitgPty")
    _el(initg, "Nm", name_dbtr)

    # --- Payment Information (eine Sammelposition) ---
    pmt = _el(cstmr, "PmtInf")
    _el(pmt, "PmtInfId", msg_id)
    _el(pmt, "PmtMtd", "TRF")
    _el(pmt, "BtchBookg", "true")
    _el(pmt, "NbOfTxs", len(rechnungen))
    _el(pmt, "CtrlSum", f"{summe:.2f}")
    # Kein SvcLvl/SEPA — das gilt nur für EUR-SEPA; hier CHF-Inlandzahlung (CH-Typ 3).
    _el(pmt, "ReqdExctnDt").append(ET.Element("Dt"))
    pmt.find("ReqdExctnDt/Dt").text = exec_date
    dbtr = _el(pmt, "Dbtr")
    _el(dbtr, "Nm", name_dbtr)
    _postadresse(dbtr, debtor_adresse)
    dbtr_acct = _el(pmt, "DbtrAcct")
    dbtr_id = _el(dbtr_acct, "Id")
    _el(dbtr_id, "IBAN", debtor_iban)
    dbtr_agt = _el(pmt, "DbtrAgt")
    fininst = _el(dbtr_agt, "FinInstnId")
    othr = _el(fininst, "Othr")
    _el(othr, "Id", "NOTPROVIDED")

    for i, r in enumerate(rechnungen, start=1):
        betrag = Decimal(str(r.betrag)).quantize(Decimal('0.01'))
        iban = _iban_clean(r.iban)
        qrr = ist_qr_iban(iban)
        tx = _el(pmt, "CdtTrfTxInf")
        pid = _el(tx, "PmtId")
        _el(pid, "InstrId", f"{msg_id}-{i}")
        _el(pid, "EndToEndId", (_ref_clean(r.referenz) if qrr else _text(r.referenz, 35))
            or f"{msg_id}-{i}"[:35])
        amt = _el(tx, "Amt")
        _el(amt, "InstdAmt", f"{betrag:.2f}").set("Ccy", "CHF")
        cdtr = _el(tx, "Cdtr")
        _el(cdtr, "Nm", _text(r.lieferant, 70))
        _postadresse(cdtr, adresse_der_rechnung(r))
        cdtr_acct = _el(tx, "CdtrAcct")
        cid = _el(cdtr_acct, "Id")
        _el(cid, "IBAN", iban)
        rmt = _el(tx, "RmtInf")
        if qrr:
            strd = _el(rmt, "Strd")
            cdtr_ref = _el(strd, "CdtrRefInf")
            tp = _el(cdtr_ref, "Tp")
            org = _el(tp, "CdOrPrtry")
            _el(org, "Prtry", "QRR")
            _el(cdtr_ref, "Ref", _ref_clean(r.referenz))
        else:
            _el(rmt, "Ustrd", _verwendungszweck(r))

    xml = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(xml).toprettyxml(indent="  ", encoding="utf-8")
    return pretty, len(rechnungen), summe
