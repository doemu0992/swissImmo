import os
import io
import base64
import json
import requests
import traceback
import logging
import unicodedata
import re

from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponse
from django.utils import timezone
from django.template.loader import get_template
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.core.files.base import ContentFile
from django.conf import settings
from django.contrib.staticfiles import finders

from xhtml2pdf import pisa

# Models importieren
from core.models import Mietvertrag, Dokument

logger = logging.getLogger(__name__)

# --- Helper Funktionen ---
def sanitize_filename(filename):
    filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    filename = re.sub(r'[^\w\s-]', '', filename).strip().lower()
    return re.sub(r'[-\s]+', '-', filename)

def link_callback(uri, rel):
    """
    Sicherer Link-Callback, der absolute Pfade (für Unterschriften) erlaubt.
    """
    # 1. Ist es bereits ein absoluter Pfad auf der Festplatte?
    if os.path.isfile(uri):
        return uri

    # 2. Relative Pfade via Static Finders
    if not uri.startswith('/') and not uri.startswith('http'):
        result = finders.find(uri)
        if result:
            if isinstance(result, (list, tuple)): result = result[0]
            return result

    # 3. Standard Django URL Auflösung
    sUrl, sRoot = settings.STATIC_URL, settings.STATIC_ROOT
    mUrl, mRoot = settings.MEDIA_URL, settings.MEDIA_ROOT

    if uri.startswith(mUrl):
        path = os.path.join(mRoot, uri.replace(mUrl, ""))
    elif uri.startswith(sUrl):
        path = os.path.join(sRoot, uri.replace(sUrl, ""))
    else:
        return uri

    if not os.path.isfile(path):
        return None
    return path

# --- VIEWS ---

