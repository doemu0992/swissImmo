# rentals/api.py
import os
import io
import base64
import json
import requests
import logging
import unicodedata
import re

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import get_template
from django.utils import timezone
from typing import List, Optional
from decimal import Decimal
from datetime import date
from ninja import Router, Schema

from xhtml2pdf import pisa

from portfolio.models import Einheit
from crm.models import Mieter, Verwaltung
from .models import Mietvertrag
from .schemas import VertragSchemaOut, VertragCreateSchema, VertragUpdateSchema

logger = logging.getLogger(__name__)
router = Router(tags=["Rentals"])

# ========================================================
# HILFSFUNKTIONEN
# ========================================================
def sanitize_filename(filename):
    filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    filename = re.sub(r'[^\w\s-]', '', filename).strip().lower()
    return re.sub(r'[-\s]+', '-', filename)

def link_callback(uri, rel):
    if os.path.isfile(uri):
        return uri
    if not uri.startswith('/') and not uri.startswith('http'):
        result = finders.find(uri)
        if result:
            if isinstance(result, (list, tuple)): result = result[0]
            return result
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

def generate_vertrag_pdf_bytes(vertrag):
    """Generiert das PDF aus dem HTML-Template und gibt die Bytes zurück"""
    DEFAULT_VERWALTUNG_NAME = getattr(settings, 'VERWALTUNG_NAME', "SwissImmo Verwaltung")
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    mandant = liegenschaft.mandant
    verwaltung = Verwaltung.objects.first()

    if einheit.typ in ['pp', 'bas', 'gar']:
        template_path = 'core/mietvertrag_garage.html'
    else:
        template_path = 'core/mietvertrag_pdf.html'

    unterschrift_path = None
    if mandant and mandant.unterschrift_bild:
        try: unterschrift_path = mandant.unterschrift_bild.path
        except: pass

    if not unterschrift_path:
        dummy = finders.find("img/unterschrift_dummy.png")
        if dummy: unterschrift_path = dummy

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
        'verwaltung': verwaltung,
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

    if pisa_status.err:
        raise Exception(f"Pisa Error: {pisa_status.err}")
    return pdf_file.getvalue()

# ========================================================
# CRUD ENDPUNKTE
# ========================================================
@router.get("/vertraege", response=List[VertragSchemaOut])
def list_vertraege(request):
    return Mietvertrag.objects.all().order_by('-beginn')

@router.get("/vertraege/{vertrag_id}", response=VertragSchemaOut)
def get_vertrag(request, vertrag_id: int):
    return get_object_or_404(Mietvertrag, id=vertrag_id)

@router.post("/vertraege", response={201: VertragSchemaOut})
def create_vertrag(request, payload: VertragCreateSchema):
    m = get_object_or_404(Mieter, id=payload.mieter_id)
    e = get_object_or_404(Einheit, id=payload.einheit_id)
    data = payload.dict(exclude={'mieter_id', 'einheit_id'}, exclude_unset=True)

    # 🔥 SICHERHEIT: Falls das Frontend 'null' sendet, poppen wir es, damit der Django-Default greift
    if data.get('basis_referenzzinssatz') is None:
        data.pop('basis_referenzzinssatz', None)
    if data.get('basis_lik_punkte') is None:
        data.pop('basis_lik_punkte', None)

    neuer_vertrag = Mietvertrag.objects.create(mieter=m, einheit=e, **data)

    # Einheit mit den neuen Werten aktualisieren
    e.nettomiete_aktuell = neuer_vertrag.netto_mietzins
    e.nebenkosten_aktuell = neuer_vertrag.nebenkosten
    e.save()

    return 201, neuer_vertrag

@router.put("/vertraege/{vertrag_id}", response={200: dict})
def update_vertrag(request, vertrag_id: int, payload: VertragUpdateSchema):
    v = get_object_or_404(Mietvertrag, id=vertrag_id)
    data = payload.dict(exclude_unset=True)

    # 🔥 SICHERHEIT: Verhindert, dass man die Basiswerte aus Versehen auf leer setzt
    if 'basis_referenzzinssatz' in data and data['basis_referenzzinssatz'] is None:
        data.pop('basis_referenzzinssatz')
    if 'basis_lik_punkte' in data and data['basis_lik_punkte'] is None:
        data.pop('basis_lik_punkte')

    for k, val in data.items():
        setattr(v, k, val)
    v.save()
    return 200, {"success": True}

