# portfolio/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib import messages
from .models import Liegenschaft, Einheit
from .forms import LiegenschaftForm, EinheitForm

# Import der GWR-Schnittstelle (vom Bund)
try:
    from core.gwr import get_egid_from_address, get_units_from_bfs
except ImportError:
    get_egid_from_address = None
    get_units_from_bfs = None

def liegenschaft_liste(request):
    form = None

    if request.method == 'POST':
        if 'save_new_liegenschaft' in request.POST:
            form = LiegenschaftForm(request.POST)
            if form.is_valid():
                neue_liegenschaft = form.save()

                # --- NEU: DIE EGID MAGIE (Aus der admin.py übernommen) ---
                if get_egid_from_address and get_units_from_bfs:
                    try:
                        # 1. EGID über die Adresse finden, falls nicht manuell eingegeben
                        if not neue_liegenschaft.egid:
                            found = get_egid_from_address(neue_liegenschaft.strasse, neue_liegenschaft.plz, neue_liegenschaft.ort)
                            if found:
                                neue_liegenschaft.egid = found
                                neue_liegenschaft.save()
                                messages.info(request, f"EGID gefunden: {neue_liegenschaft.egid}")

                        # 2. Einheiten vom Bundesamt (BFS) laden
                        if neue_liegenschaft.egid and neue_liegenschaft.einheiten.count() == 0:
                            data = get_units_from_bfs(neue_liegenschaft.egid)
                            cnt = 0
                            for i in data:
                                if i.get('is_meta'):
                                    if i.get('baujahr'):
                                        neue_liegenschaft.baujahr = i['baujahr']
                                        neue_liegenschaft.save()
                                    continue
                                Einheit.objects.create(
                                    liegenschaft=neue_liegenschaft,
                                    bezeichnung=i['bezeichnung'],
                                    ewid=i['ewid'],
                                    zimmer=i['zimmer'],
                                    etage=i['etage'],
                                    flaeche_m2=i['flaeche'],
                                    typ='whg'
                                )
                                cnt += 1
                            if cnt > 0:
                                messages.success(request, f"Erfolg: {cnt} Wohnungen automatisch vom Bund geladen!")
                    except Exception as e:
                        messages.error(request, f"Fehler beim EGID Import: {e}")
                # --- ENDE EGID MAGIE ---

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
        # 1. Liegenschaft bearbeiten
        if 'save_liegenschaft' in request.POST:
            form = LiegenschaftForm(request.POST, instance=liegenschaft)
            if form.is_valid():
                form.save()
                return redirect('liegenschaft_detail', pk=pk)

        # 2. Liegenschaft löschen
        elif 'delete_liegenschaft' in request.POST:
            liegenschaft.delete()
            return redirect('liegenschaft_liste')

        # 3. Einheit bearbeiten
        elif 'save_einheit' in request.POST:
            active_einheit_id = request.POST.get('einheit_id')
            einheit = get_object_or_404(Einheit, pk=active_einheit_id, liegenschaft=liegenschaft)
            einheit_form = EinheitForm(request.POST, instance=einheit)
            if einheit_form.is_valid():
                einheit_form.save()
                return redirect('liegenschaft_detail', pk=pk)

        # 4. Neue Einheit anlegen
        elif 'save_new_einheit' in request.POST:
            einheit_form = EinheitForm(request.POST)
            if einheit_form.is_valid():
                neue_einheit = einheit_form.save(commit=False)
                neue_einheit.liegenschaft = liegenschaft
                neue_einheit.save()
                return redirect('liegenschaft_detail', pk=pk)

        # 5. Einheit löschen
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

    # --- Bestehende Logik ---
    einheiten = liegenschaft.einheiten.all().order_by('bezeichnung')
    total_einheiten = einheiten.count()
    vermietet = sum(1 for e in einheiten if getattr(e, 'aktiver_vertrag', False))
    leerstand = total_einheiten - vermietet
    soll_miete = sum(float(getattr(e, 'nettomiete_aktuell', 0) or 0) + float(getattr(e, 'nebenkosten_aktuell', 0) or 0) for e in einheiten)
    ist_miete = sum(float(getattr(e, 'nettomiete_aktuell', 0) or 0) + float(getattr(e, 'nebenkosten_aktuell', 0) or 0) for e in einheiten if getattr(e, 'aktiver_vertrag', False))

    context = {
        'liegenschaft': liegenschaft, 'einheiten': einheiten,
        'stats': {'total': total_einheiten, 'vermietet': vermietet, 'leerstand': leerstand, 'soll_miete': soll_miete, 'ist_miete': ist_miete},
        'form': form, 'einheit_form': einheit_form, 'active_einheit_id': active_einheit_id,
    }
    return render(request, 'portfolio/liegenschaft_detail.html', context)