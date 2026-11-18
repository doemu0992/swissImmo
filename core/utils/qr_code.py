import logging
import io
import os
import re
import segno
import reportlab.lib.utils
from decimal import ROUND_HALF_UP, Decimal

from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from django.conf import settings
from django.utils import dateformat, timezone, translation
from django.utils.translation import gettext as _

from core.services.dokumentsprache import sprache_von
from core.utils.betrag import betrag_text_zahlteil

logger = logging.getLogger(__name__)


def format_iban(iban):
    """Formatiert IBAN in 4er Blöcke, linksbündig («CH43 3199 9000 0012 6578 9»)."""
    if not iban:
        return ""
    iban = iban.replace(" ", "")
    return " ".join(iban[i:i+4] for i in range(0, len(iban), 4))


def strasse_und_nummer(zeile):
    """Zerlegt «Musterstrasse 12a» in ('Musterstrasse', '12a').

    Ohne erkennbare Nummer bleibt die Hausnummer leer — das ist zulässig,
    die Strasse allein genügt."""
    text = (zeile or '').strip()
    if not text:
        return '', ''
    # Hausnummer am Ende: Ziffern, optional Buchstabe, optional Bereich (12-14, 12/3)
    m = re.search(r'\s(\d+\s*[a-zA-Z]?(?:\s*[-/]\s*\d+\s*[a-zA-Z]?)?)$', text)
    if not m:
        return text[:70], ''
    return text[:m.start()].strip()[:70], m.group(1).replace(' ', '')[:16]


def plz_und_ort(zeile):
    """Zerlegt «3000 Bern» oder «CH-3000 Bern» in ('3000', 'Bern')."""
    text = (zeile or '').strip()
    if not text:
        return '', ''
    m = re.match(r'^(?:[A-Za-z]{2}\s*-\s*)?(\d{4,5})\s+(.*)$', text)
    if not m:
        return '', text[:35]
    return m.group(1)[:16], m.group(2).strip()[:35]


def adressblock(daten, pflicht=True):
    """Sieben Felder der STRUKTURIERTEN Adresse für den QR-Datenblock.

    Ab den Swiss Implementation Guidelines v2.4 — eingeführt mit dem
    SIC-Release vom 13. November 2026 — wird ausschliesslich die strukturierte
    Adresse unterstützt; die bisher hier verwendete kombinierte Adresse («K»)
    entfällt. Einzahlungsscheine mit kombinierter Adresse werden dann
    abgewiesen.

    Die Aufrufer liefern die Adresse historisch als zwei Zeilen (`line1` =
    Strasse mit Hausnummer, `line2` = «PLZ Ort»); die werden hier zerlegt.
    Wer die Felder einzeln hat, gibt sie direkt mit (`strasse`, `hausnummer`,
    `plz`, `ort`, `land`) — das ist der genauere Weg und geht vor. Die
    Debitoren- und Mail-Wege tun das inzwischen; Zerlegen ist nur der Notnagel.

    `pflicht=False` für den Schuldner: Ist er unbekannt oder fehlt ihm die
    Adresse (Leerstand, Sammelposten), verlangt die Spezifikation, dass ALLE
    sieben Felder leer bleiben — ein halb gefülltes «S» ohne Postleitzahl und
    Ort wäre ein ungültiger Einzahlungsschein. Vorher war das eine kombinierte
    Adresse, die diese Lücke noch verkraftete.
    """
    strasse = (daten.get('strasse') or '').strip()
    hausnummer = (daten.get('hausnummer') or '').strip()
    if not strasse:
        strasse, nr_aus_zeile = strasse_und_nummer(daten.get('line1', ''))
        hausnummer = hausnummer or nr_aus_zeile
    plz = (daten.get('plz') or '').strip()
    ort = (daten.get('ort') or '').strip()
    if not (plz and ort):
        plz_z, ort_z = plz_und_ort(daten.get('line2', ''))
        plz = plz or plz_z
        ort = ort or ort_z
    name = (daten.get('name', '') or '').strip()

    vollstaendig = bool(name and plz and ort)
    if not vollstaendig:
        if not pflicht:
            return ['', '', '', '', '', '', '']      # Block bewusst weglassen
        logger.warning(
            "QR-Rechnung: unvollständige Empfängeradresse (Name=%r, PLZ=%r, Ort=%r) — "
            "Stammdaten ergänzen, sonst weisen Banken den Einzahlungsschein ab.",
            name, plz, ort)

    return ['S', name[:70], strasse[:70], hausnummer[:16],
            plz[:16], ort[:35], (daten.get('land') or 'CH')[:2]]


