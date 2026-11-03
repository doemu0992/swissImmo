"""Eigentümerportal v2: Schäden, Aufträge, Freigaben und Verlauf — lesend, kuratiert.

WAS DER EIGENTÜMER SIEHT UND WAS NICHT

Sichtbar sind die Schäden der EIGENEN Liegenschaften (Eigentümerbezug; der Mandantenfilter
kommt vom Default-Manager dazu): Titel, Liegenschaft, Objekt, Bauteil, Kategorie, Status,
Aufträge mit Handwerker (Firma), Kosten, Freigabe, Termin und Rechnungsbetrag.

NICHT sichtbar, und zwar nicht durch Weglassen in der Vorlage, sondern weil es nie in die
Rückgabe dieses Moduls gelangt (die Vorlagen bekommen Wörterbücher, keine Modelle):

* Kontaktdaten und Namen des Melders und der Mieter (`melder_*`, `email_melder`, `tel_melder`,
  `gemeldet_von`, `mieter_*`),
* die Beschreibung der Meldung und die Fotos (sie nennen Personen und Wohnungsinnenräume),
* `TicketNachricht` — gar nicht, auch nicht die nicht-internen: Nachrichten sind frei
  getippt, gehen an Melder und Handwerker und enthalten deren Adressen. Der Verlauf wird
  stattdessen aus den STRUKTURIERTEN Feldern von Schaden und Auftrag abgeleitet,
* Bemerkung des Auftrags (Text der Verwaltung an den Handwerker), Link-Token, IBAN und
  Referenz der Kreditorenrechnung (es gehen nur Vorhandensein, Betrag und Rechnungsdatum raus).

VERLAUF AUS FELDERN, NICHT AUS PROTOKOLLTEXTEN

Nicht jedes Ereignis hat einen Zeitstempel im Bestand. Was einen hat, trägt das Datum
(Meldung `erstellt_am`, Auftrag `beauftragt_am`, Freigabe `freigabe_datum`, Rechnung `datum`).
Was keinen hat, steht OHNE Datum an seiner logischen Stelle (Termin vereinbart: der Termin
selbst steht im Text; Freigabe angefragt; Arbeit erledigt). Ein erfundenes Datum wäre falsch.
«Abgeschlossen» trägt `aktualisiert_am` des Schadens: der Zeitpunkt der letzten Änderung, der
beim Abschluss der richtige ist, bei späteren Änderungen aber nachläuft (Näherung; es gibt
kein Feld «erledigt am»).
"""
from collections import defaultdict

from django.db.models import Case, Count, F, Prefetch, Q, Sum, When
from django.db.models.functions import ExtractYear
from django.utils.translation import gettext, gettext_lazy as _

from core.services.eigentuemer_portal import NULL, eigene_liegenschaften

#: Auftrag, der nicht mehr gilt (`tickets.workflow.AUFTRAG_STORNIERT`); zählt in keiner Summe.
AUFTRAG_STORNIERT = 'storniert'

STATUS_FILTER = (('offen', _('Offen')), ('erledigt', _('Erledigt')))
SEITENGROESSE = 25

ROLLE_VERWALTUNG = _('Verwaltung')
ROLLE_EIGENTUEMER = _('Eigentümer')
ROLLE_MIETER = _('Mieter')
ROLLE_MELDER = _('Melder')


def _rolle_handwerker(firma):
    return gettext('Handwerker %(firma)s') % {'firma': firma}


# ---------------------------------------------------------------------------
# Menge der eigenen Schäden
# ---------------------------------------------------------------------------

def eigene_schaeden(eigentuemer):
    """Alle Schäden der Liegenschaften dieses Eigentümers (archivierte eingeschlossen)."""
    from tickets.models import SchadenMeldung
    return SchadenMeldung.objects.filter(liegenschaft__eigentuemer=eigentuemer)


