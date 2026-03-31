from crm.models import Verwaltung
from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag, Leerstand
from tickets.models import SchadenMeldung

import io
import segno
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader

from core.utils.email_service import send_ticket_receipt

# ==========================================
# 1. LANDING PAGE (STARTSEITE)
# ==========================================
def index_view(request):
    """
    Zeigt die Startseite mit der Auswahl:
    - Schaden melden (Öffentlich)
    - Verwaltung Login (Intern)
    """
    return render(request, 'core/index.html')


# ==========================================
# 2. QR-CODE FORMULAR (ÖFFENTLICH)
# ==========================================
def public_ticket_view(request, liegenschaft_id):
    liegenschaft = get_object_or_404(Liegenschaft, pk=liegenschaft_id)

    # Einheiten laden
    einheiten = Einheit.objects.filter(liegenschaft=liegenschaft).order_by('etage', 'bezeichnung')
    for e in einheiten:
        aktiver_v = Mietvertrag.objects.filter(einheit=e, aktiv=True).first()
        e.mieter_namen = f"{aktiver_v.mieter.nachname}" if aktiver_v else "Leerstand"

    if request.method == 'POST':
        # 1. Basis Daten
        titel = request.POST.get('titel')
        beschreibung_raw = request.POST.get('beschreibung')
        einheit_id = request.POST.get('einheit_id')
        foto = request.FILES.get('foto')

        # 2. Kontakt Daten
        anrede = request.POST.get('anrede', '')
        vorname = request.POST.get('vorname', '')
        nachname = request.POST.get('nachname', '')
        email = request.POST.get('email', '')
        telefon = request.POST.get('telefon', '')
        # Erreichbarkeit (Liste von Checkboxen)
        erreichbarkeit_list = request.POST.getlist('erreichbarkeit')

        # Name zusammensetzen
        melder_name = f"{anrede} {vorname} {nachname}".strip()

        # 3. Geräte Daten
        hersteller = request.POST.get('hersteller')
        seriennummer = request.POST.get('seriennummer')

        # 4. Beschreibung zusammenbauen (Alles in den Text für Historie)
        final_text = f"{beschreibung_raw}\n\n"
        final_text += "--- KONTAKT ---\n"
        final_text += f"Name: {melder_name}\n"
        final_text += f"Tel: {telefon}\n"
        final_text += f"Email: {email}\n"

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
            status='offen',
            betroffene_einheit_id=einheit_id if einheit_id else None,
            liegenschaft=liegenschaft,
            # WICHTIG: Speichern der Kontaktdaten für Automatisierung
            email_melder=email,
            tel_melder=telefon,
            gemeldet_von=None
        )
        if foto:
            ticket.foto = foto

        ticket.save()

        # Bestätigungs-Email via Brevo senden 🚀
        try:
            send_ticket_receipt(ticket)
        except Exception as e:
            print(f"Fehler beim Mailversand: {e}")

        return render(request, 'core/public_ticket_form.html', {'success': True, 'liegenschaft': liegenschaft})

    return render(request, 'core/public_ticket_form.html', {
        'liegenschaft': liegenschaft,
        'einheiten': einheiten
    })


# ==========================================
# 3. AUSHANG GENERIEREN (ADMIN)
# ==========================================
@staff_member_required
def generate_hallway_poster(request, liegenschaft_id):
    liegenschaft = get_object_or_404(Liegenschaft, pk=liegenschaft_id)
    domain = request.get_host()
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
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Aushang_{liegenschaft.strasse}.pdf"'
    return response
