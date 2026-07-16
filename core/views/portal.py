# core/views/portal.py
"""
Eigentümer-Portal (read-only).

Ein Mandant (Eigentümer) kann über crm.Mandant.benutzer mit einem Login
verknüpft werden. Er sieht hier NUR seine eigenen Liegenschaften — keine
Mieterdetails anderer Mandanten, kein SPA, keine API (core/auth.py sperrt
Eigentümer-Logins dort aus).
"""
import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.cache import never_cache

from core.auth import hat_rolle, ist_eigentuemer, TEAM_ROLLEN
from rentals.models import Mietvertrag


@login_required
def nach_login_view(request):
    """Login-Weiche: Team → /neu/, Eigentümer → Portal, Mieter → Mieterportal."""
    if getattr(request.user, 'mandant_profil', None) is not None:
        return redirect('portal')
    if hat_rolle(request.user, TEAM_ROLLEN):
        return redirect('fw_dashboard')
    if ist_eigentuemer(request.user):
        return redirect('portal')
    if getattr(request.user, 'mieter_profil', None) is not None:
        return redirect('mieter_portal')
    # Login ohne Rolle und ohne Verknüpfung: zurück zum Login
    # (Rolle muss zuerst von der Verwaltung zugewiesen werden).
    return redirect('login')


@never_cache
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
    from django.utils import timezone
    steuerjahr = timezone.localdate().year - 1
    return render(request, 'core/portal.html', {
        'mandant': mandant, 'freigaben': freigaben, 'steuerjahr': steuerjahr, **daten})


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


@never_cache
@login_required
def portal_steuerauszug_pdf(request):
    """Steuerauszug (Liegenschaftsrechnung) für ein Jahr — nur eigene Mandate."""
    mandant = getattr(request.user, 'mandant_profil', None)
    if mandant is None:
        raise Http404
    import datetime
    heute = datetime.date.today()
    try:
        jahr = int(request.GET.get('jahr') or (heute.year - 1))
    except (TypeError, ValueError):
        jahr = heute.year - 1
    # Plausibler Bereich
    jahr = max(2000, min(jahr, heute.year))
    from core.services.steuerauszug import generate_steuerauszug_pdf
    pdf = generate_steuerauszug_pdf(mandant, jahr)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Steuerauszug_{jahr}.pdf"'
    return resp


# ============================================================
# MIETERPORTAL (Self-Service für Mieter mit Login)
# ============================================================

def _ist_mieter_q(mieter):
    """Verträge, bei denen die Person Erst- ODER Mitmieter ist (2-Personen-Verträge)."""
    from django.db.models import Q
    return Q(mieter=mieter) | Q(mitmieter=mieter)

# ---------------------------------------------------------------------------
# Gemeinsame Datenbeschaffung fürs Mieterportal (von mehreren Views genutzt)
# ---------------------------------------------------------------------------
def _mieter_objekte(mieter):
    """Aktive Mietobjekte des Mieters (Erst- und Mitmieter) als Anzeige-Dicts."""
    vertraege = (Mietvertrag.objects
                 .filter(_ist_mieter_q(mieter), status='aktiv')
                 .select_related('einheit__liegenschaft').order_by('-beginn'))
    objekte = []
    for v in vertraege:
        e = v.einheit
        lg = e.liegenschaft if e else None
        objekte.append({
            'vertrag': v, 'einheit': e, 'liegenschaft': lg,
            'adresse': f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else '—',
            'brutto': v.brutto_mietzins, 'netto': v.netto_mietzins, 'nk': v.nebenkosten,
            'beginn': v.beginn, 'kaution': v.kautions_betrag,
        })
    return vertraege, objekte


