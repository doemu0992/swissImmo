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

from ._basis import _global_filter, _num, team_der_organisation

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


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zeit_erfassen(request, pk):
    """Aufwand auf einem Fall erfassen (E2.46).

    `SCHREIB_ROLLEN`, NICHT `TEAM_ROLLEN`

    Der erste Entwurf nahm `TEAM_ROLLEN` — dieselbe Zeile wie bei der Ansicht
    darunter, kopiert ohne nachzudenken. `TEAM_ROLLEN` schliesst aber den
    LESEZUGRIFF ein: Wer nur lesen darf, haette Aufwand buchen koennen.

    `test_lesende_rolle_kann_nirgends_unbemerkt_schreiben` hat es beim ersten
    vollen Lauf gemeldet. Das Wort «unbemerkt» im Testnamen ist woertlich zu
    nehmen — es waere niemandem aufgefallen.

    WARUM ES DAS BIS HIERHER NICHT GAB

    `faelle.Zeiteintrag` steht seit der ersten Migration im Modell, mit
    Fallbezug, Minuten, Taetigkeit und `verrechenbar`. Ausser den Migrationen
    hat es NIEMAND benutzt — es gab keinen Weg, einen Eintrag anzulegen.
    `Fall.erfasste_minuten` zeigte deshalb auf jeder Fallakte «0 min», und
    `mandat_detail.html` traegt bis heute die Notiz, dass die
    Rentabilitaetsansicht «Zeiterfassung pro Fall voraussetzt, die es nicht
    gibt».

    MINUTEN, NICHT STUNDEN

    So steht es im Modell begruendet: «Eine Zeiterfassung, die nicht
    beilaeufig geht, wird nicht gepflegt.» Das Formular hat deshalb ein Feld
    und einen Knopf, keine Maske.

    DER STUNDENSATZ IST FREI

    Leer heisst «Vorgabe der Organisation». Ein eigener Wert traegt den Fall,
    in dem ein Einsatz anders kostet — Notfall am Sonntag, Pauschale, Kulanz.
    Ist WEDER hier NOCH an der Organisation ein Satz hinterlegt, bleibt der
    Betrag leer statt null: «nicht berechenbar» ist eine Aussage, «CHF 0.00»
    waere eine falsche.
    """
    from faelle.models import Fall, Zeiteintrag

    fall = get_object_or_404(Fall, pk=pk)
    if request.method != 'POST':
        return redirect(f'/neu/faelle/{pk}/')

    try:
        minuten = int(request.POST.get('minuten') or 0)
    except ValueError:
        minuten = 0
    if minuten <= 0:
        messages.error(request, 'Bitte eine Dauer in Minuten angeben.')
        return redirect(f'/neu/faelle/{pk}/')

    satz_roh = (request.POST.get('satz') or '').strip().replace("'", '')
    satz = None
    if satz_roh:
        from decimal import Decimal, InvalidOperation
        try:
            satz = Decimal(satz_roh.replace(',', '.'))
        except InvalidOperation:
            messages.error(request, f'«{satz_roh}» ist kein Betrag.')
            return redirect(f'/neu/faelle/{pk}/')

    Zeiteintrag.objects.create(
        fall=fall, benutzer=request.user, minuten=minuten,
        taetigkeit=request.POST.get('taetigkeit') or Zeiteintrag.SONDER,
        notiz=(request.POST.get('notiz') or '')[:200],
        verrechenbar=bool(request.POST.get('verrechenbar')),
        satz=satz)
    from core.auth import log_aktion
    log_aktion(request, 'Aufwand erfasst', objekt=f'Fall {fall.pk}',
               details=f'{minuten} Min.')
    messages.success(request, f'{minuten} Minuten erfasst.')
    return redirect(f'/neu/faelle/{pk}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_fall_zustaendig(request, pk):
    """Die Zuständigkeit eines Falls wechseln.

    WARUM DAS NOETIG IST

    `Fall.zustaendig` wurde bis E2.70 an GENAU EINER Stelle gesetzt: beim
    Uebernehmen aus dem Posteingang, auf den gerade Anwesenden. Aendern konnte
    man es NIRGENDS — der Filter «Zustaendigkeit» auf «Heute» und das Kuerzel
    in der Zeile zeigten einen Wert, den niemand pflegen konnte.

    Seit E2.70 erbt ein neuer Fall die Betreuung der Liegenschaft. Das deckt
    den Normalfall; dieser Weg deckt den Rest: Ferien, Wechsel,
    Fehlzuordnung.

    JEDER WECHSEL STEHT IM LOGBUCH. Wer spaeter fragt, warum ein Fall bei
    jemand anderem liegt, findet die Antwort — mit altem und neuem Namen.
    """
    from django.contrib import messages

    from core.auth import log_aktion
    # `Fall` wird in dieser Datei sonst nirgends auf Modulebene gebraucht —
    # der Isolationswaechter hat den fehlenden Import beim ersten POST auf
    # eine fremde ID gemeldet, bevor er jemandem im Betrieb begegnet ist.
    from faelle.models import Fall

    fall = get_object_or_404(Fall.objects, pk=pk)
    if request.method != 'POST':
        return redirect(f'/neu/faelle/{pk}/')

    roh = (request.POST.get('zustaendig') or '').strip()
    neu_person = None
    if roh.isdigit():
        # UEBER `Mitgliedschaft`, NICHT UEBER `Benutzer.objects`.
        #
        # Ein erster Entwurf schrieb hier «laeuft durch den `TenantManager`».
        # DAS STIMMT NICHT: `Benutzer` erbt von `AbstractUser` und hat keinen
        # Mandantenfilter — die Zugehoerigkeit laeuft ueber `Mitgliedschaft`,
        # weil ein Mensch in mehreren Verwaltungen arbeiten kann.
        #
        # Der Test dazu hat einen Fall einer FREMDEN Verwaltung zugewiesen.
        # Die Begruendung war aus Etappe 6.2 uebernommen, wo sie richtig ist —
        # eine Begruendung ist nicht uebertragbar, nur weil sie ueberzeugt.
        neu_person = team_der_organisation(
            getattr(request, 'organisation', None)).filter(pk=roh).first()
        if neu_person is None:
            messages.error(request, 'Diese Person gehört nicht zu Ihrer Verwaltung.')
            return redirect(f'/neu/faelle/{pk}/')

    def _name(b):
        return (b.get_full_name() or b.get_username()) if b else 'niemand'

    alt = fall.zustaendig
    if alt == neu_person:
        return redirect(f'/neu/faelle/{pk}/')

    fall.zustaendig = neu_person
    fall.save(update_fields=['zustaendig'])
    # `ziel=fall` — SONST STEHT DER EINTRAG NUR IM LOGBUCH.
    #
    # Mit `ziel` wird er anklickbar und erscheint im Verlauf DES FALLS. Wer
    # fragt, warum ein Fall bei jemand anderem liegt, sucht die Antwort dort
    # und nicht in einer Gesamtliste. Derselbe Fund wie in E2.53.
    log_aktion(request, 'Zuständigkeit geändert', objekt=f'Fall {fall.nummer}',
               details=f'{_name(alt)} → {_name(neu_person)}', ziel=fall)
    messages.success(request, f'Fall liegt jetzt bei {_name(neu_person)}.')
    return redirect(f'/neu/faelle/{pk}/')


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
    from faelle.models import Zeiteintrag
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
        # Fuer den Zustaendigkeitswechsel (E2.70). `SCHREIB_ROLLEN` — die
        # Leserolle sieht den Namen, aendert ihn aber nicht.
        'kann_schreiben': getattr(request, 'rolle', None) in SCHREIB_ROLLEN,
        'benutzer_auswahl': list(team_der_organisation(
            getattr(request, 'organisation', None))[:100]),
        'etappen': etappen,
        'naechster': fall.naechster_schritt,
        'schritte_erledigt': erledigt,
        'schritte_gesamt': gesamt,
        'liegengeblieben': fall.ist_liegengeblieben,
        'tage_ohne_bewegung': fall.tage_ohne_bewegung,
        'zeiteintraege': list(fall.zeiteintraege.select_related('benutzer')
                              .order_by('-datum', '-pk')[:20]),
        'zeit_arten': Zeiteintrag.TAETIGKEITEN,
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
