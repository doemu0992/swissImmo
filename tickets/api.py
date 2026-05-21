# tickets/api.py
from ninja import Router, Schema
from django.shortcuts import get_object_or_404
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from typing import List

# 🔥 KORREKTUR: Handwerker aus dem CRM importieren
from crm.models import Handwerker
from .models import SchadenMeldung, TicketNachricht, HandwerkerAuftrag
from .schemas import (
    SchadenMeldungListSchema,
    SchadenMeldungDetailSchema,
    TicketNachrichtCreateSchema,
    TicketStatusUpdateSchema,
    SuccessSchema,
    HandwerkerOutSchema
)

router = Router(tags=["Tickets"])

@router.get("/", response=List[SchadenMeldungListSchema])
def list_tickets(request):
    """Gibt eine Liste aller Tickets zurück."""
    return SchadenMeldung.objects.all()

@router.get("/{ticket_id}", response=SchadenMeldungDetailSchema)
def get_ticket(request, ticket_id: int):
    """Gibt alle Details eines Tickets zurück."""
    ticket = get_object_or_404(SchadenMeldung, id=ticket_id)
    if not ticket.gelesen:
        ticket.gelesen = True
        ticket.save()
    return ticket

@router.patch("/{ticket_id}/status", response=SchadenMeldungListSchema)
def update_ticket_status(request, ticket_id: int, payload: TicketStatusUpdateSchema):
    """Ändert den Status eines Tickets."""
    ticket = get_object_or_404(SchadenMeldung, id=ticket_id)
    ticket.status = payload.status
    ticket.save()
    return ticket

# ==========================================
# 🔥 NEU: HANDWERKER LISTE FÜR DAS DROPDOWN
# ==========================================
@router.get("/handwerker/liste", response=List[HandwerkerOutSchema])
def list_handwerker(request):
    """Gibt alle registrierten Handwerker für das Dropdown zurück."""
    handwerker = Handwerker.objects.all()
    result = []
    for h in handwerker:
        result.append({
            "id": h.id,
            "firma": h.firma,
            "kontaktperson": h.kontaktperson,
            "branche": h.branche,
            "branche_label": h.get_branche_display(),
            "email": h.email,
            "telefon": h.telefon
        })
    return result


# 🔥 NOTIZEN SPEICHERN
@router.post("/{ticket_id}/nachrichten", response={201: SuccessSchema})
def add_ticket_message(request, ticket_id: int, payload: TicketNachrichtCreateSchema):
    """Fügt einem Ticket eine neue interne Notiz hinzu."""
    ticket = get_object_or_404(SchadenMeldung, id=ticket_id)

    absender = "Admin User"
    if request.user.is_authenticated:
        absender = request.user.get_full_name() or request.user.username

    TicketNachricht.objects.create(
        ticket=ticket,
        absender_name=absender,
        nachricht=payload.nachricht,
        typ='chat',
        is_intern=True
    )
    return 201, {"success": True}

@router.delete("/{ticket_id}", response={204: None})
def delete_ticket(request, ticket_id: int):
    """Löscht ein Ticket aus dem System."""
    ticket = get_object_or_404(SchadenMeldung, id=ticket_id)
    ticket.delete()
    return 204, None


# ==========================================
# 🔥 KOMMUNIKATION & HANDWERKER MAIL-ENDPUNKTE
# ==========================================

class SendMessageSchema(Schema):
    message: str

@router.post("/{ticket_id}/send-message", response={200: SuccessSchema, 400: dict})
def send_ticket_message(request, ticket_id: int, payload: SendMessageSchema):
    """Sendet eine offizielle Update-E-Mail an den Mieter."""
    ticket = get_object_or_404(SchadenMeldung, id=ticket_id)

    empfaenger_email = ticket.email_melder or (ticket.gemeldet_von.email if ticket.gemeldet_von else None)

    if not empfaenger_email:
        return 400, {"success": False, "error": "Keine E-Mail-Adresse für diesen Melder vorhanden."}

    betreff = f"Update zu Ihrer Meldung: {ticket.titel} (Ticket #{ticket.id})"
    status_text = payload.message

    try:
        html_content = render_to_string('emails/mieter_update_email.html', {
            'ticket': ticket,
            'nachricht': payload.message,
        })
        text_content = strip_tags(html_content)

        send_mail(
            subject=betreff,
            message=text_content,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'info@swissimmo.ch'),
            recipient_list=[empfaenger_email],
            html_message=html_content,
            fail_silently=False,
        )
    except Exception as e:
        status_text = f"FEHLER BEIM MAILVERSAND: {str(e)}\n\nGewünschte Nachricht war:\n{payload.message}"

    TicketNachricht.objects.create(
        ticket=ticket,
        absender_name=request.user.get_full_name() or request.user.username if request.user.is_authenticated else "Verwaltung",
        nachricht=status_text,
        typ='email',
        is_intern=False
    )

    return 200, {"success": True}


# 🔥 ANGEPASST: Erwartet nun die ID aus dem Dropdown
class AssignArtisanSchema(Schema):
    handwerker_id: int

@router.post("/{ticket_id}/assign-artisan", response={200: SuccessSchema, 400: dict})
def assign_artisan(request, ticket_id: int, payload: AssignArtisanSchema):
    """Generiert einen Arbeitsauftrag und sendet ihn dem Handwerker per Mail."""
    ticket = get_object_or_404(SchadenMeldung, id=ticket_id)

    # 🔥 Handwerker aus der Datenbank laden
    handwerker = get_object_or_404(Handwerker, id=payload.handwerker_id)

    if not handwerker.email:
        return 400, {"success": False, "error": "Der gewählte Handwerker hat keine E-Mail-Adresse hinterlegt."}

    betreff = f"Arbeitsauftrag: {ticket.titel} (Ticket #{ticket.id})"
    foto_url = request.build_absolute_uri(ticket.foto.url) if ticket.foto else None
    status_text = f"Arbeitsauftrag per E-Mail an {handwerker.firma} übermittelt."

    try:
        html_content = render_to_string('emails/handwerker_auftrag_email.html', {
            'ticket': ticket,
            'foto_url': foto_url,
            'verwaltung_name': request.user.get_full_name() or "swissImmo Verwaltung"
        })
        text_content = strip_tags(html_content)

        send_mail(
            subject=betreff,
            message=text_content,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'info@swissimmo.ch'),
            recipient_list=[handwerker.email],
            html_message=html_content,
            fail_silently=False,
        )

        # 🔥 Offiziellen Auftrag in der DB hinterlegen
        HandwerkerAuftrag.objects.create(
            ticket=ticket,
            handwerker=handwerker,
            status='offen',
            bemerkung='Automatisch generiert per E-Mail'
        )

    except Exception as e:
        status_text = f"FEHLER BEIM HANDWERKER-VERSAND an {handwerker.firma}: {str(e)}"

    ticket.status = 'warte_auf_handwerker'
    ticket.save()

    TicketNachricht.objects.create(
        ticket=ticket,
        absender_name="System",
        nachricht=status_text,
        typ='system',
        is_intern=True,
        empfaenger_handwerker=handwerker
    )

    return 200, {"success": True}