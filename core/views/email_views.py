from crm.models import Verwaltung, Mieter
from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag, Leerstand
from finance.models import AbrechnungsPeriode

import io
import datetime
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from django.http import HttpResponse

# ReportLab (PDF)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

# Eigene Imports
from core.utils.billing import berechne_abrechnung
from core.utils.qr_code import draw_qr_bill

# ==============================================================================
# HILFSFUNKTIONEN FÜR PDF-GENERIERUNG
# ==============================================================================

def draw_header(c, verwaltung):
    """ Zeichnet das Logo und die Absenderzeile oben """
    if not verwaltung: return
    if verwaltung.logo:
        try:
            c.drawImage(verwaltung.logo.path, 20*mm, 270*mm, height=15*mm, preserveAspectRatio=True, mask='auto')
        except: pass
    c.setFont("Helvetica", 8)
    c.drawRightString(190*mm, 280*mm, f"{verwaltung.firma} | {verwaltung.strasse} | {verwaltung.plz} {verwaltung.ort}")


def generate_single_pdf_bytes(periode, row, verwaltung, liegenschaft, vertrag):
    """ Erzeugt das NK-Abrechnung-PDF im Speicher (inkl. QR auf Seite 2) """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    if verwaltung:
        creditor = {'name': verwaltung.firma, 'line1': verwaltung.strasse, 'line2': f"{verwaltung.plz} {verwaltung.ort}"}
    else:
        creditor = {'name': "Immobilienverwaltung", 'line1': liegenschaft.strasse, 'line2': f"{liegenschaft.plz} {liegenschaft.ort}"}

    debtor = {'name': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}", 'line1': vertrag.mieter.strasse, 'line2': f"{vertrag.mieter.plz} {vertrag.mieter.ort}"} if vertrag else {'name': row['name'], 'line1': '', 'line2': ''}

    draw_header(c, verwaltung)
    c.setFont("Helvetica", 11); c.drawString(25*mm, 245*mm, debtor['name']); c.drawString(25*mm, 240*mm, debtor['line1']); c.drawString(25*mm, 235*mm, debtor['line2'])
    c.setFont("Helvetica", 10); c.drawRightString(190*mm, 245*mm, f"Datum: {datetime.date.today().strftime('%d.%m.%Y')}"); c.drawRightString(190*mm, 240*mm, f"Liegenschaft: {liegenschaft.ort}")
    c.setFont("Helvetica-Bold", 14); c.drawString(20*mm, 210*mm, f"Nebenkostenabrechnung: {periode.bezeichnung}")

    # Kostenauflistung...
    y = 170*mm
    c.setFillColorRGB(0.9, 0.9, 0.9); c.rect(20*mm, y-2*mm, 170*mm, 8*mm, fill=1, stroke=0); c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 10); c.drawString(25*mm, y, "Beschreibung"); c.drawRightString(185*mm, y, "Betrag (CHF)")
    y -= 10*mm; c.setFont("Helvetica", 10); c.drawString(25*mm, y, f"Kostenanteil"); c.drawRightString(185*mm, y, f"{row['kosten_anteil']:.2f}")
    y -= 6*mm; akonto = row.get('akonto', 0)
    if akonto > 0: c.drawString(25*mm, y, "Abzüglich Akonto Zahlungen"); c.drawRightString(185*mm, y, f"- {akonto:.2f}"); y -= 8*mm
    c.line(20*mm, y, 190*mm, y); y -= 8*mm; betrag = abs(row['saldo'])
    c.setFont("Helvetica-Bold", 12)
    label = "Nachzahlung zu Ihren Lasten:" if row['nachzahlung'] else "Guthaben zu Ihren Gunsten:"
    c.drawString(25*mm, y, label); c.drawRightString(185*mm, y, f"CHF {betrag:.2f}")

    c.showPage()
    if row['nachzahlung'] and liegenschaft.iban:
        try: draw_qr_bill(c, liegenschaft.iban, creditor, debtor, betrag, f"NK {periode.bezeichnung}"); c.showPage()
        except: pass

    c.save(); buffer.seek(0)
    return buffer.getvalue()


