"""Ticket-Board (Kanban) — dieselben Tickets wie die Liste, nach Zustand in Spalten.

WARUM ES DAS GIBT

Die Liste «Schadensfälle» sortiert nach Befund und beantwortet «was brennt?».
Eine Bewirtschafterin mit zwanzig offenen Tickets fragt aber auch «wo steht was?»:
was ist neu, was liegt bei mir, worauf warte ich. Das zeigt ein Board mit einem
Blick — und der Statuswechsel ist ein Ziehen statt drei Klicks.

WAS SICH NICHT ÄNDERT

* Die Daten kommen aus `faelle.schaeden.zeilen` — dieselbe Befundrechnung wie die
  Liste, dieselben Sichtrechte (der Hauswart sieht nur seine Liegenschaften).
* Jeder Statuswechsel läuft über `tickets.workflow.wechsle_status`. Die Sperre
  «nicht erledigt ohne Handwerkerrechnung» gilt also auch beim Ziehen; die Karte
  springt zurück und die Meldung sagt warum.
* Vier Spalten, sechs Zustände: «Wartet auf Dritte» fasst Mieter, Handwerker und
  Rechnung zusammen. Wer eine Karte dorthin zieht, bekommt den ersten Zustand der
  Spalte, den der Fluss von hier aus erlaubt (`tickets.workflow.UEBERGAENGE`);
  den genauen Zustand wählt das Auswahlfeld an der Karte. Es bietet nur Zustände
  an, die erlaubt sind — wer «Erledigt» aus «Neu» sucht, sieht ihn, wer von
  «Erledigt» nach «Wartet» will, nicht.
"""
from datetime import timedelta

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy
from django.views.decorators.http import require_POST

from core.auth import (TICKET_LESE_ROLLEN, TICKET_SCHREIB_ROLLEN, ist_nur_hauswart,
                       log_aktion, rolle_erforderlich)

from ._basis import _global_filter
from .schaeden import PRIO_PILL, _hauswart_pruefen

#: (Schlüssel, Beschriftung, Zustände der Spalte in Vorzugsreihenfolge beim Ablegen)
SPALTEN = [
    ('neu', gettext_lazy('Neu'), ('neu',)),
    ('bearbeitung', gettext_lazy('In Bearbeitung'), ('in_bearbeitung',)),
    ('wartet', gettext_lazy('Wartet auf Dritte'),
     ('warte_auf_handwerker', 'warte_auf_mieter', 'wartet_auf_rechnung')),
    ('erledigt', gettext_lazy('Erledigt'), ('erledigt',)),
]
#: Erledigte Tickets bleiben so lange sichtbar — danach gehören sie ins Archiv (Liste).
ERLEDIGT_TAGE = 30
ERLEDIGT_MAX = 20


def _initialen(user):
    name = (user.get_full_name() or user.username or '').strip()
    teile = name.replace('.', ' ').split()
    return ''.join(t[0] for t in teile[:2]).upper() or '?'


