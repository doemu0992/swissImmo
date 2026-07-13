"""PDF-Export der Ersatz- & Budgetplanung: Jahres-Budget (Balken) + Elementliste
nach Restnutzungsdauer. Basis für die Erneuerungsfonds-Planung des Eigentümers."""
import io
from decimal import Decimal


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


STATUS_LABEL = {'faellig': 'fällig', 'bald': 'bald', 'ok': 'ok', 'unbekannt': '—'}


def generate_ersatzplanung_pdf(daten, lg_name, verwaltung=None, deckung=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    indigo = colors.HexColor("#4F46E5")
    rose = colors.HexColor("#E11D48")
    amber = colors.HexColor("#D97706")
    grey = colors.HexColor("#64748B")
    c.setTitle(f"Ersatzplanung {lg_name}")

    # Kopf
    c.setFillColor(indigo)
    c.rect(0, h - 26 * mm, w, 26 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, h - 13 * mm, "Ersatz- & Budgetplanung")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, h - 20 * mm, lg_name)
    if verwaltung:
        c.setFont("Helvetica", 9)
        c.drawRightString(w - 20 * mm, h - 13 * mm, verwaltung.firma or "")
    c.setFillColor(colors.black)

    y = h - 38 * mm

    # Kennzahlen-Zeile
    c.setFont("Helvetica", 9); c.setFillColor(grey)
    c.drawString(20 * mm, y, "Ersatz fällig")
    c.drawString(60 * mm, y, "Bald (≤ 2 J)")
    c.drawString(105 * mm, y, "Im Zeitraum")
    c.drawString(150 * mm, y, "Budget-Horizont")
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 13)
    c.setFillColor(rose); c.drawString(20 * mm, y - 7 * mm, str(daten['n_faellig']))
    c.setFillColor(amber); c.drawString(60 * mm, y - 7 * mm, str(daten['n_bald']))
    c.setFillColor(colors.black); c.drawString(105 * mm, y - 7 * mm, str(daten['n_ok']))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(150 * mm, y - 7 * mm, f"CHF {_fmt(daten['budget_total'])}")
    c.setFillColor(colors.black)
    y -= 18 * mm

    # Erneuerungsfonds-Deckung
    if deckung:
        emerald = colors.HexColor("#059669")
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.roundRect(20 * mm, y - 20 * mm, w - 40 * mm, 22 * mm, 3, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 10); c.setFillColor(colors.black)
        c.drawString(24 * mm, y - 5 * mm, f"Erneuerungsfonds-Deckung ({daten['horizont_jahre']} J)")
        if deckung.get('deckungsgrad') is not None:
            c.setFillColor(emerald if deckung['gedeckt'] else rose)
            c.setFont("Helvetica-Bold", 10)
            c.drawRightString(w - 24 * mm, y - 5 * mm, f"{deckung['deckungsgrad']}% gedeckt")
        c.setFillColor(grey); c.setFont("Helvetica", 8)
        c.drawString(24 * mm, y - 11 * mm, "Bestand")
        c.drawString(70 * mm, y - 11 * mm, "Jährl. Einlage")
        c.drawString(120 * mm, y - 11 * mm, "Empf. Rückstellung")
        c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 9)
        c.drawString(24 * mm, y - 16 * mm, f"CHF {_fmt(deckung['bestand'])}")
        c.drawString(70 * mm, y - 16 * mm, f"CHF {_fmt(deckung['einlage'])}")
        c.setFillColor(rose if deckung['mehrbedarf'] > 0 else emerald)
        c.drawString(120 * mm, y - 16 * mm, f"CHF {_fmt(deckung['empfohlen'])}")
        c.setFillColor(colors.black)
        y -= 26 * mm

    # Jahres-Budget als Balken
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, f"Ersatzbudget je Jahr (nächste {daten['horizont_jahre']} Jahre)")
    y -= 8 * mm
    jb = daten['jahres_budget']
    if not jb:
        c.setFont("Helvetica-Oblique", 9); c.setFillColor(grey)
        c.drawString(20 * mm, y, "Keine datierten Ersatzkosten im Horizont (Neuwert/Einbaudatum fehlen).")
        c.setFillColor(colors.black); y -= 8 * mm
    else:
        maxb = max([b['summe'] for b in jb] + [Decimal('0.01')])
        bar_x, bar_w = 42 * mm, 110 * mm
        for b in jb:
            if y < 30 * mm:
                c.showPage(); y = h - 25 * mm
            c.setFont("Helvetica", 9); c.setFillColor(colors.black)
            c.drawString(20 * mm, y, str(b['jahr']))
            frac = float(b['summe'] / maxb) if maxb else 0
            c.setFillColor(indigo)
            c.rect(bar_x, y - 1 * mm, max(bar_w * frac, 0.4), 3.4 * mm, fill=1, stroke=0)
            c.setFillColor(colors.black); c.setFont("Helvetica", 9)
            c.drawRightString(w - 20 * mm, y, f"CHF {_fmt(b['summe'])}")
            y -= 6.4 * mm

    # Elementliste
    y -= 6 * mm
    if y < 45 * mm:
        c.showPage(); y = h - 25 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Elemente nach Restnutzungsdauer")
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 8); c.setFillColor(grey)
    c.drawString(20 * mm, y, "Element / Objekt")
    c.drawString(120 * mm, y, "Rest")
    c.drawString(138 * mm, y, "Status")
    c.drawRightString(w - 20 * mm, y, "Neuwert")
    c.setFillColor(colors.black); y -= 2 * mm
    c.setStrokeColor(colors.HexColor("#E2E8F0")); c.line(20 * mm, y, w - 20 * mm, y)
    y -= 5 * mm

    for r in daten['rows']:
        if y < 20 * mm:
            c.showPage(); y = h - 25 * mm
        a = r['a']
        c.setFont("Helvetica", 9); c.setFillColor(colors.black)
        c.drawString(20 * mm, y, f"{a.kategorie}"[:44])
        c.setFont("Helvetica", 7); c.setFillColor(grey)
        c.drawString(20 * mm, y - 3.4 * mm, f"{a.raum} · {r['standort']}"[:70])
        c.setFont("Helvetica", 9); c.setFillColor(colors.black)
        c.drawString(120 * mm, y, f"{r['rest']} J" if r['rest'] is not None else "—")
        stc = {'faellig': rose, 'bald': amber}.get(r['status'], colors.black)
        c.setFillColor(stc); c.setFont("Helvetica-Bold", 8)
        c.drawString(138 * mm, y, STATUS_LABEL[r['status']])
        c.setFillColor(colors.black); c.setFont("Helvetica", 9)
        c.drawRightString(w - 20 * mm, y, _fmt(r['neuwert']) if r['neuwert'] else "—")
        y -= 7.5 * mm

    c.setFont("Helvetica-Oblique", 8); c.setFillColor(colors.HexColor("#94A3B8"))
    c.drawString(20 * mm, 12 * mm, "Ersatzjahr = Einbaujahr + Lebensdauer (paritätische Tabelle). Budget = Neuwert im Horizont.")
    c.setFillColor(colors.black)

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
