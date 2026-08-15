# core/views/fw/hypotheken.py
#
# Finanzierung je Liegenschaft. Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.

from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.shortcuts import render
from django.utils import timezone

from core.auth import rolle_erforderlich, SCHREIB_ROLLEN, TEAM_ROLLEN
from portfolio.models import Liegenschaft

from ._basis import _global_filter, _num


# ============================================================
# HYPOTHEKEN (Finanzierung je Liegenschaft)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_hypotheken(request):
    """Hypotheken je Liegenschaft: Schuld, Zinssatz/-kosten, Ablauf/Fälligkeit.
    Gruppiert nach Liegenschaft (Akkordeon), mit Erfassen/Löschen und
    Ablauf-Warnung für die Refinanzierung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Hypothek
    from core.auth import log_aktion, hat_rolle
    heute = timezone.localdate()
    grenze = heute + _timedelta(days=180)
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    if request.method == 'POST' and hat_rolle(request.user, SCHREIB_ROLLEN):
        aktion = request.POST.get('aktion')
        if aktion == 'neu':
            lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()

            def _dec(x):
                try:
                    return Decimal(_num(x) or '0')
                except Exception:
                    return Decimal('0.00')

            def _date(x):
                try:
                    return date.fromisoformat(x)
                except Exception:
                    return None
            if lg:
                Hypothek.objects.create(
                    liegenschaft=lg, bank=(request.POST.get('bank') or '').strip(),
                    bezeichnung=(request.POST.get('bezeichnung') or '').strip(),
                    betrag=_dec(request.POST.get('betrag')),
                    zinssatz=_dec(request.POST.get('zinssatz')),
                    typ=request.POST.get('typ') or 'fest',
                    beginn=_date(request.POST.get('beginn')),
                    ablauf=_date(request.POST.get('ablauf')),
                    notiz=(request.POST.get('notiz') or '').strip())
                log_aktion(request, "Hypothek erfasst", lg.strasse, f"CHF {request.POST.get('betrag')}")
                messages.success(request, "✅ Hypothek erfasst.")
            else:
                messages.error(request, "Liegenschaft ist Pflicht.")
        elif aktion == 'loeschen':
            Hypothek.objects.filter(id=request.POST.get('id') or None).delete()
            messages.success(request, "Hypothek gelöscht.")
        return redirect('/neu/hypotheken/' + (f'?lg={aktive_lg.id}' if aktive_lg else ''))

    qs = Hypothek.objects.select_related('liegenschaft').order_by(
        'liegenschaft__strasse', 'ablauf', 'id')
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    gruppen = []
    total_schuld = total_zins = Decimal('0.00')
    n_ablaufend = 0
    for hy in qs:
        ablauf_status = 'ok'
        if hy.ablauf:
            if hy.ablauf < heute:
                ablauf_status = 'abgelaufen'; n_ablaufend += 1
            elif hy.ablauf < grenze:
                ablauf_status = 'bald'; n_ablaufend += 1
        total_schuld += hy.betrag
        total_zins += hy.jaehrlicher_zins
        row = {'hy': hy, 'zins': hy.jaehrlicher_zins, 'ablauf_status': ablauf_status}
        if gruppen and gruppen[-1]['lg'].id == hy.liegenschaft_id:
            gruppen[-1]['rows'].append(row)
        else:
            gruppen.append({'lg': hy.liegenschaft, 'rows': [row]})
    for g in gruppen:
        g['schuld'] = sum((r['hy'].betrag for r in g['rows']), Decimal('0.00'))
        g['zins'] = sum((r['zins'] for r in g['rows']), Decimal('0.00'))
        vw = g['lg'].versicherungswert or Decimal('0')
        g['belehnung'] = int((g['schuld'] / vw * 100).to_integral_value()) if vw > 0 else None
    avg_zins = (total_zins / total_schuld * 100).quantize(Decimal('0.001')) if total_schuld > 0 else Decimal('0.000')

    return render(request, 'fw/hypotheken.html', {
        **basis, 'nav': 'hypotheken', 'gruppen': gruppen,
        'total_schuld': total_schuld, 'total_zins': total_zins,
        'avg_zins': avg_zins, 'n_ablaufend': n_ablaufend,
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        'kann_schreiben': hat_rolle(request.user, SCHREIB_ROLLEN),
    })
