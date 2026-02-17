import io
from django.core.mail import EmailMessage
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings

# ReportLab (PDF)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

# Eigene Imports
from core.models import AbrechnungsPeriode, Verwaltung, Mietvertrag
from core.utils.billing import berechne_abrechnung
from core.utils.qr_code import draw_qr_bill

# --- HILFSFUNKTION: PDF GENERIEREN (Nur Bytes, kein HTTP Response) ---
def generate_single_pdf_bytes(periode, row, verwaltung, liegenschaft):
    """Erzeugt das PDF für einen einzelnen Mieter im Speicher"""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"NK-Abrechnung {row['mieter']}")

    # Daten laden
    try:
        vertrag = Mietvertrag.objects.get(pk=row['vertrag_id'])
        debtor = {
            'name': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}",
            'line1': vertrag.mieter.strasse,
            'line2': f"{vertrag.mieter.plz} {vertrag.mieter.ort}"
        }
    except:
        debtor = {'name': row['mieter'], 'line1': '', 'line2': ''}

    # Creditor (Empfänger)
    mandant = liegenschaft.mandant
    creditor_name = mandant.firma_oder_name if mandant else verwaltung.firma
    creditor = {
        'name': creditor_name,
        'line1': mandant.strasse if mandant else verwaltung.strasse,
        'line2': f"{mandant.plz} {mandant.ort}" if mandant else f"{verwaltung.plz} {verwaltung.ort}"
    }

    # --- SEITE 1 ---
    draw_header(c, verwaltung)

    # Adressfeld
    c.setFont("Helvetica", 12)
    c.drawString(20*mm, 240*mm, debtor['name'])
    c.drawString(20*mm, 235*mm, debtor['line1'])
    c.drawString(20*mm, 230*mm, debtor['line2'])

    # Titel
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20*mm, 200*mm, f"Nebenkostenabrechnung: {periode.bezeichnung}")

    c.setFont("Helvetica", 10)
    c.drawString(20*mm, 190*mm, f"Objekt: {row['einheit']}")
    c.drawString(20*mm, 185*mm, f"Zeitraum: {periode.start_datum.strftime('%d.%m.%Y')} bis {periode.ende_datum.strftime('%d.%m.%Y')}")

    # Tabelle
    y = 160*mm
    c.line(20*mm, y, 180*mm, y); y -= 6*mm
    c.drawString(20*mm, y, f"Kostenanteil ({row['anteil_m2']} m²)")
    c.drawRightString(180*mm, y, f"{row['kosten_anteil']:.2f}"); y -= 6*mm
    c.drawString(20*mm, y, "Akonto Zahlungen")
    c.drawRightString(180*mm, y, f"- {row['akonto_bezahlt']:.2f}"); y -= 10*mm
    c.line(20*mm, y, 180*mm, y); y -= 10*mm

    # Saldo
    betrag = abs(row['saldo'])
    if row['nachzahlung']:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(20*mm, y, "Nachzahlung zu Ihren Lasten:")
        c.drawRightString(180*mm, y, f"CHF {betrag:.2f}")
    else:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(20*mm, y, "Guthaben zu Ihren Gunsten:")
        c.drawRightString(180*mm, y, f"CHF {betrag:.2f}")

    c.showPage()

    # --- SEITE 2: QR (Nur bei Nachzahlung) ---
    if row['nachzahlung'] and liegenschaft.iban:
        draw_qr_bill(c, liegenschaft.iban, creditor, debtor, betrag, f"NK {periode.bezeichnung}")
        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer.getvalue()

def draw_header(c, verwaltung):
    if not verwaltung: return
    if verwaltung.logo:
        try:
            c.drawImage(verwaltung.logo.path, 160*mm, 270*mm, width=35*mm, preserveAspectRatio=True, mask='auto')
        except: pass
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, 280*mm, verwaltung.firma)
    c.setFont("Helvetica", 9)
    c.drawString(20*mm, 275*mm, f"{verwaltung.strasse}, {verwaltung.plz} {verwaltung.ort}")


# --- HAUPTFUNKTION: SENDEN ---
@staff_member_required
def send_abrechnung_email_view(request, periode_id):
    periode = get_object_or_404(AbrechnungsPeriode, pk=periode_id)
    liegenschaft = periode.liegenschaft
    verwaltung = Verwaltung.objects.first()

    # Berechnung
    ergebnis = berechne_abrechnung(periode_id)
    if 'error' in ergebnis:
        messages.error(request, f"Fehler bei Berechnung: {ergebnis['error']}")
        return redirect(f'/admin/core/abrechnungsperiode/{periode_id}/change/')

    abrechnungen = ergebnis['abrechnungen']

    emails_sent = 0
    missing_email = 0

    for row in abrechnungen:
        try:
            vertrag = Mietvertrag.objects.get(pk=row['vertrag_id'])
            mieter_email = vertrag.mieter.email

            if not mieter_email:
                missing_email += 1
                continue

            # 1. PDF generieren
            pdf_bytes = generate_single_pdf_bytes(periode, row, verwaltung, liegenschaft)
            filename = f"Abrechnung_{periode.bezeichnung}_{vertrag.mieter.nachname}.pdf"

            # 2. E-Mail bauen
            subject = f"Nebenkostenabrechnung: {periode.bezeichnung}"

            body = f"""Guten Tag {vertrag.mieter.anrede} {vertrag.mieter.nachname}

Anbei erhalten Sie Ihre Nebenkostenabrechnung für die Periode "{periode.bezeichnung}".
{ "Bitte beachten Sie die Nachzahlung auf Seite 2." if row['nachzahlung'] else "Das Guthaben wird Ihnen überwiesen." }

Freundliche Grüsse
{verwaltung.firma}
"""
            email = EmailMessage(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [mieter_email],
            )

            # 3. PDF anhängen und senden
            email.attach(filename, pdf_bytes, 'application/pdf')
            email.send(fail_silently=False)

            emails_sent += 1

        except Exception as e:
            messages.warning(request, f"Fehler bei {row['mieter']}: {e}")

    # Abschlussbericht
    if emails_sent > 0:
        messages.success(request, f"✅ Erfolgreich versendet: {emails_sent} E-Mails.")

    if missing_email > 0:
        messages.warning(request, f"⚠️ Nicht gesendet: {missing_email} Mieter haben keine E-Mail-Adresse hinterlegt.")

    return redirect(f'/admin/core/abrechnungsperiode/{periode_id}/change/')