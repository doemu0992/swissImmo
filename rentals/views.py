# rentals/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib import messages
from .models import Mietvertrag, MietzinsAnpassung, Dokument
from .forms import MietvertragForm
from .services import archiviere_vertrag_wenn_unterzeichnet

def mietvertrag_liste(request):
    form = None

    if request.method == 'POST':
        if 'save_new_vertrag' in request.POST:
            form = MietvertragForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Mietvertrag wurde erfolgreich angelegt.")
                return redirect('mietvertrag_liste')

    elif request.GET.get('new'):
        form = MietvertragForm()

    query = request.GET.get('q', '')
    if query:
        # Sucht im Namen des Mieters oder in der Bezeichnung der Einheit
        vertraege = Mietvertrag.objects.filter(
            Q(mieter__vorname__icontains=query) |
            Q(mieter__nachname__icontains=query) |
            Q(mieter__firma__icontains=query) |
            Q(einheit__bezeichnung__icontains=query)
        ).distinct()
    else:
        vertraege = Mietvertrag.objects.all()

    context = {
        'vertraege': vertraege.order_by('-aktiv', '-beginn'),
        'search_query': query,
        'form': form,
    }
    return render(request, 'rentals/mietvertrag_liste.html', context)


def mietvertrag_detail(request, pk):
    vertrag = get_object_or_404(Mietvertrag, pk=pk)
    form = None

    if request.method == 'POST':
        # 1. Vertrag speichern & Archivierungs-Logik prüfen
        if 'save_vertrag' in request.POST:
            form = MietvertragForm(request.POST, request.FILES, instance=vertrag)
            if form.is_valid():
                gespeicherter_vertrag = form.save()

                # --- Service aufrufen statt Logik in der View ---
                wurde_archiviert = archiviere_vertrag_wenn_unterzeichnet(gespeicherter_vertrag)
                if wurde_archiviert:
                    messages.success(request, "✅ Vertrag wurde automatisch im Archiv abgelegt.")
                else:
                    messages.success(request, "Vertrag aktualisiert.")

                return redirect('mietvertrag_detail', pk=pk)

        # 2. Vertrag löschen
        elif 'delete_vertrag' in request.POST:
            vertrag.delete()
            messages.success(request, "Mietvertrag wurde gelöscht.")
            return redirect('mietvertrag_liste')

    elif request.GET.get('edit'):
        form = MietvertragForm(instance=vertrag)

    anpassungen = vertrag.anpassungen.all().order_by('-wirksam_ab')
    dokumente = vertrag.dokumente.all().order_by('-erstellt_am')

    context = {
        'vertrag': vertrag,
        'form': form,
        'anpassungen': anpassungen,
        'dokumente': dokumente,
    }
    return render(request, 'rentals/mietvertrag_detail.html', context)

# ========================================================
# NEUER VUE.JS VIEW FÜR MIETVERTRÄGE
# ========================================================

def rentals_vue_test_view(request):
    """Rendert das neue Vue.js Dashboard für Mietverträge"""
    return render(request, 'rentals/vue_test.html')