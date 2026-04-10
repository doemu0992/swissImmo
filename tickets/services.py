# tickets/services.py
import io
import segno
from django.core.mail import send_mail
from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader

from .models import SchadenMeldung, TicketNachricht, HandwerkerAuftrag
from core.utils.email_service import send_ticket_receipt

# --- 1. INTERNE VERWALTUNGS-LOGIK ---

def create_handwerker_auftrag(ticket, handwerker, bemerkung=""):
    """
    Erstellt einen Auftrag für einen Handwerker und postet automatisch
    eine interne Systemnachricht in den Chat.
    """
    auftrag = HandwerkerAuftrag.objects.create(
        ticket=ticket,
        handwerker=handwerker,
        bemerkung=bemerkung
    )

    # System-Meldung in den Chat
    TicketNachricht.objects.create(
        ticket=ticket,
        absender_name="System",
        typ='system',
        nachricht=f"Handwerker beauftragt: {handwerker}",
        is_intern=True
    )
    return auftrag

def add_chat_message(ticket, text, absender="Verwaltung", is_von_verwaltung=True):
    """
    Fügt eine Chatnachricht hinzu und aktualisiert den Ticket-Status.
    """
    msg = TicketNachricht.objects.create(
        ticket=ticket,
        absender_name=absender,
        typ='chat',
        nachricht=text,
        is_von_verwaltung=is_von_verwaltung
    )

    if is_von_verwaltung and ticket.status == 'neu':
        ticket.status = 'in_bearbeitung'
        ticket.save()

    return msg


# --- 2. ÖFFENTLICHE FORMULAR & PDF LOGIK ---

def process_public_ticket_form(liegenschaft, post_data, files_data):
    """
    Verarbeitet das öffentliche QR-Formular, setzt die Beschreibung
    zusammen und speichert das Ticket.
    """
    # 1. Basis Daten
    titel = post_data.get('titel')
    beschreibung_raw = post_data.get('beschreibung')
    einheit_id = post_data.get('einheit_id')
    foto = files_data.get('foto')

    # 2. Kontakt Daten
    anrede = post_data.get('anrede', '')
    vorname = post_data.get('vorname', '')
    nachname = post_data.get('nachname', '')
    email = post_data.get('email', '')
    telefon = post_data.get('telefon', '')
    erreichbarkeit_list = post_data.getlist('erreichbarkeit')

    melder_name = f"{anrede} {vorname} {nachname}".strip()

    # 3. Geräte Daten
    hersteller = post_data.get('hersteller')
    seriennummer = post_data.get('seriennummer')

    # 4. Beschreibung zusammenbauen
    final_text = f"{beschreibung_raw}\n\n--- KONTAKT ---\n"
    final_text += f"Name: {melder_name}\nTel: {telefon}\nEmail: {email}\n"

    if erreichbarkeit_list:
        final_text += f"Erreichbar: {', '.join(erreichbarkeit_list)}\n"

    if hersteller or seriennummer:
        final_text += "\n--- GERÄT ---\n"
        if hersteller: final_text += f"Marke: {hersteller}\n"
        if seriennummer: final_text += f"S/N: {seriennummer}\n"

    # Speichern
    ticket = SchadenMeldung(
        titel=f"{titel} ({nachname})",
        beschreibung=final_text,
        prioritaet='mittel',
        status='neu',
        betroffene_einheit_id=einheit_id if einheit_id else None,
        liegenschaft=liegenschaft,
        email_melder=email,
        tel_melder=telefon,
        gemeldet_von=None
    )
    if foto:
        ticket.foto = foto
    ticket.save()

    # Bestätigungs-Email via Brevo senden
    try:
        send_ticket_receipt(ticket)
    except Exception as e:
        print(f"Fehler beim Mailversand: {e}")

    return ticket

def generate_qr_poster(liegenschaft, domain):
    """
    Generiert das PDF für den Treppenhaus-Aushang mit QR-Code.
    Rückgabe ist ein BytesIO Buffer.
    """
    report_url = f"https://{domain}/report/{liegenschaft.id}/"

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header Balken (Blau)
    c.setFillColorRGB(0.1, 0.4, 0.8)
    c.rect(0, height - 60*mm, width, 60*mm, fill=1, stroke=0)

    # Header Text
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(width/2, height - 30*mm, "Haben Sie ein Anliegen?")
    c.setFont("Helvetica", 16)
    c.drawCentredString(width/2, height - 45*mm, f"Liegenschaft: {liegenschaft.strasse}, {liegenschaft.ort}")

    # QR Code generieren
    qr = segno.make(report_url, error='H')
    qr_img = io.BytesIO()
    qr.save(qr_img, kind='png', scale=10)
    qr_img.seek(0)

    # QR Code zeichnen
    c.drawImage(ImageReader(qr_img), (width/2) - 40*mm, height - 160*mm, width=80*mm, height=80*mm)

    # Anweisung Text
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width/2, height - 180*mm, "Scannen & Melden")

    c.setFont("Helvetica", 12)
    c.setFillColor(colors.darkgrey)
    lines = ["1. Kamera öffnen", "2. QR-Code scannen", "3. Problem direkt am Handy melden", "4. Wir kümmern uns darum!"]
    y = height - 200*mm
    for line in lines:
        c.drawCentredString(width/2, y, line)
        y -= 8*mm

    c.showPage()
    c.save()
    buffer.seek(0)

    return buffer