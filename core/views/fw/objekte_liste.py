# core/views/fw/objekte_liste.py
#
# Objektliste (Einheiten gruppiert nach Liegenschaft) mit CSV-Export.
# Aus listen.py herausgeloest (reiner Umzug ohne Aenderung am Code).


from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from core.auth import (rolle_erforderlich, TEAM_ROLLEN)
from portfolio.models import Einheit
from core.views.fw._liste import (blaettern, csv_antwort, query_mit)


from ._basis import (_global_filter)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_objekte(request):
    """Objektliste nach G9 — sortiert nach Befund, gruppiert nach Liegenschaft.

    Die Gruppierung nach Liegenschaft bleibt (Entscheid 21.08.2026), aber die
    Gruppen folgen nicht mehr dem Alphabet, sondern dem Befund. Und die Filter
    machen die Arbeit: «Mit Befund» reduziert zwoelf Liegenschaften auf die
    drei, um die es geht.

    Das zweite Suchfeld in der Karte ist entfallen — die Topbar hat eines, und
    zwei Suchfelder auf einer Seite sind eine Frage zu viel. `q` wird
    weiterhin entgegengenommen, damit gespeicherte Adressen nicht brechen.
    """
    from faelle.objekte import TYP_GRUPPEN, gruppen, streifen, zeilen

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    from core.services.archiv import ausblenden
    einheiten = ausblenden(Einheit.objects.select_related('liegenschaft'))
    if aktive_lg:
        einheiten = einheiten.filter(liegenschaft=aktive_lg)

    typ_filter = request.GET.get('typ', '')
    if typ_filter in TYP_GRUPPEN:
        einheiten = einheiten.filter(typ__in=TYP_GRUPPEN[typ_filter])
    q = (request.GET.get('q') or '').strip()
    if q:
        einheiten = einheiten.filter(
            Q(bezeichnung__icontains=q) | Q(liegenschaft__strasse__icontains=q))

    alle = zeilen(einheiten)
    kopf = streifen(alle)

    # Der Zustandsfilter wirkt NACH der Befundrechnung — die Zahlen im Kopf
    # zeigen weiterhin das ganze Portfolio. Wuerden sie mitfiltern, stuende
    # dort bei aktivem Filter «2 von 2 mit Befund», und der Streifen waere
    # wertlos (dasselbe Argument wie beim Streifen der Liegenschaftsliste).
    zustand = request.GET.get('zustand', '')
    if zustand == 'befund':
        sichtbar = [z for z in alle if z['befunde']]
    elif zustand == 'leer':
        sichtbar = [z for z in alle if not z['versorgt']]
    else:
        zustand = ''
        sichtbar = alle

    alle_gruppen = gruppen(sichtbar)
    if request.GET.get('export') == 'csv':
        return _objekte_csv(alle_gruppen)

    # Geblättert wird in GANZEN Gruppen (Liegenschaften), nicht in Zeilen:
    # Eine Liegenschaft, deren Objekte auf zwei Seiten verteilt sind, zeigte
    # oben auf der zweiten Seite eine zweite Kopfzeile mit halben Zahlen.
    seite, query_ohne_seite = blaettern(request, alle_gruppen, pro_seite=OBJEKT_GRUPPEN_JE_SEITE)

    return render(request, 'fw/objekte.html', {
        **basis, 'nav': 'objekte',
        'gruppen': seite.object_list, 'kopf': kopf,
        'seite': seite, 'query_ohne_seite': query_ohne_seite,
        'csv_url': query_mit(request, export='csv'),
        'typ_filter': typ_filter, 'zustand': zustand, 'q': q,
        'gefiltert': len(sichtbar) != len(alle),
        'sichtbar_anzahl': len(sichtbar),
        'typ_chips': [('', _('Alle')), ('wohnen', _('Wohnen')),
                      ('parkplatz', _('Parkplatz')), ('gewerbe', _('Gewerbe'))],
        'zustand_chips': [('', _('Alle Zustände')),
                          ('befund', _('Mit Befund (%(n)s)') % {'n': kopf['mit_befund']}),
                          ('leer', _('Leerstand (%(n)s)') % {'n': kopf['leer']})],
    })

#: Liegenschaften je Seite in der Objektliste — eine Gruppe hat oft zehn und
#: mehr Objekte, 50 Gruppen wären eine Seite mit tausend Zeilen.
OBJEKT_GRUPPEN_JE_SEITE = 20


def _objekte_csv(gruppenliste):
    heute = timezone.localdate()
    return csv_antwort(
        f'Objekte_{heute:%Y-%m-%d}.csv',
        [_('Liegenschaft'), _('PLZ'), _('Ort'), _('Objekt'), _('Typ'), _('Zimmer'),
         _('Fläche m²'), _('Mieter'), _('Nettomiete (CHF)'), _('Vermietet'), _('Befund')],
        ([g['lg'].strasse, g['lg'].plz, g['lg'].ort, z['e'].bezeichnung,
          z['e'].get_typ_display(),
          # «3.5», nicht «3.50» — Zimmer sind kein Betrag.
          f"{z['e'].zimmer:g}" if z['e'].zimmer is not None else '', z['e'].flaeche_m2, z['mieter'] or '',
          z['e'].nettomiete_aktuell, _('ja') if z['belegt'] else _('nein'),
          ', '.join(str(b['text']) for b in z['befunde'])]
         for g in gruppenliste for z in g['zeilen']))
