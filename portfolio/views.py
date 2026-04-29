import urllib.parse
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib import messages

from .models import Liegenschaft, Einheit
from .forms import LiegenschaftForm, EinheitForm
from .services import sync_liegenschaft_with_gwr, get_liegenschaft_stats

# WICHTIG: Import für den Live-Abgleich der Vermietungen
from rentals.models import Mietvertrag

# ========================================================
# 1. DEINE BESTEHENDEN LEGACY VIEWS
# ========================================================

def liegenschaft_liste(request):
    form = None
    if request.method == 'POST':
        if 'save_new_liegenschaft' in request.POST:
            form = LiegenschaftForm(request.POST)
            if form.is_valid():
                neue_liegenschaft = form.save()
                sync_result = sync_liegenschaft_with_gwr(neue_liegenschaft)

                if sync_result.get('error'):
                    messages.error(request, f"Fehler beim EGID Import: {sync_result['error']}")
                else:
                    if sync_result.get('egid_found'):
                        messages.info(request, f"EGID automatisch gefunden: {sync_result['egid_found']}")
                    if sync_result.get('units_created') > 0:
                        messages.success(request, f"Erfolg: {sync_result['units_created']} Wohnungen automatisch vom Bund geladen!")

                return redirect('liegenschaft_liste')

    elif request.GET.get('new'):
        form = LiegenschaftForm()

    query = request.GET.get('q', '')
    if query:
        liegenschaften = Liegenschaft.objects.filter(
            Q(strasse__icontains=query) | Q(ort__icontains=query) | Q(plz__icontains=query)
        ).distinct()
    else:
        liegenschaften = Liegenschaft.objects.all()

    context = {
        'liegenschaften': liegenschaften.order_by('strasse'),
        'search_query': query,
        'form': form,
    }
    return render(request, 'portfolio/liegenschaft_liste.html', context)


def liegenschaft_detail(request, pk):
    liegenschaft = get_object_or_404(Liegenschaft, pk=pk)
    form = None
    einheit_form = None
    active_einheit_id = None

    if request.method == 'POST':
        if 'save_liegenschaft' in request.POST:
            form = LiegenschaftForm(request.POST, instance=liegenschaft)
            if form.is_valid():
                form.save()
                return redirect('liegenschaft_detail', pk=pk)

        elif 'delete_liegenschaft' in request.POST:
            liegenschaft.delete()
            return redirect('liegenschaft_liste')

        elif 'save_einheit' in request.POST:
            active_einheit_id = request.POST.get('einheit_id')
            einheit = get_object_or_404(Einheit, pk=active_einheit_id, liegenschaft=liegenschaft)
            einheit_form = EinheitForm(request.POST, instance=einheit)
            if einheit_form.is_valid():
                einheit_form.save()
                return redirect('liegenschaft_detail', pk=pk)

        elif 'save_new_einheit' in request.POST:
            einheit_form = EinheitForm(request.POST)
            if einheit_form.is_valid():
                neue_einheit = einheit_form.save(commit=False)
                neue_einheit.liegenschaft = liegenschaft
                neue_einheit.save()
                return redirect('liegenschaft_detail', pk=pk)

        elif 'delete_einheit' in request.POST:
            einheit_id = request.POST.get('einheit_id')
            Einheit.objects.filter(pk=einheit_id, liegenschaft=liegenschaft).delete()
            return redirect('liegenschaft_detail', pk=pk)

    elif request.GET.get('edit'):
        form = LiegenschaftForm(instance=liegenschaft)
    elif request.GET.get('edit_einheit'):
        active_einheit_id = request.GET.get('edit_einheit')
        einheit = get_object_or_404(Einheit, pk=active_einheit_id, liegenschaft=liegenschaft)
        einheit_form = EinheitForm(instance=einheit)
    elif request.GET.get('new_einheit'):
        einheit_form = EinheitForm()

    einheiten = liegenschaft.einheiten.all().order_by('bezeichnung')
    aktive_vertraege = Mietvertrag.objects.filter(aktiv=True)
    belegte_haupt_ids = list(aktive_vertraege.values_list('einheit_id', flat=True))
    belegte_neben_ids = list(aktive_vertraege.values_list('nebenobjekte', flat=True))
    alle_belegten_ids = set([id for id in (belegte_haupt_ids + belegte_neben_ids) if id is not None])

    for e in einheiten:
        e.ist_vermietet = e.id in alle_belegten_ids

    stats = get_liegenschaft_stats(liegenschaft)
    addr_query = urllib.parse.quote(f"{liegenschaft.strasse}, {liegenschaft.plz} {liegenschaft.ort}") if liegenschaft.strasse else ""
    map_url = f"https://maps.google.com/maps?q={addr_query}&t=&z=15&ie=UTF8&iwloc=&output=embed" if addr_query else ""

    context = {
        'liegenschaft': liegenschaft,
        'einheiten': einheiten,
        'stats': stats,
        'form': form,
        'einheit_form': einheit_form,
        'active_einheit_id': active_einheit_id,
        'map_url': map_url,
    }
    return render(request, 'portfolio/liegenschaft_detail.html', context)

# ========================================================
# 2. UNSER NEUER VUE.JS TEST VIEW
# ========================================================

def vue_test_view(request):
    """
    Rendert das moderne Vue.js Template, das seine Daten über die API zieht.
    """
    return render(request, 'portfolio/vue_test.html')