# core/views/fw/vertraege_liste.py
#
# Vertragsliste mit Saldo, Mahnstufe und CSV-Export.
# Aus listen.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from collections import defaultdict
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core.auth import (rolle_erforderlich, TEAM_ROLLEN)
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag
from core.views.fw._liste import (Sortierung, blaettern, csv_antwort, query_mit,
                                  sortieren, sortierung_waehlen, verdeckte_felder)


from ._basis import (_global_filter, _vermietung_pipeline,
                     VERTRAG_PILL)


# Design-System-Chip-Variante je Status (fw-chip fw-<variant>)
VERTRAG_CHIP = {'aktiv': 'good', 'gekuendigt': 'crit',
                'entwurf': 'mut', 'archiviert': 'mut', 'beendet': 'mut'}

#: In der Auswahl erscheint «Archiviert» nicht mehr eigenstaendig — es geht in
#: «Beendet» auf, sonst haette der Nutzer zwei Filter fuer dieselbe Sache.
VERTRAG_FILTER = ('entwurf', 'aktiv', 'gekuendigt', 'beendet')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vertraege(request):
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (Mietvertrag.objects
          .select_related('mieter', 'einheit__liegenschaft')
          .order_by('-beginn'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    # Gefiltert wird nach dem ANZEIGE-Status, nicht nach dem gespeicherten.
    # Ein gekuendigter Vertrag, dessen Ende vorbei ist, gehoert unter
    # «Beendet» — und nicht mehr unter «Gekuendigt». Die Regel steht in
    # `Mietvertrag.anzeige_status`; hier wird sie in eine Abfrage uebersetzt,
    # damit die Datenbank filtert und nicht Python.
    heute = timezone.localdate()
    status_filter = request.GET.get('status', '')
    if status_filter == 'beendet':
        qs = qs.filter(Q(status='archiviert') | Q(ende__lt=heute))
    elif status_filter in VERTRAG_FILTER:
        # `exclude(ende__lt=heute)` deckt ALLE uebrigen Filter ab, auch
        # «Gekuendigt»: Ein gekuendigter Vertrag mit abgelaufenem Ende faellt
        # hier heraus und steht unter «Beendet».
        #
        # Ein eigener Zweig fuer «gekuendigt» stand hier zuerst und war
        # ueberfluessig — die Gegenprobe (Zweig entfernen) blieb gruen und hat
        # das gezeigt. Django nimmt NULL-Werte aus einem `exclude` heraus, eine
        # Kuendigung ohne Enddatum bleibt also sichtbar; geprueft in
        # `test_kuendigung_ohne_ende_bleibt_im_filter_gekuendigt`.
        qs = qs.filter(status=status_filter).exclude(ende__lt=heute)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(mieter__vorname__icontains=q) | Q(mieter__nachname__icontains=q)
                       | Q(mieter__firmen_name__icontains=q)
                       | Q(einheit__bezeichnung__icontains=q)
                       | Q(einheit__liegenschaft__strasse__icontains=q))

    sort = sortierung_waehlen(request, VERTRAG_SORTEN, 'beginn')
    qs = sortieren(qs, VERTRAG_SORTEN, sort)

    if request.GET.get('export') == 'csv':
        return _vertraege_csv(qs.iterator(chunk_size=500))

    seite, query_ohne_seite = blaettern(request, qs)
    rows = [_vertrag_zeile(v) for v in seite.object_list]
    _saldo_und_mahnstufe(rows)

    # konzept-v8 (#akten): Zaehler am Reiter «Liegenschaften» — eine Zaehlung.
    lg_qs = Liegenschaft.objects.all()
    if aktive_lg:
        lg_qs = lg_qs.filter(id=aktive_lg.id)

    return render(request, 'fw/vertraege.html', {
        'liegenschaften_anzahl': lg_qs.count(),
        **basis, **_vermietung_pipeline('vertraege', basis['lg_query']), 'nav': 'vertraege', 'rows': rows,
        'seite': seite, 'query_ohne_seite': query_ohne_seite, 'treffer': seite.paginator.count,
        'status_filter': status_filter, 'q': q,
        'status_chips': [(k, label, query_mit(request, status=k))
                         for k, label in [('', _('Alle'))] + [(k, VERTRAG_PILL[k][0])
                                                              for k in VERTRAG_FILTER]],
        # «Aktiv» nach der Anzeige-Regel (`Mietvertrag.anzeige_status`): aktiv
        # und Ende nicht vorbei. Gezählt über die Abfrage, nicht die Seite.
        'aktiv_count': qs.filter(status='aktiv').exclude(ende__lt=heute).count(),
        'sort': sort, 'sorten': [(k, x.label) for k, x in VERTRAG_SORTEN.items()],
        'verdeckt': verdeckte_felder(request, 'q', 'sort'),
        'csv_url': query_mit(request, export='csv'),
        'suche_aufheben_url': query_mit(request, q=None),
    })


def _saldo_und_mahnstufe(rows):
    """Saldo (offene Posten) und hoechste Mahnstufe je Zeile — konzept-v8 #akten.

    Nur lesend, drei Abfragen fuer die ganze Seite, nicht je Zeile. Der Saldo
    ist dieselbe Zahl wie «Saldo» auf der Vertragsakte: Summe von
    `max(0, Betrag − verbuchte Zahlungen)` ueber die offenen und teilbezahlten
    Rechnungen. Die Mahnstufe steht nur bei offenem Saldo — eine alte Mahnung
    zu einer laengst bezahlten Rechnung ist kein Befund.
    """
    from django.db.models import Max

    from finance.models import Mahnung

    vids = [r['v'].id for r in rows]
    for r in rows:
        r['saldo'] = Decimal('0.00')
        r['mahnstufe'] = 0
    if not vids:
        return
    rechnungen = list(DebitorenRechnung.objects
                      .filter(vertrag_id__in=vids, status__in=('offen', 'teilbezahlt'))
                      .values_list('id', 'vertrag_id', 'betrag'))
    bezahlt = dict(Zahlungseingang.objects
                   .filter(debitoren_rechnung_id__in=[x[0] for x in rechnungen], status='verbucht')
                   .values('debitoren_rechnung_id').annotate(s=Sum('betrag'))
                   .values_list('debitoren_rechnung_id', 's')) if rechnungen else {}
    saldo = defaultdict(lambda: Decimal('0.00'))
    for r_id, v_id, betrag in rechnungen:
        saldo[v_id] += max(Decimal('0.00'), (betrag or Decimal('0')) - (bezahlt.get(r_id) or Decimal('0')))
    stufen = dict(Mahnung.objects.filter(vertrag_id__in=vids).values('vertrag_id')
                  .annotate(m=Max('stufe')).values_list('vertrag_id', 'm'))
    for r in rows:
        r['saldo'] = saldo.get(r['v'].id, Decimal('0.00'))
        r['mahnstufe'] = (stufen.get(r['v'].id) or 0) if r['saldo'] else 0


def _vertrag_zeile(v):
    anzeige = v.anzeige_status
    label, pill_cls = VERTRAG_PILL.get(anzeige, (anzeige, 'fw-flaeche2 fw-mutet'))
    return {
        'v': v,
        'brutto': (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0')),
        'status_label': label,
        'pill_cls': pill_cls,
        'chip': VERTRAG_CHIP.get(anzeige, 'mut'),
    }


#: Wählbare Sortierungen der Vertragsliste. Die Datenbank sortiert; `id` als
#: letzter Schlüssel, damit die Reihenfolge über Seiten hinweg stabil bleibt —
#: sonst kann ein Vertrag mit gleichem Beginn auf zwei Seiten stehen.
VERTRAG_SORTEN = {
    'beginn': Sortierung(gettext_lazy('Neueste zuerst'), None,
                         felder=('-beginn', '-id')),
    'ende': Sortierung(gettext_lazy('Nächstes Ende'), None,
                       felder=(F('ende').asc(nulls_last=True), 'id')),
    'mieter': Sortierung(gettext_lazy('Mieter'), None,
                         felder=('mieter__nachname', 'mieter__firmen_name', 'mieter__vorname', 'id')),
    'objekt': Sortierung(gettext_lazy('Objekt'), None,
                         felder=('einheit__liegenschaft__strasse', 'einheit__bezeichnung', 'id')),
    'miete': Sortierung(gettext_lazy('Höchste Miete'), None,
                        felder=((Coalesce('netto_mietzins', Decimal('0'))
                                 + Coalesce('nebenkosten', Decimal('0'))).desc(), 'id')),
}


def _vertraege_csv(vertraege):
    heute = timezone.localdate()
    zeilen = (_vertrag_zeile(v) for v in vertraege)
    return csv_antwort(
        f'Mietverhaeltnisse_{heute:%Y-%m-%d}.csv',
        [_('Mieter'), _('Liegenschaft'), _('Objekt'), _('Beginn'), _('Ende'),
         _('Netto (CHF)'), _('Nebenkosten (CHF)'), _('Brutto (CHF)'), _('Status')],
        ([z['v'].mieter.display_name, z['v'].einheit.liegenschaft.strasse,
          z['v'].einheit.bezeichnung, z['v'].beginn, z['v'].ende,
          z['v'].netto_mietzins, z['v'].nebenkosten, z['brutto'], z['status_label']]
         for z in zeilen))
