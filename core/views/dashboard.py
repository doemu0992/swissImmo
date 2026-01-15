from django.shortcuts import render
from django.db.models import Sum
from core.models import Mandant, Einheit, SchadenMeldung, Liegenschaft, Mieter

def dashboard_view(request):
    baum_daten = Mandant.objects.prefetch_related(
        'liegenschaften',
        'liegenschaften__einheiten',
        'liegenschaften__einheiten__geraete'
    ).all()

    try:
        agg_soll = Einheit.objects.aggregate(Sum('nettomiete_aktuell'))
        total_soll = agg_soll['nettomiete_aktuell__sum'] or 0
        leerstand_count = Einheit.objects.exclude(vertraege__aktiv=True).count()
        offene_schaden = SchadenMeldung.objects.exclude(status='erledigt').count()
        total_liegenschaften = Liegenschaft.objects.count()
        total_mieter = Mieter.objects.count()
    except Exception:
        total_soll = 0; leerstand_count = 0; offene_schaden = 0
        total_liegenschaften = 0; total_mieter = 0

    context = {
        'baum_daten': baum_daten,
        'total_soll': total_soll,
        'leerstand_count': leerstand_count,
        'offene_schaden': offene_schaden,
        'total_liegenschaften': total_liegenschaften,
        'total_mieter': total_mieter
    }
    return render(request, 'dashboard.html', context)