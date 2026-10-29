"""Tabellen lesen: CSV und XLSX, ohne Fremdbibliothek.

Für den Datenimport (`core/services/datenimport.py`). Liefert Kopfzeile und Zeilen als
Dict, mit der Zeilennummer, wie sie in Excel steht (Kopfzeile = 1, erste Datenzeile = 2),
damit die Fehlerliste dem Menschen sagt, wo er hinschauen muss.

XLSX wird mit `zipfile` und `xml.etree` gelesen (eine neue Abhängigkeit wie openpyxl
braucht eine Freigabe). Das genügt für Tabellen, wie sie aus Rimo, ImmoTop oder Excel
kommen: Werte, Zahlen, Daten, Text. Formeln werden mit ihrem zuletzt gespeicherten
Wert gelesen, Formatierung, Makros und Bilder ignoriert. Gegen präparierte Dateien
schützt eine Grössenschranke je Teil der Datei und die Ablehnung von DTD/Entitäten
(Entity-Expansion).
"""
import csv
import io
import re
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET

from django.utils.translation import gettext as _

MAX_BYTES = 5 * 1024 * 1024            # eine Datei
MAX_ZEILEN = 5000                      # Datenzeilen je Datei
MAX_SPALTEN = 80
_MAX_TEIL = 40 * 1024 * 1024           # unkomprimiert, je Teil einer XLSX-Datei

_NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
       'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
#: Eingebaute Zahlenformate von Excel, die ein Datum bedeuten.
_DATUM_FORMATE = set(range(14, 23)) | {27, 30, 36, 45, 46, 47, 50, 57}


class DateiFehler(ValueError):
    """Die Datei ist als Ganzes unbrauchbar. `str(e)` ist für den Menschen."""


def kopf_normieren(name):
    """Spaltenname -> Schlüssel: klein, Umlaute aufgelöst, Leerzeichen/Bindestriche -> '_'."""
    t = (name or '').strip().lower()
    for a, b in (('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss'), ('é', 'e'), ('è', 'e')):
        t = t.replace(a, b)
    t = re.sub(r'[^a-z0-9]+', '_', t).strip('_')
    return t


def lese_tabelle(name, inhalt, blatt=None):
    """(kopf: [str], zeilen: [(zeilennummer, {kopf: str})]) aus einer CSV- oder XLSX-Datei."""
    if not inhalt:
        raise DateiFehler(_('Die Datei ist leer.'))
    if len(inhalt) > MAX_BYTES:
        raise DateiFehler(_('Die Datei ist grösser als 5 MB.'))
    if inhalt[:4] == b'PK\x03\x04':
        rohzeilen = _xlsx(inhalt, blatt)
    elif (name or '').lower().endswith(('.xlsx', '.xlsm')):
        raise DateiFehler(_('Die Datei ist keine gültige Excel-Datei (.xlsx).'))
    elif (name or '').lower().endswith('.xls'):
        raise DateiFehler(_('Das alte Excel-Format (.xls) wird nicht gelesen: als .xlsx oder CSV speichern.'))
    else:
        rohzeilen = _csv(inhalt)
    return _kopf_und_zeilen(rohzeilen)


def _kopf_und_zeilen(rohzeilen):
    # Leere Zeilen am Anfang überspringen: die erste nicht leere Zeile ist die Kopfzeile.
    kopf_nr, kopf = None, None
    for nr, z in rohzeilen:
        if any(x.strip() for x in z):
            kopf_nr, kopf = nr, z
            break
    if kopf is None:
        raise DateiFehler(_('Die Datei enthält keine Kopfzeile.'))
    namen = [kopf_normieren(k) for k in kopf]
    while namen and not namen[-1]:
        namen.pop()
    if len(namen) > MAX_SPALTEN:
        raise DateiFehler(_('Die Datei hat mehr als %(n)s Spalten.') % {'n': MAX_SPALTEN})
    doppelt = sorted({n for n in namen if n and namen.count(n) > 1})
    if doppelt:
        raise DateiFehler(_('Die Spalte «%(n)s» kommt mehrfach vor.') % {'n': doppelt[0]})
    zeilen = []
    for nr, z in rohzeilen:
        if nr <= kopf_nr or not any(x.strip() for x in z):
            continue
        z = list(z) + [''] * (len(namen) - len(z))
        zeilen.append((nr, {n: z[i].strip() for i, n in enumerate(namen) if n}))
        if len(zeilen) > MAX_ZEILEN:
            raise DateiFehler(_('Höchstens %(n)s Zeilen je Datei.') % {'n': MAX_ZEILEN})
    return [n for n in namen if n], zeilen


# ── CSV ───────────────────────────────────────────────────────────────────────
def _csv(inhalt):
    try:
        text = inhalt.decode('utf-8-sig')
    except UnicodeDecodeError:
        # Excel in der Schweiz speichert «CSV» oft als Windows-1252.
        try:
            text = inhalt.decode('cp1252')
        except UnicodeDecodeError:
            raise DateiFehler(_('Die Datei ist keine lesbare Textdatei (UTF-8 oder Windows-1252).'))
    if '\x00' in text:
        raise DateiFehler(_('Die Datei ist keine Textdatei.'))
    erste = next((z for z in text.splitlines() if z.strip()), '')
    trenner = max(';,\t', key=lambda t: erste.count(t))
    if erste.count(trenner) == 0:
        trenner = ';'
    leser = csv.reader(io.StringIO(text), delimiter=trenner)
    try:
        return [(i, z) for i, z in enumerate(leser, start=1)]
    except csv.Error as e:
        raise DateiFehler(_('Die CSV-Datei ist nicht lesbar: %(e)s') % {'e': e})


