from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template import Template, Context
from django.contrib import messages
from datetime import date
import weasyprint

from .models import Mietvertrag, DokumentVorlage
from .forms import SchadenMeldenForm

def generate_pdf_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, id=vertrag_id)
    vorlage = DokumentVorlage.objects.first()
    
    if not vorlage:
        return HttpResponse("Fehler: Bitte erst DokumentVorlage anlegen!", status=404)

    context_data = {
        'mieter_name': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}",
        'strasse': vertrag.einheit.liegenschaft.strasse,
        'ort': f"{vertrag.einheit.liegenschaft.plz} {vertrag.einheit.liegenschaft.ort}",
        'netto_mietzins': f"{vertrag.netto_mietzins:.2f}",
        'brutto_total': f"{vertrag.bruttomietzins:.2f}",
        'datum': date.today().strftime("%d.%m.%Y"),
    }

    template = Template(vorlage.inhalt)
    context = Context(context_data)
    html_body = template.render(context)

    full_html = f"""
    <!DOCTYPE html><html><head><style>
        @page {{ size: A4; margin: 2.5cm; }}
        body {{ font-family: sans-serif; }}
    </style></head><body>{html_body}</body></html>
    """
    
    pdf_file = weasyprint.HTML(string=full_html).write_pdf()
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Vertrag.pdf"'
    return response

def schaden_melden_public(request):
    if request.method == 'POST':
        form = SchadenMeldenForm(request.POST, request.FILES)
        if form.is_valid():
            meldung = form.save(commit=False)
            meldung.status = 'NEU'
            meldung.save()
            messages.success(request, "Erfolg!")
            return redirect('schaden_erfolg')
    else:
        form = SchadenMeldenForm()
    return render(request, 'schaden_form.html', {'form': form})

def schaden_erfolg(request):
    return render(request, 'schaden_success.html')
