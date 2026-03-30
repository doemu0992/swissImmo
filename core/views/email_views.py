import io
import datetime
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

# --- HILFSFUNKTION: PDF GENERIEREN (im Speicher) ---
def generate_single_pdf_bytes(periode, row, verwaltung, liegenschaft, vertrag):
    """
    Erzeugt das PDF für einen einzelnen Mieter im Speicher (für E-Mail Anhang).
    Nutzt das gleiche Layout wie die Haupt-Abrechnung.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"NK-Abrechnung {row['name']}")

    # Absender / Creditor
    if verwaltung:
        creditor = {
            'name': verwaltung.firma,
            'line1': verwaltung.strasse,
            'line2': f"{verwaltung.plz} {verwaltung.ort}",
        }
    else:
        creditor = {
            'name': "Immobilienverwaltung",
            'line1': liegenschaft.strasse,
            'line2': f"{liegenschaft.plz} {liegenschaft.ort}"
        }

    # Empfänger / Debtor
    if vertrag:
        debtor = {
            'name': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}",
            'line1': vertrag.mieter.strasse,
            'line2': f"{vertrag.mieter.plz} {vertrag.mieter.ort}"
        }
    else:
        # Fallback falls kein Vertrag gefunden (z.B. Leerstand)
        debtor = {'name': row['name'], 'line1': '', 'line2': ''}

    # --- SEITE 1 ---
    draw_header(c, verwaltung)

    # Adressfeld
    c.setFont("Helvetica", 11)
    c.drawString(25*mm, 245*mm, debtor['name'])
    c.drawString(25*mm, 240*mm, debtor['line1'])
    c.drawString(25*mm, 235*mm, debtor['line2'])

    # Datum & Ort
    c.setFont("Helvetica", 10)
    c.drawRightString(190*mm, 245*mm, f"Datum: {datetime.date.today().strftime('%d.%m.%Y')}")
    c.drawRightString(190*mm, 240*mm, f"Liegenschaft: {liegenschaft.ort}")

    # Titel
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20*mm, 210*mm, f"Nebenkostenabrechnung: {periode.bezeichnung}")

    c.setFont("Helvetica", 10)
    c.drawString(20*mm, 200*mm, f"Objekt: {row['einheit']}")
    c.drawString(20*mm, 195*mm, f"Zeitraum: {periode.start_datum.strftime('%d.%m.%Y')} bis {periode.ende_datum.strftime('%d.%m.%Y')}")

    # Tabelle Header
    y = 170*mm
    c.setFillColorRGB(0.9, 0.9, 0.9)
    c.rect(20*mm, y-2*mm, 170*mm, 8*mm, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(25*mm, y, "Beschreibung")
    c.drawRightString(185*mm, y, "Betrag (CHF)")

    y -= 10*mm
    c.setFont("Helvetica", 10)

    # 1. Kosten
    c.drawString(25*mm, y, f"Kostenanteil")
    c.drawRightString(185*mm, y, f"{row['kosten_anteil']:.2f}")
    y -= 6*mm

    # 2. Akonto (WICHTIG: heisst jetzt 'akonto', nicht 'akonto_bezahlt')
    akonto = row.get('akonto', 0)
    if akonto > 0:
        c.drawString(25*mm, y, "Abzüglich Akonto Zahlungen")
        c.drawRightString(185*mm, y, f"- {akonto:.2f}")
        y -= 8*mm

    c.line(20*mm, y, 190*mm, y)
    y -= 8*mm

    # Saldo
    betrag = abs(row['saldo'])
    c.setFont("Helvetica-Bold", 12)
    if row['nachzahlung']:
        c.drawString(25*mm, y, "Nachzahlung zu Ihren Lasten:")
        c.drawRightString(185*mm, y, f"CHF {betrag:.2f}")
    else:
        c.drawString(25*mm, y, "Guthaben zu Ihren Gunsten:")
        c.drawRightString(185*mm, y, f"CHF {betrag:.2f}")

    c.showPage()

    # --- SEITE 2: QR (Nur bei Nachzahlung & vorhandener IBAN) ---
    if row['nachzahlung'] and liegenschaft.iban:
        try:
            draw_qr_bill(c, liegenschaft.iban, creditor, debtor, betrag, f"NK {periode.bezeichnung}")
            c.showPage()
        except: pass

    c.save()
    buffer.seek(0)
    return buffer.getvalue()

def draw_header(c, verwaltung):
    if not verwaltung: return
    if verwaltung.logo:
        try:
            c.drawImage(verwaltung.logo.path, 20*mm, 270*mm, height=15*mm, preserveAspectRatio=True, mask='auto')
        except: pass
    c.setFont("Helvetica", 8)
    c.drawRightString(190*mm, 280*mm, f"{verwaltung.firma} | {verwaltung.strasse} | {verwaltung.plz} {verwaltung.ort}")


# --- HAUPTFUNKTION: SENDEN ---
@staff_member_required
def send_abrechnung_email_view(request, periode_id):
    periode = get_object_or_404(AbrechnungsPeriode, pk=periode_id)
    liegenschaft = periode.liegenschaft
    verwaltung = Verwaltung.objects.first()

    # Berechnung durchführen
    ergebnis = berechne_abrechnung(periode_id)
    if 'error' in ergebnis:
        messages.error(request, f"Fehler bei Berechnung: {ergebnis['error']}")
        return redirect(request.META.get('HTTP_REFERER', '/admin/'))

    abrechnungen = ergebnis['abrechnungen']
    emails_sent = 0
    missing_email = 0

    # Alle Verträge der Liegenschaft vorladen für die Suche
    alle_vertraege = Mietvertrag.objects.filter(einheit__liegenschaft=liegenschaft).select_related('mieter', 'einheit')

    for row in abrechnungen:
        if row['typ'] == 'leerstand':
            continue # Leerstand bekommt keine Mail

        # --- VERTRAG FINDEN (Workaround für fehlende ID in billing.py) ---
        vertrag = None
        for v in alle_vertraege:
            # Wir vergleichen den Namen und die Einheit
            full_name = f"{v.mieter.vorname} {v.mieter.nachname}"
            if full_name == row['name'] and v.einheit.bezeichnung == row['einheit']:
                vertrag = v
                break

        if not vertrag or not vertrag.mieter.email:
            missing_email += 1
            continue

        try:
            # 1. PDF generieren
            pdf_bytes = generate_single_pdf_bytes(periode, row, verwaltung, liegenschaft, vertrag)
            filename = f"Abrechnung_{periode.bezeichnung}.pdf"

            # 2. E-Mail Text
            salutation = "Guten Tag"
            if vertrag.mieter.anrede == "Herr": salutation = f"Sehr geehrter Herr {vertrag.mieter.nachname}"
            elif vertrag.mieter.anrede == "Frau": salutation = f"Sehr geehrte Frau {vertrag.mieter.nachname}"
            else: salutation = f"Guten Tag {vertrag.mieter.vorname} {vertrag.mieter.nachname}"

            info_text = "Bitte beachten Sie die Nachzahlung auf der zweiten Seite." if row['nachzahlung'] else "Das Guthaben wird Ihnen in den nächsten Tagen gutgeschrieben."

            body = f"""{salutation}

Anbei erhalten Sie Ihre Nebenkostenabrechnung für die Periode "{periode.bezeichnung}".
{info_text}

Bei Fragen stehen wir Ihnen gerne zur Verfügung.

Freundliche Grüsse
{verwaltung.firma}
"""
            # 3. Senden
            email = EmailMessage(
                subject=f"Nebenkostenabrechnung: {periode.bezeichnung}",
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[vertrag.mieter.email],
            )
            email.attach(filename, pdf_bytes, 'application/pdf')
            email.send(fail_silently=False)

            emails_sent += 1

        except Exception as e:
            messages.warning(request, f"Fehler bei {row['name']}: {e}")

    # Abschlussbericht
    if emails_sent > 0:
        messages.success(request, f"✅ {emails_sent} E-Mails erfolgreich versendet.")

    if missing_email > 0:
        messages.warning(request, f"⚠️ Bei {missing_email} Mietern wurde keine E-Mail gesendet (E-Mail fehlt oder Vertrag nicht gefunden).")

    return redirect(request.META.get('HTTP_REFERER', '/admin/'))