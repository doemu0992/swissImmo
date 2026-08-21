"""Ersatz- & Budgetplanung: projiziert je Element das erwartete Ersatzjahr
(Einbaujahr + Lebensdauer aus der paritätischen Lebensdauertabelle) und
aggregiert die zu erwartenden Ersatzkosten (Neuwert) pro Jahr — Grundlage für
die Erneuerungsfonds-/Budgetplanung des Eigentümers.

SEIT 4b.20 STEHEN GERÄTE MIT IN DIESER RECHNUNG

Bis dahin las diese Datei ausschliesslich `Ausstattung` — ausgerechnet die
Geräte, die teuren Posten (Heizung, Boiler, Lift), blieben aussen vor. Sie
standen stattdessen auf einer eigenen Seite `/neu/assets/`, die nur auflistete
und nichts rechnete.

**Geräte tragen NICHTS zum Jahresbudget bei, und das ist Absicht.**
`portfolio.Geraet` hat kein `neuwert`-Feld. Einen Preis zu schätzen wäre die
schlechtere Antwort als eine ehrliche Lücke: Ein erfundener Boilerpreis
wanderte über den PDF-Report direkt in die Fondsplanung des Eigentümers und
sähe dort aus wie eine Zahl. Die Geräte erscheinen in den Zeilen und den
Zählern; im Budget erscheinen sie nicht, und `budget_ohne_neuwert` sagt, wie
viele es sind.

DIE KATEGORIENBRÜCKE

Die Lebensdauertabelle ist nach Raumbuch-Kategorien benannt («Heizung /
Wärmeerzeuger»), die Geräteliste nach Gerätekategorien («Heizung»).
`GERAET_ZU_LEBENSDAUER` übersetzt, wo die Namen auseinandergehen. Wo es keinen
Eintrag gibt — Aufzug, Wärmepumpe, Photovoltaik —, bleibt es bei «Keine
Datenbasis». Eine Frist zu behaupten, für die es keine Grundlage gibt, ist
schlechter als keine Frist.
"""
from decimal import Decimal

#: Gerätekategorie → Kategorie der Lebensdauertabelle. Nur die Fälle, in denen
#: die Namen auseinandergehen; `Lebensdauer.fuer_kategorie` trifft identische
#: Namen (Waschmaschine, Geschirrspüler, Backofen, Rauchmelder) von selbst.
#:
#: Was hier FEHLT, fehlt bewusst: Für Aufzug, Wärmepumpe, Klimaanlage,
#: Solaranlage und Photovoltaik führt der Raumkatalog keine Lebensdauer. Diese
#: Geräte erscheinen als «Keine Datenbasis» — nicht mit einer geratenen Zahl.
GERAET_ZU_LEBENSDAUER = {
    'heizung': 'Heizung / Wärmeerzeuger',
    'boiler / wassererwärmer': 'Boiler / Warmwasserspeicher',
    'lüftung': 'Lüftungsanlage',
    'tumbler': 'Tumbler / Trockner',
    'kochfeld': 'Kochherd / Glaskeramik',
    'kühlschrank': 'Kühlschrank / Gefrierteil',
    'dampfabzug': 'Dampfabzug / Ventilator',
}


def geraet_lebensdauer(geraet):
    """Erwartete Lebensdauer eines Geräts in Jahren — oder None.

    None heisst «keine Grundlage», nicht «null Jahre». Der Aufrufer muss den
    Unterschied machen; `_geraet_zeile` tut das über den Status «unbekannt».
    """
    from portfolio.models import Lebensdauer
    kat = (geraet.kategorie or '').strip()
    if not kat:
        return None
    return (Lebensdauer.fuer_kategorie(kat)
            or Lebensdauer.fuer_kategorie(GERAET_ZU_LEBENSDAUER.get(kat.lower(), '')))


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
            'a': a, 'g': None, 'art': 'raumbuch',
            'rest': a.rest_jahre(heute), 'status': st,
            'status_label': label, 'status_cls': cls, 'ersatz_jahr': ejahr,
            'neuwert': neuwert,
            'lebenszyklus': a.lebenszyklus_kosten(),
            'reparaturkosten': a.reparatur_kosten_total(),
            'schaden_anzahl': a.schaeden.count(),
            'standort': f"{a.einheit.liegenschaft.strasse} · {a.einheit.bezeichnung}",
            # Einheitliche Anzeigefelder, damit die Vorlage nicht zwischen
            # Ausstattung und Geraet verzweigen muss.
            'bezeichnung': a.kategorie,
            'detail': a.raum,
            'lebensdauer': a.effektive_lebensdauer(),
            'einbau': a.einbau_datum,
            'garantie_bis': a.garantie_bis,
            'ziel_url': f'/neu/objekte/{a.einheit_id}/#obj-raumbuch',
        }
        rows.append(row)
        # Budget nur innerhalb des Horizonts und nur mit bekanntem Neuwert
        if ejahr and ejahr <= aktuelles_jahr + horizont_jahre and neuwert > 0:
            b = budget.setdefault(ejahr, {'summe': Decimal('0.00'), 'anzahl': 0})
            b['summe'] += neuwert
            b['anzahl'] += 1

    # --- Geraete (4b.20) -----------------------------------------------
    # Ohne Neuwert und deshalb ohne Budgetbeitrag; siehe Dateikopf.
    ohne_neuwert = 0
    for g in _geraete(aktive_lg):
        zeile = _geraet_zeile(g, heute, aktuelles_jahr)
        n[zeile['status']] += 1
        rows.append(zeile)
        ohne_neuwert += 1

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
        'n_geraete': ohne_neuwert,
        # Wie viele Zeilen im Budget FEHLEN, weil kein Neuwert erfasst ist.
        # Die Zahl gehoert auf die Seite: Ein Budget, dem die Heizung fehlt,
        # sieht sonst aus wie ein vollstaendiges.
        'budget_ohne_neuwert': ohne_neuwert,
        'aktuelles_jahr': aktuelles_jahr, 'horizont_jahre': horizont_jahre,
    }