def _mieter_dok_gruppen(mieter, vertraege):
    """Portal-sichtbare Dokumente, nach Kategorie gruppiert."""
    from django.db.models import Q
    from rentals.models import Dokument as RDokument
    alle_vertrag_ids = list(Mietvertrag.objects.filter(_ist_mieter_q(mieter)).values_list('id', flat=True))
    einheit_ids = [v.einheit_id for v in vertraege if v.einheit_id]
    # Die Einheit-Zuordnung darf NUR echte Objektdokumente einschliessen (ohne Mieter-/
    # Vertragsbezug — z. B. Hausordnung). Sonst sähe der neue Mieter einer Einheit die
    # portal-sichtbaren Dokumente des Vormieters (Datenschutz-Leck). Eigene Dokumente
    # laufen über mieter=… bzw. die eigenen Verträge.
    dok_qs = (RDokument.objects.filter(
                  Q(mieter=mieter) | Q(vertrag_id__in=alle_vertrag_ids)
                  | Q(einheit_id__in=einheit_ids, mieter__isnull=True, vertrag__isnull=True),
                  im_portal_sichtbar=True)
              .distinct().order_by('-datum')[:120])
    KAT_LABEL = {'vertrag': 'Vertrag', 'protokoll': 'Protokolle',
                 'korrespondenz': 'Korrespondenz', 'sonstiges': 'Dokumente'}
    KAT_ORDER = ['vertrag', 'korrespondenz', 'protokoll', 'sonstiges']
    gruppen = {}
    for d in dok_qs:
        if not d.datei:
            continue
        kat = d.kategorie or 'sonstiges'
        gruppen.setdefault(kat, []).append({'id': d.id, 'titel': d.bezeichnung or d.titel, 'datum': d.datum})
    return [{'label': KAT_LABEL.get(k, k.capitalize()), 'docs': gruppen[k]}
            for k in KAT_ORDER if gruppen.get(k)]


def _mieter_offene(mieter):
    """Offene Rechnungen (Erst- und Mitmieter) + Gesamtsumme."""
    from finance.models import DebitorenRechnung
    from django.utils import timezone
    alle_vertrag_ids = list(Mietvertrag.objects.filter(_ist_mieter_q(mieter)).values_list('id', flat=True))
    offene_qs = (DebitorenRechnung.objects
                 .filter(vertrag_id__in=alle_vertrag_ids, status__in=['offen', 'teilbezahlt'])
                 .select_related('vertrag').order_by('faellig_am'))
    heute = timezone.localdate()
    offene = []
    total_offen = Decimal('0.00')
    for r in offene_qs:
        betrag = r.offener_betrag if r.offener_betrag and r.offener_betrag > 0 else r.betrag
        total_offen += betrag
        offene.append({
            'id': r.id, 'titel': r.titel, 'betrag': betrag,
            'faellig': r.faellig_am,
            'ueberfaellig': bool(r.faellig_am and r.faellig_am < heute),
        })
    return offene, total_offen


def _mieter_ticket_count(mieter):
    from tickets.models import SchadenMeldung
    return SchadenMeldung.objects.filter(gemeldet_von=mieter).count()


@never_cache
@login_required
def mieter_portal_view(request):
    """Portal-Startseite (Dashboard): Mietobjekt(e) + Schnellzugriffe mit Zählern."""
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        if hat_rolle(request.user, TEAM_ROLLEN):
            return redirect('fw_dashboard')
        if getattr(request.user, 'mandant_profil', None) is not None:
            return redirect('portal')
        return render(request, 'core/mieter_portal.html', {'mieter': None})

    vertraege, objekte = _mieter_objekte(mieter)
    offene, total_offen = _mieter_offene(mieter)
    dok_gruppen = _mieter_dok_gruppen(mieter, vertraege)
    dok_count = sum(len(g['docs']) for g in dok_gruppen)
    return render(request, 'core/mieter_portal.html', {
        'mieter': mieter, 'objekte': objekte,
        'offene_count': len(offene), 'total_offen': total_offen,
        'dok_count': dok_count, 'ticket_count': _mieter_ticket_count(mieter),
    })


@never_cache
@login_required
def mieter_rechnungen_view(request):
    """Eigene Seite: offene Rechnungen mit QR-Einzahlschein."""
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        return redirect('mieter_portal')
    offene, total_offen = _mieter_offene(mieter)
    return render(request, 'core/mieter_rechnungen.html', {
        'mieter': mieter, 'offene': offene, 'total_offen': total_offen})


@never_cache
@login_required
def mieter_dokumente_view(request):
    """Eigene Seite: Dokumentenablage (Vertrag, Korrespondenz, Protokolle …)."""
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        return redirect('mieter_portal')
    vertraege, _objekte = _mieter_objekte(mieter)
    dok_gruppen = _mieter_dok_gruppen(mieter, vertraege)
    return render(request, 'core/mieter_dokumente.html', {
        'mieter': mieter, 'dok_gruppen': dok_gruppen})


