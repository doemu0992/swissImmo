"""Exposé / Inserat für ein ausgeschriebenes Mietobjekt — ein sauberes PDF
mit Eckdaten, Mietzins, Verfügbarkeit, Beschreibung und Kontakt der Verwaltung.
Das Dokument für Portale/Interessenten in der Nachmietersuche."""
import logging
import io
from decimal import Decimal

logger = logging.getLogger(__name__)



def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


def objekt_titel(einheit):
    """Aussagekräftiger Inserat-Titel, z. B. '3.5-Zimmer-Wohnung' oder 'Parkplatz'."""
    typ = einheit.get_typ_display()
    z = einheit.zimmer
    if z and einheit.typ in ('whg', 'stwe'):
        zt = (str(int(z)) if z == z.to_integral_value() else str(z))
        return f"{zt}-Zimmer-Wohnung"
    return typ


def generate_expose_pdf(einheit, verwaltung=None, bewerbung_url=None):
    """Das Exposé ist (noch) nur deutsch formuliert. Fest deutsch erzeugt,
    damit der übersetzbare Objekttyp nicht in der Sprache der Sachbearbeitung
    mitten im deutschen Text steht (siehe core.services.dokumentsprache).

    `bewerbung_url`: absolute Adresse des öffentlichen Bewerbungsformulars.
    Ist sie gesetzt, trägt die Kontaktbox einen QR-Code darauf — so führt ein
    ausgedrucktes oder weitergeleitetes Exposé direkt zur Bewerbung."""
    from core.services.dokumentsprache import STANDARD, in_sprache
    with in_sprache(STANDARD):
        return _expose_pdf(einheit, verwaltung, bewerbung_url)