# Eine einzige Definition: `core.services.iban.ist_qr_iban` (prüft Länge, CH/LI und die Kennung 30000–31999).
from core.services.iban import ist_qr_iban  # noqa: E402,F401  (hier weiter importierbar)


def betrag_payload(amount):
    """Betrag für den QR-Code: zwei Stellen, kaufmännisch gerundet, ohne Umweg über `float` (0.125 → 0.13, nicht 0.12)."""
    if amount is None:
        return ""
    return str(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class QrReferenzFehlt(ValueError):
    """Zur QR-IBAN fehlt die (gültige) QR-Referenz: Einen Einzahlungsschein mit
    «NON» lehnt das E-Banking ab, also wird er nicht gezeichnet."""


def sammelreferenz(vertrag_id):
    """Gültige QR-Referenz für ein Schreiben, das MEHRERE Forderungen eines
    Vertrags zugleich mahnt (257d mit mehreren fälligen Posten). Sie trägt die
    Vertragsnummer und die Rechnungsnummer 0 — keine Forderung hat die 0, also
    wird die Zahlung keiner einzelnen zugeschlagen. Die Zuordnung im
    Bankabgleich bleibt Handarbeit (Zahlungsklärung)."""
    return qrr_referenz(vertrag_id, 0)[0]


def qrr_referenz(vertrag_id, rechnung_id):
    """27-stellige QRR-Referenz (Modulo-10-rekursiv). Gibt (raw, formatiert) zurück."""
    basis = f"{(vertrag_id or 0):010d}{(rechnung_id or 0):016d}"
    tabelle = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]
    uebertrag = 0
    for z in basis:
        uebertrag = tabelle[(uebertrag + int(z)) % 10]
    pruef = (10 - uebertrag) % 10
    ref = basis + str(pruef)
    formatiert = ' '.join([ref[0:2], ref[2:7], ref[7:12], ref[12:17], ref[17:22], ref[22:27]])
    return ref, formatiert

# ---------------------------------------------------------------------------
# Zahlteil und Empfangsschein (Style Guide QR-Rechnung, SIX / Swiss Payment Standards)
#
# Alle Masse in mm, Y-Werte vom OBEREN Rand der 105 mm hohen Zahlteil-Zone aus
# gemessen («oben»), damit sie sich mit dem Style Guide vergleichen lassen.
# Empfangsschein 62 x 105 mm, Zahlteil 148 x 105 mm, überall 5 mm Rand, QR-Code
# 46 x 46 mm (ohne Ruhezone), Schweizer Kreuz 7 x 7 mm.
# ---------------------------------------------------------------------------
ZONE_HOEHE = 105
EMPFANGSSCHEIN_BREITE = 62
RAND = 5
RS_TEXTBREITE = EMPFANGSSCHEIN_BREITE - 2 * RAND            # 52 mm
ZT_LINKS = EMPFANGSSCHEIN_BREITE + RAND                     # 67 mm: QR-Code, Währung, Betrag
ZT_DETAIL_LINKS = ZT_LINKS + 46 + RAND                      # 118 mm: Angaben rechts vom QR-Code
ZT_TEXTBREITE = 210 - RAND - ZT_DETAIL_LINKS                # 87 mm
QR_OBEN = 17
WAEHRUNG_OBEN = 72
PT = 25.4 / 72                                              # 1 pt in mm

#: (Schriftgrösse, Zeilenabstand) in pt laut Style Guide: Überschrift, Wert, Betrag, je Teil.
#: Der Empfangsschein trägt zusätzlich die Annahmestelle (6 pt fett / 8), der Zahlteil die
#: «Weitere Informationen» (7 pt / 8).
SCHRIFT_TITEL = 11
SCHRIFT_EMPFANGSSCHEIN = {'kopf': (6, 9), 'wert': (8, 9), 'betrag': (8, 11), 'annahme': (6, 8)}
SCHRIFT_ZAHLTEIL = {'kopf': (8, 11), 'wert': (10, 11), 'betrag': (10, 13), 'weitere': (7, 8)}
#: Zeilenlänge für Angaben, die der Style Guide kürzen lässt (Mitteilung, Alternative Verfahren).
ZEILENLAENGE = 90
WEITERE_OBEN = 91                                           # Weitere Informationen: unten im Zahlteil
ANNAHMESTELLE_OBEN = 93