@never_cache
@login_required
def mieter_schaden_formular(request):
    """Eigene Seite mit dem Schaden-Meldeformular (POST geht an mieter_schaden_melden)."""
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        return redirect('mieter_portal')
    _vertraege, objekte = _mieter_objekte(mieter)
    return render(request, 'core/mieter_schaden.html', {'mieter': mieter, 'objekte': objekte})


@login_required
def mieter_rechnung_qr(request, pk):
    """QR-Einzahlschein einer offenen Rechnung des eingeloggten Mieters."""
    from finance.models import DebitorenRechnung
    from core.services.debitor_qr import generate_debitor_qr_pdf
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        raise Http404
    vertrag_ids = list(Mietvertrag.objects.filter(_ist_mieter_q(mieter)).values_list('id', flat=True))
    r = get_object_or_404(DebitorenRechnung.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft'),
        pk=pk, vertrag_id__in=vertrag_ids)
    pdf = generate_debitor_qr_pdf(r)
    if pdf is None:
        raise Http404
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Rechnung_{r.id}.pdf"'
    return resp


@never_cache
@login_required
def mieter_kuendigung(request):
    """Mieter erfasst eine Kündigung für ein Objekt (Antrag) + Brief zum Download.
    Setzt den Vertrag NICHT automatisch auf gekündigt — die Verwaltung bestätigt."""
    from django.contrib import messages
    from rentals.models import Kuendigung
    from rentals.services import berechne_kuendigungstermin
    from django.utils import timezone
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        raise Http404

    vertraege = (Mietvertrag.objects.filter(_ist_mieter_q(mieter), status='aktiv')
                 .select_related('einheit__liegenschaft'))

    if request.method == 'POST':
        v = vertraege.filter(id=request.POST.get('vertrag_id') or None).first()
        if not v:
            messages.error(request, "Kein gültiges Mietobjekt gewählt.")
            return redirect('mieter_kuendigung')
        heute = timezone.localdate()
        wunsch = (request.POST.get('gewuenschtes_ende') or '').strip()
        try:
            gewuenscht = datetime.date.fromisoformat(wunsch) if wunsch else None
        except ValueError:
            gewuenscht = None
        termin = berechne_kuendigungstermin(v, heute)
        # Wirksames Ende: frühestens der ordentliche Termin (Wunsch nur, wenn später)
        per = gewuenscht if (gewuenscht and gewuenscht >= termin) else termin
        k = Kuendigung.objects.create(
            vertrag=v, absender='mieter', eingang_datum=heute,
            zustellung='einschreiben', gewuenschtes_ende=gewuenscht,
            berechneter_termin=termin, per_datum=per, status='erfasst',
            bemerkung=(request.POST.get('bemerkung') or '').strip())

        # Verwaltung benachrichtigen (E-Mail) + Journal-Notiz
        _benachrichtige_verwaltung_kuendigung(v, k)

        messages.success(request, f"✅ Ihre Kündigung wurde erfasst (Termin: {per.strftime('%d.%m.%Y')}). "
                         "Laden Sie den Kündigungsbrief herunter und senden Sie ihn per Einschreiben. "
                         "Die Verwaltung wurde informiert und bestätigt den Eingang.")
        return redirect('mieter_kuendigung')

    # GET: Objekte mit berechnetem Termin + bereits erfasste Kündigungen
    heute = timezone.localdate()
    objekte = []
    for v in vertraege:
        lg = v.einheit.liegenschaft if v.einheit_id else None
        objekte.append({
            'vertrag': v,
            'adresse': f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else '—',
            'einheit': v.einheit.bezeichnung if v.einheit_id else '',
            'termin': berechne_kuendigungstermin(v, heute),
            'frist': v.kuendigungsfrist_monate,
            'familienwohnung': bool(getattr(v, 'familienwohnung', False)) or bool(getattr(v, 'mitmieter_name', '')),
        })
    _vids = list(Mietvertrag.objects.filter(_ist_mieter_q(mieter)).values_list('id', flat=True))
    erfasste = (Kuendigung.objects.filter(vertrag_id__in=_vids)
                .select_related('vertrag__einheit__liegenschaft').order_by('-erstellt_am'))
    STATUS_LABEL = {'erfasst': 'Eingereicht', 'bestaetigt': 'Bestätigt',
                    'vollzogen': 'Vollzogen', 'zurueckgezogen': 'Zurückgezogen'}
    kuendigungen = [{
        'id': k.id, 'objekt': (k.vertrag.einheit.bezeichnung if k.vertrag.einheit_id else ''),
        'per': k.per_datum or k.berechneter_termin,
        'status': STATUS_LABEL.get(k.status, k.status),
        'eingereicht': k.eingang_datum,
    } for k in erfasste]
    return render(request, 'core/mieter_kuendigung.html', {
        'mieter': mieter, 'objekte': objekte, 'kuendigungen': kuendigungen,
        'heute_iso': heute.isoformat(),
    })


