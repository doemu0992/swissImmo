# crm/views.py
import base64
from django.core.files.base import ContentFile
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import Mieter, Mandant, Verwaltung, Handwerker
from .forms import MieterForm, VerwaltungForm, MandantForm, HandwerkerForm
from .services import search_mieter, onboard_new_mieter

def mieter_liste(request):
    form = None
    if request.method == 'POST':
        if 'save_new_mieter' in request.POST:
            form = MieterForm(request.POST)
            if form.is_valid():
                neuer_mieter = form.save()
                onboard_new_mieter(neuer_mieter)
                messages.success(request, "Mieter erfolgreich angelegt.")
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
                messages.success(request, "Mieterdaten aktualisiert.")
                return redirect('mieter_detail', pk=pk)
        elif 'delete_mieter' in request.POST:
            mieter.delete()
            messages.success(request, "Mieter gelöscht.")
            return redirect('mieter_liste')
    elif request.GET.get('edit'):
        form = MieterForm(instance=mieter)

    vertraege = mieter.vertraege.all().order_by('-aktiv', '-beginn')
    tickets = mieter.gemeldete_schaeden.all().order_by('-erstellt_am')

    context = {
        'mieter': mieter,
        'form': form,
        'vertraege': vertraege,
        'tickets': tickets,
    }
    return render(request, 'crm/mieter_detail.html', context)

# ==============================================================================
# ZENTRALES EINSTELLUNGS-DASHBOARD (Modul 7)
# ==============================================================================

def settings_view(request):
    # 1. Verwaltung laden oder erstellen
    verwaltung = Verwaltung.objects.first()
    if not verwaltung:
        verwaltung = Verwaltung.objects.create(firma="Meine neue Verwaltung")

    verwaltung_form = VerwaltungForm(instance=verwaltung)

    # 2. Listen laden
    mandanten = Mandant.objects.all().order_by('firma_oder_name')
    handwerker = Handwerker.objects.all().order_by('gewerk', 'firma')

    # 3. Formular-Logik für Bearbeitungs-Modals
    active_tab = request.GET.get('tab', 'company')
    edit_obj_id = request.GET.get('edit_id')
    modal_form = None
    modal_title = ""

    if active_tab == 'mandanten' and edit_obj_id:
        if edit_obj_id == 'new':
            modal_form = MandantForm()
            modal_title = "Neuer Eigentümer"
        else:
            m = get_object_or_404(Mandant, pk=edit_obj_id)
            modal_form = MandantForm(instance=m)
            modal_title = f"Eigentümer: {m.firma_oder_name}"

    if active_tab == 'handwerker' and edit_obj_id:
        if edit_obj_id == 'new':
            modal_form = HandwerkerForm()
            modal_title = "Neuer Handwerker"
        else:
            h = get_object_or_404(Handwerker, pk=edit_obj_id)
            modal_form = HandwerkerForm(instance=h)
            modal_title = f"Handwerker: {h.firma}"

    # 4. Speichern-Logik (POST)
    if request.method == 'POST':

        # --- TAB 1: Verwaltung speichern ---
        if 'save_verwaltung' in request.POST:
            verwaltung_form = VerwaltungForm(request.POST, request.FILES, instance=verwaltung)
            if verwaltung_form.is_valid():
                vw = verwaltung_form.save(commit=False)

                # Digitale Unterschrift (Base64) verarbeiten
                sig_data = request.POST.get('signature_data')
                if sig_data and sig_data.startswith('data:image/png;base64,'):
                    format, imgstr = sig_data.split(';base64,')
                    data = ContentFile(base64.b64decode(imgstr), name=f"sig_vw_{vw.id or 'new'}.png")
                    vw.unterschrift_bild = data

                vw.save()
                messages.success(request, "Unternehmensdaten und Unterschrift gespeichert.")
                return redirect('/crm/settings/?tab=company')

        # --- TAB 2: Mandant/Eigentümer speichern ---
        elif 'save_mandant' in request.POST:
            instance = None
            if edit_obj_id and edit_obj_id != 'new':
                instance = get_object_or_404(Mandant, pk=edit_obj_id)
            form = MandantForm(request.POST, request.FILES, instance=instance)
            if form.is_valid():
                m = form.save(commit=False)

                # Digitale Unterschrift (Base64) verarbeiten
                sig_data = request.POST.get('signature_data')
                if sig_data and sig_data.startswith('data:image/png;base64,'):
                    format, imgstr = sig_data.split(';base64,')
                    data = ContentFile(base64.b64decode(imgstr), name=f"sig_man_{m.id or 'new'}.png")
                    m.unterschrift_bild = data

                m.save()
                messages.success(request, "Eigentümer und Unterschrift gespeichert.")
                return redirect('/crm/settings/?tab=mandanten')

        # --- TAB 3: Handwerker speichern ---
        elif 'save_handwerker' in request.POST:
            instance = None
            if edit_obj_id and edit_obj_id != 'new':
                instance = get_object_or_404(Handwerker, pk=edit_obj_id)
            form = HandwerkerForm(request.POST, instance=instance)
            if form.is_valid():
                form.save()
                messages.success(request, "Handwerker gespeichert.")
                return redirect('/crm/settings/?tab=handwerker')

        # --- LÖSCHEN ---
        elif 'delete_obj' in request.POST:
            obj_type = request.POST.get('obj_type')
            obj_id = request.POST.get('obj_id')
            if obj_type == 'mandant':
                Mandant.objects.filter(pk=obj_id).delete()
            elif obj_type == 'handwerker':
                Handwerker.objects.filter(pk=obj_id).delete()
            messages.success(request, "Eintrag gelöscht.")
            return redirect(f'/crm/settings/?tab={active_tab}')

    context = {
        'verwaltung': verwaltung,
        'verwaltung_form': verwaltung_form,
        'mandanten': mandanten,
        'handwerker': handwerker,
        'active_tab': active_tab,
        'modal_form': modal_form,
        'modal_title': modal_title,
        'edit_obj_id': edit_obj_id,
    }
    return render(request, 'crm/settings.html', context)