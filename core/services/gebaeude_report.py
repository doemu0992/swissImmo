"""Gebäudescharfe Berichte als PDF: Betriebsrechnung (Ertrag − Aufwand) je
Liegenschaft und Kalenderjahr."""
from decimal import Decimal
from io import BytesIO
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def _chf(x):
    return f"{(x or Decimal('0')):,.2f}".replace(',', "'")


def betriebsrechnung_pdf(lg, jahr=None, verwaltung=None):
    """Betriebsrechnung eines Kalenderjahres als PDF (A4)."""
    from core.services.rendite import betriebsrechnung, liegenschaft_rendite
    daten = betriebsrechnung(lg, jahr)
    jahr = daten['jahr']
    rendite = liegenschaft_rendite(lg)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 24 * mm

    absender = (verwaltung.firma if verwaltung else '') or 'Liegenschaftsverwaltung'
    c.setFont("Helvetica-Bold", 8)
    c.drawString(20 * mm, h - 15 * mm, absender)

    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, y, f"Betriebsrechnung {jahr}")
    y -= 7 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, f"{lg.strasse}, {lg.plz} {lg.ort}")
    y -= 10 * mm

    def zeile(label, betrag, bold=False, indent=0):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        c.drawString((22 + indent) * mm, y, label[:70])
        c.drawRightString(190 * mm, y, f"CHF {_chf(betrag)}")
        y -= 5.5 * mm

    def linie():
        nonlocal y
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(20 * mm, y + 1.5 * mm, 190 * mm, y + 1.5 * mm)
        y -= 2 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Ertrag")
    y -= 6 * mm
    if daten['ertrag']:
        for r in daten['ertrag']:
            zeile(f"{r['nummer']} {r['name']}", r['betrag'], indent=2)
    else:
        c.setFont("Helvetica-Oblique", 9); c.drawString(24 * mm, y, "keine Ertragsbuchungen"); y -= 5.5 * mm
    linie()
    zeile("Total Ertrag", daten['ertrag_total'], bold=True)
    y -= 4 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Aufwand")
    y -= 6 * mm
    if daten['aufwand']:
        for r in daten['aufwand']:
            zeile(f"{r['nummer']} {r['name']}", r['betrag'], indent=2)
    else:
        c.setFont("Helvetica-Oblique", 9); c.drawString(24 * mm, y, "keine Aufwandbuchungen"); y -= 5.5 * mm
    linie()
    zeile("Total Aufwand", daten['aufwand_total'], bold=True)
    y -= 6 * mm

    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.line(20 * mm, y + 2 * mm, 190 * mm, y + 2 * mm)
    y -= 1 * mm
    c.setFont("Helvetica-Bold", 11)
    ergebnis = daten['ergebnis']
    c.drawString(22 * mm, y, "Nettoergebnis (Ertrag − Aufwand)")
    c.drawRightString(190 * mm, y, f"CHF {_chf(ergebnis)}")
    y -= 10 * mm

    # Rendite-Fussnote (nur wenn Wert hinterlegt)
    if rendite['bruttorendite'] is not None:
        c.setFont("Helvetica", 8)
        quelle = {'verkehrswert': 'Verkehrswert', 'anlagekosten': 'Anlagekosten'}.get(rendite['wert_quelle'], 'Wert')
        c.drawString(20 * mm, y, f"Bruttorendite (Soll-Nettomietzins / {quelle}): "
                                 f"{rendite['bruttorendite']:.2f} %  ·  "
                                 f"Nettorendite (nach Aufwand 12 Mt.): {rendite['nettorendite']:.2f} %")
        y -= 5 * mm

    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20 * mm, 12 * mm,
                 "Grundlage: verbuchte Erträge/Aufwände dieser Liegenschaft im Kalenderjahr. "
                 "Nicht zugeordnete Buchungen sind nicht enthalten.")
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
