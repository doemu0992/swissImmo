from django.shortcuts import render
from django.db.models import Sum, Count, Q
from django.contrib.admin.views.decorators import staff_member_required
import datetime
from decimal import Decimal

# Modelle importieren
from core.models import Einheit, Mietvertrag, SchadenMeldung, Liegenschaft

@staff_member_required
def dashboard_view(request):
    """
    Das Cockpit: Zeigt alle wichtigen Kennzahlen auf einen Blick.
    """
    # 1. KPI: Finanzen (Monatliche Soll-Miete aus aktiven Verträgen)
    # Wir summieren Nettomiete + Nebenkosten aller aktiven Verträge
    aktive_vertraege = Mietvertrag.objects.filter(aktiv=True)

    total_netto = aktive_vertraege.aggregate(Sum('netto_mietzins'))['netto_mietzins__sum'] or Decimal('0.00')
    total_nk = aktive_vertraege.aggregate(Sum('nebenkosten'))['nebenkosten__sum'] or Decimal('0.00')
    total_income = total_netto + total_nk

    # 2. KPI: Leerstand (Einheiten total vs. vermietet)
    total_einheiten = Einheit.objects.count()
    # Vermietet sind Einheiten, die einen aktiven Vertrag haben
    vermietet_count = aktive_vertraege.values('einheit').distinct().count()
    leerstand_count = total_einheiten - vermietet_count

    leerstand_prozent = 0
    if total_einheiten > 0:
        leerstand_prozent = round((leerstand_count / total_einheiten) * 100, 1)

    # 3. KPI: Offene Tickets (Schäden)
    offene_tickets = SchadenMeldung.objects.exclude(status='erledigt').count()
    kritische_tickets = SchadenMeldung.objects.filter(prioritaet='hoch').exclude(status='erledigt').count()

    # 4. Warnungen: Auslaufende Verträge (in den nächsten 90 Tagen)
    heute = datetime.date.today()
    in_90_tagen = heute + datetime.timedelta(days=90)

    auslaufende_vertraege = Mietvertrag.objects.filter(
        aktiv=True,
        ende__isnull=False,
        ende__lte=in_90_tagen,
        ende__gte=heute
    ).order_by('ende')

    # 5. Daten für Grafiken vorbereiten (Chart.js)
    # Grafik 1: Ticket Status Verteilung
    ticket_stats = SchadenMeldung.objects.values('status').annotate(count=Count('status'))
    # Wir mappen das in zwei Listen für JS: Labels und Daten
    chart_ticket_labels = [item['status'] for item in ticket_stats]
    chart_ticket_data = [item['count'] for item in ticket_stats]

    context = {
        'total_income': total_income,
        'total_units': total_einheiten,
        'vermietet_count': vermietet_count,
        'leerstand_count': leerstand_count,
        'leerstand_prozent': leerstand_prozent,
        'offene_tickets': offene_tickets,
        'kritische_tickets': kritische_tickets,
        'auslaufende_vertraege': auslaufende_vertraege,

        # Chart Data
        'chart_ticket_labels': chart_ticket_labels,
        'chart_ticket_data': chart_ticket_data,
    }

    return render(request, 'core/dashboard.html', context)