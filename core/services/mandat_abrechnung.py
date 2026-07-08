"""Eigentümer-/Mandatsabrechnung als PDF.

Stellt je Liegenschaft eines Mandanten Erträge und Aufwände eines Geschäftsjahres
gegenüber und weist den Saldo (Auszahlung an den Eigentümer) aus."""
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


def generate_mandat_abrechnung_pdf(mandant, jahr, zeilen, totals, von, bis, verwaltung=None):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"Mandatsabrechnung {mandant.firma_oder_name} {jahr}")

    if verwaltung and getattr(verwaltung, 'logo', None):
        try:
            c.drawImage(verwaltung.logo.path, 155*mm, 272*mm, width=40*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    # Absender
    if verwaltung:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20*mm, 280*mm, verwaltung.firma or "")
        c.setFont("Helvetica", 9)
        c.drawString(20*mm, 276*mm, verwaltung.strasse or "")
        c.drawString(20*mm, 272*mm, f"{verwaltung.plz or ''} {verwaltung.ort or ''}".strip())

    # Empfänger (Eigentümer)
    c.setFont("Helvetica", 11)
    c.drawString(20*mm, 250*mm, mandant.firma_oder_name)
    if mandant.kontaktperson:
        c.drawString(20*mm, 245*mm, mandant.kontaktperson)
    c.drawString(20*mm, 240*mm, mandant.strasse or "")
    c.drawString(20*mm, 235*mm, f"{mandant.plz or ''} {mandant.ort or ''}".strip())

    # Titel
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20*mm, 218*mm, f"Eigentümerabrechnung {jahr}")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.grey)
    c.drawString(20*mm, 212*mm, f"Abrechnungsperiode: {von.strftime('%d.%m.%Y')} – {bis.strftime('%d.%m.%Y')}")
    c.setFillColor(colors.black)

    # Tabellenkopf
    y = 198*mm
    c.setFillColor(colors.HexColor("#EEF0F5"))
    c.rect(18*mm, y - 2*mm, 174*mm, 8*mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(22*mm, y, "Liegenschaft")
    c.drawRightString(120*mm, y, "Ertrag")
    c.drawRightString(155*mm, y, "Aufwand")
    c.drawRightString(188*mm, y, "Saldo")

    y -= 9*mm
    c.setFont("Helvetica", 9)
    for z in zeilen:
        if y < 60*mm:
            c.showPage()
            y = 270*mm
        lg = z['lg']
        c.drawString(22*mm, y, f"{lg.strasse}, {lg.ort}"[:52])
        c.drawRightString(120*mm, y, _fmt(z['ertrag']))
        c.drawRightString(155*mm, y, _fmt(z['aufwand']))
        c.setFillColor(colors.HexColor("#B91C1C") if z['saldo'] < 0 else colors.black)
        c.drawRightString(188*mm, y, _fmt(z['saldo']))
        c.setFillColor(colors.black)
        y -= 6*mm

    if not zeilen:
        c.setFillColor(colors.grey)
        c.drawString(22*mm, y, "Keine Liegenschaften diesem Mandanten zugeordnet.")
        c.setFillColor(colors.black)
        y -= 6*mm

    # Total
    y -= 2*mm
    c.setLineWidth(0.6)
    c.line(18*mm, y, 192*mm, y)
    y -= 7*mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(22*mm, y, "Total")
    c.drawRightString(120*mm, y, _fmt(totals['ertrag']))
    c.drawRightString(155*mm, y, _fmt(totals['aufwand']))
    c.drawRightString(188*mm, y, _fmt(totals['saldo']))

    # Auszahlungsbox
    y -= 16*mm
    saldo = totals['saldo']
    c.setFillColor(colors.HexColor("#ECFDF5") if saldo >= 0 else colors.HexColor("#FEF2F2"))
    c.rect(18*mm, y - 6*mm, 174*mm, 16*mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    label = "Auszahlung an Eigentümer" if saldo >= 0 else "Nachschuss durch Eigentümer"
    c.drawString(22*mm, y, label)
    c.drawRightString(188*mm, y, f"CHF {_fmt(abs(saldo))}")

    # Fusszeile
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(20*mm, 20*mm, "Diese Abrechnung basiert auf den verbuchten Erträgen und Aufwänden der zugeordneten Liegenschaften.")
    if mandant.iban:
        c.drawString(20*mm, 16*mm, f"Auszahlung auf: {mandant.iban}")
    c.setFillColor(colors.black)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()
