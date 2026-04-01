from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum

# Moderne App-Architektur Importe
from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag
from tickets.models import SchadenMeldung

@staff_member_required
def custom_dashboard_view(request):
    """
    Modernes SaaS-Cockpit mit den wichtigsten KPIs für die Immobilienbewirtschaftung.
    """
    # 1. PORTFOLIO KPIs
    total_liegenschaften = Liegenschaft.objects.count()
    total_einheiten = Einheit.objects.count()

    # 2. VERMIETUNG & LEERSTAND
    aktive_vertraege = Mietvertrag.objects.filter(aktiv=True).count()
    leerstaende = total_einheiten - aktive_vertraege if total_einheiten > 0 else 0
    leerstands_quote = (leerstaende / total_einheiten * 100) if total_einheiten > 0 else 0

    # 3. FINANZEN (Monatliche Soll-Miete)
    monatliche_soll_miete = Mietvertrag.objects.filter(aktiv=True).aggregate(
        total_netto=Sum('netto_mietzins'),
        total_nk=Sum('nebenkosten')
    )
    soll_total = (monatliche_soll_miete['total_netto'] or 0) + (monatliche_soll_miete['total_nk'] or 0)

    # 4. PENDENZEN / TICKETS
    offene_tickets = SchadenMeldung.objects.exclude(status='erledigt').count()
    neuste_tickets = SchadenMeldung.objects.all().order_by('-erstellt_am')[:5]

    context = {
        'title': 'Cockpit',
        'total_liegenschaften': total_liegenschaften,
        'total_einheiten': total_einheiten,
        'aktive_vertraege': aktive_vertraege,
        'leerstaende': leerstaende,
        'leerstands_quote': round(leerstands_quote, 1),
        'soll_total': soll_total,
        'offene_tickets': offene_tickets,
        'neuste_tickets': neuste_tickets,
    }

    return render(request, 'admin/dashboard_stats.html', context)