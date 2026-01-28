import io
import datetime
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required

# Profi-Tools
import segno
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
import reportlab.lib.utils

from core.models import Mietvertrag, Verwaltung

def format_iban(iban):
    """Formatiert IBAN in 4er Blöcke für bessere Lesbarkeit"""
    if not iban: return ""
    iban = iban.replace(" ", "")
    return " ".join(iban[i:i+4] for i in range(0, len(iban), 4))

def draw_cross(c, x, y):
    """Zeichnet das Schweizer Kreuz in den QR Code"""
    # 1. Schwarzer Hintergrund
    c.setFillColorRGB(0, 0, 0)
    c.rect(x - 3.5*mm, y - 3.5*mm, 7*mm, 7*mm, fill=1, stroke=0)
    # 2. Weisses Kreuz (Pinsel wird hier weiss!)
    c.setFillColorRGB(1, 1, 1)
    bar_width = 1.1 * mm
    bar_length = 3.8 * mm
    c.rect(x - bar_width/2, y - bar_length/2, bar_width, bar_length, fill=1, stroke=0)
    c.rect(x - bar_length/2, y - bar_width/2, bar_length, bar_width, fill=1, stroke=0)
    # WICHTIG: Pinsel wird hier NICHT zurückgesetzt, das machen wir im Hauptcode