def _geraete(aktive_lg):
    from portfolio.models import Geraet
    from django.db.models import Q
    qs = Geraet.objects.select_related('liegenschaft', 'einheit__liegenschaft')
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(einheit__liegenschaft=aktive_lg))
    return qs


def _geraet_zeile(g, heute, aktuelles_jahr):
    """Ein Geraet in derselben Zeilenform wie ein Raumbuch-Element.

    `Geraet` hat weder `rest_jahre()` noch `ersatz_status()` — beides rechnet
    hier, aus `installations_datum` und der Lebensdauer aus der
    Kategorienbruecke. Ohne eines von beiden lautet der Status «unbekannt»
    und nicht etwa «faellig»: Ein Geraet ohne Einbaudatum ist nicht alt,
    sondern unbekannt.
    """
    ld = geraet_lebensdauer(g)
    rest = None
    status = 'unbekannt'
    ejahr = None
    if ld and g.installations_datum:
        alter = (heute - g.installations_datum).days / 365.25
        rest = round(float(ld) - alter, 1)
        status = 'faellig' if rest <= 0 else ('bald' if rest <= 2 else 'ok')
        ejahr = max(g.installations_datum.year + int(ld), aktuelles_jahr)
    label, cls = STATUS_META[status]
    lg = g.liegenschaft or (g.einheit.liegenschaft if g.einheit_id else None)
    wo = lg.strasse if lg else '—'
    if g.einheit_id:
        wo = f'{wo} · {g.einheit.bezeichnung}'
    ziel = (f'/neu/objekte/{g.einheit_id}/?tab=geraete' if g.einheit_id
            else (f'/neu/liegenschaften/{lg.id}/?tab=technik' if lg else '#'))
    return {
        'a': None, 'g': g, 'art': 'geraet',
        'rest': rest, 'status': status,
        'status_label': label, 'status_cls': cls, 'ersatz_jahr': ejahr,
        'neuwert': Decimal('0.00'),
        'lebenszyklus': Decimal('0.00'),
        'reparaturkosten': Decimal('0.00'),
        'schaden_anzahl': 0,
        'standort': wo,
        'bezeichnung': g.kategorie or g.sonstiges_bezeichnung or 'Gerät',
        'detail': ' '.join(x for x in (g.marke, g.modell) if x) or g.standort,
        'lebensdauer': ld,
        'einbau': g.installations_datum,
        'garantie_bis': g.garantie_bis,
        'ziel_url': ziel,
    }


def fonds_deckung(aktive_lg, budget_total, horizont_jahre):
    """Vergleicht das projizierte Ersatzbudget mit dem Erneuerungsfonds:
    aktueller Bestand, jährliche Einlage, Deckungsgrad und empfohlene
    Jahresrückstellung. Aggregiert über alle Fonds, wenn keine Liegenschaft
    gewählt ist. None, wenn gar kein Fonds existiert."""
    from finance.models import Erneuerungsfonds
    qs = Erneuerungsfonds.objects.all()
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    fonds = list(qs)
    if not fonds:
        return None
    bestand = sum((f.bestand or Decimal('0.00') for f in fonds), Decimal('0.00'))
    einlage = sum((f.jaehrliche_einlage or Decimal('0.00') for f in fonds), Decimal('0.00'))
    horizont = horizont_jahre or 1
    empfohlen = (budget_total / horizont).quantize(Decimal('0.01')) if budget_total else Decimal('0.00')
    # Projektion: Bestand + Einlagen über den Horizont vs. Ersatzbudget
    projiziert = bestand + einlage * horizont
    saldo = projiziert - budget_total   # >= 0 → gedeckt
    deckungsgrad = None
    if budget_total > 0:
        deckungsgrad = int((projiziert / budget_total * 100).to_integral_value())
    return {
        'anzahl_fonds': len(fonds),
        'bestand': bestand,
        'einlage': einlage,
        'empfohlen': empfohlen,
        'mehrbedarf': max(Decimal('0.00'), empfohlen - einlage),
        'projiziert': projiziert,
        'saldo': saldo,
        'gedeckt': saldo >= 0,
        'deckungsgrad': deckungsgrad,
    }
