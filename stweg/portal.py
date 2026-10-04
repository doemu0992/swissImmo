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
from django.views.decorators.http import require_POST

from portfolio.models import Einheit, Liegenschaft
from stweg import anfragen as anf
from stweg.models import StwegAbrechnung, StwegAbrechnungPosition, StwegAnfrage, Versammlung
from stweg.pdf import abrechnung_pdf, einladung_pdf, protokoll_pdf

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
        g['versammlungen'] = (Versammlung.objects.filter(liegenschaft_id=lg_id)
                              .exclude(status=Versammlung.ENTWURF).order_by('-datum'))
        g['anfragen'] = StwegAnfrage.objects.filter(liegenschaft_id=lg_id, eigentuemer=eig)
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
