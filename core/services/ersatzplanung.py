"""Ersatz- & Budgetplanung: projiziert je Raumbuch-Element das erwartete
Ersatzjahr (Einbaujahr + Lebensdauer aus der paritätischen Lebensdauertabelle)
und aggregiert die zu erwartenden Ersatzkosten (Neuwert) pro Jahr — Grundlage
für die Erneuerungsfonds-/Budgetplanung des Eigentümers.
"""
from decimal import Decimal


STATUS_META = {
    'faellig': ('Ersatz fällig', 'bg-rose-50 text-rose-700'),
    'bald': ('Ersatz bald', 'bg-amber-50 text-amber-700'),
    'ok': ('Im Nutzungszeitraum', 'bg-emerald-50 text-emerald-700'),
    'unbekannt': ('Keine Datenbasis', 'bg-slate-100 text-slate-400'),
}
ORDNUNG = {'faellig': 0, 'bald': 1, 'ok': 2, 'unbekannt': 3}


def _ersatz_jahr(a, aktuelles_jahr):
    """Erwartetes Ersatzjahr = Einbaujahr + Lebensdauer. Überfällige Elemente
    werden auf das laufende Jahr gelegt. None ohne Datenbasis."""
    ld = a.effektive_lebensdauer()
    if not (a.einbau_datum and ld):
        return None
    jahr = a.einbau_datum.year + int(ld)
    return max(jahr, aktuelles_jahr)


def berechne_ersatzplanung(aktive_lg=None, heute=None, horizont_jahre=10):
    """Baut Zeilen + Jahres-Budget. Gibt dict mit rows, jahres_budget, Kennzahlen."""
    from datetime import date
    from portfolio.models import Ausstattung
    heute = heute or date.today()
    aktuelles_jahr = heute.year

    qs = (Ausstattung.objects.select_related('einheit__liegenschaft')
          .prefetch_related('schaeden__handwerker_auftraege'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    rows = []
    n = {'faellig': 0, 'bald': 0, 'ok': 0, 'unbekannt': 0}
    budget = {}  # jahr -> {'summe': Decimal, 'anzahl': int}
    for a in qs:
        st = a.ersatz_status(heute)
        n[st] += 1
        label, cls = STATUS_META[st]
        ejahr = _ersatz_jahr(a, aktuelles_jahr)
        neuwert = a.neuwert or Decimal('0.00')
        row = {
            'a': a, 'rest': a.rest_jahre(heute), 'status': st,
            'status_label': label, 'status_cls': cls, 'ersatz_jahr': ejahr,
            'neuwert': neuwert,
            'lebenszyklus': a.lebenszyklus_kosten(),
            'reparaturkosten': a.reparatur_kosten_total(),
            'schaden_anzahl': a.schaeden.count(),
            'standort': f"{a.einheit.liegenschaft.strasse} · {a.einheit.bezeichnung}",
        }
        rows.append(row)
        # Budget nur innerhalb des Horizonts und nur mit bekanntem Neuwert
        if ejahr and ejahr <= aktuelles_jahr + horizont_jahre and neuwert > 0:
            b = budget.setdefault(ejahr, {'summe': Decimal('0.00'), 'anzahl': 0})
            b['summe'] += neuwert
            b['anzahl'] += 1

    rows.sort(key=lambda r: (ORDNUNG[r['status']], r['rest'] if r['rest'] is not None else 999))

    jahres_budget = [{'jahr': j, 'summe': budget[j]['summe'], 'anzahl': budget[j]['anzahl']}
                     for j in sorted(budget)]
    budget_total = sum((b['summe'] for b in budget.values()), Decimal('0.00'))

    return {
        'rows': rows,
        'jahres_budget': jahres_budget,
        'budget_total': budget_total,
        'n_faellig': n['faellig'], 'n_bald': n['bald'],
        'n_ok': n['ok'], 'n_unbekannt': n['unbekannt'],
        'aktuelles_jahr': aktuelles_jahr, 'horizont_jahre': horizont_jahre,
    }
