import io
import datetime
from decimal import Decimal, InvalidOperation
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required

# PDF Tools
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

# Eigene Modelle
from core.models import Mietvertrag, MietzinsAnpassung, Verwaltung

# Hilfsfunktionen für Marktdaten
from core.models import get_current_ref_zins, get_current_lik

def parse_decimal(value):
    """Hilfsfunktion: Verwandelt Eingaben sicher in Decimal-Zahlen."""
    if not value: return Decimal('0.00')
    try:
        clean_value = str(value).replace(',', '.').strip()
        return Decimal(clean_value)
    except (InvalidOperation, ValueError):
        return Decimal('0.00')

@staff_member_required
def mietzins_anpassung_view(request, vertrag_id):
    """
    Zeigt ein Formular zur Berechnung und generiert danach das PDF mit Unterschrift.
    """
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)

    # --- DATEN ERMITTELN ---
    liegenschaft = vertrag.einheit.liegenschaft
    mandant = liegenschaft.mandant
    verwaltung = Verwaltung.objects.first()

    absender_name = "Immobilienverwaltung"
    absender_strasse = ""
    absender_ort = ""
    unterschrift_pfad = None

    if mandant:
        absender_name = mandant.firma_oder_name
        absender_strasse = mandant.strasse
        absender_ort = f"{mandant.plz} {mandant.ort}"
        if mandant.unterschrift_bild:
            unterschrift_pfad = mandant.unterschrift_bild.path
    elif verwaltung:
        absender_name = verwaltung.firma
        absender_strasse = verwaltung.strasse
        absender_ort = f"{verwaltung.plz} {verwaltung.ort}"


    # Aktuelle Marktdaten für Vorschau
    aktueller_zins = get_current_ref_zins()
    aktueller_lik = get_current_lik()

    # --- WENN FORMULAR GESENDET WURDE (POST) ---
    if request.method == 'POST':
        # Daten holen
        neuer_zins = parse_decimal(request.POST.get('neuer_zins'))
        neuer_lik = parse_decimal(request.POST.get('neuer_lik'))
        neue_miete = parse_decimal(request.POST.get('neue_miete'))
        wirksam_ab_str = request.POST.get('wirksam_ab')
        begruendung = request.POST.get('begruendung', 'Anpassung an Referenzzinssatz und Teuerung')

        if not wirksam_ab_str:
             wirksam_ab_str = datetime.date.today().strftime('%Y-%m-%d')

        # 1. DB Speichern
        MietzinsAnpassung.objects.create(
            vertrag=vertrag,
            alter_netto_mietzins=vertrag.netto_mietzins,
            alter_referenzzinssatz=vertrag.basis_referenzzinssatz,
            alter_lik_index=vertrag.basis_lik_punkte,
            neuer_referenzzinssatz=neuer_zins,
            neuer_lik_index=neuer_lik,
            neuer_netto_mietzins=neue_miete,
            erhoehung_prozent_total=0,
            wirksam_ab=wirksam_ab_str,
            begruendung=begruendung
        )

        # 2. PDF Generieren
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        c.setTitle(f"Mietzinsanpassung {vertrag.mieter.nachname}")

        # -- PDF LAYOUT START --

        # Logo
        if verwaltung and verwaltung.logo:
            try:
                c.drawImage(verwaltung.logo.path, 160*mm, 270*mm, width=35*mm, preserveAspectRatio=True, mask='auto')
            except: pass

        # Absender (Oben Links)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20*mm, 275*mm, absender_name)
        c.setFont("Helvetica", 10)
        c.drawString(20*mm, 270*mm, absender_strasse)
        c.drawString(20*mm, 265*mm, absender_ort)

        # Empfänger
        c.setFont("Helvetica", 12)
        y_empf = 240*mm
        c.drawString(20*mm, y_empf, f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}")
        c.drawString(20*mm, y_empf-5*mm, f"{vertrag.mieter.strasse}")
        c.drawString(20*mm, y_empf-10*mm, f"{vertrag.mieter.plz} {vertrag.mieter.ort}")

        # Titel & Objekt
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20*mm, 200*mm, "Amtliche Mitteilung einer Mietzinsanpassung")
        c.setFont("Helvetica", 10)
        c.drawString(20*mm, 190*mm, f"Objekt: {vertrag.einheit.bezeichnung}")

        # Datum
        try:
            d = datetime.datetime.strptime(wirksam_ab_str, '%Y-%m-%d')
            datum_schön = d.strftime('%d.%m.%Y')
        except:
            datum_schön = wirksam_ab_str
        c.drawString(20*mm, 185*mm, f"Wirksam ab: {datum_schön}")

        # --- RECHNUNG ---
        y = 160*mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20*mm, y, "Veränderungen:")
        y -= 8*mm
        c.setFont("Helvetica", 11)
        c.drawString(20*mm, y, f"Referenzzinssatz: {vertrag.basis_referenzzinssatz}% -> {neuer_zins}%")
        y -= 6*mm
        c.drawString(20*mm, y, f"Landesindex (LIK): {vertrag.basis_lik_punkte} -> {neuer_lik} Punkte")
        y -= 15*mm

        # Graue Box
        c.setFillColor(colors.lightgrey)
        c.rect(15*mm, y-15*mm, 180*mm, 25*mm, fill=1, stroke=0)
        c.setFillColor(colors.black)

        c.setFont("Helvetica", 12)
        c.drawString(20*mm, y, "Alter Nettomietzins:")
        c.drawRightString(180*mm, y, f"CHF {vertrag.netto_mietzins:.2f}")

        c.setFont("Helvetica-Bold", 14)
        c.drawString(20*mm, y-10*mm, "Neuer Nettomietzins:")
        c.drawRightString(180*mm, y-10*mm, f"CHF {neue_miete:.2f}")

        # --- BEGRÜNDUNG (Fixiert auf 90mm Höhe) ---
        y_text = 90*mm
        c.setFont("Helvetica", 10)
        c.drawString(20*mm, y_text, "Begründung:")
        y_text -= 5*mm
        if len(begruendung) > 90:
            c.drawString(20*mm, y_text, begruendung[:90])
            c.drawString(20*mm, y_text-5*mm, begruendung[90:180])
        else:
            c.drawString(20*mm, y_text, begruendung)

        # --- RECHTSMITTELBELEHRUNG (Fixiert auf 70mm Höhe) ---
        # Damit ist genug Abstand zur Begründung oben und zur Unterschrift unten
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20*mm, 70*mm, "Rechtsmittelbelehrung:")
        c.setFont("Helvetica", 9)
        c.drawString(20*mm, 65*mm, "Diese Erhöhung kann innert 30 Tagen bei der Schlichtungsbehörde angefochten werden.")

        # --- UNTERSCHRIFTENBLOCK (Start bei 45mm Höhe) ---
        y_sign_start = 45*mm

        c.setFont("Helvetica", 11)
        c.drawString(20*mm, y_sign_start, "Freundliche Grüsse")

        # UNTERSCHRIFT BILD (Platzieren zwischen Gruss und Name)
        if unterschrift_pfad:
            try:
                # Wir zeichnen das Bild unterhalb des Grusses
                # y = y_sign_start - 25mm -> Bildunterkante bei 20mm
                # x = 20mm (linksbündig mit Text)
                c.drawImage(unterschrift_pfad, 20*mm, y_sign_start - 25*mm, width=50*mm, preserveAspectRatio=True, mask='auto')
            except Exception as e:
                pass

        # NAME (Ganz unten bei 15mm)
        # So ist sichergestellt, dass der Name unter dem Bild steht
        c.drawString(20*mm, 15*mm, absender_name)

        c.showPage()
        c.save()

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        filename = f"Mietzinsanpassung_{vertrag.mieter.nachname}.pdf"
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response


    # --- GET: BERECHNUNG ---
    alt_zins = vertrag.basis_referenzzinssatz
    alt_lik = vertrag.basis_lik_punkte
    alt_miete = vertrag.netto_mietzins

    delta_zins = (aktueller_zins - alt_zins) / Decimal('0.25')
    aufschlag_zins_prozent = delta_zins * Decimal('3.0')

    if alt_lik > 0:
        teuerung_prozent = ((aktueller_lik - alt_lik) / alt_lik) * 100 * Decimal('0.4')
    else:
        teuerung_prozent = 0

    kosten_prozent = Decimal('0.5')
    total_prozent = aufschlag_zins_prozent + teuerung_prozent + kosten_prozent

    aufschlag = alt_miete * (total_prozent / 100)
    neue_miete = alt_miete + aufschlag
    neue_miete = (neue_miete * 20).quantize(Decimal('1')) / 20

    heute = datetime.date.today()
    wirksam_ab = (heute.replace(day=1) + datetime.timedelta(days=100)).replace(day=1)

    context = {
        'vertrag': vertrag,
        'alt_zins': alt_zins,
        'neu_zins': aktueller_zins,
        'alt_lik': alt_lik,
        'neu_lik': aktueller_lik,
        'vorschlag_miete': neue_miete,
        'wirksam_datum': wirksam_ab.strftime('%Y-%m-%d')
    }

    return render(request, 'core/mietzins_form.html', context)

def generiere_amtliches_formular(request, vertrag_id):
    return redirect('mietzins_anpassung', vertrag_id=vertrag_id)