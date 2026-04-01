import os
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import get_template
from django.utils import timezone
from django.conf import settings
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa

from rentals.models import Mietvertrag

def link_callback(uri, rel):
    if os.path.isfile(uri): return uri
    if not uri.startswith('/') and not uri.startswith('http'):
        result = finders.find(uri)
        if result: return result[0] if isinstance(result, (list, tuple)) else result

    sUrl, sRoot = settings.STATIC_URL, settings.STATIC_ROOT
    mUrl, mRoot = settings.MEDIA_URL, settings.MEDIA_ROOT

    if uri.startswith(mUrl): path = os.path.join(mRoot, uri.replace(mUrl, ""))
    elif uri.startswith(sUrl): path = os.path.join(sRoot, uri.replace(sUrl, ""))
    else: return uri

    return path if os.path.isfile(path) else None

def generate_pdf_view(request, vertrag_id):
    """Generiert den Mietvertrag als PDF mittels HTML-Template"""
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    mandant = liegenschaft.mandant

    netto = vertrag.netto_mietzins or 0
    nk = vertrag.nebenkosten or 0
    brutto = netto + nk
    kaution = vertrag.kautions_betrag or 0

    unterschrift_path = mandant.unterschrift_bild.path if (mandant and mandant.unterschrift_bild) else None
    if not unterschrift_path:
        dummy = finders.find("img/unterschrift_dummy.png")
        if dummy: unterschrift_path = dummy

    template_name = 'core/mietvertrag_garage.html' if einheit.typ in ['pp', 'bas', 'gar'] else 'core/mietvertrag_pdf.html'

    context = {
        'vertrag': vertrag, 'mieter': vertrag.mieter, 'einheit': einheit,
        'liegenschaft': liegenschaft, 'mandant': mandant,
        'heute': timezone.now().date(),
        'miete_fmt': f"{netto:.2f}", 'nk_fmt': f"{nk:.2f}",
        'brutto_fmt': f"{brutto:.2f}", 'kaution_fmt': f"{kaution:.2f}",
        'unterschrift_path': unterschrift_path,
    }

    html = get_template(template_name).render(context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Mietvertrag_{vertrag.id}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err: return HttpResponse(f'Fehler: {pisa_status.err}', status=500)
    return response