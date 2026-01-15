from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.mail import send_mail

# Imports
from core.models import SchadenMeldung, TicketNachricht
from core.forms import SchadenForm, NachrichtForm

# --- 1. TICKET ERSTELLEN (Bleibt gleich, nur zur Vollständigkeit) ---
def ticket_erstellen(request):
    if request.method == 'POST':
        form = SchadenForm(request.POST, request.FILES)
        if form.is_valid():
            ticket = form.save()

            if ticket.mieter_email:
                try:
                    ticket_link = request.build_absolute_uri(reverse('ticket_detail_public', args=[ticket.uuid]))
                    betreff = f"Eingang: Ticket #{ticket.id} ({ticket.titel})"
                    nachricht = f"""Guten Tag,

Wir haben Ihre Schadenmeldung erhalten.

Titel: {ticket.titel}
Status: {ticket.get_status_display()}

Status prüfen & Chatten:
{ticket_link}

Freundliche Grüsse,
Ihre Verwaltung"""

                    send_mail(betreff, nachricht, settings.DEFAULT_FROM_EMAIL, [ticket.mieter_email], fail_silently=False)
                except Exception as e:
                    print(f"Mail-Fehler: {e}")

            messages.success(request, f"Schaden gemeldet! Bestätigung an {ticket.mieter_email} gesendet.")
            return redirect('ticket_detail_public', uuid=ticket.uuid)
    else:
        form = SchadenForm()

    return render(request, 'core/ticket_create.html', {'form': form})


# --- 2. ÖFFENTLICH: ANSICHT FÜR MIETER ---
def ticket_detail_public(request, uuid):
    ticket = get_object_or_404(SchadenMeldung, uuid=uuid)

    if request.method == 'POST':
        form = NachrichtForm(request.POST, request.FILES)
        if form.is_valid():
            msg = form.save(commit=False)
            msg.ticket = ticket

            # Name des Absenders
            if ticket.gemeldet_von:
                msg.absender_name = f"{ticket.gemeldet_von.vorname} {ticket.gemeldet_von.nachname}"
            else:
                msg.absender_name = "Mieter"

            msg.is_von_verwaltung = False
            msg.save()

            # Status Update bei Bedarf
            if ticket.status == 'warte_auf_mieter':
                ticket.status = 'in_bearbeitung'
                ticket.save()

            # --- NEU: E-MAIL AN VERWALTUNG (DICH) ---
            try:
                admin_link = request.build_absolute_uri(reverse('ticket_detail_admin', args=[ticket.pk]))
                betreff_admin = f"Neues im Ticket #{ticket.id}: {ticket.titel}"
                nachricht_admin = f"""Ein Mieter hat geantwortet!

Ticket: #{ticket.id}
Titel: {ticket.titel}
Nachricht:
"{msg.nachricht}"

Zum Admin-Bereich:
{admin_link}
"""
                # Sendet an die Adresse, die in settings.DEFAULT_FROM_EMAIL steht (also an dich selbst)
                send_mail(betreff_admin, nachricht_admin, settings.DEFAULT_FROM_EMAIL, [settings.DEFAULT_FROM_EMAIL], fail_silently=True)
            except: pass
            # -----------------------------------------

            messages.success(request, "Antwort gesendet.")
            return redirect('ticket_detail_public', uuid=uuid)
    else:
        form = NachrichtForm()

    chat = ticket.nachrichten.filter(is_intern=False)

    return render(request, 'core/ticket_public.html', {
        'ticket': ticket,
        'chat': chat,
        'form': form
    })


# --- 3. INTERN: ADMIN ANSICHT ---
@login_required
def ticket_detail_admin(request, pk):
    ticket = get_object_or_404(SchadenMeldung, pk=pk)

    if request.method == 'POST':

        # A) STATUS ÄNDERN
        if 'status_update' in request.POST:
            alter_status = ticket.get_status_display()
            neuer_status_key = request.POST.get('status')

            if neuer_status_key != ticket.status:
                ticket.status = neuer_status_key
                ticket.save()

                # --- NEU: E-MAIL AN MIETER BEI STATUS-ÄNDERUNG ---
                if ticket.mieter_email:
                    try:
                        ticket_link = request.build_absolute_uri(reverse('ticket_detail_public', args=[ticket.uuid]))
                        betreff_mieter = f"Status-Update: Ticket #{ticket.id}"
                        nachricht_mieter = f"""Guten Tag,

Der Status Ihres Tickets wurde geändert.

Neuer Status: {ticket.get_status_display()}
(Vorher: {alter_status})

Details einsehen:
{ticket_link}

Freundliche Grüsse,
Ihre Verwaltung"""

                        send_mail(betreff_mieter, nachricht_mieter, settings.DEFAULT_FROM_EMAIL, [ticket.mieter_email], fail_silently=True)
                        messages.success(request, f"Mieter wurde über Statuswechsel informiert.")
                    except:
                        messages.warning(request, "Status gespeichert, aber E-Mail konnte nicht gesendet werden.")
                # -------------------------------------------------

            return redirect('ticket_detail_admin', pk=pk)

        # B) NACHRICHT SENDEN
        else:
            form = NachrichtForm(request.POST, request.FILES)
            if form.is_valid():
                msg = form.save(commit=False)
                msg.ticket = ticket
                msg.absender_name = "Verwaltung"
                msg.is_von_verwaltung = True

                if request.POST.get('is_intern'):
                    msg.is_intern = True

                msg.save()

                # Optional: E-Mail an Mieter bei neuer Nachricht (falls nicht intern)
                if not msg.is_intern and ticket.mieter_email:
                     try:
                        ticket_link = request.build_absolute_uri(reverse('ticket_detail_public', args=[ticket.uuid]))
                        send_mail(
                            f"Neue Nachricht zu Ticket #{ticket.id}",
                            f"Die Verwaltung hat geantwortet:\n\n\"{msg.nachricht}\"\n\nHier antworten: {ticket_link}",
                            settings.DEFAULT_FROM_EMAIL,
                            [ticket.mieter_email],
                            fail_silently=True
                        )
                     except: pass

                messages.success(request, "Antwort gespeichert.")
                return redirect('ticket_detail_admin', pk=pk)

    else:
        form = NachrichtForm()

    return render(request, 'core/ticket_admin.html', {
        'ticket': ticket,
        'form': form,
        'STATUS_CHOICES': SchadenMeldung.STATUS_CHOICES
    })