@rolle_erforderlich(*TICKET_LESE_ROLLEN)
def fw_schaeden_board(request):
    from faelle.schaeden import zeilen
    from tickets.models import SchadenMeldung
    from tickets.sla import ist_ueberfaellig
    from tickets.workflow import erlaubte_ziele
    from django.db.models import Q

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    from core.services.archiv import ausblenden
    qs = ausblenden(SchadenMeldung.objects
                    .select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von', 'zugewiesen_an')
                    .prefetch_related('handwerker_auftraege', 'nachrichten'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    if ist_nur_hauswart(request.user):
        qs = qs.filter(liegenschaft__hauswarte=request.user)

    nur_meine = request.GET.get('zustaendig') == 'ich'
    if nur_meine:
        qs = qs.filter(zugewiesen_an=request.user)
    prio = request.GET.get('prio', '')
    if prio == 'dringend':
        qs = qs.filter(prioritaet__in=('notfall', 'hoch'))
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(titel__icontains=q) | Q(beschreibung__icontains=q)
                       | Q(liegenschaft__strasse__icontains=q))
    # Erledigtes nur ein Monat zurück — das Board ist eine Arbeitsfläche, kein Archiv.
    grenze = timezone.now() - timedelta(days=ERLEDIGT_TAGE)
    qs = qs.exclude(status='erledigt', aktualisiert_am__lt=grenze)

    alle = zeilen(qs)
    nur_ueberfaellig = request.GET.get('sla') == 'ueberfaellig'
    karten = []
    for z in alle:
        t = z['t']
        z['ueberfaellig'] = ist_ueberfaellig(t)
        if nur_ueberfaellig and not z['ueberfaellig']:
            continue
        z['p_label'], z['p_cls'] = PRIO_PILL.get((t.prioritaet or '').lower(),
                                                 (t.prioritaet or 'Mittel', 'fw-flaeche2 fw-mutet'))
        z['objekt'] = (f"{t.liegenschaft.strasse}, {t.liegenschaft.ort}" if t.liegenschaft_id else '—')
        z['wer'] = _initialen(t.zugewiesen_an) if t.zugewiesen_an_id else ''
        z['wer_name'] = ((t.zugewiesen_an.get_full_name() or t.zugewiesen_an.username)
                         if t.zugewiesen_an_id else '')
        z['alter'] = max(0, (timezone.now() - t.erstellt_am).days)
        karten.append(z)

    spalten = []
    labels = dict(SchadenMeldung.STATUS_CHOICES)
    for z in karten:
        z['ziele'] = [(w, labels[w]) for w in [z['t'].status] + erlaubte_ziele(z['t'].status)]
    for schluessel, label, zustaende in SPALTEN:
        eigene = [z for z in karten if z['t'].status in zustaende]
        # Dringendes und Überfälliges nach oben, dann das Älteste.
        eigene.sort(key=lambda z: (not z['ueberfaellig'],
                                   (z['t'].prioritaet or '') not in ('notfall', 'hoch'),
                                   -z['alter']))
        gesamt = len(eigene)
        if schluessel == 'erledigt':
            eigene = eigene[:ERLEDIGT_MAX]
        spalten.append({'key': schluessel, 'label': label,
                        'karten': eigene, 'anzahl': gesamt})

    return render(request, 'fw/schaeden_board.html', {
        **basis, 'nav': 'schadensfaelle',
        'spalten': spalten, 'q': q, 'nur_meine': nur_meine, 'prio': prio,
        'nur_ueberfaellig': nur_ueberfaellig, 'gesamt': len(karten),
        'kann_verschieben': request.user.is_authenticated and _darf_schreiben(request),
        'erledigt_tage': ERLEDIGT_TAGE,
    })


def _darf_schreiben(request):
    from core.auth import hat_rolle
    return hat_rolle(request.user, TICKET_SCHREIB_ROLLEN)


def _antwort(request, t, ok, text, status=200):
    """JSON für das Ziehen, Weiterleitung mit Meldung für das Auswahlfeld."""
    from tickets.models import SchadenMeldung
    from tickets.workflow import erlaubte_ziele
    als_json = (request.headers.get('x-requested-with') == 'XMLHttpRequest'
                or 'application/json' in request.headers.get('accept', ''))
    if als_json:
        labels = dict(SchadenMeldung.STATUS_CHOICES)
        return JsonResponse({
            'ok': ok, 'meldung': str(text), 'status': t.status, 'label': str(t.get_status_display()),
            'ziele': [[w, str(labels[w])] for w in [t.status] + erlaubte_ziele(t.status)]},
            status=status)
    (messages.success if ok else messages.error)(request, text)
    return redirect('/neu/schaeden/board/')


@rolle_erforderlich(*TICKET_SCHREIB_ROLLEN)
@require_POST
def fw_schaden_verschieben(request, pk):
    """Statuswechsel vom Board — als Ziehen (JSON) oder Auswahlfeld (Formular)."""
    from django.core.exceptions import ValidationError
    from tickets.models import SchadenMeldung, TicketNachricht
    from tickets.workflow import erlaubte_ziele, wechsle_status
    from core.services.dokumentsprache import auf_deutsch

    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft'), id=pk)
    _hauswart_pruefen(request, t)
    neu = request.POST.get('status', '')
    spalte = request.POST.get('spalte', '')
    if spalte and not neu:
        # Ziehen: den ersten Zustand der Zielspalte nehmen, den der Fluss erlaubt.
        zustaende = next((z for k, _l, z in SPALTEN if k == spalte), ())
        if t.status in zustaende:
            neu = t.status
        else:
            neu = next((z for z in zustaende if z in erlaubte_ziele(t.status)), '')
        if not neu:
            return _antwort(request, t, False, gettext(
                'Von «%(von)s» ist kein Wechsel in diese Spalte vorgesehen.') % {
                'von': t.get_status_display()}, 409)

    def antwort(ok, text, status=200):
        return _antwort(request, t, ok, text, status)

    if neu not in dict(SchadenMeldung.STATUS_CHOICES):
        return antwort(False, gettext('Ungültiger Status.'), 400)
    if neu == t.status:
        return antwort(True, gettext('Keine Änderung.'))
    try:
        wechsle_status(t, neu, melder_informieren=False)
    except ValidationError as e:
        t.refresh_from_db()
        return antwort(False, ' '.join(e.messages), 409)
    TicketNachricht.objects.create(
        ticket=t, absender_name='System', typ='system', is_intern=True,
        nachricht=f"Status geändert: {auf_deutsch(t.get_status_display)} (Board).")
    log_aktion(request, 'Ticket-Status geändert', f'Ticket #{t.id}', auf_deutsch(t.get_status_display))
    return antwort(True, gettext('Ticket #%(nr)s: %(status)s.') % {
        'nr': t.id, 'status': t.get_status_display()})
