# core/views/fw/arbeit.py
#
# Die drei Seiten, auf denen Phase 4a bedienbar wird: Arbeit, Fallakte, Läufe.
#
# WARUM ES SIE GEBEN MUSS
#
# `Fall`, `Fallschritt`, `Eingang`, `Zuordnungsregel`, `Lauf` und `Blockade`
# waren nach vier Etappen vollständig gebaut, vollständig getestet — und
# hatten null Views, null URLs, null Templates. Ein grüner Modelltest sagt
# nichts darüber, ob ein Mensch die Sache je zu Gesicht bekommt.
#
# NACH KONZEPT (KONZEPT-UI.md, Abschnitt 3.1 und 6)
#
#   Arbeit    Eine Liste aller offenen Vorgänge mit vorgefilterten Ansichten,
#             links der Zulauf als eigene Spalte. Ansichten: Heute · Diese
#             Woche · Wartet auf Dritte · Liegengeblieben · Alle.
#             **Keine Kennzahlen** — das steht dort ausdrücklich.
#   Läufe     Wiederkehrende Verarbeitung mit Zustand und dem, was blockiert.
#   Fallakte  Etappen und Schritte eines Vorgangs, mit Verfallsregel.

import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auth import rolle_erforderlich, SCHREIB_ROLLEN, TEAM_ROLLEN

from ._basis import _global_filter

logger = logging.getLogger(__name__)

