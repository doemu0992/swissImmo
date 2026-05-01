import io
import os
import segno
import reportlab.lib.utils
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from django.conf import settings
from django.utils import timezone

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

def generate_mieter_qr_pdf(mieter, vertrag, verwaltung):
    """
    Erstellt ein PDF mit dem QR-Zahlteil für einen Mieter/Vertrag.
    """
    output_dir = os.path.join(settings.MEDIA_ROOT, 'qr_rechnungen')
    os.makedirs(output_dir, exist_ok=True)
    filename = f"QR_Rechnung_{mieter.id}_{vertrag.id}.pdf"
    file_path = os.path.join(output_dir, filename)

    # 1. Daten zusammensuchen
    iban = getattr(verwaltung, 'iban', None) or "CH0000000000000000000"

    creditor = {
        'name': getattr(verwaltung, 'firma', ''),
        'line1': getattr(verwaltung, 'strasse', ''),
        'line2': f"{getattr(verwaltung, 'plz', '')} {getattr(verwaltung, 'ort', '')}".strip()
    }

    debtor = {
        'name': f"{mieter.vorname} {mieter.nachname}".strip() or getattr(mieter, 'display_name', ''),
        'line1': getattr(mieter, 'strasse', ''),
        'line2': f"{getattr(mieter, 'plz', '')} {getattr(mieter, 'ort', '')}".strip()
    }

    amount = vertrag.brutto_mietzins
    monat = timezone.now().strftime("%m/%Y")
    reason = f"Miete {vertrag.einheit.bezeichnung} - {monat}"

    # 2. PDF generieren
    c = canvas.Canvas(file_path, pagesize=A4)

    # Text oben auf der A4-Seite
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20*mm, 260*mm, "Einzahlungsschein Mietzins")
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, 250*mm, f"Mieter: {debtor['name']}")
    c.drawString(20*mm, 245*mm, f"Objekt: {vertrag.einheit.bezeichnung}")
    c.drawString(20*mm, 235*mm, "Bitte verwenden Sie den untenstehenden Einzahlungsschein für Ihre Überweisung.")

    # 3. QR-Funktion aufrufen (zeichnet unten den Zahlteil)
    draw_qr_bill(c, iban, creditor, debtor, float(amount), reason)

    c.save()

    # 4. URL zurückgeben
    return f"{settings.MEDIA_URL}qr_rechnungen/{filename}"

