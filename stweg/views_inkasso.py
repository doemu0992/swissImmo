"""Oberfläche für das STWEG-Inkasso (/neu/stweg/<id>/inkasso/)."""
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from core.auth import SCHREIB_ROLLEN, TEAM_ROLLEN, rolle_erforderlich
from stweg import inkasso, zins
from stweg.models import StwegInkassoFall, StwegMahnung, StwegPfandrecht
from stweg.validierung import stimm_einheiten
from stweg.views import _gemeinschaft, _zahl


def _zurueck(lg):
    return redirect(f'/neu/stweg/{lg.pk}/inkasso/')


def _einheit(lg, request):
    return stimm_einheiten(lg).filter(pk=_zahl(request.POST.get('einheit')) or 0).first()


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_inkasso(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    heute = timezone.localdate()
    zeilen = []
    for e in stimm_einheiten(lg).select_related('stockwerkeigentuemer').order_by('bezeichnung'):
        offen = inkasso.offener_betrag(e, heute)
        fall = inkasso.offener_fall(e)
        if offen <= 0 and fall is None:
            continue
        p = inkasso.pfandberechtigt(e, heute) if offen > 0 else None
        zeilen.append({'einheit': e, 'offen': offen, 'fall': fall, 'pfand': p,
                       'stufe': inkasso.mahnstufe(fall), 'zins_unbestaetigt': zins.satz_unbestaetigt(lg),
                       'neben': [c for c in inkasso.forderungen(e, heute)
                                 if c['art'] not in zins.KAPITAL_ARTEN and c['offen'] > 0],
                       'altforderung': offen - inkasso.offener_betrag_eigentuemer(e, heute),
                       'mahnungen': list(fall.mahnungen.all()) if fall else [],
                       'pfandrechte': list(fall.pfandrechte.all()) if fall else [],
                       'naechste': (inkasso.mahnstufe(fall) + 1) if inkasso.mahnstufe(fall) < inkasso.MAX_STUFE
                       else None})
    return render(request, 'stweg/inkasso.html', {
        'nav': 'stweg', 'lg': lg, 'zeilen': zeilen, 'frist': inkasso.MAHNFRIST_TAGE,
        'monate': inkasso.PFANDRECHT_MONATE})


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_inkasso_mahnen(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    e = _einheit(lg, request)
    if e is None:
        messages.error(request, gettext('Bitte eine Einheit wählen.'))
        return _zurueck(lg)
    try:
        m = inkasso.mahnung_erstellen(e, frist_tage=_zahl(request.POST.get('frist_tage')) or inkasso.MAHNFRIST_TAGE,
                                      user=request.user)
        weg = inkasso.mahnung_versenden(m)
    except inkasso.InkassoFehler as fehler:
        messages.error(request, str(fehler))
        return _zurueck(lg)
    if weg == 'email':
        messages.success(request, gettext('%(stufe)s. Mahnung per E-Mail versendet.') % {'stufe': m.stufe})
    elif weg == 'post':
        messages.warning(request, gettext('%(stufe)s. Mahnung erstellt — keine E-Mail-Adresse, bitte das PDF per Post '
                                          'zustellen.') % {'stufe': m.stufe})
    else:
        messages.error(request, gettext('%(stufe)s. Mahnung erstellt, aber der Versand ist fehlgeschlagen.')
                       % {'stufe': m.stufe})
    return _zurueck(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_inkasso_retention(request, stweg_id):
    lg = _gemeinschaft(stweg_id)
    e = _einheit(lg, request)
    fall = inkasso.offener_fall(e) if e else None
    if fall is None:
        messages.error(request, gettext('Für diese Einheit ist kein Inkassofall offen.'))
        return _zurueck(lg)
    try:
        inkasso.retention_geltend_machen(fall, request.POST.get('gegenstaende') or '',
                                         ohne_mahnungen=bool(request.POST.get('ohne_mahnungen')), user=request.user)
        messages.success(request, gettext('Das Retentionsrecht ist festgehalten.'))
    except inkasso.InkassoFehler as fehler:
        messages.error(request, str(fehler))
    return _zurueck(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_inkasso_pfandrecht(request, stweg_id):
    """«Gemeinschaftspfandrecht anmelden»: nur die Forderungen der letzten 36 Monate."""
    lg = _gemeinschaft(stweg_id)
    e = _einheit(lg, request)
    fall = inkasso.offener_fall(e) if e else None
    if fall is None:
        messages.error(request, gettext('Für diese Einheit ist kein Inkassofall offen.'))
        return _zurueck(lg)
    try:
        pf = inkasso.pfandrecht_anmelden(fall, stichtag=parse_date(request.POST.get('stichtag') or ''),
                                         ohne_mahnungen=bool(request.POST.get('ohne_mahnungen')), user=request.user)
        messages.success(request, gettext('Pfandrecht angemeldet: Pfandsumme CHF %(betrag)s (nur die letzten %(monate)s '
                                          'Monate). Das PDF für das Grundbuchamt liegt bereit.')
                         % {'betrag': pf.betrag_pfandberechtigt, 'monate': inkasso.PFANDRECHT_MONATE})
    except inkasso.InkassoFehler as fehler:
        messages.error(request, str(fehler))
    return _zurueck(lg)


@rolle_erforderlich(*SCHREIB_ROLLEN)
@require_POST
def stweg_pfandrecht_eingetragen(request, pk):
    pf = get_object_or_404(StwegPfandrecht.objects.select_related('fall__einheit__liegenschaft'), pk=pk)
    inkasso.pfandrecht_eingetragen(pf, parse_date(request.POST.get('datum') or ''))
    messages.success(request, gettext('Eintragung im Grundbuch vermerkt.'))
    return _zurueck(pf.fall.einheit.liegenschaft)


def _pdf(inhalt, name):
    antwort = HttpResponse(inhalt, content_type='application/pdf')
    antwort['Content-Disposition'] = f'inline; filename="{name}"'
    return antwort


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_mahnung_pdf(request, pk):
    from stweg.pdf import mahnung_pdf
    m = get_object_or_404(StwegMahnung.objects.select_related('fall__einheit__liegenschaft'), pk=pk)
    return _pdf(mahnung_pdf(m), f'Mahnung_{m.stufe}.pdf')


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_pfandrecht_pdf(request, pk):
    from stweg.pdf import pfandrecht_pdf
    pf = get_object_or_404(StwegPfandrecht.objects.select_related('fall__einheit__liegenschaft'), pk=pk)
    return _pdf(pfandrecht_pdf(pf), 'Pfandrecht_Grundbuchamt.pdf')


@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_inkassofall_pdf(request, pk):
    """Mitteilung über das Retentionsrecht."""
    from stweg.pdf import retention_pdf
    fall = get_object_or_404(StwegInkassoFall.objects.select_related('einheit__liegenschaft'), pk=pk)
    if not fall.retention_erklaert_am:
        from django.http import Http404
        raise Http404
    return _pdf(retention_pdf(fall), 'Retentionsrecht.pdf')




@rolle_erforderlich(*TEAM_ROLLEN)
def stweg_handaenderung_pdf(request, pk):
    """Handänderungs-Abrechnung (pro rata temporis) zu einem erfassten Eigentümerwechsel."""
    from stweg.models import StwegEigentuemerwechsel
    from stweg.pdf import handaenderung_pdf
    w = get_object_or_404(StwegEigentuemerwechsel.objects.select_related('einheit__liegenschaft', 'neu', 'bisheriger'),
                          pk=pk)
    return _pdf(handaenderung_pdf(w), 'Handaenderung.pdf')
