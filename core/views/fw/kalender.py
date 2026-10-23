"""Monatskalender — Termine, Fristen, Ticket-Zielzeiten und Auszüge an einem Ort.

WARUM

`/neu/termine/` ist eine Liste: gut für «was kommt als Nächstes», schlecht für «wie
voll ist die Woche vom 14.?». Eine Bewirtschafterin plant Abnahmen und Handwerker
am Raster. Die vier Quellen stehen bisher auf vier Seiten (Termine, Fristen,
Schäden, Verträge); hier liegen sie zum ersten Mal übereinander.

WAS ES NICHT IST

Kein neues Datenmodell und keine Synchronisation: Der Kalender liest, was es gibt.
Bearbeitet wird an der Quelle — ein Klick führt dorthin. Das Erfassen eines Termins
bleibt auf `/neu/termine/`.

QUELLEN

    termin   `faelle.Termin` (nicht abgesagt; Erledigtes bleibt, aber gedämpft)
    frist    `core.Pendenz` mit Datum, offen
    ticket   `SchadenMeldung.faellig_bis` (Zielzeit), solange nicht erledigt
    auszug   `Mietvertrag` im Zustand «gekündigt» mit Enddatum im Monat

Alles läuft durch die Mandantenfilter der Manager; die Liegenschaftswahl der
Kopfzeile gilt für Fristen, Tickets und Auszüge (Termine tragen keine).
"""
import calendar
from datetime import date, datetime, timedelta

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy

from core.auth import TEAM_ROLLEN, rolle_erforderlich

from ._basis import _global_filter, _pendenz_ziel

ARTEN = [
    ('termin', gettext_lazy('Termine')),
    ('frist', gettext_lazy('Fristen')),
    ('ticket', gettext_lazy('Ticket-Zielzeiten')),
    ('auszug', gettext_lazy('Auszüge')),
]
#: Chips je Tag im Raster — der Rest steht in der Tagesliste.
MAX_JE_TAG = 3
MONATE = ['', 'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August',
          'September', 'Oktober', 'November', 'Dezember']


def _monat_aus(text, heute):
    try:
        j, m = (int(x) for x in (text or '').split('-'))
        return date(j, m, 1) if 1 <= m <= 12 and 2000 <= j <= 2100 else heute.replace(day=1)
    except (ValueError, TypeError):
        return heute.replace(day=1)


