"""Oberfläche für Verteilschlüssel und Budget (/neu/stweg/…).

Die Fachlogik steht in `stweg.schluessel` und `stweg.budget`; hier werden Eingaben gelesen, die
Services aufgerufen und Fehler gemeldet. Jedes Objekt wird über seinen `TenantManager` geladen
(fremde ID → 404).
"""
from django.utils.translation import gettext
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.auth import SCHREIB_ROLLEN, TEAM_ROLLEN, rolle_erforderlich
from crm.models import Eigentuemer
from finance.models import Buchungskonto
from stweg import budget as bd
from stweg.models import (StwegBefreiung, StwegBudget, StwegBudgetPosition, StwegKostenzuordnung, StwegSchluessel,
                          StwegSchluesselAnteil, StwegVorschreibung, Traktandum, Versammlung)
from stweg.schluessel import (SchluesselFehler, befreien, befreiung_aufheben, gewichte, kostenart_zuordnen, lift_schluessel,
                              standard_schluessel)
from stweg.validierung import stimm_einheiten
from stweg.views import _betrag, _gemeinschaft, _jahr, _zahl


def _zu_schluessel(lg):
    return redirect(f'/neu/stweg/{lg.pk}/schluessel/')


def _zu_budget(b):
    return redirect(f'/neu/stweg/budget/{b.pk}/')


# ── Verteilschlüssel ─────────────────────────────────────────────────────

