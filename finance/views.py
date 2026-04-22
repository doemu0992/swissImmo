# finance/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q, Sum
from django.contrib import messages
from django.utils import timezone
from decimal import Decimal

from .models import AbrechnungsPeriode, NebenkostenBeleg, Zahlungseingang
from .forms import AbrechnungsPeriodeForm, NebenkostenBelegForm, ZahlungseingangForm
from .services import berechne_abrechnung
from rentals.models import Mietvertrag
from core.utils.email_service import send_payment_reminder # <-- IMPORT HINZUGEFÜGT

# ==============================================================================
# 1. NEBENKOSTEN-ABRECHNUNGEN
# ==============================================================================

def abrechnung_liste(request):
    form = None
    if request.method == 'POST':
        if 'save_new_periode' in request.POST:
            form = AbrechnungsPeriodeForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Abrechnungsperiode erfolgreich erstellt.")
                return redirect('abrechnung_liste')
    elif request.GET.get('new'):
        form = AbrechnungsPeriodeForm()

    query = request.GET.get('q', '')
    if query:
        perioden = AbrechnungsPeriode.objects.filter(
            Q(bezeichnung__icontains=query) | Q(liegenschaft__strasse__icontains=query)
        ).distinct()
    else:
        perioden = AbrechnungsPeriode.objects.all()

    context = {
        'perioden': perioden.order_by('-start_datum'),
        'search_query': query,
        'form': form,
    }
    return render(request, 'finance/abrechnung_liste.html', context)


def abrechnung_detail(request, pk):
    periode = get_object_or_404(AbrechnungsPeriode, pk=pk)
    form = None
    beleg_form = NebenkostenBelegForm()

    edit_beleg_id = request.GET.get('edit_beleg')
    show_new_modal = request.GET.get('new_beleg')

    if edit_beleg_id:
        beleg_obj = get_object_or_404(NebenkostenBeleg, pk=edit_beleg_id, periode=periode)
        beleg_form = NebenkostenBelegForm(instance=beleg_obj)

    if request.method == 'POST':
        if 'save_periode' in request.POST:
            form = AbrechnungsPeriodeForm(request.POST, instance=periode)
            if form.is_valid():
                form.save()
                messages.success(request, "Periode aktualisiert.")
                return redirect('abrechnung_detail', pk=pk)

        elif 'add_beleg' in request.POST:
            beleg_form = NebenkostenBelegForm(request.POST, request.FILES)
            if beleg_form.is_valid():
                neuer_beleg = beleg_form.save(commit=False)
                neuer_beleg.periode = periode
                neuer_beleg.save()
                messages.success(request, "Beleg gespeichert!")
                return redirect('abrechnung_detail', pk=pk)
            else:
                show_new_modal = True

        elif 'save_edit_beleg' in request.POST:
            beleg_id = request.POST.get('beleg_id')
            beleg_obj = get_object_or_404(NebenkostenBeleg, pk=beleg_id, periode=periode)
            beleg_form = NebenkostenBelegForm(request.POST, request.FILES, instance=beleg_obj)
            if beleg_form.is_valid():
                beleg_form.save()
                messages.success(request, "Beleg aktualisiert!")
                return redirect('abrechnung_detail', pk=pk)
            else:
                edit_beleg_id = beleg_id

        elif 'delete_beleg' in request.POST:
            beleg_id = request.POST.get('delete_beleg')
            beleg_obj = get_object_or_404(NebenkostenBeleg, pk=beleg_id, periode=periode)
            beleg_obj.delete()
            messages.success(request, "Beleg gelöscht.")
            return redirect('abrechnung_detail', pk=pk)

        elif 'delete_periode' in request.POST:
            periode.delete()
            messages.success(request, "Abrechnung gelöscht.")
            return redirect('abrechnung_liste')

    elif request.GET.get('edit'):
        form = AbrechnungsPeriodeForm(instance=periode)

    belege = periode.belege.all().order_by('-datum')
    total_belege = belege.aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')

    try:
        ergebnis = berechne_abrechnung(periode.pk)
    except Exception as e:
        ergebnis = {'error': str(e)}

    context = {
        'periode': periode,
        'form': form,
        'beleg_form': beleg_form,
        'belege': belege,
        'total_belege': total_belege,
        'ergebnis': ergebnis,
        'edit_beleg_id': edit_beleg_id,
        'show_new_modal': show_new_modal,
    }
    return render(request, 'finance/abrechnung_detail.html', context)


