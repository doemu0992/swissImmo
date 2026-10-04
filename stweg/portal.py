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
from django.core.mail import send_mail
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.utils import timezone
from django.views.decorators.http import require_POST

from portfolio.models import Einheit, Liegenschaft
from stweg import anfragen as anf
from stweg.models import (StwegAbrechnung, StwegAbrechnungPosition, StwegAnfrage, Versammlung, Vollmacht,
                          Zirkularbeschluss, ZirkularStimme)
from stweg.pdf import abrechnung_pdf, einladung_pdf, protokoll_pdf, zirkular_pdf

logger = logging.getLogger(__name__)


def _eigentuemer(request):
    eig = getattr(request.user, 'eigentuemer_profil', None)
    if eig is None:
        raise Http404
    return eig


def _meine_einheiten(eig):
    return Einheit.objects.filter(stockwerkeigentuemer=eig, liegenschaft__typ=Liegenschaft.TYP_STWEG)


@never_cache
@login_required
def portal_stweg(request):
    eig = _eigentuemer(request)
    einheiten = list(_meine_einheiten(eig).select_related('liegenschaft'))
    gemeinschaften = {}
    for e in einheiten:
        g = gemeinschaften.setdefault(e.liegenschaft_id, {'lg': e.liegenschaft, 'einheiten': []})
        g['einheiten'].append(e)
    for lg_id, g in gemeinschaften.items():
        g['versammlungen'] = list(Versammlung.objects.filter(liegenschaft_id=lg_id)
                                  .exclude(status=Versammlung.ENTWURF).order_by('-datum'))
        for v in g['versammlungen']:
            # Vollmachten je eigene Einheit — nur solange die Versammlung noch bevorsteht.
            v.meine_vollmachten = []
            if v.status == Versammlung.EINGELADEN:
                for e in g['einheiten']:
                    v.meine_vollmachten.append({
                        'einheit': e,
                        'vollmacht': Vollmacht.objects.filter(
                            versammlung=v, einheit=e, widerrufen_am__isnull=True).first()})
        g['anfragen'] = StwegAnfrage.objects.filter(liegenschaft_id=lg_id, eigentuemer=eig)
        # Abstimmungen: laufende mit meiner Stimme je Einheit, abgeschlossene mit Ergebnis.
        heute = timezone.localdate()
        g['abstimmungen'] = []
        for z in Zirkularbeschluss.objects.filter(liegenschaft_id=lg_id).exclude(
                status=Zirkularbeschluss.ENTWURF).order_by('-erstellt_am')[:10]:
            stimmen = {st.einheit_id: st.wert for st in ZirkularStimme.objects.filter(zirkular=z)}
            g['abstimmungen'].append({
                'z': z, 'offen': z.status == Zirkularbeschluss.LAUFEND and heute <= z.frist_bis,
                'meine': [{'einheit': e, 'wert': stimmen.get(e.pk, '')} for e in g['einheiten']]})
        # Nur ABGESCHLOSSENE Abrechnungen, und nur der eigene Teil davon.
        g['abrechnungen'] = [
            {'abrechnung': a, 'saldo': sum(p.saldo for p in
                                           StwegAbrechnungPosition.objects.filter(abrechnung=a, eigentuemer=eig))}
            for a in StwegAbrechnung.objects.filter(
                liegenschaft_id=lg_id, status=StwegAbrechnung.STATUS_ABGESCHLOSSEN,
                positionen__eigentuemer=eig).distinct()]
    return render(request, 'stweg/portal.html', {
        'eigentuemer': eig, 'gemeinschaften': list(gemeinschaften.values())})


def _versammlung_des_eigentuemers(request, pk):
    eig = _eigentuemer(request)
    v = Versammlung.objects.select_related('liegenschaft').filter(pk=pk).first()
    if v is None or not _meine_einheiten(eig).filter(liegenschaft=v.liegenschaft).exists():
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
        messages.success(request, 'Ihre Vollmacht wurde erfasst.')
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
        messages.success(request, 'Die Vollmacht wurde widerrufen.')
    except VollmachtFehler as e:
        messages.error(request, str(e))
    return redirect('/portal/stweg/')


def _zirkular_des_eigentuemers(request, pk):
    eig = _eigentuemer(request)
    z = Zirkularbeschluss.objects.select_related('liegenschaft').filter(pk=pk).first()
    if z is None or z.status == Zirkularbeschluss.ENTWURF \
            or not _meine_einheiten(eig).filter(liegenschaft=z.liegenschaft).exists():
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
    messages.success(request, 'Ihre Stimme wurde gespeichert.' if abgegeben else 'Keine Stimme angegeben.')
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
        messages.error(request, 'Bitte einen Betreff angeben.')
        return redirect('/portal/stweg/')
    a = anf.anfrage_erfassen(einheit.liegenschaft, betreff, (request.POST.get('text') or '').strip(),
                             einheit=einheit, eigentuemer=eig, kanal='portal')
    zustaendig = einheit.liegenschaft.betreut_von
    if zustaendig is not None and zustaendig.email:
        try:
            send_mail(f'Neue STWEG-Anfrage: {a.betreff}',
                      f'{eig.firma_oder_name} ({einheit.bezeichnung}, {einheit.liegenschaft}):\n\n{a.text}',
                      None, [zustaendig.email], fail_silently=False)
        except Exception:                                           # noqa: BLE001
            # Die Anfrage ist gespeichert und als Pendenz sichtbar; die Mail ist
            # nur der Hinweis darauf. Ihr Scheitern darf die Anfrage nicht verlieren.
            logger.warning('Benachrichtigung zur STWEG-Anfrage %s fehlgeschlagen', a.pk, exc_info=True)
    messages.success(request, 'Ihre Anfrage wurde an die Verwaltung übermittelt.')
    return redirect('/portal/stweg/')