def _benachrichtige_verwaltung_kuendigung(vertrag, kuendigung):
    from crm.models import Verwaltung
    try:
        from crm.models import Kommunikation
        Kommunikation.objects.create(
            mieter=vertrag.mieter, vertrag=vertrag, typ='email', richtung='eingehend',
            betreff='Kündigung über Mieterportal',
            inhalt=f"Der Mieter hat über das Portal per {(kuendigung.per_datum or kuendigung.berechneter_termin)} gekündigt. "
                   "Bitte Eingang bestätigen und Kündigung prüfen (Familienwohnung/Unterschriften).")
    except Exception:
        pass
    vw = Verwaltung.objects.first()
    empfaenger = (vw.email if vw and vw.email else None)
    if empfaenger:
        try:
            from core.utils.email_service import send_ticket_email
            per = kuendigung.per_datum or kuendigung.berechneter_termin
            lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
            text = (f"Eingang einer Kündigung über das Mieterportal.\n\n"
                    f"Mieter: {vertrag.mieter.display_name}\n"
                    f"Objekt: {vertrag.einheit.bezeichnung if vertrag.einheit_id else ''}"
                    f"{(' · ' + lg.strasse + ', ' + lg.plz + ' ' + lg.ort) if lg else ''}\n"
                    f"Gewünschtes Vertragsende: {per.strftime('%d.%m.%Y') if per else '—'}\n\n"
                    "Bitte im System bestätigen. Der Mieter versendet zusätzlich den Kündigungsbrief per Einschreiben.")
            send_ticket_email(empfaenger, "Kündigung über Mieterportal", text)
        except Exception:
            pass


@login_required
def mieter_kuendigung_pdf(request, pk):
    """Kündigungsbrief (PDF) zu einer eigenen Kündigung."""
    from rentals.models import Kuendigung
    from crm.models import Verwaltung
    from core.services.kuendigung_brief import generate_kuendigung_mieter_pdf
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        raise Http404
    _vids = list(Mietvertrag.objects.filter(_ist_mieter_q(mieter)).values_list('id', flat=True))
    k = get_object_or_404(Kuendigung.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'),
        pk=pk, vertrag_id__in=_vids)
    lg = k.vertrag.einheit.liegenschaft if k.vertrag.einheit_id else None
    mandant = lg.mandant if lg else None
    pdf = generate_kuendigung_mieter_pdf(k.vertrag, k, verwaltung=Verwaltung.objects.first(), mandant=mandant)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = 'inline; filename="Kuendigung.pdf"'
    return resp


@login_required
def mieter_kontoauszug_pdf(request):
    """Kontoauszug (PDF) des eingeloggten Mieters."""
    from crm.models import Verwaltung
    from core.services.mieterkonto import generate_mieterkonto_pdf
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        raise Http404
    pdf = generate_mieterkonto_pdf(mieter, verwaltung=Verwaltung.objects.first())
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = 'inline; filename="Kontoauszug.pdf"'
    return resp


@login_required
def mieter_dokument_download(request, pk):
    """Dokument-Download — nur portal-freigegebene Dokumente am Mieter oder
    seinem Vertrag/Objekt."""
    from django.db.models import Q
    from rentals.models import Dokument as RDokument, Mietvertrag
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        raise Http404
    meine = Mietvertrag.objects.filter(_ist_mieter_q(mieter))
    vertrag_ids = list(meine.values_list('id', flat=True))
    einheit_ids = [e for e in meine.values_list('einheit_id', flat=True) if e]
    # Einheit-Zuordnung nur für echte Objektdokumente (ohne Mieter-/Vertragsbezug) —
    # sonst könnte der neue Mieter einer Einheit die Dokumente des Vormieters per ID
    # herunterladen (identisch zur Sichtbarkeitsregel in _mieter_dok_gruppen).
    dok = get_object_or_404(
        RDokument.objects.filter(
            Q(mieter=mieter) | Q(vertrag_id__in=vertrag_ids)
            | Q(einheit_id__in=einheit_ids, mieter__isnull=True, vertrag__isnull=True),
            im_portal_sichtbar=True),
        pk=pk)
    try:
        f = dok.datei.open('rb')
    except Exception:
        raise Http404
    import os
    resp = HttpResponse(f.read(), content_type='application/octet-stream')
    resp['Content-Disposition'] = f'attachment; filename="{os.path.basename(dok.datei.name)}"'
    return resp


