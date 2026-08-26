# core/views/fw/dokumente.py
#
# Zentrale Dokumentenablage aus beiden Quellen (rentals.Dokument und
# portfolio-seitige Ablage — die Zusammenfuehrung der zwei Modelle ist
# TS-6/P2.1 und ausdruecklich NICHT Teil dieses Umzugs).
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.

from datetime import date

from django.db.models import Q
from django.shortcuts import render

from core.auth import rolle_erforderlich, TEAM_ROLLEN
from portfolio.models import Einheit, Liegenschaft

from ._basis import _global_filter


# ============================================================
# ETAPPE D: DOKUMENTE (zentrale Ablage aus beiden Quellen)
# ============================================================

DOK_ICON = {
    'vertrag': ('vertrag', 'fw-markenflaeche fw-marke'),
    'protokoll': ('gut', 'fw-gut-flaeche fw-gut'),
    'korrespondenz': ('senden', 'fw-info-flaeche fw-info'),
    'sonstiges': ('dokument', 'fw-flaeche2 fw-mutet'),
}


def _dok_icon(kat):
    return DOK_ICON.get((kat or '').lower(), ('dokument', 'fw-flaeche2 fw-mutet'))


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_dokumente(request):
    from rentals.models import Dokument as RDok
    from portfolio.models import Dokument as PDok
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    kat_filter = (request.GET.get('kat') or '').strip().lower()
    q = (request.GET.get('q') or '').strip()

    eintraege = []

    # 1) Vertrags-/Mieter-Ablage (rentals)
    rqs = RDok.objects.select_related('liegenschaft', 'mieter', 'vertrag', 'einheit').order_by('-datum')
    if aktive_lg:
        rqs = rqs.filter(Q(liegenschaft=aktive_lg) | Q(einheit__liegenschaft=aktive_lg))
    for d in rqs:
        if not d.datei:
            continue
        name = d.bezeichnung or d.titel or 'Dokument'
        kontext = ''
        if d.mieter_id:
            kontext = d.mieter.display_name
        elif d.liegenschaft_id:
            kontext = d.liegenschaft.strasse
        eintraege.append({
            'name': name, 'kat': d.kategorie or 'sonstiges', 'datum': d.datum,
            'url': d.datei.url, 'kontext': kontext, 'quelle': 'Vertragsablage',
        })

    # 2) Objekt-/Liegenschafts-Ablage (portfolio)
    pqs = PDok.objects.select_related('liegenschaft', 'einheit').order_by('-datum')
    if aktive_lg:
        pqs = pqs.filter(Q(liegenschaft=aktive_lg) | Q(einheit__liegenschaft=aktive_lg))
    for d in pqs:
        if not d.datei:
            continue
        kontext = d.liegenschaft.strasse if d.liegenschaft_id else (d.einheit.bezeichnung if d.einheit_id else '')
        eintraege.append({
            'name': d.titel or 'Dokument', 'kat': d.kategorie or 'sonstiges', 'datum': d.datum,
            'url': d.datei.url, 'kontext': kontext, 'quelle': 'Objektablage',
            'id': d.id, 'loeschbar': True,
        })

    # Kategorien für Chips (aus vorhandenen)
    vorhanden = sorted({(e['kat'] or 'sonstiges').lower() for e in eintraege})

    # Filter anwenden
    if kat_filter:
        eintraege = [e for e in eintraege if (e['kat'] or 'sonstiges').lower() == kat_filter]
    if q:
        ql = q.lower()
        eintraege = [e for e in eintraege if ql in e['name'].lower() or ql in (e['kontext'] or '').lower()]

    # Icon + Sortierung
    for e in eintraege:
        e['icon'], e['icon_cls'] = _dok_icon(e['kat'])
    eintraege.sort(key=lambda e: e['datum'] or date.min, reverse=True)

    kat_labels = {'vertrag': 'Verträge', 'protokoll': 'Protokolle', 'korrespondenz': 'Korrespondenz',
                  'sonstiges': 'Sonstiges', 'allgemein': 'Allgemein'}
    kat_chips = [('', 'Alle')] + [(k, kat_labels.get(k, k.capitalize())) for k in vorhanden]

    return render(request, 'fw/dokumente.html', {
        **basis, 'nav': 'dokumente', 'eintraege': eintraege,
        'kat_filter': kat_filter, 'kat_chips': kat_chips, 'q': q,
        'anzahl': len(eintraege),
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        'einheiten': Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'),
    })
