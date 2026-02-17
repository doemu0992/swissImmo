import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from core.models import SchadenMeldung, TicketNachricht
import re

@csrf_exempt
def brevo_inbound_webhook(request):
    if request.method == 'POST':
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
                    ticket = SchadenMeldung.objects.get(id=ticket_id)

                    # Nachricht speichern
                    TicketNachricht.objects.create(
                        ticket=ticket,
                        absender_name=sender,
                        typ='mail_antwort',
                        nachricht=text_body
                    )
                    return JsonResponse({'status': 'ok, saved'})
                except SchadenMeldung.DoesNotExist:
                    return JsonResponse({'status': 'ticket not found'}, status=404)

            return JsonResponse({'status': 'no ticket id in subject'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'status': 'invalid method'}, status=405)