def zeile_kuerzen(text, laenge=ZEILENLAENGE):
    """Style Guide: Ist eine Zeile länger als ca. 90 Zeichen, steht sie mit «…» am Ende gekürzt da.
    Nur für Angaben, die nicht Personendaten sind — Namen und Adressen werden umbrochen, nie gekürzt."""
    text = ' '.join(str(text or '').split())
    return text if len(text) <= laenge else text[:laenge - 1].rstrip() + '…'


def zahlteil_texte(sprache='de'):
    """Die Überschriften des Zahlteils in der gewünschten Sprache (Style Guide, Anhang
    «Mehrsprachige Überschriften»). Standard Deutsch — wie bisher alle Dokumente."""
    with translation.override(sprache):
        return {
            'zahlteil': _("Zahlteil"),
            'empfangsschein': _("Empfangsschein"),
            'konto': _("Konto / Zahlbar an"),
            'referenz': _("Referenz"),
            'info': _("Zusätzliche Informationen"),
            'zahlbar_durch': _("Zahlbar durch"),
            'zahlbar_durch_leer': _("Zahlbar durch (Name/Adresse)"),
            'waehrung': _("Währung"),
            'betrag': _("Betrag"),
            'annahmestelle': _("Annahmestelle"),
            'weitere': _("Weitere Informationen"),
        }


def referenz_formatieren(ref_typ, referenz):
    """Referenz fürs Auge: QRR in 5er-Gruppen von RECHTS (27 Stellen: 2+5·5), SCOR in
    4er-Gruppen von links. Anderes (NON, leer) bleibt wie es ist."""
    roh = (referenz or '').replace(' ', '')
    if ref_typ == 'QRR':
        kopf = len(roh) % 5
        gruppen = ([roh[:kopf]] if kopf else []) + [roh[i:i + 5] for i in range(kopf, len(roh), 5)]
        return ' '.join(gruppen)
    if ref_typ == 'SCOR':
        return ' '.join(roh[i:i + 4] for i in range(0, len(roh), 4))
    return roh


def text_umbrechen(text, schrift, groesse, breite_mm):
    """Zerlegt `text` in Zeilen, die in `breite_mm` passen (Umbruch an Leerzeichen; ein
    einzelnes zu langes Wort wird hart getrennt). Leere Zeilen fallen weg."""
    grenze = breite_mm * mm
    zeilen = []
    for absatz in str(text or '').splitlines():
        aktuell = ''
        for wort in absatz.split():
            while stringWidth(wort, schrift, groesse) > grenze:
                n = len(wort) - 1
                while n > 1 and stringWidth(wort[:n], schrift, groesse) > grenze:
                    n -= 1
                if aktuell:
                    zeilen.append(aktuell)
                    aktuell = ''
                zeilen.append(wort[:n])
                wort = wort[n:]
            probe = f"{aktuell} {wort}" if aktuell else wort
            if aktuell and stringWidth(probe, schrift, groesse) > grenze:
                zeilen.append(aktuell)
                aktuell = wort
            else:
                aktuell = probe
        if aktuell:
            zeilen.append(aktuell)
    return zeilen


