# core/views/fw/mwst.py
#
# Block 24 der 33 (Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md): Umsatzsteuer
# gegen Vorsteuer, effektive Methode und Saldosteuersatz, ESTV-Export.
#
# Der Block ist deutlich kuerzer als im Auftrag angegeben (90 statt 191
# Zeilen): Seine drei Helfer _mwst_beleg, _mwst_bereits_verbucht und
# _mwst_periode liegen seit Schnitt 0b in _basis.py, weil sie auch anderswo
# gebraucht werden. Genau dafuer war der Schritt gedacht.

from decimal import Decimal

from django.shortcuts import render
from django.utils import timezone

from core.auth import rolle_erforderlich, ROLLE_VERWALTER, TEAM_ROLLEN

from ._basis import (_global_filter, _mwst_beleg, _mwst_bereits_verbucht,
                     _mwst_periode, _num)
from core.tenancy import aktuelle_organisation


# ============================================================
# MWST-AUSWERTUNG (Umsatzsteuer vs. Vorsteuer = Zahllast)
# ============================================================







@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mwst(request):
    """MWST-Abrechnung: geschuldete Umsatzsteuer (2200) minus Vorsteuer (1170) = Zahllast."""
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    quartal = request.GET.get('quartal', '')  # '', '1'..'4'
    p = _mwst_periode(jahr, quartal, aktive_lg)
    vw = p['verwaltung']

    return render(request, 'fw/mwst.html', {
        **basis, 'nav': 'mwst', 'jahr': jahr, 'quartal': quartal,
        'von': p['von'], 'bis': p['bis'],
        'umsatzsteuer': p['umsatzsteuer'], 'vorsteuer': p['vorsteuer'],
        'zahllast': p['zahllast'],
        'umsatz_steuerbar': p['umsatz_steuerbar'], 'umsatz_brutto': p['umsatz_brutto'],
        'estv': p['estv'], 'saldo_vorteil': p['saldo_vorteil'],
        'mwst_verbucht': _mwst_bereits_verbucht(jahr, quartal, aktive_lg),
        'mwst_methode': p['methode'], 'saldosteuersatz': p['saldosteuersatz'],
        'mwst_uid': getattr(vw, 'mwst_uid', '') if vw else '',
        'jahre': list(range(heute.year, heute.year - 5, -1)),
    })


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_mwst_einstellungen(request):
    """Speichert MWST-Methode, Saldosteuersatz und MWST-Nummer."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Organisation
    if request.method != 'POST':
        return redirect('fw_mwst')
    vw = aktuelle_organisation()
    if not vw:
        messages.error(request, "Keine Verwaltung erfasst.")
        return redirect('fw_mwst')
    vw.mwst_methode = request.POST.get('mwst_methode', 'effektiv')
    vw.mwst_uid = (request.POST.get('mwst_uid') or '').strip()
    try:
        vw.saldosteuersatz = Decimal((_num(request.POST.get('saldosteuersatz')) or '0'))
    except Exception:
        vw.saldosteuersatz = Decimal('0')
    vw.save(update_fields=['mwst_methode', 'mwst_uid', 'saldosteuersatz'])
    messages.success(request, "✅ MWST-Einstellungen gespeichert.")
    ziel = request.POST.get('zurueck') or '/neu/mwst/'
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mwst_estv_export(request):
    """ESTV-Abrechnung als CSV (offizielle Ziffern) für den gewählten Zeitraum.

    Rechnet über denselben Helper wie Anzeige und Verbuchung. Vorher hatte der
    Export eine eigene Rechnung ohne die Brutto-Rückrechnung des Saldosteuersatzes
    und ohne Liegenschaftsfilter — die eingereichte Abrechnung wich damit von der
    angezeigten ab (Audit).
    """
    from django.http import HttpResponse
    from core.services.mwst_estv import estv_csv
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    quartal = request.GET.get('quartal', '')
    p = _mwst_periode(jahr, quartal, aktive_lg)
    von, bis, estv, vw = p['von'], p['bis'], p['estv'], p['verwaltung']
    csv_bytes = estv_csv(estv, firma=(vw.firma if vw else 'Verwaltung'),
                         uid=(vw.mwst_uid if vw else ''), periode_von=von, periode_bis=bis)
    resp = HttpResponse(csv_bytes, content_type='text/csv; charset=utf-8')
    zeitraum = f"{jahr}" + (f"_Q{quartal}" if quartal else "")
    resp['Content-Disposition'] = f'attachment; filename="ESTV_MWST_{zeitraum}.csv"'
    return resp
