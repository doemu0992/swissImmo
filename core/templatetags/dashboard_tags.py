from django import template
from django.db.models import Sum
from core.models import Liegenschaft, Einheit, SchadenMeldung, Mietvertrag
from django.utils import timezone
import json

register = template.Library()

@register.inclusion_tag('admin/dashboard_stats.html')
def render_dashboard_stats():
    # 1. Basis-Zahlen
    total_liegenschaften = Liegenschaft.objects.count()
    total_einheiten = Einheit.objects.count()
    total_miete = Einheit.objects.aggregate(Sum('nettomiete_aktuell'))['nettomiete_aktuell__sum'] or 0

    # 2. Leerstand
    vermietet_count = Einheit.objects.filter(vertraege__aktiv=True).distinct().count()
    leerstand_count = total_einheiten - vermietet_count
    leerstand_prozent = 0
    if total_einheiten > 0:
        leerstand_prozent = round((leerstand_count / total_einheiten) * 100, 1)

    # 3. Listen für Tabellen (NEU!)
    # Die neuesten 5 Tickets
    neueste_tickets = SchadenMeldung.objects.exclude(status='erledigt').order_by('-prioritaet', '-erstellt_am')[:5]

    # Die nächsten auslaufenden Verträge (oder Leerstände)
    # Hier nehmen wir einfach die Leerstände, da das wichtig ist
    leerstaende_liste = Einheit.objects.filter(vertraege__aktiv=False).exclude(vertraege__aktiv=True)[:5]

    # 4. Chart Daten
    chart_labels = []
    chart_data = []
    all_objekte = Liegenschaft.objects.annotate(total_soll=Sum('einheiten__nettomiete_aktuell'))
    for obj in all_objekte:
        if obj.total_soll and obj.total_soll > 0: # Nur Gebäude mit Umsatz anzeigen
            chart_labels.append(f"{obj.strasse}")
            chart_data.append(float(obj.total_soll))

    return {
        'total_miete': f"{total_miete:,.2f}",
        'leerstand_count': leerstand_count,
        'leerstand_prozent': leerstand_prozent,
        'offene_tickets_count': SchadenMeldung.objects.exclude(status='erledigt').count(),
        'total_objekte': total_liegenschaften,

        # Listen
        'neueste_tickets': neueste_tickets,
        'leerstaende_liste': leerstaende_liste,

        # Chart
        'chart_labels': json.dumps(chart_labels),
        'chart_data': json.dumps(chart_data),
    }