from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from decimal import Decimal
import json
import datetime

from core.models import Einheit, Mietvertrag, SchadenMeldung, Verwaltung

@staff_member_required
def custom_dashboard_view(request):
    """
    Lädt die Daten für das Immobilien-Cockpit.
    """
    # --- 1. FINANZEN (Soll-Miete) ---
    aktive_vertraege = Mietvertrag.objects.filter(aktiv=True)
    total_netto = aktive_vertraege.aggregate(Sum('netto_mietzins'))['netto_mietzins__sum'] or Decimal('0.00')
    total_nk = aktive_vertraege.aggregate(Sum('nebenkosten'))['nebenkosten__sum'] or Decimal('0.00')
    total_income = total_netto + total_nk

    # --- 2. LEERSTAND ---
    total_einheiten = Einheit.objects.count()
    # Wir zählen Einheiten, die mindestens einen aktiven Vertrag haben
    vermietet_count = aktive_vertraege.values('einheit').distinct().count()
    leerstand_count = total_einheiten - vermietet_count

    # Schutz vor negativen Zahlen (Daten-Inkonsistenz)
    if leerstand_count < 0: leerstand_count = 0
    if vermietet_count > total_einheiten: vermietet_count = total_einheiten

    leerstand_prozent = 0
    if total_einheiten > 0:
        leerstand_prozent = round((leerstand_count / total_einheiten) * 100, 1)

    # --- 3. TICKETS ---
    # Alles was nicht erledigt/abgeschlossen ist
    offene_tickets = SchadenMeldung.objects.exclude(status__in=['erledigt', 'abgeschlossen']).count()
    kritische_tickets = SchadenMeldung.objects.filter(prioritaet='hoch').exclude(status__in=['erledigt', 'abgeschlossen']).count()

    # --- 4. CHARTS VORBEREITUNG (JSON) ---
    # Wir gruppieren die Tickets nach Status für das Balkendiagramm
    ticket_stats = SchadenMeldung.objects.values('status').annotate(count=Count('status'))

    # Labels schön formatieren (z.B. "in_bearbeitung" -> "In Bearbeitung")
    labels = [item['status'].replace('_', ' ').title() for item in ticket_stats]
    data = [item['count'] for item in ticket_stats]

    # --- 5. AUSLAUFENDE VERTRÄGE (90 Tage) ---
    heute = datetime.date.today()
    in_90_tagen = heute + datetime.timedelta(days=90)
    auslaufende_vertraege = Mietvertrag.objects.filter(
        aktiv=True,
        ende__isnull=False,
        ende__lte=in_90_tagen,
        ende__gte=heute
    ).order_by('ende')

    # --- CONTEXT ZUSAMMENBAUEN ---
    context = {
        # Navigation Unfold (Damit die Sidebar aktiv bleibt)
        'title': 'Cockpit',
        'site_title': 'SwissImmo Verwaltung',

        # KPI Karten
        'total_income': total_income,
        'total_units': total_einheiten,
        'vermietet_count': vermietet_count,
        'leerstand_count': leerstand_count,
        'leerstand_prozent': leerstand_prozent,
        'offene_tickets': offene_tickets,
        'kritische_tickets': kritische_tickets,

        # Listen
        'auslaufende_vertraege': auslaufende_vertraege,

        # Charts (Als JSON String für JavaScript)
        'chart_ticket_labels': json.dumps(labels),
        'chart_ticket_data': json.dumps(data),
    }

    return render(request, 'core/dashboard.html', context)