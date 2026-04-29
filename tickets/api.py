# tickets/api.py
from ninja import Router
from django.shortcuts import get_object_or_404
from typing import List
from .models import SchadenMeldung, TicketNachricht
from .schemas import (
    SchadenMeldungListSchema,
    SchadenMeldungDetailSchema,
    TicketNachrichtCreateSchema,
    TicketStatusUpdateSchema,
    SuccessSchema
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

# 🔥 NOTIZEN SPEICHERN
@router.post("/{ticket_id}/nachrichten", response={201: SuccessSchema})
def add_ticket_message(request, ticket_id: int, payload: TicketNachrichtCreateSchema):
    """Fügt einem Ticket eine neue interne Notiz hinzu."""
    ticket = get_object_or_404(SchadenMeldung, id=ticket_id)

    # Sicherer Fallback für den Absendernamen
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