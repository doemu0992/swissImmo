"""PDF des Wohnungsabnahme-Protokolls (Einzug/Auszug)."""
import io
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from core.services.abnahme_texte import schlussbestimmungen
from core.services.dokumentsprache import nur_deutsch


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


ZUSTAND_LABEL = {'': 'offen', 'io': 'Neu i.O.', 'normal': 'Normal', 'uebermaessig': 'Übermässig'}
def _kuerzen(text, groesse, breite):
    """Kürzt einen Text auf die Spaltenbreite (Helvetica), mit «…»."""
    text = str(text or '')
    if stringWidth(text, 'Helvetica', groesse) <= breite:
        return text
    while text and stringWidth(text + '…', 'Helvetica', groesse) > breite:
        text = text[:-1]
    return text.rstrip() + '…'


def _bildleser(feld):
    """Ein hochgeladenes Bild für reportlab; None, wenn keines da oder nicht lesbar
    (eine fehlende Datei darf das PDF nicht verhindern)."""
    if not feld:
        return None
    try:
        with feld.open('rb') as f:
            return ImageReader(io.BytesIO(f.read()))
    except Exception:
        return None


VERURS_LABEL = {'abnutzung': 'normale Abnutzung', 'mieter': 'Mieter (Schaden)', 'vermieter': 'Vermieter'}


