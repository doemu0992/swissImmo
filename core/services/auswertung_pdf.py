"""PDF-Export der interaktiven Auswertung: gewählte Kennzahl im Monatsverlauf
und je Liegenschaft, mit einfachen Balken (ohne externe Chart-Library)."""
import io
from decimal import Decimal
from core.services.dokumentsprache import nur_deutsch
from core.services.druckfarben import EMBER


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


@nur_deutsch
def generate_auswertung_pdf(typ_label, jahr, lg_name, total, monate, lg_rows, verwaltung=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    from core.services.dok_layout import DokCanvas

    buf = io.BytesIO()
    c = DokCanvas(buf, organisation=verwaltung, absender=['Verwaltung', '', ''],
                  titel=f"Auswertung: {typ_label}", ref=f"Geschäftsjahr {jahr} · {lg_name}")
    w, h = A4
    ember = colors.HexColor(EMBER)
    rose = colors.HexColor("#E11D48")
    c.setTitle(f"Auswertung {typ_label} {jahr}")

    # Titel unter dem Briefkopf (früher ein Farbband)
    c.setFillColor(c.akzent)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, c.Y_INHALT, f"Auswertung: {typ_label}")
    c.setFillColor(colors.HexColor("#374151"))
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, c.Y_INHALT - 6 * mm, f"Geschäftsjahr {jahr} · {lg_name}")
    c.setFillColor(colors.black)

    # Total
    y = c.Y_INHALT - 18 * mm
    c.setFont("Helvetica", 10); c.setFillColor(colors.HexColor("#374151"))
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
            if y0 < 30 * mm:
                c.showPage(); y0 = c.Y_FOLGE
            wert = Decimal(str(z['wert']))
            c.setFont("Helvetica", 9); c.setFillColor(colors.black)
            c.drawString(20 * mm, y0, label_fn(z)[:28])
            # Balken
            frac = float(abs(wert) / maxabs) if maxabs else 0
            c.setFillColor(rose if wert < 0 else ember)
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
            c.showPage(); y = c.Y_FOLGE
        lz = [{'wert': r['wert'], 'name': f"{r['lg'].strasse}, {r['lg'].ort}"} for r in lg_rows]
        y = balken_tabelle("Je Liegenschaft", lz, lambda z: z['name'], y)

    y -= 4 * mm
    if y < 30 * mm:
        c.showPage(); y = c.Y_FOLGE
    c.setFont("Helvetica-Oblique", 8); c.setFillColor(colors.HexColor("#4b5563"))
    c.drawString(20 * mm, y, "Aus den verbuchten Bewegungen des Hauptbuchs (Stornos ausgeschlossen).")
    c.setFillColor(colors.black)

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
