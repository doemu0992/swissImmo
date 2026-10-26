"""Zwei Arbeitsflächen aus dem UI-Audit (26.10.2026).

`/neu/leerstand/` — Leerstands-Cockpit für die Bewirtschaftung (faelle/leerstand_cockpit.py)
`/neu/team/`      — Team & Auslastung für die Geschäftsleitung (faelle/team_auslastung.py)

Die Ansichten wählen nur aus (Liegenschaft, Objektart, Zustand) und legen hin;
gerechnet wird in den beiden Modulen.
"""
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from core.auth import TEAM_ROLLEN, VERWALTUNGS_ROLLEN, rolle_erforderlich
from faelle import leerstand_cockpit, team_auslastung
from portfolio.models import Einheit

from ._basis import _global_filter
from ._liste import csv_antwort

__all__ = ['fw_leerstand', 'fw_team']

ZUSTAENDE = ('alle', 'leer', 'bald')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_leerstand(request):
    basis = _global_filter(request)
    heute = timezone.localdate()
    typ = request.GET.get('typ', 'alle')
    typ = typ if typ in ('wohnen', 'parkplatz', 'gewerbe') else 'alle'
    zustand = request.GET.get('zustand', 'alle')
    zustand = zustand if zustand in ZUSTAENDE else 'alle'

    qs = Einheit.objects.all()
    if basis['aktive_lg']:
        qs = qs.filter(liegenschaft=basis['aktive_lg'])
    qs = leerstand_cockpit.typ_filter(qs, typ)
    c = leerstand_cockpit.cockpit(qs, heute)
    zeilen = c['zeilen'] if zustand == 'alle' else [z for z in c['zeilen'] if z['zustand'] == zustand]

    if request.GET.get('export') == 'csv':
        return csv_antwort(
            f'Leerstand_{heute:%Y-%m-%d}.csv',
            [_('Liegenschaft'), _('Objekt'), _('Zustand'), _('Leer seit'), _('Frei ab'), _('Tage leer'),
             _('Netto-Mietzins (CHF)'), _('Ausfall bisher geschätzt (CHF)'), _('Ausgeschrieben'),
             _('Offene Bewerbungen'), _('Nächster Schritt')],
            ([z['lg'].strasse, z['e'].bezeichnung, _('leer') if z['zustand'] == 'leer' else _('wird frei'),
              z['leer_seit'].strftime('%d.%m.%Y') if z['leer_seit'] else '',
              z['frei_ab'].strftime('%d.%m.%Y') if z['frei_ab'] else '',
              z['tage'] if z['tage'] is not None else '', z['miete'] or '', z['ausfall_bisher'] or '',
              _('ja') if z['inseriert'] else _('nein'), z['bewerbungen'], z['schritt']['text']]
             for z in zeilen))

    return render(request, 'fw/leerstand.html', {
        **basis, 'nav': 'leerstand', 'heute': heute,
        'c': c, 'zeilen': zeilen, 'typ': typ, 'zustand': zustand,
        'typen': [('alle', _('Alle')), ('wohnen', _('Wohnen')), ('gewerbe', _('Gewerbe')), ('parkplatz', _('Parkplatz & Nebenobjekte'))],
        'zustaende': [('alle', _('Alle'), len(c['zeilen'])), ('leer', _('Steht leer'), c['n_leer']),
                      ('bald', _('Wird frei'), c['n_bald'])],
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_team(request):
    basis = _global_filter(request)
    a = team_auslastung.auslastung(getattr(request, 'organisation', None), timezone.localdate())
    return render(request, 'fw/team.html', {**basis, 'nav': 'team', 'a': a})
