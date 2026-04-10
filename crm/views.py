# crm/views.py
import base64
from django.core.files.base import ContentFile
from django.shortcuts import render, get_object_or_404, redirect
from .models import Mieter, Mandant
from .forms import MieterForm
from .services import search_mieter, onboard_new_mieter

def mieter_liste(request):
    form = None
    if request.method == 'POST':
        if 'save_new_mieter' in request.POST:
            form = MieterForm(request.POST)
            if form.is_valid():
                neuer_mieter = form.save()
                onboard_new_mieter(neuer_mieter)
                return redirect('mieter_liste')
    elif request.GET.get('new'):
        form = MieterForm()

    query = request.GET.get('q', '')
    mieter_list = search_mieter(query)

    context = {
        'mieter_list': mieter_list.order_by('nachname', 'vorname'),
        'search_query': query,
        'form': form,
    }
    return render(request, 'crm/mieter_liste.html', context)

def mieter_detail(request, pk):
    mieter = get_object_or_404(Mieter, pk=pk)
    form = None
    if request.method == 'POST':
        if 'save_mieter' in request.POST:
            form = MieterForm(request.POST, instance=mieter)
            if form.is_valid():
                form.save()
                return redirect('mieter_detail', pk=pk)
        elif 'delete_mieter' in request.POST:
            mieter.delete()
            return redirect('mieter_liste')
    elif request.GET.get('edit'):
        form = MieterForm(instance=mieter)

    vertraege = mieter.vertraege.all().order_by('-aktiv', '-beginn')
    context = {
        'mieter': mieter,
        'form': form,
        'vertraege': vertraege,
    }
    return render(request, 'crm/mieter_detail.html', context)

def mandant_edit(request, pk):
    """View zum Bearbeiten des Mandanten inklusive Signature Pad Logik."""
    mandant = get_object_or_404(Mandant, pk=pk)

    if request.method == 'POST':
        signature_data = request.POST.get('signature_data')

        # Falls eine neue Zeichnung vorliegt: Base64 zu PNG umwandeln
        if signature_data and signature_data.startswith('data:image/png;base64,'):
            format, imgstr = signature_data.split(';base64,')
            data = ContentFile(base64.b64decode(imgstr), name=f"signature_{mandant.id}.png")
            mandant.unterschrift_bild = data

        mandant.firma_oder_name = request.POST.get('firma_oder_name')
        mandant.strasse = request.POST.get('strasse')
        mandant.plz = request.POST.get('plz')
        mandant.ort = request.POST.get('ort')
        mandant.save()
        messages.success(request, "Mandantendaten und Unterschrift gespeichert.")
        return redirect('admin:crm_mandant_change', pk)

    return render(request, 'crm/mandant_edit.html', {'mandant': mandant})