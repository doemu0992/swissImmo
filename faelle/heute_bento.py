"""Die Bento-Reihe der Startseite (Ember-Redesign, mockups/immoswiss-ember.html).

Sechs Karten über dem Arbeitsvorrat — jede beantwortet eine Frage, die eine
Verwaltung am Morgen stellt, und führt mit einem Klick dorthin, wo sie handelt:

    zahlung    Wie zuverlässig zahlen die Mieter? Zahlungsquote des Jahres
               (Halbkreis) und durchschnittlicher Verzug der letzten 90 Tage.
    rueckstand Was ist überfällig? Anzahl und Summe offener Rechnungen nach
               Fälligkeit → Mahnwesen.
    post       Was hat zuletzt jemand geschrieben? Neuester Eingang im Zulauf,
               sonst die neueste Mieternachricht an einem Ticket.
    orte       Wo liegt der Bestand? Objekte je Ort.
    einnahmen  Mieteingang der letzten sieben Monate (verbuchte Zahlungen).
    woche      Termine, Fristen, Ticket-Zielzeiten und Auszüge dieser Woche
               (dieselbe Quelle wie der Monatskalender).

Nichts wird erfunden: Fehlt eine Grösse (keine Rechnung fällig, keine Zahlung),
steht `None`, und die Vorlage zeigt «–» oder einen Leerzustand. Alle Abfragen
laufen durch die Mandantenmanager.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.dateformat import format as datum_format
from django.utils.translation import gettext as _

NULL = Decimal('0.00')


def _liegenschaften(aktive_lg):
    from portfolio.models import Liegenschaft
    return [aktive_lg] if aktive_lg else list(Liegenschaft.objects.all())


def _lg_q(aktive_lg, feld_lg='liegenschaft', feld_vertrag='vertrag__einheit__liegenschaft'):
    if not aktive_lg:
        return Q()
    return Q(**{feld_lg: aktive_lg}) | Q(**{feld_vertrag: aktive_lg})


def zahlung(heute, aktive_lg=None):
    """Zahlungsquote (Jahr) und Ø Verzug in Tagen (Zahlungen der letzten 90 Tage)."""
    from core.services.portfolio_kennzahlen import zahlungsquote
    from finance.models import Zahlungseingang
    quote = zahlungsquote(_liegenschaften(aktive_lg), heute.year, heute)
    zq = (Zahlungseingang.objects.filter(status='verbucht', debitoren_rechnung__isnull=False,
                                         datum_eingang__gte=heute - timedelta(days=90))
          .filter(_lg_q(aktive_lg, 'debitoren_rechnung__liegenschaft', 'debitoren_rechnung__vertrag__einheit__liegenschaft'))
          .values_list('datum_eingang', 'debitoren_rechnung__faellig_am', 'debitoren_rechnung__datum'))
    verzug = [max(0, (eingang - (faellig or datum)).days) for eingang, faellig, datum in zq if (faellig or datum)]
    dauer = round(sum(verzug) / len(verzug), 1) if verzug else None
    if dauer is None:
        stufe = ''
    elif dauer <= 3:
        stufe = 'good'
    elif dauer <= 10:
        stufe = 'warn'
    else:
        stufe = 'crit'
    return {'quote': quote, 'dauer': dauer, 'anzahl': len(verzug), 'stufe': stufe,
            'stufe_klasse': f'fw-{stufe}' if stufe else '',
            'stufe_text': {'good': _('pünktlich'), 'warn': _('verzögert'), 'crit': _('spät')}.get(stufe, ''),
            # Halbkreis: 0–100 % als Anteil von 180°
            'bogen': max(0.0, min(100.0, quote or 0.0))}


def rueckstand(heute, aktive_lg=None):
    from finance.models import DebitorenRechnung
    qs = (DebitorenRechnung.objects.filter(status__in=('offen', 'teilbezahlt'))
          .filter(_lg_q(aktive_lg))
          .filter(Q(faellig_am__lt=heute) | Q(faellig_am__isnull=True, datum__lt=heute)))
    a = qs.aggregate(n=Count('id'), s=Sum('betrag'))
    return {'n': a['n'] or 0, 'summe': a['s'] or NULL}


def post(aktive_lg=None):
    """Die neueste Nachricht von aussen: Zulauf zuerst, sonst Ticket-Antwort eines Mieters."""
    from faelle.zulauf_models import Eingang
    from tickets.models import TicketNachricht
    e = Eingang.objects.filter(status=Eingang.OFFEN).order_by('-eingegangen_am').first()
    if e:
        return {'titel': e.betreff or _('Ohne Betreff'), 'text': (e.text or '')[:140],
                'wer': e.absender or e.absender_email or e.get_quelle_display(),
                'wann': e.eingegangen_am, 'url': '/neu/zulauf/', 'art': _('Zulauf')}
    nq = (TicketNachricht.objects.filter(is_intern=False, is_von_verwaltung=False)
          .exclude(typ__in=('system', 'email', 'antwort_senden', 'handwerker_mail'))
          .select_related('ticket'))
    if aktive_lg:
        nq = nq.filter(ticket__liegenschaft=aktive_lg)
    n = nq.order_by('-erstellt_am').first()
    if n:
        return {'titel': n.ticket.titel, 'text': (n.nachricht or '')[:140], 'wer': n.absender_name,
                'wann': n.erstellt_am, 'url': f'/neu/schaeden/{n.ticket_id}/',
                'art': _('Ticket #%(nr)s') % {'nr': n.ticket_id}}
    return None


def orte(aktive_lg=None):
    """Objekte je Ort, grösster zuerst — höchstens drei Zeilen."""
    from portfolio.models import Einheit
    qs = Einheit.objects.all()
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    reihen = list(qs.values('liegenschaft__ort').annotate(n=Count('id')).order_by('-n', 'liegenschaft__ort')[:3])
    gesamt = qs.count()
    return {'reihen': [{'ort': r['liegenschaft__ort'] or '—', 'n': r['n']} for r in reihen],
            'erster': reihen[0] if reihen else None, 'gesamt': gesamt}


def einnahmen(heute, aktive_lg=None, monate=7):
    """Verbuchte Zahlungseingänge je Monat; die Balkenhöhe in % des grössten Monats."""
    from finance.models import Zahlungseingang
    start = date(heute.year, heute.month, 1)
    for _i in range(monate - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    qs = (Zahlungseingang.objects.filter(status='verbucht', datum_eingang__gte=start, datum_eingang__lte=heute))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    je = {(r['m'].year, r['m'].month): r['s'] or NULL
          for r in qs.annotate(m=TruncMonth('datum_eingang')).values('m').annotate(s=Sum('betrag'))}
    reihe, m = [], start
    while len(reihe) < monate:
        reihe.append({'monat': m, 'label': datum_format(m, 'M'), 'summe': je.get((m.year, m.month), NULL)})
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    groesst = max((r['summe'] for r in reihe), default=NULL)
    # Achse in runden Schritten (5 Linien), damit die Beschriftung lesbar bleibt
    oben = _runde_achse(groesst)
    for i, r in enumerate(reihe):
        r['hoehe'] = float(r['summe'] / oben * 100) if oben else 0.0
        r['i'] = i
        r['kurz'] = _kurz(r['summe'])
    return {'reihe': reihe, 'achse': [_kurz(oben * k / 5) for k in range(5, -1, -1)] if oben else [],
            'hat_daten': groesst > 0, 'aktiv': len(reihe) - 1}


def _runde_achse(wert):
    if not wert or wert <= 0:
        return Decimal('0')
    w = float(wert)
    import math
    stufe = 10 ** math.floor(math.log10(w))
    for f in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if w <= f * stufe:
            return Decimal(str(f * stufe))
    return Decimal(str(10 * stufe))


def _kurz(betrag):
    b = float(betrag or 0)
    if b >= 1_000_000:
        return f'{b / 1_000_000:.1f}M'.replace('.0M', 'M')
    if b >= 1000:
        return f'{round(b / 1000):.0f}k'
    return f'{b:.0f}'


def woche(heute, aktive_lg=None):
    """Wochenraster: drei Zeilen (ganztägig, Vormittag, Nachmittag) × sieben Tage."""
    from core.views.fw.kalender import ereignisse
    montag = heute - timedelta(days=heute.weekday())
    sonntag = montag + timedelta(days=6)
    alle = ereignisse(montag, sonntag, aktive_lg)
    zeilen = [(_('Ganztags'), lambda e: not e['zeit']),
              (_('Vormittag'), lambda e: e['zeit'] and e['zeit'] < '12:00'),
              (_('Nachmittag'), lambda e: e['zeit'] and e['zeit'] >= '12:00')]
    tage = [{'datum': montag + timedelta(days=i), 'label': datum_format(montag + timedelta(days=i), 'D j'),
             'heute': montag + timedelta(days=i) == heute} for i in range(7)]
    raster = []
    for name, passt in zeilen:
        slots = []
        for t in tage:
            hier = [e for e in alle if e['tag'] == t['datum'] and passt(e)]
            slots.append({'ereignisse': hier, 'anzahl': len(hier),
                          'heiss': any(e['ton'] == 'crit' for e in hier) or (t['heute'] and bool(hier)),
                          'url': hier[0]['url'] if len(hier) == 1 else f"/neu/termine/kalender/?tag={t['datum']:%Y-%m-%d}"})
        raster.append({'name': name, 'slots': slots})
    return {'tage': tage, 'raster': raster, 'anzahl': len(alle), 'montag': montag, 'sonntag': sonntag}


def tickets_offen(aktive_lg=None):
    from tickets.models import SchadenMeldung
    qs = SchadenMeldung.objects.exclude(status='erledigt')
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    return qs.count()


def bento(heute=None, aktive_lg=None):
    heute = heute or timezone.localdate()
    return {'bento': {
        'tickets_offen': tickets_offen(aktive_lg),
        'zahlung': zahlung(heute, aktive_lg),
        'rueckstand': rueckstand(heute, aktive_lg),
        'post': post(aktive_lg),
        'orte': orte(aktive_lg),
        'einnahmen': einnahmen(heute, aktive_lg),
        'woche': woche(heute, aktive_lg),
    }}
