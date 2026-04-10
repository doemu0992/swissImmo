# crm/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from .models import Mieter
from .forms import MieterForm

def mieter_liste(request):
    form = None

    if request.method == 'POST':
        if 'save_new_mieter' in request.POST:
            form = MieterForm(request.POST)
            if form.is_valid():
                form.save()
                return redirect('mieter_liste')
    elif request.GET.get('new'):
        form = MieterForm()

    query = request.GET.get('q', '')
    if query:
        # Sucht jetzt auch in Firmennamen!
        mieter_list = Mieter.objects.filter(
            Q(vorname__icontains=query) |
            Q(nachname__icontains=query) |
            Q(email__icontains=query) |
            Q(firma__icontains=query)
        ).distinct()
    else:
        mieter_list = Mieter.objects.all()

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
        # 1. Mieter bearbeiten
        if 'save_mieter' in request.POST:
            form = MieterForm(request.POST, instance=mieter)
            if form.is_valid():
                form.save()
                return redirect('mieter_detail', pk=pk)

        # 2. Mieter löschen
        elif 'delete_mieter' in request.POST:
            mieter.delete()
            return redirect('mieter_liste')

    elif request.GET.get('edit'):
        # Formular zum Bearbeiten laden
        form = MieterForm(instance=mieter)

    # 🔥 HIER IST DER FIX: .vertraege.all() anstatt dem Standard-Namen 🔥
    vertraege = mieter.vertraege.all().order_by('-aktiv', '-beginn')

    context = {
        'mieter': mieter,
        'form': form,
        'vertraege': vertraege,
    }
    return render(request, 'crm/mieter_detail.html', context)