def _expose_pdf(einheit, verwaltung, bewerbung_url=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    from core.services.dok_layout import DokCanvas

    lg = einheit.liegenschaft
    buf = io.BytesIO()
    c = DokCanvas(buf, organisation=verwaltung,
                  absender=['Verwaltung', lg.strasse if lg else '', f"{lg.plz} {lg.ort}" if lg else ''],
                  titel=f"Exposé {objekt_titel(einheit)}", ref=f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else einheit.bezeichnung)
    w, h = A4
    c.setTitle(f"Exposé {objekt_titel(einheit)} — {lg.strasse if lg else einheit.bezeichnung}")

    # Titelblock unter dem Briefkopf (früher ein Farbband über die ganze Seitenbreite)
    y0 = c.Y_INHALT
    c.setFillColor(c.akzent)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20 * mm, y0 - 6 * mm, objekt_titel(einheit))
    c.setFillColor(colors.HexColor("#374151"))
    c.setFont("Helvetica", 12)
    if lg:
        c.drawString(20 * mm, y0 - 13 * mm, f"{lg.strasse}, {lg.plz} {lg.ort}")
    brutto = (einheit.nettomiete_aktuell or Decimal('0')) + (einheit.nebenkosten_aktuell or Decimal('0'))
    c.setFillColor(c.akzent)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(w - 20 * mm, y0 - 6 * mm, f"CHF {_fmt(brutto)}/Mt.")
    c.setFillColor(colors.HexColor("#374151"))
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 20 * mm, y0 - 12 * mm, "inkl. Nebenkosten")
    c.setFillColor(colors.black)

    # Titelbild (erstes Objekt-Foto), falls vorhanden
    y = y0 - 24 * mm
    titelbild = einheit.fotos.first()
    if titelbild:
        try:
            from reportlab.lib.utils import ImageReader
            img = ImageReader(titelbild.bild.path)
            iw, ih = img.getSize()
            bw = w - 40 * mm
            bh = bw * ih / iw
            bh = min(bh, 70 * mm)
            bw2 = bh * iw / ih
            c.drawImage(img, 20 * mm, y - bh, width=bw2, height=bh,
                        preserveAspectRatio=True, mask='auto')
            y -= bh + 6 * mm
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)

    # Eckdaten-Kacheln
    verf = einheit.verfuegbar_ab.strftime('%d.%m.%Y') if einheit.verfuegbar_ab else "sofort"
    fakten = [
        ("Zimmer", (str(einheit.zimmer) if einheit.zimmer else "—")),
        ("Fläche", (f"{_fmt(einheit.flaeche_m2)} m²" if einheit.flaeche_m2 else "—")),
        ("Etage", (einheit.etage or "—")),
        ("Verfügbar", verf),
    ]
    bw = (w - 40 * mm) / 4
    for i, (label, wert) in enumerate(fakten):
        x = 20 * mm + i * bw
        c.setStrokeColor(colors.HexColor("#E2E8F0")); c.setLineWidth(0.8)
        c.roundRect(x, y - 18 * mm, bw - 4 * mm, 18 * mm, 3 * mm, stroke=1, fill=0)
        c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#64748B"))
        c.drawString(x + 4 * mm, y - 6 * mm, label.upper())
        c.setFont("Helvetica-Bold", 13); c.setFillColor(colors.black)
        c.drawString(x + 4 * mm, y - 14 * mm, str(wert))

    # Mietzins-Aufstellung
    y -= 30 * mm
    c.setFont("Helvetica-Bold", 12); c.drawString(20 * mm, y, "Mietzins")
    y -= 8 * mm
    c.setFont("Helvetica", 10)
    for label, betrag in [("Nettomiete", einheit.nettomiete_aktuell or Decimal('0')),
                          ("Nebenkosten (akonto)", einheit.nebenkosten_aktuell or Decimal('0'))]:
        c.drawString(24 * mm, y, label)
        c.drawRightString(120 * mm, y, f"CHF {_fmt(betrag)}")
        y -= 6 * mm
    c.setStrokeColor(colors.HexColor("#CBD5E1")); c.line(24 * mm, y + 1 * mm, 120 * mm, y + 1 * mm)
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(24 * mm, y, "Bruttomiete / Monat")
    c.drawRightString(120 * mm, y, f"CHF {_fmt(brutto)}")

    # Beschreibung
    if (einheit.ausschreibung_notiz or '').strip():
        y -= 14 * mm
        c.setFont("Helvetica-Bold", 12); c.drawString(20 * mm, y, "Beschreibung")
        y -= 7 * mm
        c.setFont("Helvetica", 10)
        from textwrap import wrap
        for para in einheit.ausschreibung_notiz.splitlines():
            for line in (wrap(para, 95) or ['']):
                if y < 78 * mm:
                    c.showPage(); y = c.Y_FOLGE; c.setFont("Helvetica", 10)
                c.drawString(24 * mm, y, line); y -= 5.5 * mm

    # Kontaktbox (früher ein Band am Blattfuss, das nun der Fusszeile gehört): im Fluss, auf der letzten Seite
    if y < 80 * mm:
        c.showPage(); y = c.Y_FOLGE
    boden = y - 14 * mm - 36 * mm        # Unterkante der Box
    c.setFillColor(colors.HexColor("#F1F5F9"))
    c.rect(20 * mm, boden, w - 40 * mm, 36 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(25 * mm, boden + 28 * mm, "Interessiert? Kontaktieren Sie uns")
    c.setFont("Helvetica", 10)
    if verwaltung:
        zeile = verwaltung.firma or ""
        tel = getattr(verwaltung, 'telefon', '') or ''
        mail = getattr(verwaltung, 'email', '') or ''
        c.drawString(25 * mm, boden + 21 * mm, zeile)
        kontakt = " · ".join([x for x in [tel, mail] if x])
        if kontakt:
            c.drawString(25 * mm, boden + 15 * mm, kontakt)
    if bewerbung_url:
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPDF
        seite = 26 * mm
        qr = QrCodeWidget(bewerbung_url, barLevel='M')
        x0, y0, x1, y1 = qr.getBounds()
        zeichnung = Drawing(seite, seite, transform=[seite / (x1 - x0), 0, 0, seite / (y1 - y0), 0, 0])
        zeichnung.add(qr)
        renderPDF.draw(zeichnung, c, w - 25 * mm - seite, boden + 5 * mm)
        c.setFont("Helvetica-Bold", 9); c.setFillColor(colors.black)
        c.drawRightString(w - 25 * mm - seite - 3 * mm, boden + 21 * mm, "Online bewerben")
        c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#374151"))
        c.drawRightString(w - 25 * mm - seite - 3 * mm, boden + 16 * mm, "QR-Code scannen")
    c.setFont("Helvetica-Oblique", 8); c.setFillColor(colors.HexColor("#4b5563"))
    c.drawString(25 * mm, boden + 4 * mm, "Angaben ohne Gewähr. Kein Rechtsanspruch aus diesem Exposé.")

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
