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
from datetime import date, datetime, time, timedelta
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


def _einheit(delta, singular, plural):
    """Die Einheit hinter dem Vormonatspfeil, in der richtigen Zahlform.

    «▲ 1 Fälle» steht sonst auf der Startseite, und ±1 ist der haeufigste Wert
    ueberhaupt. Zwei Zeilen weiter unten wird die Fusszeile schon so gebildet
    (`Position{"en" if … != 1}`); das hier ist dieselbe Regel, nur auf dem
    Betrag der Veraenderung statt auf dem Bestand.
    """
    return singular if abs(delta or 0) == 1 else plural


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

    quote, soll, offen, anzahl_offen = _eingangsquote(erster, stichtag, aktive_lg)
    # Die vierte Stelle ist die ANZAHL offener Positionen im Vormonat. Sie wurde
    # bis E2.58 verworfen; ein zweiter Aufruf mit denselben Argumenten waere eine
    # zusaetzliche Abfrage auf der meistbesuchten Seite gewesen, fuer eine Zahl,
    # die hier schon vorliegt.
    vor_quote, _s, _o, vor_anzahl = _eingangsquote(vor_erster, vor_letzter, aktive_lg)

    leer_quote, leer_anzahl, _gesamt = _leerstandsquote(stichtag, aktive_lg)
    vor_leer, _la, _lg = _leerstandsquote(vor_letzter, aktive_lg)

    # DIE ZWEITEN ANGABEN DER FUSSZEILEN (v7).
    #
    # «11 Positionen, 3 in Mahnstufe 2» und «10 Objekte, 4 ohne Ausschreibung».
    # Beide lesen sich als TEILMENGE der ersten Zahl — und muessen deshalb
    # dieselbe Menge einschraenken, nicht eine andere zaehlen.
    #
    # DER ERSTE ENTWURF TAT DAS NICHT, GEMESSEN:
    #
    #   `Mahnung.objects.filter(stufe__gte=2)` zaehlte JEDE je ausgestellte
    #   Mahnung — auch zu laengst bezahlten Rechnungen und aus beliebigen
    #   Monaten. Eine im Januar 2025 gemahnte, inzwischen bezahlte Rechnung
    #   ergab «1 Position, 1 in Mahnstufe 2», obwohl die eine offene Position
    #   nie gemahnt wurde. Zwei fremde Mengen, als Teilmenge geschrieben.
    #
    #   `exclude(vertraege__status='aktiv')` ist zudem eine ANDERE
    #   Leerstandsdefinition als die des Streifens: `_leerstandsquote` prueft
    #   den Vertrag am Stichtag (`beginn <= tag <= ende`), nicht nur seinen
    #   Status. Eine Einheit mit einem aktiven, aber erst naechsten Monat
    #   beginnenden Vertrag zaehlt dort leer und hier belegt.
    #
    # UND BEIDE MISSACHTETEN DEN LIEGENSCHAFTSFILTER, waehrend jede andere
    # Zahl im Streifen ihn beachtet — mit gesetztem Filter waere die erste
    # Zahl eingeschraenkt gewesen und die zweite nicht.
    gemahnt = ohne_aussch = 0
    try:
        from finance.models import DebitorenRechnung

        # Dieselbe Fensterung und derselbe Status wie `anzahl_offen` oben.
        gem = DebitorenRechnung.objects.filter(
            faellig_am__gte=erster, faellig_am__lte=stichtag,
            status__in=('offen', 'teilbezahlt'))
        if aktive_lg:
            gem = gem.filter(Q(liegenschaft=aktive_lg)
                             | Q(vertrag__einheit__liegenschaft=aktive_lg))
        gemahnt = gem.filter(mahnungen__stufe__gte=2).distinct().count()
    except Exception:
        log.exception('Mahnstufen fuer die Kachel nicht ladbar')
    try:
        from portfolio.models import Einheit
        from rentals.models import Mietvertrag

        # Dieselbe Leerstandsdefinition wie `_leerstandsquote`.
        belegt = (Mietvertrag.objects.filter(status='aktiv', beginn__lte=stichtag)
                  .filter(Q(ende__isnull=True) | Q(ende__gte=stichtag)))
        eh = Einheit.objects.filter(zur_ausschreibung=False)
        if aktive_lg:
            eh = eh.filter(liegenschaft=aktive_lg)
            belegt = belegt.filter(einheit__liegenschaft=aktive_lg)
        ohne_aussch = eh.exclude(id__in=belegt.values('einheit_id')).count()
    except Exception:
        log.exception('Ausschreibungsstand fuer die Kachel nicht ladbar')

    faelle_offen = liegen = 0
    vor_faelle = None
    try:
        from faelle.models import Fall
        # ABGEBROCHEN gehoert genauso wenig zu den offenen wie ABGESCHLOSSEN.
        # Nur nach ABGESCHLOSSEN zu filtern zaehlte abgebrochene Faelle mit —
        # nachgesehen in faelle/models.py, nicht angenommen.
        faelle_offen = Fall.objects.exclude(
            status__in=(Fall.ABGESCHLOSSEN, Fall.ABGEBROCHEN)).count()
        liegen = Fall.objects.liegengeblieben().count()
        # WARUM HIER KEINE «KEIN VORMONATSWERT»-SCHRANKE STEHT
        #
        # Bei den Ausstaenden gibt es eine: War im Vormonat NICHTS faellig, ist
        # `vor_quote` `None` und der Vergleich entfaellt. (Nicht `vor_anzahl` —
        # die ist dann `0` und von einem echten Nullstand nicht zu
        # unterscheiden; siehe die Begruendung bei der Kachel unten.) Eine Null
        # waere dort eine ERFUNDENE Vergleichsbasis.
        #
        # Bei den Faellen ist ein Nullstand eine GEMESSENE Zahl. Am ersten Tag
        # gab es null offene Faelle — das ist wahr, nicht unbekannt. Wer am 15.
        # drei anlegt, hat drei mehr als am 31. des Vormonats, und «▲ 3 Faelle»
        # beschreibt genau das.
        #
        # Der Unterschied ist derselbe wie zwischen `Geraet.neuwert = None`
        # («nicht erfasst») und `= 0` («kostet nichts»): eine fehlende Messung
        # ist etwas anderes als ein gemessener Nullwert.
        #
        # Bei leerer Installation steht ohnehin nichts: `delta` ist 0, und die
        # Vorlage blendet ein Delta von 0 aus (`{% if k.delta %}`). Gemessen,
        # nicht gemeint — `ErsterTagTests` haelt beides fest.
        #
        # DER STAND VOR EINEM MONAT — gerechnet, nicht gespeichert.
        #
        # Offen war damals, was bis dahin eroeffnet und noch nicht abgeschlossen
        # war. `abgeschlossen_am` traegt das Datum; fehlt es, ist der Fall bis
        # heute offen und zaehlt mit.
        #
        # DIE GRENZE IST EIN ZEITPUNKT MIT ZEITZONE, KEIN DATUM.
        #
        # `eroeffnet_am` und `abgeschlossen_am` sind `DateTimeField`, und
        # `USE_TZ` ist an. Gegen `vor_letzter` (ein `date`) zu filtern hat zwei
        # Folgen, beide gemessen: Django warnt bei JEDEM Aufruf der Startseite
        # («received a naive datetime … while time zone support is active»),
        # und die Grenze liegt auf MITTERNACHT des letzten Vormonatstags — der
        # ganze 31. faellt heraus. Ein am 31. um 09:00 eroeffneter Fall galt
        # damit als «damals noch nicht da», ein am 31. abgeschlossener als
        # «damals noch offen». Zwei Fehler in entgegengesetzte Richtungen.
        #
        # `erster` (00:00 des laufenden Monats) ist dieselbe Grenze, nur richtig
        # ausgedrueckt: alles davor liegt im Vormonat oder frueher.
        grenze = datetime.combine(erster, time.min)
        if timezone.is_naive(grenze):          # `USE_TZ = True` — immer der Fall
            grenze = timezone.make_aware(grenze)
        # ABGEBROCHENE ZAEHLEN AUCH DAMALS NICHT MIT — sonst vergleicht die
        # Kachel zwei verschieden gerechnete Zahlen, und ein abgebrochener Fall
        # sieht aus wie ein erledigter. `abgebrochen_am` gibt es nicht; ein
        # heute abgebrochener Fall wird deshalb auch rueckwirkend nicht
        # mitgezaehlt. Das ist die Naeherung, die zur Zeile oben passt.
        vor_faelle = Fall.objects.exclude(status=Fall.ABGEBROCHEN).filter(
            eroeffnet_am__lt=grenze).exclude(
            abgeschlossen_am__isnull=False,
            abgeschlossen_am__lt=grenze).count()
    except Exception:
        log.exception('Lage: Fallzahlen nicht ermittelbar')

    return [
        # DER BETRAG IST DER WERT, DIE QUOTE DIE EINORDNUNG (v7).
        #
        # Der Prototyp zeigt «CHF 184'320», darunter «92 % des Solls» und den
        # Vormonat. Wir zeigten nur die Quote.
        #
        # DER BETRAG IST DIE FRAGE, DIE MAN MORGENS HAT: Wie viel ist
        # eingegangen? Die Quote sagt, ob das gut ist — sie beantwortet die
        # zweite Frage, nicht die erste. Und «92 %» allein sagt nicht, ob es um
        # zweitausend oder zweihunderttausend Franken geht.
        #
        # DER PFEIL BLEIBT DIE QUOTE, und deshalb steht die Einheit dabei.
        # Ohne sie stuende «▲ 3» ueber einem Frankenbetrag und laese sich wie
        # drei Franken mehr. `_einheit` liefert dazu die richtige Zahlform —
        # «▲ 1 Prozentpunkt», nicht «1 Prozentpunkte»; dieselbe Regel wie bei
        # den drei Kacheln daneben seit E2.58.
        {'schluessel': 'eingang', 'label': f'Zahlungseingang {stichtag.strftime("%B")}',
         'wert': (f'CHF {(soll - offen):,.0f}'.replace(',', "'")
                  if quote is not None else '—'),
         'stufe': 'crit' if quote is not None and quote < SCHWELLE_EINGANG else '',
         'delta': (quote - vor_quote) if (quote is not None and vor_quote is not None) else None,
         'delta_gut_wenn': 'hoch',
         'delta_einheit': _einheit((quote - vor_quote)
                                   if (quote is not None and vor_quote is not None) else 0,
                                   'Prozentpunkt', 'Prozentpunkte'),
         # Die Teile erst sammeln, dann verbinden — sonst beginnt die Zeile mit
         # «· kein Vormonatswert», wenn die Quote fehlt.
         'fuss': ' · '.join(t for t in (
             f'{quote} % des Solls' if quote is not None else '',
             f'Vormonat {vor_quote} %' if vor_quote is not None
             else 'kein Vormonatswert') if t)},
        # AUSSTAENDE: DER VERGLEICH ZAEHLT POSITIONEN, NICHT FRANKEN.
        #
        # Konzept v7 verlangt «Kennzahlen nur mit Vergleich». Bis E2.58 stand
        # hier `delta: None` — CHF 23'140 ohne Bezugspunkt.
        #
        # Verglichen wird die ANZAHL, nicht der Betrag: Eine einzelne grosse
        # Rechnung laesst den Franken-Wert springen, ohne dass sich an der Lage
        # etwas geaendert haette. Zwei Positionen mehr heisst zwei Mieter mehr,
        # die nicht bezahlt haben — das ist die Aussage.
        #
        # DIE SCHRANKE IST `vor_quote`, NICHT `vor_anzahl`.
        #
        # `_eingangsquote` gibt die Anzahl als `0` zurueck, wenn im Vormonat gar
        # nichts faellig war — `0` und «kein Vormonat» sind dort nicht zu
        # unterscheiden. Nur die QUOTE ist in diesem Fall `None`. Auf `vor_anzahl
        # is not None` zu pruefen waere immer wahr gewesen und haette auf einer
        # frischen Installation «▲ 3 Positionen» gezeigt: einen Anstieg gegen
        # einen Monat, den es nicht gab.
        {'schluessel': 'ausstaende', 'label': 'Ausstände',
         'wert': f'CHF {offen:,.0f}'.replace(',', "'"),
         'stufe': 'crit' if offen else '',
         'delta': (anzahl_offen - vor_anzahl) if vor_quote is not None else None,
         'delta_gut_wenn': 'runter',
         'delta_einheit': _einheit(anzahl_offen - vor_anzahl, 'Position', 'Positionen'),
         # DIE FUSSZEILE TRAEGT ZWEI ANGABEN (v7).
         #
         # Der Prototyp zeigt «11 Positionen, 3 in Mahnstufe 2». Die zweite
         # sagt, wie ERNST der Ausstand ist: Elf offene Posten sind Alltag,
         # drei davon in der zweiten Mahnung nicht. Ohne sie ist die Zahl
         # ein Betrag ohne Dringlichkeit.
         'fuss': (f'{anzahl_offen} Position{"en" if anzahl_offen != 1 else ""}'
                  + (f', {gemahnt} in Mahnstufe 2' if gemahnt else '')),},
        {'schluessel': 'leerstand', 'label': 'Leerstand',
         'wert': f'{leer_quote} %' if leer_quote is not None else '—',
         'stufe': ('warn' if leer_quote is not None
                   and leer_quote >= SCHWELLE_LEERSTAND else ''),
         'delta': (leer_quote - vor_leer) if (leer_quote is not None
                                              and vor_leer is not None) else None,
         'delta_gut_wenn': 'runter',
         # «10 Objekte, 4 ohne Ausschreibung» — die zweite Angabe sagt, was
         # man TUN kann. Leerstand allein ist eine Zahl; Leerstand ohne
         # Ausschreibung ist eine Unterlassung.
         'fuss': (f'{leer_anzahl} Objekt{"e" if leer_anzahl != 1 else ""}'
                  + (f', {ohne_aussch} ohne Ausschreibung' if ohne_aussch else '')),},
        # OFFENE FAELLE: gegen den Stand vor einem Monat.
        #
        # `eroeffnet_am` und `abgeschlossen_am` stehen im Modell; daraus laesst
        # sich der damalige Stand rechnen, ohne ihn zu speichern. Ein wachsender
        # Vorrat ist die Aussage, nicht die absolute Zahl — 27 offene Faelle sind
        # bei einer grossen Verwaltung wenig und bei einer kleinen viel.
        {'schluessel': 'faelle', 'label': 'Offene Fälle',
         'wert': str(faelle_offen), 'stufe': 'warn' if liegen else '',
         'delta': (faelle_offen - vor_faelle) if vor_faelle is not None else None,
         'delta_gut_wenn': 'runter',
         'delta_einheit': _einheit((faelle_offen - vor_faelle)
                                   if vor_faelle is not None else 0, 'Fall', 'Fälle'),
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
