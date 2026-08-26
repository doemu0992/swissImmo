# core/views/fw/dienstleister.py
#
# Handwerkerstamm. Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.

from django.db.models import Q
from django.shortcuts import render

from core.auth import rolle_erforderlich, TEAM_ROLLEN

from ._basis import _global_filter


# ============================================================
# ETAPPE D: DIENSTLEISTER (Handwerkerstamm)
# ============================================================

BRANCHE_ICON = {
    'sanitaer': ('arbeit', 'fw-info-flaeche fw-info'),
    'elektro': ('arbeit', 'fw-warn-flaeche fw-warnton'),
    'maler': ('arbeit', 'fw-warn-flaeche fw-warnton'),
    'schreiner': ('arbeit', 'fw-warn-flaeche fw-warnton'),
    'schloss': ('schluessel', 'fw-flaeche2 fw-mutet'),
    'allgemein': ('arbeit', 'fw-markenflaeche fw-marke'),
    'garten': ('arbeit', 'fw-gut-flaeche fw-gut'),
    'reinigung': ('arbeit', 'fw-markenflaeche fw-marke'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_dienstleister(request):
    from crm.models import Handwerker
    from tickets.models import HandwerkerAuftrag
    basis = _global_filter(request)

    qs = Handwerker.objects.all().order_by('firma')
    branche_filter = request.GET.get('branche', '')
    if branche_filter:
        qs = qs.filter(branche=branche_filter)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(firma__icontains=q) | Q(kontaktperson__icontains=q) | Q(email__icontains=q))

    # Offene Aufträge je Handwerker zählen
    offene = {}
    for a in HandwerkerAuftrag.objects.exclude(status='erledigt').values_list('handwerker_id', flat=True):
        offene[a] = offene.get(a, 0) + 1

    rows = []
    for h in qs:
        icon, cls = BRANCHE_ICON.get(h.branche, ('arbeit', 'fw-flaeche2 fw-mutet'))
        rows.append({
            'h': h, 'icon': icon, 'icon_cls': cls,
            'branche': h.get_branche_display(),
            'offene': offene.get(h.id, 0),
        })

    # Branchen-Chips nur für vorhandene Branchen
    vorhanden = set(Handwerker.objects.values_list('branche', flat=True))
    branche_chips = [('', 'Alle')] + [(k, v) for k, v in Handwerker.BRANCHEN_CHOICES if k in vorhanden]

    return render(request, 'fw/dienstleister.html', {
        **basis, 'nav': 'dienstleister', 'rows': rows,
        'branche_filter': branche_filter, 'branche_chips': branche_chips, 'q': q,
        'anzahl': len(rows),
        'anzahl_branchen': len(vorhanden),
    })
