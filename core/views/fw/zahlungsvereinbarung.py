# core/views/fw/zahlungsvereinbarung.py
#
# Zahlungsvereinbarung und Schreiben (PDF).
# Aus kuendigung.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from datetime import date

from django.utils.translation import gettext
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, VERWALTUNGS_ROLLEN)
from rentals.models import Mietvertrag

from ._basis import _global_filter


# Eine Zahlungsvereinbarung nimmt die gedeckten Forderungen aus dem Mahnlauf und
# verschiebt ihre Fälligkeit im Gespräch mit dem Mieter — eine Entscheidung der
# Verwaltung, wie die Fristansetzung.
@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_zahlungsvereinbarung(request, vertrag_id):
    """Ratenplan für einen Rückstand (core/services/zahlungsvereinbarung.py)."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.auth import log_aktion
    from core.services import zahlungsvereinbarung as zv
    from core.services.zahlungsverzug import aktive_fristen, faelliger_rueckstand

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'),
                          id=vertrag_id)
    basis = _global_filter(request)
    heute = timezone.localdate()

    if request.method == 'POST':
        aktion = request.POST.get('aktion', 'anlegen')
        if aktion == 'abbrechen':
            vereinb = v.zahlungsvereinbarungen.filter(pk=request.POST.get('vereinbarung') or 0,
                                                      status='aktiv').first()
            if vereinb:
                zv.abbrechen(vereinb)
                log_aktion(request, 'Zahlungsvereinbarung abgebrochen', str(v.mieter), f'#{vereinb.pk}', ziel=v)
                messages.success(request, gettext('Zahlungsvereinbarung abgebrochen — die gedeckten Forderungen laufen wieder im Mahnlauf.'))
            return redirect(f'/neu/vertraege/{v.id}/zahlungsvereinbarung/')
        try:
            raten = int(request.POST.get('anzahl_raten') or 0)
            intervall = int(request.POST.get('intervall_monate') or 1)
            erste = date.fromisoformat(request.POST.get('erste_rate') or '')
        except ValueError:
            messages.error(request, gettext('Bitte Anzahl Raten, Abstand und Datum der ersten Rate angeben.'))
            return redirect(f'/neu/vertraege/{v.id}/zahlungsvereinbarung/')
        try:
            vereinb = zv.anlegen(v, raten, erste, intervall, user=request.user,
                                 notiz=(request.POST.get('notiz') or '').strip())
        except ValueError as exc:
            messages.error(request, f'❌ {exc}')
            return redirect(f'/neu/vertraege/{v.id}/zahlungsvereinbarung/')
        log_aktion(request, 'Zahlungsvereinbarung erfasst', str(v.mieter),
                   f'CHF {vereinb.betrag_total:.2f} in {raten} Raten ab {erste:%d.%m.%Y}', ziel=v)
        messages.success(request, '✅ ' + gettext('Zahlungsvereinbarung erfasst — die gedeckten Forderungen ruhen im Mahnlauf, %(n)s Raten-Pendenzen angelegt.') % {'n': raten})
        messages.info(request, gettext('Das Schreiben «Zahlungsvereinbarung mit Schuldanerkennung» steht bereit — zweifach ausdrucken und unterzeichnen lassen.'))
        return redirect(f'/neu/vertraege/{v.id}/zahlungsvereinbarung/')

    vereinbarungen = []
    for vb in v.zahlungsvereinbarungen.all():
        vereinbarungen.append({
            'v': vb, 'plan': zv.raten_plan(vb),
            'bezahlt': zv.bezahlt(vb), 'offen': zv.rueckstand(vb),
            'forderungen': zv.gedeckte_forderungen(vb) if vb.status == 'aktiv' else []})
    return render(request, 'fw/zahlungsvereinbarung.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'vereinbarungen': vereinbarungen,
        'rueckstand': faelliger_rueckstand(v, stichtag=heute),
        'frist_laeuft': aktive_fristen(v).exists(),
        'heute_iso': heute.isoformat(),
        'toleranz_tage': zv.TOLERANZ_TAGE,
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_zahlungsvereinbarung_pdf(request, vertrag_id):
    """«Zahlungsvereinbarung mit Schuldanerkennung» als PDF. GET ist die Vorschau und
    schreibt nichts; erst POST («Erstellen») legt sie in der Vertragsakte ab (ROUTE-01).

    `?vb=<id>` wählt die Vereinbarung; gesucht wird über den Rückbezug DIESES
    Vertrags — eine fremde ID findet nichts (404). Ohne Angabe die neueste.
    Dieselbe Rolle wie die Vereinbarung selbst: Das Schreiben ist die Erklärung
    der Vermieterin, die der Mieter unterschreibt."""
    from django.http import Http404, HttpResponse

    from core.auth import log_aktion
    from core.services.ablage import ablegen
    from core.services.inkasso_briefe import zahlungsvereinbarung_pdf

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft__eigentuemer'),
                          id=vertrag_id)
    qs = v.zahlungsvereinbarungen.all()
    roh = request.GET.get('vb') or ''
    if roh:
        if not roh.isdigit():
            raise Http404
        vb = qs.filter(pk=int(roh)).first()
    else:
        vb = qs.first()
    if vb is None:
        raise Http404
    pdf = zahlungsvereinbarung_pdf(vb)
    titel = f"Zahlungsvereinbarung mit Schuldanerkennung #{vb.pk}"
    if request.method == 'POST':
        # dedup: erneutes Erstellen legt eine neue Fassung desselben Titels an,
        # statt die Akte mit Kopien zu füllen.
        ablegen(pdf, titel, kategorie='vertrag', vertrag=v, dedup=True,
                dateiname=f"Zahlungsvereinbarung_{v.mieter.nachname or v.id}_{vb.pk}.pdf")
        log_aktion(request, "Zahlungsvereinbarung (Schreiben) erstellt", str(v.mieter), titel, ziel=v)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Zahlungsvereinbarung_{vb.pk}.pdf"'
    return resp
