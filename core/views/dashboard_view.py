# Nach E1b enthält diese Datei nur noch zwei Dinge: den manuellen
# Marktdaten-Import und `_berechne_aufgaben`, das von core/views/fw.py
# gebraucht wird. Die Vue-Ansicht `spa_master_view` und ihre beiden
# ausschliesslich von ihr genutzten Hilfen sind entfallen; die Importe
# hier sind entsprechend auf das noch Gebrauchte zurückgeschnitten.
from portfolio.models import Einheit, Geraet
from rentals.models import Mietvertrag
from finance.models import DebitorenRechnung

from django.shortcuts import redirect
from core.auth import rolle_erforderlich, ROLLE_VERWALTER, ROLLE_SACHBEARBEITER
from django.contrib import messages
import datetime

# Import für den Marktdaten-Sync
from core.tenancy import aktuelle_organisation, organisation_der_anfrage
from core.utils.market_data import update_verwaltung_rates

@rolle_erforderlich(ROLLE_VERWALTER, ROLLE_SACHBEARBEITER)
def update_market_data_view(request):
    """
    Startet den manuellen Import von BWO (Zins) und BFS (LIK).
    """
    # Nur die eigene Verwaltung — der Knopf gehoert dem angemeldeten Team.
    msg, errors = update_verwaltung_rates(organisation_der_anfrage(request))

    # Eventuelle Warnungen anzeigen
    if errors:
        for error in errors:
            messages.warning(request, error)

    # Erfolgsmeldung anzeigen und zurück zur neuen Oberfläche
    messages.success(request, msg)
    return redirect('fw_dashboard')


# ====================================================================
# HILFSFUNKTIONEN (Damit wir den Code nicht doppelt schreiben müssen)
# ====================================================================

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
    ).prefetch_related('zahlungseingaenge')
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
