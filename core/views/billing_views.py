import io
import datetime
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

from core.models import AbrechnungsPeriode, Verwaltung, Mietvertrag
from core.utils.billing import berechne_abrechnung
from core.utils.qr_code import draw_qr_bill

@staff_member_required
def abrechnung_pdf_view(request, periode_id):
    """
    Generiert ein PDF mit allen Abrechnungen für diese Periode.
    Inklusive QR-Einzahlungsschein bei Nachzahlung.
    """
    periode = get_object_or_404(AbrechnungsPeriode, pk=periode_id)
    liegenschaft = periode.liegenschaft  # WICHTIG: Hier holen wir die Liegenschaft

    # 1. Berechnung durchführen
    ergebnis = berechne_abrechnung(periode_id)

    if 'error' in ergebnis:
        return HttpResponse(f"Fehler in Berechnung: {ergebnis['error']}")

    abrechnungen = ergebnis['abrechnungen']
    verwaltung = Verwaltung.objects.first()

    # 2. Validierung: IBAN prüfen (Liegenschaft!)
    # Wir prüfen hier die Liegenschaft, da dort das Konto hinterlegt ist
    if not liegenschaft.iban:
        return HttpResponse(f"Fehler: Für die Liegenschaft '{liegenschaft}' ist keine IBAN hinterlegt. Bitte im Admin nachtragen.", status=400)

    # 3. Creditor (Empfänger) vorbereiten
    # Wenn ein Mandant existiert, nehmen wir ihn als Empfänger, sonst die Verwaltung
    mandant = liegenschaft.mandant

    if mandant:
        creditor_name = mandant.firma_oder_name
        creditor_line1 = mandant.strasse
        creditor_line2 = f"{mandant.plz} {mandant.ort}"
    elif verwaltung:
        creditor_name = verwaltung.firma
        creditor_line1 = verwaltung.strasse
        creditor_line2 = f"{verwaltung.plz} {verwaltung.ort}"
    else:
        # Fallback, falls gar nichts da ist (sollte nicht passieren)
        creditor_name = "Immobilienverwaltung"
        creditor_line1 = liegenschaft.strasse
        creditor_line2 = f"{liegenschaft.plz} {liegenschaft.ort}"

    creditor = {
        'name': creditor_name,
        'line1': creditor_line1,
        'line2': creditor_line2
    }

    # 4. PDF Starten
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"NK-Abrechnung {periode.bezeichnung}")

    for row in abrechnungen:
        # Mieter Adresse laden
        try:
            vertrag = Mietvertrag.objects.get(pk=row['vertrag_id'])
            debtor = {
                'name': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}",
                'line1': vertrag.mieter.strasse,
                'line2': f"{vertrag.mieter.plz} {vertrag.mieter.ort}"
            }
        except:
            debtor = {'name': row['mieter'], 'line1': '', 'line2': ''}

        # --- SEITE 1: Abrechnung ---
        draw_header(c, verwaltung)

        # Empfänger Adresse
        c.setFont("Helvetica", 12)
        c.drawString(20*mm, 240*mm, debtor['name'])
        c.drawString(20*mm, 235*mm, debtor['line1'])
        c.drawString(20*mm, 230*mm, debtor['line2'])

        # Titel & Infos
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20*mm, 200*mm, f"Nebenkostenabrechnung: {periode.bezeichnung}")

        c.setFont("Helvetica", 10)
        c.drawString(20*mm, 190*mm, f"Objekt: {row['einheit']}")
        c.drawString(20*mm, 185*mm, f"Zeitraum: {periode.start_datum.strftime('%d.%m.%Y')} bis {periode.ende_datum.strftime('%d.%m.%Y')}")

        # Tabelle Kosten
        y = 160*mm
        c.line(20*mm, y, 180*mm, y)
        y -= 6*mm
        c.drawString(20*mm, y, f"Kostenanteil ({row['anteil_m2']} m²)")
        c.drawRightString(180*mm, y, f"{row['kosten_anteil']:.2f}")
        y -= 6*mm
        c.drawString(20*mm, y, "Akonto Zahlungen")
        c.drawRightString(180*mm, y, f"- {row['akonto_bezahlt']:.2f}")
        y -= 10*mm
        c.line(20*mm, y, 180*mm, y)
        y -= 10*mm

        # Saldo Box
        betrag = abs(row['saldo'])
        if row['nachzahlung']:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(20*mm, y, "Nachzahlung zu Ihren Lasten:")
            c.drawRightString(180*mm, y, f"CHF {betrag:.2f}")
            c.setFont("Helvetica", 10)
            c.drawString(20*mm, y-10*mm, "Bitte verwenden Sie den beiliegenden Einzahlungsschein.")
        else:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(20*mm, y, "Guthaben zu Ihren Gunsten:")
            c.drawRightString(180*mm, y, f"CHF {betrag:.2f}")
            c.setFont("Helvetica", 10)
            c.drawString(20*mm, y-10*mm, "Der Betrag wird Ihnen in den nächsten Tagen überwiesen.")

        c.showPage() # Ende Seite 1

        # --- SEITE 2: QR Code (nur bei Nachzahlung) ---
        if row['nachzahlung']:
            # Hier nutzen wir jetzt liegenschaft.iban !
            draw_qr_bill(
                c,
                liegenschaft.iban,  # <-- KORRIGIERT
                creditor,
                debtor,
                betrag,
                f"NK {periode.bezeichnung}"
            )
            c.showPage()

    c.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Abrechnung_{periode.bezeichnung}.pdf"'
    return response

def draw_header(c, verwaltung):
    """Zeichnet Briefkopf der Verwaltung"""
    if not verwaltung: return
    if verwaltung.logo:
        try:
            c.drawImage(verwaltung.logo.path, 160*mm, 270*mm, width=35*mm, preserveAspectRatio=True, mask='auto')
        except: pass
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, 280*mm, verwaltung.firma)
    c.setFont("Helvetica", 9)
    c.drawString(20*mm, 275*mm, f"{verwaltung.strasse}, {verwaltung.plz} {verwaltung.ort}")