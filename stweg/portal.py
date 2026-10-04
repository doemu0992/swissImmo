"""Eigentümer-Portal für Stockwerkeigentümer (/portal/stweg/).

Der Eigentümer sieht NUR Gemeinschaften, in denen ihm eine Einheit gehört
(`Einheit.stockwerkeigentuemer`). Dort findet er seine Einheiten, die
Versammlungen mit Einladung und Protokoll (erst sichtbar, wenn sie versendet
wurden), und er kann der Verwaltung eine Anfrage stellen.

Fremde Gemeinschaften, Versammlungen und Anfragen antworten mit 404, nie mit
403: Ein 403 bestätigte, dass die ID existiert.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext
from django.views.decorators.cache import never_cache
from django.utils import timezone
from django.views.decorators.http import require_POST

from portfolio.models import Einheit, Liegenschaft
from stweg import anfragen as anf
from stweg import dokumente as dok
from stweg import evoting
from stweg.konto import fonds_stand, kontokorrent
from stweg.models import (Anwesenheit, StwegAbrechnung, StwegAbrechnungPosition, StwegAnfrage, StwegBudget,
                          StwegDokument, StwegVorschreibung, Traktandum, Versammlung, Vollmacht,
                          Zirkularbeschluss, ZirkularStimme)
from stweg.pdf import abrechnung_pdf, einladung_pdf, protokoll_pdf, vorschreibung_pdf, zirkular_pdf

logger = logging.getLogger(__name__)


def _eigentuemer(request):
    eig = getattr(request.user, 'eigentuemer_profil', None)
    if eig is None:
        raise Http404
    return eig


def _meine_einheiten(eig):
    # Nur Hauptobjekte: Nebenräume haben weder Quote noch Stimme (stimm_einheiten).
    return Einheit.objects.filter(stockwerkeigentuemer=eig, liegenschaft__typ=Liegenschaft.TYP_STWEG,
                                  gehoert_zu__isnull=True)


def _sichtbare_einheiten(eig):
    """Einheiten, die der Eigentümer SEHEN darf: seine eigenen und die, an denen er Miteigentümer
    ist. Handeln (abstimmen, bevollmächtigen, Anfrage stellen) darf nur die Hauptansprechperson
    — `_meine_einheiten`."""
    return (Einheit.objects.filter(Q(stockwerkeigentuemer=eig) | Q(miteigentuemer=eig),
                                   liegenschaft__typ=Liegenschaft.TYP_STWEG, gehoert_zu__isnull=True)
            .distinct())


@never_cache
@login_required
def portal_stweg(request):
    eig = _eigentuemer(request)
    einheiten = list(_sichtbare_einheiten(eig).select_related('liegenschaft', 'stockwerkeigentuemer'))
    gemeinschaften = {}
    for e in einheiten:
        g = gemeinschaften.setdefault(e.liegenschaft_id, {'lg': e.liegenschaft, 'einheiten': [], 'meine': []})
        g['einheiten'].append(e)
        if e.stockwerkeigentuemer_id == eig.pk:
            g['meine'].append(e)                       # nur hier darf er handeln
        e.miteigentum = e.stockwerkeigentuemer_id != eig.pk
    for lg_id, g in gemeinschaften.items():
        g['versammlungen'] = list(Versammlung.objects.filter(liegenschaft_id=lg_id)
                                  .exclude(status=Versammlung.ENTWURF).order_by('-datum'))
        for v in g['versammlungen']:
            # Vollmachten je eigene Einheit — nur solange die Versammlung noch bevorsteht.
            v.meine_vollmachten = []
            if v.status == Versammlung.EINGELADEN:
                for e in g['meine']:
                    v.meine_vollmachten.append({
                        'einheit': e,
                        'vollmacht': Vollmacht.objects.filter(
                            versammlung=v, einheit=e, widerrufen_am__isnull=True).first()})
        # E-Voting: nur Versammlungen, bei denen es eingeschaltet ist.
        meine_ids = {e.pk for e in g['meine']}
        for v in g['versammlungen']:
            v.evoting_offen = evoting.ist_offen(v)
            if v.evoting_offen and g['meine']:
                stimmen = evoting.meine_stimmen(v, eig)
                da = set(Anwesenheit.objects.filter(versammlung=v, einheit_id__in=meine_ids,
                                                    art=Anwesenheit.ANWESEND).values_list('einheit_id', flat=True))
                v.teilnahme_erklaert = meine_ids <= da
                v.evoting_traktanden = [
                    {'t': t, 'zeilen': [{'einheit': e, 'wert': stimmen.get((t.pk, e.pk), ''),
                                         'angemeldet': e.pk in da} for e in g['meine']]}
                    for t in v.traktanden.exclude(mehrheitsart='kenntnisnahme').filter(ergebnis=Traktandum.OFFEN)]
        g['anfragen'] = StwegAnfrage.objects.filter(liegenschaft_id=lg_id, eigentuemer=eig)
        # Abstimmungen: laufende mit meiner Stimme je Einheit, abgeschlossene mit Ergebnis.
        heute = timezone.localdate()
        g['abstimmungen'] = []
        for z in Zirkularbeschluss.objects.filter(liegenschaft_id=lg_id).exclude(
                status=Zirkularbeschluss.ENTWURF).order_by('-erstellt_am')[:10]:
            stimmen = {st.einheit_id: st.wert for st in ZirkularStimme.objects.filter(zirkular=z)}
            g['abstimmungen'].append({
                'z': z, 'offen': z.status == Zirkularbeschluss.LAUFEND and heute <= z.frist_bis,
                'meine': [{'einheit': e, 'wert': stimmen.get(e.pk, '')} for e in g['meine']]})
        # Nur ABGESCHLOSSENE Abrechnungen, und nur der eigene Teil davon.
        g['abrechnungen'] = [
            {'abrechnung': a, 'saldo': sum(p.saldo for p in
                                           StwegAbrechnungPosition.objects.filter(abrechnung=a, eigentuemer=eig))}
            for a in StwegAbrechnung.objects.filter(
                liegenschaft_id=lg_id, status=StwegAbrechnung.STATUS_ABGESCHLOSSEN,
                positionen__eigentuemer=eig).distinct()]
    for lg_id, g in gemeinschaften.items():
        g['kontokorrent'] = [{'einheit': e, **kontokorrent(e)} for e in g['einheiten']]
        g['fonds'] = fonds_stand(g['lg'], g['einheiten'])
        g['dokumente'] = dok.fuer_eigentuemer(g['lg'])
        g['akonto_budgets'] = StwegBudget.objects.filter(
            liegenschaft_id=lg_id, status=StwegBudget.GENEHMIGT,
            vorschreibungen__eigentuemer=eig).distinct()
    return render(request, 'stweg/portal.html', {
        'eigentuemer': eig, 'gemeinschaften': list(gemeinschaften.values())})


def _versammlung_des_eigentuemers(request, pk):
    eig = _eigentuemer(request)
    v = Versammlung.objects.select_related('liegenschaft').filter(pk=pk).first()
    if v is None or not _sichtbare_einheiten(eig).filter(liegenschaft=v.liegenschaft).exists():
        raise Http404
    return eig, v


def _pdf(inhalt, name):
    antwort = HttpResponse(inhalt, content_type='application/pdf')
    antwort['Content-Disposition'] = f'inline; filename="{name}"'
    return antwort


@never_cache
@login_required
def portal_stweg_einladung(request, pk):
    eig, v = _versammlung_des_eigentuemers(request, pk)
    if v.einladung_versendet_am is None:
        raise Http404                      # Entwürfe sind nicht öffentlich
    return _pdf(einladung_pdf(v, eig), f'Einladung_{v.datum:%Y%m%d}.pdf')


@never_cache
@login_required
def portal_stweg_protokoll(request, pk):
    eig, v = _versammlung_des_eigentuemers(request, pk)
    if v.protokoll_versendet_am is None:
        raise Http404                      # Protokoll erst nach dem Versand
    return _pdf(protokoll_pdf(v), f'Protokoll_{v.datum:%Y%m%d}.pdf')


@never_cache
@login_required
def portal_stweg_abrechnung(request, pk):
    eig = _eigentuemer(request)
    a = StwegAbrechnung.objects.filter(pk=pk, status=StwegAbrechnung.STATUS_ABGESCHLOSSEN,
                                       positionen__eigentuemer=eig).first()
    if a is None:
        raise Http404                      # fremd, nicht abgeschlossen oder nicht meine
    return _pdf(abrechnung_pdf(a, eig), f'Abrechnung_{a.jahr}.pdf')


@login_required
@require_POST
def portal_stweg_vollmacht(request, pk):
    from stweg.vollmacht import VollmachtFehler, erteilen
    eig, v = _versammlung_des_eigentuemers(request, pk)
    einheit = _meine_einheiten(eig).filter(pk=request.POST.get('einheit') or 0,
                                           liegenschaft=v.liegenschaft).first() \
        if (request.POST.get('einheit') or '').isdigit() else None
    if einheit is None:
        raise Http404
    try:
        erteilen(v, einheit, request.POST.get('bevollmaechtigter'), erteilt_von=eig, kanal='portal')
        messages.success(request, gettext('Ihre Vollmacht wurde erfasst.'))
    except VollmachtFehler as e:
        messages.error(request, str(e))
    return redirect('/portal/stweg/')


@login_required
@require_POST
def portal_stweg_vollmacht_widerruf(request, pk):
    from stweg.vollmacht import VollmachtFehler, widerrufen
    eig = _eigentuemer(request)
    vm = Vollmacht.objects.select_related('versammlung', 'einheit').filter(pk=pk).first()
    if vm is None or vm.einheit.stockwerkeigentuemer_id != eig.pk:
        raise Http404
    try:
        widerrufen(vm)
        messages.success(request, gettext('Die Vollmacht wurde widerrufen.'))
    except VollmachtFehler as e:
        messages.error(request, str(e))
    return redirect('/portal/stweg/')


def _zirkular_des_eigentuemers(request, pk):
    eig = _eigentuemer(request)
    z = Zirkularbeschluss.objects.select_related('liegenschaft').filter(pk=pk).first()
    if z is None or z.status == Zirkularbeschluss.ENTWURF \
            or not _sichtbare_einheiten(eig).filter(liegenschaft=z.liegenschaft).exists():
        raise Http404                      # fremd oder noch Entwurf
    return eig, z


@login_required
@require_POST
def portal_stweg_abstimmen(request, pk):
    from stweg import zirkular as zk
    from stweg.beschluss import BeschlussFehler
    eig, z = _zirkular_des_eigentuemers(request, pk)
    abgegeben = 0
    try:
        for e in _meine_einheiten(eig).filter(liegenschaft=z.liegenschaft):
            wert = request.POST.get(f'stimme_{e.pk}')
            if wert:
                zk.stimme_abgeben(z, e, wert, kanal='portal')
                abgegeben += 1
    except BeschlussFehler as fehler:
        messages.error(request, str(fehler))
        return redirect('/portal/stweg/')
    messages.success(request, gettext('Ihre Stimme wurde gespeichert.') if abgegeben
                     else gettext('Keine Stimme angegeben.'))
    return redirect('/portal/stweg/')


@never_cache
@login_required
def portal_stweg_zirkular(request, pk):
    eig, z = _zirkular_des_eigentuemers(request, pk)
    return _pdf(zirkular_pdf(z), f'Zirkular_{z.pk}.pdf')


@login_required
@require_POST
def portal_stweg_anfrage(request, stweg_id):
    eig = _eigentuemer(request)
    einheit = _meine_einheiten(eig).filter(liegenschaft_id=stweg_id).first()
    if einheit is None:
        raise Http404
    betreff = (request.POST.get('betreff') or '').strip()
    if not betreff:
        messages.error(request, gettext('Bitte einen Betreff angeben.'))
        return redirect('/portal/stweg/')
    a = anf.anfrage_erfassen(einheit.liegenschaft, betreff, (request.POST.get('text') or '').strip(),
                             einheit=einheit, eigentuemer=eig, kanal='portal')
    anf.verwaltung_benachrichtigen(a)
    messages.success(request, gettext('Ihre Anfrage wurde an die Verwaltung übermittelt.'))
    return redirect('/portal/stweg/')


@never_cache
@login_required
def portal_stweg_dokument(request, pk):
    eig = _eigentuemer(request)
    d = StwegDokument.objects.select_related('liegenschaft').filter(pk=pk, sichtbar=True).first()
    if d is None or not _sichtbare_einheiten(eig).filter(liegenschaft=d.liegenschaft).exists():
        raise Http404                      # fremd oder nicht freigegeben
    from stweg.views_dokumente import datei_antwort
    return datei_antwort(d)


@never_cache
@login_required
def portal_stweg_akonto(request, pk):
    eig = _eigentuemer(request)
    b = StwegBudget.objects.filter(pk=pk, status=StwegBudget.GENEHMIGT,
                                   vorschreibungen__eigentuemer=eig).distinct().first()
    if b is None:
        raise Http404
    return _pdf(vorschreibung_pdf(b, eig), f'Akonto_{b.jahr}.pdf')


@login_required
@require_POST
def portal_stweg_teilnehmen(request, pk):
    from stweg.beschluss import BeschlussFehler
    eig, v = _versammlung_des_eigentuemers(request, pk)
    try:
        evoting.teilnehmen(v, eig)
        messages.success(request, gettext('Ihre Teilnahme ist erfasst. Sie können jetzt abstimmen.'))
    except BeschlussFehler as e:
        messages.error(request, str(e))
    return redirect('/portal/stweg/')


@login_required
@require_POST
def portal_stweg_evoting(request, pk):
    from stweg.beschluss import BeschlussFehler
    eig, v = _versammlung_des_eigentuemers(request, pk)
    stimmen = {}
    for schluessel, wert in request.POST.items():
        if schluessel.startswith('stimme_') and wert:
            teile = schluessel.split('_')
            if len(teile) == 3 and teile[1].isdigit() and teile[2].isdigit():
                stimmen[(int(teile[1]), int(teile[2]))] = wert
    if not stimmen:
        messages.error(request, gettext('Keine Stimme angegeben.'))
        return redirect('/portal/stweg/')
    try:
        n = evoting.abstimmen(v, eig, stimmen)
        messages.success(request, gettext('Ihre Stimme wurde gespeichert.') if n == 1
                         else gettext('Ihre Stimmen wurden gespeichert.'))
    except BeschlussFehler as e:
        messages.error(request, str(e))
    return redirect('/portal/stweg/')