@nur_deutsch
def generate_abnahme_pdf(prot, verwaltung=None):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    v = prot.vertrag
    e = v.einheit
    lg = e.liegenschaft
    c.setTitle(f"Abnahmeprotokoll {v.mieter.nachname}")

    y = 280 * mm
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, y, f"Wohnungsabnahme — {prot.get_typ_display()}")
    y -= 7 * mm
    c.setFont("Helvetica", 10); c.setFillColor(colors.grey)
    c.drawString(20 * mm, y, f"{e.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}")
    y -= 5 * mm
    c.drawString(20 * mm, y, f"Mieter: {v.mieter.vorname} {v.mieter.nachname} · Datum: {prot.datum.strftime('%d.%m.%Y')}")
    c.setFillColor(colors.black)
    y -= 10 * mm

    def zeile(label, wert):
        nonlocal y
        if not wert:
            return
        c.setFont("Helvetica-Bold", 9); c.drawString(20 * mm, y, f"{label}:")
        c.setFont("Helvetica", 9); c.drawString(62 * mm, y, str(wert))
        y -= 5.5 * mm

    zeile("Abnahme durch", prot.verwalter_name)
    zeile("Mieter anwesend", "Ja" if prot.mieter_anwesend else "Nein")
    zeile("Allgemeinzustand", prot.get_allgemein_zustand_display())
    zeile("Schlüssel zurück", prot.schluessel_anzahl)
    zeile("Zähler Strom", prot.zaehler_strom)
    zeile("Zähler Wasser", prot.zaehler_wasser)
    zeile("Zähler Gas/Wärme", prot.zaehler_gas)
    zeile("Neue Adresse", prot.neue_adresse)

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11); c.drawString(20 * mm, y, "Festgestellte Mängel")
    y -= 2 * mm
    c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 8); c.setFillColor(colors.grey)
    c.drawString(20 * mm, y, "Raum"); c.drawString(50 * mm, y, "Mangel")
    c.drawString(118 * mm, y, "Verursacher")
    c.drawRightString(168 * mm, y, "Kosten"); c.drawRightString(190 * mm, y, "Anteil")
    c.setFillColor(colors.black)
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    maengel = list(prot.maengel.all())
    if not maengel:
        c.setFillColor(colors.grey); c.drawString(20 * mm, y, "Keine Mängel festgestellt."); c.setFillColor(colors.black); y -= 6 * mm
    for m in maengel:
        if y < 40 * mm:
            c.showPage(); y = 280 * mm; c.setFont("Helvetica", 9)
        c.drawString(20 * mm, y, (m.raum or '—')[:18])
        c.drawString(50 * mm, y, (m.beschreibung or '')[:44])
        c.drawString(118 * mm, y, VERURS_LABEL.get(m.verursacher, m.verursacher))
        basis = m.kostenschaetzung if m.kostenschaetzung is not None else m.neuwert
        if basis is not None:
            c.drawRightString(168 * mm, y, _fmt(basis))
        if m.verursacher == 'mieter':
            anteil = m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung
            if anteil is not None:
                c.drawRightString(190 * mm, y, _fmt(anteil))
        y -= 5.5 * mm

    y -= 2 * mm
    c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y); y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Kosten zulasten Mieter (Zeitwert)")
    c.drawRightString(190 * mm, y, f"CHF {_fmt(prot.kosten_mieter_total)}")
    y -= 6 * mm
    c.setFont("Helvetica", 7); c.setFillColor(colors.grey)
    c.drawString(20 * mm, y, "Anteil = Zeitwert nach paritätischer Lebensdauertabelle (Abzug 'neu für alt') bei verknüpftem Raumbuch-Element.")
    c.setFillColor(colors.black)
    y -= 8 * mm

    # Bewertete Bauteile (Abnahme vor Ort): alle Bauteile mit Zustand, bei
    # aufbauenden Protokollen zusätzlich der Vorzustand aus dem Vorgänger.
    # Die Nummer läuft durch Bauteile und Schlüssel (wie im Praxisprotokoll)
    # und verbindet die Tabelle mit den Bildern am Ende.
    positionen = list(prot.positionen.select_related('vorgaenger_position__protokoll'))
    nummern = {pos.id: i for i, pos in enumerate(positionen, start=1)}
    if positionen:
        vorg = prot.vorgaenger
        if y < 60 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 11); c.drawString(20 * mm, y, "Bewertete Bauteile")
        y -= 2 * mm
        c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
        y -= 5 * mm
        if vorg is not None:
            c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
            c.drawString(20 * mm, y, f"Baut auf: {vorg.get_typ_display()} vom {vorg.datum.strftime('%d.%m.%Y')} "
                                     f"({vorg.vertrag.mieter.nachname})")
            c.setFillColor(colors.black)
            y -= 6 * mm

        # Spalten (mm): Nr 20, Raum 28, Bauteil 45, Vorzustand 87, Zustand 110, Kommentar 134–190
        bauteil_breite = (40 if vorg is not None else 62) * mm

        def kopfzeile():
            nonlocal y
            c.setFont("Helvetica-Bold", 8); c.setFillColor(colors.grey)
            c.drawString(20 * mm, y, "Nr"); c.drawString(28 * mm, y, "Raum"); c.drawString(45 * mm, y, "Bauteil")
            if vorg is not None:
                c.drawString(87 * mm, y, "Vorzustand")
            c.drawString(110 * mm, y, "Zustand"); c.drawString(134 * mm, y, "Kommentar")
            c.setFillColor(colors.black)
            y -= 5 * mm
        kopfzeile()
        for pos in positionen:
            bemerkung = pos.kommentar or ''
            if pos.vorbestand_entscheid == 'vorbestehend':
                bemerkung = ('[vorbestehend] ' + bemerkung).strip()
            elif pos.vorbestand_entscheid == 'mieter':
                bemerkung = ('[dem Mieter belastet] ' + bemerkung).strip()
            # Langer Kommentar: bis zu drei Zeilen, der Rest wird abgeschnitten.
            zeilen = (simpleSplit(bemerkung, "Helvetica", 8, 56 * mm)[:3]) or ['']
            hoehe = 4.2 * mm * len(zeilen) + 0.8 * mm
            if y - hoehe < 40 * mm:
                c.showPage(); y = 280 * mm; kopfzeile()
            c.setFont("Helvetica", 8)
            c.drawString(20 * mm, y, str(nummern[pos.id]))
            c.drawString(28 * mm, y, _kuerzen(pos.raum or '—', 8, 16 * mm))
            c.drawString(45 * mm, y, _kuerzen(pos.bezeichnung or '', 8, bauteil_breite))
            if vorg is not None:
                vp = pos.vorgaenger_position
                c.drawString(87 * mm, y, ZUSTAND_LABEL.get(vp.zustand, '—') if vp else '—')
            c.drawString(110 * mm, y, ZUSTAND_LABEL.get(pos.zustand, 'offen'))
            for i, zeile_text in enumerate(zeilen):
                c.drawString(134 * mm, y - i * 4.2 * mm, zeile_text)
            y -= hoehe
        y -= 4 * mm

    # Schlüsselverzeichnis: Soll gegen Ist, Nummern setzen die der Bauteile fort.
    schluessel = list(prot.schluessel.all())
    if schluessel:
        if y < 60 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 11); c.drawString(20 * mm, y, "Schlüsselverzeichnis")
        y -= 2 * mm
        c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
        y -= 5 * mm
        c.setFont("Helvetica-Bold", 8); c.setFillColor(colors.grey)
        c.drawString(20 * mm, y, "Nr"); c.drawString(28 * mm, y, "Schlüssel"); c.drawString(75 * mm, y, "Schliessanlage / Schlüsselnummer")
        c.drawRightString(160 * mm, y, "Soll"); c.drawRightString(172 * mm, y, "Ist"); c.drawRightString(190 * mm, y, "Fehlend")
        c.setFillColor(colors.black)
        y -= 5 * mm
        c.setFont("Helvetica", 8)
        for i, z in enumerate(schluessel, start=len(positionen) + 1):
            if y < 40 * mm:
                c.showPage(); y = 280 * mm; c.setFont("Helvetica", 8)
            c.drawString(20 * mm, y, str(i))
            c.drawString(28 * mm, y, _kuerzen(z.bezeichnung, 8, 44 * mm))
            c.drawString(75 * mm, y, _kuerzen(z.anlage or '—', 8, 62 * mm))
            c.drawRightString(160 * mm, y, str(z.soll))
            c.drawRightString(172 * mm, y, '—' if z.ist is None else str(z.ist))
            c.drawRightString(190 * mm, y, '—' if z.fehlend is None else str(z.fehlend))
            y -= 5 * mm
        y -= 4 * mm

    if prot.bemerkungen:
        # Reicht der Platz nicht, geht es auf einer neuen Seite weiter.
        if y < 60 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 9); c.drawString(20 * mm, y, "Bemerkungen:"); y -= 5 * mm
        c.setFont("Helvetica", 9)
        for line in prot.bemerkungen.split('\n'):
            for chunk in [line[i:i+95] for i in range(0, len(line) or 1, 95)]:
                if y < 45 * mm:
                    c.showPage(); y = 280 * mm; c.setFont("Helvetica", 9)
                c.drawString(20 * mm, y, chunk); y -= 5 * mm
        y -= 3 * mm

    # Schlussbestimmungen (Standardtext der Verwaltung, siehe abnahme_texte)
    absaetze = schlussbestimmungen(prot)
    if absaetze:
        if y < 70 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 11); c.drawString(20 * mm, y, "Schlussbestimmungen")
        y -= 2 * mm
        c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
        y -= 6 * mm
        for titel, text in absaetze:
            zeilen = simpleSplit(text, "Helvetica", 8.5, 170 * mm)
            if y - (len(zeilen) + 1) * 4.2 * mm < 25 * mm:
                c.showPage(); y = 280 * mm
            c.setFont("Helvetica-Bold", 9); c.drawString(20 * mm, y, titel); y -= 5 * mm
            c.setFont("Helvetica", 8.5)
            for zeile_text in zeilen:
                c.drawString(20 * mm, y, zeile_text); y -= 4.2 * mm
            y -= 3 * mm

    # Unterschriften: im Fluss hinter dem Inhalt, mit der gezeichneten Unterschrift über der Linie.
    if y < 75 * mm:
        c.showPage(); y = 280 * mm
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Unterschriften")
    y -= 3 * mm
    for x, bild, name, rolle in ((20 * mm, prot.unterschrift_mieter_bild, prot.unterschrift_mieter, 'Mieter'),
                                 (115 * mm, prot.unterschrift_verwalter_bild, prot.unterschrift_verwalter, 'Verwaltung')):
        leser = _bildleser(bild)
        if leser is not None:
            c.drawImage(leser, x, y - 26 * mm, width=70 * mm, height=25 * mm, preserveAspectRatio=True, anchor='sw')
        c.setStrokeColor(colors.HexColor("#94a3b8"))
        c.line(x, y - 28 * mm, x + 70 * mm, y - 28 * mm)
        c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
        c.drawString(x, y - 32 * mm, f"{rolle}{'  ' + name if name else ''}")
        c.setFillColor(colors.black)
    y -= 36 * mm

    # Bilder: alle Fotos der Bauteile, nach Raum gruppiert, mit der Nummer der Tabelle
    mit_foto = [pos for pos in positionen if pos.foto]
    if mit_foto:
        c.showPage()
        y = 280 * mm
        c.setFont("Helvetica-Bold", 13); c.drawString(20 * mm, y, "Bilder")
        y -= 3 * mm
        c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y)
        y -= 8 * mm
        raum, spalte = None, 0
        zellen_hoehe, zellen_breite = 68 * mm, 82 * mm
        for pos in mit_foto:
            leser = _bildleser(pos.foto)
            if leser is None:
                continue
            if pos.raum != raum:
                # Neuer Raum: neue Zeile mit Raumüberschrift
                if spalte == 1:
                    y -= zellen_hoehe
                    spalte = 0
                if y - 14 * mm - zellen_hoehe < 15 * mm:
                    c.showPage(); y = 280 * mm
                raum = pos.raum
                c.setFont("Helvetica-Bold", 10); c.drawString(20 * mm, y, raum or '—')
                y -= 7 * mm
            if spalte == 0 and y - zellen_hoehe < 15 * mm:
                c.showPage(); y = 280 * mm
            x = 20 * mm + spalte * 88 * mm
            c.setFont("Helvetica", 8)
            c.drawString(x, y, _kuerzen(f"{nummern[pos.id]} {pos.bezeichnung}", 8, zellen_breite))
            c.drawImage(leser, x, y - 4 * mm - 56 * mm, width=zellen_breite, height=56 * mm,
                        preserveAspectRatio=True, anchor='nw')
            if spalte == 1:
                y -= zellen_hoehe
            spalte = 1 - spalte

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
