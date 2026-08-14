# rentals/api.py
#
# Nach E1c ist hier nur noch EIN Endpunkt: der DocuSeal-Ruecklauf. Er ist in
# der DocuSeal-Konfiguration als
#     https://swissimmo.pythonanywhere.com/api/rentals/webhook/docuseal
# eingetragen — der Pfad darf sich deshalb nicht aendern, sonst kommen
# unterzeichnete Vertraege nicht mehr zurueck.
#
# Die acht Vertrags-Endpunkte (Liste, Detail, Anlegen, Aendern, Loeschen, PDF,
# DocuSeal-Versand) sind entfallen; sie wurden ausschliesslich von der in E1b
# geloeschten Vue-Oberflaeche aufgerufen. Mit ihnen fallen rentals/schemas.py
# und die drei PDF-Helfer (generate_vertrag_pdf_bytes, sanitize_filename,
# link_callback) weg — die uebrige Anwendung nutzt dafuer die Fassungen in
# core/services/pdf_service.py.
#
# Die Fachlogik des Webhooks liegt seit E1a in rentals/services.py.
import json
import logging

from django.conf import settings
from django.http import HttpResponse
from ninja import Router

from .services import verarbeite_docuseal_event

logger = logging.getLogger(__name__)

router = Router(tags=["Rentals"])


# ========================================================
# WEBHOOK
# ========================================================

# auth=None + KEIN Body-Schema: Webhook muss öffentlich erreichbar sein und darf
# NIE mit „Wert ungültig"/422 antworten (sonst meldet DocuSeal den Webhook als
# fehlerhaft). Payload wird tolerant selbst geparst. Absicherung optional über
# DOCUSEAL_WEBHOOK_SECRET (Header "X-Webhook-Secret").
@router.post("/webhook/docuseal", auth=None)
def docuseal_webhook(request):
    import hmac
    secret = getattr(settings, 'DOCUSEAL_WEBHOOK_SECRET', None)
    provided = request.headers.get('X-Webhook-Secret', '')
    # Secret ist PFLICHT. Ohne konfiguriertes Secret (oder bei falschem Secret) wird
    # der Webhook NICHT verarbeitet — sonst könnte ein unauthentifizierter POST einen
    # Vertrag als 'unterzeichnet' fälschen und über die combined_document_url eine
    # angreiferkontrollierte URL abrufen lassen (SSRF/Überschreiben). Konstant-zeitiger
    # Vergleich gegen Timing-Seitenkanäle.
    if not secret or not hmac.compare_digest(str(provided), str(secret)):
        return HttpResponse('{"status":"forbidden"}', content_type='application/json', status=403)
    try:
        payload = json.loads(request.body or b'{}')
    except Exception:
        payload = {}
    try:
        verarbeite_docuseal_event(payload)
    except Exception:
        logger.error("DocuSeal-Webhook: Verarbeitung fehlgeschlagen", exc_info=True)
    return HttpResponse('{"status":"ok"}', content_type='application/json', status=200)
