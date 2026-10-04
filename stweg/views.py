"""Oberfläche des STWEG-Moduls (/neu/stweg/…).

Die Verwaltung führt die Gemeinschaft vollständig hier: Versammlung einberufen,
Einladung versenden, Anwesenheit und Stimmen erfassen, Beschlüsse feststellen,
Protokoll versenden, Anfragen beantworten, Aufgaben abhaken. Fachlogik steht in
den Services (`stweg.versammlung`, `.beschluss`, `.anfragen`, `.aufgaben`); die
Ansichten lesen Eingaben, rufen sie auf und melden das Ergebnis.

Mandantentrennung: Jedes Objekt wird über seinen `TenantManager` geladen
(`get_object_or_404(Modell, pk=…)`). Eine fremde ID findet nichts → 404.
"""
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_POST

from core.auth import SCHREIB_ROLLEN, TEAM_ROLLEN, rolle_erforderlich
from core.models import Pendenz
from portfolio.models import Einheit, Liegenschaft
from stweg import anfragen as anf
from stweg import aufgaben, beschluss
from stweg.models import (Anwesenheit, Stimme, StwegAnfrage, StwegVersand, Traktandum, Versammlung)
from stweg.validierung import WertquotenFehler, pruefe_wertquoten, wertquoten_summe
from stweg.versammlung import (VersammlungsFehler, durchfuehren, einladung_pruefen,
                               einladung_versenden, protokoll_pruefen, protokoll_versenden)


def _gemeinschaft(lg):
    return get_object_or_404(Liegenschaft, pk=lg, typ=Liegenschaft.TYP_STWEG)


def _zurueck(v):
    return redirect(f'/neu/stweg/versammlung/{v.pk}/')


def _fehler(request, fehler):
    probleme = getattr(fehler, 'probleme', None) or [str(fehler)]
    for p in probleme:
        messages.error(request, p)


def _zahl(wert):
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


# ── Übersicht ─────────────────────────────────────────────────────────────

