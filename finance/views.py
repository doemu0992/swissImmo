# finance/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q, Sum
from django.contrib import messages
from .models import AbrechnungsPeriode, NebenkostenBeleg
from .forms import AbrechnungsPeriodeForm, NebenkostenBelegForm
from .services import berechne_abrechnung  # <-- Sauberer, direkter Import aus dem Service

def abrechnung_liste(request):
    form = None
    if request.method == 'POST':
        if 'save_new_periode' in request.POST:
            form = AbrechnungsPeriodeForm(request.POST)
            if form.is_valid():
                form.save()
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
        # 1. Periode bearbeiten
        if 'save_periode' in request.POST:
            form = AbrechnungsPeriodeForm(request.POST, instance=periode)
            if form.is_valid():
                form.save()
                return redirect('abrechnung_detail', pk=pk)

        # 2. NEUER Beleg
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

        # 3. BELEG BEARBEITEN
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

        # 4. BELEG LÖSCHEN
        elif 'delete_beleg' in request.POST:
            beleg_id = request.POST.get('delete_beleg')
            beleg_obj = get_object_or_404(NebenkostenBeleg, pk=beleg_id, periode=periode)
            beleg_obj.delete()
            messages.success(request, "Beleg gelöscht.")
            return redirect('abrechnung_detail', pk=pk)

        # 5. Periode löschen
        elif 'delete_periode' in request.POST:
            periode.delete()
            return redirect('abrechnung_liste')

    elif request.GET.get('edit'):
        form = AbrechnungsPeriodeForm(instance=periode)

    belege = periode.belege.all().order_by('-datum')
    total_belege = belege.aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')

    # Den neuen Service sauber und direkt aufrufen
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