def _auftrags_prefetch():
    from tickets.models import HandwerkerAuftrag
    return Prefetch('handwerker_auftraege',
                    queryset=HandwerkerAuftrag.objects.select_related('handwerker', 'kreditoren_rechnung')
                    .order_by('beauftragt_am', 'id'))


def jahre_der_schaeden(eigentuemer):
    """Meldejahre, in denen es Schäden gibt, neueste zuerst (für den Jahresfilter)."""
    return sorted({j for j in eigene_schaeden(eigentuemer).order_by()
                   .annotate(j=ExtractYear('erstellt_am')).values_list('j', flat=True)}, reverse=True)


def gefiltert(eigentuemer, *, liegenschaft=None, status=None, jahr=None):
    """Eigene Schäden, eingeschränkt. Ein Filter auf eine fremde Liegenschaft ergibt einfach nichts."""
    qs = eigene_schaeden(eigentuemer)
    if liegenschaft:
        qs = qs.filter(liegenschaft_id=liegenschaft)
    if status == 'offen':
        qs = qs.exclude(status='erledigt')
    elif status == 'erledigt':
        qs = qs.filter(status='erledigt')
    if jahr:
        qs = qs.filter(erstellt_am__year=jahr)
    return qs


# ---------------------------------------------------------------------------
# Baustein: ein Auftrag / ein Schaden als Wörterbuch
# ---------------------------------------------------------------------------

def _auftrag(a):
    """Ein Auftrag in der Form, die der Eigentümer sehen darf."""
    r = a.kreditoren_rechnung if a.kreditoren_rechnung_id else None
    rechnung_gilt = r is not None and r.status != 'storniert'
    return {
        'id': a.pk,
        'firma': a.handwerker.firma,
        'beauftragt_am': a.beauftragt_am,
        'storniert': a.status == AUFTRAG_STORNIERT,
        'termin': a.termin_am if (a.termin_status == 'vereinbart' and a.termin_am) else None,
        'termin_abgesagt': a.termin_status == 'abgesagt',
        'geschaetzt': a.kosten_geschaetzt,
        'effektiv': a.kosten_effektiv,
        'freigabe': a.freigabe_status,
        'freigabe_text': a.get_freigabe_status_display(),
        'freigabe_datum': a.freigabe_datum,
        'freigabe_kommentar': (a.freigabe_kommentar or '').strip(),
        'rechnung': rechnung_gilt,
        'rechnung_storniert': r is not None and not rechnung_gilt,
        'rechnung_betrag': r.betrag if rechnung_gilt else None,
        'rechnung_datum': r.datum if rechnung_gilt else None,
    }


def _schaden(t, auftraege):
    from stweg.bauteile import bezeichnung as bauteil_name
    objekt = t.betroffene_einheit.bezeichnung if t.betroffene_einheit_id else (t.objekt or '')
    gilt = [a for a in auftraege if not a['storniert']]
    return {
        'id': t.pk,
        'titel': t.titel,
        'liegenschaft': t.liegenschaft,
        'objekt': objekt,
        'bauteil': bauteil_name(t.bauteil),
        'kategorie': t.kategorie or '',
        'gemeldet_am': t.erstellt_am,
        'status': t.status,
        'status_text': t.get_status_display(),
        'erledigt': t.status == 'erledigt',
        # «erledigt am»: es gibt kein eigenes Feld; siehe Modulkopf (Näherung).
        'erledigt_am': t.aktualisiert_am if t.status == 'erledigt' else None,
        'auftraege': auftraege,
        'anzahl_auftraege': len(gilt),
        'ausstehend': sum(1 for a in gilt if a['freigabe'] == 'ausstehend'),
        'effektiv': _summe(a['effektiv'] for a in gilt),
        'geschaetzt_offen': _summe(a['geschaetzt'] for a in gilt if a['effektiv'] is None),
    }


def _summe(werte):
    """Summe der erfassten Werte; `None` (nicht erfasst) zählt nicht als 0, eine leere Menge ist `None`."""
    erfasst = [w for w in werte if w is not None]
    return sum(erfasst, NULL) if erfasst else None


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

