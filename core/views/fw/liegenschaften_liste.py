# core/views/fw/liegenschaften_liste.py
#
# Liegenschaftsliste mit Befundfilter und CSV-Export.
# Aus listen.py herausgeloest (reiner Umzug ohne Aenderung am Code).


from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core.auth import (rolle_erforderlich, TEAM_ROLLEN)
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag
from core.views.fw._liste import (Sortierung, blaettern, csv_antwort, natuerlich, query_mit,
                                  sortieren, sortierung_waehlen, suche_anwenden,
                                  suchtext, verdeckte_felder)


from ._basis import (_global_filter)


#: Die Filterleiste ueber der Liegenschaftsliste. Die Schluessel sind dieselben
#: Kategorien, die `faelle.liegenschaften` an die Chips haengt — deshalb steht
#: dort auch die Zuordnung. Waere sie hier noch einmal gebaut, koennten Chip
#: und Filter auseinanderlaufen, ohne dass ein Test es merkt.
BEFUND_FILTER = {
    'leer': 'Leerstand',
    'frist': 'Fristen',
    'ticket': 'Tickets',
    'budget': 'Unterhalt',
}


def _befund_zaehler(rows):
    """Wie viele Zeilen jeder Filter treffen wuerde — fuer die Zahl am Chip.

    Ein Filter, der auf eine leere Liste fuehrt, ist eine Sackgasse: Man klickt,
    sieht nichts und weiss nicht, ob der Filter kaputt ist oder der Bestand
    sauber. Mit der Zahl daneben ist beides vorher sichtbar.
    """
    zaehler = {k: sum(1 for r in rows if k in r['kategorien'])
               for k in BEFUND_FILTER}
    zaehler['ohne'] = sum(1 for r in rows if r['ohne_befund'])
    return zaehler


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_liegenschaften(request):
    """Eine Zeile je Liegenschaft, sortiert nach Befund — nicht nach Adresse.

    Das Rechnen steht in `faelle.liegenschaften`, nicht hier: Die Leerstands-
    regel ist eine fachliche Festlegung (leer ab Ende der Kuendigungsfrist, ein
    Objekt genuegt, Nachmieter hebt auf) und gehoert an eine Stelle, an der man
    sie samt Begruendung findet und einzeln pruefen kann.
    """
    from faelle.liegenschaften import streifen, zeilen as befundzeilen

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    liegenschaften = Liegenschaft.objects.select_related('eigentuemer').order_by('strasse')
    if aktive_lg:
        liegenschaften = liegenschaften.filter(id=aktive_lg.id)

    alle = befundzeilen(liegenschaften)
    # Der Streifen zaehlt das GANZE Portfolio, auch wenn die Liste darunter
    # gefiltert ist. Sonst zeigt der Filter «Leerstand» eine Leerstandsquote
    # von 100 % — richtig gerechnet und trotzdem irrefuehrend.
    kennzahlen = streifen(alle)

    # Suche vor dem Befundfilter: Die Zahlen an den Chips gelten dann für
    # das, was die Suche übrig lässt — ein Chip «Leerstand 3», der nach dem
    # Klick eine leere Liste zeigt, wäre eine Sackgasse.
    suche = suchtext(request)
    gesucht = suche_anwenden(alle, suche, _lg_suchtext)

    befund = request.GET.get('befund', '')
    if befund == 'ohne':
        rows = [r for r in gesucht if r['ohne_befund']]
    elif befund in BEFUND_FILTER:
        rows = [r for r in gesucht if befund in r['kategorien']]
    else:
        befund = ''
        rows = gesucht

    sort = sortierung_waehlen(request, LG_SORTEN, 'befund')
    rows = sortieren(rows, LG_SORTEN, sort)

    if request.GET.get('export') == 'csv':
        return _lg_csv(rows)

    seite, query_ohne_seite = blaettern(request, rows)

    # konzept-v8 (#akten): Befund «CHF … offen» und der Zaehler am Reiter
    # «Mietverhältnisse». Beides nur lesend: Ausstaende in zwei Abfragen fuer
    # die ANGEZEIGTE Seite (`faelle.liegenschaften.ausstaende`), die Vertraege
    # in einer Zaehlung — dieselbe Menge wie die Vertragsliste ohne Filter.
    from faelle.liegenschaften import ausstaende as _ausstaende
    offen_je_lg = _ausstaende([r['lg'].id for r in seite.object_list])
    for r in seite.object_list:
        r['ausstand'] = (offen_je_lg.get(r['lg'].id) or {}).get('betrag')
    vertraege_qs = Mietvertrag.objects.all()
    if aktive_lg:
        vertraege_qs = vertraege_qs.filter(einheit__liegenschaft=aktive_lg)

    return render(request, 'fw/liegenschaften.html', {
        'vertraege_anzahl': vertraege_qs.count(),
        **basis, 'nav': 'liegenschaften', 'rows': seite.object_list,
        'seite': seite, 'query_ohne_seite': query_ohne_seite,
        'treffer': len(rows), 'alle_rows': len(alle), 'gesucht_rows': len(gesucht),
        'kennzahlen': kennzahlen, 'befund': befund, 'suche': suche,
        'filter_zaehler': _befund_zaehler(gesucht),
        'filter_urls': {k or 'alle': query_mit(request, befund=k)
                        for k in ('', *BEFUND_FILTER, 'ohne')},
        'suche_aufheben_url': query_mit(request, suche=None),
        'sort': sort,
        'sorten': [(k, s.label) for k, s in LG_SORTEN.items()],
        'csv_url': query_mit(request, export='csv'),
        'verdeckt': verdeckte_felder(request, 'suche', 'sort'),
    })


def _lg_suchtext(r):
    lg = r['lg']
    return ' '.join(str(x) for x in (lg.strasse, lg.plz, lg.ort, lg.kanton,
                                      lg.eigentuemer or '') if x)


#: Wählbare Sortierungen der Liegenschaftsliste. «Befund» ist die Reihenfolge,
#: in der `faelle.liegenschaften.zeilen` liefert — dort steht, warum.
LG_SORTEN = {
    'befund': Sortierung(gettext_lazy('Befund'), None),
    'adresse': Sortierung(gettext_lazy('Adresse'),
                          lambda r: (natuerlich(r['lg'].strasse), r['lg'].id)),
    'ort': Sortierung(gettext_lazy('Ort'),
                      lambda r: (natuerlich(r['lg'].ort), natuerlich(r['lg'].strasse), r['lg'].id)),
    'objekte': Sortierung(gettext_lazy('Anzahl Objekte'),
                          lambda r: r['einheiten'], absteigend=True),
    'ertrag': Sortierung(gettext_lazy('Ist-Miete'),
                         lambda r: r['ertrag'], absteigend=True),
}


def _lg_csv(rows):
    heute = timezone.localdate()
    return csv_antwort(
        f'Liegenschaften_{heute:%Y-%m-%d}.csv',
        [_('Strasse'), _('PLZ'), _('Ort'), _('Kanton'), _('Eigentümer'),
         _('Objekte'), _('Belegt'), _('Leer'), _('Belegung %'),
         _('Ist-Miete pro Monat (CHF)'), _('Befund')],
        ([r['lg'].strasse, r['lg'].plz, r['lg'].ort, r['lg'].kanton,
          r['lg'].eigentuemer or '', r['einheiten'], r['belegt'], r['leer'],
          r['belegung'], r['ertrag'], ', '.join(str(c[1]) for c in r['chips'])]
         for r in rows))