def send_via_docuseal(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    DEFAULT_VERWALTUNG_NAME = getattr(settings, 'VERWALTUNG_NAME', "SwissImmo Verwaltung")

    # 1. Validierung
    api_key = getattr(settings, 'DOCUSEAL_API_KEY', None)
    if not api_key:
        messages.error(request, "❌ API-Key fehlt in settings.py")
        return redirect(request.META.get('HTTP_REFERER', 'admin:index'))

    if not vertrag.mieter.email:
        messages.error(request, "❌ Abbruch: Mieter hat keine E-Mail.")
        return redirect(request.META.get('HTTP_REFERER', 'admin:index'))

    # 2. PDF Generieren
    try:
        # DATEN LADEN
        einheit = vertrag.einheit
        liegenschaft = einheit.liegenschaft
        mandant = liegenschaft.mandant

        # TEMPLATE AUSWAHL (Garage vs. Wohnung)
        if einheit.typ in ['pp', 'bas', 'gar']:
            template_path = 'core/mietvertrag_garage.html'
        else:
            template_path = 'core/mietvertrag_pdf.html'

        # UNTERSCHRIFT FINDEN
        unterschrift_path = None
        if mandant and mandant.unterschrift_bild:
            try:
                # Absoluter Pfad für xhtml2pdf
                unterschrift_path = mandant.unterschrift_bild.path
            except: pass

        if not unterschrift_path:
            # Fallback
            dummy = finders.find("img/unterschrift_dummy.png")
            if dummy: unterschrift_path = dummy

        # ZAHLEN FORMATIEREN
        netto = vertrag.netto_mietzins or 0
        nk = vertrag.nebenkosten or 0
        brutto = netto + nk
        kaution = vertrag.kautions_betrag or 0

        context = {
            'vertrag': vertrag,
            'mieter': vertrag.mieter,
            'einheit': einheit,
            'liegenschaft': liegenschaft,
            'mandant': mandant,
            'verwaltungs_name': DEFAULT_VERWALTUNG_NAME,
            'heute': timezone.now().date(),
            'miete_fmt': f"{netto:.2f}",
            'nk_fmt': f"{nk:.2f}",
            'brutto_fmt': f"{brutto:.2f}",
            'kaution_fmt': f"{kaution:.2f}",
            'unterschrift_path': unterschrift_path,
        }

        template = get_template(template_path)
        html = template.render(context)
        pdf_file = io.BytesIO()
        pisa_status = pisa.CreatePDF(html, dest=pdf_file, link_callback=link_callback)

        if pisa_status.err: raise Exception(f"Pisa Error: {pisa_status.err}")
        pdf_value = pdf_file.getvalue()

        if len(pdf_value) < 1000:
            logger.warning(f"PDF ist klein ({len(pdf_value)} bytes).")

    except Exception as e:
        logger.error(f"PDF Gen Error: {e}")
        messages.error(request, f"❌ PDF Fehler: {str(e)}")
        return redirect(request.META.get('HTTP_REFERER', 'admin:index'))

    # 3. API Request an DocuSeal
    try:
        clean_name = sanitize_filename(f"mietvertrag_{vertrag.mieter.nachname}_{vertrag.id}")
        filename = f"{clean_name}.pdf"

        b64_data = base64.b64encode(pdf_value).decode('ascii').replace('\n', '')
        url = "https://api.docuseal.com/submissions/pdf"

        payload = {
            "name": f"Mietvertrag {vertrag.id}",
            "send_email": True,
            "documents": [
                {
                    "name": filename,
                    "file": b64_data,
                    "fields": [{
                        "name": "Unterschrift_Mieter",
                        "type": "signature",
                        "role": "Mieter",
                        "required": True,
                        # ACHTUNG: Koordinaten ("areas") sind optional, wenn Text-Tags im HTML verwendet werden.
                        # Da wir im Template {{Unterschrift...}} nutzen, sollte DocuSeal das erkennen.
                        # Wir lassen die Koordinaten als Fallback drin, passen aber auf Seite 1 auf.
                        "areas": [{"x": 300, "y": 650, "w": 180, "h": 60, "page": 2}]
                    }]
                }
            ],
            "submitters": [{
                "role": "Mieter",
                "email": vertrag.mieter.email,
                "send_email": True,
                "name": f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}"
            }]
        }

        headers = {"X-Auth-Token": api_key, "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code in [200, 201]:
            data = response.json()
            if isinstance(data, list): data = data[0]

            new_id = str(data.get('id'))
            if hasattr(vertrag, 'jotform_submission_id'):
                vertrag.jotform_submission_id = new_id
                vertrag.sign_status = 'gesendet'
                vertrag.save()

            messages.success(request, f"✅ Vertrag an {vertrag.mieter.email} gesendet (ID: {new_id})")
        else:
            raise Exception(f"API Fehler {response.status_code}: {response.text}")

    except Exception as e:
        logger.error(f"DocuSeal Exception: {e}")
        messages.error(request, f"❌ Fehler beim Senden: {str(e)}")

    return redirect(request.META.get('HTTP_REFERER', 'admin:index'))

@csrf_exempt
def docuseal_webhook(request):
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
            event_type = payload.get('event_type')
            data = payload.get('data', {})

            sub_id = str(data.get('id'))
            vertrag = Mietvertrag.objects.filter(jotform_submission_id=sub_id).first()

            if not vertrag: return HttpResponse("OK", status=200)

            status_api = data.get('status', 'unknown')
            if status_api == 'completed': vertrag.sign_status = 'unterzeichnet'
            elif status_api == 'declined': vertrag.sign_status = 'abgelehnt'
            vertrag.save()

            if event_type == 'submission.completed' or status_api == 'completed':
                doc_url = data.get('combined_document_url')
                if not doc_url and data.get('documents'):
                    docs = data.get('documents')
                    if len(docs) > 0: doc_url = docs[0].get('url')

                if doc_url:
                    r = requests.get(doc_url)
                    if r.status_code == 200:
                        filename = f"Unterschrieben_Mietvertrag_{vertrag.id}.pdf"
                        file_content = ContentFile(r.content, name=filename)

                        vertrag.pdf_datei.save(filename, file_content, save=False)
                        vertrag.sign_status = 'unterzeichnet'
                        vertrag.save()

                        Dokument.objects.create(
                            kategorie='Mietvertrag',
                            bezeichnung=f"Vertrag (Unterschrieben)",
                            datei=ContentFile(r.content, name=filename),
                            vertrag=vertrag,
                            liegenschaft=vertrag.einheit.liegenschaft,
                            mandant=vertrag.einheit.liegenschaft.mandant
                        )

            return HttpResponse("OK", status=200)
        except Exception as e:
            logger.error(f"Webhook Error: {e}")
            return HttpResponse("Error", status=500)
    return HttpResponse("Method not allowed", status=405)