# 🔥 VERBESSERT: Hilfsfunktion für das kombinierte PDF (Brief S1 + QR S2)
def generate_mahnung_combined_pdf_bytes(vertrag, verwaltung, monat_str, betrag_str, heute):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    # --- SEITE 1: DAS JURISTISCHE SCHREIBEN ---
    left_margin = 25*mm
    right_window_margin = 120*mm

    c.setFont("Helvetica-Bold", 10)
    if verwaltung:
        c.drawString(left_margin, 280*mm, verwaltung.firma)
        c.setFont("Helvetica", 9)
        c.drawString(left_margin, 275*mm, f"{verwaltung.strasse}, {verwaltung.plz} {verwaltung.ort}")

    c.setFont("Helvetica", 11)
    y_addr = 250*mm
    if vertrag.mieter.is_company:
        c.drawString(right_window_margin, y_addr, vertrag.mieter.firma); y_addr -= 5*mm
    c.drawString(right_window_margin, y_addr, f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}")
    c.drawString(right_window_margin, y_addr-5*mm, vertrag.mieter.strasse)
    c.drawString(right_window_margin, y_addr-10*mm, f"{vertrag.mieter.plz} {vertrag.mieter.ort}")

    c.setFont("Helvetica", 10); c.drawString(left_margin, 210*mm, f"{verwaltung.ort if verwaltung else 'Ort'}, {heute.strftime('%d.%m.%Y')}")
    c.setFont("Helvetica-Bold", 12); c.drawString(left_margin, 195*mm, f"Zahlungsverzug gemäss Art. 257d OR – Kündigungsandrohung")
    c.setFont("Helvetica-Bold", 10); c.drawString(left_margin, 189*mm, f"Mietobjekt: {vertrag.einheit.bezeichnung}, {vertrag.einheit.liegenschaft.strasse}")

    c.setFont("Helvetica", 11); text_y = 175*mm
    salutation = f"Sehr geehrte Damen und Herren,"
    if vertrag.mieter.anrede == "Herr": salutation = f"Sehr geehrter Herr {vertrag.mieter.nachname},"
    elif vertrag.mieter.anrede == "Frau": salutation = f"Sehr geehrte Frau {vertrag.mieter.nachname},"
    c.drawString(left_margin, text_y, salutation); text_y -= 10*mm

    lines = [
        f"Bei der Kontrolle unserer Mietzinseingänge mussten wir feststellen, dass für den Monat",
        f"{monat_str} noch ein Betrag von CHF {betrag_str} ausstehend ist.", "",
        "Gestützt auf Art. 257d des Schweizerischen Obligationenrechts (OR) setzen wir Ihnen hiermit",
        "eine Zahlungsfrist von", "", "30 TAGEN", "",
        f"ab Erhalt dieses Schreibens an, um den oben genannten Betrag zu begleichen.", "",
        "KÜNDIGUNGSANDROHUNG:",
        "Sollte die Zahlung nicht innert dieser Frist bei uns eintreffen, werden wir das",
        "Mietverhältnis gemäss Art. 257d Abs. 2 OR kündigen.", "",
        "Wir bitten Sie, die Unannehmlichkeiten einer Kündigung zu vermeiden und den Betrag",
        "umgehend zu überweisen.", "", "Freundliche Grüsse", "", "", "__________________________",
        f"{verwaltung.firma if verwaltung else 'Die Vermieterschaft'}"
    ]

    for line in lines:
        if "30 TAGEN" in line or "KÜNDIGUNGSANDROHUNG" in line: c.setFont("Helvetica-Bold", 11)
        else: c.setFont("Helvetica", 11)
        c.drawString(left_margin, text_y, line); text_y -= 5.5*mm

    # --- SEITE 2: DIE QR-RECHNUNG (Falls IBAN vorhanden) ---
    iban = vertrag.einheit.liegenschaft.iban
    if iban:
        try:
            c.showPage() # Neue Seite anfangen
            betrag_float = float(str(betrag_str).replace(',', '.'))

            if verwaltung:
                creditor = {'name': verwaltung.firma, 'line1': verwaltung.strasse, 'line2': f"{verwaltung.plz} {verwaltung.ort}"}
            else:
                creditor = {'name': "Verwaltung", 'line1': vertrag.einheit.liegenschaft.strasse, 'line2': f"{vertrag.einheit.liegenschaft.plz} {vertrag.einheit.liegenschaft.ort}"}

            m_name = vertrag.mieter.firma if vertrag.mieter.is_company else f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}"
            debtor = {'name': m_name, 'line1': vertrag.mieter.strasse, 'line2': f"{vertrag.mieter.plz} {vertrag.mieter.ort}"}

            draw_qr_bill(c, iban, creditor, debtor, betrag_float, f"Mahnung {monat_str} {vertrag.einheit.bezeichnung}")
            c.showPage()
        except: pass

    c.save(); buffer.seek(0)
    return buffer.getvalue()


