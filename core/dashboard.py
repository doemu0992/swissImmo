import datetime
import json
from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.utils import timezone

# Modelle importieren
from crm.models import Verwaltung
from portfolio.models import Einheit
from rentals.models import Mietvertrag, Leerstand
from tickets.models import SchadenMeldung
from core.mietrecht_logic import berechne_mietpotenzial

# Import für die Zahlungen
from finance.models import Zahlung

# 🔥 NEU: Import für die Bewerbungen (passe den App-Namen an, falls nötig, z.B. mietprozess)
from mietprozess.models import Mietbewerbung

def dashboard_callback(request, context):
    """
    Das zentrale Cockpit für Unfold.
    Kombiniert Mietzins-Scanner, Finanzen, Ticket-Statistiken
    und generiert das Action-Center (To-Do-Liste).
    """

    # --- 1. SEITEN-DATEN & BASICS ---
    verwaltung = Verwaltung.objects.first()
    ref_zins = verwaltung.aktueller_referenzzinssatz if verwaltung else 0
    lik = verwaltung.aktueller_lik_punkte if verwaltung else 0
    heute = datetime.date.today()

    aktive_vertraege = Mietvertrag.objects.filter(aktiv=True)

    # --- 2. KPI: MIETZINS-POTENZIAL (SCANNER) ---
    potenzial_total = 0.0
    potenzial_up = 0      # Anzahl Mietzinserhöhungen möglich
    potenzial_down = 0    # Anzahl Mietzinssenkungen-Risiken

    for v in aktive_vertraege:
        res = berechne_mietpotenzial(v, ref_zins, lik)
        if res:
            if res['action'] == 'UP':
                potenzial_up += 1
                potenzial_total += float(res['delta_chf'])
            elif res['action'] == 'DOWN':
                potenzial_down += 1

    # --- 3. KPI: LEERSTAND ---
    total_einheiten = Einheit.objects.count()
    vermietet_count = aktive_vertraege.values('einheit').distinct().count()
    leerstand_count = total_einheiten - vermietet_count
    if leerstand_count < 0:
        leerstand_count = 0

    leerstand_prozent = 0
    if total_einheiten > 0:
        leerstand_prozent = round((leerstand_count / total_einheiten) * 100, 1)

    # --- 4. KPI: TICKETS ---
    offene_tickets = SchadenMeldung.objects.exclude(status__in=['erledigt', 'abgeschlossen']).count()
    kritische_tickets = SchadenMeldung.objects.filter(prioritaet='hoch', status__in=['neu', 'in_bearbeitung']).count()

    # --- 5. KPI: FINANZEN (Soll vs. Ist für aktuellen Monat) ---
    total_netto = aktive_vertraege.aggregate(Sum('netto_mietzins'))['netto_mietzins__sum'] or Decimal('0.00')
    total_nk = aktive_vertraege.aggregate(Sum('nebenkosten'))['nebenkosten__sum'] or Decimal('0.00')
    soll_miete = total_netto + total_nk

    aktueller_monat_start = heute.replace(day=1)
    ist_miete = Zahlung.objects.filter(datum_eingang__gte=aktueller_monat_start).aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')

    finanz_quote = round((float(ist_miete) / float(soll_miete) * 100), 1) if soll_miete > 0 else 0

    # --- 6. CHART: VERLAUF DER LETZTEN 6 MONATE (Soll vs. Ist) ---
    chart_labels = []
    chart_soll = []
    chart_ist = []
    monate_namen = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

    for i in range(5, -1, -1):
        m = heute.month - i
        y = heute.year
        while m < 1:
            m += 12
            y -= 1

        chart_labels.append(f"{monate_namen[m-1]} {y}")
        chart_soll.append(float(soll_miete))

        monat_sum = Zahlung.objects.filter(
            datum_eingang__year=y,
            datum_eingang__month=m
        ).aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')
        chart_ist.append(float(monat_sum))

    # --- 7. 🔥 NEU: ACTION-CENTER / TO-DO GENERATOR ---
    action_items = []

    # 7a. Neue Bewerbungen prüfen
    neue_bewerbungen = Mietbewerbung.objects.filter(status='neu').count()
    if neue_bewerbungen > 0:
        action_items.append({
            "icon": "bi-person-lines-fill",
            "color": "bg-indigo-100 text-indigo-600",
            "title": f"{neue_bewerbungen} neue Bewerbung(en)",
            "desc": "Mietinteressenten warten auf Prüfung."
        })

    # 7b. Neue oder kritische Tickets prüfen
    neue_tickets = SchadenMeldung.objects.filter(status='neu').count()
    if neue_tickets > 0:
        action_items.append({
            "icon": "bi-tools",
            "color": "bg-rose-100 text-rose-600",
            "title": f"{neue_tickets} ungesehene Tickets",
            "desc": "Mieter haben neue Meldungen erfasst."
        })

    # 7c. Bevorstehende Einzüge (nächste 30 Tage)
    in_30_tagen = heute + datetime.timedelta(days=30)
    # Beachte: 'aktiv=True' könnte hier je nach deiner Logik auch 'status="aktiv"' heissen.
    einzug_bald = Mietvertrag.objects.filter(beginn__gte=heute, beginn__lte=in_30_tagen, aktiv=True).count()
    if einzug_bald > 0:
        action_items.append({
            "icon": "bi-key",
            "color": "bg-amber-100 text-amber-600",
            "title": f"{einzug_bald} bevorstehende Einzüge",
            "desc": "Schlüsselübergaben in den nächsten 30 Tagen."
        })


    # --- AUSGABE AN DAS CUSTOM TEMPLATE ---
    return {
        "total_einheiten": total_einheiten,
        "leerstand_count": leerstand_count,
        "leerstand_quote": str(leerstand_prozent).replace(',', '.'),
        "offene_tickets": offene_tickets,

        "soll_miete": float(soll_miete),
        "ist_miete": float(ist_miete),
        "finanz_quote": str(finanz_quote).replace(',', '.'),

        "potenzial_up": potenzial_up,
        "potenzial_down": potenzial_down,

        "chart_labels": json.dumps(chart_labels),
        "chart_soll": json.dumps(chart_soll),
        "chart_ist": json.dumps(chart_ist),

        "action_items": action_items, # 🔥 Die neue Liste ans Template senden

        # Unfold-interne KPI Karten
        "kpi": [
            {
                "title": "Miet-Einnahmen (Soll/Monat)",
                "metric": f"CHF {soll_miete:,.2f}",
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