def liste(eigentuemer, *, liegenschaft=None, status=None, jahr=None, seite=1):
    """Eine Seite Schäden (neueste zuerst) plus Kennzahlen über die ganze gefilterte Menge.

    Abfragen: Schäden, Aufträge samt Handwerker und Rechnung (Prefetch), Zählung, Summen —
    unabhängig von der Zahl der Schäden."""
    from django.core.paginator import Paginator
    qs = gefiltert(eigentuemer, liegenschaft=liegenschaft, status=status, jahr=jahr)
    kennzahlen = _kennzahlen(qs)
    seiten = Paginator(qs.select_related('liegenschaft', 'betroffene_einheit')
                       .prefetch_related(_auftrags_prefetch()).order_by('-erstellt_am', '-id'),
                       SEITENGROESSE)
    s = seiten.get_page(seite)
    zeilen = [_schaden(t, [_auftrag(a) for a in t.handwerker_auftraege.all()]) for t in s.object_list]
    return {'zeilen': zeilen, 'seite': s, 'kennzahlen': kennzahlen}


def _kennzahlen(qs):
    from tickets.models import HandwerkerAuftrag
    z = qs.order_by().aggregate(anzahl=Count('id'), offen=Count('id', filter=~Q(status='erledigt')))
    a = (HandwerkerAuftrag.objects.filter(ticket__in=qs.order_by().values('pk'))
         .exclude(status=AUFTRAG_STORNIERT)
         .aggregate(effektiv=Sum('kosten_effektiv'),
                    geschaetzt=Sum(Case(When(kosten_effektiv__isnull=True, then=F('kosten_geschaetzt'))))))
    return {'anzahl': z['anzahl'], 'offen': z['offen'], 'erledigt': z['anzahl'] - z['offen'],
            'effektiv': a['effektiv'], 'geschaetzt_offen': a['geschaetzt']}


# ---------------------------------------------------------------------------
# Detail mit Verlauf
# ---------------------------------------------------------------------------

def detail(eigentuemer, pk):
    """Ein Schaden mit Aufträgen und Verlauf — `None`, wenn er nicht zu diesem Eigentümer gehört (404)."""
    t = (eigene_schaeden(eigentuemer).filter(pk=pk)
         .select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von')
         .prefetch_related(_auftrags_prefetch()).first())
    if t is None:
        return None
    auftraege = [_auftrag(a) for a in t.handwerker_auftraege.all()]
    d = _schaden(t, auftraege)
    d['verlauf'] = verlauf(t, auftraege)
    return d


def _ereignis(art, titel, akteur, datum=None, text='', termin=None):
    return {'art': art, 'titel': titel, 'akteur': akteur, 'datum': datum, 'text': text, 'termin': termin}


