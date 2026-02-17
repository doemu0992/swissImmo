import io
import segno
import reportlab.lib.utils
from reportlab.lib.units import mm
from reportlab.lib import colors

def format_iban(iban):
    """Formatiert IBAN in 4er Blöcke"""
    if not iban: return ""
    iban = iban.replace(" ", "")
    return " ".join(iban[i:i+4] for i in range(0, len(iban), 4))

def draw_cross(c, x, y):
    """Zeichnet das Schweizer Kreuz in den QR Code"""
    c.setFillColorRGB(0, 0, 0)
    c.rect(x - 3.5*mm, y - 3.5*mm, 7*mm, 7*mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    bar_width = 1.1 * mm
    bar_length = 3.8 * mm
    c.rect(x - bar_width/2, y - bar_length/2, bar_width, bar_length, fill=1, stroke=0)
    c.rect(x - bar_length/2, y - bar_width/2, bar_length, bar_width, fill=1, stroke=0)
    c.setFillColor(colors.black) # Reset auf Schwarz

def draw_qr_bill(c, iban, creditor, debtor, amount, reason):
    """
    Zeichnet den offiziellen QR-Teil unten auf das Blatt.
    Funktioniert für Mietzins UND Nebenkosten.
    """
    # 1. Daten Vorbereiten
    raw_iban = iban.replace(" ", "")
    formatted_iban = format_iban(raw_iban)

    # Creditor (Empfänger = Verwaltung/Mandant)
    creditor_data = {
        'name': creditor.get('name', '')[:70],
        'line1': creditor.get('line1', '')[:70],
        'line2': creditor.get('line2', '')[:70],
    }

    # Debtor (Zahler = Mieter)
    debtor_data = {
        'name': debtor.get('name', '')[:70],
        'line1': debtor.get('line1', '')[:70],
        'line2': debtor.get('line2', '')[:70],
    }

    # QR Daten Payload (SIX Specs)
    qr_data = "\n".join([
        "SPC", "0200", "1", raw_iban,
        "K", creditor_data['name'], creditor_data['line1'], creditor_data['line2'], "", "", "CH",
        "", "", "", "", "", "", "",
        f"{amount:.2f}", "CHF",
        "K", debtor_data['name'], debtor_data['line1'], debtor_data['line2'], "", "", "CH",
        "NON", "", reason[:140], "EPD", ""
    ])

    # 2. Zeichnen Starten (Unten am Blatt)

    # Perforationslinie
    c.setDash(1, 4)
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.line(0, 105*mm, 210*mm, 105*mm)
    c.setDash([]) # Reset

    # Schere
    c.setFillColor(colors.black)
    c.setFont("ZapfDingbats", 10)
    c.drawString(10*mm, 107*mm, "✂")

    # Titel
    c.setFont("Helvetica-Bold", 11)
    c.drawString(67*mm, 95*mm, "Zahlteil")
    c.drawString(5*mm, 95*mm, "Empfangsschein")

    # QR Code Bild
    qr = segno.make(qr_data, error='M')
    qr_img = io.BytesIO()
    qr.save(qr_img, kind='png', scale=4)
    qr_img.seek(0)
    c.drawImage(reportlab.lib.utils.ImageReader(qr_img), 67*mm, 42*mm, width=46*mm, height=46*mm)

    # Kreuz drübermalen
    draw_cross(c, 67*mm + 23*mm, 42*mm + 23*mm)

    # Hilfsfunktion für Textblöcke
    def draw_details(x, is_receipt=False):
        c.setFillColor(colors.black)
        y = 90*mm
        lh = 3.5*mm

        # Konto / Zahlbar an
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x, y, "Konto / Zahlbar an")
        y -= lh
        c.setFont("Helvetica", 8)
        c.drawString(x, y, formatted_iban)
        y -= lh
        c.drawString(x, y, creditor_data['name'])
        y -= lh
        c.drawString(x, y, creditor_data['line1'])
        y -= lh
        c.drawString(x, y, creditor_data['line2'])

        # Info (nur links kurz, rechts lang)
        if is_receipt:
            y -= (lh * 1.5)
            c.setFont("Helvetica-Bold", 8)
            c.drawString(x, y, "Information")
            y -= lh
            c.setFont("Helvetica", 7)
            # Auf Empfangsschein kürzen wir den Text wenn nötig
            c.drawString(x, y, reason[:25] + "..." if len(reason)>25 else reason)
            y -= (lh * 0.5)
        else:
            y -= (lh * 3)

        # Zahlbar durch
        y -= (lh * 1.5)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x, y, "Zahlbar durch")
        y -= lh
        c.setFont("Helvetica", 8)
        c.drawString(x, y, debtor_data['name'])
        y -= lh
        c.drawString(x, y, debtor_data['line1'])
        y -= lh
        c.drawString(x, y, debtor_data['line2'])

    # Linker Teil (Empfangsschein)
    draw_details(5*mm, is_receipt=True)

    # Währung/Betrag Links
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8); c.drawString(5*mm, 15*mm, "Währung"); c.drawString(18*mm, 15*mm, "Betrag")
    c.setFont("Helvetica", 10); c.drawString(5*mm, 10*mm, "CHF"); c.drawString(18*mm, 10*mm, f"{amount:,.2f}")

    # Rechter Teil (Zahlteil)
    draw_details(118*mm, is_receipt=False)

    # Währung/Betrag Rechts
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8); c.drawString(67*mm, 15*mm, "Währung"); c.drawString(82*mm, 15*mm, "Betrag")
    c.setFont("Helvetica", 10); c.drawString(67*mm, 10*mm, "CHF"); c.drawString(82*mm, 10*mm, f"{amount:,.2f}")

    # Info Rechts
    c.setFont("Helvetica-Bold", 7); c.drawString(118*mm, 35*mm, "Zusätzliche Informationen")
    c.setFont("Helvetica", 7); c.drawString(118*mm, 32*mm, reason)