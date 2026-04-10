# core/views/pdf.py
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from rentals.models import Mietvertrag
from core.services.pdf_service import generate_vertrag_pdf_bytes

def generate_pdf_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    try:
        pdf_bytes = generate_vertrag_pdf_bytes(vertrag)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        filename = f"Mietvertrag_{vertrag.einheit.bezeichnung}_{vertrag.mieter.nachname}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        return HttpResponse(f'Fehler beim Erstellen des PDFs: {str(e)}', status=500)