@router.delete("/vertraege/{vertrag_id}", response={204: None})
def delete_vertrag(request, vertrag_id: int):
    get_object_or_404(Mietvertrag, id=vertrag_id).delete()
    return 204, None

# ========================================================
# PDF & DOCUSEAL
# ========================================================
@router.get("/vertraege/{vertrag_id}/pdf")
def view_vertrag_pdf(request, vertrag_id: int):
    v = get_object_or_404(Mietvertrag, id=vertrag_id)
    if v.sign_status == 'unterzeichnet' and v.pdf_datei:
        return HttpResponse(v.pdf_datei.read(), content_type='application/pdf')
    try:
        pdf_bytes = generate_vertrag_pdf_bytes(v)
        return HttpResponse(pdf_bytes, content_type='application/pdf')
    except Exception as e:
        logger.error(f"PDF Gen Error: {e}")
        return HttpResponse(f"Fehler bei der PDF Generierung: {e}", status=500)

@router.post("/vertraege/{vertrag_id}/send-docuseal")
def send_to_docuseal(request, vertrag_id: int):
    vertrag = get_object_or_404(Mietvertrag, id=vertrag_id)
    api_key = getattr(settings, 'DOCUSEAL_API_KEY', None)

    # WICHTIG: Hier deine Template-ID aus DocuSeal eintragen!
    TEMPLATE_ID = 1234567

    if not api_key:
        return {"success": False, "error": "Konfigurationsfehler: DOCUSEAL_API_KEY fehlt in settings.py"}
    if not vertrag.mieter.email:
        return {"success": False, "error": "Abbruch: Der Mieter hat keine E-Mail Adresse."}

    try:
        pdf_value = generate_vertrag_pdf_bytes(vertrag)
        clean_name = sanitize_filename(f"mietvertrag_{vertrag.mieter.nachname}_{vertrag.id}")
        filename = f"{clean_name}.pdf"
        b64_data = base64.b64encode(pdf_value).decode('ascii').replace('\n', '')

        url = "https://api.docuseal.com/submissions/pdf"
        payload = {
            "name": f"Mietvertrag {vertrag.id}",
            "send_email": True,
            "documents": [{
                "name": filename,
                "file": b64_data,
                "fields": [{
                    "name": "Unterschrift_Mieter",
                    "type": "signature",
                    "role": "Mieter",
                    "required": True,
                    "areas": [{"x": 300, "y": 650, "w": 180, "h": 60, "page": 2}]
                }]
            }],
            "submitters": [{
                "role": "Mieter",
                "email": vertrag.mieter.email,
                "send_email": True,
                "name": vertrag.mieter.display_name
            }]
        }

        headers = {"X-Auth-Token": api_key, "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code in [200, 201]:
            vertrag.sign_status = 'gesendet'
            vertrag.save()
            return {"success": True, "message": f"Vertrag erfolgreich an {vertrag.mieter.email} gesendet!"}
        else:
            return {"success": False, "error": f"DocuSeal API Fehler ({response.status_code}): {response.text}"}

    except Exception as e:
        logger.error(f"DocuSeal Exception: {e}")
        return {"success": False, "error": f"Systemfehler: {str(e)}"}

# ========================================================
# WEBHOOK
# ========================================================
class WebhookSchema(Schema):
    event_type: str
    data: dict = {}

@router.post("/webhook/docuseal")
def docuseal_webhook(request, payload: WebhookSchema):
    if payload.event_type == 'submission.completed':
        name = payload.data.get('name', '')
        try:
            vertrag_id = int(name.replace("Mietvertrag", "").strip())
            vertrag = Mietvertrag.objects.get(id=vertrag_id)
            doc_url = payload.data.get('combined_document_url') or (payload.data.get('documents')[0].get('url') if payload.data.get('documents') else None)

            if doc_url:
                r = requests.get(doc_url)
                if r.status_code == 200:
                    filename = f"Unterschrieben_Mietvertrag_{vertrag.id}.pdf"
                    vertrag.pdf_datei.save(filename, ContentFile(r.content), save=False)
                    vertrag.sign_status = 'unterzeichnet'
                    vertrag.status = 'aktiv'
                    vertrag.save()
        except Exception:
            pass
    return 200, {"status": "ok"}