#: Die fünf Ansichten aus Abschnitt 3.1, in dieser Reihenfolge.
ANSICHTEN = (
    ('heute', 'Heute'),
    ('woche', 'Diese Woche'),
    ('wartet', 'Wartet auf Dritte'),
    ('liegen', 'Liegengeblieben'),
    ('alle', 'Alle'),
)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_arbeit(request):
    """Der Arbeitsvorrat mit vorgefilterten Ansichten und dem Zulauf daneben."""
    from faelle.arbeitsvorrat import posteingang, was_reisst
    from faelle.models import Fall

    basis = _global_filter(request)
    heute = timezone.localdate()
    ansicht = request.GET.get('ansicht', 'heute')
    if ansicht not in dict(ANSICHTEN):
        ansicht = 'heute'

    faelle = []
    if ansicht == 'heute':
        vorrat = [e for e in was_reisst(heute, grenze=0, aktive_lg=basis['aktive_lg'])]
    elif ansicht == 'woche':
        vorrat = was_reisst(heute, grenze=7, aktive_lg=basis['aktive_lg'])
    elif ansicht == 'wartet':
        # Fälle im Wartestatus tragen kein Datum, an dem etwas reisst — sie
        # warten. Deshalb hier die FÄLLE, nicht der Fristenvorrat.
        vorrat = []
        faelle = list(Fall.objects.filter(status=Fall.WARTET)
                      .select_related('fallart', 'zustaendig')
                      .order_by('letzte_bewegung'))
    elif ansicht == 'liegen':
        vorrat = []
        faelle = list(Fall.objects.liegengeblieben()
                      .select_related('fallart', 'zustaendig')
                      .order_by('letzte_bewegung'))
    else:
        # «Alle» heisst alle — ohne Fenster. Ein Jahr ist die Obergrenze,
        # damit eine versehentlich auf 2099 datierte Frist die Seite nicht
        # allein füllt.
        vorrat = was_reisst(heute, grenze=365, aktive_lg=basis['aktive_lg'])

    eingaenge, eingaenge_gesamt = posteingang()
    return render(request, 'fw/arbeit.html', {
        **basis, 'nav': 'arbeit',
        'heute': heute,
        'ansicht': ansicht,
        'ansichten': [(k, b, k == ansicht) for k, b in ANSICHTEN],
        'vorrat': vorrat,
        'faelle': faelle,
        'av_eingaenge': eingaenge,
        'av_eingaenge_gesamt': eingaenge_gesamt,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_fall_detail(request, pk):
    """Die Fallakte: Etappen, Schritte, Verfallsregel.

    Der Fortschritt kommt aus `Fall.fortschritt()`, die Verfallsregel aus
    `ist_liegengeblieben()` — beide sind seit 4a.1 gebaut und getestet und
    werden hier zum ersten Mal angezeigt.
    """
    from faelle.models import Fall

    fall = get_object_or_404(
        Fall.objects.select_related('fallart', 'zustaendig', 'akte_typ'), pk=pk)
    schritte = list(fall.schritte.select_related('erledigt_durch').order_by('nr'))

    # Nach Etappen gruppieren, ohne die Reihenfolge zu verlieren. `groupby`
    # aus itertools wäre kürzer, verlangt aber vorsortierte Daten — die
    # Schritte sind nach `nr` sortiert, nicht nach Etappe.
    etappen = []
    for s in schritte:
        if not etappen or etappen[-1]['nr'] != s.etappe_nr:
            etappen.append({'nr': s.etappe_nr, 'bezeichnung': s.etappe, 'schritte': []})
        etappen[-1]['schritte'].append(s)

    # `naechster_schritt`, `fortschritt`, `ist_liegengeblieben` und
    # `tage_ohne_bewegung` sind PROPERTIES, keine Methoden — nachgesehen in
    # faelle/models.py, nicht geraten. Ein `()` dahinter warf
    # «'Fallschritt' object is not callable». Und `fortschritt` gibt ein
    # Tupel `(erledigt, gesamt)` zurueck; es hier auszupacken ist ehrlicher
    # als `fortschritt.0` in der Vorlage.
    erledigt, gesamt = fall.fortschritt
    return render(request, 'fw/fall_detail.html', {
        **_global_filter(request), 'nav': 'arbeit',
        'fall': fall,
        'etappen': etappen,
        'naechster': fall.naechster_schritt,
        'schritte_erledigt': erledigt,
        'schritte_gesamt': gesamt,
        'liegengeblieben': fall.ist_liegengeblieben,
        'tage_ohne_bewegung': fall.tage_ohne_bewegung,
        'heute': timezone.localdate(),
    })


@require_POST
@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_fallschritt_erledigen(request, pk):
    """Einen Schritt abhaken.

    `Fallschritt.erledigen()` setzt `erledigt_am`, `erledigt_durch` und
    bewegt den Fall — das ist die Grundlage der Verfallsregel. Deshalb wird
    hier die Modellmethode gerufen und nicht das Feld gesetzt.
    """
    from faelle.models import Fallschritt

    schritt = get_object_or_404(Fallschritt.objects.select_related('fall'), pk=pk)
    schritt.erledigen(benutzer=request.user)
    messages.success(request, f'«{schritt.bezeichnung}» ist erledigt.')
    return redirect(f'/neu/faelle/{schritt.fall_id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_laeufe(request):
    """Läufe mit Zustand — und dem, was sie blockiert.

    Der Blockadegrund steht als Text da («Verbrauchsablesung Techem fehlt»),
    nicht das Wort «blockiert»: Der Grund führt zu einer Handlung, das Wort
    zu einer Rückfrage.
    """
    from faelle.lauf_models import Lauf

    heute = timezone.localdate()
    offen, erledigt = [], []
    for lauf in (Lauf.objects.select_related('laufart')
                 .prefetch_related('blockaden').order_by('-faellig_am')[:100]):
        blockaden = list(lauf.offene_blockaden)
        zeile = {
            'lauf': lauf, 'blockaden': blockaden,
            'tage': (lauf.faellig_am - heute).days,
        }
        (erledigt if lauf.status == Lauf.ABGESCHLOSSEN else offen).append(zeile)
    offen.sort(key=lambda z: z['lauf'].faellig_am)
    return render(request, 'fw/laeufe.html', {
        **_global_filter(request), 'nav': 'arbeit',
        'heute': heute, 'offen': offen, 'erledigt': erledigt[:20],
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_zulauf(request):
    """Der ganze Posteingang mit Vorschlägen.

    Konzept Abschnitt 6: Jeder Eingang wird zu genau einem von drei Dingen —
    einer Akte zugeordnet, Auslöser eines Falls, oder bewusst abgelegt.
    """
    from faelle.arbeitsvorrat import posteingang
    from faelle.zulauf import vorschlagen
    from faelle.zulauf_models import Eingang

    basis = _global_filter(request)
    offen = list(Eingang.objects.offen()[:100])
    zeilen = [{'eingang': e, 'v': vorschlagen(e)} for e in offen]
    _z, gesamt = posteingang()
    return render(request, 'fw/zulauf.html', {
        **basis, 'nav': 'arbeit',
        'zeilen': zeilen, 'gesamt': gesamt,
        'erledigt': list(Eingang.objects.exclude(status=Eingang.OFFEN)
                         .order_by('-erledigt_am')[:20]),
    })


@require_POST
@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zulauf_uebernehmen(request, pk):
    """Den Vorschlag übernehmen — oder begründet ablegen."""
    from faelle.zulauf import uebernehmen
    from faelle.zulauf_models import Eingang

    eingang = get_object_or_404(Eingang, pk=pk)
    grund = (request.POST.get('ablegen') or '').strip()
    if grund:
        eingang.ablegen(grund, benutzer=request.user)
        messages.success(request, f'Abgelegt: {grund}')
        return redirect('/neu/zulauf/')
    try:
        uebernehmen(eingang, benutzer=request.user,
                    regel_lernen=bool(request.POST.get('regel_lernen')))
    except ValueError as fehler:
        # `uebernehmen` wirft absichtlich, wenn kein tragfähiger Vorschlag
        # vorliegt — Raten ist nicht vorgesehen (Konzept Abschnitt 6). Die
        # Meldung gehört dem Benutzer, nicht dem Log allein.
        messages.error(request, str(fehler))
        return redirect('/neu/zulauf/')
    messages.success(request, 'Eingang zugeordnet.')
    return redirect('/neu/zulauf/')
