# core/views/ticket_public.py
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required

from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag
from tickets.services import process_public_ticket_form, generate_qr_poster

# ==========================================
# 1. LANDING PAGE (STARTSEITE)
# ==========================================
def index_view(request):
    """
    Zeigt die Startseite mit der Auswahl.
    """
    return render(request, 'core/index.html')

# ==========================================
# 2. QR-CODE FORMULAR (ÖFFENTLICH)
# ==========================================
def public_ticket_view(request, liegenschaft_id):
    liegenschaft = get_object_or_404(Liegenschaft, pk=liegenschaft_id)

    # Einheiten laden
    einheiten = Einheit.objects.filter(liegenschaft=liegenschaft).order_by('etage', 'bezeichnung')
    for e in einheiten:
        aktiver_v = Mietvertrag.objects.filter(einheit=e, aktiv=True).first()
        e.mieter_namen = f"{aktiver_v.mieter.nachname}" if aktiver_v else "Leerstand"

    if request.method == 'POST':
        # --- Aufruf des Services anstatt komplexer Logik im View ---
        process_public_ticket_form(liegenschaft, request.POST, request.FILES)

        return render(request, 'core/public_ticket_form.html', {'success': True, 'liegenschaft': liegenschaft})

    return render(request, 'core/public_ticket_form.html', {
        'liegenschaft': liegenschaft,
        'einheiten': einheiten
    })

# ==========================================
# 3. AUSHANG GENERIEREN (ADMIN)
# ==========================================
@staff_member_required
def generate_hallway_poster(request, liegenschaft_id):
    liegenschaft = get_object_or_404(Liegenschaft, pk=liegenschaft_id)
    domain = request.get_host()

    # --- Aufruf des Services für die PDF Generierung ---
    buffer = generate_qr_poster(liegenschaft, domain)

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Aushang_{liegenschaft.strasse}.pdf"'
    return response