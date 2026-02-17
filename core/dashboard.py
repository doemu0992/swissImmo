from django.db.models import Sum, Count, Q
from django.utils import timezone
from decimal import Decimal
import datetime

# Modelle importieren
from core.models import Einheit, SchadenMeldung, Mietvertrag, Verwaltung
from core.mietrecht_logic import berechne_mietpotenzial

def dashboard_callback(request, context):
    """
    Das zentrale Cockpit für Unfold.
    Kombiniert Mietzins-Scanner, Finanzen und Ticket-Statistiken.
    """

    # --- 1. DATEN LADEN ---
    verwaltung = Verwaltung.objects.first()
    ref_zins = verwaltung.aktueller_referenzzinssatz if verwaltung else 0
    lik = verwaltung.aktueller_lik_punkte if verwaltung else 0

    aktive_vertraege = Mietvertrag.objects.filter(aktiv=True)
    heute = datetime.date.today()

    # --- 2. KPI: MIETZINS-POTENZIAL (SCANNER) ---
    potenzial_total = 0.0
    for v in aktive_vertraege:
        res = berechne_mietpotenzial(v, ref_zins, lik)
        if res and res['action'] == 'UP':
            potenzial_total += float(res['delta_chf'])

    # --- 3. KPI: LEERSTAND ---
    total_einheiten = Einheit.objects.count()
    vermietet_count = aktive_vertraege.values('einheit').distinct().count()
    leerstand_count = total_einheiten - vermietet_count
    if leerstand_count < 0: leerstand_count = 0

    leerstand_prozent = 0
    if total_einheiten > 0:
        leerstand_prozent = round((leerstand_count / total_einheiten) * 100, 1)

    # --- 4. KPI: TICKETS ---
    offene_tickets = SchadenMeldung.objects.exclude(status__in=['erledigt', 'abgeschlossen']).count()
    kritische_tickets = SchadenMeldung.objects.filter(prioritaet='hoch', status__in=['neu', 'in_bearbeitung']).count()

    # --- 5. KPI: FINANZEN (Neu aus deiner View) ---
    total_netto = aktive_vertraege.aggregate(Sum('netto_mietzins'))['netto_mietzins__sum'] or Decimal('0.00')
    total_nk = aktive_vertraege.aggregate(Sum('nebenkosten'))['nebenkosten__sum'] or Decimal('0.00')
    total_income = total_netto + total_nk

    # --- 6. CHART: TICKET STATUS ---
    # Unfold erwartet einfache Daten für Charts
    ticket_stats = SchadenMeldung.objects.values('status').annotate(count=Count('status'))
    # Wir bauen das in ein Format, das wir vielleicht später nutzen können,
    # aktuell unterstützt Unfold Charts vor allem via KPI-Karten oder Custom Templates.

    # --- AUSGABE AN UNFOLD ---
    return {
        "kpi": [
            {
                "title": "Miet-Einnahmen (Soll/Monat)",
                "metric": f"CHF {total_income:,.2f}",
                "footer": f"Davon NK: CHF {total_nk:,.2f}",
                "color": "bg-blue-50 text-blue-600",
            },
            {
                "title": "Miet-Potenzial (Möglich)",
                "metric": f"CHF {potenzial_total:,.2f}",
                "footer": f"Bei {ref_zins}% Referenzzins",
                "color": "bg-green-50 text-green-600" if potenzial_total > 0 else "bg-gray-50 text-gray-600",
            },
            {
                "title": "Leerstand",
                "metric": f"{leerstand_count}",
                "footer": f"{leerstand_prozent}% von {total_einheiten} Einheiten",
                "color": "bg-red-50 text-red-600" if leerstand_count > 0 else "bg-green-50 text-green-600",
            },
            {
                "title": "Offene Tickets",
                "metric": f"{offene_tickets}",
                "footer": f"{kritische_tickets} Kritisch",
                "color": "bg-orange-50 text-orange-600" if offene_tickets > 0 else "bg-gray-50 text-gray-600",
            },
        ]
    }