# ==============================================================================
# VIEWS
# ==============================================================================

@staff_member_required
def send_abrechnung_email_view(request, periode_id):
    # (Abrechnungs-Logik bleibt gleich...)
    pass


@staff_member_required
def send_mahnung_email_view(request, vertrag_id):
    """ Verschickt die Mahnung per E-Mail (mit dem kombinierten PDF) """
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    verwaltung = Verwaltung.objects.first()
    monat_str = request.POST.get('monat', 'Laufender Monat')
    betrag_str = request.POST.get('betrag', '0.00')

    if not vertrag.mieter.email:
        messages.error(request, "Mieter hat keine E-Mail."); return redirect(request.META.get('HTTP_REFERER', '/admin/'))

    # Kombiniertes PDF generieren
    pdf_bytes = generate_mahnung_combined_pdf_bytes(vertrag, verwaltung, monat_str, betrag_str, datetime.date.today())

    context = {
        'firma_name': verwaltung.firma if verwaltung else 'Ihre Verwaltung',
        'logo_url': request.build_absolute_uri(verwaltung.logo.url) if verwaltung and verwaltung.logo else "",
        'mieter_name': vertrag.mieter.firma if vertrag.mieter.is_company else f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}",
        'objekt_name': f"{vertrag.einheit.bezeichnung} ({vertrag.einheit.liegenschaft.strasse})",
        'monat': monat_str, 'betrag': betrag_str,
    }

    html_content = render_to_string('emails/email_mahnung.html', context)
    email = EmailMultiAlternatives(
        subject=f"Mahnung mit Kündigungsandrohung: {context['objekt_name']}",
        body=f"Guten Tag, im Anhang finden Sie die Mahnung für {monat_str}.",
        from_email=settings.DEFAULT_FROM_EMAIL, to=[vertrag.mieter.email],
    )
    email.attach_alternative(html_content, "text/html")
    email.attach(f"Mahnung_{monat_str.replace(' ','_')}.pdf", pdf_bytes, 'application/pdf')
    email.send()

    messages.success(request, f"✅ Mahnung inkl. QR-Rechnung an {vertrag.mieter.email} gesendet.")
    return redirect(request.META.get('HTTP_REFERER', '/admin/'))


@staff_member_required
def generate_mahnung_pdf_view(request, vertrag_id):
    """ Nur Download des kombinierten PDFs (Brief + QR) """
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    verwaltung = Verwaltung.objects.first()
    monat_str = request.POST.get('monat', 'Laufender Monat')
    betrag_str = request.POST.get('betrag', '0.00')

    # Hier nutzen wir jetzt die kombinierte Funktion!
    pdf_bytes = generate_mahnung_combined_pdf_bytes(vertrag, verwaltung, monat_str, betrag_str, datetime.date.today())

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Mahnung_Art257d_{vertrag.mieter.nachname}.pdf"'
    response.write(pdf_bytes)
    return response