@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_schluessel(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    einheiten = list(stimm_einheiten(lg).order_by('bezeichnung'))
    schluessel = []
    for s in lg.stweg_schluessel.all():
        try:
            g, fehler = gewichte(s, einheiten), ''
        except SchluesselFehler as e:
            g, fehler = {}, str(e)
        total = sum(g.values(), Decimal('0'))
        schluessel.append({
            's': s, 'fehler': fehler,
            'zeilen': [{'einheit': e, 'gewicht': g.get(e.pk),
                        'prozent': (g[e.pk] / total * 100).quantize(Decimal('0.01')) if g and total else None,
                        'anteil': next((a.anteil for a in s.anteile.all() if a.einheit_id == e.pk), None)}
                       for e in einheiten]})
    return render(request, 'stweg/schluessel.html', {
        'nav': 'stweg', 'lg': lg, 'schluessel': schluessel, 'art_choices': StwegSchluessel.ART_CHOICES,
        'konten': Buchungskonto.objects.filter(typ='aufwand').order_by('nummer'),
        'zuordnungen': StwegKostenzuordnung.objects.filter(liegenschaft=lg).select_related('konto', 'schluessel'),
        'alle_schluessel': lg.stweg_schluessel.all(),
        'einheiten': einheiten,
        'befreiungen': StwegBefreiung.objects.filter(schluessel__liegenschaft=lg)
        .select_related('schluessel', 'einheit').order_by('schluessel__name', 'einheit__bezeichnung')})


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_schluessel_befreien(request, stweg_id):
    """Einheiten von den Kosten eines Schlüssels befreien (Art. 712h Abs. 3 ZGB) — mit Begründung."""
    lg = _gemeinschaft(stweg_id)
    ids = [_zahl(x) for x in request.POST.getlist('einheit')]
    einheiten = list(stimm_einheiten(lg).filter(pk__in=[i for i in ids if i]))
    try:
        with transaction.atomic():
            befreien(lg, (request.POST.get('name') or '').strip()[:100] or 'Lift', einheiten,
                     request.POST.get('begruendung') or '', user=request.user)
        messages.success(request, gettext('Befreiung festgehalten: Der Betrag wird auf die übrigen Einheiten umgerechnet.'))
    except SchluesselFehler as e:
        messages.error(request, str(e))
    return _zu_schluessel(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_befreiung_aufheben(request, pk):
    b = get_object_or_404(StwegBefreiung.objects.select_related('schluessel__liegenschaft'), pk=pk)
    befreiung_aufheben(b)
    messages.success(request, gettext('Befreiung aufgehoben: Die Einheit trägt wieder ihre Wertquote.'))
    return _zu_schluessel(b.schluessel.liegenschaft)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_schluessel_neu(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    name = (request.POST.get('name') or '').strip()[:100]
    art = request.POST.get('art')
    if not name or art not in dict(StwegSchluessel.ART_CHOICES):
        messages.error(request, gettext('Name und Art sind nötig.'))
        return _zu_schluessel(lg)
    try:
        with transaction.atomic():
            if art == StwegSchluessel.MANUELL and request.POST.get('ohne_eg'):
                lift_schluessel(lg, name=name)
                messages.success(request, gettext('Schlüssel «%(name)s» angelegt: Erdgeschoss trägt nichts, die übrigen Einheiten nach Wertquote. Anteile bei Bedarf anpassen.') % {'name': name})
            else:
                StwegSchluessel.objects.create(liegenschaft=lg, name=name, art=art,
                                               bemerkung=(request.POST.get('bemerkung') or '').strip()[:200])
                messages.success(request, gettext('Schlüssel «%(name)s» angelegt.') % {'name': name})
    except IntegrityError:
        messages.error(request, gettext('Einen Schlüssel «%(name)s» gibt es schon.') % {'name': name})
    except SchluesselFehler as e:
        messages.error(request, str(e))
    return _zu_schluessel(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_schluessel_anteile(request, pk):
    s = get_object_or_404(StwegSchluessel.objects.select_related('liegenschaft'), pk=pk)
    lg = s.liegenschaft
    if s.art != StwegSchluessel.MANUELL:
        messages.error(request, gettext('Nur Schlüssel mit eigenen Anteilen haben Anteile zu pflegen.'))
        return _zu_schluessel(lg)
    neu = {}
    for e in stimm_einheiten(lg):
        roh = (request.POST.get(f'anteil_{e.pk}') or '').strip().replace("'", '').replace(',', '.')
        if roh == '':
            continue
        try:
            w = Decimal(roh)
        except InvalidOperation:
            messages.error(request, gettext('«%(roh)s» ist keine Zahl (%(bezeichnung)s).') % {'roh': roh, 'bezeichnung': e.bezeichnung})
            return _zu_schluessel(lg)
        if w < 0:
            messages.error(request, gettext('Anteile dürfen nicht negativ sein (%(bezeichnung)s).') % {'bezeichnung': e.bezeichnung})
            return _zu_schluessel(lg)
        neu[e.pk] = w
    with transaction.atomic():
        for eid, w in neu.items():
            StwegSchluesselAnteil.objects.update_or_create(schluessel=s, einheit_id=eid, defaults={'anteil': w})
    messages.success(request, gettext('Anteile von «%(name)s» gespeichert.') % {'name': s.name})
    return _zu_schluessel(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_schluessel_loeschen(request, pk):
    s = get_object_or_404(StwegSchluessel.objects.select_related('liegenschaft'), pk=pk)
    lg = s.liegenschaft
    if s.ist_standard:
        messages.error(request, gettext('Der Standardschlüssel lässt sich nicht löschen.'))
    elif (StwegBudgetPosition.objects.filter(schluessel=s).exists()
          or StwegKostenzuordnung.objects.filter(schluessel=s).exists()):
        messages.error(request, gettext('«%(name)s» wird noch verwendet (Kostenart oder Budget).') % {'name': s.name})
    else:
        try:
            s.delete()
            messages.success(request, gettext('Schlüssel gelöscht.'))
        except ProtectedError:
            messages.error(request, gettext('«%(name)s» wird noch verwendet.') % {'name': s.name})
    return _zu_schluessel(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_kostenart_zuordnen(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    konto = Buchungskonto.objects.filter(pk=_zahl(request.POST.get('konto')) or 0, typ='aufwand').first()
    if konto is None:
        messages.error(request, gettext('Bitte ein Aufwandkonto wählen.'))
        return _zu_schluessel(lg)
    if not request.POST.get('schluessel'):
        StwegKostenzuordnung.objects.filter(liegenschaft=lg, konto=konto).delete()
        messages.success(request, gettext('Zuordnung für %(nummer)s entfernt: Kosten laufen über den Standardschlüssel.') % {'nummer': konto.nummer})
        return _zu_schluessel(lg)
    s = lg.stweg_schluessel.filter(pk=_zahl(request.POST.get('schluessel')) or 0).first()
    if s is None:
        messages.error(request, gettext('Schlüssel nicht gefunden.'))
        return _zu_schluessel(lg)
    kostenart_zuordnen(lg, konto, s)
    messages.success(request, gettext('Kosten auf %(nummer)s %(bezeichnung)s werden nach «%(name)s» verteilt.') % {'nummer': konto.nummer, 'bezeichnung': konto.bezeichnung, 'name': s.name})
    return _zu_schluessel(lg)


# ── Budget ───────────────────────────────────────────────────────────────

@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_budget(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    return render(request, 'stweg/budget.html', {
        'nav': 'stweg', 'lg': lg, 'budgets': StwegBudget.objects.filter(liegenschaft=lg),
        'jahr': timezone.localdate().year + 1})


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_budget_neu(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    jahr = _jahr(request.POST.get('jahr'))
    raten = _zahl(request.POST.get('raten')) or 4
    if jahr is None or raten not in (1, 2, 3, 4, 6, 12):
        messages.error(request, gettext('Jahr und eine Ratenzahl (1, 2, 3, 4, 6 oder 12) sind nötig.'))
        return redirect(f'/neu/stweg/{lg.pk}/budget/')
    standard_schluessel(lg)             # damit es für die Positionen einen Schlüssel zu wählen gibt
    b, neu = StwegBudget.objects.get_or_create(
        liegenschaft=lg, jahr=jahr,
        defaults={'raten': raten, 'erste_faelligkeit': parse_date(request.POST.get('erste_faelligkeit') or '')})
    if not neu:
        messages.info(request, gettext('Für %(jahr)s gibt es schon ein Budget.') % {'jahr': jahr})
    return _zu_budget(b)


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_budget_detail(request, pk):
    b = get_object_or_404(StwegBudget.objects.select_related('liegenschaft'), pk=pk)
    lg = b.liegenschaft
    try:
        vorschau, fehler = bd.jahresbetraege(b) if b.positionen.exists() else {}, ''
    except bd.BudgetFehler as e:
        vorschau, fehler = {}, str(e)
    traktanden = Traktandum.objects.filter(versammlung__liegenschaft=lg, ergebnis=Traktandum.OFFEN,
                                           versammlung__status__in=(Versammlung.ENTWURF, Versammlung.EINGELADEN,
                                                                    Versammlung.DURCHGEFUEHRT)
                                           ).select_related('versammlung').order_by('-versammlung__datum', 'nr')
    vs = list(StwegVorschreibung.objects.filter(budget=b).select_related('einheit', 'eigentuemer'))
    return render(request, 'stweg/budget_detail.html', {
        'nav': 'stweg', 'lg': lg, 'b': b, 'positionen': b.positionen.select_related('schluessel'),
        'vorschau': vorschau.items(), 'fehler': fehler, 'probleme': bd.pruefen(b) if b.status != 'genehmigt' else [],
        'schluessel': lg.stweg_schluessel.all(), 'traktanden': traktanden,
        'angehaengt': b.traktanden.select_related('versammlung'),
        'vorschreibungen': vs,
        'eigentuemer': sorted({v.eigentuemer for v in vs if v.eigentuemer}, key=lambda x: x.firma_oder_name),
        'offen_versand': sum(1 for v in vs if v.versendet_am is None)})


def _budget_aktion(request, pk, funktion):
    b = get_object_or_404(StwegBudget.objects.select_related('liegenschaft'), pk=pk)
    try:
        meldung = funktion(b)
        if meldung:
            messages.success(request, meldung)
    except bd.BudgetFehler as e:
        messages.error(request, str(e))
    return _zu_budget(b)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_budget_position_neu(request, pk):
    def tun(b):
        s = b.liegenschaft.stweg_schluessel.filter(pk=_zahl(request.POST.get('schluessel')) or 0).first()
        betrag = _betrag(request.POST.get('betrag'))
        bez = (request.POST.get('bezeichnung') or '').strip()[:200]
        if s is None or betrag is None or not bez:
            raise bd.BudgetFehler('Bezeichnung, Schlüssel und Betrag sind nötig.')
        bd.position_setzen(b, bez, s, betrag)
        return f'Position «{bez}» erfasst.'
    return _budget_aktion(request, pk, tun)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_budget_position_loeschen(request, pk):
    def tun(b):
        b.refresh_from_db(fields=['status'])
        if b.status == StwegBudget.GENEHMIGT:
            raise bd.BudgetFehler('Ein genehmigtes Budget ist abgeschlossen.')
        n, _ = b.positionen.filter(pk=_zahl(request.POST.get('position')) or 0).delete()
        if n and b.status == StwegBudget.VORGELEGT:
            b.status = StwegBudget.ENTWURF
            b.save(update_fields=['status'])
        return 'Position entfernt.' if n else None
    return _budget_aktion(request, pk, tun)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_budget_vorlegen(request, pk):
    def tun(b):
        bd.vorlegen(b)
        return 'Das Budget ist vorgelegt. Jetzt einem Traktandum zuweisen.'
    return _budget_aktion(request, pk, tun)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_budget_traktandum(request, pk):
    def tun(b):
        t = Traktandum.objects.select_related('versammlung').filter(
            pk=_zahl(request.POST.get('traktandum')) or 0, versammlung__liegenschaft=b.liegenschaft).first()
        if t is None:
            raise bd.BudgetFehler('Traktandum nicht gefunden.')
        bd.an_traktandum_haengen(t, b)
        return (f'Das Budget wird unter Traktandum {t.nr} «{t.titel}» beschlossen. Wählen Sie dort eine '
                'Mehrheitsart; ein angenommener Beschluss schreibt die Akonto-Raten vor.')
    return _budget_aktion(request, pk, tun)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_budget_versenden(request, pk):
    def tun(b):
        r = bd.vorschreibungen_versenden(b)
        teile = [f'{len(r["gesendet"])} gesendet']
        if r['post']:
            teile.append(f'{len(r["post"])} ohne E-Mail (per Post: ' + ', '.join(
                e.firma_oder_name for e in r['post']) + ')')
        if r['fehler']:
            teile.append(f'{len(r["fehler"])} Versandfehler (erneut versuchen)')
        return 'Akonto-Rechnungen: ' + '; '.join(teile) + '.'
    return _budget_aktion(request, pk, tun)


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_budget_pdf(request, pk):
    from stweg.pdf import vorschreibung_pdf
    b = get_object_or_404(StwegBudget.objects.select_related('liegenschaft'), pk=pk)
    eig = get_object_or_404(Eigentuemer, pk=_zahl(request.GET.get('eigentuemer')) or 0)
    antwort = HttpResponse(vorschreibung_pdf(b, eig), content_type='application/pdf')
    antwort['Content-Disposition'] = f'inline; filename="Akonto_{b.jahr}.pdf"'
    return antwort
