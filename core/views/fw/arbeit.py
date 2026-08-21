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
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_POST

from core.auth import rolle_erforderlich, SCHREIB_ROLLEN, TEAM_ROLLEN

from ._basis import _global_filter, _num

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
    """Leitet auf die Startseite um.

    Bis zum 21.08.2026 war dies eine eigene Flaeche mit Arbeitsvorrat, Zulauf
    und Ansichten — und `/neu/` zeigte DIESELBEN zwei Abschnitte plus vier
    Kennzahlkacheln. Zwei Startflaechen mit derselben Aufgabe, von denen die
    aeltere gewann, weil sie unter `/neu/` lag.

    Die Ansichten sind auf die Startseite gewandert; damit ist diese hier
    ueberfluessig. Die URL bleibt bestehen, weil Lesezeichen darauf zeigen
    koennen — sie leitet weiter, statt ins Leere zu laufen. Der
    `ansicht`-Parameter wird mitgenommen; ohne ihn landete ein gespeicherter
    Verweis auf «Liegengeblieben» wieder bei «Heute».
    """
    ziel = '/neu/'
    ansicht = request.GET.get('ansicht')
    if ansicht:
        ziel += f'?ansicht={ansicht}'
    return redirect(ziel)


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


# ============================================================
# TERMINE UND ABWESENHEITEN (Phase 4b.8)
#
# Ohne Erfassungsseite waeren die beiden neuen Modelle genau das, was
# Phase 4a vier Etappen lang war: vollstaendig getestet und fuer niemanden
# erreichbar. Deshalb stehen Liste und Formular hier gleich mit.
# ============================================================


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_termine(request):
    """Alle Termine — kommende zuerst, vergangene darunter."""
    from faelle.termin_models import Termin

    jetzt = timezone.now()
    kommend = list(Termin.objects.offen().filter(beginn__gte=jetzt)
                   .select_related('zustaendig')[:100])
    vergangen = list(Termin.objects.filter(beginn__lt=jetzt)
                     .select_related('zustaendig').order_by('-beginn')[:30])
    return render(request, 'fw/termine.html', {
        **_global_filter(request), 'nav': 'arbeit',
        'kommend': kommend, 'vergangen': vergangen,
        'arten': Termin.ARTEN, 'heute': timezone.localdate(),
    })


@require_POST
@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_termin_neu(request):
    from faelle.termin_models import Termin

    beginn = parse_datetime(request.POST.get('beginn') or '')
    titel = (request.POST.get('titel') or '').strip()
    if not beginn or not titel:
        # Kein stiller Abbruch: Wer ein Formular abschickt und nichts
        # passieren sieht, schickt es nochmal.
        messages.error(request, 'Titel und Beginn sind nötig.')
        return redirect('/neu/termine/')
    if timezone.is_naive(beginn):
        beginn = timezone.make_aware(beginn)
    Termin(titel=titel, beginn=beginn,
           art=request.POST.get('art') or Termin.SONSTIGES,
           dauer_minuten=_num(request.POST.get('dauer_minuten')) or 60,
           ort=(request.POST.get('ort') or '').strip(),
           notiz=(request.POST.get('notiz') or '').strip(),
           zustaendig=request.user).save()
    messages.success(request, f'Termin «{titel}» erfasst.')
    return redirect('/neu/termine/')


@require_POST
@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_termin_status(request, pk):
    """Erledigt oder abgesagt — beides nimmt den Termin aus der Heute-Sicht."""
    from faelle.termin_models import Termin

    # `get_object_or_404` ueber den gefilterten Manager: Eine fremde ID muss
    # 404 liefern, nicht 403. Ein 403 bestaetigte, dass der Termin existiert.
    termin = get_object_or_404(Termin.objects, pk=pk)
    neu = request.POST.get('status')
    if neu not in dict(Termin.STATUS):
        messages.error(request, 'Unbekannter Status.')
        return redirect('/neu/termine/')
    termin.status = neu
    termin.save(update_fields=['status'])
    messages.success(request, f'«{termin.titel}» ist {termin.get_status_display().lower()}.')
    return redirect('/neu/termine/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abwesenheiten(request):
    """Wer wann weg ist — und wer übernimmt."""
    from crm.models import Mitgliedschaft
    from faelle.termin_models import Abwesenheit

    heute = timezone.localdate()
    return render(request, 'fw/abwesenheiten.html', {
        **_global_filter(request), 'nav': 'arbeit', 'heute': heute,
        'laufend': list(Abwesenheit.objects.laufend(heute)
                        .select_related('benutzer', 'vertreten_durch')),
        'kommend': list(Abwesenheit.objects.filter(von__gt=heute)
                        .select_related('benutzer', 'vertreten_durch')[:30]),
        'vergangen': list(Abwesenheit.objects.filter(bis__lt=heute)
                          .select_related('benutzer', 'vertreten_durch')
                          .order_by('-bis')[:15]),
        # Nur Mitglieder DIESER Organisation zur Auswahl — sonst stünde im
        # Formular die Belegschaft des Nachbarn.
        'leute': [m.benutzer for m in Mitgliedschaft.objects
                  .filter(organisation=request.organisation)
                  .select_related('benutzer')],
        'gruende': Abwesenheit.GRUENDE,
    })


@require_POST
@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abwesenheit_neu(request):
    from django.core.exceptions import ValidationError

    from faelle.termin_models import Abwesenheit

    a = Abwesenheit(
        benutzer_id=_num(request.POST.get('benutzer')) or request.user.id,
        von=parse_date(request.POST.get('von') or ''),
        bis=parse_date(request.POST.get('bis') or ''),
        grund=request.POST.get('grund') or Abwesenheit.FERIEN,
        vertreten_durch_id=_num(request.POST.get('vertreten_durch')) or None,
        notiz=(request.POST.get('notiz') or '').strip())
    if not a.von or not a.bis:
        messages.error(request, 'Von und Bis sind nötig.')
        return redirect('/neu/abwesenheiten/')
    try:
        # `clean()` prueft Ende-vor-Beginn und Selbstvertretung. Ohne
        # ausdruecklichen Aufruf laeuft es bei `save()` NICHT mit — dann
        # landeten beide Fehler stumm in der Datenbank.
        a.full_clean(exclude=('organisation',))
    except ValidationError as fehler:
        messages.error(request, ' '.join(
            m for liste in fehler.message_dict.values() for m in liste))
        return redirect('/neu/abwesenheiten/')
    a.save()
    messages.success(request, 'Abwesenheit erfasst.')
    return redirect('/neu/abwesenheiten/')