@staff_member_required
def qr_rechnung_pdf(request, vertrag_id):
    """
    Erstellt eine professionelle QR-Rechnung (Fix: Schwarze Schrift).
    """
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    mieter = vertrag.mieter
    mandant = liegenschaft.mandant
    verwaltung = Verwaltung.objects.first()

    # --- 1. VALIDIERUNG ---
    errors = []
    if not liegenschaft.iban: errors.append(f"Liegenschaft hat keine IBAN.")
    if not mieter.strasse or not mieter.plz or not mieter.ort: errors.append(f"Mieter Adresse unvollständig.")
    if errors: return HttpResponse(f"Fehler:<br>- " + "<br>- ".join(errors), status=400)

    # --- 2. DATEN VORBEREITEN ---
    raw_iban = liegenschaft.iban.replace(" ", "")
    formatted_iban = format_iban(raw_iban)

    total_betrag = vertrag.netto_mietzins + vertrag.nebenkosten

    creditor_name = mandant.firma_oder_name if mandant else "Immobilienverwaltung"
    creditor_line1 = liegenschaft.strasse
    creditor_line2 = f"{liegenschaft.plz} {liegenschaft.ort}"

    debtor_name = f"{mieter.vorname} {mieter.nachname}"
    debtor_line1 = mieter.strasse
    debtor_line2 = f"{mieter.plz} {mieter.ort}"

    monat_jahr = datetime.date.today().strftime('%m/%Y')
    mitteilung = f"Miete {monat_jahr} - {einheit.bezeichnung}"

    # --- 3. QR DATEN GENERIEREN (SIX Specs) ---
    qr_data = "\n".join([
        "SPC", "0200", "1", raw_iban,
        "K", creditor_name, creditor_line1, creditor_line2, "", "", "CH",
        "", "", "", "", "", "", "",
        f"{total_betrag:.2f}", "CHF",
        "K", debtor_name, debtor_line1, debtor_line2, "", "", "CH",
        "NON", "", mitteilung, "EPD", ""
    ])

    # --- 4. PDF DESIGN ---
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"Mietrechnung {monat_jahr}")

    # === OBERER TEIL (Freies Design) ===
    # Logo
    if verwaltung and verwaltung.logo:
        try:
            c.drawImage(verwaltung.logo.path, 150*mm, 265*mm, width=40*mm, preserveAspectRatio=True, mask='auto')
        except: pass

    # Header
    c.setFillColor(colors.black) # Sicherstellen dass wir schwarz beginnen
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20*mm, 270*mm, "Mietrechnung")
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.darkgrey)
    c.drawString(20*mm, 264*mm, f"Monat: {monat_jahr}")
    c.setStrokeColor(colors.lightgrey)
    c.line(20*mm, 258*mm, 190*mm, 258*mm)

    # Adressen Block oben
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    y_start = 245*mm
    # Links: Mieter
    c.drawString(20*mm, y_start, "Rechnungsempfänger:")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20*mm, y_start - 6*mm, debtor_name)
    c.setFont("Helvetica", 11)
    c.drawString(20*mm, y_start - 11*mm, debtor_line1)
    c.drawString(20*mm, y_start - 16*mm, debtor_line2)

    # Rechts: Objekt
    c.setFont("Helvetica", 9)
    c.drawString(110*mm, y_start, "Objekt / Details:")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(110*mm, y_start - 6*mm, f"{einheit.liegenschaft.strasse}")
    c.drawString(110*mm, y_start - 11*mm, f"{einheit.bezeichnung}")

    # Zahlen
    y_tab = y_start - 35*mm
    c.setStrokeColor(colors.lightgrey)
    c.line(110*mm, y_tab + 4*mm, 190*mm, y_tab + 4*mm)
    c.setFont("Helvetica", 10)
    c.drawString(110*mm, y_tab, "Nettomiete")
    c.drawRightString(190*mm, y_tab, f"CHF {vertrag.netto_mietzins:,.2f}")
    c.drawString(110*mm, y_tab - 6*mm, "Nebenkosten")
    c.drawRightString(190*mm, y_tab - 6*mm, f"CHF {vertrag.nebenkosten:,.2f}")
    c.setLineWidth(0.5)
    c.line(110*mm, y_tab - 10*mm, 190*mm, y_tab - 10*mm)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(110*mm, y_tab - 16*mm, "Totalbetrag")
    c.drawRightString(190*mm, y_tab - 16*mm, f"CHF {total_betrag:,.2f}")

    # === UNTERER TEIL (QR BILL) ===
    # Startpunkt Y für den QR-Teil (fixiert auf A4 unten)
    # Perforationslinie
    c.setDash(1, 4)
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.line(0, 105*mm, 210*mm, 105*mm)
    c.setDash([])

    # Scheren-Symbol
    c.setFillColor(colors.black) # Zurücksetzen auf Schwarz
    c.setFont("ZapfDingbats", 10)
    c.drawString(10*mm, 107*mm, "✂")

    # Titel
    c.setFont("Helvetica-Bold", 11)
    c.drawString(67*mm, 95*mm, "Zahlteil")
    c.drawString(5*mm, 95*mm, "Empfangsschein")

    # QR Code zeichnen
    qr = segno.make(qr_data, error='M')
    qr_img = io.BytesIO()
    qr.save(qr_img, kind='png', scale=4)
    qr_img.seek(0)
    c.drawImage(reportlab.lib.utils.ImageReader(qr_img), 67*mm, 42*mm, width=46*mm, height=46*mm)

    # Kreuz zeichnen (setzt Pinsel auf WEISS!)
    draw_cross(c, 67*mm + 23*mm, 42*mm + 23*mm)

    # --- TEXT FUNKTIONEN ---
    def draw_details(x, is_receipt=False):
        """Zeichnet die Textblöcke"""
        # HIER IST DER FIX: Pinsel explizit wieder auf Schwarz stellen!
        c.setFillColor(colors.black)

        y = 90*mm
        lh = 3.5*mm

        # 1. KONTO / ZAHLBAR AN
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x, y, "Konto / Zahlbar an")
        y -= lh
        c.setFont("Helvetica", 8)
        c.drawString(x, y, formatted_iban)
        y -= lh
        c.drawString(x, y, creditor_name)
        y -= lh
        c.drawString(x, y, creditor_line1)
        y -= lh
        c.drawString(x, y, creditor_line2)

        # 2. REFERENZ / INFO
        if is_receipt:
            y -= (lh * 1.5)
            c.setFont("Helvetica-Bold", 8)
            c.drawString(x, y, "Information")
            y -= lh
            c.setFont("Helvetica", 7)
            c.drawString(x, y, mitteilung)
            y -= (lh * 0.5)
        else:
            y -= (lh * 3)

        # 3. ZAHLBAR DURCH
        y -= (lh * 1.5)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x, y, "Zahlbar durch")
        y -= lh
        c.setFont("Helvetica", 8)
        c.drawString(x, y, debtor_name)
        y -= lh
        c.drawString(x, y, debtor_line1)
        y -= lh
        c.drawString(x, y, debtor_line2)

    # Linker Teil (Empfangsschein)
    draw_details(5*mm, is_receipt=True)

    # Währung/Betrag Links
    c.setFillColor(colors.black) # Sicherheitshalber
    c.setFont("Helvetica-Bold", 8); c.drawString(5*mm, 15*mm, "Währung"); c.drawString(18*mm, 15*mm, "Betrag")
    c.setFont("Helvetica", 10); c.drawString(5*mm, 10*mm, "CHF"); c.drawString(18*mm, 10*mm, f"{total_betrag:,.2f}")

    # Rechter Teil (Zahlteil)
    draw_details(118*mm, is_receipt=False)

    # Währung/Betrag Rechts
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8); c.drawString(67*mm, 15*mm, "Währung"); c.drawString(82*mm, 15*mm, "Betrag")
    c.setFont("Helvetica", 10); c.drawString(67*mm, 10*mm, "CHF"); c.drawString(82*mm, 10*mm, f"{total_betrag:,.2f}")

    # Zusätzliche Info (Rechts oben im Zahlteil)
    c.setFont("Helvetica-Bold", 7); c.drawString(118*mm, 35*mm, "Zusätzliche Informationen")
    c.setFont("Helvetica", 7); c.drawString(118*mm, 32*mm, mitteilung)

    c.showPage()
    c.save()

    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f"QR_Rechnung_{mieter.nachname}_{monat_jahr.replace('/', '-')}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response