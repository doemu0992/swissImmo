# core/views/portal.py
"""
Eigentümer-Portal (read-only).

Ein Mandant (Eigentümer) kann über crm.Mandant.benutzer mit einem Login
verknüpft werden. Er sieht hier NUR seine eigenen Liegenschaften — keine
Mieterdetails anderer Mandanten, kein SPA, keine API (core/auth.py sperrt
Eigentümer-Logins dort aus).
"""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404

from core.auth import hat_rolle, ist_eigentuemer, TEAM_ROLLEN
from rentals.models import Mietvertrag


@login_required
def nach_login_view(request):
    """Login-Weiche: Team → neue Oberfläche (/neu/), Eigentümer → Portal."""
    if getattr(request.user, 'mandant_profil', None) is not None:
        return redirect('portal')
    if hat_rolle(request.user, TEAM_ROLLEN):
        return redirect('fw_dashboard')
    if ist_eigentuemer(request.user):
        return redirect('portal')
    # Login ohne Rolle und ohne Mandant-Verknüpfung: zurück zum Login
    # (Rolle muss zuerst von der Verwaltung zugewiesen werden).
    return redirect('login')


@login_required
def portal_view(request):
    mandant = getattr(request.user, 'mandant_profil', None)

    # Team-Mitglieder ohne Mandant-Verknüpfung gehören in die neue Oberfläche
    if mandant is None:
        if hat_rolle(request.user, TEAM_ROLLEN):
            return redirect('fw_dashboard')
        return render(request, 'core/portal.html', {'mandant': None})

    daten = _portfolio_daten(mandant)
    freigaben = _offene_freigaben(mandant)
    return render(request, 'core/portal.html', {'mandant': mandant, 'freigaben': freigaben, **daten})


def _offene_freigaben(mandant):
    """Handwerker-Aufträge, die auf die Freigabe dieses Eigentümers warten."""
    from tickets.models import HandwerkerAuftrag
    lg_ids = list(mandant.liegenschaften.values_list('id', flat=True))
    qs = (HandwerkerAuftrag.objects
          .filter(freigabe_status='ausstehend', ticket__liegenschaft_id__in=lg_ids)
          .select_related('ticket__liegenschaft', 'handwerker').order_by('-id'))
    out = []
    for a in qs:
        t = a.ticket
        out.append({
            'id': a.id,
            'titel': t.titel,
            'liegenschaft': f"{t.liegenschaft.strasse}, {t.liegenschaft.ort}" if t.liegenschaft_id else '—',
            'handwerker': a.handwerker.firma if a.handwerker_id else '—',
            'kosten': a.kosten_geschaetzt,
            'bemerkung': a.bemerkung,
        })
    return out


@login_required
def portal_freigabe(request, pk):
    """Eigentümer gibt einen Reparatur-Auftrag frei oder lehnt ihn ab."""
    from django.utils import timezone
    from tickets.models import HandwerkerAuftrag, TicketNachricht
    mandant = getattr(request.user, 'mandant_profil', None)
    if mandant is None or request.method != 'POST':
        raise Http404
    lg_ids = list(mandant.liegenschaften.values_list('id', flat=True))
    a = get_object_or_404(HandwerkerAuftrag.objects.select_related('ticket'),
                          pk=pk, ticket__liegenschaft_id__in=lg_ids)
    if a.freigabe_status != 'ausstehend':
        return redirect('portal')
    aktion = request.POST.get('aktion')
    kommentar = (request.POST.get('kommentar') or '').strip()
    if aktion == 'freigeben':
        a.freigabe_status = 'freigegeben'
    elif aktion == 'ablehnen':
        a.freigabe_status = 'abgelehnt'
    else:
        return redirect('portal')
    a.freigabe_datum = timezone.now()
    a.freigabe_kommentar = kommentar
    a.save(update_fields=['freigabe_status', 'freigabe_datum', 'freigabe_kommentar'])
    # Aktennotiz am Ticket hinterlassen (für die Verwaltung sichtbar)
    try:
        label = 'freigegeben' if a.freigabe_status == 'freigegeben' else 'abgelehnt'
        TicketNachricht.objects.create(
            ticket=a.ticket, absender_name=mandant.firma_oder_name, typ='system',
            nachricht=f"Reparatur vom Eigentümer {label}." + (f" Kommentar: {kommentar}" if kommentar else ''),
            is_intern=True)
    except Exception:
        pass
    return redirect('portal')


