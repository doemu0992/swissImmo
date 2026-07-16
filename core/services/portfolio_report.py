"""Portfolio-Report (PDF) für das Eigentümer-Portal: Kennzahlen + Objektliste."""
import io
import datetime

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


def _chf(v):
    try:
        return f"{float(v):,.0f}".replace(',', "'")
    except Exception:
        return '0'


def generate_portfolio_report(mandant, daten):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    heute = datetime.date.today().strftime('%d.%m.%Y')

    def kopf(titel):
        c.setFillColorRGB(0.12, 0.23, 0.54)
        c.rect(0, h - 30 * mm, w, 30 * mm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(20 * mm, h - 18 * mm, titel)
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, h - 24 * mm, f"{mandant.firma_oder_name} · Stand {heute}")
        c.setFillColorRGB(0, 0, 0)

    kopf("Portfolio-Report")
    y = h - 42 * mm

    # KPI-Block
    kpis = [
        ("Liegenschaften", str(len(daten['liegenschaften']))),
        ("Einheiten", str(daten['total_einheiten'])),
        ("Vermietet", f"{daten['total_vermietet']}/{daten['total_einheiten']}"),
        ("Leerstand", f"{daten['leerquote']:.1f}%"),
        ("Ist-Miete/Mt.", f"CHF {_chf(daten['total_soll'])}"),
        ("Jahres-Ist", f"CHF {_chf(daten['jahres_soll'])}"),
    ]
    if daten.get('bruttorendite') is not None:
        kpis.append(("Bruttorendite*", f"{daten['bruttorendite']:.2f}%"))
    col_w = (w - 40 * mm) / 3
    for i, (label, wert) in enumerate(kpis):
        cx = 20 * mm + (i % 3) * col_w
        cy = y - (i // 3) * 20 * mm
        c.setStrokeColorRGB(0.85, 0.87, 0.9)
        c.roundRect(cx, cy - 15 * mm, col_w - 4 * mm, 15 * mm, 3, stroke=1, fill=0)
        c.setFont("Helvetica", 7.5); c.setFillColorRGB(0.4, 0.45, 0.5)
        c.drawString(cx + 4 * mm, cy - 5 * mm, label.upper())
        c.setFont("Helvetica-Bold", 12); c.setFillColorRGB(0.1, 0.12, 0.15)
        c.drawString(cx + 4 * mm, cy - 12 * mm, wert)
    rows_kpi = (len(kpis) + 2) // 3
    y = y - rows_kpi * 20 * mm - 6 * mm

    # Objektliste je Liegenschaft
    c.setFillColorRGB(0, 0, 0)
    for lg in daten['liegenschaften']:
        if y < 45 * mm:
            c.showPage(); kopf("Portfolio-Report (Forts.)"); y = h - 42 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, lg['adresse'])
        c.setFont("Helvetica", 9); c.setFillColorRGB(0.3, 0.5, 0.3)
        rendite = f" · Rendite {lg['rendite']:.2f}%" if lg.get('rendite') is not None else ""
        c.drawRightString(w - 20 * mm, y, f"CHF {_chf(lg['soll_monat'])}/Mt.{rendite}")
        c.setFillColorRGB(0, 0, 0)
        y -= 6 * mm
        c.setFont("Helvetica", 8.5)
        for e in lg['einheiten']:
            if y < 25 * mm:
                c.showPage(); kopf("Portfolio-Report (Forts.)"); y = h - 42 * mm
                c.setFont("Helvetica", 8.5)
            mieter = e['mieter'] or 'LEERSTAND'
            zeile = f"  {e['bezeichnung']} · {e['typ']}"
            c.drawString(22 * mm, y, zeile[:60])
            c.drawString(105 * mm, y, mieter[:32])
            if e['brutto']:
                c.drawRightString(w - 20 * mm, y, f"CHF {_chf(e['brutto'])}")
            else:
                c.setFillColorRGB(0.8, 0.15, 0.15)
                c.drawRightString(w - 20 * mm, y, "leer")
                c.setFillColorRGB(0, 0, 0)
            y -= 5 * mm
        y -= 4 * mm

    # Fussnote
    if daten.get('bruttorendite') is not None:
        c.setFont("Helvetica-Oblique", 7); c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(20 * mm, 15 * mm,
                     "* Bruttorendite = aktueller Jahres-Mietertrag (Ist, ohne Leerstand) / Gebäudeversicherungswert (Näherung, ersetzt keine Verkehrswertschätzung).")

    c.save(); buf.seek(0)
    return buf.read()
