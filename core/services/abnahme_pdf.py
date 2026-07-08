"""PDF des Wohnungsabnahme-Protokolls (Einzug/Auszug)."""
import io
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


VERURS_LABEL = {'abnutzung': 'normale Abnutzung', 'mieter': 'Mieter (Schaden)', 'vermieter': 'Vermieter'}


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
    c.drawString(20 * mm, y, "Raum"); c.drawString(55 * mm, y, "Mangel")
    c.drawString(140 * mm, y, "Verursacher"); c.drawRightString(190 * mm, y, "CHF")
    c.setFillColor(colors.black)
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    total_mieter = Decimal('0.00')
    maengel = list(prot.maengel.all())
    if not maengel:
        c.setFillColor(colors.grey); c.drawString(20 * mm, y, "Keine Mängel festgestellt."); c.setFillColor(colors.black); y -= 6 * mm
    for m in maengel:
        if y < 40 * mm:
            c.showPage(); y = 280 * mm; c.setFont("Helvetica", 9)
        c.drawString(20 * mm, y, (m.raum or '—')[:22])
        c.drawString(55 * mm, y, (m.beschreibung or '')[:52])
        c.drawString(140 * mm, y, VERURS_LABEL.get(m.verursacher, m.verursacher))
        if m.kostenschaetzung:
            c.drawRightString(190 * mm, y, _fmt(m.kostenschaetzung))
            if m.verursacher == 'mieter':
                total_mieter += m.kostenschaetzung
        y -= 5.5 * mm

    y -= 2 * mm
    c.setStrokeColor(colors.HexColor("#e2e8f0")); c.line(20 * mm, y, 190 * mm, y); y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Kosten zulasten Mieter (Schätzung)")
    c.drawRightString(190 * mm, y, f"CHF {_fmt(total_mieter)}")
    y -= 10 * mm

    if prot.bemerkungen:
        c.setFont("Helvetica-Bold", 9); c.drawString(20 * mm, y, "Bemerkungen:"); y -= 5 * mm
        c.setFont("Helvetica", 9)
        for line in prot.bemerkungen.split('\n'):
            for chunk in [line[i:i+95] for i in range(0, len(line) or 1, 95)]:
                c.drawString(20 * mm, y, chunk); y -= 5 * mm

    # Unterschriften
    y = max(y, 45 * mm)
    c.setStrokeColor(colors.HexColor("#94a3b8"))
    c.line(20 * mm, 35 * mm, 90 * mm, 35 * mm)
    c.line(115 * mm, 35 * mm, 185 * mm, 35 * mm)
    c.setFont("Helvetica", 8); c.setFillColor(colors.grey)
    c.drawString(20 * mm, 31 * mm, f"Mieter{'  ' + prot.unterschrift_mieter if prot.unterschrift_mieter else ''}")
    c.drawString(115 * mm, 31 * mm, f"Verwaltung{'  ' + prot.unterschrift_verwalter if prot.unterschrift_verwalter else ''}")

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
