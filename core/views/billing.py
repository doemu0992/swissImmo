from crm.models import Verwaltung, Mieter
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag, Leerstand
from finance.models import AbrechnungsPeriode

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

from core.utils.billing import berechne_abrechnung
from core.utils.qr_code import draw_qr_bill

# ==========================================
# 1. QR RECHNUNG FÜR MIETZINS
# ==========================================

def format_iban(iban):
    if not iban: return ""
    iban = iban.replace(" ", "")
    return " ".join(iban[i:i+4] for i in range(0, len(iban), 4))

def draw_cross(c, x, y):
    c.setFillColorRGB(0, 0, 0)
    c.rect(x - 3.5*mm, y - 3.5*mm, 7*mm, 7*mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    bar_width = 1.1 * mm
    bar_length = 3.8 * mm
    c.rect(x - bar_width/2, y - bar_length/2, bar_width, bar_length, fill=1, stroke=0)
    c.rect(x - bar_length/2, y - bar_width/2, bar_length, bar_width, fill=1, stroke=0)

@staff_member_required
def qr_rechnung_pdf(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    mieter = vertrag.mieter
    mandant = liegenschaft.mandant
    verwaltung = Verwaltung.objects.first()

    errors = []
    if not liegenschaft.iban: errors.append(f"Liegenschaft hat keine IBAN.")
    if not mieter.strasse or not mieter.plz or not mieter.ort: errors.append(f"Mieter Adresse unvollständig.")
    if errors: return HttpResponse(f"Fehler:<br>- " + "<br>- ".join(errors), status=400)

    raw_iban = liegenschaft.iban.replace(" ", "")
    formatted_iban = format_iban(raw_iban)
    total_betrag = vertrag.netto_mietzins + vertrag.nebenkosten

    creditor_name = mandant.firma_oder_name if mandant else "Immobilienverwaltung"
    creditor_line1 = liegenschaft.strasse
    creditor_line2 = f"{liegenschaft.plz} {liegenschaft.ort}"

    debtor_name = f"{mieter.vorname} {mieter.nachname}"
    debtor_line1 = mieter.strasse
    debtor_line2 = f"{mieter.plz} {mieter.ort}"

    monat_jahr = request.GET.get('monat', datetime.date.today().strftime('%m/%Y'))
    mitteilung = f"Miete {monat_jahr} - {einheit.bezeichnung}"

    qr_data = "\n".join([
        "SPC", "0200", "1", raw_iban,
        "K", creditor_name, creditor_line1, creditor_line2, "", "", "CH",
        "", "", "", "", "", "", "", f"{total_betrag:.2f}", "CHF",
        "K", debtor_name, debtor_line1, debtor_line2, "", "", "CH",
        "NON", "", mitteilung, "EPD", ""
    ])

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"Mietrechnung {monat_jahr}")

    if verwaltung and verwaltung.logo:
        try: c.drawImage(verwaltung.logo.path, 150*mm, 265*mm, width=40*mm, preserveAspectRatio=True, mask='auto')
        except: pass

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20*mm, 270*mm, "Mietrechnung")
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.darkgrey)
    c.drawString(20*mm, 264*mm, f"Monat: {monat_jahr}")
    c.setStrokeColor(colors.lightgrey)
    c.line(20*mm, 258*mm, 190*mm, 258*mm)

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    y_start = 245*mm
    c.drawString(20*mm, y_start, "Rechnungsempfänger:")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20*mm, y_start - 6*mm, debtor_name)
    c.setFont("Helvetica", 11)
    c.drawString(20*mm, y_start - 11*mm, debtor_line1)
    c.drawString(20*mm, y_start - 16*mm, debtor_line2)

    c.setFont("Helvetica", 9)
    c.drawString(110*mm, y_start, "Objekt / Details:")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(110*mm, y_start - 6*mm, f"{einheit.liegenschaft.strasse}")
    c.drawString(110*mm, y_start - 11*mm, f"{einheit.bezeichnung}")

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

    c.setDash(1, 4)
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.line(0, 105*mm, 210*mm, 105*mm)
    c.setDash([])
    c.setFillColor(colors.black)
    c.setFont("ZapfDingbats", 10)
    c.drawString(10*mm, 107*mm, "✂")

    c.setFont("Helvetica-Bold", 11)
    c.drawString(67*mm, 95*mm, "Zahlteil")
    c.drawString(5*mm, 95*mm, "Empfangsschein")

    qr = segno.make(qr_data, error='M')
    qr_img = io.BytesIO()
    qr.save(qr_img, kind='png', scale=4)
    qr_img.seek(0)
    c.drawImage(reportlab.lib.utils.ImageReader(qr_img), 67*mm, 42*mm, width=46*mm, height=46*mm)
    draw_cross(c, 67*mm + 23*mm, 42*mm + 23*mm)

    def draw_details(x, is_receipt=False):
        c.setFillColor(colors.black)
        y = 90*mm
        lh = 3.5*mm
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

    draw_details(5*mm, is_receipt=True)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8); c.drawString(5*mm, 15*mm, "Währung"); c.drawString(18*mm, 15*mm, "Betrag")
    c.setFont("Helvetica", 10); c.drawString(5*mm, 10*mm, "CHF"); c.drawString(18*mm, 10*mm, f"{total_betrag:,.2f}")

    draw_details(118*mm, is_receipt=False)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8); c.drawString(67*mm, 15*mm, "Währung"); c.drawString(82*mm, 15*mm, "Betrag")
    c.setFont("Helvetica", 10); c.drawString(67*mm, 10*mm, "CHF"); c.drawString(82*mm, 10*mm, f"{total_betrag:,.2f}")
    c.setFont("Helvetica-Bold", 7); c.drawString(118*mm, 35*mm, "Zusätzliche Informationen")
    c.setFont("Helvetica", 7); c.drawString(118*mm, 32*mm, mitteilung)

    c.showPage()
    c.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f"QR_Rechnung_{mieter.nachname}_{monat_jahr.replace('/', '-')}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


