from crm.models import Verwaltung, Mandant, Mieter
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag, Leerstand
from finance.models import AbrechnungsPeriode

import os
import io
import tempfile
import datetime
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string, get_template
from django.db.models import Sum
from django.utils import timezone
from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.admin.views.decorators import staff_member_required
from xhtml2pdf import pisa

# Profi-Tools für den QR Code
import segno
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
import reportlab.lib.utils


try:
    from swiss_qr_bill import QRBill, Bill, Address
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

def link_callback(uri, rel):
    """
    Wandelt Pfade für xhtml2pdf um.
    Behebt 'SuspiciousFileOperation' indem absolute Systempfade direkt akzeptiert werden.
    """
    # 1. Ist es bereits ein absoluter Pfad auf der Festplatte? (z.B. Media-Uploads)
    if os.path.isfile(uri):
        return uri

    # 2. Ist es ein relativer Pfad? Dann Static Finder nutzen.
    if not uri.startswith('/') and not uri.startswith('http'):
        result = finders.find(uri)
        if result:
            if isinstance(result, (list, tuple)):
                result = result[0]
            return result

    # 3. Standard URL-Umwandlung (Static & Media)
    sUrl = settings.STATIC_URL
    sRoot = settings.STATIC_ROOT
    mUrl = settings.MEDIA_URL
    mRoot = settings.MEDIA_ROOT

    if uri.startswith(mUrl):
        path = os.path.join(mRoot, uri.replace(mUrl, ""))
    elif uri.startswith(sUrl):
        path = os.path.join(sRoot, uri.replace(sUrl, ""))
    else:
        return uri

    if not os.path.isfile(path):
        return None

    return path


# --- NEBENKOSTEN ABRECHNUNG ---
def abrechnung_pdf_view(request, pk):
    periode = get_object_or_404(AbrechnungsPeriode, pk=pk)
    liegenschaft = periode.liegenschaft
    einheiten = liegenschaft.einheiten.all()
    belege = periode.belege.all()
    gesamt_flaeche = einheiten.aggregate(Sum('flaeche_m2'))['flaeche_m2__sum'] or 1
    temp_dir = tempfile.gettempdir()
    abrechnungen = []

    for einheit in einheiten:
        mietvertrag = einheit.vertraege.filter(aktiv=True).first()
        mieter_name = str(mietvertrag.mieter) if mietvertrag else "Leerstand / Eigentümer"
        anteil_kosten = 0.0
        details = []
        for beleg in belege:
            if beleg.verteilschluessel == 'm2':
                anteil_faktor = float(einheit.flaeche_m2) / float(gesamt_flaeche)
                kosten = float(beleg.betrag) * anteil_faktor
                anteil_kosten += kosten
                details.append({
                    'kategorie': beleg.get_kategorie_display(),
                    'text': beleg.text,
                    'total': beleg.betrag,
                    'anteil': kosten
                })
        akonto = float(einheit.nebenkosten_aktuell) * 12
        saldo = akonto - anteil_kosten
        qr_data_uri = None

        if saldo < -0.05 and QR_AVAILABLE and liegenschaft.iban:
            try:
                creditor = Address(name="Verwaltung", line1=liegenschaft.strasse, line2=f"{liegenschaft.plz} {liegenschaft.ort}", country='CH')
                debtor = Address(name=mieter_name, line1=einheit.liegenschaft.strasse, line2=f"{einheit.liegenschaft.plz} {einheit.liegenschaft.ort}", country='CH')
                bill = Bill(account=liegenschaft.iban.replace(" ", ""), creditor=creditor, debtor=debtor, amount=abs(saldo), currency='CHF')
                canvas = QRBill.generate(bill)
                filename = f"qr_temp_{periode.id}_{einheit.id}.svg"
                full_path = os.path.join(temp_dir, filename)
                with open(full_path, 'wb') as f:
                    f.write(canvas.get_content().encode('utf-8') if isinstance(canvas.get_content(), str) else canvas.get_content())
                qr_data_uri = f"file://{full_path}"
            except Exception: pass

        abrechnungen.append({
            'einheit': einheit.bezeichnung,
            'mieter': mieter_name,
            'details': details,
            'total_kosten': round(anteil_kosten, 2),
            'akonto': akonto,
            'saldo': round(saldo, 2),
            'qr_data_uri': qr_data_uri
        })

    html_string = render_to_string('core/abrechnung_pdf.html', {'abrechnungen': abrechnungen, 'datum': timezone.now()})
    pdf_file = io.BytesIO()
    pisa.CreatePDF(html_string, dest=pdf_file, link_callback=link_callback)
    pdf_file.seek(0)
    response = HttpResponse(pdf_file.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'filename="NK_Abrechnung_{periode.pk}.pdf"'
    return response


# --- MIETVERTRAG GENERIEREN ---
def generate_pdf_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)

    # Objekte laden
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    mandant = liegenschaft.mandant  # Der Eigentümer

    # Formatierung
    netto = vertrag.netto_mietzins or 0
    nk = vertrag.nebenkosten or 0
    brutto = netto + nk
    kaution = vertrag.kautions_betrag or 0

    # Unterschrift Bild holen
    unterschrift_path = None
    if mandant and mandant.unterschrift_bild:
        try:
             unterschrift_path = mandant.unterschrift_bild.path
        except: pass

    if not unterschrift_path:
        dummy = finders.find("img/unterschrift_dummy.png")
        if dummy:
            unterschrift_path = dummy

    # TEMPLATE AUSWAHL
    if einheit.typ in ['pp', 'bas', 'gar']:
        template_name = 'core/mietvertrag_garage.html'
    else:
        template_name = 'core/mietvertrag_pdf.html'

    context = {
        'vertrag': vertrag,
        'mieter': vertrag.mieter,
        'einheit': einheit,
        'liegenschaft': liegenschaft,
        'mandant': mandant,        # WICHTIG: Das Mandant-Objekt für den Vermieter-Namen
        'heute': timezone.now().date(),
        'miete_fmt': f"{netto:.2f}",
        'nk_fmt': f"{nk:.2f}",
        'brutto_fmt': f"{brutto:.2f}",
        'kaution_fmt': f"{kaution:.2f}",
        'unterschrift_path': unterschrift_path,
    }

    template = get_template(template_name)
    html = template.render(context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Mietvertrag_{vertrag.id}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)

    if pisa_status.err:
        return HttpResponse(f'Fehler beim Erstellen des PDFs: {pisa_status.err}', status=500)

    return response


# =====================================================================
# QR RECHNUNG GENERIEREN (REPORTLAB + SEGNO)
# =====================================================================

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
    Erstellt eine professionelle QR-Rechnung mit wählbarem Monat.
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

    # --- NEU: Den Monat aus der URL auslesen ---
    monat_jahr = request.GET.get('monat')
    if not monat_jahr:
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
