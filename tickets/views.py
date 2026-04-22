# tickets/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from .models import SchadenMeldung, TicketNachricht, HandwerkerAuftrag
from .forms import SchadenMeldungForm, HandwerkerAuftragForm
from .services import add_chat_message, create_handwerker_auftrag

def ticket_liste(request):
    form = None

    if request.method == 'POST':
        if 'save_new_ticket' in request.POST:
            form = SchadenMeldungForm(request.POST, request.FILES)
            if form.is_valid():
                form.save()
                return redirect('ticket_liste')
    elif request.GET.get('new'):
        form = SchadenMeldungForm()

    query = request.GET.get('q', '')
    if query:
        tickets = SchadenMeldung.objects.filter(
            Q(titel__icontains=query) |
            Q(beschreibung__icontains=query) |
            Q(liegenschaft__strasse__icontains=query)
        ).distinct()
    else:
        tickets = SchadenMeldung.objects.all()

    # Wir gruppieren die Tickets für das Kanban Board
    tickets_neu = tickets.filter(status='neu').order_by('-erstellt_am')
    tickets_in_bearbeitung = tickets.filter(status__in=['in_bearbeitung', 'warte_auf_mieter']).order_by('-erstellt_am')
    tickets_erledigt = tickets.filter(status='erledigt').order_by('-erstellt_am')[:20] # Max 20 anzeigen, sonst wird es zu voll

    context = {
        'tickets_neu': tickets_neu,
        'tickets_in_bearbeitung': tickets_in_bearbeitung,
        'tickets_erledigt': tickets_erledigt,
        'search_query': query,
        'form': form,
    }
    return render(request, 'tickets/ticket_liste.html', context)


def ticket_detail(request, pk):
    ticket = get_object_or_404(SchadenMeldung, pk=pk)
    form = None
    auftrag_form = HandwerkerAuftragForm()

    if not ticket.gelesen:
        ticket.gelesen = True
        ticket.save()

    if request.method == 'POST':
        # 1. Ticket bearbeiten
        if 'save_ticket' in request.POST:
            form = SchadenMeldungForm(request.POST, request.FILES, instance=ticket)
            if form.is_valid():
                form.save()
                return redirect('ticket_detail', pk=pk)

        # 2. Chat-Nachricht senden (Über Service)
        elif 'add_message' in request.POST:
            nachricht_text = request.POST.get('nachricht')
            if nachricht_text:
                add_chat_message(ticket, nachricht_text)
            return redirect('ticket_detail', pk=pk)

        # 3. Handwerker beauftragen (Über Service)
        elif 'add_auftrag' in request.POST:
            auftrag_form = HandwerkerAuftragForm(request.POST)
            if auftrag_form.is_valid():
                neuer_auftrag = auftrag_form.save(commit=False)
                create_handwerker_auftrag(ticket, neuer_auftrag.handwerker, neuer_auftrag.bemerkung)
                return redirect('ticket_detail', pk=pk)

        # 4. Ticket löschen
        elif 'delete_ticket' in request.POST:
            ticket.delete()
            return redirect('ticket_liste')

    elif request.GET.get('edit'):
        form = SchadenMeldungForm(instance=ticket)

    nachrichten = ticket.nachrichten.all().order_by('erstellt_am')
    auftraege = ticket.handwerker_auftraege.all().order_by('-beauftragt_am')

    context = {
        'ticket': ticket,
        'form': form,
        'nachrichten': nachrichten,
        'auftraege': auftraege,
        'auftrag_form': auftrag_form,
    }
    return render(request, 'tickets/ticket_detail.html', context)


# Endpoint für Status-Wechsel im Board (Unterstützt Buttons & Drag-and-Drop)
def update_ticket_status(request, pk, new_status):
    ticket = get_object_or_404(SchadenMeldung, pk=pk)

    # Status sicher updaten
    ticket.status = new_status
    ticket.save()

    # 1. Wenn die Anfrage per Drag & Drop (JavaScript fetch) reinkommt
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({'success': True, 'new_status': new_status})

    # 2. Wenn normal auf den Button geklickt wurde (Alpine AJAX Formular)
    return redirect('ticket_liste')