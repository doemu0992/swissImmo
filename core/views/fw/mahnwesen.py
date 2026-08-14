# core/views/fw/mahnwesen.py
#
# Erster aus core/views/fw/_rest.py herausgeloester Block (Etappe 1,
# siehe docs/ETAPPE-1-ZERLEGEN.md). Block 3 der 33: Mahnstufen aus
# ueberfaelligen Debitoren, dazu die Altersstruktur (Aging).
#
# Unveraendert uebernommen -- der Blockinhalt ab dem Kommentarbanner ist
# Zeile fuer Zeile derselbe. Neu sind ausschliesslich die Importe hier oben,
# die vorher aus dem Dateikopf der alten fw.py kamen.
#
# Erreichbar bleibt alles ueber `core.views.fw` -- das __init__.py des Pakets
# re-exportiert; swiss_immo/urls.py und die Tests aendern sich nicht.

from decimal import Decimal

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from core.auth import rolle_erforderlich, TEAM_ROLLEN
from crm.models import Mieter
from finance.models import DebitorenRechnung

from ._basis import _global_filter


# ============================================================
# ETAPPE D: MAHNWESEN (Mahnstufen aus überfälligen Debitoren)
# ============================================================

# Mahnstufen-Konfiguration liegt jetzt PRO MANDANT (crm.Eigentuemer.mahn_konfig) —
# EINE Quelle der Wahrheit in core.services.mahnstufen. MAHN_STUFEN = Standard-
# Legende (ohne Eigentuemer); die View berechnet die effektive Legende pro Eigentuemer.
from core.services.mahnstufen import (  # noqa: E402
    mahnstufen_config as _mahnstufen_config,
    stufe_fuer_tage as _stufe_fuer_tage,
    eigentuemer_von_rechnung as _eigentuemer_von_rechnung,
)
MAHN_STUFEN = _mahnstufen_config(None)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mahnwesen(request):
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (DebitorenRechnung.objects
          .filter(status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft__eigentuemer',
                          'liegenschaft__eigentuemer')
          .prefetch_related('zahlungseingaenge'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    stufe_filter = request.GET.get('stufe', '')
    # Effektive Mahnstufen-Legende: die des gefilterten Eigentümer, sonst Standard.
    legende = _mahnstufen_config(getattr(aktive_lg, 'eigentuemer', None) if aktive_lg else None)

    rows = []
    total = Decimal('0.00')
    counts = {1: 0, 2: 0, 3: 0}
    summe = {1: Decimal('0.00'), 2: Decimal('0.00'), 3: Decimal('0.00')}
    for r in qs:
        faellig = r.faellig_am or r.datum
        if not faellig or faellig >= heute:
            continue
        tage = (heute - faellig).days
        stufe = _stufe_fuer_tage(tage, _eigentuemer_von_rechnung(r))
        if not stufe:
            continue  # unter der ersten aktiven Stufe: noch kein Mahnfall
        offen = r.offener_betrag
        if offen <= 0:
            continue
        counts[stufe['stufe']] += 1
        summe[stufe['stufe']] += offen
        total += offen
        if stufe_filter and str(stufe['stufe']) != stufe_filter:
            continue
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        monat = faellig.strftime('%m/%Y')
        rows.append({
            'r': r, 'stufe': stufe, 'tage': tage, 'offen': offen,
            'mieter': r.vertrag.mieter.display_name if r.vertrag_id else '—',
            'objekt': (f"{lg.strasse}, {lg.ort}" if lg else '—'),
            'faellig': faellig,
            'vertrag_id': r.vertrag_id,
            'hat_email': bool(r.vertrag and r.vertrag.mieter.email),
            'mahn_url': (f"/vertrag/{r.vertrag_id}/mahnung/?betrag={offen}&monat={monat}"
                         if r.vertrag_id else None),
        })
    rows.sort(key=lambda x: (-x['stufe']['stufe'], -x['tage']))

    stufe_chips = [('', 'Alle Stufen')] + [(str(s['stufe']), s['label']) for s in legende]

    # Letzte erfasste Mahnung je Rechnung + Historie
    from finance.models import Mahnung
    letzte_je_rechnung = {}
    for mn in Mahnung.objects.all().order_by('datum'):
        letzte_je_rechnung[mn.debitoren_rechnung_id] = mn
    for row in rows:
        row['letzte_mahnung'] = letzte_je_rechnung.get(row['r'].id)

    historie_qs = (Mahnung.objects.select_related('vertrag__mieter', 'debitoren_rechnung')
                   .order_by('-datum', '-id'))
    if aktive_lg:
        historie_qs = historie_qs.filter(vertrag__einheit__liegenschaft=aktive_lg)
    historie = list(historie_qs[:30])

    context = {
        **basis, 'nav': 'mahnwesen', 'rows': rows,
        'stufe_filter': stufe_filter, 'stufe_chips': stufe_chips,
        'total': total,
        'mahnstufen': legende,
        'counts': counts, 'summe': summe,
        'anzahl_total': counts[1] + counts[2] + counts[3],
        'historie': historie,
    }
    return render(request, 'fw/mahnwesen.html', context)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_debitoren_aging(request):
    """Debitoren-Altersstruktur (OP-Aging): offene Forderungen nach
    Fälligkeitsalter (nicht fällig / 1–30 / 31–60 / 61–90 / >90 Tage),
    gruppiert je Mieter — die Risikosicht fürs Mahnwesen."""
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    # `offener_betrag` summiert die verbuchten Zahlungseingänge. Ohne Prefetch
    # ist das EINE Abfrage je offener Rechnung — gemessen 88 Posten → 93
    # Abfragen, 176 → 181. Ausgerechnet diese Seite öffnet man dann, wenn viel
    # offen ist. Der Prefetch-Zweig in `offener_betrag` greift nur, wenn die
    # Zahlungen hier auch vorgeladen werden; die übrigen Debitoren-Listen tun
    # das seit dem N+1-Hotfix, diese Seite war nicht nachgezogen worden.
    qs = (DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft')
          .prefetch_related('zahlungseingaenge'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    BUCKETS = ['nicht_faellig', 'd30', 'd60', 'd90', 'd90plus']

    def bucket(tage):
        if tage <= 0:
            return 'nicht_faellig'
        if tage <= 30:
            return 'd30'
        if tage <= 60:
            return 'd60'
        if tage <= 90:
            return 'd90'
        return 'd90plus'

    gruppen = {}
    total = {b: Decimal('0.00') for b in BUCKETS}
    total['summe'] = Decimal('0.00')
    for r in qs:
        offen = r.offener_betrag
        if offen <= 0:
            continue
        faellig = r.faellig_am or r.datum
        tage = (heute - faellig).days if faellig else 0
        b = bucket(tage)
        if r.vertrag_id and r.vertrag.mieter_id:
            key = ('m', r.vertrag.mieter_id)
            name = r.vertrag.mieter.display_name
            lg = r.vertrag.einheit.liegenschaft if r.vertrag.einheit_id else None
            objekt = (f"{lg.strasse}" if lg else '')
        else:
            key = ('t', (r.titel or 'Diverse'))
            name = r.titel or 'Diverse'
            objekt = r.liegenschaft.strasse if r.liegenschaft_id else ''
        g = gruppen.setdefault(key, {'name': name, 'objekt': objekt,
                                     **{b: Decimal('0.00') for b in BUCKETS},
                                     'summe': Decimal('0.00'), 'aeltester': 0})
        g[b] += offen
        g['summe'] += offen
        g['aeltester'] = max(g['aeltester'], tage)
        total[b] += offen
        total['summe'] += offen

    rows = sorted(gruppen.values(), key=lambda g: (-g['aeltester'], -float(g['summe'])))
    ueberfaellig_summe = total['d30'] + total['d60'] + total['d90'] + total['d90plus']

    return render(request, 'fw/debitoren_aging.html', {
        **basis, 'nav': 'mahnwesen', 'rows': rows, 'total': total,
        'ueberfaellig_summe': ueberfaellig_summe, 'anzahl': len(rows), 'heute': heute,
    })
