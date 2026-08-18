from tickets.models import SchadenMeldung, TicketNachricht

import json
import hmac
import logging
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import re

logger = logging.getLogger(__name__)

@csrf_exempt
def brevo_inbound_webhook(request):
    if request.method == 'POST':
        # Ohne konfiguriertes Secret wird ABGEWIESEN. Früher stand hier `if secret:`
        # — war keines gesetzt, entfiel die Prüfung ganz und jeder konnte über
        # diesen Endpunkt Nachrichten in fremde Ticketverläufe schreiben.
        secret = getattr(settings, 'BREVO_WEBHOOK_SECRET', None)
        gesendet = request.headers.get('X-Webhook-Secret') or request.GET.get('token', '')
        if not secret or not hmac.compare_digest(str(gesendet), str(secret)):
            logger.warning("Brevo-Webhook: ungültiges/fehlendes Secret abgewiesen")
            return JsonResponse({'status': 'forbidden'}, status=403)
        try:
            data = json.loads(request.body)
            # Brevo sendet Betreff im Feld 'Subject'
            subject = data.get('Subject', '')
            text_body = data.get('RawTextBody', '')
            sender = data.get('From', '')

            # Ticket ID aus Betreff extrahieren (Suche nach "#123")
            match = re.search(r'#(\d+)', subject)
            if match:
                ticket_id = match.group(1)
                try:
                    # `alle_organisationen`: Brevo liefert eingehende Mails
                    # als Webhook — keine Anmeldung, kein Mandantenkontext.
                    # Ueber `objects` warf die Zeile seit Etappe 6.2 -> HTTP 500,
                    # und jede Mail-Antwort auf ein Ticket ging verloren.
                    ticket = SchadenMeldung.alle_organisationen.get(id=ticket_id)

                    # Nachricht im Kontext DIESES Tickets speichern — sonst
                    # wuesste der Datensatz nicht, wem er gehoert.
                    from core.tenancy import kontext_des_objekts
                    with kontext_des_objekts(ticket):
                        TicketNachricht.objects.create(
                            ticket=ticket,
                            absender_name=sender,
                            typ='mail_antwort',
                            nachricht=text_body,
                        )
                    return JsonResponse({'status': 'ok, saved'})
                except SchadenMeldung.DoesNotExist:
                    return JsonResponse({'status': 'ticket not found'}, status=404)

            return JsonResponse({'status': 'no ticket id in subject'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'status': 'invalid method'}, status=405)
