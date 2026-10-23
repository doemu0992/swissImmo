"""Portfolio — die Seite für Eigentümer und Investoren (Berichte → Portfolio).

Rendite, Leerstand, Zahlungsmoral und Cashflow des Bestands auf einer Seite. Die
Zahlen kommen aus `core.services.portfolio_kennzahlen`; diese Ansicht wählt nur
aus (Mandat, Zeitraum, Verteilung) und legt sie hin.
"""
from collections import Counter
from datetime import date

from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from core.auth import TEAM_ROLLEN, rolle_erforderlich
from core.services import portfolio_kennzahlen as pk
from portfolio.models import Einheit, Liegenschaft

from ._basis import _global_filter
from ._liste import csv_antwort, query_mit

MONATE_KURZ = ['', 'Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
ZEITRAEUME = (6, 12, 24)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_portfolio(request):
    from crm.models import Eigentuemer
    basis = _global_filter(request)
    heute = timezone.localdate()

    lgs = Liegenschaft.objects.select_related('eigentuemer').order_by('strasse')
    mandat_id = request.GET.get('mandat', '')
    mandat = None
    if mandat_id.isdigit():
        mandat = Eigentuemer.objects.filter(pk=int(mandat_id)).first()
        if mandat:
            lgs = lgs.filter(eigentuemer=mandat)
    if basis['aktive_lg']:
        lgs = lgs.filter(pk=basis['aktive_lg'].pk)
    lgs = list(lgs)

    try:
        monate = int(request.GET.get('monate', 12))
    except ValueError:
        monate = 12
    monate = monate if monate in ZEITRAEUME else 12
    verteilung = 'nutzung' if request.GET.get('verteilung') == 'nutzung' else 'liegenschaft'

    u = pk.uebersicht(lgs, heute)
    reihe = pk.cashflow(lgs, monate, heute)

    if request.GET.get('export') == 'csv':
        return csv_antwort(
            f'Portfolio_{heute:%Y-%m-%d}.csv',
            [_('Liegenschaft'), _('Ort'), _('Objekte'), _('Leer'), _('Soll-Mietertrag p.a. (CHF)'),
             _('Betriebsaufwand 12 Mt. (CHF)'), _('Wert (CHF)'), _('Wertbasis'),
             _('Bruttorendite (%)'), _('Nettorendite (%)')],
            ([z['lg'].strasse, z['lg'].ort, z['objekte'], z['leer'], z['soll'], z['aufwand'],
              z['wert'] if z['wert'] else '', z['quelle'] or '',
              f"{z['brutto']:.2f}" if z['brutto'] is not None else '',
              f"{z['netto']:.2f}" if z['netto'] is not None else '']
             for z in u['zeilen']))

    if verteilung == 'nutzung':
        typen = dict(Einheit.TYP_CHOICES)
        zaehler = Counter(Einheit.objects.filter(liegenschaft__in=lgs).values_list('typ', flat=True))
        teile = [{'lab': str(typen.get(t, t)), 'wert': n} for t, n in zaehler.most_common()]
        mitte = (str(sum(zaehler.values())), _('Objekte'))
    else:
        teile = [{'lab': z['lg'].strasse, 'wert': z['soll']} for z in sorted(
            u['zeilen'], key=lambda z: -z['soll']) if z['soll'] > 0]
        mitte = (str(len(u['zeilen'])), _('Liegenschaften'))
    summe_teile = sum(float(t['wert']) for t in teile) or 1
    legende = [{**t, 'anteil': float(t['wert']) / summe_teile * 100, 'i': i % 6}
               for i, t in enumerate(teile)]

    ertrag_summe = sum(r['ertrag'] for r in reihe)
    aufwand_summe = sum(r['aufwand'] for r in reihe)
    return render(request, 'fw/portfolio.html', {
        **basis, 'nav': 'portfolio',
        'u': u, 'zeilen': u['zeilen'], 'reihe': reihe,
        'ertrag_werte': [float(r['ertrag']) for r in reihe],
        'aufwand_werte': [float(r['aufwand']) for r in reihe],
        'monate_namen': [MONATE_KURZ[r['monat'].month] for r in reihe],
        'ertrag_summe': ertrag_summe, 'aufwand_summe': aufwand_summe,
        'netto_summe': ertrag_summe - aufwand_summe,
        'hat_cashflow': any(r['ertrag'] or r['aufwand'] for r in reihe),
        'mandate': Eigentuemer.objects.filter(liegenschaften__isnull=False).distinct().order_by('pk'),
        'mandat': mandat, 'monate': monate, 'zeitraeume': ZEITRAEUME,
        'verteilung': verteilung, 'teile': teile, 'legende': legende,
        'donut_mitte': mitte, 'csv_url': query_mit(request, export='csv'),
        'stand': heute,
    })
