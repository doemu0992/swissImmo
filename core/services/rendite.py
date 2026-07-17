"""Rendite- und Gebäude-Kennzahlen je Liegenschaft.

Kernidee: der Verkehrswert (Marktwert) ist der massgebliche Renditenenner,
ersatzweise die Anlagekosten. Der Versicherungswert (Neuwert Gebäudehülle)
taugt NICHT als Nenner und wird hier nur als expliziter Notbehelf mit klarer
Kennzeichnung verwendet.
"""
from decimal import Decimal
from datetime import date


def _monatsanfang(d):
    return date(d.year, d.month, 1)


def _plus_monate(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def soll_jahresmiete(lg, stichtag=None):
    """Soll-Jahresmietzins (netto + brutto) der Liegenschaft aus den zum Stichtag
    aktiven Verträgen. Netto = Mietertrag ohne Nebenkosten (relevanter Ertrag
    für die Rendite); Brutto = inkl. NK."""
    from rentals.models import Mietvertrag
    stichtag = stichtag or date.today()
    netto = Decimal('0.00')
    brutto = Decimal('0.00')
    vertraege = (Mietvertrag.objects.filter(einheit__liegenschaft=lg, status='aktiv')
                 .select_related('einheit'))
    for v in vertraege:
        n = v.effektiver_netto_mietzins(stichtag) or Decimal('0.00')
        nk = v.effektive_nebenkosten(stichtag) or Decimal('0.00')
        netto += n
        brutto += n + nk
    return netto * 12, brutto * 12


def betriebsaufwand_12m(lg, bis=None):
    """Effektiver Betriebsaufwand der letzten 12 Monate (Aufwand-Buchungen der
    Liegenschaft, ohne Storni). Grundlage für die Nettorendite."""
    from finance.models import Buchung
    bis = bis or date.today()
    von = _plus_monate(_monatsanfang(bis), -11)
    total = Decimal('0.00')
    qs = (Buchung.objects.filter(liegenschaft=lg, ist_storno=False,
                                 datum__gte=von, datum__lte=bis,
                                 soll_konto__typ='aufwand')
          .select_related('soll_konto'))
    for b in qs:
        total += b.betrag or Decimal('0.00')
    return total


def liegenschaft_rendite(lg, stichtag=None):
    """Rendite-Kennzahlen einer Liegenschaft.

    Rückgabe-Dict:
      wert, wert_quelle ('verkehrswert'|'anlagekosten'|'versicherungswert'|None),
      jahres_netto, jahres_brutto, betriebsaufwand,
      bruttorendite (%, Netto-Soll / Wert), nettorendite (%, (Netto-Soll − Aufwand)/Wert).
    Renditen sind None, wenn kein valider Wert hinterlegt ist.
    """
    stichtag = stichtag or date.today()
    jahres_netto, jahres_brutto = soll_jahresmiete(lg, stichtag)
    aufwand = betriebsaufwand_12m(lg, stichtag)

    wert, quelle = None, None
    if lg.verkehrswert and lg.verkehrswert > 0:
        wert, quelle = lg.verkehrswert, 'verkehrswert'
    elif lg.anlagekosten and lg.anlagekosten > 0:
        wert, quelle = lg.anlagekosten, 'anlagekosten'

    bruttorendite = nettorendite = None
    if wert:
        bruttorendite = float(jahres_netto) / float(wert) * 100
        nettorendite = float(jahres_netto - aufwand) / float(wert) * 100
    return {
        'wert': wert, 'wert_quelle': quelle,
        'jahres_netto': jahres_netto, 'jahres_brutto': jahres_brutto,
        'betriebsaufwand': aufwand,
        'bruttorendite': bruttorendite, 'nettorendite': nettorendite,
    }


def betriebsrechnung(lg, jahr=None):
    """Gebäudescharfe Betriebsrechnung (Ertrag − Aufwand) eines Kalenderjahres
    aus den Buchungen der Liegenschaft. Gibt Ertrags-/Aufwandszeilen je Konto +
    Totale + Nettoergebnis zurück."""
    from finance.models import Buchung
    jahr = jahr or date.today().year
    von, bis = date(jahr, 1, 1), date(jahr, 12, 31)
    ertrag_rows, aufwand_rows = {}, {}
    ertrag_total = Decimal('0.00')
    aufwand_total = Decimal('0.00')
    qs = (Buchung.objects.filter(liegenschaft=lg, ist_storno=False,
                                 datum__gte=von, datum__lte=bis)
          .select_related('soll_konto', 'haben_konto'))
    for b in qs:
        betrag = b.betrag or Decimal('0.00')
        soll_aufwand = bool(b.soll_konto and b.soll_konto.typ == 'aufwand')
        haben_ertrag = bool(b.haben_konto and b.haben_konto.typ == 'ertrag')
        # Reine Erfolgsumbuchung (Aufwand↔Ertrag) darf NICHT beide Totale aufblähen
        # (das Nettoergebnis bliebe zwar korrekt, die Summen wären überzeichnet) —
        # solche Umbuchungen überspringen; sie laufen normal über ein Bilanzkonto.
        if soll_aufwand and haben_ertrag:
            continue
        # Ertrag: Haben-Konto ist Ertrag. Aufwand: Soll-Konto ist Aufwand.
        if haben_ertrag:
            k = b.haben_konto
            row = ertrag_rows.setdefault(k.nummer, {'nummer': k.nummer, 'name': k.bezeichnung, 'betrag': Decimal('0.00')})
            row['betrag'] += betrag
            ertrag_total += betrag
        if soll_aufwand:
            k = b.soll_konto
            row = aufwand_rows.setdefault(k.nummer, {'nummer': k.nummer, 'name': k.bezeichnung, 'betrag': Decimal('0.00')})
            row['betrag'] += betrag
            aufwand_total += betrag
    return {
        'jahr': jahr,
        'ertrag': sorted(ertrag_rows.values(), key=lambda r: r['nummer']),
        'aufwand': sorted(aufwand_rows.values(), key=lambda r: r['nummer']),
        'ertrag_total': ertrag_total,
        'aufwand_total': aufwand_total,
        'ergebnis': ertrag_total - aufwand_total,
    }


def leerstand_zeitverlauf(lg=None, monate=12, bis=None):
    """Monatlicher Leerstands-Zeitverlauf: je Monat die Zahl leerer Einheiten
    und die Leerquote (%). Basis: Leerstand-Zeiträume (beginn/ende) gegen die
    Gesamtzahl Einheiten. Optional auf eine Liegenschaft gefiltert."""
    from portfolio.models import Einheit
    from rentals.models import Leerstand
    bis = bis or date.today()
    start = _plus_monate(_monatsanfang(bis), -(monate - 1))

    einheiten = Einheit.objects.all()
    if lg is not None:
        einheiten = einheiten.filter(liegenschaft=lg)
    total_einheiten = einheiten.count()
    einheit_ids = set(einheiten.values_list('id', flat=True))

    leerstaende = Leerstand.objects.all()
    if lg is not None:
        leerstaende = leerstaende.filter(einheit__liegenschaft=lg)
    leerstaende = list(leerstaende.select_related('einheit'))

    reihe = []
    monat = start
    while monat <= _monatsanfang(bis):
        monat_ende = _plus_monate(monat, 1)
        leer_ids = set()
        for ls in leerstaende:
            if ls.einheit_id not in einheit_ids:
                continue
            b = ls.beginn
            e = ls.ende or bis
            # Überschneidung des Leerstands mit diesem Monat?
            if b < monat_ende and e >= monat:
                leer_ids.add(ls.einheit_id)
        leer = len(leer_ids)
        quote = (leer / total_einheiten * 100) if total_einheiten else 0.0
        reihe.append({'monat': monat, 'leer': leer,
                      'total': total_einheiten, 'quote': round(quote, 1)})
        monat = monat_ende
    return reihe
