# core/views/fw/assets.py
#
# Block 9 der 33 (Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md): Geraete und
# Anlagen mit Garantie- und Wartungsfristen.
#
# Unveraendert uebernommen. Neu sind nur die Importe hier oben, die vorher
# aus dem Dateikopf der alten fw.py kamen.

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from core.auth import rolle_erforderlich, TEAM_ROLLEN
from portfolio.models import Einheit, Liegenschaft

from ._basis import _global_filter


# ============================================================
# ETAPPE D: ASSETS (Geräte / Anlagen mit Garantie)
# ============================================================

from datetime import timedelta as _timedelta

ASSET_ICON = {
    'geschirrspueler': 'fa-sink', 'waschmaschine': 'fa-soap', 'tumbler': 'fa-wind',
    'backofen': 'fa-fire-burner', 'kuehlschrank': 'fa-snowflake', 'dampfabzug': 'fa-fan',
    'heizung': 'fa-temperature-half', 'boiler': 'fa-water', 'lift': 'fa-elevator',
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_assets(request):
    from portfolio.models import Geraet
    heute = timezone.localdate()
    grenze = heute + _timedelta(days=90)
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (Geraet.objects.select_related('liegenschaft', 'einheit__liegenschaft')
          .order_by('garantie_bis'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(einheit__liegenschaft=aktive_lg))

    g_filter = request.GET.get('garantie', '')
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(kategorie__icontains=q) | Q(marke__icontains=q) | Q(modell__icontains=q)
                       | Q(sonstiges_bezeichnung__icontains=q))

    rows = []
    n_aktiv = n_bald = n_abgelaufen = 0
    for g in qs:
        gb = g.garantie_bis
        if gb is None:
            g_status, g_cls, g_key = 'keine Angabe', 'bg-slate-100 text-slate-400', 'ohne'
        elif gb < heute:
            g_status, g_cls, g_key = 'abgelaufen', 'bg-slate-100 text-slate-500', 'abgelaufen'
            n_abgelaufen += 1
        elif gb < grenze:
            g_status, g_cls, g_key = 'läuft bald ab', 'bg-amber-50 text-amber-700', 'bald'
            n_bald += 1
        else:
            g_status, g_cls, g_key = 'aktiv', 'bg-emerald-50 text-emerald-700', 'aktiv'
            n_aktiv += 1
        # nach Filter erst NACH Zählung aussortieren (KPI zeigt Gesamtbild)
        if g_filter and g_filter != g_key:
            continue
        lg = g.liegenschaft or (g.einheit.liegenschaft if g.einheit_id else None)
        standort = '—'
        if g.einheit_id:
            standort = f"{g.einheit.liegenschaft.strasse} · {g.einheit.bezeichnung}"
        elif lg:
            standort = f"{lg.strasse} · Allgemein"
        name = g.kategorie if g.kategorie != 'sonstiges' else (g.sonstiges_bezeichnung or 'Gerät')
        rows.append({
            'g': g, 'name': name, 'standort': standort,
            'icon': ASSET_ICON.get(g.kategorie, 'fa-plug'),
            'g_status': g_status, 'g_cls': g_cls,
            'lg_id': g.einheit.liegenschaft_id if g.einheit_id else g.liegenschaft_id,
            'einheit_id': g.einheit_id,
        })

    chips = [('', 'Alle'), ('aktiv', 'Garantie aktiv'), ('bald', 'Läuft bald ab'),
             ('abgelaufen', 'Abgelaufen'), ('ohne', 'Ohne Garantie')]

    # Raumbuch portfolioweit — Ausstattung je Objekt (Raum entsteht aus Assets)
    from portfolio.models import Ausstattung
    aqs = (Ausstattung.objects.select_related('einheit__liegenschaft')
           .order_by('einheit__liegenschaft__strasse', 'einheit__bezeichnung', 'raum', 'sortierung'))
    if aktive_lg:
        aqs = aqs.filter(einheit__liegenschaft=aktive_lg)
    ZUSTAND_CLS = {
        'neuwertig': 'bg-emerald-50 text-emerald-700', 'gut': 'bg-emerald-50 text-emerald-700',
        'gebraucht': 'bg-amber-50 text-amber-700', 'defekt': 'bg-rose-50 text-rose-700'}
    # Raumbuch pro Objekt gruppiert (Objekt → Räume → Elemente)
    from collections import OrderedDict
    _obj = OrderedDict()
    ausst_count = 0
    for a in aqs:
        e = a.einheit
        if not e:
            continue
        ausst_count += 1
        entry = _obj.setdefault(e.id, {'einheit': e, 'raeume': OrderedDict(), 'count': 0})
        entry['count'] += 1
        entry['raeume'].setdefault(a.raum, []).append({
            'a': a, 'zustand_cls': ZUSTAND_CLS.get(a.zustand, 'bg-slate-100 text-slate-500'),
        })
    raumbuch_objekte = [{
        'einheit': v['einheit'], 'count': v['count'],
        'raeume': [{'raum': r, 'elemente': els} for r, els in v['raeume'].items()],
    } for v in _obj.values()]

    return render(request, 'fw/assets.html', {
        **basis, 'nav': 'assets', 'rows': rows,
        'g_filter': g_filter, 'garantie_chips': chips, 'q': q,
        'anzahl': len(rows), 'n_aktiv': n_aktiv, 'n_bald': n_bald, 'n_abgelaufen': n_abgelaufen,
        'raumbuch_objekte': raumbuch_objekte, 'ausst_count': ausst_count,
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        'einheiten': Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'),
    })
