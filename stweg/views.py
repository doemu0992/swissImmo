"""Oberfläche des STWEG-Moduls (/neu/stweg/…).

Die Verwaltung führt die Gemeinschaft vollständig hier: Versammlung einberufen,
Einladung versenden, Anwesenheit und Stimmen erfassen, Beschlüsse feststellen,
Protokoll versenden, Anfragen beantworten, Aufgaben abhaken. Fachlogik steht in
den Services (`stweg.versammlung`, `.beschluss`, `.anfragen`, `.aufgaben`); die
Ansichten lesen Eingaben, rufen sie auf und melden das Ergebnis.

Mandantentrennung: Jedes Objekt wird über seinen `TenantManager` geladen
(`get_object_or_404(Modell, pk=…)`). Eine fremde ID findet nichts → 404.
"""
from django.utils.translation import gettext
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_POST

from core.auth import SCHREIB_ROLLEN, TEAM_ROLLEN, rolle_erforderlich
from core.models import Pendenz
from portfolio.models import Einheit, Liegenschaft
from stweg import anfragen as anf
from stweg import aufgaben, beschluss, dokumente, vorgaben
from stweg.models import (Anwesenheit, Stimme, StwegAbrechnung, StwegBudget, StwegAkonto, StwegAnfrage,
                          StwegVersand, Traktandum, Versammlung, Vollmacht, Zirkularbeschluss,
                          ZirkularStimme)
from stweg.beschluss import BeschlussFehler
from stweg.validierung import WertquotenFehler, pruefe_wertquoten, stimm_einheiten, wertquoten_summe
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
                                              'protokoll_ausstehend', 'zustellung_offen',
                                              'zirkulare_offen', 'zirkular_ergebnis_ausstehend')),
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
        'einheiten': stimm_einheiten(lg).select_related('stockwerkeigentuemer').order_by('bezeichnung'),
        'versammlungen': Versammlung.objects.filter(liegenschaft=lg),
        'zirkulare': Zirkularbeschluss.objects.filter(liegenschaft=lg),
        'mehrheiten': Traktandum.MEHRHEIT_CHOICES,
        'offen': aufgaben.offene_punkte(lg),
        'art_choices': Versammlung.ART_CHOICES,
        'dokument_luecken': dokumente.luecken(lg),
        'vorgaben_unbestaetigt': not vorgaben.ist_bestaetigt(lg),
        'frist_vorgabe': vorgaben.einladungsfrist_vorgabe(lg),
        'budgets_vorgelegt': StwegBudget.objects.filter(liegenschaft=lg, status__in=('entwurf', 'vorgelegt')),
    })


# ── Versammlung ──────────────────────────────────────────────────────────