def verlauf(t, auftraege):
    """Kuratierte Ereignisliste in fachlicher Reihenfolge (siehe Modulkopf).

    Akteure nur als Rolle: «Verwaltung», «Handwerker <Firma>», «Eigentümer», «Mieter»/«Melder».
    `t.gemeldet_von` wird nur auf Vorhandensein geprüft (Rolle), nie gelesen."""
    e = [_ereignis('meldung', _('Meldung eingegangen'),
                   ROLLE_MIETER if t.gemeldet_von_id else ROLLE_MELDER, t.erstellt_am)]
    gilt = [a for a in auftraege if not a['storniert']]
    for a in auftraege:
        e.append(_ereignis('auftrag', _('Auftrag vergeben'), ROLLE_VERWALTUNG, a['beauftragt_am'], a['firma']))
        if a['storniert']:
            e.append(_ereignis('storno', _('Auftrag storniert'), ROLLE_VERWALTUNG, None, a['firma']))
            continue
        if a['termin']:
            e.append(_ereignis('termin', _('Termin vereinbart'), ROLLE_VERWALTUNG, None, a['firma'],
                               termin=a['termin']))
        if a['termin_abgesagt']:
            e.append(_ereignis('termin', _('Termin abgesagt'), ROLLE_VERWALTUNG, None, a['firma']))
        if a['freigabe'] != 'nicht_noetig':
            e.append(_ereignis('freigabe', _('Freigabe angefragt'), ROLLE_VERWALTUNG, None, a['firma']))
        if a['freigabe'] == 'freigegeben':
            e.append(_ereignis('freigabe', _('Freigabe erteilt'), ROLLE_EIGENTUEMER,
                               a['freigabe_datum'], a['freigabe_kommentar']))
        elif a['freigabe'] == 'abgelehnt':
            e.append(_ereignis('freigabe', _('Freigabe abgelehnt'), ROLLE_EIGENTUEMER,
                               a['freigabe_datum'], a['freigabe_kommentar']))
    if gilt and t.status in ('wartet_auf_rechnung', 'erledigt'):
        e.append(_ereignis('arbeit', _('Arbeit erledigt'),
                           _rolle_handwerker(gilt[0]['firma']) if len(gilt) == 1 else gettext('Handwerker')))
    for a in gilt:
        if a['rechnung']:
            e.append(_ereignis('rechnung', _('Rechnung eingegangen'), _rolle_handwerker(a['firma']),
                               a['rechnung_datum']))
    if t.status == 'erledigt':
        e.append(_ereignis('abschluss', _('Schaden abgeschlossen'), ROLLE_VERWALTUNG, t.aktualisiert_am))
    return e


# ---------------------------------------------------------------------------
# Reparaturhistorie je Liegenschaft
# ---------------------------------------------------------------------------

def historie(eigentuemer, lg_pk):
    """Reparaturhistorie einer eigenen Liegenschaft: je Meldejahr Anzahl und Kosten.

    `None`, wenn die Liegenschaft nicht diesem Eigentümer gehört. Zwei Abfragen (Schäden je Jahr,
    Aufträge je Jahr), unabhängig vom Bestand. Stornierte Aufträge zählen nicht. `effektiv` ist
    die Summe der abgerechneten Kosten, `geschaetzt_offen` die Schätzung der Aufträge, die noch
    keine effektiven Kosten haben; beide `None`, wenn nichts erfasst ist (nicht 0)."""
    from tickets.models import HandwerkerAuftrag, SchadenMeldung
    lg = eigene_liegenschaften(eigentuemer).filter(pk=lg_pk).first()
    if lg is None:
        return None
    jahre = defaultdict(lambda: {'anzahl': 0, 'offen': 0, 'effektiv': None, 'geschaetzt_offen': None})
    for z in (SchadenMeldung.objects.filter(liegenschaft=lg).order_by()
              .values(jahr=ExtractYear('erstellt_am'))
              .annotate(n=Count('id'), offen=Count('id', filter=~Q(status='erledigt')))):
        jahre[z['jahr']].update(anzahl=z['n'], offen=z['offen'])
    for z in (HandwerkerAuftrag.objects.filter(ticket__liegenschaft=lg).exclude(status=AUFTRAG_STORNIERT)
              .order_by().values(jahr=ExtractYear('ticket__erstellt_am'))
              .annotate(eff=Sum('kosten_effektiv'),
                        gesch=Sum(Case(When(kosten_effektiv__isnull=True, then=F('kosten_geschaetzt')))))):
        jahre[z['jahr']].update(effektiv=z['eff'], geschaetzt_offen=z['gesch'])
    zeilen = [dict(jahr=j, **jahre[j]) for j in sorted(jahre, reverse=True)]
    return {'zeilen': zeilen,
            'anzahl': sum(z['anzahl'] for z in zeilen),
            'offen': sum(z['offen'] for z in zeilen),
            'effektiv': _summe(z['effektiv'] for z in zeilen)}