# ==========================================
# 2. NEBENKOSTEN ABRECHNUNG
# ==========================================

def draw_header(c, verwaltung):
    if not verwaltung: return
    if verwaltung.logo:
        try: c.drawImage(verwaltung.logo.path, 20*mm, 270*mm, height=15*mm, preserveAspectRatio=True, mask='auto')
        except: pass
    c.setFont("Helvetica", 8)
    c.drawRightString(190*mm, 280*mm, f"{verwaltung.firma} | {verwaltung.strasse} | {verwaltung.plz} {verwaltung.ort}")

@staff_member_required
def abrechnung_pdf_view(request, periode_id):
    periode = get_object_or_404(AbrechnungsPeriode, pk=periode_id)
    liegenschaft = periode.liegenschaft
    ergebnis = berechne_abrechnung(periode_id)

    if 'error' in ergebnis:
        return HttpResponse(f"Fehler: {ergebnis['error']}")

    abrechnungen = ergebnis.get('abrechnungen', [])
    verwaltung = Verwaltung.objects.first()
    mandant = liegenschaft.mandant

    if not liegenschaft.iban:
        return HttpResponse("Fehler: Keine IBAN bei der Liegenschaft hinterlegt!", status=400)

    if verwaltung:
        creditor = {'name': verwaltung.firma, 'line1': verwaltung.strasse, 'line2': f"{verwaltung.plz} {verwaltung.ort}"}
    else:
        creditor = {'name': "Immobilienverwaltung", 'line1': liegenschaft.strasse, 'line2': f"{liegenschaft.plz} {liegenschaft.ort}"}

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"NK {periode.bezeichnung}")

    for row in abrechnungen:
        if row['typ'] == 'leerstand':
            if mandant: debtor = {'name': mandant.firma_oder_name, 'line1': mandant.strasse, 'line2': f"{mandant.plz} {mandant.ort}"}
            else: debtor = {'name': "Eigentümer (Leerstand)", 'line1': '', 'line2': ''}
        else:
            debtor = {'name': row['name'], 'line1': liegenschaft.strasse, 'line2': f"{liegenschaft.plz} {liegenschaft.ort}"}

        draw_header(c, verwaltung)
        c.setFont("Helvetica", 11)
        c.drawString(25*mm, 245*mm, debtor['name'])
        c.drawString(25*mm, 240*mm, debtor['line1'])
        c.drawString(25*mm, 235*mm, debtor['line2'])

        c.setFont("Helvetica", 10)
        c.drawRightString(190*mm, 245*mm, f"Datum: {datetime.date.today().strftime('%d.%m.%Y')}")
        c.drawRightString(190*mm, 240*mm, f"Liegenschaft: {liegenschaft.ort}")

        c.setFont("Helvetica-Bold", 14)
        c.drawString(20*mm, 210*mm, f"Nebenkostenabrechnung: {periode.bezeichnung}")

        c.setFont("Helvetica", 10)
        c.drawString(20*mm, 200*mm, f"Objekt: {row['einheit']}")
        c.drawString(20*mm, 195*mm, f"Abrechnungsperiode: {periode.start_datum.strftime('%d.%m.%Y')} bis {periode.ende_datum.strftime('%d.%m.%Y')}")

        if row.get('tage'): c.drawString(20*mm, 190*mm, f"Ihre Mietdauer: {row.get('tage')} Tage")

        y = 170*mm
        c.setFillColorRGB(0.9, 0.9, 0.9)
        c.rect(20*mm, y-2*mm, 170*mm, 8*mm, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(25*mm, y, "Beschreibung")
        c.drawRightString(185*mm, y, "Betrag (CHF)")

        y -= 10*mm
        c.setFont("Helvetica", 10)
        c.drawString(25*mm, y, f"Ihr Anteil an den Gesamtkosten ({periode.bezeichnung})")
        c.drawRightString(185*mm, y, f"{row['kosten_anteil']:.2f}")
        y -= 6*mm

        if row['akonto'] > 0:
            c.drawString(25*mm, y, "Abzüglich Ihre Akontozahlungen")
            c.drawRightString(185*mm, y, f"- {row['akonto']:.2f}")
            y -= 8*mm

        c.line(20*mm, y, 190*mm, y)
        y -= 8*mm

        saldo = row['saldo']
        betrag_abs = abs(saldo)

        c.setFont("Helvetica-Bold", 12)
        if row['nachzahlung']:
            c.drawString(25*mm, y, "Nachzahlung zu Ihren Lasten:")
            text_info = "Bitte begleichen Sie den Betrag innert 30 Tagen."
        else:
            c.drawString(25*mm, y, "Guthaben zu Ihren Gunsten:")
            text_info = "Das Guthaben wird auf Ihr Konto überwiesen."

        c.drawRightString(185*mm, y, f"CHF {betrag_abs:.2f}")
        y -= 10*mm
        c.setFont("Helvetica", 10)
        c.drawString(25*mm, y, text_info)

        c.showPage()

        if row['nachzahlung'] and liegenschaft.iban:
            try:
                draw_qr_bill(c, liegenschaft.iban, creditor, debtor, betrag_abs, f"NK {periode.bezeichnung} - {row['einheit']}")
                c.showPage()
            except Exception as e:
                print(f"QR Error: {e}")

    c.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Abrechnung_{periode.bezeichnung}.pdf"'
    return response