@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_versammlung_neu(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    datum = parse_datetime((request.POST.get('datum') or '').strip())
    titel = (request.POST.get('titel') or '').strip()
    if not titel or datum is None:
        messages.error(request, gettext('Titel und Datum (mit Uhrzeit) sind nötig.'))
        return redirect(f'/neu/stweg/{lg.pk}/')
    if timezone.is_naive(datum):
        datum = timezone.make_aware(datum)
    art = request.POST.get('art')
    v = Versammlung.objects.create(
        liegenschaft=lg, titel=titel, datum=datum, ort=(request.POST.get('ort') or '').strip(),
        art=art if art in dict(Versammlung.ART_CHOICES) else 'ordentlich',
        einladungsfrist_tage=_zahl(request.POST.get('einladungsfrist_tage'))
        or vorgaben.einladungsfrist_vorgabe(lg),
        evoting=bool(request.POST.get('evoting')))
    messages.success(request, gettext('Versammlung angelegt. Jetzt Traktanden erfassen.'))
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_versammlung_evoting(request, pk):
    v = get_object_or_404(Versammlung, pk=pk)
    if v.status == v.PROTOKOLLIERT:
        messages.error(request, gettext('Das Protokoll ist versendet — E-Voting lässt sich nicht mehr ändern.'))
        return _zurueck(v)
    bis = parse_datetime((request.POST.get('evoting_bis') or '').strip())
    if bis is not None and timezone.is_naive(bis):
        bis = timezone.make_aware(bis)
    v.evoting = bool(request.POST.get('evoting'))
    v.evoting_bis = bis if v.evoting else None
    v.save(update_fields=['evoting', 'evoting_bis'])
    messages.success(request, gettext('E-Voting ist eingeschaltet.') if v.evoting else gettext('E-Voting ist ausgeschaltet.'))
    return _zurueck(v)


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_versammlung(request, pk):
    v = get_object_or_404(Versammlung.objects.select_related('liegenschaft'), pk=pk)
    lg = v.liegenschaft
    traktanden = list(v.traktanden.all())
    einheiten = list(stimm_einheiten(lg).select_related('stockwerkeigentuemer').order_by('bezeichnung'))
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
        'vollmachten': v.vollmachten.select_related('einheit').order_by('-erteilt_am'),
        'beschlussfaehigkeit': vorgaben.beschlussfaehigkeit(v) if v.status != v.ENTWURF else None,
        'anfechtungsfrist_bis': vorgaben.anfechtungsfrist_bis(v),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_traktandum_neu(request, pk):
    v = get_object_or_404(Versammlung, pk=pk)
    if v.status != v.ENTWURF:
        messages.error(request, gettext('Traktanden lassen sich nur ändern, solange die Einladung nicht versendet ist.'))
        return _zurueck(v)
    titel = (request.POST.get('titel') or '').strip()
    if not titel:
        messages.error(request, gettext('Ein Traktandum braucht einen Titel.'))
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
        messages.error(request, gettext('Traktanden lassen sich nur ändern, solange die Einladung nicht versendet ist.'))
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
    messages.success(request, gettext('Einladung: %(gesendet)s per E-Mail versendet.') % {'gesendet': gesendet})
    if post:
        messages.warning(request, gettext('%(post)s Eigentümer ohne E-Mail-Adresse — Einladung per Post zustellen.') % {'post': post})
    if fehler:
        messages.error(request, gettext('%(fehler)s Versand(e) fehlgeschlagen — «Einladung versenden» wiederholt nur diese.') % {'fehler': fehler})
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
        messages.error(request, gettext('Anwesenheit lässt sich nur bei einer durchgeführten Versammlung erfassen.'))
        return _zurueck(v)
    for e in stimm_einheiten(v.liegenschaft):
        art = request.POST.get(f'art_{e.pk}')
        if art in dict(Anwesenheit.ART_CHOICES):
            beschluss.anwesenheit_setzen(v, e, art, (request.POST.get(f'vertreter_{e.pk}') or '').strip())
    for key in ('leitung', 'protokollfuehrung'):
        if key in request.POST:
            setattr(v, key, request.POST[key].strip())
    v.save(update_fields=['leitung', 'protokollfuehrung'])
    messages.success(request, gettext('Anwesenheit gespeichert.'))
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_stimmen_speichern(request, pk):
    t = get_object_or_404(Traktandum.objects.select_related('versammlung'), pk=pk)
    v = t.versammlung
    if v.status != v.DURCHGEFUEHRT:
        messages.error(request, gettext('Stimmen lassen sich nur bei einer durchgeführten Versammlung erfassen.'))
        return _zurueck(v)
    try:
        for e in beschluss.vertretene_einheiten(v):
            wert = request.POST.get(f'stimme_{e.pk}')
            if wert in dict(Stimme.WERT_CHOICES):
                beschluss.stimme_abgeben(t, e, wert)
            elif wert == '':
                beschluss.stimme_loeschen(t, e)
    except beschluss.BeschlussFehler as e:
        _fehler(request, e)
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_beschluss_feststellen(request, pk):
    t = get_object_or_404(Traktandum.objects.select_related('versammlung'), pk=pk)
    v = t.versammlung
    if v.status not in (v.DURCHGEFUEHRT, v.PROTOKOLLIERT):
        messages.error(request, gettext('Beschlüsse werden nach der Versammlung festgestellt.'))
        return _zurueck(v)
    try:
        beschluss.feststellen(t, request.POST.get('ergebnis') or '',
                              beschlusstext=(request.POST.get('beschlusstext') or '').strip(),
                              user=request.user, trotzdem=bool(request.POST.get('trotzdem')))
        messages.success(request, gettext('Traktandum %(nr)s: Ergebnis festgestellt.') % {'nr': t.nr})
    except beschluss.BeschlussFehler as e:
        _fehler(request, e)
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_protokoll_speichern(request, pk):
    v = get_object_or_404(Versammlung, pk=pk)
    v.protokoll_text = (request.POST.get('protokoll_text') or '').strip()
    v.save(update_fields=['protokoll_text'])
    messages.success(request, gettext('Bemerkungen gespeichert.'))
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
    messages.success(request, gettext('Protokoll an %(wert)s Eigentümer versendet.') % {'wert': sum(1 for n in neu if n.status == StwegVersand.GESENDET)})
    offen = [n for n in neu if n.status != StwegVersand.GESENDET]
    if offen:
        messages.warning(request, gettext('%(wert)s Zustellung(en) offen (keine E-Mail-Adresse oder Fehler).') % {'wert': len(offen)})
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
        messages.error(request, gettext('Die Anfrage braucht einen Betreff.'))
        return redirect(f'/neu/stweg/{lg.pk}/')
    einheit = None
    if _zahl(request.POST.get('einheit')):
        einheit = Einheit.objects.filter(pk=_zahl(request.POST['einheit']), liegenschaft=lg).first()
    kanal = request.POST.get('kanal')
    anf.anfrage_erfassen(
        lg, betreff, (request.POST.get('text') or '').strip(), einheit=einheit,
        kanal=kanal if kanal in dict(StwegAnfrage.KANAL_CHOICES) else 'telefon',
        faellig_am=parse_date(request.POST.get('faellig_am') or ''), user=request.user)
    messages.success(request, gettext('Anfrage erfasst.'))
    return redirect(f'/neu/stweg/{lg.pk}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_anfrage_beantworten(request, pk):
    a = get_object_or_404(StwegAnfrage, pk=pk)
    try:
        gesendet = anf.beantworten(a, request.POST.get('antwort') or '')
        messages.success(request, gettext('Antwort gespeichert und per E-Mail versendet.') if gesendet
                         else gettext('Antwort gespeichert (keine E-Mail versendet).'))
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
        messages.error(request, gettext('Die Aufgabe braucht einen Titel.'))
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


# ── Abrechnung, Akonto, Erneuerungsfonds ─────────────────────────────────

def _betrag(wert):
    """Beträge aus dem Formular: «1'234.50», «1234,5» — sonst None."""
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal((wert or '').strip().replace("'", '').replace(',', '.')).quantize(Decimal('0.01'))
    except InvalidOperation:
        return None


def _jahr(wert):
    j = _zahl(wert)
    return j if j and 1990 <= j <= 2100 else None


def _zur_abrechnung(lg, jahr=None):
    return redirect(f'/neu/stweg/{lg.pk}/abrechnung/' + (f'?jahr={jahr}' if jahr else ''))


def _geparkte_eingaenge():
    """Importierte, noch nicht zugeordnete Bankeingänge (Durchlaufkonto 1190), die zu einer Zahlung
    zugeordnet werden können."""
    from finance.models import Zahlungseingang
    vergeben = StwegAkonto.objects.exclude(zahlungseingang__isnull=True).values_list('zahlungseingang_id', flat=True)
    return list(Zahlungseingang.objects.filter(status='verbucht', konto__nummer='1190')
                .exclude(pk__in=vergeben).order_by('-datum_eingang')[:50])


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_abrechnung(request, stweg_id):
    from finance.models import Erneuerungsfonds
    from stweg.services import StwegAbrechnungService
    lg = _gemeinschaft(stweg_id)
    jahr = _jahr(request.GET.get('jahr')) or timezone.localdate().year - 1
    abrechnung = (StwegAbrechnung.objects.filter(liegenschaft=lg, jahr=jahr)
                  .prefetch_related('positionen__einheit', 'positionen__eigentuemer', 'kostenzeilen').first())
    service = StwegAbrechnungService(lg)
    einheiten = list(stimm_einheiten(lg).select_related('stockwerkeigentuemer').order_by('bezeichnung'))
    akonto = service.akonto_je_einheit(jahr)
    for e in einheiten:
        e.akonto_summe = akonto.get(e.pk, 0)
    # Lesen legt nichts an: den Fonds gibt es erst mit der ersten Einlage.
    fonds = Erneuerungsfonds.objects.filter(liegenschaft=lg).first()
    return render(request, 'stweg/abrechnung.html', {
        'nav': 'stweg', 'lg': lg, 'jahr': jahr, 'abrechnung': abrechnung, 'einheiten': einheiten,
        'vorschau': None if abrechnung else service.kostenzeilen(jahr),
        'vorschau_total': None if abrechnung else service.allgemeine_kosten(jahr),
        'akontos': StwegAkonto.objects.filter(einheit__liegenschaft=lg, datum__year=jahr)
        .select_related('einheit'),
        'fonds': fonds,
        'geparkt': _geparkte_eingaenge(),
        'zwecke': StwegAkonto.ZWECK_CHOICES,
        'bewegungen': list(fonds.bewegungen.select_related('einheit').order_by('-datum', '-id')[:30]) if fonds else [],
        'eigentuemer': sorted({p.eigentuemer for p in abrechnung.positionen.all() if p.eigentuemer},
                              key=lambda x: x.firma_oder_name) if abrechnung else [],
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_abrechnung_berechnen(request, stweg_id):
    from stweg.services import AbrechnungsFehler, StwegAbrechnungService
    lg = _gemeinschaft(stweg_id)
    jahr = _jahr(request.POST.get('jahr'))
    if jahr is None:
        messages.error(request, gettext('Bitte ein Jahr angeben.'))
        return _zur_abrechnung(lg)
    try:
        StwegAbrechnungService(lg).abrechnen(jahr)
        messages.success(request, gettext('Abrechnung %(jahr)s berechnet.') % {'jahr': jahr})
    except (AbrechnungsFehler, WertquotenFehler) as e:
        messages.error(request, str(getattr(e, 'message', None) or e))
    return _zur_abrechnung(lg, jahr)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_abrechnung_abschliessen(request, pk):
    from stweg.services import StwegAbrechnungService
    a = get_object_or_404(StwegAbrechnung.objects.select_related('liegenschaft'), pk=pk)
    from stweg.services import AbrechnungsFehler
    try:
        StwegAbrechnungService.abschliessen(a, user=request.user)
        messages.success(request, gettext('Abrechnung %(jahr)s abgeschlossen und ins Hauptbuch gebucht.') % {'jahr': a.jahr})
    except AbrechnungsFehler as e:
        messages.error(request, str(e))
    return _zur_abrechnung(a.liegenschaft, a.jahr)


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_abrechnung_pdf(request, pk):
    from crm.models import Eigentuemer
    from stweg.pdf import abrechnung_pdf
    a = get_object_or_404(StwegAbrechnung.objects.select_related('liegenschaft'), pk=pk)
    eig = None
    if request.GET.get('eigentuemer'):
        eig = get_object_or_404(Eigentuemer, pk=_zahl(request.GET['eigentuemer']) or 0)
    antwort = HttpResponse(abrechnung_pdf(a, eig), content_type='application/pdf')
    antwort['Content-Disposition'] = f'inline; filename="Abrechnung_{a.jahr}.pdf"'
    return antwort


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_akonto_neu(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    einheit = Einheit.objects.filter(pk=_zahl(request.POST.get('einheit')) or 0, liegenschaft=lg).first()
    betrag = _betrag(request.POST.get('betrag'))
    datum = parse_date(request.POST.get('datum') or '') or timezone.localdate()
    if einheit is None or betrag is None or betrag <= 0:
        messages.error(request, gettext('Einheit und ein Betrag grösser 0 sind nötig.'))
        return _zur_abrechnung(lg)
    from finance.models import Zahlungseingang
    from stweg import hauptbuch
    zweck = request.POST.get('zweck') if request.POST.get('zweck') in dict(StwegAkonto.ZWECK_CHOICES) \
        else StwegAkonto.AKONTO
    ze = None
    if request.POST.get('zahlungseingang'):
        ze = Zahlungseingang.objects.filter(pk=_zahl(request.POST.get('zahlungseingang')) or 0).first()
        if ze is None:
            messages.error(request, gettext('Der gewählte Bankeingang wurde nicht gefunden.'))
            return _zur_abrechnung(lg, datum.year)
    try:
        with transaction.atomic():
            k = StwegAkonto.objects.create(einheit=einheit, betrag=betrag, datum=datum, zweck=zweck,
                                           zahlungseingang=ze,
                                           bemerkung=(request.POST.get('bemerkung') or '').strip()[:200])
            hauptbuch.zahlung_buchen(k, user=request.user)
    except hauptbuch.HauptbuchFehler as e:
        messages.error(request, str(e))
        return _zur_abrechnung(lg, datum.year)
    messages.success(request, gettext('%(wert)s CHF %(betrag)s für %(bezeichnung)s erfasst und gebucht.') % {'wert': k.get_zweck_display(), 'betrag': betrag, 'bezeichnung': einheit.bezeichnung})
    return _zur_abrechnung(lg, datum.year)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_akonto_loeschen(request, pk):
    k = get_object_or_404(StwegAkonto.objects.select_related('einheit__liegenschaft'), pk=pk)
    lg, jahr = k.einheit.liegenschaft, k.datum.year
    from stweg import hauptbuch
    if k.zweck == StwegAkonto.AKONTO and StwegAbrechnung.objects.filter(
            liegenschaft=lg, jahr=jahr, status=StwegAbrechnung.STATUS_ABGESCHLOSSEN).exists():
        messages.error(request, gettext('Die Abrechnung %(jahr)s ist abgeschlossen — Akonto lässt sich nicht mehr ändern.') % {'jahr': jahr})
    else:
        try:
            with transaction.atomic():
                hauptbuch.zahlung_stornieren(k, user=request.user)     # Gegenbuchung, nichts wird überschrieben
                k.delete()
        except hauptbuch.HauptbuchFehler as e:
            messages.error(request, str(e))
    return _zur_abrechnung(lg, jahr)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_fonds_einlage(request, stweg_id):
    from stweg.fonds import FondsFehler, jahreseinlage_belasten
    lg = _gemeinschaft(stweg_id)
    jahr, betrag = _jahr(request.POST.get('jahr')), _betrag(request.POST.get('betrag'))
    if jahr is None or betrag is None:
        messages.error(request, gettext('Jahr und Betrag sind nötig.'))
        return _zur_abrechnung(lg)
    try:
        verteilt = jahreseinlage_belasten(lg, jahr, betrag, user=request.user)
        messages.success(request, gettext('Einlage %(jahr)s: CHF %(betrag)s auf %(wert)s Einheiten verteilt.') % {'jahr': jahr, 'betrag': betrag, 'wert': len(verteilt)})
    except (FondsFehler, WertquotenFehler) as e:
        messages.error(request, str(getattr(e, 'message', None) or e))
    return _zur_abrechnung(lg, jahr)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_fonds_entnahme(request, stweg_id):
    from stweg.fonds import FondsFehler, entnahme_buchen
    lg = _gemeinschaft(stweg_id)
    jahr, betrag = _jahr(request.POST.get('jahr')), _betrag(request.POST.get('betrag'))
    text = (request.POST.get('text') or '').strip()
    if jahr is None or betrag is None or not text:
        messages.error(request, gettext('Jahr, Betrag und Verwendungszweck sind nötig.'))
        return _zur_abrechnung(lg)
    try:
        entnahme_buchen(lg, jahr, betrag, text, user=request.user)
        messages.success(request, gettext('Entnahme CHF %(betrag)s gebucht.') % {'betrag': betrag})
    except (FondsFehler, WertquotenFehler) as e:
        messages.error(request, str(getattr(e, 'message', None) or e))
    return _zur_abrechnung(lg, jahr)


# ── Vollmachten ──────────────────────────────────────────────────────────

@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_vollmacht_neu(request, pk):
    from stweg.vollmacht import VollmachtFehler, erteilen
    v = get_object_or_404(Versammlung, pk=pk)
    einheit = Einheit.objects.filter(pk=_zahl(request.POST.get('einheit')) or 0,
                                     liegenschaft=v.liegenschaft).first()
    if einheit is None:
        messages.error(request, gettext('Bitte eine Einheit wählen.'))
        return _zurueck(v)
    try:
        erteilen(v, einheit, request.POST.get('bevollmaechtigter'), kanal='verwaltung',
                 dokument=request.FILES.get('dokument'))
        messages.success(request, gettext('Vollmacht für %(bezeichnung)s erfasst.') % {'bezeichnung': einheit.bezeichnung})
    except VollmachtFehler as e:
        _fehler(request, e)
    return _zurueck(v)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_vollmacht_dokument(request, pk):
    from stweg.vollmacht import VollmachtFehler, dokument_anhaengen
    vm = get_object_or_404(Vollmacht.objects.select_related('versammlung'), pk=pk)
    if not request.FILES.get('dokument'):
        messages.error(request, gettext('Keine Datei ausgewählt.'))
        return _zurueck(vm.versammlung)
    try:
        dokument_anhaengen(vm, request.FILES['dokument'])
        messages.success(request, gettext('Scan der Vollmacht abgelegt.'))
    except VollmachtFehler as e:
        _fehler(request, e)
    return _zurueck(vm.versammlung)


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_vollmacht_datei(request, pk):
    from stweg.views_dokumente import datei_antwort
    vm = get_object_or_404(Vollmacht, pk=pk)
    if not vm.dokument:
        raise Http404
    return datei_antwort(vm, feld='dokument')


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_vollmacht_widerrufen(request, pk):
    from stweg.vollmacht import VollmachtFehler, widerrufen
    vm = get_object_or_404(Vollmacht.objects.select_related('versammlung'), pk=pk)
    try:
        widerrufen(vm)
    except VollmachtFehler as e:
        _fehler(request, e)
    return _zurueck(vm.versammlung)


# ── Zirkularbeschlüsse ───────────────────────────────────────────────────

def _zirkular_zurueck(z):
    return redirect(f'/neu/stweg/zirkular/{z.pk}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_zirkular_neu(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    titel = (request.POST.get('titel') or '').strip()
    antrag = (request.POST.get('antrag') or '').strip()
    frist = parse_date(request.POST.get('frist_bis') or '')
    if not titel or not antrag or frist is None:
        messages.error(request, gettext('Titel, Antrag und Abstimmungsfrist sind nötig.'))
        return redirect(f'/neu/stweg/{lg.pk}/')
    art = request.POST.get('mehrheitsart')
    z = Zirkularbeschluss.objects.create(
        liegenschaft=lg, titel=titel[:200], antrag=antrag,
        begruendung=(request.POST.get('begruendung') or '').strip(), frist_bis=frist,
        mehrheitsart=art if art in dict(Traktandum.MEHRHEIT_CHOICES) and art not in ('kenntnisnahme', 'doppelt_anwesende') else 'einstimmig',
        rechtsgrundlage=(request.POST.get('rechtsgrundlage') or '').strip()[:200],
        vollzug_aufgabe=(request.POST.get('vollzug_aufgabe') or '').strip()[:200],
        vollzug_faellig_am=parse_date(request.POST.get('vollzug_faellig_am') or ''))
    budget_pk = _zahl(request.POST.get('budget'))
    if budget_pk:
        from stweg import budget as bd
        b = StwegBudget.objects.filter(pk=budget_pk, liegenschaft=lg).first()
        try:
            if b is None:
                raise bd.BudgetFehler('Budget nicht gefunden.')
            bd.an_zirkular_haengen(z, b)
        except bd.BudgetFehler as e:
            messages.error(request, gettext('Zirkularbeschluss angelegt, aber ohne Budget: %(e)s') % {'e': e})
            return _zirkular_zurueck(z)
    messages.success(request, gettext('Zirkularbeschluss angelegt. Prüfen und versenden.'))
    return _zirkular_zurueck(z)


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_zirkular(request, pk):
    from stweg import zirkular as zk
    z = get_object_or_404(Zirkularbeschluss.objects.select_related('liegenschaft'), pk=pk)
    einheiten = list(stimm_einheiten(z.liegenschaft).select_related('stockwerkeigentuemer').order_by('bezeichnung'))
    stimmen = {s.einheit_id: s for s in z.stimmen.all()}
    for e in einheiten:
        e.stimme = stimmen.get(e.pk)
    return render(request, 'stweg/zirkular.html', {
        'nav': 'stweg', 'z': z, 'lg': z.liegenschaft, 'einheiten': einheiten,
        'probleme': zk.pruefen(z) if z.status in (z.ENTWURF, z.LAUFEND) else [],
        'zaehlung': zk.auswerten(z) if z.status != z.ENTWURF else None,
        'vollstaendig': zk.vollstaendig(z), 'frist_vorbei': timezone.localdate() > z.frist_bis,
        'versaende': z.versaende.select_related('eigentuemer'),
        'stimmwerte': Stimme.WERT_CHOICES,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_zirkular_versenden(request, pk):
    from stweg import zirkular as zk
    z = get_object_or_404(Zirkularbeschluss, pk=pk)
    try:
        neu = zk.versenden(z)
    except VersammlungsFehler as e:
        _fehler(request, e)
        return _zirkular_zurueck(z)
    messages.success(request, gettext('Antrag: %(wert)s per E-Mail versendet.') % {'wert': sum(1 for n in neu if n.status == "gesendet")})
    offen = [n for n in neu if n.status != 'gesendet']
    if offen:
        messages.warning(request, gettext('%(wert)s Zustellung(en) offen (keine E-Mail-Adresse oder Fehler).') % {'wert': len(offen)})
    return _zirkular_zurueck(z)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_zirkular_stimmen(request, pk):
    from stweg import zirkular as zk
    z = get_object_or_404(Zirkularbeschluss.objects.select_related('liegenschaft'), pk=pk)
    try:
        for e in stimm_einheiten(z.liegenschaft):
            wert = request.POST.get(f'stimme_{e.pk}')
            if wert in dict(Stimme.WERT_CHOICES):
                zk.stimme_abgeben(z, e, wert, kanal='verwaltung')
            elif wert == '':
                if z.status == z.LAUFEND:
                    ZirkularStimme.objects.filter(zirkular=z, einheit=e).delete()
    except BeschlussFehler as e:
        _fehler(request, e)
    return _zirkular_zurueck(z)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_zirkular_feststellen(request, pk):
    from stweg import zirkular as zk
    z = get_object_or_404(Zirkularbeschluss, pk=pk)
    try:
        zk.feststellen(z, request.POST.get('ergebnis') or '',
                       beschlusstext=(request.POST.get('beschlusstext') or '').strip(), user=request.user)
        messages.success(request, gettext('Ergebnis festgestellt.'))
    except BeschlussFehler as e:
        _fehler(request, e)
    return _zirkular_zurueck(z)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_zirkular_ergebnis(request, pk):
    from stweg import zirkular as zk
    z = get_object_or_404(Zirkularbeschluss, pk=pk)
    try:
        neu = zk.ergebnis_versenden(z)
        messages.success(request, gettext('Ergebnis an %(wert)s Eigentümer versendet.') % {'wert': sum(1 for n in neu if n.status == "gesendet")})
    except VersammlungsFehler as e:
        _fehler(request, e)
    return _zirkular_zurueck(z)


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_zirkular_pdf(request, pk):
    from stweg.pdf import zirkular_pdf
    z = get_object_or_404(Zirkularbeschluss.objects.select_related('liegenschaft'), pk=pk)
    antwort = HttpResponse(zirkular_pdf(z), content_type='application/pdf')
    antwort['Content-Disposition'] = f'inline; filename="Zirkular_{z.pk}.pdf"'
    return antwort


# ── Einheiten und Eigentümer einer Gemeinschaft ──────────────────────────

def _quote(wert):
    """Wertquote aus dem Formular: «200», «12,5» — nicht negativ, höchstens 99999.99."""
    from decimal import Decimal, InvalidOperation
    try:
        q = Decimal((wert or '').strip().replace("'", '').replace(',', '.')).quantize(Decimal('0.01'))
    except InvalidOperation:
        return None
    return q if 0 <= q <= Decimal('99999.99') else None


def _zur_einheitenseite(lg):
    return redirect(f'/neu/stweg/{lg.pk}/einheiten/')


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_einheiten(request, stweg_id):
    from crm.models import Eigentuemer
    lg = _gemeinschaft(stweg_id)
    haupt = list(stimm_einheiten(lg).select_related('stockwerkeigentuemer')
                 .prefetch_related('miteigentuemer').order_by('bezeichnung'))
    for e in haupt:
        e.mit_ids = {m.pk for m in e.miteigentuemer.all()}
    neben = list(lg.einheiten.filter(gehoert_zu__isnull=False).select_related('gehoert_zu').order_by('bezeichnung'))
    summe = wertquoten_summe(lg)
    return render(request, 'stweg/einheiten.html', {
        'nav': 'stweg', 'lg': lg, 'einheiten': haupt, 'nebenraeume': neben,
        'summe': summe, 'passt': summe == lg.wertquote_total,
        'eigentuemer': Eigentuemer.objects.all().order_by('firma_oder_name'),
        'ohne_eigentuemer': sum(1 for e in haupt if e.stockwerkeigentuemer_id is None),
        'sprachen': [('de', 'Deutsch'), ('fr', 'Französisch'), ('it', 'Italienisch'), ('en', 'Englisch')],
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_einheiten_speichern(request, stweg_id):
    """Alle Quoten und Eigentümer in einem Zug — oder nichts: Eine ungültige Eingabe
    verwirft die ganze Seite, damit keine halb geänderte Verteilung entsteht."""
    from django.db import transaction

    from crm.models import Eigentuemer
    lg = _gemeinschaft(stweg_id)
    fehler = []
    aenderungen = []
    for e in stimm_einheiten(lg):
        roh = request.POST.get(f'quote_{e.pk}')
        quote = e.wertquote if roh is None else _quote(roh)
        if quote is None:
            fehler.append(f'«{e.bezeichnung}»: Die Wertquote «{roh}» ist ungültig.')
            continue
        mit = None                       # None = unverändert
        if f'mit_set_{e.pk}' in request.POST:
            ids = {int(x) for x in request.POST.getlist(f'mit_{e.pk}') if x.isdigit()}
            mit = list(Eigentuemer.objects.filter(pk__in=ids))
            if len(mit) != len(ids):
                fehler.append(f'«{e.bezeichnung}»: Ein Miteigentümer ist nicht (mehr) erfasst.')
                continue
        eig = e.stockwerkeigentuemer
        if f'eig_{e.pk}' in request.POST:
            wert = request.POST[f'eig_{e.pk}']
            if wert == '':
                eig = None
            else:
                eig = Eigentuemer.objects.filter(pk=_zahl(wert) or 0).first()
                if eig is None:
                    fehler.append(f'«{e.bezeichnung}»: Dieser Eigentümer ist nicht (mehr) erfasst.')
                    continue
        aenderungen.append((e, quote, eig, mit))
    if fehler:
        for f in fehler:
            messages.error(request, f)
        return _zur_einheitenseite(lg)
    with transaction.atomic():
        for e, quote, eig, mit in aenderungen:
            e.wertquote, e.stockwerkeigentuemer = quote, eig
            e.save(update_fields=['wertquote', 'stockwerkeigentuemer'])
            if mit is not None:
                # Die Hauptansprechperson ist nie zugleich Miteigentümer.
                e.miteigentuemer.set([m for m in mit if m.pk != (eig.pk if eig else None)])
    messages.success(request, gettext('Einheiten gespeichert.'))
    return _zur_einheitenseite(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_einheit_neu(request, stweg_id):
    from crm.models import Eigentuemer
    lg = _gemeinschaft(stweg_id)
    bezeichnung = (request.POST.get('bezeichnung') or '').strip()
    quote = _quote(request.POST.get('wertquote') or '0')
    if not bezeichnung or quote is None:
        messages.error(request, gettext('Bezeichnung und eine gültige Wertquote sind nötig.'))
        return _zur_einheitenseite(lg)
    eig = None
    if request.POST.get('eigentuemer'):
        eig = Eigentuemer.objects.filter(pk=_zahl(request.POST['eigentuemer']) or 0).first()
        if eig is None:
            messages.error(request, gettext('Dieser Eigentümer ist nicht (mehr) erfasst.'))
            return _zur_einheitenseite(lg)
    Einheit.objects.create(liegenschaft=lg, bezeichnung=bezeichnung[:50], typ='stwe', wertquote=quote,
                           etage=(request.POST.get('etage') or '').strip()[:50], stockwerkeigentuemer=eig)
    messages.success(request, gettext('Einheit «%(bezeichnung)s» angelegt.') % {'bezeichnung': bezeichnung})
    return _zur_einheitenseite(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_eigentuemer_neu(request, stweg_id):
    """Einen Stockwerkeigentümer erfassen, ohne die Seite zu verlassen."""
    from crm.models import Eigentuemer
    lg = _gemeinschaft(stweg_id)
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, gettext('Der Name des Eigentümers fehlt.'))
        return _zur_einheitenseite(lg)
    sprache = request.POST.get('sprache')
    Eigentuemer.objects.create(
        firma_oder_name=name[:100], email=(request.POST.get('email') or '').strip()[:254],
        sprache=sprache if sprache in ('de', 'fr', 'it', 'en') else 'de')
    messages.success(request, gettext('Eigentümer «%(name)s» erfasst — jetzt einer Einheit zuteilen.') % {'name': name})
    return _zur_einheitenseite(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_aktivieren(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    lg.status = lg.STATUS_AKTIV
    try:
        lg.save()
        messages.success(request, gettext('Die Gemeinschaft ist aktiv: Einladung, Abstimmung und Abrechnung sind freigegeben.'))
    except WertquotenFehler as e:
        messages.error(request, str(e.message))
    return _zur_einheitenseite(lg)


# ── Vorgaben der Gemeinschaft ────────────────────────────────────────────

@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_vorgaben(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    return render(request, 'stweg/vorgaben.html', {
        'nav': 'stweg', 'lg': lg, 'v': vorgaben.vorgaben_von(lg), 'system_frist': vorgaben.SYSTEM_EINLADUNGSFRIST})


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_vorgaben_speichern(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    try:
        v = vorgaben.speichern(lg, request.POST, bestaetigen=bool(request.POST.get('bestaetigt')),
                               user=request.user)
        messages.success(request, gettext('Vorgaben gespeichert und bestätigt.') if v.bestaetigt_am else gettext('Vorgaben gespeichert — noch nicht bestätigt.'))
    except vorgaben.VorgabenFehler as e:
        messages.error(request, str(e))
    return redirect(f'/neu/stweg/{lg.pk}/vorgaben/')