def draw_cross(c, x, y):
    """Schweizer Kreuz in der Mitte des QR-Codes (Mittelpunkt x/y): 7 x 7 mm, davon ein
    weisser Rand und ein schwarzes Quadrat von 6 x 6 mm mit weissem Kreuz."""
    c.saveState()
    c.setFillColorRGB(1, 1, 1)
    c.rect(x - 3.5*mm, y - 3.5*mm, 7*mm, 7*mm, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    c.rect(x - 3*mm, y - 3*mm, 6*mm, 6*mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    breite, laenge = 1.2 * mm, 4.05 * mm
    c.rect(x - breite/2, y - laenge/2, breite, laenge, fill=1, stroke=0)
    c.rect(x - laenge/2, y - breite/2, laenge, breite, fill=1, stroke=0)
    c.restoreState()


def _leeres_feld(c, links, oben, breite, hoehe):
    """Rahmen aus vier Eckmarken (Style Guide) für ein Feld, das von Hand ausgefüllt wird."""
    c.saveState()
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.75)
    c.setLineCap(2)
    x0, x1 = links * mm, (links + breite) * mm
    y0, y1 = (ZONE_HOEHE - oben) * mm, (ZONE_HOEHE - oben - hoehe) * mm
    for x, dx in ((x0, 3*mm), (x1, -3*mm)):
        for y, dy in ((y0, -3*mm), (y1, 3*mm)):
            c.line(x, y, x + dx, y)
            c.line(x, y, x, y + dy)
    c.restoreState()


def _spalte(c, links, breite, oben, bloecke, groessen):
    """Zeichnet Blöcke aus Überschrift + Zeilen (oder einem leeren Feld) untereinander.

    Zeilenabstände laut Style Guide: Von der Überschrift zur ersten Zeile gilt der Abstand der
    Überschrift, danach der des Werts; zwischen zwei Blöcken bleibt eine Leerzeile.
    Lange Zeilen werden auf `breite` umbrochen (Pflichtangaben) oder auf 90 Zeichen mit «…» gekürzt
    (Block mit `kuerzen`). Gibt die Position (oben, mm) unter dem letzten Block zurück."""
    kopf, kopf_abstand = groessen['kopf']
    wert, wert_abstand = groessen['wert']
    y = oben
    for nr, (titel, zeilen, feld, kuerzen) in enumerate(bloecke):
        if nr:
            y += wert_abstand * PT                       # Leerzeile zwischen den Blöcken
        c.setFont("Helvetica-Bold", kopf)
        c.drawString(links * mm, (ZONE_HOEHE - y) * mm, titel)
        if feld:
            _leeres_feld(c, links, y + 1.5, *feld)
            y += 1.5 + feld[1]
            continue
        y += kopf_abstand * PT
        c.setFont("Helvetica", wert)
        for zeile in zeilen:
            if kuerzen:
                zeile = zeile_kuerzen(zeile)
            for teil in text_umbrechen(zeile, "Helvetica", wert, breite):
                c.drawString(links * mm, (ZONE_HOEHE - y) * mm, teil)
                y += wert_abstand * PT
    return y


def _adresszeilen(angaben):
    return [z for z in (angaben.get('name', ''), angaben.get('line1', ''), angaben.get('line2', ''))
            if z and z.strip()]


def _waehrung_betrag(c, t, links, betrag_links, oben, groessen, betrag_anzeige, feld):
    """Block «Währung / Betrag»: Überschriften, «CHF», der Betrag — oder, ohne Betrag, das Leerfeld."""
    kopf, kopf_abstand = groessen['kopf']
    wert, _abstand = groessen['betrag']
    c.setFont("Helvetica-Bold", kopf)
    c.drawString(links * mm, (ZONE_HOEHE - oben) * mm, t['waehrung'])
    c.drawString(betrag_links * mm, (ZONE_HOEHE - oben) * mm, t['betrag'])
    c.setFont("Helvetica", wert)
    zeile = oben + kopf_abstand * PT
    c.drawString(links * mm, (ZONE_HOEHE - zeile) * mm, "CHF")
    if betrag_anzeige:
        c.drawString(betrag_links * mm, (ZONE_HOEHE - zeile) * mm, betrag_anzeige)
    else:
        _leeres_feld(c, betrag_links, oben + 1.5, *feld)


def zahlteil_zeichnen(c, *, qr_data, iban, creditor, debtor, amount, reason,
                      ref_typ='NON', ref_val='', sprache='de', alternative_verfahren=()):
    """Zeichnet Empfangsschein und Zahlteil in die untere Blatthälfte (105 mm).

    Eine einzige Stelle für alle QR-Rechnungen. `qr_data` ist der fertige Datenteil des
    QR-Codes — er wird hier nur abgebildet, nie verändert. `amount` darf fehlen (None):
    dann bleibt das Betragsfeld als Rahmen zum Ausfüllen leer. Ohne Schuldner steht an
    der Stelle ebenfalls ein leerer Rahmen. `sprache`: Sprache des Empfängers (wie alle
    Dokumente, `dokumentsprache.sprache_von`); unbekannt oder leer → Deutsch.
    `alternative_verfahren`: die Zeilen aus dem Datenteil, gedruckt unter «Weitere Informationen»."""
    from core.services.dokumentsprache import gueltige_sprache
    t = zahlteil_texte(gueltige_sprache(sprache))
    iban_text = format_iban(iban)
    ref_text = referenz_formatieren(ref_typ, ref_val) if ref_typ in ('QRR', 'SCOR') and ref_val else ''
    # Gedruckt mit Blank als Tausendertrenner («1 590.00»); der Datenteil bleibt ohne Trenner.
    betrag_anzeige = betrag_text_zahlteil(Decimal(str(amount))) if amount is not None else ''
    hat_schuldner = bool(debtor and (debtor.get('name') or '').strip())

    # Hinweis an die Canvas: Auf dieser Seite steht keine Fusszeile (Zahlteil füllt die Hälfte).
    if hasattr(c, 'ohne_fuss'):
        c.ohne_fuss()

    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)

    # Perforation: waagrecht über dem Zahlteil, senkrecht zwischen Empfangsschein und Zahlteil
    c.saveState()
    c.setDash(1, 4)
    c.setLineWidth(0.5)
    c.line(0, ZONE_HOEHE*mm, 210*mm, ZONE_HOEHE*mm)
    c.line(EMPFANGSSCHEIN_BREITE*mm, 0, EMPFANGSSCHEIN_BREITE*mm, ZONE_HOEHE*mm)
    c.restoreState()
    c.setFont("ZapfDingbats", 10)
    c.drawString(10*mm, (ZONE_HOEHE + 2)*mm, "✂")
    c.saveState()
    c.translate((EMPFANGSSCHEIN_BREITE - 2)*mm, 80*mm)
    c.rotate(-90)
    c.setFont("ZapfDingbats", 10)
    c.drawString(0, 0, "✂")
    c.restoreState()

    # Titel
    c.setFont("Helvetica-Bold", SCHRIFT_TITEL)
    c.drawString(RAND*mm, (ZONE_HOEHE - 10)*mm, t['empfangsschein'])
    c.drawString(ZT_LINKS*mm, (ZONE_HOEHE - 10)*mm, t['zahlteil'])

    # --- Empfangsschein: Konto, Referenz, Zahlbar durch, Währung / Betrag, Annahmestelle ---
    rs_bloecke = [(t['konto'], [iban_text, *_adresszeilen(creditor)], None, False)]
    if ref_text:
        rs_bloecke.append((t['referenz'], [ref_text], None, False))
    if hat_schuldner:
        rs_bloecke.append((t['zahlbar_durch'], _adresszeilen(debtor), None, False))
    else:
        rs_bloecke.append((t['zahlbar_durch_leer'], [], (RS_TEXTBREITE, 20), False))
    _spalte(c, RAND, RS_TEXTBREITE, 15, rs_bloecke, SCHRIFT_EMPFANGSSCHEIN)

    _waehrung_betrag(c, t, RAND, RAND + 12, WAEHRUNG_OBEN, SCHRIFT_EMPFANGSSCHEIN, betrag_anzeige, (30, 10))

    # Annahmestelle (rechtsbündig am rechten Textrand)
    kopf, _abstand = SCHRIFT_EMPFANGSSCHEIN['annahme']
    c.setFont("Helvetica-Bold", kopf)
    c.drawRightString((EMPFANGSSCHEIN_BREITE - RAND)*mm, (ZONE_HOEHE - ANNAHMESTELLE_OBEN)*mm,
                      t['annahmestelle'])

    # --- Zahlteil: QR-Code, Währung / Betrag, Konto, Referenz, Mitteilung, Zahlbar durch, Weitere ---
    qr = segno.make(qr_data, error='M')
    qr_img = io.BytesIO()
    qr.save(qr_img, kind='png', scale=8, border=0)       # 46 mm sind die Module, ohne Ruhezone
    qr_img.seek(0)
    c.drawImage(reportlab.lib.utils.ImageReader(qr_img), ZT_LINKS*mm, (ZONE_HOEHE - QR_OBEN - 46)*mm,
                width=46*mm, height=46*mm)
    draw_cross(c, (ZT_LINKS + 23)*mm, (ZONE_HOEHE - QR_OBEN - 23)*mm)

    _waehrung_betrag(c, t, ZT_LINKS, ZT_LINKS + 15, WAEHRUNG_OBEN, SCHRIFT_ZAHLTEIL, betrag_anzeige, (40, 15))

    zt_bloecke = [(t['konto'], [iban_text, *_adresszeilen(creditor)], None, False)]
    if ref_text:
        zt_bloecke.append((t['referenz'], [ref_text], None, False))
    if (reason or '').strip():
        zt_bloecke.append((t['info'], [reason], None, True))
    if hat_schuldner:
        zt_bloecke.append((t['zahlbar_durch'], _adresszeilen(debtor), None, False))
    else:
        zt_bloecke.append((t['zahlbar_durch_leer'], [], (65, 25), False))
    ende = _spalte(c, ZT_DETAIL_LINKS, ZT_TEXTBREITE, 10, zt_bloecke, SCHRIFT_ZAHLTEIL)

    weitere = [z for z in (alternative_verfahren or ()) if (z or '').strip()][:2]
    if weitere:
        _spalte(c, ZT_DETAIL_LINKS, ZT_TEXTBREITE, max(WEITERE_OBEN, ende + 2),
                [(t['weitere'], [z[:100] for z in weitere], None, True)],
                {'kopf': SCHRIFT_ZAHLTEIL['weitere'], 'wert': SCHRIFT_ZAHLTEIL['weitere']})


