from portfolio.models import Einheit, Geraet
from rentals.models import Mietvertrag
from tickets.models import SchadenMeldung
from finance.models import Zahlungseingang, DebitorenRechnung

from django.shortcuts import render, redirect
from django.db.models import Sum, Count, Q
from django.contrib.auth.decorators import login_required
from core.auth import (rolle_erforderlich, hat_rolle, ist_eigentuemer,
                       ROLLE_VERWALTUNG, ROLLE_SACHBEARBEITUNG, TEAM_ROLLEN)
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse
import datetime
import traceback
from decimal import Decimal

# Import für den Marktdaten-Sync
from core.utils.market_data import update_verwaltung_rates

@rolle_erforderlich(ROLLE_VERWALTUNG, ROLLE_SACHBEARBEITUNG)
def update_market_data_view(request):
    """
    Startet den manuellen Import von BWO (Zins) und BFS (LIK).
    """
    msg, errors = update_verwaltung_rates()

    # Eventuelle Warnungen anzeigen
    if errors:
        for error in errors:
            messages.warning(request, error)

    # Erfolgsmeldung anzeigen und zurück zur neuen Oberfläche
    messages.success(request, msg)
    return redirect('fw_dashboard')


@login_required
def spa_master_view(request):
    """
    NEUE LOGIK: Für unser Vue.js Cockpit (Single Page Application).
    Nutzt dieselben Berechnungen, sendet sie aber an spa_master.html.
    Zugriff: Team-Rollen (Verwaltung/Sachbearbeitung/Lesend) + Superuser.
    Eigentümer-Logins werden ins Portal umgeleitet.
    """
    if ist_eigentuemer(request.user) and not hat_rolle(request.user, TEAM_ROLLEN):
        return redirect('portal')
    if not hat_rolle(request.user, TEAM_ROLLEN):
        return redirect('login')
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

    # 5. AUFGABEN fürs Action Center (serverseitig berechnet).
    # Jede Aufgabe: Icon, Farbstil, Titel, Untertitel und Ziel-Tab (Klick).
    # Nur volle Klassennamen verwenden (Tailwind), Palette wie im Template.
    aufgaben = _berechne_aufgaben(heute, leerstand_count, potenzial_up, potenzial_down)

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
        'aufgaben': aufgaben,
    }


def _berechne_aufgaben(heute, leerstand_count, potenzial_up, potenzial_down):
    """
    Das Herz des Aufgaben-Dashboards: beantwortet 'Was muss ich heute tun?'.
    Reihenfolge = Dringlichkeit (Geld zuerst, dann Fristen, dann Chancen).
    """
    STIL = {
        'rose':    ('bg-rose-50', 'text-rose-600'),
        'amber':   ('bg-amber-50', 'text-amber-600'),
        'indigo':  ('bg-indigo-50', 'text-indigo-600'),
        'emerald': ('bg-emerald-50', 'text-emerald-600'),
    }

    def aufgabe(stil, icon, titel, sub, tab):
        bg, text = STIL[stil]
        return {'icon': icon, 'bg': bg, 'text': text, 'titel': titel, 'sub': sub, 'tab': tab}

    aufgaben = []
    in_90_tagen = heute + datetime.timedelta(days=90)
    aktive = Mietvertrag.objects.filter(status='aktiv')

    # a) ÜBERFÄLLIGE FORDERUNGEN — das Wichtigste zuerst
    ueberfaellig = DebitorenRechnung.objects.filter(
        status__in=['offen', 'teilbezahlt'], faellig_am__lt=heute
    )
    if ueberfaellig.exists():
        total_offen = sum(r.offener_betrag for r in ueberfaellig)
        aufgaben.append(aufgabe(
            'rose', 'fa-file-invoice-dollar',
            f"{ueberfaellig.count()} überfällige Forderung(en)",
            f"CHF {total_offen:.2f} ausstehend — Mietzins-Kontrolle & Mahnung prüfen",
            'finance'
        ))

    # b) SOLLSTELLUNG für den aktuellen Monat noch nicht gelaufen
    titel_monat = f"Miete & NK {heute.month:02d}/{heute.year}"
    if aktive.exists() and not DebitorenRechnung.objects.filter(
            titel=titel_monat).exclude(status='storniert').exists():
        aufgaben.append(aufgabe(
            'amber', 'fa-rotate',
            f"Sollstellung {heute.month:02d}/{heute.year} noch nicht gelaufen",
            "Monatlichen Mietenlauf im Finanz-Tab starten",
            'finance'
        ))

    # c) KAUTION AUSSTEHEND bei aktiven Verträgen
    kaution_fehlt = aktive.filter(
        kautions_betrag__gt=0, kautions_einbezahlt_am__isnull=True
    ).count()
    if kaution_fehlt:
        aufgaben.append(aufgabe(
            'amber', 'fa-shield-halved',
            f"{kaution_fehlt} Kaution(en) noch nicht einbezahlt",
            "Eingang prüfen und im Vertrag erfassen",
            'rentals'
        ))

    # d) FRISTEN: erstmals kündbar innert 90 Tagen
    kuendbar = aktive.filter(erstmals_kuendbar_auf__range=[heute, in_90_tagen])
    if kuendbar.exists():
        naechster = kuendbar.order_by('erstmals_kuendbar_auf').first()
        aufgaben.append(aufgabe(
            'indigo', 'fa-calendar-check',
            f"{kuendbar.count()} Vertrag/Verträge erstmals kündbar bis {in_90_tagen.strftime('%d.%m.%Y')}",
            f"Nächster: {naechster.mieter} am {naechster.erstmals_kuendbar_auf.strftime('%d.%m.%Y')}",
            'rentals'
        ))

    # e) GERÄTE-GARANTIEN laufen ab
    garantien = Geraet.objects.filter(garantie_bis__range=[heute, in_90_tagen]).count()
    if garantien:
        aufgaben.append(aufgabe(
            'indigo', 'fa-screwdriver-wrench',
            f"{garantien} Gerätegarantie(n) laufen in 90 Tagen ab",
            "Vor Ablauf prüfen: Mängel jetzt kostenlos reparieren lassen",
            'portfolio'
        ))

    # f) LEERSTAND
    if leerstand_count:
        aufgaben.append(aufgabe(
            'amber', 'fa-house-circle-exclamation',
            f"{leerstand_count} Einheit(en) im Leerstand",
            "Bewerbungs-Link teilen oder Inserat aufschalten",
            'portfolio'
        ))

    # g) MIETZINS-POTENZIAL (Referenzzins)
    if potenzial_down:
        aufgaben.append(aufgabe(
            'rose', 'fa-arrow-trend-down',
            f"{potenzial_down} Vertrag/Verträge über dem aktuellen Referenzzins",
            "Mieter haben Anspruch auf Senkung — proaktiv anpassen",
            'rentals'
        ))
    if potenzial_up:
        aufgaben.append(aufgabe(
            'emerald', 'fa-arrow-trend-up',
            f"{potenzial_up} Vertrag/Verträge mit Erhöhungspotenzial",
            "Referenzzins/LIK gestiegen — Mietzinsanpassung prüfen",
            'rentals'
        ))

    return aufgaben


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