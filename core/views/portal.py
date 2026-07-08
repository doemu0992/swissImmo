# core/views/portal.py
"""
Eigentümer-Portal (read-only).

Ein Mandant (Eigentümer) kann über crm.Mandant.benutzer mit einem Login
verknüpft werden. Er sieht hier NUR seine eigenen Liegenschaften — keine
Mieterdetails anderer Mandanten, kein SPA, keine API (core/auth.py sperrt
Eigentümer-Logins dort aus).
"""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from core.auth import hat_rolle, ist_eigentuemer, TEAM_ROLLEN
from rentals.models import Mietvertrag


@login_required
def nach_login_view(request):
    """Login-Weiche: Team → neue Oberfläche (/neu/), Eigentümer → Portal."""
    if getattr(request.user, 'mandant_profil', None) is not None:
        return redirect('portal')
    if hat_rolle(request.user, TEAM_ROLLEN):
        return redirect('fw_dashboard')
    if ist_eigentuemer(request.user):
        return redirect('portal')
    # Login ohne Rolle und ohne Mandant-Verknüpfung: zurück zum Login
    # (Rolle muss zuerst von der Verwaltung zugewiesen werden).
    return redirect('login')


@login_required
def portal_view(request):
    mandant = getattr(request.user, 'mandant_profil', None)

    # Team-Mitglieder ohne Mandant-Verknüpfung gehören in die neue Oberfläche
    if mandant is None:
        if hat_rolle(request.user, TEAM_ROLLEN):
            return redirect('fw_dashboard')
        return render(request, 'core/portal.html', {'mandant': None})

    liegenschaften = []
    total_soll = Decimal('0.00')
    total_einheiten = 0
    total_vermietet = 0

    for lg in mandant.liegenschaften.all().prefetch_related('einheiten'):
        einheiten_rows = []
        lg_soll = Decimal('0.00')

        for e in lg.einheiten.all():
            vertrag = (
                Mietvertrag.objects
                .filter(einheit=e, status='aktiv')
                .select_related('mieter')
                .order_by('-beginn')
                .first()
            )
            brutto = vertrag.brutto_mietzins if vertrag else Decimal('0.00')
            lg_soll += brutto
            total_einheiten += 1
            if vertrag:
                total_vermietet += 1

            einheiten_rows.append({
                'bezeichnung': e.bezeichnung,
                'typ': e.get_typ_display(),
                'zimmer': e.zimmer,
                'flaeche': e.flaeche_m2,
                'mieter': str(vertrag.mieter) if vertrag else None,
                'seit': vertrag.beginn if vertrag else None,
                'brutto': brutto if vertrag else None,
            })

        total_soll += lg_soll
        liegenschaften.append({
            'adresse': f"{lg.strasse}, {lg.plz} {lg.ort}",
            'baujahr': lg.baujahr,
            'einheiten': einheiten_rows,
            'soll_monat': lg_soll,
        })

    context = {
        'mandant': mandant,
        'liegenschaften': liegenschaften,
        'total_soll': total_soll,
        'total_einheiten': total_einheiten,
        'total_vermietet': total_vermietet,
        'total_leer': total_einheiten - total_vermietet,
    }
    return render(request, 'core/portal.html', context)