@login_required
def mieter_schaden_melden(request):
    """Mieter meldet einen Schaden aus dem Portal (erzeugt ein Ticket)."""
    from django.contrib import messages
    from tickets.models import SchadenMeldung
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None or request.method != 'POST':
        return redirect('mieter_portal')
    titel = (request.POST.get('titel') or '').strip()
    beschreibung = (request.POST.get('beschreibung') or '').strip()
    vertrag_id = request.POST.get('vertrag_id')
    if not titel or not beschreibung:
        messages.error(request, "Bitte Titel und Beschreibung angeben.")
        return redirect('mieter_schaden_formular')
    v = (Mietvertrag.objects.filter(_ist_mieter_q(mieter), id=vertrag_id)
         .select_related('einheit__liegenschaft').first()) if vertrag_id else None
    if not v:
        v = (Mietvertrag.objects.filter(_ist_mieter_q(mieter), status='aktiv')
             .select_related('einheit__liegenschaft').first())
    if not v or not v.einheit_id:
        messages.error(request, "Kein aktives Mietobjekt gefunden.")
        return redirect('mieter_portal')
    t = SchadenMeldung.objects.create(
        liegenschaft=v.einheit.liegenschaft, betroffene_einheit=v.einheit,
        gemeldet_von=mieter, titel=titel, beschreibung=beschreibung,
        raum=(request.POST.get('raum') or '').strip(),
        melder_vorname=mieter.vorname or '', melder_nachname=mieter.nachname or '',
        email_melder=mieter.email or '', tel_melder=mieter.mobile or mieter.telefon_privat or '',
        status='neu', gelesen=False)

    # 1) Eingangsbestätigung an den Mieter, 2) Benachrichtigung an die Verwaltung
    _benachrichtige_neue_meldung(t, v)

    messages.success(request, "✅ Ihre Schadenmeldung wurde übermittelt. Sie erhalten eine Bestätigung per E-Mail; die Verwaltung kümmert sich darum.")
    return redirect('mieter_portal')


def _benachrichtige_neue_meldung(ticket, vertrag):
    """Mieter erhält Eingangsbestätigung, Verwaltung/Eigentümer die Meldung.
    Fehler beim Mailversand dürfen die Schadenmeldung nie blockieren."""
    from core.utils.email_service import send_ticket_email, send_neue_meldung_intern
    from crm.models import Verwaltung
    # Mieter-Bestätigung
    try:
        if ticket.email_melder:
            body = (f"Guten Tag\n\nWir haben Ihre Schadenmeldung '{ticket.titel}' erhalten "
                    f"(Ticket #{ticket.id}) und kümmern uns darum. Sobald ein Handwerker "
                    f"beauftragt wurde, informieren wir Sie.\n\n"
                    f"Freundliche Grüsse\nIhre Liegenschaftsverwaltung")
            send_ticket_email(ticket.email_melder, f"Eingangsbestätigung: {ticket.titel} (Ticket #{ticket.id})", body)
    except Exception:
        pass
    # Verwaltung/Eigentümer-Benachrichtigung
    try:
        send_neue_meldung_intern(ticket, _verwaltung_empfaenger(ticket.liegenschaft))
    except Exception:
        pass


def _verwaltung_empfaenger(lg):
    """E-Mail-Empfänger auf Verwaltungsseite (Verwaltung + ggf. Eigentümer)."""
    from crm.models import Verwaltung
    empf = []
    vw = (lg.verwaltung if lg and lg.verwaltung_id else None) or Verwaltung.objects.first()
    if vw and vw.email:
        empf.append(vw.email)
    if lg and lg.mandant_id and lg.mandant.email:
        empf.append(lg.mandant.email)
    return empf