def draw_qr_bill(c, iban, creditor, debtor, amount, reason, reference=None, sprache='de',
                 alternative_verfahren=()):
    """
    Zeichnet den offiziellen QR-Teil unten auf das Blatt.
    Funktioniert für Mietzins UND Nebenkosten.
    reference: 27-stellige QRR-Referenz (ohne Leerzeichen). Bei QR-IBAN Pflicht.
    """
    # 1. Daten Vorbereiten
    raw_iban = iban.replace(" ", "")

    # Referenztyp korrekt bestimmen (SIX-Spec): QR-IBAN => QRR + Referenz, sonst NON.
    # Eine QR-IBAN OHNE gültige QR-Referenz ergäbe einen Einzahlungsschein mit
    # «NON», den das E-Banking ablehnt (FIN-11). Den gibt es nicht still: Der
    # Aufrufer bekommt einen Fehler und liefert die Referenz.
    ref_raw = (reference or "").replace(" ", "")
    if ist_qr_iban(raw_iban):
        from core.services.iban import qrr_pruefziffer_ok
        if not qrr_pruefziffer_ok(ref_raw):
            raise QrReferenzFehlt(
                "QR-IBAN %s braucht eine gültige QR-Referenz (27 Ziffern, Prüfziffer); "
                "erhalten: %r." % (raw_iban, reference))
        ref_typ, ref_val = "QRR", ref_raw
    else:
        ref_typ, ref_val = "NON", ""

    # Creditor (Empfänger = Verwaltung/Eigentuemer)
    creditor_data = {
        'name': creditor.get('name', '')[:70],
        'line1': creditor.get('line1', '')[:70],
        'line2': creditor.get('line2', '')[:70],
    }

    # Debtor (Zahler = Mieter)
    debtor_data = {
        'name': debtor.get('name', '')[:70],
        'line1': debtor.get('line1', '')[:70],
        'line2': debtor.get('line2', '')[:70],
    }

    # Alternative Verfahren: höchstens zwei Zeilen zu 100 Zeichen; ohne bleibt ein leeres Feld.
    av = [z.strip()[:100] for z in (alternative_verfahren or ()) if (z or '').strip()][:2] or [""]

    # QR Daten Payload (SIX Specs) — strukturierte Adressen, siehe adressblock().
    qr_data = "\n".join([
        "SPC", "0200", "1", raw_iban,
        *adressblock(creditor),
        "", "", "", "", "", "", "",
        betrag_payload(amount), "CHF",
        *adressblock(debtor, pflicht=False),
        ref_typ, ref_val, reason[:140], "EPD", *av
    ])

    # Gezeichnet wird in zahlteil_zeichnen(): die Darstellung nach Style Guide, an einer Stelle.
    zahlteil_zeichnen(c, qr_data=qr_data, iban=raw_iban, creditor=creditor_data, debtor=debtor_data,
                      amount=amount, reason=reason, ref_typ=ref_typ, ref_val=ref_val, sprache=sprache,
                      alternative_verfahren=[z for z in av if z])


