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
from core.auth import auth_schreiben, auth_verwaltung, log_aktion

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
        dummy = finders.find("img/unterschrift_dummy_transparent.png")
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

@router.post("/vertraege", response={201: VertragSchemaOut}, auth=auth_schreiben)
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

    # 🔥 NEU: Zukünftige Adresse beim Mieter vollautomatisch hinterlegen
    m.zukuenftige_strasse = e.liegenschaft.strasse
    m.zukuenftige_plz = e.liegenschaft.plz
    m.zukuenftiger_ort = e.liegenschaft.ort
    m.zukuenftig_ab = neuer_vertrag.beginn
    m.save()

    return 201, neuer_vertrag

@router.put("/vertraege/{vertrag_id}", response={200: dict}, auth=auth_schreiben)
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

    # Falls sich das Einzugsdatum bei einem noch nicht aktiven Vertrag ändert,
    # ziehen wir die Info für den Mieter gleich mit glatt.
    if 'beginn' in data and v.beginn:
        m = v.mieter
        if m.zukuenftig_ab:  # Nur wenn er noch in der "Warteschlange" für den Adresswechsel ist
            m.zukuenftig_ab = v.beginn
            m.save()

    return 200, {"success": True}

@router.delete("/vertraege/{vertrag_id}", response={204: None}, auth=auth_verwaltung)
def delete_vertrag(request, vertrag_id: int):
    vertrag = get_object_or_404(Mietvertrag, id=vertrag_id)
    mieter = vertrag.mieter

    # 🔥 NEU: Wenn dieser Vertrag der Grund für den Zukunfts-Umzug war, stornieren wir den Umzug!
    if mieter.zukuenftig_ab == vertrag.beginn:
        mieter.zukuenftige_strasse = ''
        mieter.zukuenftige_plz = ''
        mieter.zukuenftiger_ort = ''
        mieter.zukuenftig_ab = None
        mieter.save()

    log_aktion(request, "Mietvertrag gelöscht", str(vertrag), f"Vertrag-ID {vertrag.id}")
    vertrag.delete()
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

@router.post("/vertraege/{vertrag_id}/send-docuseal", auth=auth_verwaltung)
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
            # Position via Textanker im PDF ({{...;type=signature;role=Mieter}}),
            # nicht über feste Koordinaten → korrekt für alle Vertragstypen.
            "documents": [{
                "name": filename,
                "file": b64_data,
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
            log_aktion(request, "Vertrag via DocuSeal gesendet", str(vertrag), f"an {vertrag.mieter.email}")
            return {"success": True, "message": f"Vertrag erfolgreich an {vertrag.mieter.email} gesendet!"}
        else:
            return {"success": False, "error": f"DocuSeal API Fehler ({response.status_code}): {response.text}"}

    except Exception as e:
        logger.error(f"DocuSeal Exception: {e}")
        return {"success": False, "error": f"Systemfehler: {str(e)}"}

# ========================================================
# WEBHOOK
# ========================================================
def _erster_dokument_url(dokumente):
    """Extrahiert die erste Dokument-URL aus einer DocuSeal-Dokumentliste."""
    if isinstance(dokumente, list):
        for d in dokumente:
            if isinstance(d, dict) and d.get('url'):
                return d['url']
    return None


def _vertrag_id_aus_name(name):
    """Zieht die Vertrags-ID aus einem Namen wie 'Mietvertrag 3'."""
    if not name:
        return 0
    teil = str(name).split('Mietvertrag')[-1]
    ziffern = re.sub(r'[^0-9]', '', teil)
    try:
        return int(ziffern) if ziffern else 0
    except ValueError:
        return 0


def verarbeite_docuseal_event(payload):
    """Verarbeitet ein DocuSeal-Webhook-Event tolerant (verschiedene Payload-
    Varianten). Lädt bei Abschluss den unterschriebenen Vertrag herunter und
    legt ihn über vertrag.save() zentral überall ab. Gibt True zurück, wenn ein
    Vertrag aktualisiert wurde."""
    if not isinstance(payload, dict):
        return False
    event = str(payload.get('event_type') or payload.get('event') or '').lower()
    data = payload.get('data')
    if not isinstance(data, dict):
        data = payload
    status = str(data.get('status') or '').lower()
    if 'completed' not in event and status != 'completed':
        return False   # nur vollständig unterschriebene Verträge ablegen

    submission = data.get('submission') if isinstance(data.get('submission'), dict) else {}
    name = data.get('name') or submission.get('name') or ''
    vertrag_id = _vertrag_id_aus_name(name)
    vertrag = Mietvertrag.objects.filter(id=vertrag_id).first() if vertrag_id else None
    if not vertrag:
        return False

    doc_url = (data.get('combined_document_url')
               or submission.get('combined_document_url')
               or _erster_dokument_url(data.get('documents'))
               or _erster_dokument_url(submission.get('documents')))
    if not doc_url:
        return False
    try:
        r = requests.get(doc_url, timeout=30)
    except Exception:
        return False
    if r.status_code != 200:
        return False
    vertrag.pdf_datei.save(f"Unterschrieben_Mietvertrag_{vertrag.id}.pdf",
                           ContentFile(r.content), save=False)
    vertrag.sign_status = 'unterzeichnet'
    if vertrag.status in ('entwurf', 'offen'):
        vertrag.status = 'aktiv'
    vertrag.save()   # → zentrale Ablage (Portal, Person, Objekt) via Model.save
    return True


# auth=None + KEIN Body-Schema: Webhook muss öffentlich erreichbar sein und darf
# NIE mit „Wert ungültig"/422 antworten (sonst meldet DocuSeal den Webhook als
# fehlerhaft). Payload wird tolerant selbst geparst. Absicherung optional über
# DOCUSEAL_WEBHOOK_SECRET (Header "X-Webhook-Secret").
@router.post("/webhook/docuseal", auth=None)
def docuseal_webhook(request):
    secret = getattr(settings, 'DOCUSEAL_WEBHOOK_SECRET', None)
    if secret and request.headers.get('X-Webhook-Secret') != secret:
        return HttpResponse('{"status":"forbidden"}', content_type='application/json', status=200)
    try:
        payload = json.loads(request.body or b'{}')
    except Exception:
        payload = {}
    try:
        verarbeite_docuseal_event(payload)
    except Exception:
        logger.error("DocuSeal-Webhook: Verarbeitung fehlgeschlagen", exc_info=True)
    return HttpResponse('{"status":"ok"}', content_type='application/json', status=200)