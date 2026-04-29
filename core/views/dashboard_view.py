from portfolio.models import Einheit
from rentals.models import Mietvertrag
from tickets.models import SchadenMeldung
from finance.models import Zahlungseingang

from django.shortcuts import render, redirect
from django.db.models import Sum, Count, Q
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse
import datetime
import traceback
from decimal import Decimal

# Import für den Marktdaten-Sync
from core.utils.market_data import update_verwaltung_rates

@staff_member_required
def update_market_data_view(request):
    """
    Startet den manuellen Import von BWO (Zins) und BFS (LIK).
    """
    msg, errors = update_verwaltung_rates()

    # Eventuelle Warnungen anzeigen
    if errors:
        for error in errors:
            messages.warning(request, error)

    # Erfolgsmeldung anzeigen und zurück zum Dashboard
    messages.success(request, msg)
    return redirect('admin_dashboard')


@staff_member_required
def dashboard_view(request):
    """
    ALTE LOGIK: Für das klassische Django-Admin-Dashboard.
    """
    try:
        context = _generate_dashboard_context()
        return render(request, 'core/dashboard.html', context)
    except Exception as e:
        return _render_error(e)


@staff_member_required
def spa_master_view(request):
    """
    NEUE LOGIK: Für unser Vue.js Cockpit (Single Page Application).
    Nutzt dieselben Berechnungen, sendet sie aber an spa_master.html.
    """
    try:
        context = _generate_dashboard_context()
        return render(request, 'core/spa_master.html', context)
    except Exception as e:
        return _render_error(e)


# ====================================================================
# HILFSFUNKTIONEN (Damit wir den Code nicht doppelt schreiben müssen)
# ====================================================================

def _generate_dashboard_context():
    """
    Führt die Kernberechnungen für KPIs, Finanzen und Charts durch.
    """
    heute = timezone.now().date()
    aktueller_monat = heute.replace(day=1)

    # 1. PORTFOLIO & LEERSTAND (Mit Nebenobjekten)
    total_einheiten = Einheit.objects.count()
    aktive_vertraege = Mietvertrag.objects.filter(aktiv=True)

    # IDs der Haupt- und Nebenobjekte
    belegte_haupt_ids = list(aktive_vertraege.values_list('einheit_id', flat=True))
    belegte_neben_ids = list(aktive_vertraege.values_list('nebenobjekte', flat=True))

    # Alle belegten IDs kombinieren
    alle_belegten_ids = set([id for id in (belegte_haupt_ids + belegte_neben_ids) if id is not None])

    leerstand_count = Einheit.objects.exclude(id__in=alle_belegten_ids).count()
    leerstand_quote = round((leerstand_count / total_einheiten * 100), 1) if total_einheiten > 0 else 0

    # Mietzins-Potenzial auswerten
    potenzial_up = sum(1 for v in aktive_vertraege if v.mietzinspotenzial == 'increase')
    potenzial_down = sum(1 for v in aktive_vertraege if v.mietzinspotenzial == 'decrease')

    # 2. FINANZEN
    soll_miete = sum((v.netto_mietzins or Decimal('0.00')) + (v.nebenkosten or Decimal('0.00')) for v in aktive_vertraege)
    ist_miete = Zahlungseingang.objects.filter(buchungs_monat=aktueller_monat).aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')
    finanz_quote = round((ist_miete / soll_miete * 100), 1) if soll_miete > 0 else 0

    # 3. TICKETS
    offene_tickets = SchadenMeldung.objects.exclude(status='erledigt').count()
    kritische_tickets = SchadenMeldung.objects.filter(prioritaet='hoch').exclude(status='erledigt').count()

    # 4. CHART DATEN (Letzte 6 Monate)
    chart_labels = []
    chart_ist = []
    chart_soll = []

    for i in range(5, -1, -1):
        m = heute.month - i
        y = heute.year
        while m <= 0:
            m += 12
            y -= 1
        monat_date = datetime.date(y, m, 1)

        chart_labels.append(monat_date.strftime('%b %Y'))

        m_ist = Zahlungseingang.objects.filter(buchungs_monat=monat_date).aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')
        chart_ist.append(float(m_ist))
        chart_soll.append(float(soll_miete))

    return {
        'total_einheiten': total_einheiten,
        'leerstand_count': leerstand_count,
        'leerstand_quote': leerstand_quote,
        'potenzial_up': potenzial_up,
        'potenzial_down': potenzial_down,
        'soll_miete': soll_miete,
        'ist_miete': ist_miete,
        'finanz_quote': finanz_quote,
        'offene_tickets': offene_tickets,
        'kritische_tickets': kritische_tickets,
        'chart_labels': chart_labels,
        'chart_ist': chart_ist,
        'chart_soll': chart_soll,
    }


def _render_error(e):
    """
    Sicheres Abfangen von System-Fehlern mit schöner Anzeige.
    """
    error_msg = traceback.format_exc()
    return HttpResponse(f"""
        <div style="background:#fef2f2; border:2px solid #ef4444; padding:20px; border-radius:10px; margin:20px; font-family:monospace;">
            <h2 style="color:#b91c1c;">🚨 System-Fehler im Dashboard:</h2>
            <pre style="color:#7f1d1d; overflow-x:auto;">{error_msg}</pre>
        </div>
    """)