def _portfolio_daten(mandant):
    """Sammelt Rendite-Cockpit-Kennzahlen, Objektlisten und Dokumente."""
    from portfolio.models import Dokument as PDokument
    liegenschaften = []
    total_soll = Decimal('0.00')
    total_einheiten = 0
    total_vermietet = 0
    total_versicherungswert = Decimal('0.00')

    for lg in mandant.liegenschaften.all().prefetch_related('einheiten'):
        einheiten_rows = []
        lg_soll = Decimal('0.00')
        lg_einheiten = 0
        lg_vermietet = 0

        for e in lg.einheiten.all():
            vertrag = (
                Mietvertrag.objects
                .filter(einheit=e, status='aktiv')
                .select_related('mieter')
                .order_by('-beginn')
                .first()
            )
            brutto = vertrag.brutto_mietzins if vertrag else Decimal('0.00')
            lg_soll += brutto
            total_einheiten += 1
            lg_einheiten += 1
            if vertrag:
                total_vermietet += 1
                lg_vermietet += 1

            einheiten_rows.append({
                'bezeichnung': e.bezeichnung,
                'typ': e.get_typ_display(),
                'zimmer': e.zimmer,
                'flaeche': e.flaeche_m2,
                'mieter': str(vertrag.mieter) if vertrag else None,
                'seit': vertrag.beginn if vertrag else None,
                'brutto': brutto if vertrag else None,
            })

        total_soll += lg_soll
        vw = lg.versicherungswert or Decimal('0.00')
        total_versicherungswert += vw
        lg_jahr = lg_soll * 12
        lg_rendite = (float(lg_jahr) / float(vw) * 100) if vw else None
        lg_leer = lg_einheiten - lg_vermietet

        dok_qs = PDokument.objects.filter(liegenschaft=lg).order_by('-datum')[:20]
        dokumente = [{'id': d.id, 'titel': d.titel, 'kategorie': d.kategorie, 'datum': d.datum}
                     for d in dok_qs]

        liegenschaften.append({
            'id': lg.id,
            'adresse': f"{lg.strasse}, {lg.plz} {lg.ort}",
            'baujahr': lg.baujahr,
            'einheiten': einheiten_rows,
            'soll_monat': lg_soll,
            'jahres_soll': lg_jahr,
            'versicherungswert': vw if vw else None,
            'rendite': lg_rendite,
            'leer': lg_leer,
            'leerquote': (lg_leer / lg_einheiten * 100) if lg_einheiten else 0,
            'dokumente': dokumente,
        })

    total_leer = total_einheiten - total_vermietet
    jahres_soll = total_soll * 12
    bruttorendite = (float(jahres_soll) / float(total_versicherungswert) * 100) if total_versicherungswert else None
    leerquote = (total_leer / total_einheiten * 100) if total_einheiten else 0

    return {
        'liegenschaften': liegenschaften,
        'total_soll': total_soll,
        'jahres_soll': jahres_soll,
        'total_einheiten': total_einheiten,
        'total_vermietet': total_vermietet,
        'total_leer': total_leer,
        'total_versicherungswert': total_versicherungswert if total_versicherungswert else None,
        'bruttorendite': bruttorendite,
        'leerquote': leerquote,
    }


@login_required
def portal_dokument_download(request, pk):
    """Dokument-Download — nur für Dokumente von Liegenschaften des eigenen Mandanten."""
    from portfolio.models import Dokument as PDokument
    mandant = getattr(request.user, 'mandant_profil', None)
    if mandant is None:
        raise Http404
    dok = get_object_or_404(PDokument, pk=pk)
    if not dok.liegenschaft_id or dok.liegenschaft.mandant_id != mandant.id:
        raise Http404
    try:
        f = dok.datei.open('rb')
    except Exception:
        raise Http404
    resp = HttpResponse(f.read(), content_type='application/octet-stream')
    import os
    name = os.path.basename(dok.datei.name)
    resp['Content-Disposition'] = f'attachment; filename="{name}"'
    return resp


@login_required
def portal_report_pdf(request):
    """Portfolio-Report (PDF) für den eingeloggten Eigentümer."""
    mandant = getattr(request.user, 'mandant_profil', None)
    if mandant is None:
        raise Http404
    daten = _portfolio_daten(mandant)
    from core.services.portfolio_report import generate_portfolio_report
    pdf = generate_portfolio_report(mandant, daten)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = 'inline; filename="Portfolio-Report.pdf"'
    return resp