# ==============================================================================
# 2. MIETEINNAHMEN & ZAHLUNGSLISTE (Neu / SaaS)
# ==============================================================================

def zahlung_liste(request):
    form = ZahlungseingangForm()
    show_modal = False

    if request.method == 'POST':
        if 'save_zahlung' in request.POST:
            form = ZahlungseingangForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Zahlung wurde erfolgreich verbucht!")
                return redirect('zahlung_liste')
            else:
                show_modal = True

        elif 'delete_zahlung' in request.POST:
            zahlung_id = request.POST.get('zahlung_id')
            Zahlungseingang.objects.filter(id=zahlung_id).delete()
            messages.success(request, "Zahlung wurde gelöscht.")
            return redirect('zahlung_liste')

    zahlungen = Zahlungseingang.objects.all().select_related(
        'vertrag__mieter',
        'vertrag__einheit',
        'vertrag__einheit__liegenschaft'
    ).order_by('-datum_eingang')

    return render(request, 'finance/zahlung_liste.html', {
        'zahlungen': zahlungen,
        'form': form,
        'show_modal': show_modal
    })


# ==============================================================================
# 3. MIETZINS-KONTROLLE (Soll/Ist Abgleich)
# ==============================================================================

def mietzins_kontrolle(request):
    heute = timezone.now().date()
    aktueller_monat = heute.replace(day=1)

    aktive_vertraege = Mietvertrag.objects.filter(aktiv=True).select_related('mieter', 'einheit', 'einheit__liegenschaft')
    kontrolle = []

    total_soll = Decimal('0.00')
    total_ist = Decimal('0.00')

    for v in aktive_vertraege:
        soll = v.netto_mietzins + v.nebenkosten
        ist = Zahlungseingang.objects.filter(
            vertrag=v,
            buchungs_monat=aktueller_monat
        ).aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')

        differenz = soll - ist
        total_soll += soll
        total_ist += ist

        if ist >= soll:
            status = 'Bezahlt'
        elif Decimal('0.00') < ist < soll:
            status = 'Teilzahlung'
        else:
            status = 'Offen'

        kontrolle.append({'vertrag': v, 'soll': soll, 'ist': ist, 'diff': differenz, 'status': status})

    context = {
        'kontrolle': kontrolle,
        'monat': aktueller_monat,
        'total_soll': total_soll,
        'total_ist': total_ist,
        'total_diff': total_soll - total_ist,
        'quote': round((total_ist / total_soll * 100), 1) if total_soll > 0 else 0
    }
    return render(request, 'finance/mietzins_kontrolle.html', context)


def mahnung_senden(request, vertrag_id):
    """
    Action: Sendet eine Zahlungserinnerung per Mail an den Mieter.
    """
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    heute = timezone.now().date()
    monat = heute.replace(day=1)

    # Berechne Soll/Ist für die Mail
    soll = vertrag.netto_mietzins + vertrag.nebenkosten
    ist = Zahlungseingang.objects.filter(vertrag=vertrag, buchungs_monat=monat).aggregate(total=Sum('betrag'))['total'] or Decimal('0.00')
    offen = soll - ist

    if not vertrag.mieter.email:
        messages.error(request, f"Fehler: Mieter {vertrag.mieter} hat keine E-Mail-Adresse hinterlegt.")
    elif offen <= 0:
        messages.info(request, f"Mieter {vertrag.mieter} hat bereits vollständig bezahlt.")
    else:
        # Hier wird die neue Funktion aus dem email_service aufgerufen:
        send_payment_reminder(vertrag, monat, offen)
        messages.success(request, f"Zahlungserinnerung wurde an {vertrag.mieter.email} versendet.")

    return redirect('mietzins_kontrolle')