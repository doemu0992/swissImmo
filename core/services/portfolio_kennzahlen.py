"""Portfolio-Kennzahlen für Eigentümer und Investoren.

WAS DAS BEANTWORTET

«Wie läuft mein Bestand?» — Rendite, Ertrag, Leerstand, Cashflow. Die Rendite je
Liegenschaft rechnet `core.services.rendite` (Verkehrswert als Nenner, sonst
Anlagekosten); dieses Modul legt Liegenschaften zusammen und fügt den Cashflow
hinzu. Es erfindet keine Zahl: Fehlt ein Wert, bleibt die Kennzahl `None` und die
Seite sagt es.

CASHFLOW

Ertrag = Buchungen mit Haben-Konto vom Typ «Ertrag», Aufwand = Buchungen mit
Soll-Konto vom Typ «Aufwand», ohne Storno-Paare und ohne reine Erfolgsumbuchungen
(Aufwand ↔ Ertrag) — dieselbe Abgrenzung wie `rendite.betriebsrechnung`. Die
Summen rechnet die Datenbank (ein Aufruf je Reihe, nicht je Liegenschaft).

ZAHLUNGSQUOTE

Anteil der Sollstellung, der bei Fälligkeit bezahlt ist: bezahlte Rechnungen ÷
alle fälligen, nicht stornierten Rechnungen des laufenden Jahres. Teilzahlungen
zählen als offen — das ist die strengere Lesart.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth

from .rendite import _monatsanfang, _plus_monate, liegenschaft_renditen, soll_jahresmiete

NULL = Decimal('0.00')


def _monate(bis, anzahl):
    start = _plus_monate(_monatsanfang(bis), -(anzahl - 1))
    return [_plus_monate(start, i) for i in range(anzahl)]


def cashflow(liegenschaften, monate=12, bis=None):
    """Monatsreihe `[{monat, ertrag, aufwand, netto}]` für die gegebenen Liegenschaften."""
    from finance.models import Buchung
    bis = bis or date.today()
    reihe = _monate(bis, monate)
    ids = [lg.pk for lg in liegenschaften]
    basis = (Buchung.objects.filter(liegenschaft_id__in=ids, ist_storno=False, storniert_am__isnull=True,
                                    datum__gte=reihe[0], datum__lte=bis))

    def je_monat(qs):
        return {r['m']: r['s'] or NULL for r in
                qs.annotate(m=TruncMonth('datum')).values('m').annotate(s=Sum('betrag'))}

    ertrag = je_monat(basis.filter(haben_konto__typ='ertrag').exclude(soll_konto__typ='aufwand'))
    aufwand = je_monat(basis.filter(soll_konto__typ='aufwand').exclude(haben_konto__typ='ertrag'))

    def hole(d, monat):
        # TruncMonth liefert je nach Datenbank `date` oder `datetime`.
        return d.get(monat) or d.get(date(monat.year, monat.month, 1)) or next(
            (v for k, v in d.items() if (k.year, k.month) == (monat.year, monat.month)), NULL)

    out = []
    for m in reihe:
        e, a = hole(ertrag, m), hole(aufwand, m)
        out.append({'monat': m, 'ertrag': e, 'aufwand': a, 'netto': e - a})
    return out


def zahlungsquote(liegenschaften, jahr=None, heute=None):
    """Bezahlter Anteil der fälligen Sollstellung (in %) — `None` ohne fällige Rechnungen."""
    from finance.models import DebitorenRechnung
    heute = heute or date.today()
    jahr = jahr or heute.year
    ids = [lg.pk for lg in liegenschaften]
    qs = (DebitorenRechnung.objects.exclude(status='storniert')
          .filter(Q(liegenschaft_id__in=ids) | Q(vertrag__einheit__liegenschaft_id__in=ids))
          .filter(Q(faellig_am__year=jahr, faellig_am__lte=heute)
                  | Q(faellig_am__isnull=True, datum__year=jahr, datum__lte=heute)))
    a = qs.aggregate(gesamt=Sum('betrag'), bezahlt=Sum('betrag', filter=Q(status='bezahlt')),
                     n=Count('id'))
    if not a['n'] or not a['gesamt']:
        return None
    return float((a['bezahlt'] or NULL) / a['gesamt'] * 100)


def offene_posten(liegenschaften, heute=None):
    """(Summe, Anzahl) der offenen und überfälligen Debitoren dieser Liegenschaften."""
    from finance.models import DebitorenRechnung
    heute = heute or date.today()
    ids = [lg.pk for lg in liegenschaften]
    qs = (DebitorenRechnung.objects.filter(status__in=('offen', 'teilbezahlt'))
          .filter(Q(liegenschaft_id__in=ids) | Q(vertrag__einheit__liegenschaft_id__in=ids)))
    ueber = qs.filter(Q(faellig_am__lt=heute) | Q(faellig_am__isnull=True, datum__lt=heute))
    return (qs.aggregate(s=Sum('betrag'))['s'] or NULL, qs.count(), ueber.count())


def leerstand_je_liegenschaft(liegenschaften):
    """`{lg.pk: (leer, gesamt)}` mit zwei gruppierten Abfragen statt zwei je Liegenschaft."""
    from portfolio.models import Einheit
    from rentals.models import Mietvertrag
    ids = [lg.pk for lg in liegenschaften]
    gesamt = dict(Einheit.objects.filter(liegenschaft_id__in=ids)
                  .values_list('liegenschaft_id').annotate(n=Count('pk')))
    belegt = dict(Mietvertrag.objects.filter(status__in=('aktiv', 'gekuendigt'),
                                             einheit__liegenschaft_id__in=ids)
                  .values_list('einheit__liegenschaft_id')
                  .annotate(n=Count('einheit_id', distinct=True)))
    return {pk: (max(0, gesamt.get(pk, 0) - belegt.get(pk, 0)), gesamt.get(pk, 0)) for pk in ids}


def leerstand(liegenschaften):
    """(leere Objekte, alle Objekte): zählt Einheiten ohne aktiven Mietvertrag."""
    from portfolio.models import Einheit
    from rentals.models import Mietvertrag
    ids = [lg.pk for lg in liegenschaften]
    einheiten = Einheit.objects.filter(liegenschaft_id__in=ids)
    belegt = (Mietvertrag.objects.filter(status__in=('aktiv', 'gekuendigt'), einheit__in=einheiten)
              .values('einheit_id').distinct().count())
    gesamt = einheiten.count()
    return max(0, gesamt - belegt), gesamt


def uebersicht(liegenschaften, bis=None):
    """Alles für die Portfolio-Seite aus einer Hand.

    Rückgabe: dict mit `zeilen` (je Liegenschaft), Summen und den Kennzahlen.
    Die Renditen sind Durchschnitte über den Gesamtwert, nicht Mittel der
    Einzelrenditen — grosse Häuser zählen entsprechend mehr.
    """
    bis = bis or date.today()
    zeilen = []
    summe_netto = summe_aufwand = summe_wert = summe_wert_mit_rendite = NULL
    summe_netto_mit_wert = NULL
    renditen = liegenschaft_renditen(liegenschaften, bis)
    leerstaende = leerstand_je_liegenschaft(liegenschaften)
    for lg in liegenschaften:
        r = renditen[lg.pk]
        leer, gesamt = leerstaende[lg.pk]
        zeilen.append({
            'lg': lg, 'soll': r['jahres_netto'], 'aufwand': r['betriebsaufwand'],
            'wert': r['wert'], 'quelle': r['wert_quelle'],
            'brutto': r['bruttorendite'], 'netto': r['nettorendite'],
            'leer': leer, 'objekte': gesamt,
            'leer_quote': (leer / gesamt * 100) if gesamt else None,
        })
        summe_netto += r['jahres_netto']
        summe_aufwand += r['betriebsaufwand']
        if r['wert']:
            summe_wert += r['wert']
            summe_netto_mit_wert += r['jahres_netto']
            summe_wert_mit_rendite += r['jahres_netto'] - r['betriebsaufwand']
    leer = sum(l for l, _ in leerstaende.values())
    gesamt = sum(g for _, g in leerstaende.values())
    offen_summe, offen_n, ueberfaellig_n = offene_posten(liegenschaften, bis)
    return {
        'zeilen': zeilen,
        'soll_jahr': summe_netto, 'aufwand_jahr': summe_aufwand,
        'wert': summe_wert or None,
        'brutto': float(summe_netto_mit_wert / summe_wert * 100) if summe_wert else None,
        'netto': float(summe_wert_mit_rendite / summe_wert * 100) if summe_wert else None,
        'ohne_wert': sum(1 for z in zeilen if not z['wert']),
        'leer': leer, 'objekte': gesamt,
        'leer_quote': (leer / gesamt * 100) if gesamt else None,
        'zahlungsquote': zahlungsquote(liegenschaften, bis.year, bis),
        'offen_summe': offen_summe, 'offen_n': offen_n, 'ueberfaellig_n': ueberfaellig_n,
    }
