"""Mieterkonto-Auszug: chronologische Bewegungen (Sollstellungen als Soll,
Zahlungseingänge als Haben) mit laufendem Saldo — für Team + Mieterportal."""
import io
from decimal import Decimal


def berechne_mieterkonto(mieter, von=None, bis=None):
    """Gibt (zeilen, endsaldo) zurück. Positiver Saldo = Mieter schuldet."""
    from finance.models import DebitorenRechnung, Zahlungseingang
    bewegungen = []

    rech = DebitorenRechnung.objects.filter(vertrag__mieter=mieter).exclude(status='storniert')
    for r in rech:
        d = r.datum
        if (von and d < von) or (bis and d > bis):
            continue
        bewegungen.append({'datum': d, 'text': r.titel, 'soll': r.betrag or Decimal('0'),
                           'haben': Decimal('0'), 'sort': 0})

    zahl = Zahlungseingang.objects.filter(vertrag__mieter=mieter, status='verbucht')
    for z in zahl:
        d = z.datum_eingang
        if (von and d < von) or (bis and d > bis):
            continue
        text = z.bemerkung or 'Zahlungseingang'
        bewegungen.append({'datum': d, 'text': text, 'soll': Decimal('0'),
                           'haben': z.betrag or Decimal('0'), 'sort': 1})

    bewegungen.sort(key=lambda b: (b['datum'], b['sort']))
    saldo = Decimal('0')
    for b in bewegungen:
        saldo += b['soll'] - b['haben']
        b['saldo'] = saldo
    return bewegungen, saldo


def generate_mieterkonto_pdf(mieter, verwaltung=None, von=None, bis=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm

    zeilen, endsaldo = berechne_mieterkonto(mieter, von=von, bis=bis)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    def kopf():
        c.setFillColorRGB(0.12, 0.23, 0.54)
        c.rect(0, h - 28 * mm, w, 28 * mm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(20 * mm, h - 17 * mm, "Kontoauszug Mieter")
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, h - 23 * mm, mieter.display_name)
        if verwaltung:
            c.drawRightString(w - 20 * mm, h - 17 * mm, verwaltung.firma)
        c.setFillColorRGB(0, 0, 0)

    def spaltenkopf(y):
        c.setFont("Helvetica-Bold", 8.5); c.setFillColorRGB(0.4, 0.45, 0.5)
        c.drawString(20 * mm, y, "DATUM")
        c.drawString(42 * mm, y, "TEXT")
        c.drawRightString(135 * mm, y, "SOLL")
        c.drawRightString(162 * mm, y, "HABEN")
        c.drawRightString(190 * mm, y, "SALDO")
        c.setFillColorRGB(0, 0, 0)
        c.setStrokeColorRGB(0.8, 0.82, 0.85)
        c.line(20 * mm, y - 2 * mm, 190 * mm, y - 2 * mm)

    kopf()
    y = h - 40 * mm
    spaltenkopf(y)
    y -= 8 * mm
    c.setFont("Helvetica", 9)

    def chf(v):
        if not v:
            return ''
        return f"{float(v):,.2f}".replace(',', "'")

    for b in zeilen:
        if y < 25 * mm:
            c.showPage(); kopf(); y = h - 40 * mm; spaltenkopf(y); y -= 8 * mm; c.setFont("Helvetica", 9)
        c.drawString(20 * mm, y, b['datum'].strftime('%d.%m.%Y'))
        c.drawString(42 * mm, y, (b['text'] or '')[:52])
        c.drawRightString(135 * mm, y, chf(b['soll']))
        c.drawRightString(162 * mm, y, chf(b['haben']))
        c.drawRightString(190 * mm, y, chf(b['saldo']))
        y -= 5.6 * mm

    if not zeilen:
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(20 * mm, y, "Keine Buchungen im Zeitraum.")
        c.setFillColorRGB(0, 0, 0)

    # Endsaldo
    y -= 4 * mm
    c.setStrokeColorRGB(0.4, 0.45, 0.5); c.setLineWidth(1)
    c.line(120 * mm, y, 190 * mm, y)
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 11)
    label = "Offener Saldo (Mieter schuldet)" if endsaldo > 0 else ("Guthaben Mieter" if endsaldo < 0 else "Ausgeglichen")
    c.drawString(20 * mm, y, label)
    c.drawRightString(190 * mm, y, f"CHF {chf(abs(endsaldo)) or '0.00'}")

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()
