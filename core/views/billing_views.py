from crm.models import Verwaltung, Mieter
from portfolio.models import Liegenschaft
from rentals.models import Leerstand
from finance.models import AbrechnungsPeriode

import io
import datetime  # <--- DIESE ZEILE HAT GEFEHLT
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

from core.utils.billing import berechne_abrechnung
from core.utils.qr_code import draw_qr_bill

@staff_member_required
def abrechnung_pdf_view(request, periode_id):
    """
    Generiert ein PDF mit allen Abrechnungen.
    Kompatibel mit der neuen Smart-Berechnungs-Logik.
    """
    periode = get_object_or_404(AbrechnungsPeriode, pk=periode_id)
    liegenschaft = periode.liegenschaft

    # 1. Daten berechnen
    ergebnis = berechne_abrechnung(periode_id)

    if 'error' in ergebnis:
        return HttpResponse(f"Fehler: {ergebnis['error']}")

    abrechnungen = ergebnis.get('abrechnungen', [])
    verwaltung = Verwaltung.objects.first()
    mandant = liegenschaft.mandant

    # 2. Validierung
    if not liegenschaft.iban:
        return HttpResponse("Fehler: Keine IBAN bei der Liegenschaft hinterlegt!", status=400)

    # 3. Absender (Creditor) definieren
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

    # 4. PDF Starten
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"NK {periode.bezeichnung}")

    for row in abrechnungen:
        # --- EMPFÄNGER ERMITTELN ---
        if row['typ'] == 'leerstand':
            # Leerstandskosten gehen an den Eigentümer
            if mandant:
                debtor = {
                    'name': mandant.firma_oder_name,
                    'line1': mandant.strasse,
                    'line2': f"{mandant.plz} {mandant.ort}"
                }
            else:
                debtor = {'name': "Eigentümer (Leerstand)", 'line1': '', 'line2': ''}
        else:
            # Mieter wohnt in der Liegenschaft
            debtor = {
                'name': row['name'],
                'line1': liegenschaft.strasse,
                'line2': f"{liegenschaft.plz} {liegenschaft.ort}"
            }

        # --- SEITE 1: Abrechnung ---
        draw_header(c, verwaltung)

        # Adressfeld (DIN 5008 ähnlich)
        c.setFont("Helvetica", 11)
        c.drawString(25*mm, 245*mm, debtor['name'])
        c.drawString(25*mm, 240*mm, debtor['line1'])
        c.drawString(25*mm, 235*mm, debtor['line2'])

        # Info-Block rechts (HIER GAB ES DEN FEHLER)
        c.setFont("Helvetica", 10)
        c.drawRightString(190*mm, 245*mm, f"Datum: {datetime.date.today().strftime('%d.%m.%Y')}")
        c.drawRightString(190*mm, 240*mm, f"Liegenschaft: {liegenschaft.ort}")

        # Titel
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20*mm, 210*mm, f"Nebenkostenabrechnung: {periode.bezeichnung}")

        c.setFont("Helvetica", 10)
        c.drawString(20*mm, 200*mm, f"Objekt: {row['einheit']}")
        c.drawString(20*mm, 195*mm, f"Abrechnungsperiode: {periode.start_datum.strftime('%d.%m.%Y')} bis {periode.ende_datum.strftime('%d.%m.%Y')}")

        if row.get('tage'):
            c.drawString(20*mm, 190*mm, f"Ihre Mietdauer: {row.get('tage')} Tage")

        # --- TABELLE ---
        y = 170*mm

        # Header
        c.setFillColorRGB(0.9, 0.9, 0.9)
        c.rect(20*mm, y-2*mm, 170*mm, 8*mm, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(25*mm, y, "Beschreibung")
        c.drawRightString(185*mm, y, "Betrag (CHF)")

        y -= 10*mm
        c.setFont("Helvetica", 10)

        # 1. Kostenanteil
        c.drawString(25*mm, y, f"Ihr Anteil an den Gesamtkosten ({periode.bezeichnung})")
        c.drawRightString(185*mm, y, f"{row['kosten_anteil']:.2f}")
        y -= 6*mm

        # 2. Akonto
        if row['akonto'] > 0:
            c.drawString(25*mm, y, "Abzüglich Ihre Akontozahlungen")
            c.drawRightString(185*mm, y, f"- {row['akonto']:.2f}")
            y -= 8*mm

        # Linie
        c.line(20*mm, y, 190*mm, y)
        y -= 8*mm

        # --- SALDO ---
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

        c.showPage() # Seite 1 fertig

        # --- SEITE 2: QR-Rechnung (Nur bei Nachzahlung) ---
        if row['nachzahlung'] and liegenschaft.iban:
            try:
                # Prüfen ob wir die nötigen Daten für QR haben
                draw_qr_bill(
                    c,
                    liegenschaft.iban,
                    creditor,
                    debtor,
                    betrag_abs,
                    f"NK {periode.bezeichnung} - {row['einheit']}"
                )
                c.showPage()
            except Exception as e:
                print(f"QR Error: {e}")
                # Falls QR fehlschlägt, machen wir einfach weiter

    c.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Abrechnung_{periode.bezeichnung}.pdf"'
    return response

def draw_header(c, verwaltung):
    if not verwaltung: return
    # Optional Logo
    if verwaltung.logo:
        try:
            c.drawImage(verwaltung.logo.path, 20*mm, 270*mm, height=15*mm, preserveAspectRatio=True, mask='auto')
        except: pass

    # Absenderzeile klein
    c.setFont("Helvetica", 8)
    c.drawRightString(190*mm, 280*mm, f"{verwaltung.firma} | {verwaltung.strasse} | {verwaltung.plz} {verwaltung.ort}")
