"""PDF-Export der interaktiven Auswertung: gewählte Kennzahl im Monatsverlauf
und je Liegenschaft, mit einfachen Balken (ohne externe Chart-Library)."""
import io
from decimal import Decimal


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


def generate_auswertung_pdf(typ_label, jahr, lg_name, total, monate, lg_rows, verwaltung=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    indigo = colors.HexColor("#4F46E5")
    rose = colors.HexColor("#E11D48")
    c.setTitle(f"Auswertung {typ_label} {jahr}")

    # Kopf
    c.setFillColor(indigo)
    c.rect(0, h - 26 * mm, w, 26 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, h - 13 * mm, f"Auswertung: {typ_label}")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, h - 20 * mm, f"Geschäftsjahr {jahr} · {lg_name}")
    if verwaltung:
        c.setFont("Helvetica", 9)
        c.drawRightString(w - 20 * mm, h - 13 * mm, verwaltung.firma or "")
    c.setFillColor(colors.black)

    # Total
    y = h - 40 * mm
    c.setFont("Helvetica", 10); c.setFillColor(colors.HexColor("#64748B"))
    c.drawString(20 * mm, y, "Jahres-Total")
    c.setFillColor(rose if (total or 0) < 0 else colors.black)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y - 8 * mm, f"CHF {_fmt(total)}")
    c.setFillColor(colors.black)

    def balken_tabelle(titel, zeilen, label_fn, y0):
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y0, titel)
        y0 -= 8 * mm
        maxabs = max([abs(Decimal(str(z['wert']))) for z in zeilen] + [Decimal('0.01')])
        bar_x = 62 * mm
        bar_w = 95 * mm
        for z in zeilen:
            if y0 < 22 * mm:
                c.showPage(); y0 = h - 25 * mm
            wert = Decimal(str(z['wert']))
            c.setFont("Helvetica", 9); c.setFillColor(colors.black)
            c.drawString(20 * mm, y0, label_fn(z)[:28])
            # Balken
            frac = float(abs(wert) / maxabs) if maxabs else 0
            c.setFillColor(rose if wert < 0 else indigo)
            c.rect(bar_x, y0 - 1 * mm, max(bar_w * frac, 0.4), 3.2 * mm, fill=1, stroke=0)
            c.setFillColor(rose if wert < 0 else colors.black)
            c.setFont("Helvetica", 9)
            c.drawRightString(w - 20 * mm, y0, f"CHF {_fmt(wert)}")
            c.setFillColor(colors.black)
            y0 -= 6.2 * mm
        return y0

    monatsnamen = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
    mzeilen = [{'wert': m['wert'], 'name': monatsnamen[m['m'] - 1]} for m in monate]
    y = balken_tabelle("Monatsverlauf", mzeilen, lambda z: z['name'], y - 22 * mm)

    if lg_rows:
        y -= 8 * mm
        if y < 60 * mm:
            c.showPage(); y = h - 25 * mm
        lz = [{'wert': r['wert'], 'name': f"{r['lg'].strasse}, {r['lg'].ort}"} for r in lg_rows]
        y = balken_tabelle("Je Liegenschaft", lz, lambda z: z['name'], y)

    c.setFont("Helvetica-Oblique", 8); c.setFillColor(colors.HexColor("#94A3B8"))
    c.drawString(20 * mm, 12 * mm, "Aus den verbuchten Bewegungen des Hauptbuchs (Stornos ausgeschlossen).")
    c.setFillColor(colors.black)

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