def ereignisse(erster, letzter, aktive_lg=None):
    """Alle Ereignisse zwischen zwei Daten (einschliesslich) als Wörterbücher."""
    from core.models import Pendenz
    from faelle.termin_models import Termin
    from rentals.models import Mietvertrag
    from tickets.models import SchadenMeldung

    out = []
    von = timezone.make_aware(datetime.combine(erster, datetime.min.time()))
    bis = timezone.make_aware(datetime.combine(letzter + timedelta(days=1), datetime.min.time()))
    for t in Termin.objects.filter(beginn__gte=von, beginn__lt=bis).select_related('zustaendig'):
        lokal = timezone.localtime(t.beginn)
        out.append({'typ': 'termin', 'tag': lokal.date(), 'zeit': lokal.strftime('%H:%M'),
                    'titel': t.titel, 'sub': ' · '.join(x for x in (t.get_art_display(), t.ort) if x),
                    'url': '/neu/termine/', 'ton': 'brand',
                    'gedaempft': t.status in (Termin.ERLEDIGT, Termin.ABGESAGT),
                    'status': t.get_status_display() if t.status != Termin.GEPLANT else ''})

    pq = (Pendenz.objects.filter(erledigt=False, faellig_am__range=(erster, letzter))
          .select_related('liegenschaft', 'vertrag__mieter', 'vertrag__einheit__liegenschaft'))
    if aktive_lg:
        pq = pq.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg)
                       | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    for p in pq:
        url = _pendenz_ziel(p)[0]
        out.append({'typ': 'frist', 'tag': p.faellig_am, 'zeit': '', 'titel': p.titel,
                    'sub': gettext('Frist'), 'url': url or '/neu/fristen/', 'ton': 'warn',
                    'gedaempft': False, 'status': ''})

    tq = (SchadenMeldung.objects.exclude(status='erledigt')
          .filter(faellig_bis__range=(erster, letzter)).select_related('liegenschaft'))
    if aktive_lg:
        tq = tq.filter(liegenschaft=aktive_lg)
    for s in tq:
        out.append({'typ': 'ticket', 'tag': s.faellig_bis, 'zeit': '',
                    'titel': f'#{s.id} {s.titel}', 'sub': gettext('erledigen bis'),
                    'url': f'/neu/schaeden/{s.id}/',
                    'ton': 'crit' if (s.prioritaet or '').lower() in ('notfall', 'hoch') else 'info',
                    'gedaempft': False, 'status': ''})

    vq = (Mietvertrag.objects.filter(status='gekuendigt', ende__range=(erster, letzter))
          .select_related('mieter', 'einheit__liegenschaft'))
    if aktive_lg:
        vq = vq.filter(einheit__liegenschaft=aktive_lg)
    for v in vq:
        out.append({'typ': 'auszug', 'tag': v.ende, 'zeit': '',
                    'titel': gettext('Auszug %(name)s') % {'name': v.mieter.display_name if v.mieter_id else ''},
                    'sub': f"{v.einheit.bezeichnung}, {v.einheit.liegenschaft.strasse}" if v.einheit_id else '',
                    'url': f'/neu/vertraege/{v.id}/', 'ton': 'good',
                    'gedaempft': False, 'status': ''})
    out.sort(key=lambda e: (e['tag'], e['zeit'] or '99:99', e['titel']))
    return out


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kalender(request):
    basis = _global_filter(request)
    heute = timezone.localdate()
    erster = _monat_aus(request.GET.get('monat'), heute)
    letzter = erster.replace(day=calendar.monthrange(erster.year, erster.month)[1])
    # Raster: Montag der ersten bis Sonntag der letzten Woche.
    raster_von = erster - timedelta(days=erster.weekday())
    raster_bis = letzter + timedelta(days=6 - letzter.weekday())

    gewaehlt = {a for a, _ in ARTEN if request.GET.get('zeige', '') == '' or a in request.GET.get('zeige', '').split(',')}
    alle = [e for e in ereignisse(raster_von, raster_bis, basis['aktive_lg']) if e['typ'] in gewaehlt]
    je_tag = {}
    for e in alle:
        je_tag.setdefault(e['tag'], []).append(e)

    try:
        tag = date.fromisoformat(request.GET.get('tag', ''))
    except ValueError:
        tag = heute if erster <= heute <= letzter else erster

    wochen, d = [], raster_von
    while d <= raster_bis:
        woche = []
        for _i in range(7):
            liste = je_tag.get(d, [])
            woche.append({'datum': d, 'im_monat': d.month == erster.month, 'heute': d == heute,
                          'gewaehlt': d == tag, 'wochenende': d.weekday() >= 5,
                          'ereignisse': liste[:MAX_JE_TAG], 'mehr': max(0, len(liste) - MAX_JE_TAG),
                          'anzahl': len(liste)})
            d += timedelta(days=1)
        wochen.append(woche)

    vorher = (erster - timedelta(days=1)).replace(day=1)
    nachher = letzter + timedelta(days=1)
    tage_liste = [{'datum': t, 'ereignisse': je_tag[t], 'heute': t == heute}
                  for t in sorted(je_tag) if erster <= t <= letzter]
    zaehler = {a: sum(1 for e in alle if e['typ'] == a and erster <= e['tag'] <= letzter) for a, _ in ARTEN}

    return render(request, 'fw/kalender.html', {
        **basis, 'nav': 'termine',
        'monat_name': f'{MONATE[erster.month]} {erster.year}',
        'wochen': wochen, 'tag': tag, 'tag_ereignisse': je_tag.get(tag, []),
        'tage_liste': tage_liste, 'heute': heute,
        'vorher': vorher.strftime('%Y-%m'), 'nachher': nachher.strftime('%Y-%m'),
        'dieser': heute.strftime('%Y-%m'), 'monat': erster.strftime('%Y-%m'),
        'arten': [(a, b, zaehler[a], a in gewaehlt) for a, b in ARTEN],
        'wochentage': ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'],
        'gesamt': sum(zaehler.values()),
    })
