"""Die Lage des Bestands — vier Zahlen, die Mandate, und was abweicht.

WARUM ES DIESE DATEI GIBT

Die Startseite zeigte bis hierher vier Kacheln aus der Vorgängerzeit:
Mietertrag-Diagramm, Portfolio-Donut, Belegung, Leerstandsliste. Alle vier
zeigen den **Bestand**. Ein Donut, der seit zwei Jahren gleich aussieht, ist
Dekoration — er kostet Platz und Aufmerksamkeit und sagt nichts.

Der Unterschied, um den es hier geht, ist der **Vergleich**. «Leerstand 4.8 %»
ist eine Zahl. «Leerstand steigt zum dritten Monat in Folge, alle drei Objekte
in derselben Liegenschaft» ist eine Information. Den Vormonatsvergleich, den
das braucht, gab es im ganzen Code nirgends — null Treffer.

DER GEFÄHRLICHSTE TEIL IST `abweichungen()`

Zu empfindlich eingestellt wird der Abschnitt zur Dauerbeschwerde und niemand
liest ihn nach drei Wochen. Zu träge und er meldet nie etwas. Die Schwellen
stehen deshalb oben als benannte Konstanten, einzeln begründet, und es sind
bewusst **wenige**. Wer eine ergänzt, soll die Begründung dazuschreiben müssen.

ZUR ANZAHL DER ABFRAGEN

Diese Datei läuft bei **jedem** Aufruf der Startseite. Zwei Stellen waren im
ersten Entwurf je Datensatz statt je Menge gebaut und kosteten zusammen rund
tausend Abfragen; sie sind unten ausdrücklich als solche gekennzeichnet, damit
sie nicht versehentlich zurückgebaut werden. Der Wächter dazu steht in
`faelle/test_lage.py::AbfragezahlTests`.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

log = logging.getLogger(__name__)

#: Unter diesem Zahlungseingang meldet sich die Lage. 95 % ist keine
#: Naturkonstante, sondern eine Vorgabe — bei einem gut geführten Bestand
#: liegt der Eingang am Monatsende darüber.
SCHWELLE_EINGANG = Decimal('95')

#: Ab dieser Leerstandsquote wird gemeldet. Darunter ist Fluktuation normal.
SCHWELLE_LEERSTAND = Decimal('3')

#: So viele Monate in Folge muss der Leerstand steigen, damit es ein Trend ist
#: und kein Zufall. Zwei wären Rauschen.
TREND_MONATE = 3

#: So viele Verträge werden auf einen Senkungsanspruch geprüft. Die Grenze ist
#: da, weil die Prüfung je Vertrag rechnet (Referenzzins gegen die wirksame
#: Basis) und nicht in einer Abfrage zu haben ist.
SENKUNG_STICHPROBE = 400


def _monatsgrenzen(stichtag):
    """(erster Tag des Monats, erster Tag des Vormonats, letzter Tag Vormonat)."""
    erster = stichtag.replace(day=1)
    letzter_vor = erster - timedelta(days=1)
    return erster, letzter_vor.replace(day=1), letzter_vor


def _eingangsquote(von, bis, aktive_lg=None):
    """Anteil der im Zeitraum fälligen Sollstellung, der bezahlt ist.

    Rückgabe: (quote, soll, offen, anzahl_offen) — oder (None, …) wenn im
    Zeitraum nichts fällig war. `None` ist wichtig: Eine Quote von 0 % und
    «gar keine Sollstellung» sind völlig verschiedene Aussagen, und wer sie
    verwechselt, meldet im Januar einen Totalausfall.
    """
    from finance.models import DebitorenRechnung

    q = DebitorenRechnung.objects.filter(faellig_am__gte=von, faellig_am__lte=bis)
    if aktive_lg:
        q = q.filter(Q(liegenschaft=aktive_lg)
                     | Q(vertrag__einheit__liegenschaft=aktive_lg))
    q = q.exclude(status__in=('storniert', 'abgeschrieben'))

    # EINE Abfrage für beide Summen und die Anzahl statt drei. Auf der
    # Startseite läuft diese Funktion zweimal (Monat und Vormonat), im
    # Abweichungsblock nochmals zweimal.
    zahlen = q.aggregate(
        soll=Sum('betrag'),
        offen=Sum('betrag', filter=Q(status__in=('offen', 'teilbezahlt'))),
        anzahl_offen=Count('pk', filter=Q(status__in=('offen', 'teilbezahlt'))))
    soll = zahlen['soll'] or Decimal('0')
    offen = zahlen['offen'] or Decimal('0')
    if not soll:
        return None, Decimal('0'), Decimal('0'), 0
    quote = (soll - offen) / soll * 100
    return quote.quantize(Decimal('0.1')), soll, offen, zahlen['anzahl_offen'] or 0


def _leerstandsquote(stichtag, aktive_lg=None):
    """Anteil der Einheiten ohne laufenden Vertrag, in Prozent."""
    from portfolio.models import Einheit
    from rentals.models import Mietvertrag

    einheiten = Einheit.objects.all()
    vertraege = Mietvertrag.objects.filter(status='aktiv')
    if aktive_lg:
        einheiten = einheiten.filter(liegenschaft=aktive_lg)
        vertraege = vertraege.filter(einheit__liegenschaft=aktive_lg)
    gesamt = einheiten.count()
    if not gesamt:
        return None, 0, 0
    belegt = set(vertraege.filter(beginn__lte=stichtag)
                 .filter(Q(ende__isnull=True) | Q(ende__gte=stichtag))
                 .values_list('einheit_id', flat=True))
    leer = gesamt - len(belegt)
    quote = (Decimal(leer) / Decimal(gesamt) * 100).quantize(Decimal('0.1'))
    return quote, leer, gesamt


def streifen(stichtag=None, aktive_lg=None):
    """Die vier Zahlen im Kopf der Startseite, je mit Vormonatsvergleich."""
    stichtag = stichtag or timezone.localdate()
    erster, vor_erster, vor_letzter = _monatsgrenzen(stichtag)

    quote, _soll, offen, anzahl_offen = _eingangsquote(erster, stichtag, aktive_lg)
    vor_quote, _s, _o, _a = _eingangsquote(vor_erster, vor_letzter, aktive_lg)

    leer_quote, leer_anzahl, _gesamt = _leerstandsquote(stichtag, aktive_lg)
    vor_leer, _la, _lg = _leerstandsquote(vor_letzter, aktive_lg)

    faelle_offen = liegen = 0
    try:
        from faelle.models import Fall
        # ABGEBROCHEN gehoert genauso wenig zu den offenen wie ABGESCHLOSSEN.
        # Nur nach ABGESCHLOSSEN zu filtern zaehlte abgebrochene Faelle mit —
        # nachgesehen in faelle/models.py, nicht angenommen.
        faelle_offen = Fall.objects.exclude(
            status__in=(Fall.ABGESCHLOSSEN, Fall.ABGEBROCHEN)).count()
        liegen = Fall.objects.liegengeblieben().count()
    except Exception:
        log.exception('Lage: Fallzahlen nicht ermittelbar')

    return [
        {'schluessel': 'eingang', 'label': f'Eingang {stichtag.strftime("%B")}',
         'wert': f'{quote} %' if quote is not None else '—',
         'stufe': 'crit' if quote is not None and quote < SCHWELLE_EINGANG else '',
         'delta': (quote - vor_quote) if (quote is not None and vor_quote is not None) else None,
         'delta_gut_wenn': 'hoch',
         'fuss': 'gegen Vormonat' if vor_quote is not None else 'kein Vormonatswert'},
        {'schluessel': 'ausstaende', 'label': 'Ausstände',
         'wert': f'CHF {offen:,.0f}'.replace(',', "'"),
         'stufe': 'crit' if offen else '',
         'delta': None,
         'fuss': f'{anzahl_offen} Position{"en" if anzahl_offen != 1 else ""}'},
        {'schluessel': 'leerstand', 'label': 'Leerstand',
         'wert': f'{leer_quote} %' if leer_quote is not None else '—',
         'stufe': ('warn' if leer_quote is not None
                   and leer_quote >= SCHWELLE_LEERSTAND else ''),
         'delta': (leer_quote - vor_leer) if (leer_quote is not None
                                              and vor_leer is not None) else None,
         'delta_gut_wenn': 'runter',
         'fuss': f'{leer_anzahl} Objekt{"e" if leer_anzahl != 1 else ""}'},
        {'schluessel': 'faelle', 'label': 'Offene Fälle',
         'wert': str(faelle_offen), 'stufe': 'warn' if liegen else '',
         'delta': None,
         'fuss': (f'{liegen} liegengeblieben' if liegen else 'alle in Bewegung')},
    ]


def mandate(stichtag=None):
    """Eine Zeile je Mandat, sortiert nach Auffälligkeit — nicht nach Grösse.

    Die Sortierung ist die eigentliche Aussage: Wer die Liste von oben liest,
    sieht zuerst, wo etwas klemmt. Nach Objektzahl sortiert stünde das grösste
    Mandat oben, auch wenn dort alles ruhig ist.

    IN EINER ABFRAGE, NICHT IN DREI JE MANDAT. Der erste Entwurf zählte je
    Eigentümer Einheiten, belegte Einheiten und offene Forderungen einzeln —
    bei fünfzig Mandaten 150 Abfragen, auf der meistbesuchten Seite der
    Anwendung. `annotate` erledigt dasselbe in einer.
    """
    from crm.models import Eigentuemer

    stichtag = stichtag or timezone.localdate()
    laeuft = (Q(liegenschaften__einheiten__vertraege__status='aktiv')
              & Q(liegenschaften__einheiten__vertraege__beginn__lte=stichtag)
              & (Q(liegenschaften__einheiten__vertraege__ende__isnull=True)
                 | Q(liegenschaften__einheiten__vertraege__ende__gte=stichtag)))

    zeilen = []
    for e in (Eigentuemer.objects
              .annotate(
                  n_objekte=Count('liegenschaften__einheiten', distinct=True),
                  n_belegt=Count('liegenschaften__einheiten', distinct=True,
                                 filter=laeuft),
                  summe_offen=Sum(
                      'liegenschaften__einheiten__vertraege__debitoren_rechnungen__betrag',
                      filter=Q(liegenschaften__einheiten__vertraege__debitoren_rechnungen__status__in=(
                          'offen', 'teilbezahlt'))))[:50]):
        gesamt = e.n_objekte or 0
        if not gesamt:
            continue
        belegt = e.n_belegt or 0
        leer = gesamt - belegt
        offen = e.summe_offen or Decimal('0')
        zeilen.append({
            'mandat': e, 'objekte': gesamt, 'leer': leer,
            'belegung': (Decimal(belegt) / Decimal(gesamt) * 100
                         ).quantize(Decimal('0.1')),
            'offen': offen,
            'stufe': 'crit' if offen else ('warn' if leer else 'good'),
            'befund': ('ohne Befund' if not offen and not leer else ''),
        })
    rang = {'crit': 0, 'warn': 1, 'good': 2}
    zeilen.sort(key=lambda z: (rang[z['stufe']], -z['objekte']))
    return zeilen


def _senkungsansprueche():
    """Verträge, deren Referenzzins unter die wirksame Basis gefallen ist.

    `Mietvertrag.mietzinspotenzial` rechnet je Vertrag und ist nicht in eine
    Abfrage zu bringen: Es liest die Organisation (Zinsstand) und die jüngste
    wirksame Anpassung. Ohne `select_related` und `prefetch_related` sind das
    zwei zusätzliche Abfragen **je Vertrag** — bei der Stichprobe von 400 also
    achthundert, bei jedem Aufruf der Startseite.
    """
    from rentals.models import Mietvertrag

    vertraege = (Mietvertrag.objects.filter(status='aktiv')
                 .select_related('organisation')
                 .prefetch_related('anpassungen')[:SENKUNG_STICHPROBE])
    return [v for v in vertraege if v.mietzinspotenzial == 'decrease']


def abweichungen(stichtag=None, aktive_lg=None):
    """Nur was abweicht. Ruhige Kennzahlen erscheinen hier ausdrücklich nicht.

    Jeder Eintrag nennt eine Zahl, den Vergleichswert und **wo** es herkommt —
    «92.4 statt 93.6, und zwar wegen zweier Ausfälle» führt zu einer Handlung,
    «Zahlungseingang gesunken» führt zu einer Rückfrage.
    """
    stichtag = stichtag or timezone.localdate()
    erster, vor_erster, vor_letzter = _monatsgrenzen(stichtag)
    befunde = []

    quote, _s, offen, anzahl = _eingangsquote(erster, stichtag, aktive_lg)
    vor_quote, _s2, _o2, _a2 = _eingangsquote(vor_erster, vor_letzter, aktive_lg)
    if quote is not None and quote < SCHWELLE_EINGANG:
        vergleich = (f' statt {vor_quote} % im Vormonat'
                     if vor_quote is not None else '')
        befunde.append({
            'stufe': 'crit', 'titel': f'Zahlungseingang unter {SCHWELLE_EINGANG} %',
            'text': (f'{quote} %{vergleich}. Offen sind CHF {offen:,.2f} '
                     f'in {anzahl} Position{"en" if anzahl != 1 else ""}.'
                     ).replace(',', "'"),
            'ziel': '/neu/debitoren/', 'knopf': 'Debitoren'})

    leer_quote, leer_anzahl, _g = _leerstandsquote(stichtag, aktive_lg)
    if leer_quote is not None and leer_quote >= SCHWELLE_LEERSTAND:
        verlauf = []
        tag = stichtag
        for _ in range(TREND_MONATE):
            q, _a, _b = _leerstandsquote(tag, aktive_lg)
            verlauf.append(q)
            tag = tag.replace(day=1) - timedelta(days=1)
        steigend = all(a is not None and b is not None and a > b
                       for a, b in zip(verlauf, verlauf[1:]))
        reihe = ' → '.join(f'{q} %' for q in reversed(verlauf) if q is not None)
        befunde.append({
            'stufe': 'crit' if steigend else 'warn',
            'titel': ('Leerstand steigt den dritten Monat in Folge' if steigend
                      else f'Leerstand über {SCHWELLE_LEERSTAND} %'),
            'text': (f'{reihe}. Betroffen sind {leer_anzahl} '
                     f'Objekt{"e" if leer_anzahl != 1 else ""}.'),
            'ziel': '/neu/vermarktung/', 'knopf': 'Vermarktung'})

    try:
        senkung = _senkungsansprueche()
        if senkung:
            befunde.append({
                'stufe': 'warn',
                'titel': f'Senkungsanspruch bei {len(senkung)} Mietverhältnis'
                         f'{"sen" if len(senkung) != 1 else ""}',
                'text': ('Der Referenzzinssatz ist seit der Festsetzung gesunken. '
                         'Geltend gemacht hat ihn bisher niemand — die Ansprüche '
                         'bestehen aber.'),
                'ziel': '/neu/mietzins/', 'knopf': 'Liste öffnen'})
    except Exception:
        log.exception('Lage: Senkungsansprüche nicht ermittelbar')

    return befunde


def lage(stichtag=None, aktive_lg=None):
    """Alles für die Startseite in einem Aufruf."""
    stichtag = stichtag or timezone.localdate()
    befunde = abweichungen(stichtag, aktive_lg)
    return {
        'lg_streifen': streifen(stichtag, aktive_lg),
        'lg_mandate': mandate(stichtag),
        'lg_abweichungen': befunde,
        'lg_abweichungen_anzahl': len(befunde),
    }
