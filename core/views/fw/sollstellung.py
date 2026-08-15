# core/views/fw/sollstellung.py
#
# Block 12 der 33 (Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md): der monatliche
# Mietenlauf — aus den aktiven Vertraegen die Debitorenrechnungen des Monats
# stellen.
#
# Reiner Umzug, Zeile fuer Zeile unveraendert. Das ist hier besonders wichtig:
# Der Mietenlauf erzeugt Forderungen. Der Skill schweizer-fachlogik verlangt,
# dass an solcher Logik nichts "nebenbei" geaendert wird — der Nachweis dafuer
# ist die Gleichheitspruefung gegen HEAD, nicht ein gutes Gefuehl.

from datetime import date
from decimal import Decimal

from django.shortcuts import render
from django.utils import timezone

from core.auth import rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN, TEAM_ROLLEN
from finance.models import DebitorenRechnung
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter


# ============================================================
# ETAPPE D: SOLLSTELLUNG MIETE (monatlicher Mietenlauf)
# ============================================================

import calendar as _calendar


def _sollstellung_kontext(request):
    """Vorschau: aktive Verträge + Soll je Vertrag für den gewählten Monat."""
    heute = timezone.localdate()
    try:
        jahr = int(request.GET.get('jahr') or heute.year)
        monat = int(request.GET.get('monat') or heute.month)
    except ValueError:
        jahr, monat = heute.year, heute.month
    monat = min(max(monat, 1), 12)

    start_date = date(jahr, monat, 1)
    _, last_day = _calendar.monthrange(jahr, monat)
    end_date = date(jahr, monat, last_day)
    titel = f"Miete & NK {monat:02d}/{jahr}"

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    vertraege = (Mietvertrag.objects.filter(status__in=['aktiv', 'gekuendigt'], beginn__lte=end_date)
                 .exclude(ende__lt=start_date)
                 .select_related('mieter', 'einheit__liegenschaft')
                 # Alles, was `verrechneter_netto_mietzins` / `verrechnete_nebenkosten`
                 # unten je Vertrag anfassen — sonst fragt die Vorschau pro Zeile
                 # einzeln nach (gemessen: 325 Abfragen bei 34 Verträgen).
                 .prefetch_related('mietzins_komponenten', 'staffelstufen',
                                   'anpassungen', 'einheit__sollmietzinse'))
    if aktive_lg:
        vertraege = vertraege.filter(einheit__liegenschaft=aktive_lg)

    # «Ist für diesen Vertrag schon gestellt?» in EINER Abfrage statt einer je
    # Vertrag. Die Menge ist klein (ein Monat), das Nachschlagen im Set gratis.
    schon_gestellt = set(
        DebitorenRechnung.objects.filter(titel=titel, vertrag__in=vertraege)
        .exclude(status='storniert').values_list('vertrag_id', flat=True))

    rows = []
    total_soll = Decimal('0.00')
    n_offen = n_gestellt = 0
    for v in vertraege:
        v_start = max(start_date, v.beginn)
        v_ende = min(end_date, v.ende) if v.ende else end_date
        tage_aktiv = (v_ende - v_start).days + 1
        faktor = Decimal(tage_aktiv) / Decimal(last_day)
        # Wie im tatsächlichen Lauf (run_sollstellung) die VERRECHNETEN Werte nutzen
        # (Staffel/Index/Gratismonat/Komponenten berücksichtigt) — sonst weicht die
        # Vorschau-Summe vom real gestellten Debitor ab.
        netto = round((v.verrechneter_netto_mietzins(start_date) or Decimal('0')) * faktor, 2)
        nk = round((v.verrechnete_nebenkosten(start_date) or Decimal('0')) * faktor, 2)
        total = netto + nk
        if total <= 0:
            continue
        gestellt = v.id in schon_gestellt
        if gestellt:
            n_gestellt += 1
        else:
            n_offen += 1
            total_soll += total
        rows.append({
            'v': v, 'mieter': v.mieter.display_name,
            'objekt': f"{v.einheit.liegenschaft.strasse} · {v.einheit.bezeichnung}",
            'netto': netto, 'nk': nk, 'total': total,
            'prorata': tage_aktiv < last_day, 'tage': tage_aktiv, 'tage_monat': last_day,
            'gestellt': gestellt,
        })

    monate = [(m, date(2000, m, 1).strftime('%B')) for m in range(1, 13)]
    jahre = list(range(heute.year - 2, heute.year + 2))
    return {
        **basis, 'nav': 'sollstellung', 'rows': rows,
        'jahr': jahr, 'monat': monat, 'titel': titel,
        'total_soll': total_soll, 'n_offen': n_offen, 'n_gestellt': n_gestellt,
        'monate': monate, 'jahre': jahre,
        'monat_name': date(2000, monat, 1).strftime('%B'),
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_sollstellung(request):
    from django.contrib import messages
    ctx = _sollstellung_kontext(request)
    ctx['meldung'] = list(messages.get_messages(request))
    return render(request, 'fw/sollstellung.html', ctx)


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_sollstellung_run(request):
    """Führt den Mietenlauf für den gewählten Monat aus (idempotent, Pro-Rata,
    Debitoren 1100 an Ertrag 3000 / NK-Akonto 3020) — wie die Finanz-API."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_sollstellung')

    heute = timezone.localdate()
    try:
        jahr = int(request.POST.get('jahr') or heute.year)
        monat = int(request.POST.get('monat') or heute.month)
    except ValueError:
        jahr, monat = heute.year, heute.month
    # Bereichs-Validierung: Monat 13 / Jahr 20260 crashte sonst mit HTTP 500
    # tief in run_sollstellung (date(jahr, 13, 1)).
    if not (1 <= monat <= 12) or not (2000 <= jahr <= 2100):
        messages.error(request, f"Ungültiger Monat {monat:02d}/{jahr} — bitte Monat 1–12 wählen.")
        return redirect('fw_sollstellung')

    titel = f"Miete & NK {monat:02d}/{jahr}"
    # Der Lauf muss demselben Liegenschaftsfilter folgen wie die Vorschau darüber
    # — sonst stellt ein Klick auf «Sollstellung starten» dem ganzen Portfolio
    # Rechnung, obwohl der Dialog die gefilterte Anzahl nannte (Praxis-Audit).
    # `lg` kommt beim POST aus dem Formular-Feld (_global_filter liest nur GET).
    lauf_lg = Liegenschaft.objects.filter(id=request.POST.get('lg') or None).first()
    from core.services.automation import run_sollstellung
    try:
        erstellt = run_sollstellung(jahr, monat, user=request.user, liegenschaft=lauf_lg)
    except RuntimeError as e:
        messages.error(request, f"{e}")
        return redirect(f'/neu/sollstellung/?jahr={jahr}&monat={monat}')

    log_aktion(request, "Sollstellung ausgeführt", titel,
               f"{erstellt} Rechnungen erstellt"
               + (f" · nur {lauf_lg.strasse}" if lauf_lg else " · ganzes Portfolio"))
    umfang = f" ({lauf_lg.strasse})" if lauf_lg else ""
    if erstellt:
        messages.success(request, f"✅ Sollstellung {titel}{umfang}: {erstellt} Rechnung(en) erstellt.")
    else:
        messages.success(request, f"Sollstellung {titel}{umfang}: alles bereits gestellt — "
                                  f"nichts Neues erzeugt.")
    ziel = f'/neu/sollstellung/?jahr={jahr}&monat={monat}'
    if lauf_lg:
        ziel += f'&lg={lauf_lg.id}'
    return redirect(ziel)
