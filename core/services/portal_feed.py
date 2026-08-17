"""Vermarktungs-Objekt-Feed für Immobilien-Portale (Homegate, ImmoScout24/SMG,
Flatfox etc.). Liefert alle zur Ausschreibung markierten Objekte in einem
neutralen, stabilen Schema, das Portale/Middleware konsumieren können.

Der Feed ist read-only und token-gesichert (Verwaltung.portal_feed_token)."""
from decimal import Decimal


def _num(d):
    if d is None:
        return None
    return float(d)


def feed_objekte(base_url='', organisation=None):
    """Gibt die Liste der ausgeschriebenen Objekte als serialisierbare dicts.

    base_url (optional) wird den Exposé-Links vorangestellt (absolute URLs).

    `organisation` schraenkt auf eine Verwaltung ein — Pflicht fuer den
    oeffentlichen Feed. Ohne sie lieferte der Feed die Ausschreibungen ALLER
    Verwaltungen an jeden, der irgendeinen gueltigen Token hatte.
    """
    from portfolio.models import Einheit
    TYP = {'whg': 'apartment', 'stwe': 'apartment', 'gew': 'commercial',
           'pp': 'parking', 'gar': 'parking', 'bas': 'storage'}

    objekte = []
    # `alle_organisationen`: Diese Funktion bedient den OEFFENTLICHEN Feed —
    # kein Login, also kein Mandantenkontext. Die Grenze zieht stattdessen der
    # Parameter `organisation` ein paar Zeilen tiefer, und der oeffentliche
    # Aufrufer gibt ihn zwingend mit (er leitet ihn aus dem Token ab).
    qs = (Einheit.alle_organisationen.filter(zur_ausschreibung=True)
          .select_related('liegenschaft').prefetch_related('fotos')
          .order_by('liegenschaft__strasse', 'bezeichnung'))
    if organisation is not None:
        qs = qs.filter(liegenschaft__organisation=organisation)
    for e in qs:
        lg = e.liegenschaft
        netto = e.nettomiete_aktuell or Decimal('0')
        nk = e.nebenkosten_aktuell or Decimal('0')
        bilder = []
        for f in e.fotos.all():
            try:
                url = f.bild.url
            except Exception:
                continue
            bilder.append((base_url.rstrip('/') + url) if base_url and url.startswith('/') else url)
        objekte.append({
            'id': e.id,
            'referenz': f"OBJ-{e.id}",
            'bezeichnung': e.bezeichnung,
            'typ': TYP.get(e.typ, 'other'),
            'typ_label': e.get_typ_display(),
            'adresse': {
                'strasse': lg.strasse if lg else '',
                'plz': lg.plz if lg else '',
                'ort': lg.ort if lg else '',
            },
            'zimmer': _num(e.zimmer),
            'flaeche_m2': _num(e.flaeche_m2),
            'etage': e.etage or '',
            'miete': {
                'netto': _num(netto), 'nebenkosten': _num(nk),
                'brutto': _num(netto + nk), 'waehrung': 'CHF',
            },
            'verfuegbar_ab': e.verfuegbar_ab.isoformat() if e.verfuegbar_ab else 'sofort',
            'beschreibung': e.ausschreibung_notiz or '',
            'bilder': bilder,
            'expose_url': (base_url.rstrip('/') + f"/neu/vermarktung/{e.id}/expose/") if base_url else f"/neu/vermarktung/{e.id}/expose/",
        })
    return objekte


CSV_HEADER = ['referenz', 'typ', 'bezeichnung', 'strasse', 'plz', 'ort',
              'zimmer', 'flaeche_m2', 'etage', 'netto', 'nebenkosten', 'brutto',
              'verfuegbar_ab', 'beschreibung']


def feed_csv_rows(objekte):
    """Wandelt die Feed-Objekte in CSV-Zeilen (Header + Datenzeilen)."""
    rows = [CSV_HEADER]
    for o in objekte:
        a, mi = o['adresse'], o['miete']
        rows.append([
            o['referenz'], o['typ_label'], o['bezeichnung'],
            a['strasse'], a['plz'], a['ort'],
            o['zimmer'] if o['zimmer'] is not None else '',
            o['flaeche_m2'] if o['flaeche_m2'] is not None else '',
            o['etage'],
            mi['netto'] if mi['netto'] is not None else '',
            mi['nebenkosten'] if mi['nebenkosten'] is not None else '',
            mi['brutto'] if mi['brutto'] is not None else '',
            o['verfuegbar_ab'],
            (o['beschreibung'] or '').replace('\n', ' ').replace('\r', ' '),
        ])
    return rows
