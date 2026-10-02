"""PDF des Wohnungsabnahme-Protokolls (Einzug/Auszug)."""
import io
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import simpleSplit
from core.services.dokumentsprache import nur_deutsch


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


ZUSTAND_LABEL = {'': 'offen', 'io': 'Neu i.O.', 'normal': 'Normal', 'uebermaessig': 'Übermässig'}
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
    positionen = list(prot.positionen.select_related('vorgaenger_position__protokoll'))
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

        # Spalten (mm): Raum 20, Bauteil 40, Vorzustand 80, Zustand 104, Kommentar 128–190
        def kopfzeile():
            nonlocal y
            c.setFont("Helvetica-Bold", 8); c.setFillColor(colors.grey)
            c.drawString(20 * mm, y, "Raum"); c.drawString(40 * mm, y, "Bauteil")
            if vorg is not None:
                c.drawString(80 * mm, y, "Vorzustand")
            c.drawString(104 * mm, y, "Zustand"); c.drawString(128 * mm, y, "Kommentar")
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
            zeilen = (simpleSplit(bemerkung, "Helvetica", 8, 62 * mm)[:3]) or ['']
            hoehe = 4.2 * mm * len(zeilen) + 0.8 * mm
            if y - hoehe < 40 * mm:
                c.showPage(); y = 280 * mm; kopfzeile()
            c.setFont("Helvetica", 8)
            c.drawString(20 * mm, y, (pos.raum or '—')[:14])
            c.drawString(40 * mm, y, (pos.bezeichnung or '')[:26])
            if vorg is not None:
                vp = pos.vorgaenger_position
                c.drawString(80 * mm, y, ZUSTAND_LABEL.get(vp.zustand, '—') if vp else '—')
            c.drawString(104 * mm, y, ZUSTAND_LABEL.get(pos.zustand, 'offen'))
            for i, zeile_text in enumerate(zeilen):
                c.drawString(128 * mm, y - i * 4.2 * mm, zeile_text)
            y -= hoehe
        y -= 4 * mm

    if prot.bemerkungen:
        # Der Platz über der Unterschriftszeile (bei 35 mm) bleibt frei: Reicht er
        # nicht, geht es auf einer neuen Seite weiter.
        if y < 60 * mm:
            c.showPage(); y = 280 * mm
        c.setFont("Helvetica-Bold", 9); c.drawString(20 * mm, y, "Bemerkungen:"); y -= 5 * mm
        c.setFont("Helvetica", 9)
        for line in prot.bemerkungen.split('\n'):
            for chunk in [line[i:i+95] for i in range(0, len(line) or 1, 95)]:
                if y < 45 * mm:
                    c.showPage(); y = 280 * mm; c.setFont("Helvetica", 9)
                c.drawString(20 * mm, y, chunk); y -= 5 * mm

    # Unterschriften: stehen fest bei 35 mm. Tabellenzeilen enden über 40 mm, und
    # Bemerkungen brechen selbst um (siehe oben) — das Band darunter bleibt frei.
    y = max(y, 45 * mm)
    c.setStrokeColor(colors.HexColor("#94a3b8"))
    c.line(20 * mm, 35 * mm, 90 * mm, 35 * mm)
    c.line(115 * mm, 35 * mm, 185 * mm, 35 * mm)
    c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
    c.drawString(20 * mm, 31 * mm, f"Mieter{'  ' + prot.unterschrift_mieter if prot.unterschrift_mieter else ''}")
    c.drawString(115 * mm, 31 * mm, f"Verwaltung{'  ' + prot.unterschrift_verwalter if prot.unterschrift_verwalter else ''}")

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