# 🔥 NEU: Die Funktion für den Mahnbrief nach deiner Vorlage
def generate_mahnung_pdf(vertrag, offener_betrag, verwaltung):
    output_dir = os.path.join(settings.MEDIA_ROOT, 'qr_rechnungen')
    os.makedirs(output_dir, exist_ok=True)
    filename = f"Mahnung_{vertrag.mieter.id}_{vertrag.id}.pdf"
    file_path = os.path.join(output_dir, filename)

    mieter = vertrag.mieter
    iban = getattr(verwaltung, 'iban', None) or "CH0000000000000000000"

    creditor = {
        'name': getattr(verwaltung, 'firma', ''),
        'line1': getattr(verwaltung, 'strasse', ''),
        'line2': f"{getattr(verwaltung, 'plz', '')} {getattr(verwaltung, 'ort', '')}".strip()
    }

    debtor = {
        'name': f"{mieter.vorname} {mieter.nachname}".strip() or getattr(mieter, 'display_name', ''),
        'line1': getattr(mieter, 'strasse', ''),
        'line2': f"{getattr(mieter, 'plz', '')} {getattr(mieter, 'ort', '')}".strip()
    }

    heute = timezone.now()
    monat_text = heute.strftime("%B %Y") # Wird für die Rechnung genutzt
    datum_text = heute.strftime("%d. %B %Y") # Datum oben rechts

    # Grund für den QR Code
    reason = f"Mahnung Miete {vertrag.einheit.bezeichnung}"

    c = canvas.Canvas(file_path, pagesize=A4)

    # --- 1. Adressblock (Für C5 Fensterkuvert) ---
    c.setFont("Helvetica", 11)
    c.drawString(20*mm, 245*mm, debtor['name'])
    c.drawString(20*mm, 240*mm, debtor['line1'])
    c.drawString(20*mm, 235*mm, debtor['line2'])

    # --- 2. Ort und Datum (Rechtsbündig) ---
    c.drawString(120*mm, 205*mm, f"{getattr(verwaltung, 'ort', 'Ort')} {datum_text}")

    # --- 3. Betreff ---
    y_pos = 185*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20*mm, y_pos, "MAHNUNG / KÜNDIGUNGSANDROHUNG")
    c.setFont("Helvetica", 11)
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, f"{vertrag.einheit.liegenschaft.strasse}, {vertrag.einheit.bezeichnung}")

    # --- 4. Anrede ---
    y_pos -= 15*mm
    anrede = "Frau" if getattr(mieter, 'anrede', '') == 'Frau' else "Herr"
    c.drawString(20*mm, y_pos, f"Sehr geehrte(r) {anrede} {mieter.nachname}")

    # --- 5. Einleitungstext ---
    y_pos -= 10*mm
    c.drawString(20*mm, y_pos, "Ihr Konto weist folgende offene Posten auf:")
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, f"(Zahlungen berücksichtigt bis {heute.strftime('%d.%m.%Y')})")

    # --- 6. Tabelle (Offene Posten) ---
    y_pos -= 15*mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, y_pos, "Positionen")
    c.drawString(80*mm, y_pos, "fällig am")
    c.drawString(110*mm, y_pos, "Stufe")
    c.drawString(140*mm, y_pos, "Betrag")

    # Linie unter Header
    y_pos -= 2*mm
    c.line(20*mm, y_pos, 160*mm, y_pos)

    # Zeile
    y_pos -= 5*mm
    c.setFont("Helvetica", 10)

    # Fälligkeit ist der letzte Tag des Vormonats (Beispielhaft)
    faelligkeits_datum = heute.replace(day=1) - timezone.timedelta(days=1)

    c.drawString(20*mm, y_pos, f"Miete {vertrag.einheit.bezeichnung}")
    c.drawString(80*mm, y_pos, faelligkeits_datum.strftime('%d.%m.%Y'))
    c.drawString(110*mm, y_pos, "1")
    c.drawString(140*mm, y_pos, f"{float(offener_betrag):.2f} CHF")

    # Linie über Total
    y_pos -= 3*mm
    c.line(20*mm, y_pos, 160*mm, y_pos)

    # Total
    y_pos -= 5*mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(140*mm, y_pos, f"{float(offener_betrag):.2f} CHF")

    # --- 7. Rechtlicher Text (Art. 257d OR) ---
    y_pos -= 15*mm
    c.setFont("Helvetica", 10)

    # Lange Texte aufteilen, damit sie nicht über den Rand gehen
    text1 = "Gestützt auf Art. 257d OR gewähren wir Ihnen eine letzte Zahlungspflicht von 30 Tagen. Nach unbenütztem"
    text2 = "Ablauf dieser Frist sind wir gezwungen, das Mietverhältnis unter Einhaltung der gesetzlichen Kündigungsfrist"
    text3 = "von 30 Tagen auf Ende des nächsten Monats zu kündigen und unverzüglich die Betreibung einzuleiten."

    text4 = "Wir hoffen, dass Sie sich und uns diese äusserst unangenehmen Massnahmen ersparen und danken Ihnen"
    text5 = "für Ihre Überweisung. Aus rechtlichen Gründen wird dieses Schreiben allen Solidarpartnern separat zugestellt."

    c.drawString(20*mm, y_pos, text1)
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, text2)
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, text3)

    y_pos -= 10*mm
    c.drawString(20*mm, y_pos, text4)
    y_pos -= 5*mm
    c.drawString(20*mm, y_pos, text5)

    # --- 8. Grussformel ---
    y_pos -= 15*mm
    c.drawString(20*mm, y_pos, "Freundliche Grüsse")

    y_pos -= 15*mm # Platz für Unterschrift
    c.setFont("Helvetica-Bold", 11)
    # Hier ziehen wir dynamisch den Namen der Kontaktperson aus der Verwaltung (oder Fallback auf die Firma)
    kontakt = getattr(verwaltung, 'kontaktperson', creditor['name'])
    c.drawString(20*mm, y_pos, kontakt)

    # 🔥 ERSTELLT NEUE SEITE FÜR DEN QR-CODE
    c.showPage()

    # --- 9. QR Code unten anfügen ---
    draw_qr_bill(c, iban, creditor, debtor, float(offener_betrag), reason)

    c.save()
    return f"{settings.MEDIA_URL}qr_rechnungen/{filename}"