# ── XLSX ──────────────────────────────────────────────────────────────────────
def _teil(zf, pfad):
    try:
        info = zf.getinfo(pfad)
    except KeyError:
        return None
    if info.file_size > _MAX_TEIL:
        raise DateiFehler(_('Die Excel-Datei ist zu gross.'))
    roh = zf.read(pfad)
    # Keine DTD, keine Entitäten: eine gültige Arbeitsmappe braucht beides nicht.
    if b'<!DOCTYPE' in roh[:4096].upper() or b'<!ENTITY' in roh.upper():
        raise DateiFehler(_('Die Excel-Datei enthält unzulässige Angaben.'))
    try:
        return ET.fromstring(roh)
    except ET.ParseError:
        raise DateiFehler(_('Die Excel-Datei ist beschädigt.'))


def _spaltenindex(ref):
    buchstaben = re.match(r'[A-Z]+', ref or '')
    if not buchstaben:
        return None
    n = 0
    for c in buchstaben.group():
        n = n * 26 + ord(c) - 64
    return n - 1


def _zahl_text(roh):
    """'1200' bleibt '1200', '1200.0' wird '1200', 1234.5 bleibt '1234.5' — ohne Gleitkomma."""
    t = (roh or '').strip()
    if re.fullmatch(r'-?\d+\.0+', t):
        return t.split('.')[0]
    if 'E' in t.upper():
        from decimal import Decimal, InvalidOperation
        try:
            return format(Decimal(t), 'f')
        except InvalidOperation:
            return t
    return t


def _xlsx(inhalt, blatt):
    try:
        zf = zipfile.ZipFile(io.BytesIO(inhalt))
    except zipfile.BadZipFile:
        raise DateiFehler(_('Die Datei ist keine gültige Excel-Datei (.xlsx).'))
    with zf:
        mappe = _teil(zf, 'xl/workbook.xml')
        if mappe is None:
            raise DateiFehler(_('Die Datei ist keine gültige Excel-Datei (.xlsx).'))
        # Blätter und ihre Dateien
        bezuege = {}
        rel = _teil(zf, 'xl/_rels/workbook.xml.rels')
        if rel is not None:
            for r in rel.findall(f'{_REL}Relationship'):
                bezuege[r.get('Id')] = r.get('Target')
        blaetter = []
        for s in mappe.findall('m:sheets/m:sheet', _NS):
            ziel = bezuege.get(s.get('{%s}id' % _NS['r']))
            if ziel:
                ziel = ziel.lstrip('/')
                blaetter.append((s.get('name') or '', ziel if ziel.startswith('xl/') else f'xl/{ziel}'))
        if not blaetter:
            raise DateiFehler(_('Die Excel-Datei enthält kein Tabellenblatt.'))
        wahl = blaetter[0]
        if blatt:
            for b in blaetter:
                if kopf_normieren(b[0]) == kopf_normieren(blatt):
                    wahl = b
                    break
        texte = []
        gemeinsam = _teil(zf, 'xl/sharedStrings.xml')
        if gemeinsam is not None:
            for si in gemeinsam.findall('m:si', _NS):
                texte.append(''.join(t.text or '' for t in si.iter('{%s}t' % _NS['m'])))
        datum_xf = _datum_stile(_teil(zf, 'xl/styles.xml'))
        blatt_xml = _teil(zf, wahl[1])
        if blatt_xml is None:
            raise DateiFehler(_('Die Excel-Datei ist beschädigt.'))
        zeilen = []
        for row in blatt_xml.iter('{%s}row' % _NS['m']):
            nr = int(row.get('r') or (zeilen[-1][0] + 1 if zeilen else 1))
            werte = {}
            for c in row.findall('m:c', _NS):
                i = _spaltenindex(c.get('r'))
                if i is None or i >= MAX_SPALTEN:
                    continue
                werte[i] = _zellwert(c, texte, datum_xf)
            if werte:
                breite = max(werte) + 1
                zeilen.append((nr, [werte.get(i, '') for i in range(breite)]))
        return zeilen


def _datum_stile(styles):
    """Indizes der Zellformate (cellXfs), die ein Datum darstellen."""
    if styles is None:
        return set()
    eigene = set()
    for nf in styles.findall('m:numFmts/m:numFmt', _NS):
        code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', '', nf.get('formatCode') or '').lower()
        if re.search(r'[dy]', code):
            eigene.add(int(nf.get('numFmtId')))
    stile = set()
    for i, xf in enumerate(styles.findall('m:cellXfs/m:xf', _NS)):
        fid = int(xf.get('numFmtId') or 0)
        if fid in _DATUM_FORMATE or fid in eigene:
            stile.add(i)
    return stile


def _zellwert(c, texte, datum_xf):
    art = c.get('t')
    v = c.find('m:v', _NS)
    if art == 'inlineStr':
        return ''.join(t.text or '' for t in c.iter('{%s}t' % _NS['m']))
    if v is None or v.text is None:
        return ''
    if art == 's':
        try:
            return texte[int(v.text)]
        except (ValueError, IndexError):
            return ''
    if art == 'b':
        return 'ja' if v.text.strip() == '1' else 'nein'
    if art in ('str', 'e'):
        return '' if art == 'e' else v.text
    # Zahl: Datumsformat -> ISO-Datum, sonst Zahlentext
    roh = v.text.strip()
    if int(c.get('s') or 0) in datum_xf:
        try:
            tage = float(roh)
            return (date(1899, 12, 30) + timedelta(days=int(tage))).isoformat()
        except (ValueError, OverflowError):
            return roh
    return _zahl_text(roh)
