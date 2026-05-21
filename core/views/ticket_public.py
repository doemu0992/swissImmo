# core/views/ticket_public.py
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required

from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag
from tickets.models import SchadenMeldung
from tickets.services import process_public_ticket_form, generate_qr_poster
from crm.models import Mieter

# ==========================================
# 1. LANDING PAGE (STARTSEITE)
# ==========================================
def index_view(request):
    return render(request, 'core/index.html')


# ==========================================
# 2. NEUES ALLGEMEINES SCHADENSFORMULAR
# ==========================================
def public_schaden_melden_view(request):
    if request.method == 'POST':
        # 1. Daten aus dem POST-Request holen
        kategorie = request.POST.get('kategorie', 'unbekannt')
        raum = request.POST.get('raum', '')
        objekt = request.POST.get('objekt', '')
        beschreibung = request.POST.get('beschreibung', '')

        # Neue Strukturierte Kontaktdaten
        vorname = request.POST.get('vorname', '').strip()
        nachname = request.POST.get('nachname', '').strip()
        email = request.POST.get('email', '').strip()
        telefon = request.POST.get('telefon', '').strip()
        erreichbarkeit = request.POST.get('erreichbarkeit', 'telefon')

        # Liegenschafts-Infos aus Dropdown/Auto-Suggest
        liegenschaft_id = request.POST.get('liegenschaft_id', '')
        adresse_text = request.POST.get('adresse', '').strip()
        foto = request.FILES.get('foto')

        titel_text = f"Meldung ({kategorie.capitalize()})"
        if raum and objekt:
            titel_text = f"[{raum.capitalize()}] Defekt an {objekt.capitalize()}"

        # 3. CRM ABGLEICH & ADRESS-ZUORDNUNG
        gefundener_mieter = Mieter.objects.filter(email__iexact=email).first()
        zugewiesene_liegenschaft = None
        zugewiesene_einheit = None

        # A) Wurde sauber via Dropdown ausgewählt (Sicherstellen, dass es eine Zahl ist)
        if liegenschaft_id and liegenschaft_id.isdigit():
            zugewiesene_liegenschaft = Liegenschaft.objects.filter(pk=int(liegenschaft_id)).first()

        # B) Auto-Abgleich via E-Mail
        if gefundener_mieter and not zugewiesene_liegenschaft:
            vertrag = Mietvertrag.objects.filter(mieter=gefundener_mieter, aktiv=True).first()
            if vertrag:
                zugewiesene_einheit = vertrag.einheit
                zugewiesene_liegenschaft = zugewiesene_einheit.liegenschaft

        # 4. Fallbacks (Sicherstellen, dass keine Infos verloren gehen)
        if not zugewiesene_liegenschaft:
            zugewiesene_liegenschaft = Liegenschaft.objects.first()
            beschreibung = f"⚠️ ZUWEISUNG UNKLAR ⚠️\nAngegebene Adresse: {adresse_text}\n\n{beschreibung}"

        # 5. Ticket erstellen (Mit den neuen getrennten Namensfeldern)
        SchadenMeldung.objects.create(
            liegenschaft=zugewiesene_liegenschaft,
            betroffene_einheit=zugewiesene_einheit,
            gemeldet_von=gefundener_mieter,
            melder_vorname=vorname,   # 🔥 NEU: Sicher gespeichert
            melder_nachname=nachname, # 🔥 NEU: Sicher gespeichert
            kategorie=kategorie,
            raum=raum,
            objekt=objekt,
            titel=titel_text,
            beschreibung=beschreibung, # <-- HIER IST DIE BESCHREIBUNG NUN 100% SAUBER
            email_melder=email,
            tel_melder=telefon,
            foto=foto,
            status='neu',
            prioritaet='mittel',
            zutritt='telefon' if erreichbarkeit in ['telefon', 'immer'] else 'passpartout'
        )

        # WICHTIG: Auch beim Success-Return ein leeres JSON mitgeben, damit Alpine.js nicht abstürzt!
        return render(request, 'core/schaden_melden.html', {'success': True, 'liegenschaften_json': '[]'})

    # GET-REQUEST: Bulletproof Auslesen der Liegenschaften
    liegenschaften_query = Liegenschaft.objects.all().order_by('strasse')
    liegenschaften_liste = []

    for l in liegenschaften_query:
        # Wir nutzen getattr, falls die Felder plz oder ort in der DB gar nicht existieren, um Abstürze zu vermeiden
        plz = getattr(l, 'plz', '')
        ort = getattr(l, 'ort', '')
        adresse_komplett = f"{l.strasse}"
        if plz or ort:
            adresse_komplett += f", {plz} {ort}"

        liegenschaften_liste.append({'id': l.id, 'text': adresse_komplett})

    context = {
        'success': False,
        'liegenschaften_json': json.dumps(liegenschaften_liste)
    }
    return render(request, 'core/schaden_melden.html', context)


# ==========================================
# 3. QR-CODE FORMULAR (SPEZIFISCH PRO LIEGENSCHAFT)
# ==========================================
def public_ticket_view(request, liegenschaft_id):
    liegenschaft = get_object_or_404(Liegenschaft, pk=liegenschaft_id)
    einheiten = Einheit.objects.filter(liegenschaft=liegenschaft).order_by('etage', 'bezeichnung')
    for e in einheiten:
        aktiver_v = Mietvertrag.objects.filter(einheit=e, aktiv=True).first()
        e.mieter_namen = f"{aktiver_v.mieter.nachname}" if aktiver_v else "Leerstand"

    if request.method == 'POST':
        process_public_ticket_form(liegenschaft, request.POST, request.FILES)
        return render(request, 'core/public_ticket_form.html', {'success': True, 'liegenschaft': liegenschaft})

    return render(request, 'core/public_ticket_form.html', {'liegenschaft': liegenschaft, 'einheiten': einheiten})

# ==========================================
# 4. AUSHANG GENERIEREN (ADMIN)
# ==========================================
@staff_member_required
def generate_hallway_poster(request, liegenschaft_id):
    liegenschaft = get_object_or_404(Liegenschaft, pk=liegenschaft_id)
    domain = request.get_host()
    buffer = generate_qr_poster(liegenschaft, domain)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Aushang_{liegenschaft.strasse}.pdf"'
    return response