def generate_mieter_qr_pdf(mieter, vertrag, verwaltung):
    """
    Erstellt ein PDF mit dem QR-Zahlteil für einen Mieter/Vertrag.
    """
    output_dir = os.path.join(settings.MEDIA_ROOT, 'qr_rechnungen')
    os.makedirs(output_dir, exist_ok=True)
    filename = f"QR_Rechnung_{mieter.id}_{vertrag.id}.pdf"
    file_path = os.path.join(output_dir, filename)

    # 1. Daten zusammensuchen
    iban = getattr(verwaltung, 'iban', None) or "CH0000000000000000000"

    creditor = {
        'name': getattr(verwaltung, 'firma', ''),
        'line1': getattr(verwaltung, 'strasse', ''),
        'line2': f"{getattr(verwaltung, 'plz', '')} {getattr(verwaltung, 'ort', '')}".strip()
    }

    debtor = {
        'name': f"{mieter.vorname} {mieter.nachname}".strip() or getattr(mieter, 'display_name', ''),
        'line1': getattr(mieter, 'strasse', ''),
        'line2': f"{getattr(mieter, 'plz', '')} {getattr(mieter, 'ort', '')}".strip()
    }

    amount = vertrag.brutto_mietzins
    monat = timezone.now().strftime("%m/%Y")
    reason = f"Miete {vertrag.einheit.bezeichnung} - {monat}"

    ref = None
    if ist_qr_iban(iban):
        ref, _ = qrr_referenz(vertrag.id, int(timezone.now().strftime("%Y%m")))

    # 2. PDF generieren
    c = canvas.Canvas(file_path, pagesize=A4)

    # Text oben auf der A4-Seite
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20*mm, 260*mm, "Einzahlungsschein Mietzins")
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, 250*mm, f"Mieter: {debtor['name']}")
    c.drawString(20*mm, 245*mm, f"Objekt: {vertrag.einheit.bezeichnung}")
    c.drawString(20*mm, 235*mm, "Bitte verwenden Sie den untenstehenden Einzahlungsschein für Ihre Überweisung.")

    # 3. QR-Funktion aufrufen (zeichnet unten den Zahlteil)
    draw_qr_bill(c, iban, creditor, debtor, amount, reason, reference=ref, sprache=sprache_von(mieter))

    c.save()

    # 4. URL zurückgeben
    return f"{settings.MEDIA_URL}qr_rechnungen/{filename}"