@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_uebersicht(request):
    gemeinschaften = []
    for lg in Liegenschaft.objects.filter(typ=Liegenschaft.TYP_STWEG).order_by('strasse'):
        op = aufgaben.offene_punkte(lg)
        gemeinschaften.append({
            'lg': lg,
            'offen': sum(len(op[k]) for k in ('aufgaben', 'anfragen', 'unentschiedene_traktanden',
                                              'protokoll_ausstehend', 'zustellung_offen')),
            'naechste': (Versammlung.objects.filter(liegenschaft=lg, datum__gte=timezone.now())
                         .order_by('datum').first()),
        })
    return render(request, 'stweg/uebersicht.html', {'nav': 'stweg', 'gemeinschaften': gemeinschaften})


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_gemeinschaft(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    try:
        pruefe_wertquoten(lg)
        quoten_fehler = ''
    except WertquotenFehler as e:
        quoten_fehler = str(e.message)
    return render(request, 'stweg/gemeinschaft.html', {
        'nav': 'stweg', 'lg': lg, 'quoten_fehler': quoten_fehler,
        'quoten_summe': wertquoten_summe(lg),
        'einheiten': lg.einheiten.select_related('stockwerkeigentuemer').order_by('bezeichnung'),
        'versammlungen': Versammlung.objects.filter(liegenschaft=lg),
        'offen': aufgaben.offene_punkte(lg),
        'art_choices': Versammlung.ART_CHOICES,
    })


# ── Versammlung ──────────────────────────────────────────────────────────

@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_versammlung_neu(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    datum = parse_datetime((request.POST.get('datum') or '').strip())
    titel = (request.POST.get('titel') or '').strip()
    if not titel or datum is None:
        messages.error(request, 'Titel und Datum (mit Uhrzeit) sind nötig.')
        return redirect(f'/neu/stweg/{lg.pk}/')
    if timezone.is_naive(datum):
        datum = timezone.make_aware(datum)
    art = request.POST.get('art')
    v = Versammlung.objects.create(
        liegenschaft=lg, titel=titel, datum=datum, ort=(request.POST.get('ort') or '').strip(),
        art=art if art in dict(Versammlung.ART_CHOICES) else 'ordentlich',
        einladungsfrist_tage=_zahl(request.POST.get('einladungsfrist_tage')) or 10)
    messages.success(request, 'Versammlung angelegt. Jetzt Traktanden erfassen.')
    return _zurueck(v)


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_versammlung(request, pk):
    v = get_object_or_404(Versammlung.objects.select_related('liegenschaft'), pk=pk)
    lg = v.liegenschaft
    traktanden = list(v.traktanden.all())
    einheiten = list(lg.einheiten.select_related('stockwerkeigentuemer').order_by('bezeichnung'))
    anw = {a.einheit_id: a for a in v.anwesenheiten.all()}
    for e in einheiten:
        a = anw.get(e.pk)
        e.anwesenheit = a.art if a else Anwesenheit.ABWESEND
        e.vertreter = a.vertreter if a else ''
    for t in traktanden:
        t.zaehlung = beschluss.auswerten(t) if v.status != v.ENTWURF else None
        stimmen = {s.einheit_id: s.wert for s in t.stimmen.all()}
        t.stimmen_je_einheit = [(e, stimmen.get(e.pk, '')) for e in einheiten
                                if e.anwesenheit != Anwesenheit.ABWESEND]
    return render(request, 'stweg/versammlung.html', {
        'nav': 'stweg', 'v': v, 'lg': lg, 'traktanden': traktanden, 'einheiten': einheiten,
        'einladung_probleme': einladung_pruefen(v) if v.status in (v.ENTWURF, v.EINGELADEN) else [],
        'protokoll_probleme': protokoll_pruefen(v),
        'praesenz': beschluss.praesenz(v) if v.status != v.ENTWURF else None,
        'versaende': v.versaende.select_related('eigentuemer'),
        'mehrheiten': Traktandum.MEHRHEIT_CHOICES, 'ergebnisse': Traktandum.ERGEBNIS_CHOICES,
        'anwesenheitsarten': Anwesenheit.ART_CHOICES, 'stimmwerte': Stimme.WERT_CHOICES,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_traktandum_neu(request, pk):
    v = get_object_or_404(Versammlung, pk=pk)
    if v.status != v.ENTWURF:
        messages.error(request, 'Traktanden lassen sich nur ändern, solange die Einladung nicht versendet ist.')
        return _zurueck(v)
    titel = (request.POST.get('titel') or '').strip()
    if not titel:
        messages.error(request, 'Ein Traktandum braucht einen Titel.')
        return _zurueck(v)
    nr = (v.traktanden.order_by('-nr').values_list('nr', flat=True).first() or 0) + 1
    art = request.POST.get('mehrheitsart')
    Traktandum.objects.create(
        versammlung=v, nr=nr, titel=titel,
        beschreibung=(request.POST.get('beschreibung') or '').strip(),
        antrag=(request.POST.get('antrag') or '').strip(),
        mehrheitsart=art if art in dict(Traktandum.MEHRHEIT_CHOICES) else 'einfach_koepfe',
        rechtsgrundlage=(request.POST.get('rechtsgrundlage') or '').strip(),
        vollzug_aufgabe=(request.POST.get('vollzug_aufgabe') or '').strip(),
        vollzug_faellig_am=parse_date(request.POST.get('vollzug_faellig_am') or ''))
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_traktandum_loeschen(request, pk):
    t = get_object_or_404(Traktandum.objects.select_related('versammlung'), pk=pk)
    v = t.versammlung
    if v.status != v.ENTWURF:
        messages.error(request, 'Traktanden lassen sich nur ändern, solange die Einladung nicht versendet ist.')
    else:
        t.delete()
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_einladung_versenden(request, pk):
    v = get_object_or_404(Versammlung, pk=pk)
    try:
        neu = einladung_versenden(v)
    except VersammlungsFehler as e:
        _fehler(request, e)
        return _zurueck(v)
    gesendet = sum(1 for n in neu if n.status == StwegVersand.GESENDET)
    post = sum(1 for n in neu if n.status == StwegVersand.POST)
    fehler = sum(1 for n in neu if n.status == StwegVersand.FEHLER)
    messages.success(request, f'Einladung: {gesendet} per E-Mail versendet.')
    if post:
        messages.warning(request, f'{post} Eigentümer ohne E-Mail-Adresse — Einladung per Post zustellen.')
    if fehler:
        messages.error(request, f'{fehler} Versand(e) fehlgeschlagen — «Einladung versenden» wiederholt nur diese.')
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_durchfuehren(request, pk):
    v = get_object_or_404(Versammlung, pk=pk)
    try:
        durchfuehren(v)
    except VersammlungsFehler as e:
        _fehler(request, e)
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_anwesenheit_speichern(request, pk):
    v = get_object_or_404(Versammlung, pk=pk)
    if v.status != v.DURCHGEFUEHRT:
        messages.error(request, 'Anwesenheit lässt sich nur bei einer durchgeführten Versammlung erfassen.')
        return _zurueck(v)
    for e in v.liegenschaft.einheiten.all():
        art = request.POST.get(f'art_{e.pk}')
        if art in dict(Anwesenheit.ART_CHOICES):
            beschluss.anwesenheit_setzen(v, e, art, (request.POST.get(f'vertreter_{e.pk}') or '').strip())
    for key in ('leitung', 'protokollfuehrung'):
        if key in request.POST:
            setattr(v, key, request.POST[key].strip())
    v.save(update_fields=['leitung', 'protokollfuehrung'])
    messages.success(request, 'Anwesenheit gespeichert.')
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_stimmen_speichern(request, pk):
    t = get_object_or_404(Traktandum.objects.select_related('versammlung'), pk=pk)
    v = t.versammlung
    if v.status != v.DURCHGEFUEHRT:
        messages.error(request, 'Stimmen lassen sich nur bei einer durchgeführten Versammlung erfassen.')
        return _zurueck(v)
    try:
        for e in beschluss.vertretene_einheiten(v):
            wert = request.POST.get(f'stimme_{e.pk}')
            if wert in dict(Stimme.WERT_CHOICES):
                beschluss.stimme_abgeben(t, e, wert)
            elif wert == '':
                Stimme.objects.filter(traktandum=t, einheit=e).delete()
    except beschluss.BeschlussFehler as e:
        _fehler(request, e)
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_beschluss_feststellen(request, pk):
    t = get_object_or_404(Traktandum.objects.select_related('versammlung'), pk=pk)
    v = t.versammlung
    if v.status not in (v.DURCHGEFUEHRT, v.PROTOKOLLIERT):
        messages.error(request, 'Beschlüsse werden nach der Versammlung festgestellt.')
        return _zurueck(v)
    try:
        beschluss.feststellen(t, request.POST.get('ergebnis') or '',
                              beschlusstext=(request.POST.get('beschlusstext') or '').strip(),
                              user=request.user)
        messages.success(request, f'Traktandum {t.nr}: Ergebnis festgestellt.')
    except beschluss.BeschlussFehler as e:
        _fehler(request, e)
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_protokoll_speichern(request, pk):
    v = get_object_or_404(Versammlung, pk=pk)
    v.protokoll_text = (request.POST.get('protokoll_text') or '').strip()
    v.save(update_fields=['protokoll_text'])
    messages.success(request, 'Bemerkungen gespeichert.')
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_protokoll_versenden(request, pk):
    v = get_object_or_404(Versammlung, pk=pk)
    try:
        neu = protokoll_versenden(v)
    except VersammlungsFehler as e:
        _fehler(request, e)
        return _zurueck(v)
    messages.success(request, f'Protokoll an {sum(1 for n in neu if n.status == StwegVersand.GESENDET)} '
                              'Eigentümer versendet.')
    offen = [n for n in neu if n.status != StwegVersand.GESENDET]
    if offen:
        messages.warning(request, f'{len(offen)} Zustellung(en) offen (keine E-Mail-Adresse oder Fehler).')
    return _zurueck(v)


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_pdf(request, pk, art):
    """Einladung (Vorschau ohne Adressat) oder Protokoll als PDF."""
    from stweg.pdf import einladung_pdf, protokoll_pdf
    v = get_object_or_404(Versammlung, pk=pk)
    if art == 'einladung':
        inhalt = einladung_pdf(v)
    elif art == 'protokoll':
        inhalt = protokoll_pdf(v)
    else:
        return HttpResponse(status=404)
    antwort = HttpResponse(inhalt, content_type='application/pdf')
    antwort['Content-Disposition'] = f'inline; filename="{art}_{v.datum:%Y%m%d}.pdf"'
    return antwort


# ── Anfragen und Aufgaben ────────────────────────────────────────────────

@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_anfrage_neu(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    betreff = (request.POST.get('betreff') or '').strip()
    if not betreff:
        messages.error(request, 'Die Anfrage braucht einen Betreff.')
        return redirect(f'/neu/stweg/{lg.pk}/')
    einheit = None
    if _zahl(request.POST.get('einheit')):
        einheit = Einheit.objects.filter(pk=_zahl(request.POST['einheit']), liegenschaft=lg).first()
    kanal = request.POST.get('kanal')
    anf.anfrage_erfassen(
        lg, betreff, (request.POST.get('text') or '').strip(), einheit=einheit,
        kanal=kanal if kanal in dict(StwegAnfrage.KANAL_CHOICES) else 'telefon',
        faellig_am=parse_date(request.POST.get('faellig_am') or ''), user=request.user)
    messages.success(request, 'Anfrage erfasst.')
    return redirect(f'/neu/stweg/{lg.pk}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_anfrage_beantworten(request, pk):
    a = get_object_or_404(StwegAnfrage, pk=pk)
    try:
        gesendet = anf.beantworten(a, request.POST.get('antwort') or '')
        messages.success(request, 'Antwort gespeichert' + (' und per E-Mail versendet.' if gesendet
                                                           else ' (keine E-Mail versendet).'))
    except anf.AnfrageFehler as e:
        _fehler(request, e)
    return redirect(f'/neu/stweg/{a.liegenschaft_id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_anfrage_erledigt(request, pk):
    a = get_object_or_404(StwegAnfrage, pk=pk)
    anf.erledigt(a)
    return redirect(f'/neu/stweg/{a.liegenschaft_id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_aufgabe_neu(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    titel = (request.POST.get('titel') or '').strip()
    if not titel:
        messages.error(request, 'Die Aufgabe braucht einen Titel.')
    else:
        aufgaben.aufgabe_erfassen(lg, titel, faellig_am=parse_date(request.POST.get('faellig_am') or ''),
                                  user=request.user)
    return redirect(f'/neu/stweg/{lg.pk}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_aufgabe_erledigt(request, pk):
    p = get_object_or_404(Pendenz, pk=pk, quelle__startswith=aufgaben.PREFIX)
    aufgaben.erledigen(p)
    return redirect(f'/neu/stweg/{p.liegenschaft_id}/')