# Status → (Label, Tailwind-Klassen) fürs Mieterportal
TICKET_STATUS_PILL = {
    'neu':                  ('Neu',                 'bg-rose-100 text-rose-700'),
    'in_bearbeitung':       ('In Bearbeitung',      'bg-sky-100 text-sky-700'),
    'warte_auf_mieter':     ('Warte auf Sie',       'bg-amber-100 text-amber-700'),
    'warte_auf_handwerker': ('Handwerker beauftragt','bg-indigo-100 text-indigo-700'),
    'erledigt':             ('Erledigt',            'bg-emerald-100 text-emerald-700'),
}


@never_cache
@login_required
def mieter_tickets_view(request):
    """Übersicht aller vom Mieter gemeldeten Schäden mit Status."""
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        return redirect('mieter_portal')
    from tickets.models import SchadenMeldung
    qs = (SchadenMeldung.objects.filter(gemeldet_von=mieter)
          .select_related('liegenschaft', 'betroffene_einheit').order_by('-erstellt_am'))
    tickets = []
    for t in qs:
        label, cls = TICKET_STATUS_PILL.get(t.status, (t.status, 'bg-slate-100 text-slate-600'))
        tickets.append({'t': t, 'status_label': label, 'status_cls': cls,
                        'objekt': f"{t.liegenschaft.strasse}" if t.liegenschaft_id else '—'})
    return render(request, 'core/mieter_tickets.html', {'mieter': mieter, 'tickets': tickets})


@never_cache
@login_required
def mieter_ticket_detail(request, pk):
    """Ticket-Detail mit Status + Nachrichtenverlauf; Mieter kann antworten."""
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None:
        return redirect('mieter_portal')
    from tickets.models import SchadenMeldung
    t = get_object_or_404(SchadenMeldung, pk=pk, gemeldet_von=mieter)
    label, cls = TICKET_STATUS_PILL.get(t.status, (t.status, 'bg-slate-100 text-slate-600'))
    # Nur mieter-relevante Verlaufseinträge (keine internen Notizen / Handwerker-Mails)
    verlauf = (t.nachrichten.exclude(is_intern=True)
               .exclude(typ='handwerker_mail').order_by('erstellt_am'))
    return render(request, 'core/mieter_ticket_detail.html', {
        'mieter': mieter, 't': t, 'status_label': label, 'status_cls': cls,
        'verlauf': verlauf,
        'objekt': f"{t.liegenschaft.strasse}, {t.liegenschaft.ort}" if t.liegenschaft_id else '—',
    })


@never_cache
@login_required
def mieter_ticket_nachricht(request, pk):
    """Mieter schreibt eine Nachricht zu seinem Ticket → Verlauf + Mail an Verwaltung."""
    from django.contrib import messages
    mieter = getattr(request.user, 'mieter_profil', None)
    if mieter is None or request.method != 'POST':
        return redirect('mieter_portal')
    from tickets.models import SchadenMeldung, TicketNachricht
    t = get_object_or_404(SchadenMeldung, pk=pk, gemeldet_von=mieter)
    text = (request.POST.get('text') or '').strip()
    if not text:
        return redirect(f'/mieter/ticket/{t.id}/')
    TicketNachricht.objects.create(ticket=t, absender_name=mieter.display_name, typ='chat',
                                   nachricht=text, is_von_verwaltung=False, gelesen=False)
    # Ticket wieder als ungelesen markieren → Sidebar-Badge beim Verwalter
    t.gelesen = False
    if t.status == 'erledigt':
        t.status = 'in_bearbeitung'
    t.save(update_fields=['gelesen', 'status'])
    # Verwaltung per E-Mail benachrichtigen
    try:
        from core.utils.email_service import send_ticket_email
        body = (f"Neue Nachricht von {mieter.display_name} zu Ticket #{t.id} ({t.titel}):\n\n"
                f"{text}\n\nBitte im Cockpit unter Schadensfälle beantworten.")
        for adr in _verwaltung_empfaenger(t.liegenschaft):
            send_ticket_email(adr, f"Mieter-Nachricht zu Ticket #{t.id}: {t.titel}", body)
    except Exception:
        pass
    messages.success(request, "✅ Ihre Nachricht wurde übermittelt. Die Verwaltung meldet sich.")
    return redirect(f'/mieter/ticket/{t.id}/')