# 🔥 NEU: Die Funktion für den Mahnbrief nach deiner Vorlage
def generate_mahnung_pdf(vertrag, offener_betrag, verwaltung):
    output_dir = os.path.join(settings.MEDIA_ROOT, 'qr_rechnungen')
    os.makedirs(output_dir, exist_ok=True)
    filename = f"Mahnung_{vertrag.mieter.id}_{vertrag.id}.pdf"
    file_path = os.path.join(output_dir, filename)

    mieter = vertrag.mieter
    iban = getattr(verwaltung, 'iban', None) or "CH0000000000000000000"

    creditor = {
        'name': getattr(verwaltung, 'firma', ''),
        'line1': getattr(verwaltung, 'strasse', ''),
        'line2': f"{getattr(verwaltung, 'plz', '')} {getattr(verwaltung, 'ort', '')}".strip()
    }

    debtor = {
        'name': f"{mieter.vorname} {mieter.nachname}".strip() or getattr(mieter, 'display_name', ''),
        'line1': getattr(mieter, 'strasse', ''),
        'line2': f"{getattr(mieter, 'plz', '')} {getattr(mieter, 'ort', '')}".strip()
    }

    heute = timezone.now()
    # Monatsnamen nicht über strftime (Server-Locale, oft Englisch).
    # Bis Dokumente der Empfängersprache folgen (D11), bleibt es Deutsch.
    with translation.override('de'):
        monat_text = dateformat.format(heute, 'F Y')  # Wird für die Rechnung genutzt
        datum_text = dateformat.format(heute, 'd. F Y')  # Datum oben rechts

    # Grund für den QR Code
    reason = f"Mahnung Miete {vertrag.einheit.bezeichnung}"

    ref = None
    if ist_qr_iban(iban):
        ref, _ = qrr_referenz(vertrag.id, int(timezone.now().strftime("%Y%m")))

    c = canvas.Canvas(file_path, pagesize=A4)

    # --- 1. Adressblock (Für C5 Fensterkuvert) ---
    c.setFont("Helvetica", 11)
    c.drawString(20*mm, 245*mm, debtor['name'])
    c.drawString(20*mm, 240*mm, debtor['line1'])
    c.drawString(20*mm, 235*mm, debtor['line2'])

    # --- 2. Ort und Datum (Rechtsbündig) ---
    c.drawString(120*mm, 205*mm, f"{getattr(verwaltung, 'ort', 'Ort')} {datum_text}")

    # --- 3. Betreff ---
    y_pos = 185*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20*mm, y_pos, "MAHNUNG / KÜNDIGUNGSANDROHUNG")
    c.setFont("Helvetica", 11)
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, f"{vertrag.einheit.liegenschaft.strasse}, {vertrag.einheit.bezeichnung}")

    # --- 4. Anrede ---
    y_pos -= 15*mm
    anrede = "Frau" if getattr(mieter, 'anrede', '') == 'Frau' else "Herr"
    c.drawString(20*mm, y_pos, f"Sehr geehrte(r) {anrede} {mieter.nachname}")

    # --- 5. Einleitungstext ---
    y_pos -= 10*mm
    c.drawString(20*mm, y_pos, "Ihr Konto weist folgende offene Posten auf:")
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, f"(Zahlungen berücksichtigt bis {heute.strftime('%d.%m.%Y')})")

    # --- 6. Tabelle (Offene Posten) ---
    y_pos -= 15*mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, y_pos, "Positionen")
    c.drawString(80*mm, y_pos, "fällig am")
    c.drawString(110*mm, y_pos, "Stufe")
    c.drawString(140*mm, y_pos, "Betrag")

    # Linie unter Header
    y_pos -= 2*mm
    c.line(20*mm, y_pos, 160*mm, y_pos)

    # Zeile
    y_pos -= 5*mm
    c.setFont("Helvetica", 10)

    # Fälligkeit ist der letzte Tag des Vormonats (Beispielhaft)
    faelligkeits_datum = heute.replace(day=1) - timezone.timedelta(days=1)

    c.drawString(20*mm, y_pos, f"Miete {vertrag.einheit.bezeichnung}")
    c.drawString(80*mm, y_pos, faelligkeits_datum.strftime('%d.%m.%Y'))
    c.drawString(110*mm, y_pos, "1")
    c.drawString(140*mm, y_pos, f"{float(offener_betrag):.2f} CHF")

    # Linie über Total
    y_pos -= 3*mm
    c.line(20*mm, y_pos, 160*mm, y_pos)

    # Total
    y_pos -= 5*mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(140*mm, y_pos, f"{float(offener_betrag):.2f} CHF")

    # --- 7. Rechtlicher Text (Art. 257d OR) ---
    y_pos -= 15*mm
    c.setFont("Helvetica", 10)

    # Lange Texte aufteilen, damit sie nicht über den Rand gehen
    text1 = "Gestützt auf Art. 257d OR gewähren wir Ihnen eine letzte Zahlungspflicht von 30 Tagen. Nach unbenütztem"
    text2 = "Ablauf dieser Frist sind wir gezwungen, das Mietverhältnis unter Einhaltung der gesetzlichen Kündigungsfrist"
    text3 = "von 30 Tagen auf Ende des nächsten Monats zu kündigen und unverzüglich die Betreibung einzuleiten."

    text4 = "Wir hoffen, dass Sie sich und uns diese äusserst unangenehmen Massnahmen ersparen und danken Ihnen"
    text5 = "für Ihre Überweisung. Aus rechtlichen Gründen wird dieses Schreiben allen Solidarpartnern separat zugestellt."

    c.drawString(20*mm, y_pos, text1)
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, text2)
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, text3)

    y_pos -= 10*mm
    c.drawString(20*mm, y_pos, text4)
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, text5)

    # --- 8. Grussformel ---
    y_pos -= 15*mm
    c.drawString(20*mm, y_pos, "Freundliche Grüsse")

    y_pos -= 15*mm # Platz für Unterschrift
    # Digitale Unterschrift in den freigehaltenen Platz setzen
    try:
        from core.services.unterschrift import unterschrift_zeichnen
        _lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
        unterschrift_zeichnen(c, 20*mm, y_pos + 2*mm,
                              verwaltung, getattr(_lg, 'eigentuemer', None))
    except Exception:
        logger.debug("Fehler bewusst übergangen", exc_info=True)
    c.setFont("Helvetica-Bold", 11)
    # Hier ziehen wir dynamisch den Namen der Kontaktperson aus der Verwaltung (oder Fallback auf die Firma)
    kontakt = getattr(verwaltung, 'kontaktperson', creditor['name'])
    c.drawString(20*mm, y_pos, kontakt)

    # 🔥 ERSTELLT NEUE SEITE FÜR DEN QR-CODE
    c.showPage()

    # --- 9. QR Code unten anfügen ---
    draw_qr_bill(c, iban, creditor, debtor, float(offener_betrag), reason, reference=ref,
                 sprache=sprache_von(mieter))

    c.save()
    return f"{settings.MEDIA_URL}qr_rechnungen/{filename}"