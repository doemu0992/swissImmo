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
from stweg.models import (Anwesenheit, Stimme, StwegAbrechnung, StwegAkonto, StwegAnfrage,
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
    for e in stimm_einheiten(v.liegenschaft):
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
        messages.error(request, 'Bitte ein Jahr angeben.')
        return _zur_abrechnung(lg)
    try:
        StwegAbrechnungService(lg).abrechnen(jahr)
        messages.success(request, f'Abrechnung {jahr} berechnet.')
    except (AbrechnungsFehler, WertquotenFehler) as e:
        messages.error(request, str(getattr(e, 'message', None) or e))
    return _zur_abrechnung(lg, jahr)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_abrechnung_abschliessen(request, pk):
    from stweg.services import StwegAbrechnungService
    a = get_object_or_404(StwegAbrechnung.objects.select_related('liegenschaft'), pk=pk)
    StwegAbrechnungService.abschliessen(a)
    messages.success(request, f'Abrechnung {a.jahr} abgeschlossen.')
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
        messages.error(request, 'Einheit und ein Betrag grösser 0 sind nötig.')
        return _zur_abrechnung(lg)
    StwegAkonto.objects.create(einheit=einheit, betrag=betrag, datum=datum,
                               bemerkung=(request.POST.get('bemerkung') or '').strip()[:200])
    messages.success(request, f'Akonto CHF {betrag} für {einheit.bezeichnung} erfasst.')
    return _zur_abrechnung(lg, datum.year)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_akonto_loeschen(request, pk):
    k = get_object_or_404(StwegAkonto.objects.select_related('einheit__liegenschaft'), pk=pk)
    lg, jahr = k.einheit.liegenschaft, k.datum.year
    if StwegAbrechnung.objects.filter(liegenschaft=lg, jahr=jahr,
                                      status=StwegAbrechnung.STATUS_ABGESCHLOSSEN).exists():
        messages.error(request, f'Die Abrechnung {jahr} ist abgeschlossen — Akonto lässt sich nicht mehr ändern.')
    else:
        k.delete()
    return _zur_abrechnung(lg, jahr)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_fonds_einlage(request, stweg_id):
    from stweg.fonds import FondsFehler, jahreseinlage_belasten
    lg = _gemeinschaft(stweg_id)
    jahr, betrag = _jahr(request.POST.get('jahr')), _betrag(request.POST.get('betrag'))
    if jahr is None or betrag is None:
        messages.error(request, 'Jahr und Betrag sind nötig.')
        return _zur_abrechnung(lg)
    try:
        verteilt = jahreseinlage_belasten(lg, jahr, betrag, user=request.user)
        messages.success(request, f'Einlage {jahr}: CHF {betrag} auf {len(verteilt)} Einheiten verteilt.')
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
        messages.error(request, 'Jahr, Betrag und Verwendungszweck sind nötig.')
        return _zur_abrechnung(lg)
    try:
        entnahme_buchen(lg, jahr, betrag, text, user=request.user)
        messages.success(request, f'Entnahme CHF {betrag} gebucht.')
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
        messages.error(request, 'Bitte eine Einheit wählen.')
        return _zurueck(v)
    try:
        erteilen(v, einheit, request.POST.get('bevollmaechtigter'), kanal='verwaltung')
        messages.success(request, f'Vollmacht für {einheit.bezeichnung} erfasst.')
    except VollmachtFehler as e:
        _fehler(request, e)
    return _zurueck(v)


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
        messages.error(request, 'Titel, Antrag und Abstimmungsfrist sind nötig.')
        return redirect(f'/neu/stweg/{lg.pk}/')
    art = request.POST.get('mehrheitsart')
    z = Zirkularbeschluss.objects.create(
        liegenschaft=lg, titel=titel[:200], antrag=antrag,
        begruendung=(request.POST.get('begruendung') or '').strip(), frist_bis=frist,
        mehrheitsart=art if art in dict(Traktandum.MEHRHEIT_CHOICES) and art != 'kenntnisnahme' else 'einstimmig',
        rechtsgrundlage=(request.POST.get('rechtsgrundlage') or '').strip()[:200],
        vollzug_aufgabe=(request.POST.get('vollzug_aufgabe') or '').strip()[:200],
        vollzug_faellig_am=parse_date(request.POST.get('vollzug_faellig_am') or ''))
    messages.success(request, 'Zirkularbeschluss angelegt. Prüfen und versenden.')
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
    messages.success(request, f'Antrag: {sum(1 for n in neu if n.status == "gesendet")} per E-Mail versendet.')
    offen = [n for n in neu if n.status != 'gesendet']
    if offen:
        messages.warning(request, f'{len(offen)} Zustellung(en) offen (keine E-Mail-Adresse oder Fehler).')
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
        messages.success(request, 'Ergebnis festgestellt.')
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
        messages.success(request, f'Ergebnis an {sum(1 for n in neu if n.status == "gesendet")} Eigentümer versendet.')
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
