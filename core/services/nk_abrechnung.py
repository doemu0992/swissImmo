"""Nebenkosten-Abrechnung pro Mieter als PDF (Einzel + Sammel).

Nutzt die kanonische Engine core.utils.billing.berechne_abrechnung — dieselben
Zahlen wie Detailansicht und Verbuchung. Erzeugt je Mieter eine transparente
Abrechnung (Kostenpositionen + Verteilschlüssel + Anteil − Akonto = Saldo).
"""
import io
from decimal import Decimal

from reportlab.pdfgen import canvas as _canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm


def _chf(v):
    try:
        return f"{Decimal(v):,.2f}".replace(',', "'")
    except Exception:
        return "0.00"


_SCHLUESSEL_LABEL = {'m2': 'Fläche (m²)', 'm3': 'Volumen (m³)', 'einheit': 'pro Einheit',
                     'verbrauch': 'Verbrauch', 'heizung': 'Heizung'}


def _draw_page(c, k):
    """Zeichnet eine Mieter-Abrechnung auf die aktuelle Canvas-Seite."""
    w, h = A4
    vw = k.get('verwaltung')
    # Kopf
    c.setFillColorRGB(0.26, 0.22, 0.79)
    c.rect(0, h - 26 * mm, w, 26 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, h - 13 * mm, "Nebenkostenabrechnung")
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 20 * mm, k.get('periode', ''))

    # Absender (Verwaltung)
    c.setFillColorRGB(0.4, 0.45, 0.5)
    c.setFont("Helvetica", 8)
    if vw:
        c.drawRightString(w - 20 * mm, h - 12 * mm, vw.firma or '')
        c.drawRightString(w - 20 * mm, h - 16 * mm, f"{vw.strasse or ''}")
        c.drawRightString(w - 20 * mm, h - 20 * mm, f"{vw.plz or ''} {vw.ort or ''}")

    # Empfänger-Adresse
    c.setFillColorRGB(0.1, 0.1, 0.1)
    y = h - 44 * mm
    c.setFont("Helvetica", 11)
    for line in k.get('adresse', []):
        c.drawString(20 * mm, y, line)
        y -= 5 * mm

    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.4, 0.45, 0.5)
    c.drawString(20 * mm, y, f"Objekt: {k.get('objekt', '')}   ·   Abrechnungsperiode: {k.get('periode', '')}")
    y -= 10 * mm

    # Kostenpositionen der Liegenschaft (Transparenz)
    c.setFillColorRGB(0.4, 0.45, 0.5)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(20 * mm, y, "KOSTENPOSITION")
    c.drawString(120 * mm, y, "VERTEILUNG")
    c.drawRightString(w - 20 * mm, y, "BETRAG (TOTAL)")
    y -= 3 * mm
    c.setStrokeColorRGB(0.85, 0.87, 0.9)
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    for pos in k.get('positionen', []):
        if y < 60 * mm:
            c.showPage(); y = h - 25 * mm
        c.drawString(20 * mm, y, str(pos.get('kategorie') or pos.get('text') or '—')[:52])
        c.setFillColorRGB(0.5, 0.55, 0.6)
        c.drawString(120 * mm, y, _SCHLUESSEL_LABEL.get(pos.get('schluessel'), pos.get('schluessel') or '—'))
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawRightString(w - 20 * mm, y, _chf(pos.get('betrag', 0)))
        y -= 5.5 * mm

    y -= 2 * mm
    c.setStrokeColorRGB(0.85, 0.87, 0.9)
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.4, 0.45, 0.5)
    c.drawString(20 * mm, y, "Total umlagefähige Kosten der Liegenschaft")
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.drawRightString(w - 20 * mm, y, f"CHF {_chf(k.get('total_kosten', 0))}")

    # Ihr Anteil-Block
    y -= 16 * mm
    c.setFillColorRGB(0.95, 0.96, 1.0)
    c.rect(20 * mm, y - 26 * mm, w - 40 * mm, 32 * mm, fill=1, stroke=0)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(24 * mm, y, "Ihre Abrechnung")
    c.setFont("Helvetica", 10)
    y -= 8 * mm
    c.drawString(24 * mm, y, "Ihr Kostenanteil")
    c.drawRightString(w - 24 * mm, y, f"CHF {_chf(k.get('kosten_anteil', 0))}")
    y -= 6 * mm
    c.drawString(24 * mm, y, "− Bezahlte Akontozahlungen")
    c.drawRightString(w - 24 * mm, y, f"CHF {_chf(k.get('akonto', 0))}")
    y -= 3 * mm
    c.setStrokeColorRGB(0.7, 0.75, 0.85)
    c.line(24 * mm, y, w - 24 * mm, y)
    y -= 6 * mm
    saldo = Decimal(str(k.get('saldo', 0)))
    nachzahlung = k.get('nachzahlung', saldo > 0)
    c.setFont("Helvetica-Bold", 11)
    if nachzahlung:
        c.setFillColorRGB(0.8, 0.1, 0.1)
        c.drawString(24 * mm, y, "Nachzahlung zu Ihren Lasten")
        c.drawRightString(w - 24 * mm, y, f"CHF {_chf(abs(saldo))}")
    else:
        c.setFillColorRGB(0.0, 0.5, 0.25)
        c.drawString(24 * mm, y, "Guthaben zu Ihren Gunsten")
        c.drawRightString(w - 24 * mm, y, f"CHF {_chf(abs(saldo))}")

    # Rechtsgrundlagen (VMWG / OR) — konsistent zur klassischen Abrechnung
    from core.services.mietrecht import ref as _mr
    c.setFillColorRGB(0.5, 0.55, 0.6)
    c.setFont("Helvetica", 7.5)
    c.drawString(20 * mm, 22 * mm,
                 f"Umgelegt werden nur die vertraglich vereinbarten Nebenkosten ({_mr('nebenkosten')}, VMWG Art. 4-8) nach dem vereinbarten Verteilschlüssel.")
    c.drawString(20 * mm, 18 * mm,
                 "Einsicht in die Originalbelege ist nach Art. 257b Abs. 2 OR nach Terminvereinbarung jederzeit möglich.")
    if nachzahlung:
        c.drawString(20 * mm, 14 * mm,
                     "Bitte begleichen Sie die Nachzahlung innert 30 Tagen. Beanstandungen sind innert 30 Tagen schriftlich mitzuteilen.")
    else:
        c.drawString(20 * mm, 14 * mm,
                     "Ein allfälliges Guthaben wird Ihnen gutgeschrieben. Beanstandungen sind innert 30 Tagen schriftlich mitzuteilen.")


def generate_nk_pdf_einzeln(kontext):
    """Ein Mieter → einseitige Abrechnung (Bytes)."""
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Nebenkostenabrechnung {kontext.get('periode','')}")
    _draw_page(c, kontext)
    c.showPage()
    c.save()
    return buf.getvalue()


def generate_nk_pdf_sammel(kontext_liste):
    """Mehrere Mieter → ein Sammel-PDF (eine Seite pro Mieter)."""
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Nebenkostenabrechnungen (Sammel)")
    for k in kontext_liste:
        _draw_page(c, k)
        c.showPage()
    c.save()
    return buf.getvalue()
