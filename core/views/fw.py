# core/views/fw.py
"""
Fairwalter-Rebuild: neue Oberfläche (/neu/…) auf bestehendem Backend.
Referenz: Original-Screenshots in REBUILD.md. Server-gerendert, testbar.

Der 'Globale Filter' (?lg=<id>) filtert alle Kennzahlen auf eine Liegenschaft —
er wird in _global_filter() gelesen und an jede Seite durchgereicht.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum, F
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from core.auth import rolle_erforderlich, TEAM_ROLLEN, SCHREIB_ROLLEN, ROLLE_VERWALTUNG, VERWALTUNGS_ROLLEN
from core.views.dashboard_view import _berechne_aufgaben
from crm.models import Mieter
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag


def _global_filter(request):
    """Liest den globalen Liegenschafts-Filter (?lg=) und liefert Basis-Kontext."""
    lg_id = request.GET.get('lg') or None
    aktive_lg = None
    if lg_id:
        aktive_lg = Liegenschaft.objects.filter(id=lg_id).first()
    return {
        'alle_liegenschaften': Liegenschaft.objects.all().order_by('strasse'),
        'aktive_lg': aktive_lg,
        'lg_query': f"?lg={aktive_lg.id}" if aktive_lg else "",
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_dashboard(request):
    heute = timezone.now().date()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    einheiten = Einheit.objects.all()
    vertraege = Mietvertrag.objects.all()
    liegenschaften = Liegenschaft.objects.all()
    if aktive_lg:
        einheiten = einheiten.filter(liegenschaft=aktive_lg)
        vertraege = vertraege.filter(einheit__liegenschaft=aktive_lg)
        liegenschaften = liegenschaften.filter(id=aktive_lg.id)

    # --- PORTFOLIO (Karte 2: Mietobjekte mit Breakdown) ---
    typ_map = {'whg': 'wohnen', 'stwe': 'wohnen', 'pp': 'parkplatz', 'gar': 'parkplatz',
               'gew': 'gewerbe', 'bas': 'weitere'}
    breakdown = {'wohnen': 0, 'parkplatz': 0, 'gewerbe': 0, 'weitere': 0}
    for e in einheiten:
        breakdown[typ_map.get(e.typ, 'weitere')] += 1

    # --- VERTRÄGE (Karte 3: Status-Breakdown wie Fairwalter) ---
    v_beendet = vertraege.filter(status='archiviert').count() + \
                vertraege.exclude(status='archiviert').filter(ende__lt=heute).count()
    v_aktiv = vertraege.filter(status='aktiv').exclude(ende__lt=heute).count()
    v_gekuendigt = vertraege.filter(status='gekuendigt').count()
    v_zukuenftig = vertraege.filter(beginn__gt=heute).exclude(status__in=['archiviert', 'gekuendigt']).count()

    # --- LEERSTAND-KARTE (Tabs: Leerstand / Gekündigt / Bevorstehend) ---
    belegte_ids = set(vertraege.filter(status='aktiv').values_list('einheit_id', flat=True))
    for neben_id in vertraege.filter(status='aktiv').values_list('nebenobjekte', flat=True):
        if neben_id:
            belegte_ids.add(neben_id)
    leerstand_objekte = (einheiten.exclude(id__in=belegte_ids)
                         .select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'))
    gekuendigte = (vertraege.filter(status='gekuendigt')
                   .select_related('mieter', 'einheit__liegenschaft').order_by('ende'))
    bevorstehende = (vertraege.filter(beginn__gt=heute)
                     .exclude(status__in=['archiviert', 'gekuendigt'])
                     .select_related('mieter', 'einheit__liegenschaft').order_by('beginn'))

    # --- KPIs (Bewirtschafter-Kennzahlen) ---
    objekte_total = einheiten.count()
    leer_count = leerstand_objekte.count()
    leerstandsquote = round(leer_count / objekte_total * 100, 1) if objekte_total else 0.0
    # Soll-Miete/Monat (Potenzial = alle Objekte zu Soll-Miete) und Ist (nur belegte)
    soll_potenzial = Decimal('0.00')
    ist_miete = Decimal('0.00')
    ausfall_leerstand = Decimal('0.00')
    for e in einheiten:
        miete = (e.nettomiete_aktuell or Decimal('0')) + (e.nebenkosten_aktuell or Decimal('0'))
        soll_potenzial += miete
        if e.id in belegte_ids:
            ist_miete += miete
        else:
            ausfall_leerstand += miete
    # ertragsgewichtete Leerstandsquote (Fr.-Ausfall / Potenzial)
    leerstandsquote_ertrag = round(float(ausfall_leerstand) / float(soll_potenzial) * 100, 1) if soll_potenzial else 0.0
    # Offene überfällige Forderungen (Mietzinsausfall/Debitorenrisiko)
    _deb = DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
    if aktive_lg:
        _deb = _deb.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    offen_ueberfaellig = sum((r.offener_betrag for r in _deb
                              if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) < heute), Decimal('0.00'))
    kpis = {
        'leerstandsquote': leerstandsquote,
        'leerstandsquote_ertrag': leerstandsquote_ertrag,
        'soll_potenzial': soll_potenzial,
        'ist_miete': ist_miete,
        'ausfall_leerstand': ausfall_leerstand,
        'offen_ueberfaellig': offen_ueberfaellig,
    }

    # --- COCKPIT (handlungsorientierte Widgets, verlinkt) ---
    from core.models import Pendenz
    from tickets.models import HandwerkerAuftrag
    from portfolio.models import Wartungsfrist
    from rentals.models import Kuendigung
    _pend = Pendenz.objects.filter(erledigt=False)
    _frist = Wartungsfrist.objects.filter(aktiv=True, naechste_faelligkeit__lte=heute + _timedelta(days=30))
    _freig = HandwerkerAuftrag.objects.filter(freigabe_status='ausstehend')
    _portal_kuend = Kuendigung.objects.filter(status='erfasst', absender='mieter')
    if aktive_lg:
        _pend = _pend.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
        _frist = _frist.filter(liegenschaft=aktive_lg)
        _freig = _freig.filter(ticket__liegenschaft=aktive_lg)
        _portal_kuend = _portal_kuend.filter(vertrag__einheit__liegenschaft=aktive_lg)
    debitoren_ueberfaellig_n = sum(1 for r in _deb
                                   if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) < heute)
    cockpit = {
        'pendenzen': _pend.count(),
        'pendenzen_ueberfaellig': _pend.filter(faellig_am__lt=heute).count(),
        'debitoren_n': debitoren_ueberfaellig_n,
        'debitoren_chf': offen_ueberfaellig,
        'freigaben': _freig.count(),
        'fristen': _frist.count(),
        'fristen_ueberfaellig': _frist.filter(naechste_faelligkeit__lt=heute).count(),
        'portal_kuendigungen': _portal_kuend.count(),
    }

    # --- HEUTE ZU TUN (konkrete, per Popup erledigbare Einträge) ---
    grenze14 = heute + _timedelta(days=14)
    dringend_pend = (_pend.filter(Q(faellig_am__lte=grenze14) | Q(faellig_am__isnull=True))
                     .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft')
                     .order_by(F('faellig_am').asc(nulls_last=True)))
    heute_todo = []
    for p in dringend_pend[:8]:
        url, label, wide = _pendenz_ziel(p)
        obj = ''
        if p.vertrag_id and p.vertrag and p.vertrag.einheit_id:
            obj = p.vertrag.einheit.bezeichnung
        elif p.liegenschaft_id:
            obj = p.liegenschaft.strasse
        heute_todo.append({
            'id': p.id, 'titel': p.titel, 'sub': obj,
            'faellig': p.faellig_am,
            'ueberfaellig': bool(p.faellig_am and p.faellig_am < heute),
            'url': url, 'label': label or 'Öffnen', 'wide': wide,
        })
    heute_todo_mehr = max(_pend.filter(Q(faellig_am__lte=grenze14) | Q(faellig_am__isnull=True)).count() - 8, 0)

    # --- Letzte kritische Aktionen aus dem Logbuch (nur Verwaltung) ---
    from core.auth import hat_rolle
    kritische_aktionen = []
    if hat_rolle(request.user, [ROLLE_VERWALTUNG]):
        from core.models import AktivitaetsLog
        kritische_aktionen = list(
            AktivitaetsLog.objects.filter(kategorie__in=AktivitaetsLog.KRITISCH)
            .select_related('benutzer')[:6])

    # --- AUFGABEN (bestehende Pendenzen-Engine wiederverwenden) ---
    aufgaben = _berechne_aufgaben(heute, leerstand_objekte.count(), 0, 0)
    # Aufgaben-Ziele auf die neue Oberfläche mappen, wo es ein Pendant gibt
    tab_ziel = {
        'finance': '/neu/debitoren/', 'rentals': '/neu/vertraege/',
        'portfolio': '/neu/liegenschaften/', 'crm': '/neu/personen/',
    }
    for a in aufgaben:
        a['ziel'] = tab_ziel.get(a.get('tab'), f"/app/?tab={a.get('tab')}")

    context = {
        **basis,
        'nav': 'dashboard',
        'liegenschaften_count': liegenschaften.count(),
        'objekte_count': einheiten.count(),
        'breakdown': breakdown,
        'vertraege_count': vertraege.count(),
        'v_beendet': v_beendet, 'v_aktiv': v_aktiv,
        'v_gekuendigt': v_gekuendigt, 'v_zukuenftig': v_zukuenftig,
        'leerstand_objekte': leerstand_objekte[:20],
        'leerstand_count': leerstand_objekte.count(),
        'gekuendigte': gekuendigte[:20],
        'gekuendigte_count': gekuendigte.count(),
        'bevorstehende': bevorstehende[:20],
        'bevorstehende_count': bevorstehende.count(),
        'aufgaben': aufgaben,
        'kpis': kpis,
        'cockpit': cockpit,
        'heute_todo': heute_todo,
        'heute_todo_mehr': heute_todo_mehr,
        'kritische_aktionen': kritische_aktionen,
    }
    return render(request, 'fw/dashboard.html', context)


# ============================================================
# ETAPPE B: LISTEN ALS DATENTABELLEN
# ============================================================

def _mahnstufe(faellig, heute, status):
    """Heuristische Mahnstufe aus dem Fälligkeitsdatum (bis Etappe D
    ein echtes Mahnwesen mit gespeicherten Stufen bringt)."""
    if status not in ('offen', 'teilbezahlt') or not faellig or faellig >= heute:
        return None
    tage = (heute - faellig).days
    if tage > 60:
        return {'label': '3. Mahnung', 'cls': 'bg-rose-100 text-rose-700', 'tage': tage}
    if tage > 30:
        return {'label': '2. Mahnung', 'cls': 'bg-rose-50 text-rose-600', 'tage': tage}
    if tage > 14:
        return {'label': '1. Mahnung', 'cls': 'bg-amber-100 text-amber-700', 'tage': tage}
    return {'label': 'Fällig', 'cls': 'bg-amber-50 text-amber-600', 'tage': tage}


STATUS_PILL = {
    'offen':       ('Offen',       'bg-amber-50 text-amber-700'),
    'teilbezahlt': ('Teilbezahlt', 'bg-sky-50 text-sky-700'),
    'bezahlt':     ('Bezahlt',     'bg-emerald-50 text-emerald-700'),
    'storniert':   ('Storniert',   'bg-slate-100 text-slate-500'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_debitoren(request):
    heute = timezone.now().date()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (DebitorenRechnung.objects
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft',
                          'liegenschaft', 'einheit__liegenschaft')
          .prefetch_related('zahlungseingaenge'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    # Filterzeile: Status-Chips + Suche
    status_filter = request.GET.get('status', '')
    if status_filter in STATUS_PILL:
        qs = qs.filter(status=status_filter)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(titel__icontains=q)
                       | Q(vertrag__mieter__vorname__icontains=q)
                       | Q(vertrag__mieter__nachname__icontains=q)
                       | Q(vertrag__mieter__firmen_name__icontains=q))

    rows = []
    total_offen = Decimal('0.00')
    anzahl_offen = 0
    anzahl_ueberfaellig = 0
    for r in qs:
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        einheit = r.einheit or (r.vertrag.einheit if r.vertrag_id else None)
        offen = r.offener_betrag if r.status in ('offen', 'teilbezahlt') else Decimal('0.00')
        faellig = r.faellig_am or r.datum
        mahn = _mahnstufe(faellig, heute, r.status)
        if r.status in ('offen', 'teilbezahlt'):
            total_offen += offen
            anzahl_offen += 1
            if mahn:
                anzahl_ueberfaellig += 1
        label, pill_cls = STATUS_PILL.get(r.status, (r.status, 'bg-slate-100 text-slate-500'))
        rows.append({
            'r': r,
            'mieter': r.vertrag.mieter.display_name if r.vertrag_id else '—',
            'objekt': f"{lg.strasse}, {lg.ort}" if lg else '—',
            'einheit': einheit.bezeichnung if einheit else '',
            'faellig': faellig,
            'offen': offen,
            'status_label': label,
            'pill_cls': pill_cls,
            'mahn': mahn,
            'vertrag_id': r.vertrag_id,
        })
    # Offene zuerst (nach Fälligkeit), erledigte danach (neuste zuoberst)
    rows.sort(key=lambda x: (0, x['faellig'].toordinal()) if x['r'].status in ('offen', 'teilbezahlt')
              else (1, -x['faellig'].toordinal()))

    aktive_vertraege = (Mietvertrag.objects.filter(status='aktiv')
                        .select_related('mieter', 'einheit__liegenschaft').order_by('einheit__liegenschaft__strasse'))
    if aktive_lg:
        aktive_vertraege = aktive_vertraege.filter(einheit__liegenschaft=aktive_lg)

    context = {
        **basis,
        'nav': 'debitoren',
        'rows': rows,
        'status_filter': status_filter,
        'q': q,
        'status_chips': [('', 'Alle')] + [(k, v[0]) for k, v in STATUS_PILL.items()],
        'total_offen': total_offen,
        'anzahl_offen': anzahl_offen,
        'anzahl_ueberfaellig': anzahl_ueberfaellig,
        'aktive_vertraege': aktive_vertraege,
    }
    return render(request, 'fw/debitoren.html', context)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_debitor_neu(request):
    """Ad-hoc-Debitorenrechnung (Weiterverrechnung: Sonnerie/Schlüssel/Ersatz …).
    Bucht Debitor an Ertrag (3000) und ermöglicht anschliessend die QR-Rechnung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_debitoren')

    titel = (request.POST.get('titel') or '').strip()
    try:
        betrag = Decimal(str(request.POST.get('betrag') or '0').replace(',', '.'))
    except Exception:
        betrag = Decimal('0')
    if not titel or betrag <= 0:
        messages.error(request, "Titel und ein Betrag > 0 sind erforderlich.")
        return redirect('fw_debitoren')

    vertrag = None
    if request.POST.get('vertrag_id'):
        vertrag = Mietvertrag.objects.filter(id=request.POST['vertrag_id']).select_related('einheit__liegenschaft').first()
    lg = vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None
    heute = timezone.now().date()
    faellig = heute + _timedelta(days=30)

    with transaction.atomic():
        rechnung = DebitorenRechnung.objects.create(
            vertrag=vertrag, liegenschaft=lg,
            einheit=(vertrag.einheit if vertrag else None),
            titel=titel, beschreibung=(request.POST.get('beschreibung') or '').strip(),
            datum=heute, faellig_am=faellig, betrag=betrag, status='offen',
        )
        from finance.booking import buche
        buche("1100", "3000", betrag, f"Weiterverrechnung: {titel}", datum=heute,
              liegenschaft=lg, debitor=rechnung, user=request.user)

    log_aktion(request, "Ad-hoc-Debitorenrechnung erstellt", titel, f"CHF {betrag}")
    messages.success(request, f"✅ Rechnung '{titel}' über CHF {betrag} erstellt — QR-Rechnung via QR-Button.")
    ziel = '/neu/debitoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_weiterverrechnung(request, kreditor_id):
    """Geführte Weiterverrechnung einer Lieferantenrechnung an einen Mieter.

    GET: Formular (Mieter/Vertrag wählen, Betrag = offener weiterzuverrechnender
    Anteil, optionaler Zuschlag). POST: erstellt eine mit der Kreditorenrechnung
    VERKNÜPFTE Debitorenrechnung und bucht ertragsneutral über das Durchlaufkonto
    1190 (Grundbetrag mindert den Aufwand), der Zuschlag wird als Ertrag gebucht."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, DebitorenRechnung
    from finance.booking import buche
    from core.auth import log_aktion
    k = get_object_or_404(KreditorenRechnung.objects.select_related('liegenschaft', 'konto'), id=kreditor_id)
    basis = _global_filter(request)
    heute = timezone.localdate()

    aufwand_konto = k.konto.nummer if k.konto_id else '4000'

    if request.method == 'POST':
        vertrag_id = request.POST.get('vertrag_id')
        vertrag = Mietvertrag.objects.filter(id=vertrag_id).select_related('mieter', 'einheit__liegenschaft').first()
        if not vertrag:
            messages.error(request, "Bitte einen Mieter/Vertrag wählen.")
            return redirect(request.path)

        def _dec(x, d='0'):
            try:
                return Decimal(str(x).replace(',', '.').strip() or d)
            except Exception:
                return Decimal(d)
        grund = _dec(request.POST.get('betrag'), str(k.offen_weiterzuverrechnen))
        zuschlag = _dec(request.POST.get('zuschlag'), '0')
        if grund <= 0:
            messages.error(request, "Betrag muss grösser als 0 sein.")
            return redirect(request.path)
        # Nicht mehr weiterverrechnen als noch offen ist (Grundbetrag = Fremdkosten)
        grund = min(grund, k.offen_weiterzuverrechnen)
        total = (grund + max(zuschlag, Decimal('0'))).quantize(Decimal('0.01'))
        lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else k.liegenschaft
        titel = (request.POST.get('titel') or f"Weiterverrechnung: {k.lieferant}").strip()

        rechnung = DebitorenRechnung.objects.create(
            vertrag=vertrag, liegenschaft=lg, einheit=vertrag.einheit,
            titel=titel, beschreibung=f"Weiterverrechnung Lieferantenrechnung {k.lieferant}"
                                      + (f" · {k.referenz}" if k.referenz else ''),
            datum=heute, faellig_am=heute + _timedelta(days=30), betrag=total,
            status='offen', quell_kreditor=k)

        # Ertragsneutrale Durchreichung des Grundbetrags über 1190:
        #   1100 Debitor  an 1190 Durchlauf   (Forderung an Mieter)
        #   1190 Durchlauf an <Aufwand>        (mindert den Aufwand → netto null)
        buche("1100", "1190", grund, f"Weiterverrechnung {vertrag.mieter}: {titel}",
              datum=heute, liegenschaft=lg, debitor=rechnung, kreditor=k, user=request.user)
        buche("1190", aufwand_konto, grund, f"Aufwandsminderung Weiterverrechnung: {k.lieferant}",
              datum=heute, liegenschaft=lg, debitor=rechnung, kreditor=k, user=request.user)
        # Zuschlag = echter Ertrag (übrige Erträge 3600)
        if zuschlag > 0:
            buche("1100", "3600", zuschlag, f"Zuschlag Weiterverrechnung {vertrag.mieter}",
                  datum=heute, liegenschaft=lg, debitor=rechnung, user=request.user)

        log_aktion(request, "Weiterverrechnung erstellt", str(vertrag.mieter),
                   f"CHF {total} aus {k.lieferant} (#{k.id})", ziel=vertrag)
        messages.success(request, f"✅ CHF {total} an {vertrag.mieter} weiterverrechnet — "
                                  "QR-Rechnung über den QR-Button in den Debitoren.")
        if request.POST.get('embed') == '1':
            return render(request, 'fw/_modal_done.html', {})
        return redirect('/neu/debitoren/')

    # GET — aktive Verträge zur Auswahl
    vertraege = (Mietvertrag.objects.filter(status='aktiv')
                 .select_related('mieter', 'einheit__liegenschaft').order_by('einheit__liegenschaft__strasse'))
    if k.liegenschaft_id:
        bevorzugt = vertraege.filter(einheit__liegenschaft=k.liegenschaft)
        vertraege = list(bevorzugt) + [v for v in vertraege if v.einheit and v.einheit.liegenschaft_id != k.liegenschaft_id]
    else:
        vertraege = list(vertraege)
    return render(request, 'fw/weiterverrechnung.html', {
        **basis, 'nav': 'kreditoren', 'k': k, 'vertraege': vertraege,
        'offen_wv': k.offen_weiterzuverrechnen, 'aufwand_konto': aufwand_konto,
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_debitor_stornieren(request, pk):
    """Storniert eine (versehentlich erstellte) Debitorenrechnung revisionssicher:
    Status → storniert und alle zugehörigen Buchungen werden per Gegenbuchung
    aufgehoben. Bereits (teil-)bezahlte Rechnungen werden blockiert — dort müssen
    zuerst die Zahlungen storniert werden."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchung, Zahlungseingang
    from finance.api import erstelle_storno_buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_debitoren')

    r = get_object_or_404(DebitorenRechnung, id=pk)
    if r.status == 'storniert':
        messages.info(request, "Rechnung ist bereits storniert.")
        return redirect('fw_debitoren')

    bezahlt = (Zahlungseingang.objects.filter(debitoren_rechnung=r, status='verbucht')
               .exists())
    if bezahlt:
        messages.error(request, "Diese Rechnung hat verbuchte Zahlungen — bitte zuerst die Zahlung(en) stornieren.")
        return redirect('fw_debitoren')

    with transaction.atomic():
        for b in Buchung.objects.filter(debitoren_rechnung=r, ist_storno=False):
            erstelle_storno_buchung(b, benutzer=request.user)
        r.status = 'storniert'
        r.save()

    log_aktion(request, "Debitorenrechnung storniert", r.titel, f"CHF {r.betrag}")
    messages.success(request, f"✅ Rechnung '{r.titel}' storniert (revisionssicher, mit Gegenbuchung).")
    ziel = '/neu/debitoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_liegenschaften(request):
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    liegenschaften = Liegenschaft.objects.all().order_by('strasse')
    if aktive_lg:
        liegenschaften = liegenschaften.filter(id=aktive_lg.id)

    rows = []
    for lg in liegenschaften:
        einheiten = lg.einheiten.all()
        aktive = Mietvertrag.objects.filter(einheit__liegenschaft=lg, status='aktiv')
        belegte = set(aktive.values_list('einheit_id', flat=True))
        for neben_id in aktive.values_list('nebenobjekte', flat=True):
            if neben_id:
                belegte.add(neben_id)
        leer = sum(1 for e in einheiten if e.id not in belegte)
        soll = aktive.aggregate(s=Sum('netto_mietzins'), n=Sum('nebenkosten'))
        mietertrag = (soll['s'] or Decimal('0')) + (soll['n'] or Decimal('0'))
        rows.append({'lg': lg, 'einheiten_count': len(einheiten), 'leer': leer,
                     'mietertrag': mietertrag, 'vertraege_count': aktive.count()})

    return render(request, 'fw/liegenschaften.html', {
        **basis, 'nav': 'liegenschaften', 'rows': rows,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_objekte(request):
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    einheiten = Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung')
    if aktive_lg:
        einheiten = einheiten.filter(liegenschaft=aktive_lg)

    typ_filter = request.GET.get('typ', '')
    typ_gruppen = {'wohnen': ['whg', 'stwe'], 'parkplatz': ['pp', 'gar'], 'gewerbe': ['gew']}
    if typ_filter in typ_gruppen:
        einheiten = einheiten.filter(typ__in=typ_gruppen[typ_filter])
    q = (request.GET.get('q') or '').strip()
    if q:
        einheiten = einheiten.filter(Q(bezeichnung__icontains=q) | Q(liegenschaft__strasse__icontains=q))

    aktive = Mietvertrag.objects.filter(status='aktiv').select_related('mieter')
    mieter_je_einheit = {}
    for v in aktive:
        mieter_je_einheit[v.einheit_id] = (v.mieter.display_name, v.id)
    for v in aktive.prefetch_related('nebenobjekte'):
        for neben in v.nebenobjekte.all():
            mieter_je_einheit.setdefault(neben.id, (v.mieter.display_name, v.id))

    rows = []
    vermietet_count = 0
    for e in einheiten:
        belegung = mieter_je_einheit.get(e.id)
        if belegung:
            vermietet_count += 1
        rows.append({'e': e, 'mieter': belegung[0] if belegung else None,
                     'vertrag_id': belegung[1] if belegung else None})

    return render(request, 'fw/objekte.html', {
        **basis, 'nav': 'objekte', 'rows': rows,
        'typ_filter': typ_filter, 'q': q,
        'typ_chips': [('', 'Alle'), ('wohnen', 'Wohnen'), ('parkplatz', 'Parkplatz'), ('gewerbe', 'Gewerbe')],
        'vermietet_count': vermietet_count,
        'leer_count': len(rows) - vermietet_count,
    })


VERTRAG_PILL = {
    'entwurf':    ('Entwurf',    'bg-slate-100 text-slate-600'),
    'aktiv':      ('Aktiv',      'bg-emerald-50 text-emerald-700'),
    'gekuendigt': ('Gekündigt',  'bg-rose-50 text-rose-600'),
    'archiviert': ('Archiviert', 'bg-slate-100 text-slate-500'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vertraege(request):
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (Mietvertrag.objects
          .select_related('mieter', 'einheit__liegenschaft')
          .order_by('-beginn'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    status_filter = request.GET.get('status', '')
    if status_filter in VERTRAG_PILL:
        qs = qs.filter(status=status_filter)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(mieter__vorname__icontains=q) | Q(mieter__nachname__icontains=q)
                       | Q(mieter__firmen_name__icontains=q)
                       | Q(einheit__bezeichnung__icontains=q)
                       | Q(einheit__liegenschaft__strasse__icontains=q))

    rows = []
    for v in qs:
        label, pill_cls = VERTRAG_PILL.get(v.status, (v.status, 'bg-slate-100 text-slate-500'))
        rows.append({
            'v': v,
            'brutto': (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0')),
            'status_label': label,
            'pill_cls': pill_cls,
        })

    return render(request, 'fw/vertraege.html', {
        **basis, 'nav': 'vertraege', 'rows': rows,
        'status_filter': status_filter, 'q': q,
        'status_chips': [('', 'Alle')] + [(k, v[0]) for k, v in VERTRAG_PILL.items()],
        'aktiv_count': sum(1 for r in rows if r['v'].status == 'aktiv'),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_personen(request):
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = Mieter.objects.all().order_by('nachname', 'firmen_name')
    if aktive_lg:
        # Haupt- ODER Mitmieter eines Vertrags in dieser Liegenschaft
        qs = qs.filter(Q(vertraege__einheit__liegenschaft=aktive_lg)
                       | Q(vertraege_als_mitmieter__einheit__liegenschaft=aktive_lg)).distinct()

    typ_filter = request.GET.get('typ', '')
    if typ_filter in ('person', 'firma', 'verein'):
        qs = qs.filter(typ=typ_filter)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(vorname__icontains=q) | Q(nachname__icontains=q)
                       | Q(firmen_name__icontains=q) | Q(email__icontains=q) | Q(ort__icontains=q))

    aktive_vertraege = (Mietvertrag.objects.filter(status='aktiv')
                        .select_related('einheit__liegenschaft'))
    vertrag_je_mieter = {}
    for v in aktive_vertraege:
        # Vertrag beim Hauptmieter UND beim Mitmieter (2. Person) anzeigen
        vertrag_je_mieter.setdefault(v.mieter_id, []).append(v)
        if v.mitmieter_id:
            vertrag_je_mieter.setdefault(v.mitmieter_id, []).append(v)

    rows = []
    for m in qs:
        aktive = vertrag_je_mieter.get(m.id, [])
        rows.append({
            'm': m,
            'telefon': m.mobile or m.telefon_privat or m.telefon_geschaeft,
            'aktive': aktive,
            'objekt': (f"{aktive[0].einheit.liegenschaft.strasse} · {aktive[0].einheit.bezeichnung}"
                       if aktive else None),
        })

    return render(request, 'fw/personen.html', {
        **basis, 'nav': 'personen', 'rows': rows,
        'typ_filter': typ_filter, 'q': q,
        'typ_chips': [('', 'Alle'), ('person', 'Privatpersonen'), ('firma', 'Firmen'), ('verein', 'Vereine')],
        'mit_vertrag_count': sum(1 for r in rows if r['aktive']),
    })


# ============================================================
# ETAPPE C: DETAILSEITEN MIT BREADCRUMB + TABS
# ============================================================

def _vertrag_status_pill(v):
    label, cls = VERTRAG_PILL.get(v.status, (v.status, 'bg-slate-100 text-slate-500'))
    return {'label': label, 'cls': cls}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_liegenschaft_detail(request, pk):
    from portfolio.models import Unterhalt
    from portfolio.models import Dokument as PortfolioDokument
    from rentals.models import Dokument as RentalsDokument
    from tickets.models import SchadenMeldung

    lg = get_object_or_404(Liegenschaft.objects.select_related('mandant', 'verwaltung'), id=pk)
    basis = _global_filter(request)

    einheiten_rows = []
    soll_monat = Decimal('0.00')
    vermietet = 0
    for e in lg.einheiten.all().order_by('bezeichnung'):
        vertrag = (Mietvertrag.objects.filter(einheit=e, status='aktiv')
                   .select_related('mieter').order_by('-beginn').first())
        if vertrag:
            vermietet += 1
            soll_monat += vertrag.brutto_mietzins
        einheiten_rows.append({'einheit': e, 'vertrag': vertrag})

    tickets = (SchadenMeldung.objects.filter(liegenschaft=lg)
               .exclude(status='erledigt').order_by('-erstellt_am')[:10])

    dokumente = []
    for d in RentalsDokument.objects.filter(liegenschaft=lg).order_by('-datum')[:15]:
        dokumente.append({'titel': d.bezeichnung or d.titel, 'kategorie': d.kategorie,
                          'datum': d.datum, 'url': d.datei.url if d.datei else None})
    for d in PortfolioDokument.objects.filter(liegenschaft=lg).order_by('-datum')[:15]:
        dokumente.append({'titel': d.titel, 'kategorie': d.kategorie,
                          'datum': d.datum, 'url': d.datei.url if d.datei else None})
    dokumente.sort(key=lambda d: d['datum'] or date.min, reverse=True)

    unterhalt = Unterhalt.objects.filter(liegenschaft=lg).order_by('-datum')[:10]
    perioden = lg.abrechnungen.order_by('-start_datum')[:6]

    from portfolio.models import Wartungsfrist
    heute = timezone.localdate()
    wartungsfristen = []
    for wf in lg.wartungsfristen.filter(aktiv=True).order_by('naechste_faelligkeit'):
        tage = (wf.naechste_faelligkeit - heute).days
        wartungsfristen.append({
            'wf': wf, 'tage': tage,
            'faellig_bald': 0 <= tage <= 60, 'ueberfaellig': tage < 0,
        })

    dok20 = dokumente[:20]
    tab_liste = [
        ('objekte', 'Objekte', len(einheiten_rows)),
        ('finanzen', 'Finanzen', None),
        ('unterhalt', 'Unterhalt', unterhalt.count() or None),
        ('fristen', 'Fristen', len(wartungsfristen) or None),
        ('schaeden', 'Schäden', tickets.count() or None),
        ('dokumente', 'Dokumente', len(dok20) or None),
    ]
    return render(request, 'fw/liegenschaft_detail.html', {
        **basis, 'nav': 'liegenschaften', 'lg': lg,
        'einheiten_rows': einheiten_rows,
        'total_einheiten': len(einheiten_rows),
        'vermietet': vermietet,
        'leerstand': len(einheiten_rows) - vermietet,
        'soll_monat': soll_monat,
        'tickets': tickets,
        'dokumente': dok20,
        'unterhalt': unterhalt,
        'wartungsfristen': wartungsfristen,
        'perioden': perioden,
        'tab_liste': tab_liste,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_wartungsfrist_neu(request, pk):
    """Wartungs-/Versicherungsfrist zu einer Liegenschaft erfassen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Wartungsfrist
    from core.auth import log_aktion
    lg = get_object_or_404(Liegenschaft, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    bez = (request.POST.get('bezeichnung') or '').strip()
    faellig = (request.POST.get('naechste_faelligkeit') or '').strip()
    if not bez or not faellig:
        messages.error(request, "Bezeichnung und Fälligkeitsdatum sind erforderlich.")
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    try:
        faellig_d = date.fromisoformat(faellig)
    except ValueError:
        messages.error(request, "Ungültiges Datum.")
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    try:
        intervall = int(request.POST.get('intervall_monate') or 12)
    except ValueError:
        intervall = 12
    Wartungsfrist.objects.create(
        liegenschaft=lg, art=request.POST.get('art', 'wartung'),
        bezeichnung=bez, anbieter=(request.POST.get('anbieter') or '').strip(),
        naechste_faelligkeit=faellig_d, intervall_monate=max(0, intervall),
        notiz=(request.POST.get('notiz') or '').strip())
    log_aktion(request, "Wartungsfrist erfasst", str(lg), bez)
    messages.success(request, f'✅ Frist „{bez}" gespeichert.')
    return redirect(f'/neu/liegenschaften/{lg.id}/?tab=fristen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_wartungsfrist_loeschen(request, pk):
    """Wartungs-/Versicherungsfrist löschen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Wartungsfrist
    wf = get_object_or_404(Wartungsfrist.objects.select_related('liegenschaft'), id=pk)
    lg_id = wf.liegenschaft_id
    if request.method == 'POST':
        from core.auth import log_aktion
        bez = f"{wf.bezeichnung} · {wf.liegenschaft}"
        wf.delete()
        log_aktion(request, "Wartungsfrist gelöscht", bez, '')
        messages.success(request, "🗑️ Frist gelöscht.")
    return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_objekt_detail(request, pk):
    from portfolio.models import Geraet, Zaehler
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=pk)
    basis = _global_filter(request)

    aktiver_vertrag = (Mietvertrag.objects.filter(einheit=e, status='aktiv')
                       .select_related('mieter').order_by('-beginn').first())
    if not aktiver_vertrag:
        aktiver_vertrag = (Mietvertrag.objects
                           .filter(nebenobjekte=e, status='aktiv')
                           .select_related('mieter').order_by('-beginn').first())
    historie = (Mietvertrag.objects.filter(einheit=e).exclude(status='aktiv')
                .select_related('mieter').order_by('-beginn')[:10])

    geraete = Geraet.objects.filter(einheit=e).order_by('kategorie')
    zaehler = Zaehler.objects.filter(einheit=e).order_by('typ')

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('historie', 'Historie', historie.count() or None),
        ('geraete', 'Geräte', geraete.count() or None),
        ('zaehler', 'Zähler', zaehler.count() or None),
    ]
    return render(request, 'fw/objekt_detail.html', {
        **basis, 'nav': 'objekte', 'e': e,
        'aktiver_vertrag': aktiver_vertrag,
        'vertrag_pill': _vertrag_status_pill(aktiver_vertrag) if aktiver_vertrag else None,
        'historie': historie,
        'geraete': geraete,
        'zaehler': zaehler,
        'tab_liste': tab_liste,
    })


# --- Erstellbare Dokumente pro Vertrag (Fairwalter-Stil) ---
def _erstellbare_dokumente(v):
    """Verlinkt die bestehenden PDF-/Prozess-Endpunkte als 'Erstellbare Dokumente'."""
    docs = [
        {'titel': 'Mietvertrag (PDF)', 'icon': 'fa-file-contract',
         'url': f'/vertrag/{v.id}/pdf/', 'sub': 'Kompletter Vertrag als PDF'},
        {'titel': 'QR-Rechnung', 'icon': 'fa-qrcode',
         'url': f'/vertrag/{v.id}/qr/', 'sub': 'Einzahlungsschein mit QR-IBAN'},
        {'titel': 'Mahnung (Art. 257d OR)', 'icon': 'fa-triangle-exclamation',
         'url': f'/vertrag/{v.id}/mahnung/', 'sub': 'Zahlungsfrist mit Kündigungsandrohung'},
        {'titel': 'Mietzinsanpassung', 'icon': 'fa-percent',
         'url': f'/mietzins/{v.id}/', 'sub': 'Amtliches Formular berechnen'},
        {'titel': 'Begleitbrief Mietvertrag', 'icon': 'fa-envelope',
         'url': f'/vertrag/{v.id}/dokument/begleitbrief/', 'sub': 'Anschreiben zur Unterzeichnung'},
        {'titel': 'Begleitbrief unterzeichnet', 'icon': 'fa-envelope-circle-check',
         'url': f'/vertrag/{v.id}/dokument/begleitbrief-signiert/', 'sub': 'Zustellung des signierten Vertrags'},
        {'titel': 'Allgemeine Bedingungen', 'icon': 'fa-file-lines',
         'url': f'/vertrag/{v.id}/dokument/allgemeine-bedingungen/', 'sub': 'Vertragsbeilage'},
        {'titel': 'Hausordnung', 'icon': 'fa-list-check',
         'url': f'/vertrag/{v.id}/dokument/hausordnung/', 'sub': 'Vertragsbeilage'},
        {'titel': 'Merkblatt Lüften & Pflegen', 'icon': 'fa-wind',
         'url': f'/vertrag/{v.id}/dokument/merkblatt-lueften/', 'sub': 'Vertragsbeilage'},
        {'titel': 'Wohnungsausweis', 'icon': 'fa-id-card',
         'url': f'/vertrag/{v.id}/dokument/wohnungsausweis/', 'sub': 'Mieter- und Objektdaten'},
    ]
    if v.kuendigungen.exists():
        docs.append({'titel': 'Kündigungsbestätigung', 'icon': 'fa-file-circle-xmark',
                     'url': f'/vertrag/{v.id}/dokument/kuendigungsbestaetigung/', 'sub': 'Bestätigung mit Vertragsende'})
    return docs


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vertrag_detail(request, pk):
    from rentals.models import Dokument as RentalsDokument
    v = get_object_or_404(
        Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=pk)
    basis = _global_filter(request)

    rechnungen = (DebitorenRechnung.objects.filter(vertrag=v)
                  .exclude(status='storniert').order_by('-datum')[:15])
    offene = [r for r in rechnungen if r.status in ('offen', 'teilbezahlt')]
    total_offen = sum((r.offener_betrag for r in offene), Decimal('0.00'))

    zahlungen = (Zahlungseingang.objects.filter(vertrag=v, status='verbucht')
                 .order_by('-datum_eingang')[:15])
    anpassungen = v.anpassungen.order_by('-wirksam_ab')[:10]
    dokumente = RentalsDokument.objects.filter(vertrag=v).order_by('-datum')[:15]

    rechnungs_rows = []
    for r in rechnungen:
        label, pill_cls = STATUS_PILL.get(r.status, (r.status, 'bg-slate-100 text-slate-500'))
        rechnungs_rows.append({'r': r, 'status_label': label, 'pill_cls': pill_cls,
                               'offen': r.offener_betrag if r.status in ('offen', 'teilbezahlt') else Decimal('0.00')})

    from core.models import AktivitaetsLog
    verlauf = list(AktivitaetsLog.objects.filter(ziel_typ='vertrag', ziel_id=v.id)
                   .select_related('benutzer')[:50])
    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('finanzen', 'Finanzen', len(offene) or None),
        ('mietzins', 'Mietzins', anpassungen.count() or None),
        ('dokumente', 'Dokumente', None),
        ('verlauf', 'Verlauf', len(verlauf) or None),
    ]
    return render(request, 'fw/vertrag_detail.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'verlauf': verlauf,
        'vertrag_pill': _vertrag_status_pill(v),
        'brutto': (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0')),
        'rechnungs_rows': rechnungs_rows,
        'total_offen': total_offen,
        'anzahl_offen': len(offene),
        'zahlungen': zahlungen,
        'anpassungen': anpassungen,
        'dokumente': dokumente,
        'nebenobjekte': v.nebenobjekte.all(),
        'erstellbare_dokumente': _erstellbare_dokumente(v),
        'kuendigungen': v.kuendigungen.all(),
        'formular_kanton': _formular_kanton_label(v),
        'tab_liste': tab_liste,
    })


def _formular_kanton_label(vertrag):
    """Kürzel des Kantons für das amtliche Formular (SO/ZH/BE/…). Leer, wenn
    keine Liegenschaft/kein Kanton bestimmbar."""
    from core.services.kantone import kanton_fuer_liegenschaft
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    return kanton_fuer_liegenschaft(lg) if lg else ''


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schlussabrechnung(request, vertrag_id):
    """Schlussabrechnung beim Auszug: offene Forderungen + NK-Saldo + Schäden −
    Kaution = Saldo. GET zeigt Formular, POST erzeugt PDF (aktion=pdf) oder
    verbucht Kaution + Nachzahlung (aktion=buchen)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from core.services.schlussabrechnung import berechne_schlussabrechnung, generate_schlussabrechnung_pdf
    from core.auth import log_aktion

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)

    def _dec(x):
        try:
            return Decimal(str(x).replace(',', '.').strip())
        except Exception:
            return Decimal('0.00')

    if request.method == 'POST':
        try:
            auszug = date.fromisoformat(request.POST.get('auszug_datum') or '')
        except Exception:
            auszug = v.ende or timezone.now().date()
        kaution_verrechnen = request.POST.get('kaution_verrechnen') == 'on'

        positionen = []
        texte = request.POST.getlist('pos_text')
        betraege = request.POST.getlist('pos_betrag')
        richtungen = request.POST.getlist('pos_richtung')
        for i, txt in enumerate(texte):
            txt = (txt or '').strip()
            betr = _dec(betraege[i] if i < len(betraege) else '0')
            if not txt or betr == 0:
                continue
            richtung = richtungen[i] if i < len(richtungen) else 'zulasten'
            positionen.append({'text': txt, 'betrag': betr, 'zulasten': (richtung == 'zulasten')})

        daten = berechne_schlussabrechnung(v, auszug, positionen, kaution_verrechnen=kaution_verrechnen)
        aktion = request.POST.get('aktion', 'pdf')

        if aktion == 'buchen':
            with transaction.atomic():
                # Kaution als abgerechnet markieren
                if kaution_verrechnen and (v.kautions_betrag or 0) > 0:
                    v.kautions_zurueckbezahlt_am = auszug
                    if v.ist_kautionsversicherung:
                        # Versicherung: keine Rückzahlung an Mieter; Police wird aufgelöst.
                        v.kautions_rueckzahlung_betrag = Decimal('0.00')
                    elif daten['nachzahlung']:
                        # Kaution ging an offene Forderungen → Abzug = ganze Kaution, Rückzahlung 0
                        v.kautions_abzug_betrag = v.kautions_betrag
                        v.kautions_rueckzahlung_betrag = Decimal('0.00')
                    else:
                        v.kautions_rueckzahlung_betrag = daten['rueckzahlung']
                        v.kautions_abzug_betrag = (v.kautions_betrag or Decimal('0')) - daten['rueckzahlung']
                    v.save()
                # Nachzahlung als Debitor stellen
                if daten['nachzahlung'] and daten['saldo'] > 0:
                    from finance.models import Buchungskonto, Buchung
                    heute = timezone.now().date()
                    rech = DebitorenRechnung.objects.create(
                        vertrag=v, liegenschaft=v.einheit.liegenschaft, einheit=v.einheit,
                        titel="Schlussabrechnung (Nachzahlung)", datum=heute,
                        faellig_am=heute + _timedelta(days=30), betrag=daten['saldo'], status='offen')
                    from finance.booking import buche
                    buche("1100", "3000", daten['saldo'], f"Schlussabrechnung {v.mieter}",
                          datum=heute, liegenschaft=v.einheit.liegenschaft, debitor=rech,
                          user=request.user)
            from core.services.automation import erledige_pendenzen_fuer
            erledige_pendenzen_fuer(v, ['Schlussabrechnung', 'Kaution'], user=request.user)
            log_aktion(request, "Schlussabrechnung verbucht", str(v.mieter), f"Saldo CHF {daten['saldo']}", ziel=v)
            if request.POST.get('embed'):
                return render(request, 'fw/_modal_done.html', {'msg': 'Schlussabrechnung verbucht'})
            messages.success(request, "✅ Schlussabrechnung verbucht (Kaution abgerechnet"
                             + (", Nachzahlung als Debitor gestellt" if daten['nachzahlung'] else "") + ").")
            return redirect(f'/neu/vertraege/{v.id}/')

        try:
            pdf = generate_schlussabrechnung_pdf(v, daten, verwaltung=Verwaltung.objects.first())
        except Exception as e:
            messages.error(request, f"❌ PDF konnte nicht erstellt werden: {e}")
            return redirect(f'/neu/vertraege/{v.id}/schlussabrechnung/')
        from core.services.ablage import ablegen
        ablegen(pdf, "Schlussabrechnung", kategorie='korrespondenz', vertrag=v, dedup=True)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Schlussabrechnung_{v.mieter.nachname}.pdf"'
        return resp

    # GET
    offene = DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
    offen_total = sum((r.offener_betrag for r in offene), Decimal('0.00'))
    # Bereits erfasste Schaden-/Einbehalts-Forderung (z.B. aus „Police auflösen") als
    # Position vorbelegen, damit sie in der Schlussabrechnung sichtbar mitzählt.
    schaden_betrag = v.kautions_abzug_betrag or Decimal('0.00')
    schaden_text = v.kautions_abzug_grund or ('Schadenforderung' if schaden_betrag > 0 else '')
    # Mängel aus einem Abnahmeprotokoll (Verursacher = Mieter) als Positionen vorbelegen
    prefill_positionen = []
    ab_id = request.GET.get('abnahme')
    if ab_id:
        from rentals.models import Abnahmeprotokoll
        ab = Abnahmeprotokoll.objects.filter(id=ab_id, vertrag=v).first()
        if ab:
            for m in ab.maengel_mieter:
                if m.kostenschaetzung:
                    txt = f"{m.raum + ': ' if m.raum else ''}{m.beschreibung}"
                    prefill_positionen.append({'text': txt[:90], 'betrag': m.kostenschaetzung})
    if schaden_betrag > 0:
        prefill_positionen.insert(0, {'text': schaden_text, 'betrag': schaden_betrag})
    return render(request, 'fw/schlussabrechnung.html', {
        **basis, 'nav': 'vertraege', 'v': v,
        'offen_total': offen_total,
        'kaution': v.kautions_betrag or Decimal('0.00'),
        'ist_versicherung': v.ist_kautionsversicherung,
        'schaden_prefill_betrag': schaden_betrag,
        'schaden_prefill_text': schaden_text,
        'prefill_positionen': prefill_positionen,
        'auszug_default': (v.ende or timezone.now().date()).isoformat(),
        'abnahmen': v.abnahmen.all(),
        'embed_base': ('fw/base_embed.html' if request.GET.get('embed') == '1' else None),
    })


# ============================================================
# WOHNUNGSABNAHME-PROTOKOLL (Einzug/Auszug, mobil)
# ============================================================
ABNAHME_RAEUME = ['Eingang/Korridor', 'Wohnzimmer', 'Küche', 'Bad/WC', 'Zimmer 1',
                  'Zimmer 2', 'Zimmer 3', 'Balkon/Terrasse', 'Keller', 'Estrich', 'Allgemein']


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_neu(request, vertrag_id):
    """Wohnungsabnahme erfassen (mobil): Zustand, Mängel je Raum mit Verursacher,
    Fotos, Zählerstände, Unterschriften."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll, AbnahmeMangel
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST

        def _dec(x):
            try:
                return Decimal(str(x).replace(',', '.').strip()) if str(x).strip() else None
            except Exception:
                return None
        try:
            datum = date.fromisoformat(P.get('datum') or '')
        except Exception:
            datum = timezone.localdate()
        prot = Abnahmeprotokoll.objects.create(
            vertrag=v, typ=P.get('typ', 'auszug'), datum=datum,
            mieter_anwesend=P.get('mieter_anwesend') == 'on',
            verwalter_name=P.get('verwalter_name', '').strip(),
            allgemein_zustand=P.get('allgemein_zustand', 'gut'),
            schluessel_anzahl=int(P.get('schluessel_anzahl')) if (P.get('schluessel_anzahl') or '').isdigit() else None,
            zaehler_strom=P.get('zaehler_strom', '').strip(),
            zaehler_wasser=P.get('zaehler_wasser', '').strip(),
            zaehler_gas=P.get('zaehler_gas', '').strip(),
            neue_adresse=P.get('neue_adresse', '').strip(),
            bemerkungen=P.get('bemerkungen', '').strip(),
            unterschrift_mieter=P.get('unterschrift_mieter', '').strip(),
            unterschrift_verwalter=P.get('unterschrift_verwalter', '').strip(),
            abgeschlossen=P.get('abgeschlossen') == 'on',
        )
        # Mängel-Zeilen (parallele Listen). Fotos werden in Reihenfolge zugeordnet
        # (leere Datei-Inputs liefert der Browser nicht mit).
        raeume = P.getlist('m_raum')
        beschr = P.getlist('m_beschreibung')
        verurs = P.getlist('m_verursacher')
        kosten = P.getlist('m_kosten')
        fotos = list(request.FILES.getlist('m_foto'))
        for i, b in enumerate(beschr):
            b = (b or '').strip()
            if not b:
                continue
            AbnahmeMangel.objects.create(
                protokoll=prot,
                raum=(raeume[i] if i < len(raeume) else '').strip(),
                beschreibung=b,
                verursacher=(verurs[i] if i < len(verurs) else 'abnutzung'),
                kostenschaetzung=_dec(kosten[i] if i < len(kosten) else ''),
                foto=(fotos.pop(0) if fotos else None),
            )
        # Passende Auszugs-Pendenzen automatisch abhaken
        if prot.typ == 'auszug':
            from core.services.automation import erledige_pendenzen_fuer
            kw = ['Wohnungsabnahme', 'Abnahmetermin']
            if prot.zaehler_strom or prot.zaehler_wasser or prot.zaehler_gas:
                kw.append('Zählerstände')
            if prot.schluessel_anzahl is not None:
                kw.append('Schlüssel')
            erledige_pendenzen_fuer(v, kw, user=request.user)
        log_aktion(request, "Wohnungsabnahme erfasst", str(v.mieter), f"{prot.get_typ_display()} {datum}", ziel=v)
        if P.get('embed'):
            typ_txt = prot.get_typ_display()
            return render(request, 'fw/_modal_done.html', {'msg': f"{typ_txt} erfasst ({prot.maengel.count()} Mängel)"})
        messages.success(request, f"✅ Abnahmeprotokoll erfasst ({prot.maengel.count()} Mängel).")
        return redirect(f'/neu/abnahme/{prot.id}/')

    embed = request.GET.get('embed') == '1'
    return render(request, 'fw/abnahme_neu.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'raeume': ABNAHME_RAEUME,
        'heute': timezone.localdate().isoformat(),
        'verwalter_default': (request.user.get_full_name() or request.user.username),
        'typ_default': (request.GET.get('typ') if request.GET.get('typ') in ('auszug', 'einzug')
                        else ('auszug' if v.status in ('gekuendigt', 'archiviert') else 'einzug')),
        'embed_base': ('fw/base_embed.html' if embed else None),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abnahme_detail(request, pk):
    from rentals.models import Abnahmeprotokoll
    basis = _global_filter(request)
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    return render(request, 'fw/abnahme_detail.html', {
        **basis, 'nav': 'vertraege', 'p': prot, 'v': prot.vertrag,
        'maengel': prot.maengel.all(),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abnahme_pdf(request, pk):
    from django.http import HttpResponse
    from rentals.models import Abnahmeprotokoll
    from crm.models import Verwaltung
    from core.services.abnahme_pdf import generate_abnahme_pdf
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    pdf = generate_abnahme_pdf(prot, verwaltung=Verwaltung.objects.first())
    # Auto-Ablage in die Vertrags-Akte (abgeschlossene Protokolle)
    if getattr(prot, 'abgeschlossen', False):
        from core.services.ablage import ablegen
        ablegen(pdf, f"Abnahmeprotokoll ({prot.get_typ_display()}) {prot.datum:%d.%m.%Y}",
                kategorie='protokoll', vertrag=prot.vertrag, dedup=True)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Abnahmeprotokoll_{prot.vertrag.mieter.nachname}.pdf"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_status(request, pk):
    """Setzt den Vertragsstatus: entwurf / aktiv / archiviert (inaktiv)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=pk)
    if request.method == 'POST':
        neu = request.POST.get('status', '')
        erlaubt = {'entwurf': 'Entwurf', 'aktiv': 'Aktiv', 'archiviert': 'Inaktiv / Archiviert'}
        if neu in erlaubt:
            v.status = neu
            v.aktiv = (neu == 'aktiv')
            v.save(update_fields=['status', 'aktiv'])
            log_aktion(request, "Vertragsstatus geändert", str(v.mieter), erlaubt[neu], ziel=v)
            messages.success(request, f"✅ Vertrag ist jetzt: {erlaubt[neu]}.")
        else:
            messages.error(request, "Unbekannter Status.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_vertrag_loeschen(request, pk):
    """Löscht einen Mietvertrag. Verknüpfte Rechnungen/Zahlungen bleiben erhalten
    (FK on_delete=SET_NULL) — die revisionssichere Buchhaltung wird nicht zerstört."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=pk)
    if request.method == 'POST':
        name = str(v.mieter)
        einheit = v.einheit.bezeichnung
        log_aktion(request, "Mietvertrag gelöscht", name, einheit)
        v.delete()
        messages.success(request, f"🗑️ Vertrag ({name} · {einheit}) wurde gelöscht.")
        return redirect('/neu/vertraege/')
    return redirect(f'/neu/vertraege/{v.id}/')


# ============================================================
# ETAPPE D: MAHNWESEN (Mahnstufen aus überfälligen Debitoren)
# ============================================================

# Mahnstufen-Schwellen (Tage überfällig) — zentrale Stellschraube.
MAHN_STUFEN = [
    {'stufe': 3, 'ab_tage': 60, 'label': '3. Mahnung', 'unter': 'Kündigungsandrohung (Art. 257d OR)',
     'cls': 'bg-rose-100 text-rose-700', 'dot': 'bg-rose-500'},
    {'stufe': 2, 'ab_tage': 30, 'label': '2. Mahnung', 'unter': 'Zweite schriftliche Erinnerung',
     'cls': 'bg-rose-50 text-rose-600', 'dot': 'bg-rose-400'},
    {'stufe': 1, 'ab_tage': 14, 'label': '1. Mahnung', 'unter': 'Erste Zahlungserinnerung',
     'cls': 'bg-amber-100 text-amber-700', 'dot': 'bg-amber-500'},
]


def _stufe_fuer_tage(tage):
    for s in MAHN_STUFEN:
        if tage >= s['ab_tage']:
            return s
    return None


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mahnwesen(request):
    heute = timezone.now().date()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (DebitorenRechnung.objects
          .filter(status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft')
          .prefetch_related('zahlungseingaenge'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    stufe_filter = request.GET.get('stufe', '')

    rows = []
    total = Decimal('0.00')
    counts = {1: 0, 2: 0, 3: 0}
    summe = {1: Decimal('0.00'), 2: Decimal('0.00'), 3: Decimal('0.00')}
    for r in qs:
        faellig = r.faellig_am or r.datum
        if not faellig or faellig >= heute:
            continue
        tage = (heute - faellig).days
        stufe = _stufe_fuer_tage(tage)
        if not stufe:
            continue  # < 14 Tage: noch kein Mahnfall
        offen = r.offener_betrag
        if offen <= 0:
            continue
        counts[stufe['stufe']] += 1
        summe[stufe['stufe']] += offen
        total += offen
        if stufe_filter and str(stufe['stufe']) != stufe_filter:
            continue
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        monat = faellig.strftime('%m/%Y')
        rows.append({
            'r': r, 'stufe': stufe, 'tage': tage, 'offen': offen,
            'mieter': r.vertrag.mieter.display_name if r.vertrag_id else '—',
            'objekt': (f"{lg.strasse}, {lg.ort}" if lg else '—'),
            'faellig': faellig,
            'vertrag_id': r.vertrag_id,
            'hat_email': bool(r.vertrag and r.vertrag.mieter.email),
            'mahn_url': (f"/vertrag/{r.vertrag_id}/mahnung/?betrag={offen}&monat={monat}"
                         if r.vertrag_id else None),
        })
    rows.sort(key=lambda x: (-x['stufe']['stufe'], -x['tage']))

    stufe_chips = [('', 'Alle Stufen')] + [(str(s['stufe']), s['label']) for s in MAHN_STUFEN]

    # Letzte erfasste Mahnung je Rechnung + Historie
    from finance.models import Mahnung
    letzte_je_rechnung = {}
    for mn in Mahnung.objects.all().order_by('datum'):
        letzte_je_rechnung[mn.debitoren_rechnung_id] = mn
    for row in rows:
        row['letzte_mahnung'] = letzte_je_rechnung.get(row['r'].id)

    historie_qs = (Mahnung.objects.select_related('vertrag__mieter', 'debitoren_rechnung')
                   .order_by('-datum', '-id'))
    if aktive_lg:
        historie_qs = historie_qs.filter(vertrag__einheit__liegenschaft=aktive_lg)
    historie = list(historie_qs[:30])

    context = {
        **basis, 'nav': 'mahnwesen', 'rows': rows,
        'stufe_filter': stufe_filter, 'stufe_chips': stufe_chips,
        'total': total,
        'mahnstufen': MAHN_STUFEN,
        'counts': counts, 'summe': summe,
        'anzahl_total': counts[1] + counts[2] + counts[3],
        'historie': historie,
    }
    return render(request, 'fw/mahnwesen.html', context)


# ============================================================
# ETAPPE D: BANKKONTEN (QR-IBAN-Erkennung + Mietertrag je Konto)
# ============================================================

def _iban_clean(iban):
    return (iban or '').replace(' ', '').upper()


def _iban_format(iban):
    """Gruppiert die IBAN in 4er-Blöcke (CH93 0076 2011 6238 5295 7)."""
    s = _iban_clean(iban)
    return ' '.join(s[i:i + 4] for i in range(0, len(s), 4)) if s else ''


def _ist_qr_iban(iban):
    """QR-IBAN: Institut-ID (Stellen 5–9) im Bereich 30000–31999 (Schweizer QR-IID)."""
    s = _iban_clean(iban)
    if len(s) < 9 or not s.startswith(('CH', 'LI')):
        return False
    try:
        iid = int(s[4:9])
    except ValueError:
        return False
    return 30000 <= iid <= 31999


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bankkonten(request):
    from crm.models import Verwaltung, Mandant
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    liegenschaften = Liegenschaft.objects.all().order_by('strasse')
    if aktive_lg:
        liegenschaften = liegenschaften.filter(id=aktive_lg.id)

    konten = []
    qr_count = 0
    # 1) Liegenschafts-Mietkonten (das Konto, auf das die Mieten laufen)
    for lg in liegenschaften:
        if not _iban_clean(lg.iban):
            continue
        aktive = Mietvertrag.objects.filter(einheit__liegenschaft=lg, status='aktiv')
        soll = aktive.aggregate(s=Sum('netto_mietzins'), n=Sum('nebenkosten'))
        mietertrag = (soll['s'] or Decimal('0')) + (soll['n'] or Decimal('0'))
        is_qr = _ist_qr_iban(lg.iban)
        qr_count += 1 if is_qr else 0
        konten.append({
            'typ': 'Mietkonto', 'typ_icon': 'fa-building', 'typ_cls': 'bg-indigo-50 text-indigo-600',
            'inhaber': lg.strasse, 'kontext': f"{lg.plz} {lg.ort}",
            'bank': lg.bank_name, 'iban': _iban_format(lg.iban),
            'ist_qr': is_qr, 'mietertrag': mietertrag,
            'lg_id': lg.id,
        })

    # 2) Verwaltungs- und Eigentümer-Konten (nur ohne aktiven LG-Filter)
    if not aktive_lg:
        vw = Verwaltung.objects.first()
        if vw and _iban_clean(vw.iban):
            is_qr = _ist_qr_iban(vw.iban)
            qr_count += 1 if is_qr else 0
            konten.append({
                'typ': 'Verwaltung', 'typ_icon': 'fa-briefcase', 'typ_cls': 'bg-slate-100 text-slate-600',
                'inhaber': vw.firma, 'kontext': 'Verwaltungskonto',
                'bank': getattr(vw, 'bank_name', ''), 'iban': _iban_format(vw.iban),
                'ist_qr': is_qr, 'mietertrag': None, 'lg_id': None,
            })
        for m in Mandant.objects.all().order_by('firma_oder_name'):
            if not _iban_clean(m.iban):
                continue
            is_qr = _ist_qr_iban(m.iban)
            qr_count += 1 if is_qr else 0
            konten.append({
                'typ': 'Eigentümer', 'typ_icon': 'fa-user-tie', 'typ_cls': 'bg-emerald-50 text-emerald-600',
                'inhaber': m.firma_oder_name, 'kontext': 'Eigentümer-Auszahlungskonto',
                'bank': m.bank_name, 'iban': _iban_format(m.iban),
                'ist_qr': is_qr, 'mietertrag': None, 'lg_id': None,
            })

    fehlend = liegenschaften.filter(Q(iban='') | Q(iban__isnull=True)).count()

    return render(request, 'fw/bankkonten.html', {
        **basis, 'nav': 'bankkonten', 'konten': konten,
        'anzahl': len(konten), 'qr_count': qr_count,
        'fehlend': fehlend,
    })


# ============================================================
# ETAPPE D: BANKABGLEICH (offene Posten mit Zahlung abgleichen)
# ============================================================

def _qrr_referenz(rechnung):
    """Erzeugt eine strukturierte 27-stellige QRR-Referenz mit Modulo-10-rekursiv-Prüfziffer
    aus Vertrags- und Rechnungs-ID (stabil, damit Zahlungseingänge zuordenbar sind)."""
    basis = f"{(rechnung.vertrag_id or 0):010d}{rechnung.id:016d}"
    tabelle = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]
    uebertrag = 0
    for z in basis:
        uebertrag = tabelle[(uebertrag + int(z)) % 10]
    pruef = (10 - uebertrag) % 10
    ref = basis + str(pruef)
    return ' '.join([ref[0:2], ref[2:7], ref[7:12], ref[12:17], ref[17:22], ref[22:27]])


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bankabgleich(request):
    heute = timezone.now().date()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (DebitorenRechnung.objects
          .filter(status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft')
          .prefetch_related('zahlungseingaenge')
          .order_by('faellig_am'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    rows = []
    total_offen = Decimal('0.00')
    for r in qs:
        offen = r.offener_betrag
        if offen <= 0:
            continue
        total_offen += offen
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        faellig = r.faellig_am or r.datum
        rows.append({
            'r': r, 'offen': offen,
            'mieter': r.vertrag.mieter.display_name if r.vertrag_id else '—',
            'objekt': f"{lg.strasse}, {lg.ort}" if lg else '—',
            'faellig': faellig,
            'ueberfaellig': bool(faellig and faellig < heute),
            'qrr': _qrr_referenz(r) if r.vertrag_id else '—',
            'kann_verbuchen': bool(r.vertrag_id),
        })

    # Kürzliche Abgleiche (verbuchte Zahlungen) als Kontext
    letzte = (Zahlungseingang.objects.filter(status='verbucht')
              .select_related('vertrag__mieter').order_by('-erstellt_am')[:8])
    if aktive_lg:
        letzte = letzte.filter(vertrag__einheit__liegenschaft=aktive_lg)

    from django.contrib import messages
    return render(request, 'fw/bankabgleich.html', {
        **basis, 'nav': 'bankabgleich', 'rows': rows,
        'total_offen': total_offen, 'anzahl': len(rows),
        'letzte': letzte,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bankabgleich_verbuchen(request):
    """Verbucht eine (Teil-)Zahlung für einen offenen Posten — Bank an Debitoren,
    dieselbe Doppelbuchung + OP-Fortschreibung wie die Finanz-API."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')

    rechnung = get_object_or_404(DebitorenRechnung, id=request.POST.get('rechnung_id'))
    if not rechnung.vertrag_id:
        messages.error(request, "Position ohne Vertrag kann nicht automatisch verbucht werden.")
        return redirect('fw_bankabgleich')

    offen = rechnung.offener_betrag
    try:
        betrag = Decimal(str(request.POST.get('betrag') or offen))
    except Exception:
        betrag = offen
    betrag = min(max(betrag, Decimal('0.01')), offen)

    heute = timezone.now().date()
    vertrag = rechnung.vertrag
    with transaction.atomic():
        zahlung = Zahlungseingang.objects.create(
            vertrag=vertrag, betrag=betrag, datum_eingang=heute,
            buchungs_monat=(rechnung.faellig_am or rechnung.datum or heute).replace(day=1),
            bemerkung=f"Bankabgleich {rechnung.titel}",
            liegenschaft=vertrag.einheit.liegenschaft,
            debitoren_rechnung=rechnung, erstellt_von=request.user, status='verbucht',
        )
        rechnung.status = 'bezahlt' if rechnung.offener_betrag <= 0 else 'teilbezahlt'
        rechnung.save()
        from finance.booking import buche
        buche("1020", "1100", betrag, f"Bankabgleich {vertrag.mieter} - {rechnung.titel}",
              datum=heute, liegenschaft=vertrag.einheit.liegenschaft, zahlung=zahlung,
              user=request.user)

    log_aktion(request, "Zahlung via Bankabgleich verbucht", str(vertrag),
               f"CHF {betrag} auf {rechnung.titel}")
    messages.success(request, f"✅ CHF {betrag} verbucht — {vertrag.mieter.display_name} ({rechnung.titel}).")
    from django.shortcuts import redirect as _r
    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'
    return _r(ziel)


def _camt_localname(tag):
    """Entfernt den XML-Namespace ({...}Ntry -> Ntry)."""
    return tag.split('}')[-1] if '}' in tag else tag


def _camt_find(el, *pfad):
    """Namespace-agnostisches Suchen entlang eines Pfads von Localnames."""
    cur = el
    for name in pfad:
        gefunden = None
        for kind in list(cur):
            if _camt_localname(kind.tag) == name:
                gefunden = kind
                break
        if gefunden is None:
            return None
        cur = gefunden
    return cur


def _camt_parse(xml_bytes):
    """Parst einen camt.053-Kontoauszug (ISO 20022) namespace-agnostisch.
    Gibt Liste von Gutschriften zurück: [{'betrag': Decimal, 'referenz': str,
    'datum': date|None, 'info': str}]."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_bytes)
    eintraege = []
    # Alle <Ntry>-Elemente unabhängig von der Verschachtelungstiefe
    for ntry in root.iter():
        if _camt_localname(ntry.tag) != 'Ntry':
            continue
        cdtdbt = _camt_find(ntry, 'CdtDbtInd')
        if cdtdbt is None or (cdtdbt.text or '').strip() != 'CRDT':
            continue  # nur Gutschriften (Zahlungseingänge)
        amt_el = _camt_find(ntry, 'Amt')
        if amt_el is None or not (amt_el.text or '').strip():
            continue
        try:
            betrag = Decimal((amt_el.text or '0').strip())
        except Exception:
            continue
        # Buchungsdatum (Element mit Text ist in ET „falsy", daher explizit is-None prüfen)
        datum = None
        dt_el = _camt_find(ntry, 'BookgDt', 'Dt')
        if dt_el is None:
            dt_el = _camt_find(ntry, 'ValDt', 'Dt')
        if dt_el is not None and dt_el.text:
            try:
                datum = date.fromisoformat(dt_el.text.strip()[:10])
            except Exception:
                datum = None
        # Referenz + Info + Bank-Tx-Ref (Duplikatschutz) + Auftraggebername (Fuzzy)
        referenz = ''
        info = ''
        acct_ref = ''
        dbtr_name = ''
        in_dbtr = False
        for sub in ntry.iter():
            ln = _camt_localname(sub.tag)
            if ln == 'CdtrRefInf':
                ref_el = _camt_find(sub, 'Ref')
                if ref_el is not None and ref_el.text:
                    referenz = ref_el.text.strip().replace(' ', '')
            elif ln == 'Ustrd' and not info and sub.text:
                info = sub.text.strip()
            elif ln in ('AcctSvcrRef', 'TxId', 'EndToEndId') and not acct_ref and sub.text:
                acct_ref = sub.text.strip()
            elif ln == 'Dbtr':
                in_dbtr = True
            elif ln == 'Nm' and in_dbtr and not dbtr_name and sub.text:
                dbtr_name = sub.text.strip(); in_dbtr = False
        eintraege.append({'betrag': betrag, 'referenz': referenz, 'datum': datum,
                          'info': info, 'acct_ref': acct_ref, 'dbtr_name': dbtr_name})
    return eintraege


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_camt_import(request):
    """Importiert einen camt.053-Kontoauszug: Gutschriften werden per QRR-Referenz
    den offenen Debitorenrechnungen zugeordnet und als Zahlungseingang (Bank an
    Debitoren) verbucht."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.utils.qr_code import qrr_referenz
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')

    datei = request.FILES.get('camt_datei')
    if not datei:
        messages.error(request, "Keine Datei ausgewählt.")
        return redirect('fw_bankabgleich')

    try:
        eintraege = _camt_parse(datei.read())
    except Exception as e:
        messages.error(request, f"Datei konnte nicht gelesen werden (kein gültiges camt.053?): {e}")
        return redirect('fw_bankabgleich')

    if not eintraege:
        messages.warning(request, "Keine Gutschriften (CRDT) im Kontoauszug gefunden.")
        return redirect('fw_bankabgleich')

    # Referenz-Index aller offenen/teilbezahlten Rechnungen aufbauen
    offene = list(DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
                  .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'))
    ref_index = {}
    for r in offene:
        schluessel = set()
        if r.qr_referenz:
            schluessel.add(r.qr_referenz.replace(' ', ''))
        if r.vertrag_id:
            raw, _ = qrr_referenz(r.vertrag_id, r.id)
            schluessel.add(raw)
        for s in schluessel:
            ref_index.setdefault(s, r)

    verbucht = 0
    zugeordnet_summe = Decimal('0.00')
    fuzzy = 0
    geklaert = 0            # auf Durchlaufkonto 1190 geparkt
    duplikate = 0
    heute = timezone.now().date()

    konto_bank = Buchungskonto.objects.filter(nummer="1020").first()
    konto_deb = Buchungskonto.objects.filter(nummer="1100").first()
    konto_clearing, _ = Buchungskonto.objects.get_or_create(
        nummer="1190", defaults={'bezeichnung': 'Durchlaufkonto (ungeklärte Zahlungen)', 'typ': 'bilanz'})

    # Fuzzy-Index: offener Betrag → Rechnungen (für referenzlose Gutschriften)
    def _norm(s):
        return ''.join(ch for ch in (s or '').lower() if ch.isalnum())

    def _verbuche(rechnung, betrag, e, via):
        vertrag = rechnung.vertrag
        with transaction.atomic():
            zahlung = Zahlungseingang.objects.create(
                vertrag=vertrag, betrag=betrag, datum_eingang=e['datum'] or heute,
                buchungs_monat=(rechnung.faellig_am or rechnung.datum or heute).replace(day=1),
                bemerkung=f"camt.053-Import ({via}) {rechnung.titel}",
                bank_referenz=e.get('acct_ref', ''),
                liegenschaft=vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None,
                debitoren_rechnung=rechnung, erstellt_von=request.user, status='verbucht',
            )
            rechnung.status = 'bezahlt' if rechnung.offener_betrag <= 0 else 'teilbezahlt'
            rechnung.save()
            from finance.booking import buche
            buche("1020", "1100", betrag, f"camt.053 {vertrag.mieter} - {rechnung.titel}",
                  datum=e['datum'] or heute,
                  liegenschaft=vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None,
                  zahlung=zahlung, user=request.user)
        if rechnung.status == 'bezahlt':
            for k in [k for k, v in ref_index.items() if v is rechnung]:
                ref_index.pop(k, None)

    for e in eintraege:
        # 0) Duplikatschutz über Bank-Transaktionsreferenz
        aref = e.get('acct_ref', '')
        if aref and Zahlungseingang.objects.filter(bank_referenz=aref).exists():
            duplikate += 1
            continue

        betrag_e = e['betrag']
        rechnung = ref_index.get(e['referenz']) if e['referenz'] else None

        # 1) Exakte QRR-Referenz
        if rechnung and rechnung.vertrag_id and rechnung.offener_betrag > 0:
            betrag = min(max(betrag_e, Decimal('0.01')), rechnung.offener_betrag)
            _verbuche(rechnung, betrag, e, 'Referenz')
            verbucht += 1; zugeordnet_summe += betrag
            continue

        # 2) Fuzzy: exakter Betrag + Name des Auftraggebers passt eindeutig
        name = _norm(e.get('dbtr_name', '')) or _norm(e.get('info', ''))
        kandidaten = [r for r in offene if r.vertrag_id and r.offener_betrag == betrag_e
                      and name and r.vertrag.mieter and _norm(r.vertrag.mieter.nachname) and _norm(r.vertrag.mieter.nachname) in name]
        if len(kandidaten) == 1:
            r = kandidaten[0]
            _verbuche(r, betrag_e, e, 'Name+Betrag')
            verbucht += 1; fuzzy += 1; zugeordnet_summe += betrag_e
            continue

        # 3) Nicht zuordenbar → aufs Durchlaufkonto 1190 parken (nichts geht verloren)
        with transaction.atomic():
            zahlung = Zahlungseingang.objects.create(
                betrag=betrag_e, datum_eingang=e['datum'] or heute,
                buchungs_monat=(e['datum'] or heute).replace(day=1),
                bemerkung=f"camt.053 UNGEKLÄRT: {e.get('dbtr_name','') or e.get('info','') or e.get('referenz','')}"[:255],
                bank_referenz=aref, konto=konto_clearing,
                erstellt_von=request.user, status='verbucht')
            from finance.booking import buche
            buche("1020", "1190", betrag_e,
                  f"camt.053 ungeklärt: {e.get('dbtr_name','') or e.get('referenz','')}",
                  datum=e['datum'] or heute, zahlung=zahlung, user=request.user)
        geklaert += 1

    log_aktion(request, "camt.053-Import", datei.name,
               f"{verbucht} verbucht (davon {fuzzy} fuzzy), CHF {zugeordnet_summe}, {geklaert} auf 1190, {duplikate} Duplikate")
    if verbucht or geklaert:
        teile = [f"{verbucht} Zahlung(en) zugeordnet (CHF {zugeordnet_summe})"]
        if fuzzy:
            teile.append(f"davon {fuzzy} über Name/Betrag")
        if geklaert:
            teile.append(f"{geklaert} ungeklärt auf Durchlaufkonto 1190 geparkt")
        if duplikate:
            teile.append(f"{duplikate} Duplikat(e) übersprungen")
        messages.success(request, "✅ camt.053-Import: " + ", ".join(teile) + ".")
    else:
        messages.warning(request,
            f"Keine neuen Gutschriften verbucht ({duplikate} Duplikat(e) übersprungen).")

    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'
    return redirect(ziel)


# ============================================================
# PERSON-DETAIL (Mieter) — in der neuen Shell
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_person_detail(request, pk):
    from rentals.models import Dokument as RentalsDokument
    from tickets.models import SchadenMeldung
    m = get_object_or_404(Mieter, id=pk)
    basis = _global_filter(request)
    from django.db.models import Q as _Q

    # Verträge, in denen die Person Haupt- ODER Mitmieter ist (2-Personen-Vertrag)
    vertraege = (Mietvertrag.objects.filter(_Q(mieter=m) | _Q(mitmieter=m))
                 .select_related('einheit__liegenschaft').distinct().order_by('-beginn'))
    aktive = [v for v in vertraege if v.status == 'aktiv']
    _vids = list(vertraege.values_list('id', flat=True))

    offene = (DebitorenRechnung.objects
              .filter(vertrag_id__in=_vids, status__in=['offen', 'teilbezahlt'])
              .select_related('vertrag').order_by('faellig_am'))
    total_offen = sum((r.offener_betrag for r in offene), Decimal('0.00'))

    zahlungen = (Zahlungseingang.objects.filter(vertrag_id__in=_vids, status='verbucht')
                 .order_by('-datum_eingang')[:15])
    # Dokumente am Mieter ODER an seinen Verträgen (Vertrags-PDF, Mietzins,
    # Kündigung …) — hier steuert der Verwalter die Portal-Sichtbarkeit.
    dokumente = (RentalsDokument.objects.filter(_Q(mieter=m) | _Q(vertrag_id__in=_vids))
                 .distinct().order_by('-datum')[:25])

    vertrag_rows = []
    for v in vertraege:
        label, cls = VERTRAG_PILL.get(v.status, (v.status, 'bg-slate-100 text-slate-500'))
        vertrag_rows.append({'v': v, 'label': label, 'cls': cls,
                             'brutto': (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0'))})

    from core.models import AktivitaetsLog
    verlauf = list(AktivitaetsLog.objects.filter(
        _Q(ziel_typ='person', ziel_id=m.id) | _Q(ziel_typ='vertrag', ziel_id__in=_vids)
    ).select_related('benutzer')[:50])

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('vertraege', 'Verträge', vertraege.count() or None),
        ('finanzen', 'Finanzen', offene.count() or None),
        ('dokumente', 'Dokumente', dokumente.count() or None),
        ('aktivitaet', 'Journal', m.kommunikationen.count() or None),
        ('verlauf', 'Verlauf', len(verlauf) or None),
    ]
    return render(request, 'fw/person_detail.html', {
        **basis, 'nav': 'personen', 'm': m, 'verlauf': verlauf,
        'vertrag_rows': vertrag_rows,
        'anzahl_aktive': len(aktive),
        'brutto_monat': sum((r['brutto'] for r in vertrag_rows if r['v'].status == 'aktiv'), Decimal('0.00')),
        'offene': offene, 'total_offen': total_offen,
        'zahlungen': zahlungen, 'dokumente': dokumente,
        'telefon': m.mobile or m.telefon_privat or m.telefon_geschaeft,
        'kommunikationen': m.kommunikationen.select_related('vertrag', 'erstellt_von')[:50],
        'portal_user': getattr(m, 'benutzer', None),
        'tab_liste': tab_liste,
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_mieter_portal_zugang(request, pk):
    """Erstellt/aktualisiert einen Mieterportal-Login und zeigt die Zugangsdaten einmalig."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth.models import User
    from core.auth import log_aktion
    import secrets
    m = get_object_or_404(Mieter, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/personen/{m.id}/')
    aktion = request.POST.get('aktion', 'erstellen')
    if aktion == 'entfernen':
        if m.benutzer_id:
            u = m.benutzer
            m.benutzer = None
            m.save(update_fields=['benutzer'])
            # Konto vollständig entfernen (kein verwaistes .1/.2-Konto zurücklassen)
            try:
                u.delete()
            except Exception:
                u.is_active = False
                u.save(update_fields=['is_active'])
        messages.success(request, "Portal-Zugang entfernt.")
        return redirect(f'/neu/personen/{m.id}/')

    # Benutzername: E-Mail bevorzugt, sonst mieter<id>
    basis_name = (m.email or f"mieter{m.id}").strip().lower()
    passwort = secrets.token_urlsafe(9)
    if m.benutzer_id:
        u = m.benutzer
        u.set_password(passwort)
        u.is_active = True
        u.save()
    else:
        username = basis_name
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{basis_name}.{i}"
            i += 1
        u = User.objects.create_user(username=username, email=m.email or '', password=passwort)
        m.benutzer = u
        m.save(update_fields=['benutzer'])
    log_aktion(request, "Mieterportal-Zugang erstellt", m.display_name, u.username)

    # Zugangsdaten per E-Mail an den Mieter senden (Benutzername, Passwort, Login-Link)
    mail_ok = False
    if m.email:
        from core.utils.email_service import send_mieter_portal_zugang
        from crm.models import Verwaltung
        vw = Verwaltung.objects.first()
        # Feste Produktions-Basis-URL (settings) statt Request-Host — der Link
        # muss immer auf die öffentliche Portal-Adresse zeigen.
        from django.conf import settings as _settings
        login_url = _settings.PORTAL_BASE_URL.rstrip('/') + '/portal/login/'
        anrede = (f"{m.anrede} " if m.anrede else "") + (m.nachname or m.display_name)
        mail_ok = send_mieter_portal_zugang(
            m.email, anrede.strip(), u.username, passwort, login_url,
            absender_firma=(vw.firma if vw else ''))

    if mail_ok:
        messages.success(request, f"✅ Portal-Zugang aktiv. Zugangsdaten wurden an {m.email} gesendet. (Benutzername: {u.username})")
    elif m.email:
        messages.warning(request, f"⚠️ Portal-Zugang aktiv, aber E-Mail-Versand fehlgeschlagen. Benutzername: {u.username} · Passwort: {passwort} — bitte manuell mitteilen.")
    else:
        messages.success(request, f"✅ Portal-Zugang aktiv. Keine E-Mail hinterlegt — Benutzername: {u.username} · Passwort: {passwort} (bitte dem Mieter sicher mitteilen, wird nur einmal angezeigt).")
    return redirect(f'/neu/personen/{m.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterkonto_pdf(request, pk):
    """Kontoauszug (PDF) eines Mieters für die Verwaltung."""
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from core.services.mieterkonto import generate_mieterkonto_pdf
    m = get_object_or_404(Mieter, id=pk)
    pdf = generate_mieterkonto_pdf(m, verwaltung=Verwaltung.objects.first())
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Kontoauszug_{m.nachname or m.id}.pdf"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kommunikation_neu(request):
    """Schnelle Telefonnotiz / Kommunikation zu einem Kontakt erfassen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Kommunikation
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/personen/')
    P = request.POST
    m = get_object_or_404(Mieter, id=P.get('mieter_id'))
    inhalt = (P.get('inhalt') or '').strip()
    if not inhalt:
        messages.error(request, "Bitte einen Inhalt/Notiztext erfassen.")
        return redirect(f'/neu/personen/{m.id}/')
    vertrag = m.vertraege.order_by('-beginn').first()
    Kommunikation.objects.create(
        mieter=m, vertrag=vertrag,
        liegenschaft=vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None,
        typ=P.get('typ', 'telefon'), richtung=P.get('richtung', 'eingehend'),
        betreff=(P.get('betreff') or '').strip(), inhalt=inhalt,
        erstellt_von=request.user,
    )
    log_aktion(request, "Kommunikation erfasst", str(m), P.get('typ', 'telefon'))
    messages.success(request, "✅ Notiz im Kontaktjournal erfasst.")
    return redirect(f'/neu/personen/{m.id}/#p-aktivitaet')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dokument_portal_toggle(request, pk):
    """Schaltet die Mieterportal-Sichtbarkeit eines Dokuments um."""
    from django.shortcuts import redirect
    from rentals.models import Dokument as RentalsDokument
    from core.auth import log_aktion
    d = get_object_or_404(RentalsDokument, id=pk)
    if request.method == 'POST':
        d.im_portal_sichtbar = not d.im_portal_sichtbar
        d.save(update_fields=['im_portal_sichtbar'])
        log_aktion(request, "Dokument-Portalsichtbarkeit", d.bezeichnung or d.titel,
                   'sichtbar' if d.im_portal_sichtbar else 'ausgeblendet')
    return redirect(request.META.get('HTTP_REFERER') or (f'/neu/personen/{d.mieter_id}/' if d.mieter_id else '/neu/dokumente/'))


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_person_loeschen(request, pk):
    """Person (Mieter/Kontakt) löschen. Blockiert bei aktivem Vertrag —
    dieser muss zuerst gekündigt/beendet werden. Entfernt auch den
    verknüpften Mieterportal-Zugang."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    m = get_object_or_404(Mieter, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/personen/{m.id}/')

    aktive = m.vertraege.filter(status='aktiv').count()
    if aktive:
        messages.error(request, f"❌ Person kann nicht gelöscht werden: {aktive} aktive(r) Vertrag/Verträge. Bitte zuerst kündigen/beenden.")
        return redirect(f'/neu/personen/{m.id}/')

    name = m.display_name
    anz_vertraege = m.vertraege.count()
    # Verknüpften Portal-Login mitentfernen
    if m.benutzer_id:
        try:
            m.benutzer.delete()
        except Exception:
            pass
    log_aktion(request, "Person gelöscht", name,
               f"inkl. {anz_vertraege} Vertrag/Verträge + zugehörige Daten" if anz_vertraege else "")
    m.delete()   # cascade: Verträge (beendet/Entwurf), Kommunikation, Dokumente etc.
    zusatz = f" inkl. {anz_vertraege} beendete(r)/Entwurf-Vertrag/Verträge" if anz_vertraege else ""
    messages.success(request, f'🗑️ „{name}" gelöscht{zusatz}.')
    return redirect('/neu/personen/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_person_form(request, pk=None):
    """Person (Mieter/Kontakt) erfassen oder bearbeiten — Fairwalter-Stil."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion, snapshot_model, diff_model
    m = get_object_or_404(Mieter, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        # Alt-Zustand für Vorher→Nachher (nur beim Bearbeiten, frisch aus der DB).
        alt_snap = snapshot_model(Mieter.objects.get(pk=m.pk)) if m is not None else {}
        obj = m or Mieter()
        obj.typ = P.get('typ', 'person')
        obj.anrede = P.get('anrede', '').strip()
        obj.vorname = P.get('vorname', '').strip()
        obj.nachname = P.get('nachname', '').strip()
        obj.firmen_name = P.get('firmen_name', '').strip()
        obj.uid_nummer = P.get('uid_nummer', '').strip()
        obj.kontaktperson = P.get('kontaktperson', '').strip()
        obj.email = P.get('email', '').strip()
        obj.telefon_privat = P.get('telefon_privat', '').strip()
        obj.mobile = P.get('mobile', '').strip()
        obj.strasse = P.get('strasse', '').strip()
        obj.adresszusatz = P.get('adresszusatz', '').strip()
        obj.plz = P.get('plz', '').strip()
        obj.ort = P.get('ort', '').strip()
        gd = P.get('geburtsdatum', '').strip()
        try:
            obj.geburtsdatum = date.fromisoformat(gd) if gd else None
        except ValueError:
            obj.geburtsdatum = None
        obj.iban = P.get('iban', '').strip()
        obj.notizen = P.get('notizen', '').strip()

        # --- Pflichtfeld-Validierung ---
        fehler = []
        if obj.typ == 'firma':
            if not obj.firmen_name:
                fehler.append("Firmenname ist erforderlich.")
        else:
            if not obj.nachname:
                fehler.append("Nachname ist erforderlich.")
        if obj.email and '@' not in obj.email:
            fehler.append("E-Mail-Adresse ist ungültig.")
        if obj.iban:
            from core.services.iban import ist_gueltige_iban, formatiere_iban
            if not ist_gueltige_iban(obj.iban):
                fehler.append("IBAN ist ungültig (Prüfsumme stimmt nicht).")
            else:
                obj.iban = formatiere_iban(obj.iban)
        if fehler:
            for f in fehler:
                messages.error(request, f"❌ {f}")
            return render(request, 'fw/person_form.html', {
                **basis, 'nav': 'personen', 'm': obj, 'ist_neu': pk is None,
            })

        # --- Dublettenprüfung (nur neue Person, überspringbar) ---
        if not pk and P.get('dublette_ok') != '1':
            dubletten = _finde_dubletten(obj.typ, obj.vorname, obj.nachname,
                                         obj.firmen_name, obj.email, obj.plz)
            if dubletten:
                return render(request, 'fw/person_form.html', {
                    **basis, 'nav': 'personen', 'm': obj, 'ist_neu': True,
                    'dubletten': dubletten, 'dublette_warnung': True,
                })

        obj.save()
        aenderungen = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Person bearbeitet" if pk else "Person erstellt",
                   obj.display_name, aenderungen, ziel=obj)
        messages.success(request, f"✅ {obj.display_name} gespeichert.")
        return redirect(f'/neu/personen/{obj.id}/')

    return render(request, 'fw/person_form.html', {
        **basis, 'nav': 'personen', 'm': m,
        'ist_neu': m is None,
    })


def _finde_dubletten(typ, vorname, nachname, firmen_name, email, plz, exclude_id=None):
    """Findet mögliche Dubletten: gleiche E-Mail ODER (Name + PLZ)."""
    from django.db.models import Q
    qs = Mieter.objects.all()
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    bedingung = Q(pk__in=[])
    if email:
        bedingung |= Q(email__iexact=email)
    if typ == 'firma' and firmen_name:
        bedingung |= Q(firmen_name__iexact=firmen_name)
    elif nachname:
        namensfilter = Q(nachname__iexact=nachname)
        if vorname:
            namensfilter &= Q(vorname__iexact=vorname)
        if plz:
            namensfilter &= Q(plz=plz)
        bedingung |= namensfilter
    treffer = qs.filter(bedingung).distinct()[:5]
    return [{'id': t.id, 'name': t.display_name, 'email': t.email,
             'ort': f"{t.plz} {t.ort}".strip()} for t in treffer]


# ============================================================
# ETAPPE D: KREDITOREN (Rechnungseingang -> Freigabe -> Zahlung)
# ============================================================

KRED_PILL = {
    'neu':         ('Neu / Prüfen', 'bg-amber-50 text-amber-700'),
    'freigegeben': ('Freigegeben',  'bg-sky-50 text-sky-700'),
    'in_zahlung':  ('In Zahlung',   'bg-indigo-50 text-indigo-700'),
    'teilbezahlt': ('Teilbezahlt',  'bg-yellow-50 text-yellow-700'),
    'bezahlt':     ('Bezahlt',      'bg-emerald-50 text-emerald-700'),
    'storniert':   ('Storniert',    'bg-slate-100 text-slate-500'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kreditoren(request):
    from finance.models import KreditorenRechnung
    from core.auth import hat_rolle, VERWALTUNGS_ROLLEN
    from django.contrib import messages
    heute = timezone.now().date()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (KreditorenRechnung.objects.exclude(status='storniert')
          .select_related('liegenschaft', 'konto').order_by('-id'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    status_filter = request.GET.get('status', '')
    if status_filter in KRED_PILL:
        qs = qs.filter(status=status_filter)

    rows = []
    total_offen = Decimal('0.00')     # freigegeben, noch nicht bezahlt
    total_neu = Decimal('0.00')       # zu prüfen
    anzahl_neu = 0
    for k in qs:
        label, cls = KRED_PILL.get(k.status, (k.status, 'bg-slate-100 text-slate-500'))
        betrag = k.betrag or Decimal('0.00')
        offen_betrag = k.offener_betrag
        faellig = k.faellig_am
        if k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt'):
            total_offen += offen_betrag
        elif k.status == 'neu':
            total_neu += betrag
            anzahl_neu += 1
        rows.append({
            'k': k, 'betrag': betrag, 'status_label': label, 'pill_cls': cls,
            'faellig': faellig,
            'ueberfaellig': bool(faellig and faellig < heute and k.status != 'bezahlt'),
            'lieferant': k.lieferant or 'Wird gescannt …',
            'objekt': f"{k.liegenschaft.strasse}, {k.liegenschaft.ort}" if k.liegenschaft else '—',
            'konto': f"{k.konto.nummer} {k.konto.bezeichnung}" if k.konto else None,
            'beleg_url': k.beleg_scan.url if k.beleg_scan else None,
            'kann_bezahlen': k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt'),
            'in_zahlung': k.status == 'in_zahlung',
            'teilbezahlt': k.status == 'teilbezahlt',
            'offen_betrag': offen_betrag,
            'offen_wv': k.offen_weiterzuverrechnen,
            'kann_weiterverrechnen': (k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt', 'bezahlt')
                                      and k.offen_weiterzuverrechnen > 0),
        })

    status_chips = [('', 'Alle')] + [(k, v[0]) for k, v in KRED_PILL.items() if k != 'storniert']

    from finance.models import Buchungskonto
    aufwand_konten = Buchungskonto.objects.filter(typ='aufwand').order_by('nummer')
    liegenschaften = Liegenschaft.objects.order_by('strasse')
    # Für pain.001: freigegebene Rechnungen mit gültiger IBAN
    zahlbar = [r for r in rows if r['k'].status == 'freigegeben' and (r['k'].iban or '').strip()]
    return render(request, 'fw/kreditoren.html', {
        **basis, 'nav': 'kreditoren', 'rows': rows,
        'status_filter': status_filter, 'status_chips': status_chips,
        'total_offen': total_offen, 'total_neu': total_neu, 'anzahl_neu': anzahl_neu,
        'anzahl': len(rows),
        'anzahl_zahlbar': len(zahlbar),
        'darf_bezahlen': hat_rolle(request.user, VERWALTUNGS_ROLLEN),
        'aufwand_konten': aufwand_konten, 'liegenschaften': liegenschaften,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_kreditoren_pain001(request):
    """Erzeugt eine ISO-20022 pain.001-Zahlungsdatei aus allen freigegebenen
    Kreditorenrechnungen (für den e-Banking-Massenupload)."""
    from django.http import HttpResponse
    from django.contrib import messages
    from django.shortcuts import redirect
    from finance.models import KreditorenRechnung
    from crm.models import Verwaltung
    from core.services.pain001 import generate_pain001
    from core.auth import log_aktion

    basis = _global_filter(request)
    qs = KreditorenRechnung.objects.filter(status='freigegeben')
    if basis['aktive_lg']:
        qs = qs.filter(liegenschaft=basis['aktive_lg'])
    rechnungen = list(qs)
    if not rechnungen:
        messages.error(request, "Keine freigegebenen Kreditorenrechnungen für die Zahlungsdatei.")
        return redirect('/neu/kreditoren/?status=freigegeben')

    vw = Verwaltung.objects.first()
    debtor_iban = (vw.iban if vw else '') or ''
    if not debtor_iban.strip():
        messages.error(request, "Für die Zahlungsdatei fehlt die IBAN der Verwaltung (Profil → Account).")
        return redirect('/neu/kreditoren/?status=freigegeben')

    heute = timezone.localdate()
    jetzt = timezone.now()
    msg_id = f"SWISSIMMO-{jetzt.strftime('%Y%m%d%H%M%S')}"
    xml, anzahl, summe, skipped = generate_pain001(
        rechnungen, debtor_name=(vw.firma if vw else 'Immobilienverwaltung'),
        debtor_iban=debtor_iban, msg_id=msg_id,
        exec_date=heute.isoformat(), now_iso=jetzt.strftime('%Y-%m-%dT%H:%M:%S'))

    if anzahl == 0:
        messages.error(request, "Keine zahlbaren Rechnungen (fehlende IBAN/Betrag).")
        return redirect('/neu/kreditoren/?status=freigegeben')

    # Enthaltene Rechnungen auf "in Zahlung" setzen → tauchen im nächsten
    # Zahllauf NICHT wieder auf (Doppelzahlungsschutz). Bestätigung via "Bezahlen".
    n_markiert = 0
    for r in rechnungen:
        if (r.iban or '').strip() and (r.betrag or 0) > 0:
            r.status = 'in_zahlung'
            r.save(update_fields=['status'])
            n_markiert += 1

    log_aktion(request, "pain.001 erzeugt", msg_id,
               f"{anzahl} Zahlungen, CHF {summe} · {n_markiert} auf 'in Zahlung'")
    resp = HttpResponse(xml, content_type='application/xml')
    resp['Content-Disposition'] = f'attachment; filename="{msg_id}.xml"'
    return resp


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_kreditor_bezahlen(request):
    """Bezahlt eine freigegebene Kreditorenrechnung — Kreditoren 2000 an Bank 1020
    (dieselbe Doppelbuchung wie die Finanz-API pay_kreditor)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, Buchungskonto, Buchung
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_kreditoren')

    from finance.models import KreditorenZahlung
    k = get_object_or_404(KreditorenRechnung, id=request.POST.get('rechnung_id'))
    if k.status in ('bezahlt', 'storniert', 'neu'):
        messages.error(request, "Diese Rechnung kann nicht (mehr) bezahlt werden.")
        return redirect('fw_kreditoren')

    # Optionaler Teilbetrag; Standard = offener Betrag
    def _dec(x):
        try:
            return Decimal(str(x).replace(',', '.').strip())
        except Exception:
            return None
    offen = k.offener_betrag
    betrag = _dec(request.POST.get('betrag')) or offen
    betrag = min(max(betrag, Decimal('0.00')), offen)
    if betrag <= 0:
        messages.error(request, "Kein offener Betrag zu bezahlen.")
        return redirect('fw_kreditoren')

    with transaction.atomic():
        from finance.booking import buche
        zahlung = KreditorenZahlung.objects.create(
            kreditor=k, betrag=betrag, datum=timezone.localdate(),
            bemerkung=f"Zahlung {k.lieferant}", erstellt_von=request.user)
        buche("2000", "1020", betrag, f"Zahlung {k.lieferant} - {k.referenz}",
              liegenschaft=k.liegenschaft, kreditor=k, user=request.user)
        k.status = 'bezahlt' if k.offener_betrag <= 0 else 'teilbezahlt'
        k.save(update_fields=['status'])

    log_aktion(request, "Kreditorenrechnung bezahlt", k.lieferant or f"Rechnung #{k.id}",
               f"CHF {betrag}" + (f" (offen CHF {k.offener_betrag})" if k.status == 'teilbezahlt' else ""))
    messages.success(request, f"✅ CHF {betrag} an {k.lieferant or 'Lieferant'} bezahlt"
                              + (f" — noch offen CHF {k.offener_betrag}." if k.status == 'teilbezahlt' else "."))
    ziel = '/neu/kreditoren/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_kreditor_zahlung_zuruecksetzen(request, pk):
    """Setzt eine 'in Zahlung' stehende Rechnung auf 'freigegeben' zurück —
    falls die pain.001-Datei doch nicht ausgeführt wurde. Dann kommt sie im
    nächsten Zahllauf wieder mit."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    k = get_object_or_404(KreditorenRechnung, id=pk)
    if k.status == 'in_zahlung':
        k.status = 'freigegeben'
        k.save(update_fields=['status'])
        log_aktion(request, "Zahllauf zurückgesetzt", k.lieferant or f"Rechnung #{k.id}", '')
        messages.success(request, f"↩︎ '{k.lieferant}' wieder freigegeben (nicht mehr in Zahlung).")
    ziel = '/neu/kreditoren/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return redirect(ziel)


# ============================================================
# ETAPPE D: SCHADENSFÄLLE (Tickets)
# ============================================================

TICKET_PILL = {
    'neu':                   ('Neu',                'bg-rose-50 text-rose-600'),
    'in_bearbeitung':        ('In Bearbeitung',     'bg-sky-50 text-sky-700'),
    'warte_auf_mieter':      ('Warte auf Mieter',   'bg-amber-50 text-amber-700'),
    'warte_auf_handwerker':  ('Warte auf Handwerker','bg-amber-50 text-amber-700'),
    'erledigt':              ('Erledigt',           'bg-emerald-50 text-emerald-700'),
}
PRIO_PILL = {
    'hoch':   ('Hoch',   'bg-rose-100 text-rose-700'),
    'mittel': ('Mittel', 'bg-amber-50 text-amber-700'),
    'tief':   ('Tief',   'bg-slate-100 text-slate-500'),
    'niedrig':('Tief',   'bg-slate-100 text-slate-500'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_schaeden(request):
    from tickets.models import SchadenMeldung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von')
          .order_by('-erstellt_am'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    status_filter = request.GET.get('status', '')
    if status_filter == 'offen':
        qs = qs.exclude(status='erledigt')
    elif status_filter in TICKET_PILL:
        qs = qs.filter(status=status_filter)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(titel__icontains=q) | Q(beschreibung__icontains=q)
                       | Q(kategorie__icontains=q) | Q(liegenschaft__strasse__icontains=q))

    rows = []
    offen = 0
    in_arbeit = 0
    for t in qs:
        s_label, s_cls = TICKET_PILL.get(t.status, (t.status, 'bg-slate-100 text-slate-500'))
        p_label, p_cls = PRIO_PILL.get((t.prioritaet or '').lower(), (t.prioritaet or 'Mittel', 'bg-slate-100 text-slate-500'))
        if t.status != 'erledigt':
            offen += 1
        if t.status == 'in_bearbeitung':
            in_arbeit += 1
        melder = (t.gemeldet_von.display_name if t.gemeldet_von_id
                  else f"{t.melder_vorname or ''} {t.melder_nachname or ''}".strip() or '—')
        rows.append({
            't': t, 's_label': s_label, 's_cls': s_cls, 'p_label': p_label, 'p_cls': p_cls,
            'objekt': f"{t.liegenschaft.strasse}, {t.liegenschaft.ort}" if t.liegenschaft_id else '—',
            'melder': melder,
        })

    chips = [('', 'Alle'), ('offen', 'Offen')] + [(k, v[0]) for k, v in TICKET_PILL.items()]
    liegenschaften = Liegenschaft.objects.order_by('strasse')
    einheiten = Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung')
    from django.contrib import messages
    return render(request, 'fw/schaeden.html', {
        **basis, 'nav': 'schadensfaelle', 'rows': rows,
        'status_filter': status_filter, 'status_chips': chips, 'q': q,
        'anzahl': len(rows), 'offen': offen, 'in_arbeit': in_arbeit,
        'liegenschaften': liegenschaften, 'einheiten': einheiten,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_neu(request):
    """Intern erfassten Schaden (z.B. telefonisch gemeldet) anlegen — sendet dem
    Melder (falls E-Mail) automatisch die Eingangsbestätigung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_schaeden')

    titel = (request.POST.get('titel') or '').strip()
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id')).first()
    if not titel or not lg:
        messages.error(request, "Titel und Liegenschaft sind erforderlich.")
        return redirect('fw_schaeden')

    einheit = Einheit.objects.filter(id=request.POST.get('einheit_id')).first() if request.POST.get('einheit_id') else None
    t = SchadenMeldung.objects.create(
        liegenschaft=lg, betroffene_einheit=einheit,
        titel=titel, beschreibung=(request.POST.get('beschreibung') or '').strip(),
        kategorie=(request.POST.get('kategorie') or '').strip(),
        melder_vorname=(request.POST.get('melder_vorname') or '').strip(),
        melder_nachname=(request.POST.get('melder_nachname') or '').strip(),
        email_melder=(request.POST.get('email_melder') or '').strip(),
        tel_melder=(request.POST.get('tel_melder') or '').strip(),
        prioritaet=request.POST.get('prioritaet', 'mittel'), status='neu',
    )
    ok = False
    if t.email_melder:
        from crm.models import Vorlage
        from core.services.ticket_workflow import ticket_kontext
        betreff = f"Eingangsbestätigung: {t.titel} (Ticket #{t.id})"
        v = Vorlage.objects.filter(kategorie='ticket_eingang').first()
        if v and v.inhalt:
            k = ticket_kontext(t)
            body = v.inhalt
            for kk, vv in k.items():
                body = body.replace('{' + kk + '}', str(vv))
            if v.betreff:
                betreff = v.betreff
                for kk, vv in k.items():
                    betreff = betreff.replace('{' + kk + '}', str(vv))
        else:
            body = (f"Guten Tag\n\nWir haben Ihre Schadenmeldung '{t.titel}' erhalten (Ticket #{t.id}) "
                    f"und kümmern uns darum. Wir melden uns, sobald ein Handwerker beauftragt wurde.\n\n"
                    f"Freundliche Grüsse\nIhre Liegenschaftsverwaltung")
        ok = send_ticket_email(t.email_melder, betreff, body)

    log_aktion(request, "Schaden intern erfasst", f"Ticket #{t.id}", titel)
    messages.success(request, f"✅ Ticket #{t.id} erstellt" + (f" · Eingangsbestätigung an {t.email_melder} gesendet." if ok else "."))
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_schaden_detail(request, pk):
    from tickets.models import SchadenMeldung
    t = get_object_or_404(
        SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von'), id=pk)
    basis = _global_filter(request)

    # Beim Öffnen als gelesen markieren (entfernt den Sidebar-Badge-Zähler)
    if not t.gelesen:
        t.gelesen = True
        t.save(update_fields=['gelesen'])

    s_label, s_cls = TICKET_PILL.get(t.status, (t.status, 'bg-slate-100 text-slate-500'))
    p_label, p_cls = PRIO_PILL.get((t.prioritaet or '').lower(), (t.prioritaet or 'Mittel', 'bg-slate-100 text-slate-500'))
    nachrichten = t.nachrichten.order_by('erstellt_am')
    auftraege = t.handwerker_auftraege.select_related('handwerker').order_by('-beauftragt_am')
    melder = (t.gemeldet_von.display_name if t.gemeldet_von_id
              else f"{t.melder_vorname or ''} {t.melder_nachname or ''}".strip() or '—')

    auftraege = list(auftraege)
    kosten_geschaetzt = sum((a.kosten_geschaetzt or Decimal('0')) for a in auftraege)
    kosten_effektiv = sum((a.kosten_effektiv or Decimal('0')) for a in auftraege)

    from crm.models import Handwerker
    from core.services.ticket_workflow import vorlage_text
    handwerker_liste = Handwerker.objects.all().order_by('firma')
    # Auftragstext-Vorschlag (Vorlage ticket_handwerker) für das Beauftragen-Formular
    _, auftrag_vorschlag = vorlage_text('ticket_handwerker', t)
    melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('verlauf', 'Verlauf', nachrichten.count() or None),
        ('handwerker', 'Handwerker & Kosten', len(auftraege) or None),
    ]
    from django.contrib import messages
    return render(request, 'fw/schaden_detail.html', {
        **basis, 'nav': 'schadensfaelle', 't': t,
        's_label': s_label, 's_cls': s_cls, 'p_label': p_label, 'p_cls': p_cls,
        'nachrichten': nachrichten, 'auftraege': auftraege, 'melder': melder,
        'kosten_geschaetzt': kosten_geschaetzt, 'kosten_effektiv': kosten_effektiv,
        'tab_liste': tab_liste,
        'handwerker_liste': handwerker_liste, 'auftrag_vorschlag': auftrag_vorschlag,
        'melder_email': melder_email, 'status_wahl': TICKET_PILL,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_auftrag(request, pk):
    """Handwerker beauftragen — automatisiert: Auftrag anlegen, Mail an Handwerker
    (aus Vorlage) + Info-Mail an Melder, Status → in Bearbeitung, Verlaufseintrag."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung, HandwerkerAuftrag, TicketNachricht
    from crm.models import Handwerker
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{pk}/')
    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von'), id=pk)
    hw = get_object_or_404(Handwerker, id=request.POST.get('handwerker_id'))
    auftragstext = (request.POST.get('auftragstext') or '').strip()

    with transaction.atomic():
        auftrag = HandwerkerAuftrag.objects.create(ticket=t, handwerker=hw, bemerkung=auftragstext, status='offen')
        TicketNachricht.objects.create(ticket=t, absender_name="System", typ='system',
                                       nachricht=f"Auftrag an {hw.firma} vergeben.", is_intern=True)
        if t.status == 'neu':
            t.status = 'in_bearbeitung'
        t.save()

    # Mail an Handwerker (Auftragstext, Foto als Anhang)
    hw_betreff, hw_text = vorlage_text('ticket_handwerker', t, handwerker=hw)
    if auftragstext:
        hw_text = auftragstext
    hw_ok = send_ticket_email(hw.email, hw_betreff, hw_text, foto_field=t.foto) if hw.email else False

    # Info-Mail an Melder
    melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')
    m_betreff, m_text = vorlage_text('ticket_melder', t, handwerker=hw)
    melder_ok = send_ticket_email(melder_email, m_betreff, m_text) if melder_email else False

    if melder_ok:
        TicketNachricht.objects.create(ticket=t, absender_name="System", typ='system',
                                       nachricht=f"Melder automatisch informiert ({melder_email}).", is_intern=True)

    log_aktion(request, "Handwerker beauftragt", f"Ticket #{t.id}", f"{hw.firma}")
    hinweise = []
    hinweise.append("Mail an Handwerker gesendet" if hw_ok else ("Handwerker ohne E-Mail" if not hw.email else "Mail an Handwerker fehlgeschlagen"))
    hinweise.append("Melder informiert" if melder_ok else ("Melder ohne E-Mail" if not melder_email else "Melder-Mail fehlgeschlagen"))
    messages.success(request, f"✅ {hw.firma} beauftragt · Status: In Bearbeitung · " + " · ".join(hinweise) + ".")
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_status(request, pk):
    """Ticket-Status ändern; optional Melder automatisch informieren
    (bei „erledigt" die Erledigt-Vorlage)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung, TicketNachricht
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{pk}/')
    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von'), id=pk)
    neu = request.POST.get('status')
    if neu not in dict(SchadenMeldung.STATUS_CHOICES):
        messages.error(request, "Ungültiger Status.")
        return redirect(f'/neu/schaeden/{t.id}/')
    t.status = neu
    t.save()
    TicketNachricht.objects.create(ticket=t, absender_name="System", typ='system',
                                   nachricht=f"Status geändert: {t.get_status_display()}.", is_intern=True)

    info = ""
    if request.POST.get('melder_informieren') == 'on':
        melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')
        kat = 'ticket_erledigt' if neu == 'erledigt' else 'ticket_melder_status'
        betreff, text = vorlage_text(kat, t, status=t.get_status_display())
        if melder_email and send_ticket_email(melder_email, betreff, text):
            info = f" · Melder informiert ({melder_email})"
            TicketNachricht.objects.create(ticket=t, absender_name="System", typ='system',
                                           nachricht=f"Melder über Status '{t.get_status_display()}' informiert.", is_intern=True)

    log_aktion(request, "Ticket-Status geändert", f"Ticket #{t.id}", t.get_status_display())
    messages.success(request, f"✅ Status: {t.get_status_display()}{info}.")
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_antwort(request, pk):
    """Antwort/Nachricht an den Melder — als Verlaufseintrag + E-Mail."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung, TicketNachricht
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{pk}/')
    t = get_object_or_404(SchadenMeldung.objects.select_related('liegenschaft', 'gemeldet_von'), id=pk)
    text = (request.POST.get('text') or '').strip()
    if not text:
        return redirect(f'/neu/schaeden/{t.id}/')

    absender = (request.user.get_full_name() or request.user.username or 'Verwaltung')
    TicketNachricht.objects.create(ticket=t, absender_name=absender, typ='antwort_senden',
                                   nachricht=text, is_von_verwaltung=True)
    if t.status == 'neu':
        t.status = 'in_bearbeitung'
        t.save()

    melder_email = t.email_melder or (t.gemeldet_von.email if t.gemeldet_von_id else '')
    ok = send_ticket_email(melder_email, f"Ihre Meldung (Ticket #{t.id})", text) if melder_email else False
    log_aktion(request, "Ticket-Antwort gesendet", f"Ticket #{t.id}", '')
    if ok:
        messages.success(request, f"✅ Antwort an {melder_email} gesendet.")
    elif melder_email:
        messages.error(request, "Antwort gespeichert, aber E-Mail-Versand fehlgeschlagen.")
    else:
        messages.success(request, "Antwort im Verlauf gespeichert (Melder ohne E-Mail).")
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_auftrag_kosten(request, pk):
    """Reparaturkosten auf einem Handwerker-Auftrag erfassen; optional eine
    Kreditorenrechnung erzeugen und verknüpfen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import HandwerkerAuftrag
    from finance.models import KreditorenRechnung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_schaeden')
    a = get_object_or_404(HandwerkerAuftrag.objects.select_related('ticket__liegenschaft', 'handwerker'), id=pk)

    def _dec(name):
        raw = (request.POST.get(name) or '').strip().replace(',', '.')
        if not raw:
            return None
        try:
            return Decimal(raw)
        except Exception:
            return None

    a.kosten_geschaetzt = _dec('kosten_geschaetzt')
    a.kosten_effektiv = _dec('kosten_effektiv')

    # Reparaturfreigabe anfordern: manuell oder ab Schwellenwert (CHF 1'000)
    REPARATUR_FREIGABE_SCHWELLE = Decimal('1000')
    freigabe_anfordern = request.POST.get('freigabe_anfordern') == 'on'
    ueber_schwelle = (a.kosten_geschaetzt or Decimal('0')) >= REPARATUR_FREIGABE_SCHWELLE
    if a.freigabe_status in ('nicht_noetig', 'abgelehnt') and (freigabe_anfordern or ueber_schwelle):
        a.freigabe_status = 'ausstehend'
        a.freigabe_datum = None
        messages.info(request, "ℹ️ Reparatur zur Freigabe an den Eigentümer weitergeleitet (Portal).")

    # Optional Kreditorenrechnung erstellen
    if request.POST.get('kreditor_erstellen') == 'on' and a.kosten_effektiv and not a.kreditoren_rechnung_id:
        kr = KreditorenRechnung.objects.create(
            liegenschaft=a.ticket.liegenschaft,
            lieferant=(a.handwerker.firma if a.handwerker_id else 'Handwerker'),
            betrag=a.kosten_effektiv,
            status='neu',
        )
        a.kreditoren_rechnung = kr
        messages.success(request, f"✅ Kosten erfasst und Kreditorenrechnung über CHF {a.kosten_effektiv} erstellt (Status: Neu — im Kreditoren-Tab freigeben).")
    else:
        messages.success(request, "✅ Kosten erfasst.")
    a.save()
    log_aktion(request, "Reparaturkosten erfasst", f"Ticket #{a.ticket_id}",
               f"geschätzt {a.kosten_geschaetzt}, effektiv {a.kosten_effektiv}")
    return redirect(f'/neu/schaeden/{a.ticket_id}/')


# ============================================================
# ETAPPE D: DIENSTLEISTER (Handwerkerstamm)
# ============================================================

BRANCHE_ICON = {
    'sanitaer': ('fa-faucet-drip', 'bg-sky-50 text-sky-600'),
    'elektro': ('fa-bolt', 'bg-amber-50 text-amber-600'),
    'maler': ('fa-paint-roller', 'bg-orange-50 text-orange-600'),
    'schreiner': ('fa-hammer', 'bg-yellow-50 text-yellow-700'),
    'schloss': ('fa-key', 'bg-slate-100 text-slate-600'),
    'allgemein': ('fa-screwdriver-wrench', 'bg-indigo-50 text-indigo-600'),
    'garten': ('fa-tree', 'bg-emerald-50 text-emerald-600'),
    'reinigung': ('fa-broom', 'bg-teal-50 text-teal-600'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_dienstleister(request):
    from crm.models import Handwerker
    from tickets.models import HandwerkerAuftrag
    basis = _global_filter(request)

    qs = Handwerker.objects.all().order_by('firma')
    branche_filter = request.GET.get('branche', '')
    if branche_filter:
        qs = qs.filter(branche=branche_filter)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(firma__icontains=q) | Q(kontaktperson__icontains=q) | Q(email__icontains=q))

    # Offene Aufträge je Handwerker zählen
    offene = {}
    for a in HandwerkerAuftrag.objects.exclude(status='erledigt').values_list('handwerker_id', flat=True):
        offene[a] = offene.get(a, 0) + 1

    rows = []
    for h in qs:
        icon, cls = BRANCHE_ICON.get(h.branche, ('fa-screwdriver-wrench', 'bg-slate-100 text-slate-600'))
        rows.append({
            'h': h, 'icon': icon, 'icon_cls': cls,
            'branche': h.get_branche_display(),
            'offene': offene.get(h.id, 0),
        })

    # Branchen-Chips nur für vorhandene Branchen
    vorhanden = set(Handwerker.objects.values_list('branche', flat=True))
    branche_chips = [('', 'Alle')] + [(k, v) for k, v in Handwerker.BRANCHEN_CHOICES if k in vorhanden]

    return render(request, 'fw/dienstleister.html', {
        **basis, 'nav': 'dienstleister', 'rows': rows,
        'branche_filter': branche_filter, 'branche_chips': branche_chips, 'q': q,
        'anzahl': len(rows),
        'anzahl_branchen': len(vorhanden),
    })


# ============================================================
# ETAPPE D: ASSETS (Geräte / Anlagen mit Garantie)
# ============================================================

from datetime import timedelta as _timedelta

ASSET_ICON = {
    'geschirrspueler': 'fa-sink', 'waschmaschine': 'fa-soap', 'tumbler': 'fa-wind',
    'backofen': 'fa-fire-burner', 'kuehlschrank': 'fa-snowflake', 'dampfabzug': 'fa-fan',
    'heizung': 'fa-temperature-half', 'boiler': 'fa-water', 'lift': 'fa-elevator',
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_assets(request):
    from portfolio.models import Geraet
    heute = timezone.now().date()
    grenze = heute + _timedelta(days=90)
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (Geraet.objects.select_related('liegenschaft', 'einheit__liegenschaft')
          .order_by('garantie_bis'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(einheit__liegenschaft=aktive_lg))

    g_filter = request.GET.get('garantie', '')
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(kategorie__icontains=q) | Q(marke__icontains=q) | Q(modell__icontains=q)
                       | Q(sonstiges_bezeichnung__icontains=q))

    rows = []
    n_aktiv = n_bald = n_abgelaufen = 0
    for g in qs:
        gb = g.garantie_bis
        if gb is None:
            g_status, g_cls, g_key = 'keine Angabe', 'bg-slate-100 text-slate-400', 'ohne'
        elif gb < heute:
            g_status, g_cls, g_key = 'abgelaufen', 'bg-slate-100 text-slate-500', 'abgelaufen'
            n_abgelaufen += 1
        elif gb < grenze:
            g_status, g_cls, g_key = 'läuft bald ab', 'bg-amber-50 text-amber-700', 'bald'
            n_bald += 1
        else:
            g_status, g_cls, g_key = 'aktiv', 'bg-emerald-50 text-emerald-700', 'aktiv'
            n_aktiv += 1
        # nach Filter erst NACH Zählung aussortieren (KPI zeigt Gesamtbild)
        if g_filter and g_filter != g_key:
            continue
        lg = g.liegenschaft or (g.einheit.liegenschaft if g.einheit_id else None)
        standort = '—'
        if g.einheit_id:
            standort = f"{g.einheit.liegenschaft.strasse} · {g.einheit.bezeichnung}"
        elif lg:
            standort = f"{lg.strasse} · Allgemein"
        name = g.kategorie if g.kategorie != 'sonstiges' else (g.sonstiges_bezeichnung or 'Gerät')
        rows.append({
            'g': g, 'name': name, 'standort': standort,
            'icon': ASSET_ICON.get(g.kategorie, 'fa-plug'),
            'g_status': g_status, 'g_cls': g_cls,
            'lg_id': g.einheit.liegenschaft_id if g.einheit_id else g.liegenschaft_id,
            'einheit_id': g.einheit_id,
        })

    chips = [('', 'Alle'), ('aktiv', 'Garantie aktiv'), ('bald', 'Läuft bald ab'),
             ('abgelaufen', 'Abgelaufen'), ('ohne', 'Ohne Garantie')]
    return render(request, 'fw/assets.html', {
        **basis, 'nav': 'assets', 'rows': rows,
        'g_filter': g_filter, 'garantie_chips': chips, 'q': q,
        'anzahl': len(rows), 'n_aktiv': n_aktiv, 'n_bald': n_bald, 'n_abgelaufen': n_abgelaufen,
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        'einheiten': Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'),
    })


# ============================================================
# ANLAGEN & ABSCHLUSS (AfA, Erneuerungsfonds, Periodensperre)
# ============================================================

@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_anlagen(request):
    """Anlagenbuchhaltung (lineare AfA), Erneuerungsfonds und Periodensperre."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Anlage, Erneuerungsfonds
    from crm.models import Verwaltung
    from core.services.automation import run_abschreibungen, run_erneuerungsfonds_einlage
    from core.auth import log_aktion
    basis = _global_filter(request)
    heute = timezone.localdate()

    def _dec(x):
        try:
            return Decimal(str(x).replace(',', '.').strip() or '0')
        except Exception:
            return Decimal('0.00')

    if request.method == 'POST':
        aktion = request.POST.get('aktion')
        if aktion == 'anlage_neu':
            lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id')).first()
            try:
                adatum = date.fromisoformat(request.POST.get('anschaffungsdatum'))
            except Exception:
                adatum = heute
            if lg and request.POST.get('bezeichnung', '').strip():
                Anlage.objects.create(
                    liegenschaft=lg, bezeichnung=request.POST['bezeichnung'].strip(),
                    anschaffungswert=_dec(request.POST.get('anschaffungswert')),
                    anschaffungsdatum=adatum,
                    nutzungsdauer_jahre=int(request.POST.get('nutzungsdauer_jahre') or 10),
                    restwert=_dec(request.POST.get('restwert')))
                messages.success(request, "✅ Anlage erfasst.")
            else:
                messages.error(request, "Bezeichnung und Liegenschaft sind Pflicht.")
        elif aktion == 'afa_lauf':
            jahr = int(request.POST.get('jahr') or heute.year)
            n, summe = run_abschreibungen(jahr, user=request.user)
            log_aktion(request, "AfA-Lauf", str(jahr), f"{n} Abschreibungen, CHF {summe}")
            messages.success(request, f"✅ AfA-Lauf {jahr}: {n} Abschreibung(en) gebucht (CHF {summe})." if n
                             else f"AfA-Lauf {jahr}: nichts zu buchen (bereits erledigt oder keine Anlagen).")
        elif aktion == 'fonds_set':
            lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id')).first()
            if lg:
                f, _ = Erneuerungsfonds.objects.get_or_create(liegenschaft=lg)
                f.jaehrliche_einlage = _dec(request.POST.get('jaehrliche_einlage'))
                if request.POST.get('bestand') not in (None, ''):
                    f.bestand = _dec(request.POST.get('bestand'))
                f.save()
                messages.success(request, f"✅ Erneuerungsfonds {lg.strasse} gespeichert.")
        elif aktion == 'fonds_lauf':
            jahr = int(request.POST.get('jahr') or heute.year)
            n, summe = run_erneuerungsfonds_einlage(jahr, user=request.user)
            log_aktion(request, "Erneuerungsfonds-Einlage", str(jahr), f"{n} Einlagen, CHF {summe}")
            messages.success(request, f"✅ Erneuerungsfonds-Einlage {jahr}: {n} Buchung(en) (CHF {summe})." if n
                             else f"Erneuerungsfonds {jahr}: nichts zu buchen.")
        elif aktion == 'sperre_set':
            vw = Verwaltung.objects.first()
            if vw:
                try:
                    vw.buchung_gesperrt_bis = date.fromisoformat(request.POST.get('gesperrt_bis')) if request.POST.get('gesperrt_bis') else None
                except Exception:
                    vw.buchung_gesperrt_bis = None
                vw.save(update_fields=['buchung_gesperrt_bis'])
                log_aktion(request, "Periodensperre gesetzt", str(vw.buchung_gesperrt_bis or '—'), '')
                messages.success(request, "✅ Periodensperre aktualisiert.")
        return redirect('/neu/anlagen/')

    anlagen = list(Anlage.objects.select_related('liegenschaft').all())
    fonds = list(Erneuerungsfonds.objects.select_related('liegenschaft').all())
    vw = Verwaltung.objects.first()
    return render(request, 'fw/anlagen.html', {
        **basis, 'nav': 'anlagen', 'anlagen': anlagen, 'fonds': fonds,
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        'gesperrt_bis': vw.buchung_gesperrt_bis if vw else None,
        'jahr_default': heute.year - 1,
    })


# ============================================================
# ETAPPE D: BUCHHALTUNG (Erfolgsrechnung + Journal)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_buchhaltung(request):
    from finance.models import Buchung, Buchungskonto
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.now().date()

    # --- Jahresfilter (Jahresabschluss) ---
    jahr_param = request.GET.get('jahr', str(heute.year))
    qs = Buchung.objects.all()
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    if jahr_param and jahr_param != 'alle':
        try:
            jahr = int(jahr_param)
            qs = qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
        except ValueError:
            jahr = heute.year
    else:
        jahr = 'alle'

    # --- ZWEI SICHTEN (korrekte Rechnungslegung) ---
    # Erfolgsrechnung = NUR die Periode (Ertrags-/Aufwandskonten werden jährlich
    #   abgeschlossen → year-scoped qs).
    # Bilanz = KUMULATIV bis Jahresende (Bilanzkonten tragen Eröffnungssalden über;
    #   ohne Kumulation wäre die Jahresbilanz falsch). Das kumulierte Jahres-/
    #   Vortragsergebnis fliesst ins Eigenkapital, damit die Bilanz aufgeht.
    konten = Buchungskonto.objects.all()
    bilanz_qs = Buchung.objects.all()
    if aktive_lg:
        bilanz_qs = bilanz_qs.filter(liegenschaft=aktive_lg)
    if jahr != 'alle':
        bilanz_qs = bilanz_qs.filter(datum__lte=date(jahr, 12, 31))

    ertraege, aufwaende = [], []
    aktiven, passiven = [], []
    total_ertrag = total_aufwand = Decimal('0.00')
    total_aktiven = total_passiven = Decimal('0.00')
    kum_erfolg = Decimal('0.00')   # kumuliertes Ergebnis bis Jahresende (Eigenkapital)
    for k in konten:
        if k.typ == 'ertrag':
            soll = qs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            haben = qs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            saldo = haben - soll
            if saldo:
                ertraege.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_ertrag += saldo
        elif k.typ == 'aufwand':
            soll = qs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            haben = qs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            saldo = soll - haben
            if saldo:
                aufwaende.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_aufwand += saldo
        else:  # bilanz — kumulativ bis Jahresende
            soll = bilanz_qs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            haben = bilanz_qs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            saldo = soll - haben  # Sollsaldo: >0 Aktivum, <0 Passivum
            if saldo == 0:
                continue
            if saldo > 0:
                aktiven.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_aktiven += saldo
            else:
                passiven.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': -saldo})
                total_passiven += -saldo
    # Kumuliertes Ergebnis (alle Erfolgskonten bis Jahresende) → Eigenkapital-Zeile
    for k in konten:
        if k.typ == 'ertrag':
            s = bilanz_qs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            h = bilanz_qs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            kum_erfolg += (h - s)
        elif k.typ == 'aufwand':
            s = bilanz_qs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            h = bilanz_qs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            kum_erfolg -= (s - h)
    for lst in (ertraege, aufwaende, aktiven, passiven):
        lst.sort(key=lambda x: x['nummer'])
    erfolg = total_ertrag - total_aufwand          # Ergebnis der Periode (Erfolgsrechnung)
    # Bilanz-Ausgleich: kumuliertes Ergebnis (Vortrag + laufendes Jahr) ins Eigenkapital
    passiven_mit_erfolg = total_passiven + kum_erfolg
    bilanz_differenz = total_aktiven - passiven_mit_erfolg
    erfolg_vortrag = kum_erfolg - erfolg           # Ergebnisvortrag aus Vorjahren

    # --- BUCHUNGSJOURNAL (letzte 60) ---
    journal = (qs.select_related('soll_konto', 'haben_konto', 'liegenschaft')
               .order_by('-datum', '-id')[:60])

    tab_liste = [
        ('erfolg', 'Erfolgsrechnung', None),
        ('bilanz', 'Bilanz', None),
        ('journal', 'Journal', journal.count() or None),
    ]
    return render(request, 'fw/buchhaltung.html', {
        **basis, 'nav': 'buchhaltung',
        'ertraege': ertraege, 'aufwaende': aufwaende,
        'total_ertrag': total_ertrag, 'total_aufwand': total_aufwand, 'erfolg': erfolg,
        'aktiven': aktiven, 'passiven': passiven,
        'total_aktiven': total_aktiven, 'total_passiven': total_passiven,
        'passiven_mit_erfolg': passiven_mit_erfolg, 'bilanz_differenz': bilanz_differenz,
        'kum_erfolg': kum_erfolg, 'erfolg_vortrag': erfolg_vortrag,
        'journal': journal,
        'tab_liste': tab_liste,
        'jahr': jahr, 'jahre': list(range(heute.year, heute.year - 5, -1)),
        'alle_konten': Buchungskonto.objects.all().order_by('nummer'),
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kontoblatt(request, nummer):
    """Kontoauszug/Kontoblatt eines Kontos: alle Buchungen mit laufendem Saldo.
    Bilanzkonten kumulativ (mit Eröffnungssaldo aus Vorjahren)."""
    from finance.models import Buchung, Buchungskonto
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.now().date()
    konto = get_object_or_404(Buchungskonto, nummer=nummer)
    jahr_param = request.GET.get('jahr', str(heute.year))
    try:
        jahr = int(jahr_param)
    except ValueError:
        jahr = None

    alle = Buchung.objects.filter(Q(soll_konto=konto) | Q(haben_konto=konto))
    if aktive_lg:
        alle = alle.filter(liegenschaft=aktive_lg)
    alle = alle.select_related('soll_konto', 'haben_konto', 'liegenschaft').order_by('datum', 'id')

    ist_bilanz = konto.typ == 'bilanz'
    # Eröffnungssaldo: bei Bilanzkonten kumulativ aus Vorjahren, bei Erfolg 0.
    eroeffnung = Decimal('0.00')
    if jahr and ist_bilanz:
        vor = alle.filter(datum__lt=date(jahr, 1, 1))
        s = vor.filter(soll_konto=konto).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        h = vor.filter(haben_konto=konto).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        eroeffnung = s - h
    periode = alle.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31)) if jahr else alle

    zeilen = []
    saldo = eroeffnung
    for b in periode:
        ist_soll = b.soll_konto_id == konto.id
        betrag = b.betrag if ist_soll else -b.betrag
        saldo += betrag
        gegen = b.haben_konto if ist_soll else b.soll_konto
        zeilen.append({'b': b, 'soll': b.betrag if ist_soll else None,
                       'haben': b.betrag if not ist_soll else None,
                       'gegenkonto': gegen, 'saldo': saldo})
    return render(request, 'fw/kontoblatt.html', {
        **basis, 'nav': 'buchhaltung', 'konto': konto, 'zeilen': zeilen,
        'eroeffnung': eroeffnung, 'endsaldo': saldo, 'ist_bilanz': ist_bilanz,
        'jahr': jahr or 'alle', 'jahre': list(range(heute.year, heute.year - 5, -1)),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_buchhaltung_export(request):
    """Exportiert das Buchungsjournal des Jahres als CSV (Treuhänder-Handover)."""
    import csv
    from django.http import HttpResponse
    from finance.models import Buchung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.now().date()
    try:
        jahr = int(request.GET.get('jahr', str(heute.year)))
    except ValueError:
        jahr = heute.year
    qs = Buchung.objects.all()
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    qs = qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
    qs = qs.select_related('soll_konto', 'haben_konto', 'liegenschaft').order_by('datum', 'id')

    resp = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    resp['Content-Disposition'] = f'attachment; filename="Journal_{jahr}.csv"'
    resp.write('﻿')  # BOM für Excel
    w = csv.writer(resp, delimiter=';')
    w.writerow(['Beleg-Nr', 'Datum', 'Belegtext', 'Soll-Konto', 'Haben-Konto', 'Betrag CHF', 'Liegenschaft', 'Storno'])
    for b in qs:
        w.writerow([
            getattr(b, 'beleg_nr', '') or b.id,
            b.datum.strftime('%d.%m.%Y'), b.beleg_text,
            f"{b.soll_konto.nummer} {b.soll_konto.bezeichnung}",
            f"{b.haben_konto.nummer} {b.haben_konto.bezeichnung}",
            f"{b.betrag:.2f}",
            b.liegenschaft.strasse if b.liegenschaft else '',
            'ja' if b.ist_storno else '',
        ])
    return resp


# ============================================================
# EIGENTÜMER-/MANDATSABRECHNUNG
# ============================================================

def _mandat_abrechnung_daten(mandant, jahr):
    """Erträge/Aufwände je Liegenschaft des Mandanten für das Geschäftsjahr.
    Gibt (zeilen, totals) zurück — Basis für Anzeige und PDF."""
    from finance.models import Buchung, Buchungskonto
    import calendar as _cal
    von, bis = date(jahr, 1, 1), date(jahr, 12, 31)
    liegenschaften = Liegenschaft.objects.filter(mandant=mandant).order_by('strasse')
    ertrag_konten = list(Buchungskonto.objects.filter(typ='ertrag'))
    aufwand_konten = list(Buchungskonto.objects.filter(typ='aufwand'))

    zeilen = []
    sum_ertrag = sum_aufwand = Decimal('0.00')
    for lg in liegenschaften:
        bqs = Buchung.objects.filter(liegenschaft=lg, datum__gte=von, datum__lte=bis)
        ertrag = Decimal('0.00')
        for k in ertrag_konten:
            s = bqs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            h = bqs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            ertrag += (h - s)
        aufwand = Decimal('0.00')
        for k in aufwand_konten:
            s = bqs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            h = bqs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            aufwand += (s - h)
        saldo = ertrag - aufwand
        zeilen.append({'lg': lg, 'ertrag': ertrag, 'aufwand': aufwand, 'saldo': saldo})
        sum_ertrag += ertrag
        sum_aufwand += aufwand
    totals = {'ertrag': sum_ertrag, 'aufwand': sum_aufwand, 'saldo': sum_ertrag - sum_aufwand}
    return zeilen, totals, von, bis


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_mandat_abrechnung(request, pk):
    from crm.models import Mandant
    md = get_object_or_404(Mandant, id=pk)
    basis = _global_filter(request)
    heute = timezone.now().date()
    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year

    if request.GET.get('pdf') == '1':
        from crm.models import Verwaltung
        from core.services.mandat_abrechnung import generate_mandat_abrechnung_pdf
        from django.http import HttpResponse
        zeilen, totals, von, bis = _mandat_abrechnung_daten(md, jahr)
        pdf = generate_mandat_abrechnung_pdf(md, jahr, zeilen, totals, von, bis, Verwaltung.objects.first())
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Mandatsabrechnung_{md.firma_oder_name}_{jahr}.pdf"'
        return resp

    zeilen, totals, von, bis = _mandat_abrechnung_daten(md, jahr)
    return render(request, 'fw/mandat_abrechnung.html', {
        **basis, 'nav': 'mandate', 'md': md, 'jahr': jahr, 'von': von, 'bis': bis,
        'zeilen': zeilen, 'totals': totals,
        'jahre': list(range(heute.year, heute.year - 5, -1)),
    })


# ============================================================
# ETAPPE D: SOLLSTELLUNG MIETE (monatlicher Mietenlauf)
# ============================================================

import calendar as _calendar


def _sollstellung_kontext(request):
    """Vorschau: aktive Verträge + Soll je Vertrag für den gewählten Monat."""
    heute = timezone.now().date()
    try:
        jahr = int(request.GET.get('jahr') or heute.year)
        monat = int(request.GET.get('monat') or heute.month)
    except ValueError:
        jahr, monat = heute.year, heute.month
    monat = min(max(monat, 1), 12)

    start_date = date(jahr, monat, 1)
    _, last_day = _calendar.monthrange(jahr, monat)
    end_date = date(jahr, monat, last_day)
    titel = f"Miete & NK {monat:02d}/{jahr}"

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    vertraege = (Mietvertrag.objects.filter(status='aktiv', beginn__lte=end_date)
                 .exclude(ende__lt=start_date)
                 .select_related('mieter', 'einheit__liegenschaft'))
    if aktive_lg:
        vertraege = vertraege.filter(einheit__liegenschaft=aktive_lg)

    rows = []
    total_soll = Decimal('0.00')
    n_offen = n_gestellt = 0
    for v in vertraege:
        v_start = max(start_date, v.beginn)
        v_ende = min(end_date, v.ende) if v.ende else end_date
        tage_aktiv = (v_ende - v_start).days + 1
        faktor = Decimal(tage_aktiv) / Decimal(last_day)
        netto = round((v.netto_mietzins or Decimal('0')) * faktor, 2)
        nk = round((v.nebenkosten or Decimal('0')) * faktor, 2)
        total = netto + nk
        if total <= 0:
            continue
        gestellt = DebitorenRechnung.objects.filter(vertrag=v, titel=titel).exclude(status='storniert').exists()
        if gestellt:
            n_gestellt += 1
        else:
            n_offen += 1
            total_soll += total
        rows.append({
            'v': v, 'mieter': v.mieter.display_name,
            'objekt': f"{v.einheit.liegenschaft.strasse} · {v.einheit.bezeichnung}",
            'netto': netto, 'nk': nk, 'total': total,
            'prorata': tage_aktiv < last_day, 'tage': tage_aktiv, 'tage_monat': last_day,
            'gestellt': gestellt,
        })

    monate = [(m, date(2000, m, 1).strftime('%B')) for m in range(1, 13)]
    jahre = list(range(heute.year - 2, heute.year + 2))
    return {
        **basis, 'nav': 'sollstellung', 'rows': rows,
        'jahr': jahr, 'monat': monat, 'titel': titel,
        'total_soll': total_soll, 'n_offen': n_offen, 'n_gestellt': n_gestellt,
        'monate': monate, 'jahre': jahre,
        'monat_name': date(2000, monat, 1).strftime('%B'),
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_sollstellung(request):
    from django.contrib import messages
    ctx = _sollstellung_kontext(request)
    ctx['meldung'] = list(messages.get_messages(request))
    return render(request, 'fw/sollstellung.html', ctx)


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_sollstellung_run(request):
    """Führt den Mietenlauf für den gewählten Monat aus (idempotent, Pro-Rata,
    Debitoren 1100 an Ertrag 3000 / NK-Akonto 3020) — wie die Finanz-API."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_sollstellung')

    heute = timezone.now().date()
    try:
        jahr = int(request.POST.get('jahr') or heute.year)
        monat = int(request.POST.get('monat') or heute.month)
    except ValueError:
        jahr, monat = heute.year, heute.month

    titel = f"Miete & NK {monat:02d}/{jahr}"
    from core.services.automation import run_sollstellung
    try:
        erstellt = run_sollstellung(jahr, monat, user=request.user)
    except RuntimeError as e:
        messages.error(request, f"{e}")
        return redirect(f'/neu/sollstellung/?jahr={jahr}&monat={monat}')

    log_aktion(request, "Sollstellung ausgeführt", titel, f"{erstellt} Rechnungen erstellt")
    if erstellt:
        messages.success(request, f"✅ Sollstellung {titel}: {erstellt} Rechnung(en) erstellt.")
    else:
        messages.success(request, f"Sollstellung {titel}: alles bereits gestellt — nichts Neues erzeugt.")
    return redirect(f'/neu/sollstellung/?jahr={jahr}&monat={monat}')


# ============================================================
# ETAPPE D: NEBENKOSTEN (HNK-Abrechnungsperioden)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten(request):
    from finance.models import AbrechnungsPeriode
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = AbrechnungsPeriode.objects.select_related('liegenschaft').order_by('-start_datum')
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    status_filter = request.GET.get('status', '')
    rows = []
    n_offen = n_zu = 0
    total_kosten_offen = Decimal('0.00')
    for p in qs:
        kosten = p.total_kosten
        if p.abgeschlossen:
            n_zu += 1
        else:
            n_offen += 1
            total_kosten_offen += kosten
        if status_filter == 'offen' and p.abgeschlossen:
            continue
        if status_filter == 'abgeschlossen' and not p.abgeschlossen:
            continue
        rows.append({
            'p': p, 'kosten': kosten,
            'lg': p.liegenschaft.strasse if p.liegenschaft_id else '—',
            'belege': p.belege.count(),
        })

    chips = [('', 'Alle'), ('offen', 'Offen'), ('abgeschlossen', 'Abgeschlossen')]
    return render(request, 'fw/nebenkosten.html', {
        **basis, 'nav': 'nebenkosten', 'rows': rows,
        'status_filter': status_filter, 'status_chips': chips,
        'n_offen': n_offen, 'n_zu': n_zu, 'total_kosten_offen': total_kosten_offen,
        'anzahl': len(rows),
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_detail(request, pk):
    """Zeigt die Abrechnung — nutzt die EINE kanonische Engine (core.utils.billing),
    identisch zu PDF und Verbuchung (keine divergierenden Berechnungen mehr)."""
    from finance.models import AbrechnungsPeriode, KreditorenRechnung
    from core.utils.billing import berechne_abrechnung
    p = get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), id=pk)
    basis = _global_filter(request)
    lg = p.liegenschaft

    result = berechne_abrechnung(p.id)
    # Kanonische Ausgabe auf die Template-Keys mappen
    abrechnungen = []
    total_kosten_verteilt = Decimal('0.00')
    total_akonto = Decimal('0.00')
    for a in result.get('abrechnungen', []):
        kosten = Decimal(str(a.get('kosten_anteil', 0)))
        akonto = Decimal(str(a.get('akonto', 0)))
        total_kosten_verteilt += kosten
        total_akonto += akonto
        abrechnungen.append({
            'v': None, 'vertrag_id': a.get('vertrag_id'),
            'mieter': a.get('name', ''), 'einheit': a.get('einheit', ''),
            'flaeche': '', 'tage': f"{a.get('von','')}–{a.get('bis','')}" if a.get('von') != '-' else 'Leerstand',
            'kosten': kosten, 'akonto': akonto, 'saldo': Decimal(str(a.get('saldo', 0))),
            'nachzahlung': a.get('nachzahlung', False), 'info': a.get('info', ''),
        })

    # Akonto-Anpassungs-Vorschlag: effektive Jahres-NK vs. aktuelle Akonto/Monat.
    # Weicht der monatliche Akonto ≥ 10 % (mind. CHF 10) vom effektiven Bedarf ab,
    # wird eine neue runde Akonto-Höhe vorgeschlagen.
    monate = 1
    if p.start_datum and p.ende_datum:
        monate = max(1, round((p.ende_datum - p.start_datum).days / 30.44))
    akonto_vorschlaege = []
    for a in abrechnungen:
        vid = a['vertrag_id']
        if not vid:
            continue
        kosten_monat = (a['kosten'] / monate) if monate else a['kosten']
        akonto_monat = (a['akonto'] / monate) if monate else a['akonto']
        # auf CHF 5 runden
        empfohlen = (Decimal(round(float(kosten_monat) / 5.0)) * 5).quantize(Decimal('1'))
        diff = empfohlen - akonto_monat
        schwelle = max(Decimal('10'), (akonto_monat * Decimal('0.10')))
        if abs(diff) >= schwelle and empfohlen > 0:
            akonto_vorschlaege.append({
                'vertrag_id': vid, 'mieter': a['mieter'], 'einheit': a['einheit'],
                'aktuell': akonto_monat.quantize(Decimal('1')),
                'empfohlen': empfohlen,
                'richtung': 'erhöhen' if diff > 0 else 'senken',
                'diff': abs(diff).quantize(Decimal('1')),
            })

    belege = p.belege.all().order_by('-datum')
    kosten_rechnungen = (KreditorenRechnung.objects.filter(
        liegenschaft=lg, is_hnk_relevant=True,
        datum__gte=p.start_datum, datum__lte=p.ende_datum).exclude(status='storniert')) if lg else []

    tab_liste = [
        ('abrechnung', 'Mieter-Abrechnung', len(abrechnungen) or None),
        ('belege', 'Belege', (len(result.get('belege_details', [])) or belege.count()) or None),
    ]
    return render(request, 'fw/nebenkosten_detail.html', {
        **basis, 'nav': 'nebenkosten', 'p': p,
        'total_kosten': result.get('total_kosten', Decimal('0.00')),
        'total_akonto': total_akonto,
        'saldo_total': total_kosten_verteilt - total_akonto,
        'abrechnungen': abrechnungen,
        'belege_details': result.get('belege_details', []),
        'belege': belege, 'kreditoren': kosten_rechnungen,
        'akonto_vorschlaege': akonto_vorschlaege,
        'hkvo_angewendet': result.get('hkvo_angewendet', False),
        'hkvo_aktiv': getattr(lg, 'hkvo_aktiv', False) if lg else False,
        'differenz': result.get('differenz', Decimal('0.00')),
        'tab_liste': tab_liste,
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_nebenkosten_verbuchen(request, pk):
    """Verbucht die Abrechnung mit den GLEICHEN Zahlen wie Anzeige/PDF (kanonische Engine)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import AbrechnungsPeriode, Buchungskonto, Buchung
    from core.utils.billing import berechne_abrechnung
    from core.auth import log_aktion
    p = get_object_or_404(AbrechnungsPeriode, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/nebenkosten/{p.id}/')
    if p.abgeschlossen:
        messages.error(request, "Diese Periode ist bereits abgeschlossen und verbucht.")
        return redirect(f'/neu/nebenkosten/{p.id}/')

    result = berechne_abrechnung(p.id)
    from finance.booking import buche, konto as _konto
    konto_nk = _konto("3020")

    heute = timezone.now().date()
    n_nach = n_gut = 0
    with transaction.atomic():
        for a in result.get('abrechnungen', []):
            vid = a.get('vertrag_id')
            saldo = Decimal(str(a.get('saldo', 0)))
            if not vid or a.get('typ') == 'leerstand' or abs(saldo) < Decimal('0.01'):
                continue
            v = Mietvertrag.objects.filter(id=vid).select_related('einheit__liegenschaft').first()
            if not v:
                continue
            if saldo > 0:  # Nachzahlung -> Debitor
                rech = DebitorenRechnung.objects.create(
                    vertrag=v, liegenschaft=v.einheit.liegenschaft, einheit=v.einheit,
                    titel=f"NK-Abrechnung Nachzahlung - {p.bezeichnung}",
                    beschreibung=f"Periode {p.start_datum:%d.%m.%Y}–{p.ende_datum:%d.%m.%Y}",
                    betrag=saldo, faellig_am=heute + timezone.timedelta(days=30), konto_haben=konto_nk)
                buche("1100", "3020", saldo, f"NK-Nachzahlung {v.mieter} - {p.bezeichnung}",
                      datum=heute, liegenschaft=v.einheit.liegenschaft, debitor=rech, user=request.user)
                n_nach += 1
            else:  # Guthaben -> Gutschrift
                buche("3020", "1100", abs(saldo), f"NK-Gutschrift {v.mieter} - {p.bezeichnung}",
                      datum=heute, liegenschaft=v.einheit.liegenschaft, user=request.user)
                n_gut += 1
        p.abgeschlossen = True
        p.save(update_fields=['abgeschlossen'])
    log_aktion(request, "NK-Abrechnung verbucht", p.bezeichnung, f"{n_nach} Nachzahlungen, {n_gut} Gutschriften")
    messages.success(request, f"✅ Abrechnung verbucht: {n_nach} Nachzahlung(en), {n_gut} Gutschrift(en).")
    return redirect(f'/neu/nebenkosten/{p.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_nebenkosten_versand(request, pk):
    """Erzeugt je Mieter eine Nebenkosten-Abrechnung (PDF), legt sie in dessen
    Akte (→ Mieterportal) und liefert alle zusammen als Sammel-PDF."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from finance.models import AbrechnungsPeriode
    from crm.models import Verwaltung
    from core.utils.billing import berechne_abrechnung
    from core.services.nk_abrechnung import generate_nk_pdf_einzeln, generate_nk_pdf_sammel
    from core.services.ablage import ablegen
    from core.auth import log_aktion

    p = get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/nebenkosten/{p.id}/')

    result = berechne_abrechnung(p.id)
    if result.get('error'):
        messages.error(request, result['error'])
        return redirect(f'/neu/nebenkosten/{p.id}/')

    vw = Verwaltung.objects.first()
    lg = p.liegenschaft
    periode_str = f"{p.bezeichnung} ({p.start_datum:%d.%m.%Y}–{p.ende_datum:%d.%m.%Y})"
    positionen = result.get('belege_details', [])
    total_kosten = result.get('total_kosten', Decimal('0.00'))

    kontexte = []
    abgelegt = 0
    for a in result.get('abrechnungen', []):
        vid = a.get('vertrag_id')
        if not vid or a.get('typ') == 'leerstand':
            continue
        v = Mietvertrag.objects.filter(id=vid).select_related('mieter', 'mitmieter', 'einheit__liegenschaft').first()
        if not v:
            continue
        m = v.mieter
        namen = m.display_name
        zweit = (v.mitmieter.display_name if v.mitmieter_id else (v.mitmieter_name or '')).strip()
        if zweit:
            namen += f" & {zweit}"
        adresse = [namen]
        if m.strasse:
            adresse.append(m.strasse)
        if m.plz or m.ort:
            adresse.append(f"{m.plz or ''} {m.ort or ''}".strip())
        k = {
            'verwaltung': vw, 'periode': periode_str,
            'objekt': f"{lg.strasse}, {lg.plz} {lg.ort} · {v.einheit.bezeichnung}" if lg and v.einheit_id else (v.einheit.bezeichnung if v.einheit_id else ''),
            'adresse': adresse, 'positionen': positionen, 'total_kosten': total_kosten,
            'kosten_anteil': a.get('kosten_anteil', 0), 'akonto': a.get('akonto', 0),
            'saldo': a.get('saldo', 0), 'nachzahlung': a.get('nachzahlung', False),
        }
        kontexte.append(k)
        # Einzel-PDF in die Akte des Mieters (erscheint im Portal)
        try:
            einzel = generate_nk_pdf_einzeln(k)
            if ablegen(einzel, f"Nebenkostenabrechnung {p.bezeichnung}", kategorie='korrespondenz',
                       vertrag=v, mieter=m, dedup=True):
                abgelegt += 1
        except Exception:
            pass

    if not kontexte:
        messages.error(request, "Keine abzurechnenden Mieter in dieser Periode gefunden.")
        return redirect(f'/neu/nebenkosten/{p.id}/')

    log_aktion(request, "NK-Abrechnungen versendet", p.bezeichnung, f"{abgelegt} abgelegt")
    sammel = generate_nk_pdf_sammel(kontexte)
    resp = HttpResponse(sammel, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="Nebenkostenabrechnungen_{p.bezeichnung}.pdf"'
    return resp


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_akonto_anpassen(request, pk):
    """Übernimmt die vorgeschlagene neue Akonto-Höhe in die gewählten Verträge
    (nach der NK-Abrechnung). Setzt Vertrag.nebenkosten + Einheit.nebenkosten_aktuell."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import AbrechnungsPeriode
    from core.auth import log_aktion
    p = get_object_or_404(AbrechnungsPeriode, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/nebenkosten/{p.id}/')
    angepasst = 0
    for vid in request.POST.getlist('vertrag_id'):
        neu = (request.POST.get(f'akonto_{vid}') or '').strip().replace(',', '.')
        try:
            betrag = Decimal(neu)
        except Exception:
            continue
        if betrag <= 0:
            continue
        v = Mietvertrag.objects.filter(id=vid).select_related('einheit').first()
        if not v:
            continue
        v.nebenkosten = betrag
        v.save(update_fields=['nebenkosten'])
        if v.einheit_id:
            v.einheit.nebenkosten_aktuell = betrag
            v.einheit.save(update_fields=['nebenkosten_aktuell'])
        angepasst += 1
    log_aktion(request, "Akonto angepasst", p.bezeichnung, f"{angepasst} Verträge")
    messages.success(request,
                     f"✅ Akonto bei {angepasst} Vertrag/Verträgen angepasst." if angepasst
                     else "Keine Akonto-Anpassung übernommen.")
    return redirect(f'/neu/nebenkosten/{p.id}/')


# ============================================================
# ETAPPE D: MIETZINS (Anpassungspotenzial + amtliches Formular)
# ============================================================

POTENZIAL_PILL = {
    'increase': ('Erhöhung möglich', 'bg-emerald-50 text-emerald-700', 'fa-arrow-trend-up'),
    'decrease': ('Senkungsanspruch', 'bg-rose-50 text-rose-600', 'fa-arrow-trend-down'),
    'neutral':  ('Aktuell', 'bg-slate-100 text-slate-500', 'fa-equals'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mietzins(request):
    from crm.models import Verwaltung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    vw = Verwaltung.objects.first()
    curr_zins = vw.aktueller_referenzzinssatz if vw else None
    curr_lik = vw.aktueller_lik_punkte if vw else None

    qs = (Mietvertrag.objects.filter(status='aktiv')
          .select_related('mieter', 'einheit__liegenschaft')
          .prefetch_related('anpassungen').order_by('einheit__liegenschaft__strasse'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    pot_filter = request.GET.get('potenzial', '')

    rows = []
    n_inc = n_dec = 0
    for v in qs:
        pot = v.mietzinspotenzial
        if pot == 'increase':
            n_inc += 1
        elif pot == 'decrease':
            n_dec += 1
        if pot_filter and pot_filter != pot:
            continue
        label, cls, icon = POTENZIAL_PILL.get(pot, POTENZIAL_PILL['neutral'])
        letzte = v.anpassungen.all()
        letzte_anpassung = max((a.wirksam_ab for a in letzte), default=None)
        rows.append({
            'v': v, 'mieter': v.mieter.display_name,
            'objekt': f"{v.einheit.liegenschaft.strasse} · {v.einheit.bezeichnung}",
            'netto': v.netto_mietzins or Decimal('0'),
            'basis_zins': v.basis_referenzzinssatz, 'basis_lik': v.basis_lik_punkte,
            'pot': pot, 'pot_label': label, 'pot_cls': cls, 'pot_icon': icon,
            'letzte_anpassung': letzte_anpassung,
            'anpassungen': letzte.count(),
        })

    chips = [('', 'Alle'), ('increase', 'Erhöhung möglich'), ('decrease', 'Senkungsanspruch'), ('neutral', 'Aktuell')]
    return render(request, 'fw/mietzins.html', {
        **basis, 'nav': 'mietzins', 'rows': rows,
        'pot_filter': pot_filter, 'pot_chips': chips,
        'curr_zins': curr_zins, 'curr_lik': curr_lik,
        'n_inc': n_inc, 'n_dec': n_dec, 'anzahl': len(rows),
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_mietzins_anpassung(request, vertrag_id):
    """Amtliches Mietzinsanpassungs-Formular (Art. 269d OR / Art. 19 VMWG) in der /neu/-Shell.
    GET: Berechnungs-Formular · POST action=pdf: Formular als PDF · POST action=speichern:
    Anpassung erfassen (und optional Vertragsbasis fortschreiben)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from rentals.models import MietzinsAnpassung
    from rentals.services import berechne_mietpotenzial, naechster_anpassungstermin
    from core.utils import get_current_ref_zins, get_current_lik
    from core.services.mietzins_formular import generate_amtliches_formular_pdf
    from core.auth import log_aktion

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    vw = Verwaltung.objects.first()
    lg = v.einheit.liegenschaft
    mandant = lg.mandant

    def _dec(x, default='0'):
        try:
            return Decimal(str(x).replace(',', '.').strip())
        except Exception:
            return Decimal(default)

    aktuell_ref = _dec(get_current_ref_zins())
    aktuell_lik = _dec(get_current_lik())
    # Automatischer LIK-Stand (Live-Abruf → BFS-Tabelle) für die Anzeige
    from core.services.lik import aktueller_lik_wert
    _auto_stand, _auto_lik, _auto_basis = aktueller_lik_wert()
    aktuell_lik_stand = _auto_stand or (vw.aktueller_lik_stand if vw else None)
    lik_basis = _auto_basis or (vw.lik_basis if vw else 'Dezember 2020')

    if request.method == 'POST':
        aktion = request.POST.get('aktion', 'pdf')
        # Vertragsbasis (Ref-Zins/LIK, auf denen der Vertrag beruht) — editierbar,
        # damit sie bei Alt-/Importverträgen ergänzt/korrigiert werden kann. Wird
        # auf dem Vertrag gespeichert, bevor das Potenzial gerechnet wird.
        if request.POST.get('basis_zins') not in (None, ''):
            v.basis_referenzzinssatz = _dec(request.POST.get('basis_zins'), str(v.basis_referenzzinssatz or aktuell_ref))
        if request.POST.get('basis_lik') not in (None, ''):
            v.basis_lik_punkte = _dec(request.POST.get('basis_lik'), str(v.basis_lik_punkte or aktuell_lik))
        stand_raw = (request.POST.get('basis_lik_stand') or '').strip()  # 'YYYY-MM'
        if stand_raw:
            try:
                _jy, _jm = stand_raw.split('-')[:2]
                v.basis_lik_stand = date(int(_jy), int(_jm), 1)
            except Exception:
                pass
        v.save(update_fields=['basis_referenzzinssatz', 'basis_lik_punkte', 'basis_lik_stand'])
        neu_netto = _dec(request.POST.get('neu_netto'), str(v.netto_mietzins))
        neu_zins = _dec(request.POST.get('neu_zins'), str(aktuell_ref))
        neu_lik = _dec(request.POST.get('neu_lik'), str(aktuell_lik))
        wirksam_str = request.POST.get('wirksam_ab') or ''
        try:
            wirksam_ab = date.fromisoformat(wirksam_str)
        except Exception:
            wirksam_ab = naechster_anpassungstermin(v, timezone.now().date())
        begruendung = (request.POST.get('begruendung') or '').strip()
        mit_vorbehalt = request.POST.get('mit_vorbehalt') == 'on'
        vorbehalt_text = (request.POST.get('vorbehalt_text') or '').strip()

        pot = berechne_mietpotenzial(v, aktuell_ref, aktuell_lik,
                                     _dec(request.POST.get('kosten_pct'), '0')) or {}
        daten = {
            'alt_netto': v.netto_mietzins, 'neu_netto': neu_netto,
            'nebenkosten': v.nebenkosten,
            'alt_zins': v.basis_referenzzinssatz, 'neu_zins': neu_zins,
            'alt_lik': v.basis_lik_punkte, 'neu_lik': neu_lik,
            'lik_basis': lik_basis,
            'alt_lik_stand': v.basis_lik_stand, 'neu_lik_stand': aktuell_lik_stand,
            'zins_pct': None, 'lik_pct': None,
            'kosten_pct': request.POST.get('kosten_pct') or None,
            'total_pct': pot.get('delta_prozent'),
            'wirksam_ab': wirksam_ab, 'begruendung': begruendung,
            'schlichtungsbehoerde': request.POST.get('schlichtungsbehoerde') or '',
            'mit_vorbehalt': mit_vorbehalt, 'vorbehalt_text': vorbehalt_text,
        }

        anp = MietzinsAnpassung.objects.create(
            vertrag=v, wirksam_ab=wirksam_ab,
            alter_netto_mietzins=v.netto_mietzins, neuer_netto_mietzins=neu_netto,
            alter_referenzzinssatz=v.basis_referenzzinssatz, neuer_referenzzinssatz=neu_zins,
            alter_lik_index=v.basis_lik_punkte, neuer_lik_index=neu_lik,
            erhoehung_prozent_total=pot.get('delta_prozent'),
            begruendung=begruendung or 'Anpassung an Referenzzinssatz und Teuerung',
        )
        log_aktion(request, "Mietzinsanpassung erstellt", str(v),
                   f"neu CHF {neu_netto}, wirksam {wirksam_ab}", ziel=v)

        # Anfechtungsfrist-Pendenz bei einer Erhöhung: der Mieter kann die
        # Mietzinserhöhung innert 30 Tagen ab Empfang anfechten (Art. 270b OR).
        if neu_netto > (v.netto_mietzins or Decimal('0')):
            from core.models import Pendenz
            frist = timezone.localdate() + _timedelta(days=30)
            Pendenz.objects.create(
                titel=f"Anfechtungsfrist Mietzinserhöhung läuft ab – {v.mieter.display_name}",
                beschreibung=(f"Erhöhung auf CHF {neu_netto} (wirksam {wirksam_ab:%d.%m.%Y}). Der Mieter kann "
                              "sie innert 30 Tagen ab Empfang des amtlichen Formulars bei der "
                              "Schlichtungsbehörde anfechten (Art. 270b OR)."),
                kategorie='frist', faellig_am=frist, vertrag=v,
                liegenschaft=lg,
                erstellt_von=request.user if request.user.is_authenticated else None,
            )

        if aktion == 'speichern':
            messages.success(request, f"✅ Mietzinsanpassung erfasst — neu CHF {neu_netto} ab {wirksam_ab.strftime('%d.%m.%Y')}.")
            return redirect(f'/neu/vertraege/{v.id}/')

        # Kanton mit eingebautem Original (SO/ZH/BE/…) → Original ausfüllen;
        # sonst kantonsabhängige Nachbildung mit korrektem Schlichtungsblock.
        from core.services.formular_fill import fill_mietzins
        pdf = None
        if request.POST.get('formular') != 'generisch':
            pdf = fill_mietzins(v, daten, verwaltung=vw)
        if pdf is None:
            from core.services.amtliche_formulare_so import mietzins_so_pdf
            pdf = mietzins_so_pdf(v, daten, verwaltung=vw)
        from core.services.ablage import ablegen
        ablegen(pdf, f"Mietzinsanpassung wirksam {wirksam_ab:%d.%m.%Y}",
                kategorie='vertrag', vertrag=v, dedup=True)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Mietzinsanpassung_{v.mieter.nachname}.pdf"'
        return resp

    # --- GET: Vorschlag berechnen ---
    pot = berechne_mietpotenzial(v, aktuell_ref, aktuell_lik, Decimal('0.00')) or {}
    vorschlag_netto = pot.get('neu_chf', v.netto_mietzins)
    naechster_termin = naechster_anpassungstermin(v, timezone.now().date())

    # Basis-Vorbelegung: fehlt sie am Vertrag (Alt-/Importvertrag), aktuelle
    # Marktwerte vorschlagen, damit der Sachbearbeiter sie ergänzen kann.
    basis_zins = v.basis_referenzzinssatz if (v.basis_referenzzinssatz or 0) > 0 else aktuell_ref
    basis_lik = v.basis_lik_punkte if (v.basis_lik_punkte or 0) > 0 else aktuell_lik
    return render(request, 'fw/mietzins_anpassung.html', {
        **basis, 'nav': 'mietzins', 'v': v, 'lg': lg,
        'alt_netto': v.netto_mietzins,
        'alt_zins': basis_zins, 'alt_lik': basis_lik,
        'basis_fehlt': not ((v.basis_referenzzinssatz or 0) > 0 and (v.basis_lik_punkte or 0) > 0),
        'aktuell_ref': aktuell_ref, 'aktuell_lik': aktuell_lik,
        'lik_basis': lik_basis,
        'alt_lik_stand': v.basis_lik_stand, 'aktuell_lik_stand': aktuell_lik_stand,
        'vorschlag_netto': vorschlag_netto, 'naechster_termin': naechster_termin,
        'pot': pot,
    })


# ============================================================
# ETAPPE D: DOKUMENTE (zentrale Ablage aus beiden Quellen)
# ============================================================

DOK_ICON = {
    'vertrag': ('fa-file-contract', 'bg-indigo-50 text-indigo-600'),
    'protokoll': ('fa-clipboard-check', 'bg-emerald-50 text-emerald-600'),
    'korrespondenz': ('fa-envelope', 'bg-sky-50 text-sky-600'),
    'sonstiges': ('fa-file', 'bg-slate-100 text-slate-500'),
}


def _dok_icon(kat):
    return DOK_ICON.get((kat or '').lower(), ('fa-file-lines', 'bg-slate-100 text-slate-500'))


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_dokumente(request):
    from rentals.models import Dokument as RDok
    from portfolio.models import Dokument as PDok
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    kat_filter = (request.GET.get('kat') or '').strip().lower()
    q = (request.GET.get('q') or '').strip()

    eintraege = []

    # 1) Vertrags-/Mieter-Ablage (rentals)
    rqs = RDok.objects.select_related('liegenschaft', 'mieter', 'vertrag', 'einheit').order_by('-datum')
    if aktive_lg:
        rqs = rqs.filter(Q(liegenschaft=aktive_lg) | Q(einheit__liegenschaft=aktive_lg))
    for d in rqs:
        if not d.datei:
            continue
        name = d.bezeichnung or d.titel or 'Dokument'
        kontext = ''
        if d.mieter_id:
            kontext = d.mieter.display_name
        elif d.liegenschaft_id:
            kontext = d.liegenschaft.strasse
        eintraege.append({
            'name': name, 'kat': d.kategorie or 'sonstiges', 'datum': d.datum,
            'url': d.datei.url, 'kontext': kontext, 'quelle': 'Vertragsablage',
        })

    # 2) Objekt-/Liegenschafts-Ablage (portfolio)
    pqs = PDok.objects.select_related('liegenschaft', 'einheit').order_by('-datum')
    if aktive_lg:
        pqs = pqs.filter(Q(liegenschaft=aktive_lg) | Q(einheit__liegenschaft=aktive_lg))
    for d in pqs:
        if not d.datei:
            continue
        kontext = d.liegenschaft.strasse if d.liegenschaft_id else (d.einheit.bezeichnung if d.einheit_id else '')
        eintraege.append({
            'name': d.titel or 'Dokument', 'kat': d.kategorie or 'sonstiges', 'datum': d.datum,
            'url': d.datei.url, 'kontext': kontext, 'quelle': 'Objektablage',
        })

    # Kategorien für Chips (aus vorhandenen)
    vorhanden = sorted({(e['kat'] or 'sonstiges').lower() for e in eintraege})

    # Filter anwenden
    if kat_filter:
        eintraege = [e for e in eintraege if (e['kat'] or 'sonstiges').lower() == kat_filter]
    if q:
        ql = q.lower()
        eintraege = [e for e in eintraege if ql in e['name'].lower() or ql in (e['kontext'] or '').lower()]

    # Icon + Sortierung
    for e in eintraege:
        e['icon'], e['icon_cls'] = _dok_icon(e['kat'])
    eintraege.sort(key=lambda e: e['datum'] or date.min, reverse=True)

    kat_labels = {'vertrag': 'Verträge', 'protokoll': 'Protokolle', 'korrespondenz': 'Korrespondenz',
                  'sonstiges': 'Sonstiges', 'allgemein': 'Allgemein'}
    kat_chips = [('', 'Alle')] + [(k, kat_labels.get(k, k.capitalize())) for k in vorhanden]

    return render(request, 'fw/dokumente.html', {
        **basis, 'nav': 'dokumente', 'eintraege': eintraege,
        'kat_filter': kat_filter, 'kat_chips': kat_chips, 'q': q,
        'anzahl': len(eintraege),
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        'einheiten': Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'),
    })


# ============================================================
# ETAPPE D: KOMMUNIKATION (Mitteilungs-Assistent mit Live-Vorschau)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kommunikation(request):
    from crm.models import Verwaltung, Vorlage
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    vw = Verwaltung.objects.first()
    absender = {
        'firma': vw.firma if vw else 'Meine Verwaltung',
        'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
    }
    logo_url = ''
    if vw and getattr(vw, 'logo', None):
        try:
            logo_url = vw.logo.url
        except Exception:
            logo_url = ''

    vorlagen = [{'id': v.id, 'name': v.name, 'betreff': v.betreff, 'inhalt': v.inhalt,
                 'kategorie': v.get_kategorie_display()} for v in Vorlage.objects.all()]

    # Empfänger = Mieter mit aktivem Vertrag (im Filter-Scope)
    vertraege = (Mietvertrag.objects.filter(status='aktiv')
                 .select_related('mieter', 'einheit__liegenschaft'))
    if aktive_lg:
        vertraege = vertraege.filter(einheit__liegenschaft=aktive_lg)

    empfaenger = []
    gesehen = set()
    for v in vertraege:
        m = v.mieter
        if m.id in gesehen:
            continue
        gesehen.add(m.id)
        lg = v.einheit.liegenschaft
        empfaenger.append({
            'id': m.id, 'name': m.display_name,
            'anrede': m.anrede or '',
            'strasse': m.strasse or lg.strasse,
            'plz': m.plz or lg.plz, 'ort': m.ort or lg.ort,
            'email': m.email or '',
            'objekt': f"{lg.strasse}, {lg.ort} · {v.einheit.bezeichnung}",
        })
    empfaenger.sort(key=lambda e: e['name'])

    return render(request, 'fw/kommunikation.html', {
        **basis, 'nav': 'kommunikation',
        'absender': absender, 'empfaenger': empfaenger,
        'anzahl_empfaenger': len(empfaenger),
        'vorlagen': vorlagen, 'logo_url': logo_url,
    })


# ============================================================
# ETAPPE D: VERTRAGSERSTELLUNG (7-Schritte-Assistent + Live-Vorschau)
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_neu(request):
    from crm.models import Verwaltung, Mieter
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    vw = Verwaltung.objects.first()
    verwaltung = {
        'firma': vw.firma if vw else '', 'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
    }

    # Vorwahl einer bestimmten Einheit (z.B. aus dem Mieterwechsel-Cockpit):
    # dann nur diese Liegenschaft + dieses Objekt anzeigen, keine Auswahl nötig.
    try:
        vorwahl_einheit = int(request.GET.get('einheit') or 0) or None
    except ValueError:
        vorwahl_einheit = None
    vorwahl_e = Einheit.objects.select_related('liegenschaft').filter(id=vorwahl_einheit).first() if vorwahl_einheit else None

    # Belegte Einheiten (aktiver Vertrag inkl. Nebenobjekte) ausschliessen
    belegte = set(Mietvertrag.objects.filter(status='aktiv').values_list('einheit_id', flat=True))
    for nid in Mietvertrag.objects.filter(status='aktiv').values_list('nebenobjekte', flat=True):
        if nid:
            belegte.add(nid)
    # Die vorgewählte Einheit immer zeigen (Nachmieter-Vertrag beginnt nach Auszug,
    # der alte Vertrag kann noch aktiv/gekündigt sein).
    belegte.discard(vorwahl_einheit)

    lg_qs = Liegenschaft.objects.select_related('mandant').prefetch_related('einheiten').order_by('strasse')
    if vorwahl_e:
        lg_qs = lg_qs.filter(id=vorwahl_e.liegenschaft_id)
    elif aktive_lg:
        lg_qs = lg_qs.filter(id=aktive_lg.id)

    liegenschaften = []
    for lg in lg_qs:
        objekte = []
        for e in lg.einheiten.all().order_by('bezeichnung'):
            if e.id in belegte:
                continue
            if vorwahl_e and e.id != vorwahl_einheit:
                continue   # bei Vorwahl nur genau dieses Objekt
            objekte.append({
                'id': e.id, 'bezeichnung': e.bezeichnung,
                'typ': e.get_typ_display(), 'etage': e.etage or '',
                'ewid': e.ewid or '', 'zimmer': float(e.zimmer) if e.zimmer else None,
                'flaeche': float(e.flaeche_m2) if e.flaeche_m2 else None,
                'netto': float(e.nettomiete_aktuell or 0), 'nk': float(e.nebenkosten_aktuell or 0),
                'kaution_monate': e.standard_kautionsmonate or 3,
                'vertrag_titel': e.vertrag_titel, 'kategorie': e.mietrecht_kategorie,
            })
        if not objekte:
            continue
        # Vermieter = Mandant (Eigentümer) sonst Verwaltung
        if lg.mandant_id:
            vermieter = {'name': lg.mandant.firma_oder_name,
                         'strasse': lg.mandant.strasse or lg.strasse,
                         'plz': lg.mandant.plz or lg.plz, 'ort': lg.mandant.ort or lg.ort}
        else:
            vermieter = {'name': verwaltung['firma'], 'strasse': verwaltung['strasse'],
                         'plz': verwaltung['plz'], 'ort': verwaltung['ort']}
        liegenschaften.append({
            'id': lg.id, 'strasse': lg.strasse, 'plz': lg.plz, 'ort': lg.ort,
            'egid': lg.egid or '', 'vermieter': vermieter, 'objekte': objekte,
        })

    # Bestehende Mieter für Auswahl
    mieter = [{'id': m.id, 'name': m.display_name, 'anrede': m.anrede or '',
               'vorname': m.vorname or '', 'nachname': m.nachname or '',
               'strasse': m.strasse or '', 'plz': m.plz or '', 'ort': m.ort or '', 'email': m.email or ''}
              for m in Mieter.objects.all().order_by('nachname', 'firmen_name')]

    return render(request, 'fw/vertrag_neu.html', {
        **basis, 'nav': 'vertraege',
        'liegenschaften': liegenschaften, 'mieter': mieter,
        'verwaltung': verwaltung,
        'aktueller_ref_zins': float(vw.aktueller_referenzzinssatz) if vw else 1.75,
        **_lik_assistent_defaults(vw),
        'heute_iso': timezone.now().date().isoformat(),
        'vorwahl_einheit': vorwahl_einheit or '',
    })


def _lik_assistent_defaults(vw):
    """Auto-Vorbelegung LIK für den Vertragsassistenten: Basis + neuester
    Stand-Monat + Punkte aus der offiziellen BFS-Tabelle (mit Fallback auf die
    Account-Einstellungen, falls die Tabelle mal leer ist)."""
    from core.services.lik import aktueller_lik_wert
    stand, pkt, basis = aktueller_lik_wert()
    lik = float(pkt) if pkt is not None else (float(vw.aktueller_lik_punkte) if vw else 107.1)
    stand_iso = (stand.strftime('%Y-%m') if stand
                 else (vw.aktueller_lik_stand.strftime('%Y-%m') if vw and vw.aktueller_lik_stand else ''))
    return {'aktueller_lik': lik, 'lik_basis': basis, 'aktueller_lik_stand_iso': stand_iso}


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_neu_speichern(request):
    """Erstellt den Mietvertrag (+ optional neuen Mieter) aus dem Assistenten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mieter
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_vertrag_neu')

    P = request.POST
    einheit = Einheit.objects.filter(id=P.get('einheit_id') or 0).first()
    if not einheit:
        messages.error(request, "Bitte wähle ein Objekt aus, bevor du den Vertrag erstellst.")
        return redirect('/neu/vertraege/neu/')

    # Mieter: bestehend oder neu
    mieter_id = P.get('mieter_id') or ''
    if mieter_id:
        mieter = get_object_or_404(Mieter, id=mieter_id)
    else:
        mieter = Mieter.objects.create(
            typ='person', anrede=P.get('anrede', 'Herr'),
            vorname=P.get('vorname', '').strip(), nachname=P.get('nachname', '').strip(),
            strasse=P.get('m_strasse', '').strip(), plz=P.get('m_plz', '').strip(),
            ort=P.get('m_ort', '').strip(), email=P.get('m_email', '').strip(),
        )

    def dec(key, default='0'):
        try:
            return Decimal(str(P.get(key) or default).replace("'", '').replace(',', '.'))
        except Exception:
            return Decimal(default)

    def datum(key):
        v = P.get(key)
        if not v:
            return None
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None

    # Zweiter Mieter (Ehepartner) — gleiche Erfassung wie 1. Person:
    # bestehend (mit_mieter_id) ODER neu (mit_* Felder). Name -> mitmieter_name.
    mitmieter = ''
    zweiter_obj = None
    mit_id = P.get('mit_mieter_id') or ''
    if mit_id:
        zweiter_obj = Mieter.objects.filter(id=mit_id).first()
        if zweiter_obj:
            mitmieter = zweiter_obj.display_name
    if not mitmieter:
        mit_vorname = P.get('mit_vorname', '').strip()
        mit_nachname = P.get('mit_nachname', '').strip()
        # Nur einen Mitmieter bilden, wenn wirklich ein Name erfasst wurde —
        # die Anrede allein (Default 'Frau') darf keinen Phantom-Mieter erzeugen.
        if mit_vorname or mit_nachname:
            mit_teile = [P.get('mit_anrede', '').strip(), mit_vorname, mit_nachname]
            mitmieter = ' '.join(t for t in mit_teile if t).strip()
        else:
            mitmieter = P.get('mitmieter_name', '').strip()
        # Neue zweite Person mit Namen -> als Mieter-Datensatz anlegen (erscheint in Personen)
        if not zweiter_obj and (P.get('mit_vorname', '').strip() or P.get('mit_nachname', '').strip()):
            zweiter_obj = Mieter.objects.create(
                typ='person', anrede=P.get('mit_anrede', 'Frau'),
                vorname=P.get('mit_vorname', '').strip(), nachname=P.get('mit_nachname', '').strip(),
                strasse=P.get('mit_strasse', '').strip(), plz=P.get('mit_plz', '').strip(),
                ort=P.get('mit_ort', '').strip(), email=P.get('mit_email', '').strip(),
            )
    familienwohnung = P.get('familienwohnung') == 'on'

    beginn = datum('beginn') or timezone.now().date()

    # LIK-Stand-Monat (aus dem die Basis-Punkte stammen): Formular-Override,
    # sonst automatisch der neueste veröffentlichte Monat (BFS-Tabelle,
    # Basis Dez. 2020), Fallback Account-Einstellung.
    from crm.models import Verwaltung as _Vw
    from core.services.lik import aktueller_lik_wert
    _vw = einheit.liegenschaft.verwaltung or _Vw.objects.first()
    _auto_stand, _auto_pkt, _ = aktueller_lik_wert()
    basis_lik_stand = _auto_stand or (_vw.aktueller_lik_stand if _vw else None)
    _stand_raw = (P.get('basis_lik_stand') or '').strip()  # 'YYYY-MM' aus <input type=month>
    if _stand_raw:
        try:
            _jahr, _monat = _stand_raw.split('-')[:2]
            basis_lik_stand = date(int(_jahr), int(_monat), 1)
        except Exception:
            pass

    # Kündigungsfrist: bei Geschäftsräumen gesetzlich min. 6 Monate (Art. 266d);
    # wird der Wert nicht gesetzt, greift der art-abhängige Default.
    _kfrist_default = 6 if einheit.mietrecht_kategorie == 'gewerbe' else 3
    try:
        _kfrist = int(P.get('kuendigungsfrist') or _kfrist_default)
    except ValueError:
        _kfrist = _kfrist_default
    _mietzins_modell = P.get('mietzins_modell', 'fest')
    if _mietzins_modell not in ('fest', 'index', 'staffel'):
        _mietzins_modell = 'fest'

    with transaction.atomic():
        vertrag = Mietvertrag.objects.create(
            mieter=mieter, einheit=einheit,
            status='aktiv' if P.get('aktiv_setzen') == 'on' else 'entwurf',
            beginn=beginn, ende=datum('ende'),
            erstmals_kuendbar_auf=datum('erstmals_kuendbar'),
            kuendigungsfrist_monate=_kfrist,
            kuendigungstermine=P.get('kuendigungstermine', '').strip() or 'Ende jedes Monats ausser Dezember',
            mitmieter_name=mitmieter, mitmieter=zweiter_obj, familienwohnung=familienwohnung,
            anzahl_personen=int(P.get('anzahl_personen') or 1),
            besondere_vereinbarungen=P.get('besondere_vereinbarungen', '').strip(),
            mitbenutzung=P.get('mitbenutzung', '').strip(),
            nebenraeume=P.get('nebenraeume', '').strip(),
            netto_mietzins=dec('netto_mietzins'), nebenkosten=dec('nebenkosten'),
            nk_abrechnungsart=P.get('nk_abrechnungsart', 'akonto'),
            verteilschluessel=P.get('verteilschluessel', 'm2'),
            zahlungsrhythmus=P.get('zahlungsrhythmus', 'monatlich'),
            mwst_pflichtig=P.get('mwst_pflichtig') == 'on',
            mwst_satz=dec('mwst_satz') or Decimal('8.1'),
            mietzins_modell=_mietzins_modell,
            zweckbestimmung=P.get('zweckbestimmung', '').strip(),
            weitere_vorbehalte=P.get('weitere_vorbehalte', '').strip(),
            basis_referenzzinssatz=dec('basis_referenzzinssatz') or Decimal('1.75'),
            basis_lik_punkte=dec('basis_lik_punkte') or Decimal('107.1'),
            basis_lik_stand=basis_lik_stand,
            kostensteigerung_datum=datum('kostensteigerung_datum'),
            kautions_betrag=dec('kautions_betrag') or None,
            kautions_konto=P.get('kautions_konto', '').strip(),
        )
        # Staffelstufen (parallele Listen ab_datum/netto) — nur bei Staffelmiete
        if _mietzins_modell == 'staffel':
            from rentals.models import Staffelstufe
            ab_list = P.getlist('staffel_ab')
            netto_list = P.getlist('staffel_netto')
            for i, ab in enumerate(ab_list):
                try:
                    ab_d = date.fromisoformat((ab or '').strip())
                except ValueError:
                    continue
                betrag = dec(f'__staffel_{i}') if False else None
                try:
                    betrag = Decimal(str(netto_list[i]).replace("'", '').replace(',', '.')) if i < len(netto_list) and str(netto_list[i]).strip() else None
                except Exception:
                    betrag = None
                if ab_d and betrag and betrag > 0:
                    Staffelstufe.objects.create(vertrag=vertrag, ab_datum=ab_d, netto_mietzins=betrag)
    # Zukünftige Adresse = Objektadresse ab Einzug (Auto-Wechsel via
    # Mieter.check_and_update_adresse am Mietbeginn) — für beide Mieter.
    lg = einheit.liegenschaft
    obj_strasse = f"{lg.strasse}{(', ' + einheit.etage) if einheit.etage else ''}"

    def setze_zukunftsadresse(person):
        if person and beginn >= timezone.now().date() and (person.strasse or '') != lg.strasse:
            person.zukuenftige_strasse = obj_strasse
            person.zukuenftige_plz = lg.plz
            person.zukuenftiger_ort = lg.ort
            person.zukuenftig_ab = beginn
            person.save()

    setze_zukunftsadresse(mieter)
    setze_zukunftsadresse(zweiter_obj)

    # Vertragsdokumente automatisch erzeugen und einzeln in die Akte legen
    # (→ erscheinen sofort im Mieterportal). Fehler dürfen die Erstellung
    # nicht blockieren.
    anzahl_dok = 0
    try:
        from core.views.pdf import erzeuge_und_ablege_vertragspaket
        anzahl_dok = len(erzeuge_und_ablege_vertragspaket(vertrag))
    except Exception:
        anzahl_dok = 0

    # Mietrechtliche Plausibilitätsprüfung (Index ≥ 5 J / Staffel ≥ 3 J,
    # max. 1 Staffelerhöhung/Jahr) — als Warnung, nicht blockierend.
    try:
        from core.services.mietrecht import pruefe_mietzinsmodell, staffel_pruefung
        _warn = pruefe_mietzinsmodell(_mietzins_modell, vertrag.beginn, vertrag.ende)
        if _mietzins_modell == 'staffel':
            _warn += staffel_pruefung(list(vertrag.staffelstufen.all()))
        for _w in _warn:
            messages.warning(request, "⚠️ " + _w)
    except Exception:
        pass

    log_aktion(request, "Mietvertrag erstellt (Assistent)", str(mieter),
               f"{einheit.bezeichnung}, ab {beginn}", ziel=vertrag)
    if anzahl_dok:
        messages.success(
            request,
            f"✅ Mietvertrag für {mieter.display_name} erstellt — "
            f"{anzahl_dok} Dokumente automatisch abgelegt (im Portal sichtbar).")
    else:
        messages.success(request, f"✅ Mietvertrag für {mieter.display_name} erstellt.")
    return redirect(f'/neu/vertraege/{vertrag.id}/')


# ============================================================
# PROFIL-MENÜ: Account, Benutzer, Mandate, Vorlagen, Integrationen
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_account(request):
    """Firmen-/Verwaltungs-Stammdaten + Marktdaten (Referenzzins/LIK)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Verwaltung
    from core.auth import log_aktion, hat_rolle, snapshot_model, diff_model
    vw = Verwaltung.objects.first() or Verwaltung.objects.create(firma="Meine Verwaltung")
    basis = _global_filter(request)

    if request.method == 'POST' and hat_rolle(request.user, SCHREIB_ROLLEN):
        P = request.POST
        alt_snap = snapshot_model(Verwaltung.objects.get(pk=vw.pk))
        vw.firma = P.get('firma', '').strip() or vw.firma
        vw.strasse = P.get('strasse', '').strip()
        vw.plz = P.get('plz', '').strip()
        vw.ort = P.get('ort', '').strip()
        vw.telefon = P.get('telefon', '').strip()
        vw.email = P.get('email', '').strip()
        vw.iban = P.get('iban', '').strip()

        def dec(key, fallback):
            try:
                return Decimal(str(P.get(key) or fallback).replace(',', '.'))
            except Exception:
                return fallback
        vw.aktueller_referenzzinssatz = dec('aktueller_referenzzinssatz', vw.aktueller_referenzzinssatz)
        vw.aktueller_lik_punkte = dec('aktueller_lik_punkte', vw.aktueller_lik_punkte)
        # LIK-Basis + Stand-Monat
        vw.lik_basis = (P.get('lik_basis') or vw.lik_basis or 'Dezember 2020').strip()
        stand_raw = (P.get('aktueller_lik_stand') or '').strip()  # 'YYYY-MM' aus <input type=month>
        if stand_raw:
            try:
                jahr, monat = stand_raw.split('-')[:2]
                vw.aktueller_lik_stand = date(int(jahr), int(monat), 1)
            except Exception:
                pass
        # Logo hochladen oder entfernen
        if P.get('logo_entfernen') == '1' and vw.logo:
            vw.logo.delete(save=False)
            vw.logo = None
        elif request.FILES.get('logo'):
            vw.logo = request.FILES['logo']
        vw.save()
        log_aktion(request, "Account/Stammdaten bearbeitet", vw.firma,
                   diff_model(alt_snap, snapshot_model(vw), vw))
        messages.success(request, "✅ Stammdaten gespeichert.")
        return redirect('/neu/account/')

    logo_url = ''
    if getattr(vw, 'logo', None):
        try:
            logo_url = vw.logo.url
        except Exception:
            logo_url = ''
    return render(request, 'fw/account.html', {**basis, 'nav': 'account', 'vw': vw, 'logo_url': logo_url})


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_marktdaten_aktualisieren(request):
    """Holt Referenzzins + LIK aus dem Internet und speichert sie in Verwaltung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.utils.market_data import update_verwaltung_rates
    if request.method == 'POST':
        try:
            msg, errors = update_verwaltung_rates()
            messages.success(request, f"📡 {msg}")
            if errors:
                messages.warning(request, "Hinweis: " + " | ".join(errors[:2]) +
                                 " — Falls das Netzwerk (PythonAnywhere-Whitelist) die Abfrage blockiert, "
                                 "kannst du die Werte oben manuell eintragen.")
        except Exception as e:
            messages.error(request, f"Marktdaten konnten nicht geladen werden: {e}. Werte bitte manuell eintragen.")
    return redirect('/neu/account/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_marktdaten_live(request):
    """JSON-Endpoint für den 'Aktuelle Werte'-Button im Vertragsassistenten.
    Versucht ein Live-Update, gibt aber immer die aktuell gespeicherten Werte zurück."""
    from django.http import JsonResponse
    from crm.models import Verwaltung
    from core.auth import hat_rolle
    quelle = 'gespeichert'
    if hat_rolle(request.user, SCHREIB_ROLLEN):
        try:
            from core.utils.market_data import update_verwaltung_rates
            update_verwaltung_rates()
            quelle = 'internet'
        except Exception:
            quelle = 'gespeichert'
    vw = Verwaltung.objects.first()
    return JsonResponse({
        'ref_zins': float(vw.aktueller_referenzzinssatz) if vw else 1.25,
        'lik': float(vw.aktueller_lik_punkte) if vw else 107.8,
        'stand': vw.letztes_update_marktdaten.strftime('%d.%m.%Y %H:%M') if vw and vw.letztes_update_marktdaten else None,
        'quelle': quelle,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_benutzer(request):
    """Team-Mitglieder (Django-User + Rolle). Portal-Konten (Mieter/Eigentümer)
    werden hier NICHT angezeigt — die werden über Person bzw. Mandant verwaltet."""
    from django.contrib.auth.models import User
    from core.auth import ROLLE_EIGENTUEMER
    basis = _global_filter(request)
    users = User.objects.filter(is_active=True).order_by('username')
    rows = []
    for u in users:
        # Reine Portal-Zugänge ausblenden (Mieter- oder Eigentümer-Portal)
        if getattr(u, 'mieter_profil', None) is not None:
            continue
        if getattr(u, 'mandant_profil', None) is not None:
            continue
        rollen = list(u.groups.values_list('name', flat=True))
        if ROLLE_EIGENTUEMER in rollen and len(rollen) == 1:
            continue  # reiner Eigentümer (per Rolle) — auch ausblenden
        rows.append({'u': u, 'rolle': ', '.join(rollen) or ('Superuser' if u.is_superuser else '—'),
                     'name': (u.get_full_name() or u.username)})
    return render(request, 'fw/benutzer.html', {**basis, 'nav': 'benutzer', 'rows': rows})


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_logbuch(request):
    """Logbuch / Audit-Trail: wer hat wann was getan (Verträge, Personen,
    Dokumente, Buchungen, Löschungen …). Nur für die Verwaltung einsehbar,
    rein lesend. Filter: Freitext, Benutzer, Aktionsart, Zeitraum · seitenweise.
    Optionaler CSV-Export mit denselben Filtern (?export=csv)."""
    from django.contrib.auth.models import User
    from django.core.paginator import Paginator
    from core.models import AktivitaetsLog
    basis = _global_filter(request)

    qs = AktivitaetsLog.objects.select_related('benutzer').all()

    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(aktion__icontains=q) | Q(objekt__icontains=q) | Q(details__icontains=q))

    benutzer_id = (request.GET.get('benutzer') or '').strip()
    if benutzer_id == 'system':
        qs = qs.filter(benutzer__isnull=True)
    elif benutzer_id.isdigit():
        qs = qs.filter(benutzer_id=int(benutzer_id))

    # Aktionsart: strukturierte Kategorie (zuverlässig, am Eintrag gespeichert).
    art = (request.GET.get('art') or '').strip()
    if art == 'kritisch':
        qs = qs.filter(kategorie__in=AktivitaetsLog.KRITISCH)
    elif art in dict(AktivitaetsLog.KATEGORIE_CHOICES):
        qs = qs.filter(kategorie=art)

    tage = (request.GET.get('tage') or '30').strip()
    if tage.isdigit() and int(tage) > 0:
        von = timezone.now() - _timedelta(days=int(tage))
        qs = qs.filter(zeitpunkt__gte=von)

    # CSV-Export (gleiche Filter) — revisionssicher für die Ablage
    if request.GET.get('export') == 'csv':
        import csv
        from django.http import HttpResponse
        resp = HttpResponse(content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename="logbuch.csv"'
        resp.write('﻿')  # BOM → Excel erkennt UTF-8
        w = csv.writer(resp, delimiter=';')
        w.writerow(['Zeitpunkt', 'Benutzer', 'Aktion', 'Objekt', 'Details'])
        for e in qs[:10000]:
            w.writerow([timezone.localtime(e.zeitpunkt).strftime('%d.%m.%Y %H:%M'),
                        e.benutzer.get_full_name() or e.benutzer.username if e.benutzer else 'System',
                        e.aktion, e.objekt, e.details])
        return resp

    # PDF-Auditbericht (revisionssicher, gleiche Filter)
    if request.GET.get('export') == 'pdf':
        from django.http import HttpResponse
        from core.services.logbuch_pdf import logbuch_pdf
        pdf = logbuch_pdf(list(qs[:2000]), erstellt_von=(request.user.get_full_name() or request.user.username))
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = 'inline; filename="Logbuch-Auditbericht.pdf"'
        return resp

    # Kennzahlen für den Statistik-Kopf (auf der gefilterten Menge)
    from django.db.models import Count
    kat_counts = {k: n for k, n in qs.values_list('kategorie').annotate(n=Count('id'))}
    stat = {
        'kritisch': qs.filter(kategorie__in=AktivitaetsLog.KRITISCH).count(),
        'sicherheit': kat_counts.get('sicherheit', 0),
        'geloescht': kat_counts.get('geloescht', 0),
    }
    top_user = list(qs.exclude(benutzer__isnull=True)
                    .values('benutzer__username', 'benutzer__first_name', 'benutzer__last_name')
                    .annotate(n=Count('id')).order_by('-n')[:5])

    paginator = Paginator(qs, 50)
    seite = paginator.get_page(request.GET.get('page'))

    # Benutzer-Dropdown: nur, wer tatsächlich Einträge hat
    aktive_ids = list(AktivitaetsLog.objects.exclude(benutzer__isnull=True)
                      .values_list('benutzer_id', flat=True).distinct())
    benutzer = User.objects.filter(id__in=aktive_ids).order_by('username')

    return render(request, 'fw/logbuch.html', {
        **basis, 'nav': 'logbuch', 'seite': seite, 'total': paginator.count,
        'benutzer': benutzer, 'stat': stat, 'top_user': top_user,
        'f_q': q, 'f_benutzer': benutzer_id, 'f_art': art, 'f_tage': tage,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_rechtsgrundlagen(request):
    """Übersicht aller mietrechtlichen Grundlagen (OR/VMWG), die die Software
    anwendet — Artikel, Kurztitel und wo im Programm sie greifen."""
    from core.services import mietrecht
    basis = _global_filter(request)
    return render(request, 'fw/rechtsgrundlagen.html', {
        **basis, 'nav': 'rechtsgrundlagen', 'gruppen': mietrecht.uebersicht(),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mandate(request):
    """Mandanten (Eigentümer, für die verwaltet wird)."""
    from crm.models import Mandant
    basis = _global_filter(request)
    mandanten = Mandant.objects.all().order_by('firma_oder_name')
    rows = []
    for md in mandanten:
        anzahl_lg = Liegenschaft.objects.filter(mandant=md).count()
        rows.append({'md': md, 'anzahl_lg': anzahl_lg})
    return render(request, 'fw/mandate.html', {**basis, 'nav': 'mandate', 'rows': rows})


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterwechsel(request):
    """Mieterwechsel-Cockpit: alle laufenden Kündigungen als Pipeline
    Gekündigt → Rücknahme → Nachmieter → neuer Vertrag → Übergabe."""
    from rentals.models import Kuendigung, Abnahmeprotokoll
    from mietprozess.models import Mietbewerbung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    qs = (Kuendigung.objects.filter(status__in=['erfasst', 'bestaetigt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft')
          .order_by('per_datum', 'berechneter_termin'))
    if aktive_lg:
        qs = qs.filter(vertrag__einheit__liegenschaft=aktive_lg)

    rows = []
    for k in qs:
        v = k.vertrag
        e = v.einheit if v else None
        lg = e.liegenschaft if e else None
        ende = k.per_datum or k.berechneter_termin
        tage = (ende - heute).days if ende else None

        # Nachmieter-Vertrag: anderer Vertrag auf derselben Einheit mit Beginn ~ab Ende
        nachmieter_v = None
        if e:
            nachmieter_v = (Mietvertrag.objects.filter(einheit=e)
                            .exclude(id=v.id)
                            .filter(beginn__gte=(ende or v.beginn) if ende else v.beginn)
                            .exclude(status='inaktiv')
                            .select_related('mieter').order_by('beginn').first())
        bewerbungen = Mietbewerbung.objects.filter(einheit=e).exclude(status='abgelehnt').count() if e else 0
        auszug_prot = v.abnahmen.filter(typ='auszug').order_by('-datum').first() if v else None
        auszug = auszug_prot is not None
        einzug = nachmieter_v.abnahmen.filter(typ='einzug').exists() if nachmieter_v else False

        # Kaution + offene Forderungen des ausziehenden Mieters: nach der Rücknahme
        # per Schlussabrechnung abrechnen (netto: offene Forderungen − Kaution, Art. 257e).
        kaution_status = v.kautions_status if v else 'keine'
        kaution_offen = kaution_status in ('erwartet', 'einbezahlt')   # noch nicht abgerechnet
        kaution_erledigt = kaution_status in ('zurueckbezahlt', 'keine')
        offene_forderungen = (DebitorenRechnung.objects
                              .filter(vertrag=v, status__in=['offen', 'teilbezahlt']).count()) if v else 0
        # Schlussabrechnung nötig, solange Kaution offen ODER Forderungen offen sind
        schluss_offen = bool(auszug and (kaution_offen or offene_forderungen > 0))

        # Pipeline-Stufe + nächste Aktion
        if schluss_offen:
            stufe, farbe, aktion = 'Schlussabrechnung', 'amber', 'Schlussabrechnung erstellen (Kaution + offene Forderungen)'
        elif einzug and kaution_erledigt and offene_forderungen == 0:
            stufe, farbe, aktion = 'Abgeschlossen', 'emerald', '—'
        elif nachmieter_v:
            stufe, farbe, aktion = 'Nachmieter-Vertrag', 'sky', 'Übergabe / Einzug planen'
        elif bewerbungen:
            stufe, farbe, aktion = 'Bewerbungen', 'indigo', 'Bewerbung prüfen & Vertrag erstellen'
        elif auszug:
            stufe, farbe, aktion = 'Rücknahme erfolgt', 'amber', 'Nachmieter suchen'
        else:
            stufe, farbe, aktion = 'Gekündigt', 'rose', 'Objekt ausschreiben / Rücknahme planen'

        rows.append({
            'k': k, 'v': v, 'einheit': e, 'liegenschaft': lg,
            'objekt': (f"{lg.strasse}, {lg.ort} · {e.bezeichnung}" if lg and e else (e.bezeichnung if e else '—')),
            'mieter': v.mieter.display_name if v and v.mieter_id else '—',
            'ende': ende, 'tage': tage,
            'nachmieter': nachmieter_v.mieter.display_name if nachmieter_v and nachmieter_v.mieter_id else None,
            'nachmieter_vid': nachmieter_v.id if nachmieter_v else None,
            'bewerbungen': bewerbungen, 'auszug': auszug, 'einzug': einzug,
            'auszug_prot_id': (auszug_prot.id if auszug_prot else None),
            'kaution_offen': kaution_offen, 'kaution_erledigt': kaution_erledigt,
            'kaution_betrag': (v.kautions_betrag if v else None),
            'offene_forderungen': offene_forderungen, 'schluss_offen': schluss_offen,
            'ausgeschrieben': (e.zur_ausschreibung if e else False),
            'einheit_id': (e.id if e else None),
            'stufe': stufe, 'farbe': farbe, 'aktion': aktion,
        })

    offen = [r for r in rows if r['stufe'] != 'Abgeschlossen']
    return render(request, 'fw/mieterwechsel.html', {
        **basis, 'nav': 'mieterwechsel', 'rows': rows,
        'anzahl': len(rows), 'offen': len(offen),
        'dringend': len([r for r in offen if r['tage'] is not None and r['tage'] <= 60]),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_ausschreiben(request, einheit_id):
    """Objekt zur Nachmietersuche ausschreiben (bzw. Ausschreibung beenden).
    Setzt `zur_ausschreibung` und übernimmt das Verfügbarkeitsdatum aus der
    laufenden Kündigung, falls noch keins gesetzt ist."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from core.auth import log_aktion
    basis = _global_filter(request)
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=einheit_id)

    def _kuendigung_ende():
        k = (Kuendigung.objects.filter(vertrag__einheit=e, status__in=['erfasst', 'bestaetigt'])
             .order_by('per_datum', 'berechneter_termin').first())
        return (k.per_datum or k.berechneter_termin) if k else None

    if request.method != 'POST':
        # GET: Ausschreibungs-Formular (v.a. für das Cockpit-Modal)
        embed = request.GET.get('embed') == '1'
        return render(request, 'fw/objekt_ausschreiben.html', {
            **basis, 'nav': 'mieterwechsel', 'e': e,
            'verfuegbar_default': (e.verfuegbar_ab or _kuendigung_ende() or timezone.localdate()).isoformat(),
            'embed_base': ('fw/base_embed.html' if embed else None),
        })

    ziel = request.POST.get('ziel', 'an')
    weiter = request.POST.get('weiter') or '/neu/mieterwechsel/'
    if ziel == 'aus':
        e.zur_ausschreibung = False
        e.save(update_fields=['zur_ausschreibung'])
        log_aktion(request, "Ausschreibung beendet", str(e), '')
        messages.success(request, "Ausschreibung beendet.")
        return redirect(weiter)

    # Verfügbarkeitsdatum: aus Formular, sonst aus der Kündigung
    try:
        vd = date.fromisoformat(request.POST.get('verfuegbar_ab') or '')
    except Exception:
        vd = None
    e.verfuegbar_ab = vd or e.verfuegbar_ab or _kuendigung_ende()
    notiz = request.POST.get('notiz', '').strip()
    if notiz:
        e.ausschreibung_notiz = notiz
    e.zur_ausschreibung = True
    e.save(update_fields=['zur_ausschreibung', 'verfuegbar_ab', 'ausschreibung_notiz'])
    # 'Nachmieter suchen'-Pendenz des ausziehenden Vertrags automatisch abhaken
    k = (Kuendigung.objects.filter(vertrag__einheit=e, status__in=['erfasst', 'bestaetigt'])
         .select_related('vertrag').order_by('per_datum', 'berechneter_termin').first())
    if k and k.vertrag_id:
        from core.services.automation import erledige_pendenzen_fuer
        erledige_pendenzen_fuer(k.vertrag, ['Nachmieter', 'Inserat'], user=request.user)
    log_aktion(request, "Objekt ausgeschrieben", str(e),
               f"verfügbar ab {e.verfuegbar_ab or '—'}")
    if request.POST.get('embed'):
        return render(request, 'fw/_modal_done.html', {'msg': 'Objekt ausgeschrieben'})
    messages.success(request, "✅ Objekt zur Nachmietersuche ausgeschrieben — erscheint jetzt in der Vermarktung.")
    return redirect(weiter)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vermarktung(request):
    """Vermarktungsliste: alle ausgeschriebenen Objekte mit Eckdaten, Verfügbarkeit
    und Bewerbungsstand — die Nachmietersuche auf einen Blick."""
    from mietprozess.models import Mietbewerbung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    qs = (Einheit.objects.filter(zur_ausschreibung=True)
          .select_related('liegenschaft').order_by('verfuegbar_ab', 'liegenschaft__strasse'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    heute = timezone.localdate()
    rows = []
    for e in qs:
        lg = e.liegenschaft
        bew = list(Mietbewerbung.objects.filter(einheit=e).exclude(status='abgelehnt'))
        rows.append({
            'e': e, 'liegenschaft': lg,
            'objekt': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else e.bezeichnung),
            'bezeichnung': e.bezeichnung,
            'zimmer': e.zimmer, 'flaeche': e.flaeche_m2,
            'miete': (e.nettomiete_aktuell or Decimal('0')) + (e.nebenkosten_aktuell or Decimal('0')),
            'netto': e.nettomiete_aktuell, 'nk': e.nebenkosten_aktuell,
            'verfuegbar_ab': e.verfuegbar_ab,
            'frei': (e.verfuegbar_ab is None or e.verfuegbar_ab <= heute),
            'bewerbungen': len(bew),
            'notiz': e.ausschreibung_notiz,
        })
    return render(request, 'fw/vermarktung.html', {
        **basis, 'nav': 'vermarktung', 'rows': rows, 'anzahl': len(rows),
        'summe_bewerbungen': sum(r['bewerbungen'] for r in rows),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_stub(request, titel, icon, text, nav=''):
    basis = _global_filter(request)
    return render(request, 'fw/stub.html', {**basis, 'nav': nav, 'titel': titel, 'icon': icon, 'text': text})


PLATZHALTER_HILFE = [
    ('{mieter_name}', 'Name des Mieters'),
    ('{mieter_adresse}', 'Adresse des Mieters'),
    ('{objekt}', 'Objektbezeichnung'),
    ('{liegenschaft}', 'Strasse der Liegenschaft'),
    ('{vermieter}', 'Name der Verwaltung / des Vermieters'),
    ('{datum}', 'Heutiges Datum'),
    ('{miete}', 'Bruttomietzins'),
    # Schadensfall-/Ticket-Vorlagen
    ('{handwerker}', 'Beauftragte Handwerkerfirma (Schaden)'),
    ('{melder_name}', 'Name des Melders (Schaden)'),
    ('{melder_tel}', 'Telefon des Melders (Schaden)'),
    ('{schaden}', 'Titel des Schadens'),
    ('{ticket_id}', 'Ticket-Nummer'),
    ('{status}', 'Aktueller Ticket-Status'),
]

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vorlagen(request):
    from crm.models import Vorlage
    basis = _global_filter(request)
    vorlagen = Vorlage.objects.all()
    return render(request, 'fw/vorlagen.html', {**basis, 'nav': 'vorlagen', 'vorlagen': vorlagen})


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlagen_standard(request):
    """Legt die vorbelegten Standardvorlagen an (fehlende), die dann editierbar sind."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.services.vorlagen_defaults import seed_standard_vorlagen
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_vorlagen')
    n = seed_standard_vorlagen()
    log_aktion(request, "Standardvorlagen erstellt", f"{n} neu", '')
    if n:
        messages.success(request, f"✅ {n} Standardvorlage(n) erstellt — jederzeit unter 'Bearbeiten' anpassbar.")
    else:
        messages.success(request, "Alle Standardvorlagen sind bereits vorhanden.")
    return redirect('fw_vorlagen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlage_form(request, pk=None):
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Vorlage
    from core.auth import log_aktion, snapshot_model, diff_model
    vl = get_object_or_404(Vorlage, id=pk) if pk else None
    basis = _global_filter(request)
    if request.method == 'POST':
        alt_snap = snapshot_model(Vorlage.objects.get(pk=pk)) if pk else {}
        obj = vl or Vorlage()
        obj.name = request.POST.get('name', '').strip()
        obj.kategorie = request.POST.get('kategorie', 'brief')
        obj.betreff = request.POST.get('betreff', '').strip()
        obj.inhalt = request.POST.get('inhalt', '')
        if not obj.name:
            messages.error(request, "Bezeichnung ist erforderlich.")
            return redirect(request.path)
        obj.save()
        _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Vorlage bearbeitet" if pk else "Vorlage erstellt", obj.name, _diff)
        messages.success(request, f"✅ Vorlage '{obj.name}' gespeichert.")
        return redirect('/neu/vorlagen/')
    return render(request, 'fw/vorlage_form.html', {
        **basis, 'nav': 'vorlagen', 'vl': vl, 'ist_neu': vl is None,
        'kategorien': Vorlage.KATEGORIE_CHOICES, 'platzhalter': PLATZHALTER_HILFE,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlage_loeschen(request, pk):
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Vorlage
    from core.auth import log_aktion
    vl = get_object_or_404(Vorlage, id=pk)
    if request.method == 'POST':
        name = vl.name
        log_aktion(request, "Vorlage gelöscht", name, '')
        vl.delete()
        messages.success(request, f"🗑️ Vorlage '{name}' gelöscht.")
    return redirect('/neu/vorlagen/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_integrationen(request):
    from django.conf import settings as dj_settings
    basis = _global_filter(request)

    def gesetzt(key):
        return bool(getattr(dj_settings, key, None))

    email_ok = gesetzt('EMAIL_HOST_USER') and gesetzt('EMAIL_HOST_PASSWORD')
    integrationen = [
        {'key': 'email', 'name': 'E-Mail-Versand', 'icon': 'fa-envelope', 'farbe': 'indigo',
         'aktiv': email_ok, 'status': 'Verbunden' if email_ok else 'Nicht konfiguriert',
         'beschreibung': 'Versende Mahnungen, Abrechnungen und Anschreiben direkt aus swissImmo über deinen SMTP-Server.',
         'detail': (getattr(dj_settings, 'EMAIL_HOST', '') or '') if email_ok else 'E-Mail-Zugangsdaten in den Servereinstellungen hinterlegen.',
         'aktion': 'test_email' if email_ok else None},
        {'key': 'docuseal', 'name': 'DocuSeal — digitale Signatur', 'icon': 'fa-file-signature', 'farbe': 'emerald',
         'aktiv': gesetzt('DOCUSEAL_API_KEY'), 'status': 'Verbunden' if gesetzt('DOCUSEAL_API_KEY') else 'Nicht konfiguriert',
         'beschreibung': 'Sende Mietverträge zur rechtsgültigen elektronischen Unterschrift. Der Rücklauf wird automatisch als unterzeichnetes PDF abgelegt.',
         'detail': 'Nutzbar über „An DocuSeal senden" auf der Vertrags-Detailseite.' if gesetzt('DOCUSEAL_API_KEY') else 'DOCUSEAL_API_KEY hinterlegen.',
         'aktion': None},
        {'key': 'ki', 'name': 'KI-Rechnungsscanner', 'icon': 'fa-robot', 'farbe': 'violet',
         'aktiv': gesetzt('GROQ_API_KEY'), 'status': 'Verbunden' if gesetzt('GROQ_API_KEY') else 'Nicht konfiguriert',
         'beschreibung': 'Kreditoren-Belege automatisch auslesen (Betrag, IBAN, QR-Referenz) und als Zahlung erfassen.',
         'detail': 'Nutzbar im Bereich Kreditoren.' if gesetzt('GROQ_API_KEY') else 'GROQ_API_KEY hinterlegen.',
         'aktion': None},
        {'key': 'bank', 'name': 'Banken-Abgleich (camt.053 / QR)', 'icon': 'fa-building-columns', 'farbe': 'sky',
         'aktiv': True, 'status': 'Aktiv',
         'beschreibung': 'Importiere camt.053-Kontoauszüge und ordne Zahlungseingänge automatisch per QR-Referenz den Debitoren zu.',
         'detail': 'Nutzbar im Bereich Bankabgleich.',
         'aktion': 'bank_link'},
    ]
    return render(request, 'fw/integrationen.html', {**basis, 'nav': 'integrationen', 'integrationen': integrationen})


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_integration_test_email(request):
    """Sendet eine Test-E-Mail an die eigene Adresse."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.core.mail import EmailMessage, get_connection
    from django.conf import settings as dj_settings
    if request.method == 'POST':
        ziel = (request.user.email or getattr(dj_settings, 'EMAIL_HOST_USER', '') or '').strip()
        if not ziel:
            messages.error(request, "Keine Ziel-E-Mail hinterlegt. Bitte im Benutzerprofil eine E-Mail eintragen.")
            return redirect('/neu/integrationen/')
        try:
            # Timeout, damit ein langsamer/nicht erreichbarer SMTP den Request nie blockiert.
            conn = get_connection(timeout=15)
            EmailMessage(
                'swissImmo — Test-E-Mail',
                'Diese Test-E-Mail bestätigt, dass der E-Mail-Versand korrekt konfiguriert ist.\n\nswissImmo',
                getattr(dj_settings, 'DEFAULT_FROM_EMAIL', None),
                [ziel], connection=conn,
            ).send(fail_silently=False)
            messages.success(request, f"✅ Test-E-Mail an {ziel} gesendet.")
        except Exception as e:
            messages.error(request, f"E-Mail-Versand fehlgeschlagen: {e}")
    return redirect('/neu/integrationen/')

# Preisplan-Definition (Single Source of Truth). Preis = pro Einheit/Monat.
ABO_PLAENE = [
    {'key': 'start', 'name': 'Start', 'preis_einheit': Decimal('0.90'),
     'grund': Decimal('9'), 'gratis_bis': 3, 'farbe': 'slate',
     'zielgruppe': 'Selbstverwalter & kleine Eigentümer',
     'features': ['Objekte, Personen & Verträge', 'Vertrags-PDF & Dokumentenablage',
                  'Mieterportal (Dokumente, QR-Rechnung, Schaden, Tickets)',
                  'QR-Rechnung & Kontoauszug'],
     'nicht': ['Buchhaltung & Zahlungsverkehr', 'Nebenkosten & MWST', 'Eigentümerportal']},
    {'key': 'pro', 'name': 'Pro', 'preis_einheit': Decimal('1.90'),
     'grund': Decimal('49'), 'gratis_bis': 0, 'farbe': 'indigo', 'empfohlen': True,
     'zielgruppe': 'Liegenschaftsverwaltungen',
     'features': ['Alles aus Start', 'Buchhaltung, Sollstellung & Mahnwesen',
                  'camt.053-Import / pain.001-Export', 'Nebenkostenabrechnung & MWST',
                  'Mietzinsanpassung (amtl. Formular, LIK/Referenzzins)',
                  'Eigentümerportal & Reports', 'Serienbriefe & Schaden-/Handwerker-Flow'],
     'nicht': ['Multi-Mandant (voll)', 'KI-Analysen', 'API-Zugang']},
    {'key': 'premium', 'name': 'Premium', 'preis_einheit': Decimal('2.90'),
     'grund': Decimal('149'), 'gratis_bis': 0, 'farbe': 'purple',
     'zielgruppe': 'Grössere Verwaltungen & Treuhänder',
     'features': ['Alles aus Pro', 'Multi-Mandant & Mandatsabrechnung',
                  'KI-Analysen & Report-Assistent', 'DocuSeal-Vertragssignatur inkl.',
                  'API-Zugang', 'Prioritäts-Support & Onboarding'],
     'nicht': []},
]


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_abonnemente(request):
    """Abo-/Preisseite: 3 Stufen, Preis pro Einheit, aktueller Plan wählbar."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Verwaltung
    from core.auth import log_aktion, hat_rolle
    vw = Verwaltung.objects.first() or Verwaltung.objects.create(firma="Meine Verwaltung")
    basis = _global_filter(request)

    if request.method == 'POST' and hat_rolle(request.user, SCHREIB_ROLLEN):
        plan = request.POST.get('plan')
        if plan in dict(Verwaltung.ABO_CHOICES):
            vw.abo_plan = plan
            vw.abo_jaehrlich = request.POST.get('jaehrlich') == 'on'
            vw.save(update_fields=['abo_plan', 'abo_jaehrlich'])
            log_aktion(request, "Abo-Plan gewählt", plan, 'jährlich' if vw.abo_jaehrlich else 'monatlich')
            messages.success(request, f"✅ Plan «{dict(Verwaltung.ABO_CHOICES)[plan]}» aktiviert.")
        return redirect('/neu/abonnement/')

    einheiten = Einheit.objects.count()
    jaehrlich = vw.abo_jaehrlich
    plaene = []
    for p in ABO_PLAENE:
        verrechenbar = max(0, einheiten - p['gratis_bis'])
        monatlich = max(p['grund'], p['preis_einheit'] * verrechenbar)
        if jaehrlich:
            monatlich = (monatlich * Decimal('12') * Decimal('0.85') / Decimal('12'))
        plaene.append({
            **p, 'aktiv': vw.abo_plan == p['key'],
            'monatlich': monatlich.quantize(Decimal('1')),
            'jahr': (monatlich * 12).quantize(Decimal('1')),
        })

    return render(request, 'fw/abonnement.html', {
        **basis, 'nav': 'abonnement', 'plaene': plaene, 'einheiten': einheiten,
        'jaehrlich': jaehrlich, 'aktiver_plan': vw.abo_plan,
    })


# ============================================================
# LIEGENSCHAFT + OBJEKT CRUD (neu / bearbeiten)
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_liegenschaft_form(request, pk=None):
    """Liegenschaft erfassen oder bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mandant
    from core.auth import log_aktion, snapshot_model, diff_model
    lg = get_object_or_404(Liegenschaft, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(Liegenschaft.objects.get(pk=pk)) if pk else {}
        obj = lg or Liegenschaft()
        obj.strasse = P.get('strasse', '').strip()
        obj.plz = P.get('plz', '').strip()
        obj.ort = P.get('ort', '').strip()
        obj.kanton = P.get('kanton', '').strip()
        obj.egid = P.get('egid', '').strip()
        obj.kataster_nummer = P.get('kataster_nummer', '').strip()

        def intval(key):
            v = P.get(key, '').strip()
            try:
                return int(v) if v else None
            except ValueError:
                return None
        obj.baujahr = intval('baujahr')
        md_id = P.get('mandant_id') or ''
        obj.mandant = Mandant.objects.filter(id=md_id).first() if md_id else None
        obj.hauswart_name = P.get('hauswart_name', '').strip()
        obj.hauswart_telefon = P.get('hauswart_telefon', '').strip()
        obj.bank_name = P.get('bank_name', '').strip()
        obj.iban = P.get('iban', '').strip()
        obj.hkvo_aktiv = P.get('hkvo_aktiv') == 'on'
        try:
            obj.hkvo_grundkosten_prozent = int(P.get('hkvo_grundkosten_prozent') or 40)
        except ValueError:
            obj.hkvo_grundkosten_prozent = 40
        obj.save()
        _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Liegenschaft bearbeitet" if pk else "Liegenschaft erstellt",
                   f"{obj.strasse}, {obj.ort}", _diff, ziel=obj)
        messages.success(request, f"✅ Liegenschaft {obj.strasse} gespeichert.")

        # Automatischer GWR/EGID-Import (nur wenn gewünscht) — ermittelt die EGID
        # aus der Adresse und importiert die Objekte (Wohnungen) vom Bundesamt.
        if P.get('gwr_import', 'on') == 'on' and (not obj.egid or obj.einheiten.count() == 0):
            try:
                from portfolio.services import sync_liegenschaft_with_gwr
                res = sync_liegenschaft_with_gwr(obj)
                if res.get('egid_found'):
                    messages.success(request, f"📍 EGID {res['egid_found']} automatisch ermittelt.")
                if res.get('units_created'):
                    messages.success(request, f"🏠 {res['units_created']} Objekt(e) automatisch aus dem Gebäude- und Wohnungsregister importiert.")
                if not obj.egid and not res.get('egid_found'):
                    messages.warning(request, "⚠️ EGID konnte nicht automatisch ermittelt werden — bitte Adresse prüfen oder EGID manuell erfassen.")
                elif res.get('error'):
                    messages.warning(request, f"⚠️ GWR-Import teilweise fehlgeschlagen: {res['error']}")
            except Exception as e:
                messages.warning(request, f"⚠️ Automatischer GWR-Import nicht möglich: {e}")
        return redirect(f'/neu/liegenschaften/{obj.id}/')

    return render(request, 'fw/liegenschaft_form.html', {
        **basis, 'nav': 'liegenschaften', 'lg': lg, 'ist_neu': lg is None,
        'mandanten': Mandant.objects.all().order_by('firma_oder_name'),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_liegenschaft_gwr(request, pk):
    """GWR/EGID-Import manuell (erneut) auslösen — z.B. wenn er beim Anlegen
    fehlschlug oder die Objekte nachträglich vom Bund geladen werden sollen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    lg = get_object_or_404(Liegenschaft, id=pk)
    try:
        from portfolio.services import sync_liegenschaft_with_gwr
        res = sync_liegenschaft_with_gwr(lg)
        if res.get('egid_found'):
            messages.success(request, f"📍 EGID {res['egid_found']} ermittelt.")
        if res.get('units_created'):
            messages.success(request, f"🏠 {res['units_created']} Objekt(e) aus dem GWR importiert.")
        if not res.get('egid_found') and not res.get('units_created'):
            if lg.egid and lg.einheiten.count() > 0:
                messages.info(request, "Objekte bereits erfasst — kein weiterer Import nötig.")
            elif not lg.egid:
                messages.warning(request, "⚠️ EGID konnte nicht ermittelt werden — Adresse prüfen.")
            else:
                messages.info(request, "Keine neuen Objekte im GWR gefunden.")
        if res.get('error'):
            messages.warning(request, f"⚠️ Hinweis: {res['error']}")
    except Exception as e:
        messages.warning(request, f"⚠️ GWR-Import nicht möglich: {e}")
    return redirect(f'/neu/liegenschaften/{lg.id}/')


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_liegenschaft_loeschen(request, pk):
    """Liegenschaft löschen. Blockiert, solange aktive Verträge bestehen —
    diese müssen zuerst beendet werden (Schutz vor versehentlichem Datenverlust)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    lg = get_object_or_404(Liegenschaft, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/liegenschaften/{lg.id}/')

    aktive = Mietvertrag.objects.filter(einheit__liegenschaft=lg, status='aktiv').count()
    if aktive:
        messages.error(request, f"❌ Liegenschaft kann nicht gelöscht werden: {aktive} aktive(r) Vertrag/Verträge. Bitte zuerst kündigen/beenden.")
        return redirect(f'/neu/liegenschaften/{lg.id}/')

    name = f"{lg.strasse}, {lg.plz} {lg.ort}"
    anz_obj = lg.einheiten.count()
    log_aktion(request, "Liegenschaft gelöscht", name, f"inkl. {anz_obj} Objekt(e)")
    lg.delete()   # cascade: Objekte, Zähler, Geräte, beendete Verträge etc.
    messages.success(request, f'🗑️ Liegenschaft „{name}" inkl. {anz_obj} Objekt(e) gelöscht.')
    return redirect('/neu/liegenschaften/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_form(request, pk=None):
    """Mietobjekt (Einheit) erfassen oder bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion, snapshot_model, diff_model
    e = get_object_or_404(Einheit, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(Einheit.objects.get(pk=pk)) if pk else {}
        obj = e or Einheit()
        lg_id = P.get('liegenschaft_id') or (e.liegenschaft_id if e else None)
        obj.liegenschaft = get_object_or_404(Liegenschaft, id=lg_id)
        obj.bezeichnung = P.get('bezeichnung', '').strip()
        obj.typ = P.get('typ', 'whg')
        obj.etage = P.get('etage', '').strip()
        obj.ewid = P.get('ewid', '').strip()

        def dec(key):
            v = str(P.get(key) or '').replace(',', '.').strip()
            try:
                return Decimal(v) if v else None
            except Exception:
                return None
        obj.zimmer = dec('zimmer')
        obj.flaeche_m2 = dec('flaeche_m2')
        obj.nettomiete_aktuell = dec('nettomiete_aktuell') or Decimal('0.00')
        obj.nebenkosten_aktuell = dec('nebenkosten_aktuell') or Decimal('0.00')
        obj.keller = P.get('keller', '').strip()
        obj.notizen = P.get('notizen', '').strip()
        obj.save()
        _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Objekt bearbeitet" if pk else "Objekt erstellt",
                   f"{obj.bezeichnung} ({obj.liegenschaft.strasse})", _diff, ziel=obj)
        messages.success(request, f"✅ Objekt {obj.bezeichnung} gespeichert.")
        return redirect(f'/neu/objekte/{obj.id}/')

    vorwahl_lg = request.GET.get('lg') or (e.liegenschaft_id if e else None)
    return render(request, 'fw/objekt_form.html', {
        **basis, 'nav': 'objekte', 'e': e, 'ist_neu': e is None,
        'liegenschaften': Liegenschaft.objects.all().order_by('strasse'),
        'vorwahl_lg': str(vorwahl_lg) if vorwahl_lg else '',
        'typ_choices': Einheit.TYP_CHOICES,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_suche(request):
    """Globale Suche über Personen, Liegenschaften, Objekte und Verträge."""
    q = (request.GET.get('q') or '').strip()
    basis = _global_filter(request)
    personen, liegenschaften, objekte, vertraege = [], [], [], []

    if q:
        personen = list(Mieter.objects.filter(
            Q(vorname__icontains=q) | Q(nachname__icontains=q) | Q(firmen_name__icontains=q)
            | Q(email__icontains=q) | Q(ort__icontains=q)
        ).order_by('nachname', 'firmen_name')[:20])

        liegenschaften = list(Liegenschaft.objects.filter(
            Q(strasse__icontains=q) | Q(ort__icontains=q) | Q(plz__icontains=q) | Q(egid__icontains=q)
        ).order_by('strasse')[:20])

        objekte = list(Einheit.objects.select_related('liegenschaft').filter(
            Q(bezeichnung__icontains=q) | Q(etage__icontains=q)
            | Q(liegenschaft__strasse__icontains=q) | Q(liegenschaft__ort__icontains=q)
        ).order_by('liegenschaft__strasse', 'bezeichnung')[:20])

        vertraege = list(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft').filter(
            Q(mieter__vorname__icontains=q) | Q(mieter__nachname__icontains=q)
            | Q(mieter__firmen_name__icontains=q) | Q(einheit__bezeichnung__icontains=q)
            | Q(einheit__liegenschaft__strasse__icontains=q)
        ).order_by('-beginn')[:20])

    total = len(personen) + len(liegenschaften) + len(objekte) + len(vertraege)
    return render(request, 'fw/suche.html', {
        **basis, 'nav': '', 'q': q, 'total': total,
        'personen': personen, 'liegenschaften': liegenschaften,
        'objekte': objekte, 'vertraege': vertraege,
    })


# ============================================================
# MANDATE CRUD (Eigentümer) + Liegenschaft-Zuordnung
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_mandat_form(request, pk=None):
    """Mandant (Eigentümer) erfassen/bearbeiten + Liegenschaften zuordnen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mandant
    from core.auth import log_aktion, snapshot_model, diff_model
    md = get_object_or_404(Mandant, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(Mandant.objects.get(pk=pk)) if pk else {}
        obj = md or Mandant()
        obj.firma_oder_name = P.get('firma_oder_name', '').strip()
        obj.kontaktperson = P.get('kontaktperson', '').strip()
        obj.strasse = P.get('strasse', '').strip()
        obj.plz = P.get('plz', '').strip()
        obj.ort = P.get('ort', '').strip()
        obj.telefon = P.get('telefon', '').strip()
        obj.email = P.get('email', '').strip()
        obj.bank_name = P.get('bank_name', '').strip()
        obj.iban = P.get('iban', '').strip()
        if not obj.firma_oder_name:
            messages.error(request, "Name / Firma ist erforderlich.")
            return redirect(request.path)
        obj.save()
        # Liegenschaften zuordnen: gewählte -> dieser Mandant; abgewählte (bisher dieser) -> ohne Mandant
        gewaehlt = set(P.getlist('liegenschaften'))
        for lg in Liegenschaft.objects.all():
            sid = str(lg.id)
            if sid in gewaehlt and lg.mandant_id != obj.id:
                lg.mandant = obj
                lg.save(update_fields=['mandant'])
            elif sid not in gewaehlt and lg.mandant_id == obj.id:
                lg.mandant = None
                lg.save(update_fields=['mandant'])
        _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Mandant bearbeitet" if pk else "Mandant erstellt", obj.firma_oder_name, _diff)
        messages.success(request, f"✅ Mandant {obj.firma_oder_name} gespeichert.")
        return redirect('/neu/mandate/')

    alle_lg = Liegenschaft.objects.all().order_by('strasse')
    zugeordnet = set(Liegenschaft.objects.filter(mandant=md).values_list('id', flat=True)) if md else set()
    return render(request, 'fw/mandat_form.html', {
        **basis, 'nav': 'mandate', 'md': md, 'ist_neu': md is None,
        'alle_liegenschaften': alle_lg, 'zugeordnet': zugeordnet,
        'portal_user': getattr(md, 'benutzer', None) if md else None,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_mandant_portal_zugang(request, pk):
    """Erstellt/entfernt einen Eigentümer-Portal-Login und mailt die Zugangsdaten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth.models import User
    from crm.models import Mandant
    from core.auth import log_aktion
    import secrets
    md = get_object_or_404(Mandant, id=pk)
    ziel = f'/neu/mandate/{md.id}/bearbeiten/'
    if request.method != 'POST':
        return redirect(ziel)

    if request.POST.get('aktion') == 'entfernen':
        if md.benutzer_id:
            u = md.benutzer
            md.benutzer = None
            md.save(update_fields=['benutzer'])
            try:
                u.delete()
            except Exception:
                u.is_active = False
                u.save(update_fields=['is_active'])
        messages.success(request, "Portal-Zugang entfernt.")
        return redirect(ziel)

    basis_name = (md.email or f"eigentuemer{md.id}").strip().lower()
    passwort = secrets.token_urlsafe(9)
    if md.benutzer_id:
        u = md.benutzer
        u.set_password(passwort)
        u.is_active = True
        u.save()
    else:
        username = basis_name
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{basis_name}.{i}"
            i += 1
        u = User.objects.create_user(username=username, email=md.email or '', password=passwort)
        md.benutzer = u
        md.save(update_fields=['benutzer'])
    log_aktion(request, "Eigentümer-Portal-Zugang erstellt", md.firma_oder_name, u.username)

    mail_ok = False
    if md.email:
        from core.utils.email_service import send_eigentuemer_portal_zugang
        from crm.models import Verwaltung
        from django.conf import settings as _settings
        vw = Verwaltung.objects.first()
        login_url = _settings.PORTAL_BASE_URL.rstrip('/') + '/portal/login/'
        mail_ok = send_eigentuemer_portal_zugang(
            md.email, md.firma_oder_name, u.username, passwort, login_url,
            absender_firma=(vw.firma if vw else ''))

    if mail_ok:
        messages.success(request, f"✅ Portal-Zugang aktiv. Zugangsdaten wurden an {md.email} gesendet. (Benutzername: {u.username})")
    elif md.email:
        messages.warning(request, f"⚠️ Portal-Zugang aktiv, aber E-Mail-Versand fehlgeschlagen. Benutzername: {u.username} · Passwort: {passwort} — bitte manuell mitteilen.")
    else:
        messages.success(request, f"✅ Portal-Zugang aktiv. Keine E-Mail hinterlegt — Benutzername: {u.username} · Passwort: {passwort} (bitte dem Eigentümer sicher mitteilen, wird nur einmal angezeigt).")
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_mandat_loeschen(request, pk):
    """Löscht einen Mandanten — NUR wenn keine Liegenschaften zugeordnet sind
    (mandant->liegenschaft ist CASCADE; sonst würden Objekte/Verträge mitgelöscht)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mandant
    from core.auth import log_aktion
    md = get_object_or_404(Mandant, id=pk)
    if request.method == 'POST':
        anzahl = Liegenschaft.objects.filter(mandant=md).count()
        if anzahl > 0:
            messages.error(request, f"❌ '{md.firma_oder_name}' hat noch {anzahl} zugeordnete Liegenschaft(en). "
                                    "Bitte zuerst die Zuordnung im Bearbeiten-Dialog entfernen, dann löschen.")
            return redirect('/neu/mandate/')
        name = md.firma_oder_name
        log_aktion(request, "Mandant gelöscht", name, '')
        md.delete()
        messages.success(request, f"🗑️ Mandant {name} gelöscht.")
    return redirect('/neu/mandate/')


# ============================================================
# BENUTZER CRUD (Django-User + Rollen/Gruppen)
# ============================================================

_ROLLEN_WAHL = ('Verwaltung', 'Sachbearbeitung', 'Lesend')

@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_benutzer_form(request, pk=None):
    """Team-Benutzer erfassen/bearbeiten (Name, E-Mail, Rolle, Passwort, aktiv)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth.models import User, Group
    from core.auth import log_aktion, snapshot_model, diff_model
    ziel = get_object_or_404(User, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
        alt_snap = snapshot_model(User.objects.get(pk=pk)) if pk else {}
        alt_rolle = (next((g for g in ziel.groups.values_list('name', flat=True)
                           if g in _ROLLEN_WAHL), '') if ziel else '')
        username = P.get('username', '').strip()
        rolle = P.get('rolle', 'Lesend')
        if rolle not in _ROLLEN_WAHL:
            rolle = 'Lesend'
        if ziel is None:
            if not username:
                messages.error(request, "Benutzername ist erforderlich.")
                return redirect(request.path)
            if User.objects.filter(username__iexact=username).exists():
                messages.error(request, f"Benutzername '{username}' ist bereits vergeben.")
                return redirect(request.path)
            ziel = User(username=username)
        pw = P.get('passwort', '').strip()
        ziel.first_name = P.get('first_name', '').strip()
        ziel.last_name = P.get('last_name', '').strip()
        ziel.email = P.get('email', '').strip()
        # sich selbst nicht deaktivieren
        if ziel == request.user:
            ziel.is_active = True
        else:
            ziel.is_active = (P.get('is_active') == 'on')
        if pw:
            ziel.set_password(pw)
        ziel.save()
        # Rolle setzen (genau eine Gruppe) — Superuser-Rolle nicht anfassen
        if not ziel.is_superuser:
            grp, _ = Group.objects.get_or_create(name=rolle)
            ziel.groups.set([grp])
        _diff = diff_model(alt_snap, snapshot_model(ziel), ziel) if pk else ''
        if pk and alt_rolle and alt_rolle != rolle:
            _diff = f"Rolle: {alt_rolle} → {rolle}" + (' · ' + _diff if _diff else '')
        log_aktion(request, "Benutzer bearbeitet" if pk else "Benutzer erstellt",
                   ziel.username, _diff or rolle)
        messages.success(request, f"✅ Benutzer {ziel.username} gespeichert.")
        return redirect('/neu/benutzer/')

    aktuelle_rolle = ''
    if ziel:
        aktuelle_rolle = next((g for g in ziel.groups.values_list('name', flat=True) if g in _ROLLEN_WAHL), '')
    return render(request, 'fw/benutzer_form.html', {
        **basis, 'nav': 'benutzer', 'ziel': ziel, 'ist_neu': ziel is None,
        'rollen': _ROLLEN_WAHL, 'aktuelle_rolle': aktuelle_rolle,
        'ist_selbst': ziel == request.user if ziel else False,
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_benutzer_loeschen(request, pk):
    """Benutzer löschen — nicht sich selbst, nicht den letzten Verwaltungs-Account."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.contrib.auth.models import User
    from core.auth import log_aktion
    ziel = get_object_or_404(User, id=pk)
    if request.method == 'POST':
        if ziel == request.user:
            messages.error(request, "Du kannst deinen eigenen Account nicht löschen.")
            return redirect('/neu/benutzer/')
        # Lockout-Schutz: letzten aktiven Verwaltungs-/Superuser nicht löschen
        ist_admin = ziel.is_superuser or ziel.groups.filter(name='Verwaltung').exists()
        if ist_admin:
            andere_admins = User.objects.filter(is_active=True).filter(
                Q(is_superuser=True) | Q(groups__name='Verwaltung')
            ).exclude(id=ziel.id).distinct().count()
            if andere_admins == 0:
                messages.error(request, "Das ist der letzte Verwaltungs-Account — er kann nicht gelöscht werden.")
                return redirect('/neu/benutzer/')
        name = ziel.username
        log_aktion(request, "Benutzer gelöscht", name, '')
        ziel.delete()
        messages.success(request, f"🗑️ Benutzer {name} gelöscht.")
    return redirect('/neu/benutzer/')


# ============================================================
# KÜNDIGUNGSPROZESS (Erfassung + Fristenberechnung + Bestätigung)
# ============================================================

def _auszugscheckliste_anlegen(vertrag, kuendigung, per, user, mit_leerstand=False):
    """Legt die Standard-Auszugscheckliste als Pendenzen an (mit Fälligkeit relativ
    zum Vertragsende). Gibt die Anzahl erstellter Pendenzen zurück."""
    from core.models import Pendenz
    heute = timezone.now().date()
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    ist_vermieter = getattr(kuendigung, 'absender', '') == 'vermieter'

    def tage(offset):
        return (per + _timedelta(days=offset)) if per else heute

    # Erste Aufgabe je Kündigungs-Richtung UND Objektart: das amtliche Formular ist
    # nur bei Wohn-/Geschäftsräumen Pflicht (Art. 266l), nicht bei Nebenobjekten.
    if ist_vermieter:
        erste = "Amtliches Kündigungsformular versenden" if vertrag.ist_geschuetzt \
                else "Kündigung schriftlich mitteilen"
    else:
        erste = "Kündigung schriftlich bestätigen"
    aufgaben = [
        (erste, heute, 'vertrag'),
        ("Abnahmetermin mit Mieter vereinbaren", tage(-30), 'aufgabe'),
        ("Wohnungsabnahme durchführen (Protokoll)", per or heute, 'protokoll' if False else 'aufgabe'),
        ("Zählerstände ablesen & Ummeldung", per or heute, 'aufgabe'),
        ("Schlüssel-Rückgabe kontrollieren", per or heute, 'aufgabe'),
        ("Schlussabrechnung erstellen", tage(7), 'finanzen'),
        ("Kaution abrechnen / freigeben", tage(14), 'finanzen'),
    ]
    if mit_leerstand:
        aufgaben.append(("Nachmieter suchen / Inserat aufschalten", heute, 'aufgabe'))

    n = 0
    for titel, faellig, kat in aufgaben:
        # Duplikatschutz: gleiche Pendenz für diesen Vertrag nicht doppelt
        if Pendenz.objects.filter(vertrag=vertrag, titel=titel, erledigt=False).exists():
            continue
        Pendenz.objects.create(
            titel=titel, kategorie=(kat if kat in dict(Pendenz.KATEGORIE_CHOICES) else 'aufgabe'),
            faellig_am=faellig, liegenschaft=lg, vertrag=vertrag,
            beschreibung=f"Auszug {vertrag.mieter.display_name} · {vertrag.einheit.bezeichnung}",
            erstellt_von=user,
        )
        n += 1
    return n


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kuendigung_erfassen(request, vertrag_id):
    """Erfasst eine Kündigung, berechnet den Termin und setzt den Vertrag auf 'gekuendigt'."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from rentals.services import berechne_kuendigungstermin
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=vertrag_id)
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST

        def d(key):
            val = P.get(key)
            if not val:
                return None
            try:
                return date.fromisoformat(val)
            except ValueError:
                return None
        eingang = d('eingang_datum') or timezone.localdate()
        termin = berechne_kuendigungstermin(v, eingang)
        gewuenscht = d('gewuenschtes_ende')
        ausserord = P.get('ausserordentlich') == 'on'
        # Wirksames Ende: ausserordentlich/gewünscht -> gewünschtes Datum, sonst ordentlicher Termin
        per = gewuenscht if (ausserord and gewuenscht) else (gewuenscht or termin)

        k = Kuendigung.objects.create(
            vertrag=v, absender=P.get('absender', 'mieter'),
            eingang_datum=eingang, zustellung=P.get('zustellung', 'einschreiben'),
            gewuenschtes_ende=gewuenscht, berechneter_termin=termin, per_datum=per,
            ausserordentlich=ausserord, ausserordentlich_grund=P.get('ausserordentlich_grund', '').strip(),
            erstreckung_bis=d('erstreckung_bis'), status='bestaetigt' if P.get('bestaetigen') == 'on' else 'erfasst',
            bemerkung=P.get('bemerkung', '').strip(),
        )
        # Vertrag auf gekündigt setzen
        v.status = 'gekuendigt'
        v.aktiv = False
        v.ende = per
        v.save(update_fields=['status', 'aktiv', 'ende'])

        # Anfechtungsfrist-Pendenz bei Vermieterkündigung geschützter Räume:
        # der Mieter kann die Kündigung innert 30 Tagen anfechten (Art. 271/273 OR).
        if k.absender == 'vermieter' and v.ist_geschuetzt:
            from core.models import Pendenz
            frist = eingang + _timedelta(days=30)
            Pendenz.objects.create(
                titel=f"Anfechtungsfrist Kündigung läuft ab – {v.mieter.display_name}",
                beschreibung=("Der Mieter kann die Vermieterkündigung innert 30 Tagen ab Empfang bei der "
                              "Schlichtungsbehörde anfechten (Art. 271/271a/273 OR) und eine Erstreckung "
                              "verlangen (Art. 272). Danach wird die Kündigung grundsätzlich rechtskräftig."),
                kategorie='frist', faellig_am=frist, vertrag=v,
                liegenschaft=v.einheit.liegenschaft if v.einheit_id else None,
                erstellt_von=request.user if request.user.is_authenticated else None,
            )

        # Auszugscheckliste automatisch als Pendenzen anlegen
        leerstand_gewuenscht = P.get('leerstand_anlegen') == 'on'
        n_pendenzen = _auszugscheckliste_anlegen(v, k, per, request.user, mit_leerstand=leerstand_gewuenscht)

        # Leerstand ab Tag nach Vertragsende (opt-in)
        hinweis = ""
        if leerstand_gewuenscht and per and v.einheit_id:
            from rentals.models import Leerstand
            beginn = per + _timedelta(days=1)
            if not Leerstand.objects.filter(einheit=v.einheit, beginn=beginn, ende__isnull=True).exists():
                Leerstand.objects.create(einheit=v.einheit, beginn=beginn, grund='mietersuche',
                                         bemerkung=f"Automatisch aus Kündigung (Ende {per.strftime('%d.%m.%Y')})")
                hinweis = " · Leerstand ab " + beginn.strftime('%d.%m.%Y') + " angelegt"

        log_aktion(request, "Kündigung erfasst", str(v.mieter),
                   f"per {per.strftime('%d.%m.%Y') if per else '—'}, {n_pendenzen} Pendenzen{hinweis}", ziel=v)
        if P.get('embed'):
            return render(request, 'fw/_modal_done.html', {
                'msg': f"Kündigung erfasst · {n_pendenzen} Auszugs-Pendenzen"})
        messages.success(request, f"✅ Kündigung erfasst — Vertragsende {per.strftime('%d.%m.%Y') if per else '—'} · "
                         f"{n_pendenzen} Auszugs-Pendenzen erstellt{hinweis}.")
        return redirect(f'/neu/vertraege/{v.id}/')

    # Vorschau des nächsten Termins für heute
    vorschau_termin = berechne_kuendigungstermin(v, timezone.localdate())
    # Aus dem Verzugsprozess kommend → ausserordentliche Kündigung wegen Zahlungsverzug vorbelegen
    verzug = request.GET.get('grund') in ('verzug', '257d')
    from rentals.services import termin_257d
    ao_termin = termin_257d(timezone.localdate()) if verzug else None
    return render(request, 'fw/kuendigung_form.html', {
        **basis, 'nav': 'vertraege', 'v': v,
        'vorschau_termin': vorschau_termin, 'heute_iso': timezone.localdate().isoformat(),
        'prefill_ao': verzug,
        'prefill_grund': 'Zahlungsverzug (Art. 257d OR)' if verzug else '',
        'ao_termin': ao_termin,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_verzug_257d(request, vertrag_id):
    """Zahlungsverzug (Art. 257d OR): fällige Miete offen → Zahlungsaufforderung mit
    Fristansetzung (Dokument + Fristen-Pendenz). Nach fruchtlosem Ablauf kann
    ausserordentlich gekündigt werden (Abs. 2). GET: Formular · POST: Frist ansetzen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from datetime import timedelta
    from finance.models import DebitorenRechnung
    from crm.models import Verwaltung
    from core.models import Pendenz
    from core.auth import log_aktion
    from core.services.serienbrief import generate_serienbrief_pdf
    from core.services.ablage import ablegen

    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    heute = timezone.localdate()
    lg = v.einheit.liegenschaft if v.einheit_id else None

    # Offene, fällige Forderungen dieses Vertrags
    offene = DebitorenRechnung.objects.filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
    faellige = [r for r in offene if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) <= heute]
    offen_total = sum((r.offener_betrag for r in faellige), Decimal('0.00'))

    # Mindestfrist: Wohn-/Geschäftsräume 30 Tage, sonst 10 Tage (Art. 257d Abs. 1)
    min_frist = 30 if v.ist_geschuetzt else 10
    default_frist = (heute + timedelta(days=min_frist)).isoformat()

    if request.method == 'POST':
        try:
            frist = date.fromisoformat(request.POST.get('frist_bis') or default_frist)
        except ValueError:
            frist = heute + timedelta(days=min_frist)
        vw = Verwaltung.objects.first()
        absender = {'firma': getattr(vw, 'firma', '') if vw else '', 'strasse': getattr(vw, 'strasse', '') if vw else '',
                    'plz': getattr(vw, 'plz', '') if vw else '', 'ort': getattr(vw, 'ort', '') if vw else ''}
        m = v.mieter
        emp = [{'name': m.display_name, 'anrede': f"Sehr geehrte/r {m.display_name}",
                'strasse': m.strasse, 'plz': m.plz, 'ort': m.ort,
                'objekt': v.einheit.bezeichnung if v.einheit_id else '',
                'liegenschaft': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else '')}]
        betreff = "Zahlungsaufforderung mit Fristansetzung (Art. 257d OR)"
        text = (
            "{anrede}\n\n"
            "Für das Mietobjekt {objekt} an der {liegenschaft} sind offene Mietzinse von total "
            f"CHF {offen_total:.2f} zur Zahlung fällig.\n\n"
            f"Gestützt auf Art. 257d OR setzen wir Ihnen eine Frist bis zum {frist.strftime('%d.%m.%Y')}, "
            "um den ausstehenden Betrag vollständig zu begleichen.\n\n"
            "Wir weisen Sie ausdrücklich darauf hin, dass wir das Mietverhältnis nach unbenutztem "
            "Ablauf dieser Frist ausserordentlich kündigen können (Art. 257d Abs. 2 OR), mit einer "
            "Frist von 30 Tagen auf Ende eines Monats.\n\n"
            "Freundliche Grüsse"
        )
        pdf = generate_serienbrief_pdf(absender, betreff, text, emp)
        ablegen(pdf, f"Zahlungsaufforderung 257d – Frist {frist:%d.%m.%Y}",
                kategorie='korrespondenz', vertrag=v, dedup=False)
        # Fristen-Pendenz: läuft am Fristende ab → dann ausserordentliche Kündigung möglich
        Pendenz.objects.create(
            titel=f"Art. 257d: Zahlungsfrist läuft ab – {v.mieter.display_name}",
            beschreibung=(f"Offene Miete CHF {offen_total:.2f}. Zahlungsfrist bis {frist:%d.%m.%Y} "
                          "(Art. 257d Abs. 1 OR). Nach fruchtlosem Ablauf: ausserordentliche Kündigung "
                          "mit 30 Tagen auf Monatsende (Art. 257d Abs. 2 OR)."),
            kategorie='frist', faellig_am=frist, vertrag=v, liegenschaft=lg,
            erstellt_von=request.user if request.user.is_authenticated else None,
        )
        log_aktion(request, "Zahlungsaufforderung 257d erstellt", str(v.mieter),
                   f"Frist bis {frist:%d.%m.%Y}, offen CHF {offen_total:.2f}", ziel=v)
        if request.POST.get('als_pdf') == '1':
            from django.http import HttpResponse
            resp = HttpResponse(pdf, content_type='application/pdf')
            resp['Content-Disposition'] = f'inline; filename="Zahlungsaufforderung_{v.mieter.nachname}.pdf"'
            return resp
        messages.success(request, f"✅ Zahlungsaufforderung erstellt – Frist bis {frist:%d.%m.%Y}. "
                                  "Fristen-Pendenz angelegt.")
        return redirect(f'/neu/vertraege/{v.id}/')

    return render(request, 'fw/verzug_257d.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'lg': lg,
        'offen_total': offen_total, 'anzahl_faellig': len(faellige),
        'min_frist': min_frist, 'default_frist': default_frist,
        'heute_iso': heute.isoformat(),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kuendigung_zuruecknehmen(request, pk):
    """Nimmt eine Kündigung zurück und reaktiviert den Vertrag."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from core.auth import log_aktion
    k = get_object_or_404(Kuendigung, id=pk)
    v = k.vertrag
    if request.method == 'POST':
        k.status = 'zurueckgezogen'
        k.save(update_fields=['status'])
        # Vertrag reaktivieren, wenn keine andere aktive Kündigung besteht
        andere = v.kuendigungen.exclude(id=k.id).exclude(status='zurueckgezogen').exists()
        if not andere:
            v.status = 'aktiv'
            v.aktiv = True
            v.ende = None
            v.save(update_fields=['status', 'aktiv', 'ende'])
        log_aktion(request, "Kündigung zurückgezogen", str(v.mieter), '', ziel=v)
        messages.success(request, "✅ Kündigung zurückgezogen, Vertrag reaktiviert.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kuendigung_bestaetigen(request, pk):
    """Bestätigt eine (i.d.R. über das Mieterportal eingegangene) Kündigung:
    setzt den Vertrag auf 'gekuendigt' und legt die Auszugs-Pendenzen an."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Kuendigung
    from core.auth import log_aktion
    k = get_object_or_404(Kuendigung.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    v = k.vertrag
    if request.method != 'POST':
        return redirect(f'/neu/vertraege/{v.id}/')
    if k.status == 'zurueckgezogen':
        messages.error(request, "Zurückgezogene Kündigung kann nicht bestätigt werden.")
        return redirect(f'/neu/vertraege/{v.id}/')

    per = k.per_datum or k.berechneter_termin
    k.status = 'bestaetigt'
    k.save(update_fields=['status'])
    v.status = 'gekuendigt'
    v.aktiv = False
    v.ende = per
    v.save(update_fields=['status', 'aktiv', 'ende'])

    n_pendenzen = _auszugscheckliste_anlegen(v, k, per, request.user, mit_leerstand=False)
    # Bestätigung erfolgt → 'Kündigung schriftlich bestätigen' abhaken
    from core.services.automation import erledige_pendenzen_fuer
    erledige_pendenzen_fuer(v, ['schriftlich', 'Kündigungsformular'], user=request.user)
    log_aktion(request, "Kündigung bestätigt", str(v.mieter),
               f"per {per.strftime('%d.%m.%Y') if per else '—'}, {n_pendenzen} Pendenzen", ziel=v)
    messages.success(request, f"✅ Kündigung bestätigt — Vertragsende {per.strftime('%d.%m.%Y') if per else '—'} · "
                     f"{n_pendenzen} Auszugs-Pendenzen erstellt.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kuendigung_formular(request, pk):
    """Amtliches Kündigungsformular (PDF) — Original des zuständigen Kantons ausfüllen."""
    from django.http import HttpResponse
    from rentals.models import Kuendigung
    from crm.models import Verwaltung
    k = get_object_or_404(Kuendigung.objects.select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    vw = Verwaltung.objects.first()
    from core.services.formular_fill import fill_kuendigung
    pdf = fill_kuendigung(k.vertrag, k, verwaltung=vw)
    if pdf is None:
        from core.services.amtliche_formulare_so import kuendigung_so_pdf
        pdf = kuendigung_so_pdf(k.vertrag, k, verwaltung=vw)
    from core.services.ablage import ablegen
    ablegen(pdf, f"Kündigung {k.get_absender_display()} {k.eingang_datum:%d.%m.%Y}",
            kategorie='vertrag', vertrag=k.vertrag, dedup=True)
    # Amtliches Formular erstellt → 'schriftlich bestätigen / Formular versenden' abhaken
    from core.services.automation import erledige_pendenzen_fuer
    erledige_pendenzen_fuer(k.vertrag, ['schriftlich', 'Kündigungsformular'],
                            user=request.user)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Kuendigung_{k.vertrag.mieter.nachname}.pdf"'
    return resp


# ============================================================
# KAUTIONS-REGISTER (Art. 257e OR — separat vom Verwaltungs-Hauptbuch)
# ============================================================

KAUTION_PILL = {
    'erwartet':       ('Erwartet',       'bg-amber-50 text-amber-700'),
    'einbezahlt':     ('Einbezahlt',     'bg-emerald-50 text-emerald-700'),
    'zurueckbezahlt': ('Zurückbezahlt',  'bg-slate-100 text-slate-500'),
}

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kautionen(request):
    """Register aller Mietzinsdepots — separate Führung nach Art. 257e OR."""
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    qs = (Mietvertrag.objects.filter(kautions_betrag__gt=0)
          .select_related('mieter', 'einheit__liegenschaft').order_by('-beginn'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    rows, sum_erwartet, sum_gehalten = [], Decimal('0.00'), Decimal('0.00')
    for v in qs:
        st = v.kautions_status
        label, cls = KAUTION_PILL.get(st, (st, 'bg-slate-100 text-slate-500'))
        rows.append({'v': v, 'status': st, 'label': label, 'cls': cls})
        if st == 'erwartet':
            sum_erwartet += v.kautions_betrag or Decimal('0.00')
        elif st == 'einbezahlt':
            sum_gehalten += v.kautions_betrag or Decimal('0.00')
    return render(request, 'fw/kautionen.html', {
        **basis, 'nav': 'kautionen', 'rows': rows,
        'sum_erwartet': sum_erwartet, 'sum_gehalten': sum_gehalten,
        'anzahl': len(rows),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kaution_aktion(request, vertrag_id):
    """Einzahlung bestätigen oder Rückzahlung (mit Einbehalt) erfassen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=vertrag_id)
    if request.method != 'POST':
        return redirect(f'/neu/vertraege/{v.id}/')
    P = request.POST
    aktion = P.get('aktion')

    def d(key):
        val = P.get(key)
        try:
            return date.fromisoformat(val) if val else None
        except ValueError:
            return None

    def dec(key):
        try:
            return Decimal(str(P.get(key) or '0').replace(',', '.'))
        except Exception:
            return Decimal('0.00')

    if aktion == 'einzahlung':
        # Sperrkonto: Einzahlung auf Mietkonto bestätigen
        v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = d('einbezahlt_am') or timezone.localdate()
        v.kautions_konto = P.get('kautions_konto', v.kautions_konto).strip() or v.kautions_konto
        v.save(update_fields=['kautions_art', 'kautions_einbezahlt_am', 'kautions_konto'])
        # Bilanzbuchung: 1015 Kautionssperrkonto an 2010 Kautionsverbindlichkeit
        try:
            from core.services.automation import buche_kaution_einzahlung
            buche_kaution_einzahlung(v, v.kautions_einbezahlt_am, user=request.user)
        except Exception:
            pass
        log_aktion(request, "Kaution einbezahlt (Sperrkonto)", str(v.mieter), f"CHF {v.kautions_betrag}", ziel=v)
        messages.success(request, "✅ Kautions-Einzahlung auf Sperrkonto erfasst (bilanziert).")

    elif aktion == 'versicherung':
        # Kautionsversicherung: bestätigen, sobald das Zertifikat/die Police vorliegt
        versicherer = P.get('kautions_versicherer', '').strip()
        police = P.get('kautions_policennummer', '').strip()
        zertifikat = request.FILES.get('kautions_zertifikat')
        if not versicherer:
            messages.error(request, "❌ Bitte den Versicherer/Anbieter angeben.")
            return redirect(f'/neu/vertraege/{v.id}/')
        if not zertifikat and not v.kautions_zertifikat:
            messages.error(request, "❌ Bitte das Zertifikat / die Police hochladen — erst dann kann bestätigt werden.")
            return redirect(f'/neu/vertraege/{v.id}/')
        v.kautions_art = 'versicherung'
        v.kautions_versicherer = versicherer
        v.kautions_policennummer = police
        if zertifikat:
            v.kautions_zertifikat = zertifikat
        v.kautions_einbezahlt_am = d('einbezahlt_am') or timezone.localdate()  # = Police aktiv ab
        v.kautions_konto = ''  # kein Sperrkonto bei Versicherung
        v.save(update_fields=['kautions_art', 'kautions_versicherer', 'kautions_policennummer',
                              'kautions_zertifikat', 'kautions_einbezahlt_am', 'kautions_konto'])
        log_aktion(request, "Kautionsversicherung bestätigt", str(v.mieter),
                   f"{versicherer} · Police {police} · CHF {v.kautions_betrag}", ziel=v)
        messages.success(request, f"✅ Kautionsversicherung bestätigt ({versicherer}) — Zertifikat hinterlegt.")

    elif aktion == 'rueckzahlung':
        abzug = dec('abzug_betrag')
        total = v.kautions_betrag or Decimal('0.00')
        # Bei Versicherung wird die Police aufgelöst — es gibt keine Rückzahlung an
        # den Mieter (er hat nur Prämien bezahlt); ein Einbehalt ist eine Schadenforderung.
        if v.ist_kautionsversicherung:
            rueck = Decimal('0.00')
        else:
            rueck = dec('rueckzahlung_betrag') if P.get('rueckzahlung_betrag') else (total - abzug)
        v.kautions_zurueckbezahlt_am = d('zurueckbezahlt_am') or timezone.localdate()
        v.kautions_rueckzahlung_betrag = rueck
        v.kautions_abzug_betrag = abzug
        v.kautions_abzug_grund = P.get('abzug_grund', '').strip()
        v.save(update_fields=['kautions_zurueckbezahlt_am', 'kautions_rueckzahlung_betrag',
                              'kautions_abzug_betrag', 'kautions_abzug_grund'])
        # Bilanz: Sperrkonto auflösen (2010 an 1015)
        try:
            from core.services.automation import buche_kaution_aufloesung
            buche_kaution_aufloesung(v, v.kautions_zurueckbezahlt_am, user=request.user)
        except Exception:
            pass
        # Einbehalt optional als Debitoren-Weiterverrechnung buchen (Schadenersatz)
        if abzug > 0 and P.get('abzug_verrechnen') == 'on':
            try:
                from finance.models import DebitorenRechnung
                DebitorenRechnung.objects.create(
                    vertrag=v, betrag=abzug, datum=timezone.localdate(),
                    faellig_am=timezone.localdate(), status='bezahlt',
                    titel="Einbehalt Mietzinsdepot",
                    beschreibung=v.kautions_abzug_grund or "Verrechnung aus Kaution",
                )
            except Exception:
                pass
        from core.services.automation import erledige_pendenzen_fuer
        erledige_pendenzen_fuer(v, ['Kaution'], user=request.user)
        log_aktion(request, "Kaution zurückbezahlt", str(v.mieter),
                   f"Rückzahlung CHF {rueck}, Abzug CHF {abzug}", ziel=v)
        messages.success(request, f"✅ Rückzahlung erfasst: CHF {rueck} an Mieter, CHF {abzug} einbehalten.")
    return redirect(f'/neu/vertraege/{v.id}/')


# ============================================================
# MWST-AUSWERTUNG (Umsatzsteuer vs. Vorsteuer = Zahllast)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mwst(request):
    """MWST-Abrechnung: geschuldete Umsatzsteuer (2200) minus Vorsteuer (1170) = Zahllast."""
    from finance.models import Buchungskonto, Buchung
    from django.db.models import Sum
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.now().date()

    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    quartal = request.GET.get('quartal', '')  # '', '1'..'4'
    if quartal in ('1', '2', '3', '4'):
        q = int(quartal)
        von = date(jahr, (q - 1) * 3 + 1, 1)
        m_end = q * 3
        _, ld = _calendar.monthrange(jahr, m_end)
        bis = date(jahr, m_end, ld)
    else:
        von, bis = date(jahr, 1, 1), date(jahr, 12, 31)

    qs = Buchung.objects.filter(datum__gte=von, datum__lte=bis)
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    def saldo(nummer, soll_positiv):
        k = Buchungskonto.objects.filter(nummer=nummer).first()
        if not k:
            return Decimal('0.00')
        soll = qs.filter(soll_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        haben = qs.filter(haben_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        return (soll - haben) if soll_positiv else (haben - soll)

    umsatzsteuer = saldo('2200', soll_positiv=False)   # geschuldete MWST (Haben-Saldo)
    vorsteuer = saldo('1170', soll_positiv=True)        # Vorsteuer-Guthaben (Soll-Saldo)
    zahllast = umsatzsteuer - vorsteuer

    # Steuerbaren Umsatz aus den Ertragskonten (nur mit MWST belegte Erträge: 3010 Gewerbe)
    from crm.models import Verwaltung
    from core.services.mwst_estv import berechne_estv
    vw = Verwaltung.objects.first()
    umsatz_steuerbar = saldo('3010', soll_positiv=False)  # Gewerbe/Parkplätze (optiert)
    methode = getattr(vw, 'mwst_methode', 'effektiv') if vw else 'effektiv'
    saldosatz = getattr(vw, 'saldosteuersatz', Decimal('0')) if vw else Decimal('0')
    estv = berechne_estv(
        umsatz_steuerbar=umsatz_steuerbar, umsatzsteuer=umsatzsteuer,
        vorsteuer_material=vorsteuer, vorsteuer_invest=Decimal('0'),
        methode=methode, saldosteuersatz=saldosatz)
    if methode == 'saldo':
        zahllast = estv['z500']

    return render(request, 'fw/mwst.html', {
        **basis, 'nav': 'mwst', 'jahr': jahr, 'quartal': quartal,
        'von': von, 'bis': bis,
        'umsatzsteuer': umsatzsteuer, 'vorsteuer': vorsteuer, 'zahllast': zahllast,
        'umsatz_steuerbar': umsatz_steuerbar, 'estv': estv,
        'mwst_methode': methode, 'saldosteuersatz': saldosatz,
        'mwst_uid': getattr(vw, 'mwst_uid', '') if vw else '',
        'jahre': list(range(heute.year, heute.year - 5, -1)),
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_mwst_einstellungen(request):
    """Speichert MWST-Methode, Saldosteuersatz und MWST-Nummer."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Verwaltung
    if request.method != 'POST':
        return redirect('fw_mwst')
    vw = Verwaltung.objects.first()
    if not vw:
        messages.error(request, "Keine Verwaltung erfasst.")
        return redirect('fw_mwst')
    vw.mwst_methode = request.POST.get('mwst_methode', 'effektiv')
    vw.mwst_uid = (request.POST.get('mwst_uid') or '').strip()
    try:
        vw.saldosteuersatz = Decimal((request.POST.get('saldosteuersatz') or '0').replace(',', '.'))
    except Exception:
        vw.saldosteuersatz = Decimal('0')
    vw.save(update_fields=['mwst_methode', 'mwst_uid', 'saldosteuersatz'])
    messages.success(request, "✅ MWST-Einstellungen gespeichert.")
    ziel = request.POST.get('zurueck') or '/neu/mwst/'
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mwst_estv_export(request):
    """ESTV-Abrechnung als CSV (offizielle Ziffern) für den gewählten Zeitraum."""
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from core.services.mwst_estv import estv_csv
    from finance.models import Buchungskonto, Buchung
    from django.db.models import Sum
    heute = timezone.now().date()
    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    quartal = request.GET.get('quartal', '')
    if quartal in ('1', '2', '3', '4'):
        q = int(quartal)
        von = date(jahr, (q - 1) * 3 + 1, 1)
        _, ld = _calendar.monthrange(jahr, q * 3)
        bis = date(jahr, q * 3, ld)
    else:
        von, bis = date(jahr, 1, 1), date(jahr, 12, 31)

    qs = Buchung.objects.filter(datum__gte=von, datum__lte=bis)

    def saldo(nummer, soll_positiv):
        k = Buchungskonto.objects.filter(nummer=nummer).first()
        if not k:
            return Decimal('0.00')
        soll = qs.filter(soll_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        haben = qs.filter(haben_konto=k).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        return (soll - haben) if soll_positiv else (haben - soll)

    vw = Verwaltung.objects.first()
    from core.services.mwst_estv import berechne_estv
    estv = berechne_estv(
        umsatz_steuerbar=saldo('3010', soll_positiv=False),
        umsatzsteuer=saldo('2200', soll_positiv=False),
        vorsteuer_material=saldo('1170', soll_positiv=True),
        vorsteuer_invest=Decimal('0'),
        methode=getattr(vw, 'mwst_methode', 'effektiv') if vw else 'effektiv',
        saldosteuersatz=getattr(vw, 'saldosteuersatz', Decimal('0')) if vw else Decimal('0'))
    csv_bytes = estv_csv(estv, firma=(vw.firma if vw else 'Verwaltung'),
                         uid=(vw.mwst_uid if vw else ''), periode_von=von, periode_bis=bis)
    resp = HttpResponse(csv_bytes, content_type='text/csv; charset=utf-8')
    zeitraum = f"{jahr}" + (f"_Q{quartal}" if quartal else "")
    resp['Content-Disposition'] = f'attachment; filename="ESTV_MWST_{zeitraum}.csv"'
    return resp


# ============================================================
# MIETPROZESS: BEWERBUNGEN → MIETER → VERTRAG (in der /neu/-Shell)
# ============================================================

BEWERBUNG_SPALTEN = [
    ('neu', 'Neu eingegangen', 'bg-sky-50 text-sky-700'),
    ('geprueft', 'Bonität geprüft', 'bg-amber-50 text-amber-700'),
    ('zugesagt', 'Zusage erteilt', 'bg-emerald-50 text-emerald-700'),
    ('abgelehnt', 'Abgelehnt', 'bg-rose-50 text-rose-700'),
]


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bewerbungen(request):
    """Bewerbungen-Board, nach Status gruppiert."""
    from mietprozess.models import Mietbewerbung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (Mietbewerbung.objects.select_related('einheit__liegenschaft')
          .order_by('-erstellt_am'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    alle = list(qs)
    spalten = []
    for key, label, cls in BEWERBUNG_SPALTEN:
        eintraege = [b for b in alle if b.status == key]
        spalten.append({'key': key, 'label': label, 'cls': cls, 'items': eintraege, 'anzahl': len(eintraege)})

    return render(request, 'fw/bewerbungen.html', {
        **basis, 'nav': 'bewerbungen', 'spalten': spalten, 'gesamt': len(alle),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bewerbung_detail(request, pk):
    from mietprozess.models import Mietbewerbung
    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft'), id=pk)
    basis = _global_filter(request)

    dokumente = []
    for feld, label in [('betreibungsauszug', 'Betreibungsauszug'), ('ausweiskopie', 'Ausweiskopie'),
                        ('lohnausweis', 'Lohnausweis'), ('weitere_dokumente', 'Weitere Dokumente')]:
        f = getattr(b, feld, None)
        if f:
            dokumente.append({'label': label, 'url': f.url})

    status_label = dict((k, l) for k, l, _ in BEWERBUNG_SPALTEN).get(b.status, b.status)
    from django.contrib import messages
    return render(request, 'fw/bewerbung_detail.html', {
        **basis, 'nav': 'bewerbungen', 'b': b, 'dokumente': dokumente,
        'status_label': status_label, 'status_wahl': BEWERBUNG_SPALTEN,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerbung_status(request, pk):
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect(f'/neu/bewerbungen/{pk}/')
    b = get_object_or_404(Mietbewerbung, id=pk)
    neu = request.POST.get('status')
    gueltig = {k for k, _, _ in BEWERBUNG_SPALTEN}
    if neu in gueltig:
        b.status = neu
        b.save()
        log_aktion(request, "Bewerbungsstatus geändert", f"{b.vorname} {b.nachname}", neu)
        messages.success(request, f"Status auf „{dict((k,l) for k,l,_ in BEWERBUNG_SPALTEN)[neu]}“ gesetzt.")
    return redirect(f'/neu/bewerbungen/{pk}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerbung_zu_vertrag(request, pk):
    """Zusage: Mieter aus der Bewerbung anlegen (oder finden) und einen
    Vertragsentwurf auf der Einheit erstellen — mit den Objekt-Defaults vorbefüllt."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect(f'/neu/bewerbungen/{pk}/')

    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft'), id=pk)
    einheit = b.einheit
    lg = einheit.liegenschaft

    # 1. Mieter finden oder anlegen (Duplikat-Schutz über E-Mail + Name)
    mieter = None
    if b.email:
        mieter = Mieter.objects.filter(email__iexact=b.email, nachname__iexact=b.nachname).first()
    if not mieter:
        mieter = Mieter.objects.create(
            typ='person',
            anrede='Frau' if b.geschlecht == 'weiblich' else 'Herr',
            vorname=b.vorname, nachname=b.nachname,
            geburtsdatum=b.geburtsdatum, zivilstand=b.zivilstand or '',
            nationalitaet=b.nationalitaet or '', heimatort=b.heimatort or '',
            erwerbsstatus=b.erwerbsstatus or '', beruf=b.beruf or '',
            arbeitgeber=b.arbeitgeber or '', einkommen_jahr=b.einkommen_jahr or '',
            email=b.email or '', mobile=b.mobilnummer or '',
            strasse=b.adresse or '', plz=b.plz or '', ort=b.ort or '',
        )

    # 2. Vertragsentwurf anlegen (mit Objekt-Defaults)
    from decimal import Decimal as _D
    beginn = b.gewuenschter_bezugstermin or timezone.now().date()
    kautionsmonate = einheit.standard_kautionsmonate or 0
    netto = einheit.nettomiete_aktuell or _D('0')
    nk = einheit.nebenkosten_aktuell or _D('0')
    kaution = (netto + nk) * kautionsmonate if kautionsmonate else None

    vertrag = Mietvertrag.objects.create(
        mieter=mieter, einheit=einheit, status='entwurf', beginn=beginn,
        netto_mietzins=netto, nebenkosten=nk,
        nk_abrechnungsart=einheit.nk_abrechnungsart or 'akonto',
        anzahl_personen=(b.anzahl_erwachsene or 1) + (b.anzahl_kinder or 0),
        kautions_betrag=kaution,
        basis_referenzzinssatz=einheit.ref_zinssatz or _D('1.75'),
        basis_lik_punkte=einheit.lik_punkte or _D('107.1'),
        besondere_vereinbarungen=(f"Haustiere: {b.haustiere_details}" if b.haustiere and b.haustiere_details else ''),
    )

    b.status = 'zugesagt'
    b.save()
    log_aktion(request, "Bewerbung → Vertragsentwurf", f"{mieter.display_name}",
               f"{einheit.bezeichnung}, Entwurf #{vertrag.id}", ziel=vertrag)
    messages.success(request,
        f"✅ Mieter angelegt und Vertragsentwurf für {einheit.bezeichnung} erstellt — "
        f"bitte Konditionen prüfen und aktivieren.")
    return redirect(f'/neu/vertraege/{vertrag.id}/')


# ============================================================
# PENDENZEN / FRISTEN (persistent + automatisch berechnet)
# ============================================================

def _auto_fristen(aktive_lg, horizont_tage=90):
    """Automatisch berechnete Fristen aus dem Datenbestand (read-only):
    befristete Vertragsenden, Kündigungs-Vollzüge, erstmals kündbar."""
    from rentals.models import Kuendigung
    heute = timezone.now().date()
    grenze = heute + _timedelta(days=horizont_tage)
    fristen = []

    aktive = Mietvertrag.objects.filter(status='aktiv').select_related('mieter', 'einheit__liegenschaft')
    gek = Mietvertrag.objects.filter(status='gekuendigt').select_related('mieter', 'einheit__liegenschaft')
    if aktive_lg:
        aktive = aktive.filter(einheit__liegenschaft=aktive_lg)
        gek = gek.filter(einheit__liegenschaft=aktive_lg)

    # a) Befristete Vertragsenden im Horizont
    for v in aktive.filter(ende__range=[heute, grenze]).order_by('ende'):
        fristen.append({
            'kategorie': 'Befristetes Vertragsende', 'farbe': 'amber', 'icon': 'fa-hourglass-end',
            'titel': f"Vertrag {v.mieter.display_name} endet",
            'sub': f"{v.einheit.bezeichnung}, {v.einheit.liegenschaft.strasse}",
            'faellig': v.ende, 'url': f'/neu/vertraege/{v.id}/',
            'tage': (v.ende - heute).days,
        })

    # b) Gekündigte Verträge — Auszug/Übergabe steht an
    for v in gek.filter(ende__range=[heute, grenze]).order_by('ende'):
        fristen.append({
            'kategorie': 'Auszug (gekündigt)', 'farbe': 'rose', 'icon': 'fa-person-walking-arrow-right',
            'titel': f"Auszug {v.mieter.display_name}",
            'sub': f"{v.einheit.bezeichnung} — Abnahme & Kautionsabrechnung vorbereiten",
            'faellig': v.ende, 'url': f'/neu/vertraege/{v.id}/',
            'tage': (v.ende - heute).days,
        })

    # c) Erstmals kündbar im Horizont
    for v in aktive.filter(erstmals_kuendbar_auf__range=[heute, grenze]).order_by('erstmals_kuendbar_auf'):
        fristen.append({
            'kategorie': 'Erstmals kündbar', 'farbe': 'indigo', 'icon': 'fa-calendar-check',
            'titel': f"{v.mieter.display_name}: erstmals kündbar",
            'sub': f"{v.einheit.bezeichnung} — Mietzins-/Konditionen-Review möglich",
            'faellig': v.erstmals_kuendbar_auf, 'url': f'/neu/vertraege/{v.id}/',
            'tage': (v.erstmals_kuendbar_auf - heute).days,
        })

    fristen.sort(key=lambda f: f['faellig'])
    return fristen


def _pendenz_ziel(p):
    """Verknüpft eine Pendenz mit dem passenden Objekt/Schritt (öffnet im Popup).
    Rückgabe: (url, label, wide). Modulweit nutzbar (Pendenzen-Seite + Dashboard)."""
    q = p.quelle or ''
    if p.vertrag_id:
        if q.startswith('auto:ruecknahme:'):
            return (f'/neu/vertraege/{p.vertrag_id}/abnahme/neu/?typ=auszug', 'Rücknahme starten', False)
        return (f'/neu/vertraege/{p.vertrag_id}/', 'Vertrag öffnen', True)
    if p.liegenschaft_id:
        return (f'/neu/liegenschaften/{p.liegenschaft_id}/', 'Liegenschaft öffnen', True)
    return (None, None, False)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_pendenzen(request):
    from core.models import Pendenz
    from crm.models import Mandant  # noqa
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.now().date()

    auto = _auto_fristen(aktive_lg)

    pq = Pendenz.objects.all().select_related('liegenschaft', 'vertrag__mieter')
    if aktive_lg:
        pq = pq.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg) | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    offene = list(pq.filter(erledigt=False))
    erledigte = list(pq.filter(erledigt=True)[:20])

    for p in offene:
        p.ueberfaellig = bool(p.faellig_am and p.faellig_am < heute)
        p.ziel_url, p.ziel_label, p.ziel_wide = _pendenz_ziel(p)

    # Nach Bezug gruppieren: pro Vertrag (Auszug/Mieterwechsel) eine Gruppe,
    # Liegenschafts-Fristen je Liegenschaft, der Rest unter „Allgemein".
    # So bleiben die je ~8 Auszugs-Pendenzen mehrerer Kündigungen getrennt.
    from collections import OrderedDict
    gruppen = OrderedDict()

    def _grp(key, titel, sub, icon, url, wide):
        if key not in gruppen:
            gruppen[key] = {'titel': titel, 'sub': sub, 'icon': icon, 'url': url,
                            'wide': wide, 'pendenzen': [], 'min_faellig': None}
        return gruppen[key]

    for p in offene:
        if p.vertrag_id:
            v = p.vertrag
            obj = (v.einheit.bezeichnung if v and v.einheit_id else '')
            strasse = (v.einheit.liegenschaft.strasse if v and v.einheit_id and v.einheit.liegenschaft_id else '')
            titel = (f"{strasse} · {obj}".strip(' ·') or f"Vertrag #{p.vertrag_id}")
            g = _grp(f"v{p.vertrag_id}", titel,
                     (v.mieter.display_name if v and v.mieter_id else ''),
                     'fa-right-from-bracket', f'/neu/vertraege/{p.vertrag_id}/', True)
        elif p.liegenschaft_id:
            g = _grp(f"l{p.liegenschaft_id}", p.liegenschaft.strasse, p.liegenschaft.ort,
                     'fa-building', f'/neu/liegenschaften/{p.liegenschaft_id}/', True)
        else:
            g = _grp('allgemein', 'Allgemein', '', 'fa-list-check', None, False)
        g['pendenzen'].append(p)
        if p.faellig_am and (g['min_faellig'] is None or p.faellig_am < g['min_faellig']):
            g['min_faellig'] = p.faellig_am

    # Gruppen nach frühester Fälligkeit sortieren, „Allgemein" ans Ende
    from datetime import date as _date
    gruppen_liste = sorted(
        gruppen.values(),
        key=lambda g: (g['titel'] == 'Allgemein', g['min_faellig'] or _date.max))

    liegenschaften = Liegenschaft.objects.order_by('strasse')
    from django.contrib import messages
    return render(request, 'fw/pendenzen.html', {
        **basis, 'nav': 'pendenzen', 'auto': auto,
        'offene': offene, 'gruppen': gruppen_liste, 'erledigte': erledigte,
        'liegenschaften': liegenschaften, 'heute': heute,
        'kategorien': Pendenz.KATEGORIE_CHOICES,
        'meldung': list(messages.get_messages(request)),
    })


def _art_aus_text(text):
    """Zieht die erste Gesetzesreferenz (z. B. 'Art. 257d OR') aus einem Text."""
    import re
    m = re.search(r'Art\.\s*\d+[a-z]?(?:\s*Abs\.\s*\d+)?\s*OR', text or '')
    return m.group(0) if m else ''


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_fristen(request):
    """Fristen-Center: alle datierten, offenen Fristen chronologisch gebündelt —
    Kündigungstermine, Anfechtungs-/Zahlungsfristen (257d/270b/271), Wartung,
    Referenzzins, befristete Vertragsenden. Zeitfenster: überfällig / diese Woche /
    dieser Monat / später. Jede Frist verlinkt aufs betroffene Objekt."""
    from core.models import Pendenz
    from datetime import timedelta
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.now().date()

    pq = (Pendenz.objects.filter(erledigt=False, faellig_am__isnull=False)
          .select_related('liegenschaft', 'vertrag__mieter', 'vertrag__einheit__liegenschaft'))
    if aktive_lg:
        pq = pq.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg)
                       | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    nur_frist = request.GET.get('nur') == 'frist'
    if nur_frist:
        pq = pq.filter(kategorie='frist')

    eintraege = []
    for p in pq.order_by('faellig_am'):
        url, label, wide = _pendenz_ziel(p)
        if p.vertrag_id and p.vertrag:
            bezug = p.vertrag.mieter.display_name if p.vertrag.mieter_id else ''
            if p.vertrag.einheit_id:
                bezug = f"{p.vertrag.einheit.liegenschaft.strasse} · {bezug}" if p.vertrag.einheit.liegenschaft_id else bezug
        elif p.liegenschaft_id:
            bezug = f"{p.liegenschaft.strasse}, {p.liegenschaft.ort}"
        else:
            bezug = ''
        eintraege.append({
            'p': p, 'faellig': p.faellig_am, 'titel': p.titel, 'bezug': bezug,
            'tage': (p.faellig_am - heute).days, 'art': _art_aus_text(p.beschreibung),
            'url': url, 'label': label or 'Öffnen', 'wide': wide,
        })

    # Zeitfenster-Buckets
    grenze_woche = heute + timedelta(days=7)
    grenze_monat = heute + timedelta(days=30)
    buckets = [
        {'key': 'ueberfaellig', 'titel': 'Überfällig', 'icon': 'fa-triangle-exclamation',
         'cls': 'text-rose-600', 'items': [e for e in eintraege if e['faellig'] < heute]},
        {'key': 'woche', 'titel': 'Diese Woche', 'icon': 'fa-calendar-day',
         'cls': 'text-amber-600', 'items': [e for e in eintraege if heute <= e['faellig'] <= grenze_woche]},
        {'key': 'monat', 'titel': 'Diesen Monat', 'icon': 'fa-calendar-week',
         'cls': 'text-indigo-600', 'items': [e for e in eintraege if grenze_woche < e['faellig'] <= grenze_monat]},
        {'key': 'spaeter', 'titel': 'Später', 'icon': 'fa-calendar',
         'cls': 'text-slate-500', 'items': [e for e in eintraege if e['faellig'] > grenze_monat]},
    ]
    from core.services.ical import feed_token
    return render(request, 'fw/fristen.html', {
        **basis, 'nav': 'fristen', 'buckets': buckets, 'heute': heute,
        'gesamt': len(eintraege), 'nur_frist': nur_frist,
        'ueberfaellig_n': len(buckets[0]['items']),
        'feed_token': feed_token(),
    })


def _offene_fristen_pendenzen(aktive_lg=None):
    """Alle offenen, datierten Pendenzen (optional auf eine Liegenschaft gefiltert)."""
    from core.models import Pendenz
    pq = (Pendenz.objects.filter(erledigt=False, faellig_am__isnull=False)
          .select_related('liegenschaft', 'vertrag__mieter'))
    if aktive_lg:
        pq = pq.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg)
                       | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    return pq.order_by('faellig_am')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_fristen_ical(request):
    """Fristen als .ics herunterladen (zum Import in den Kalender)."""
    from django.http import HttpResponse
    from core.services.ical import build_ics, fristen_events
    basis = _global_filter(request)
    ics = build_ics(fristen_events(_offene_fristen_pendenzen(basis['aktive_lg'])))
    resp = HttpResponse(ics, content_type='text/calendar; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="swissimmo-fristen.ics"'
    return resp


def fristen_ical_feed(request):
    """Öffentlicher, abonnierbarer iCal-Feed (Token-gesichert, ohne Login) —
    damit Outlook/Google/Apple Calendar die Fristen automatisch synchronisieren."""
    from django.http import HttpResponse, HttpResponseForbidden
    from core.services.ical import build_ics, fristen_events, token_gueltig
    if not token_gueltig(request.GET.get('token')):
        return HttpResponseForbidden("Ungültiger oder fehlender Token.")
    ics = build_ics(fristen_events(_offene_fristen_pendenzen()))
    resp = HttpResponse(ics, content_type='text/calendar; charset=utf-8')
    resp['Content-Disposition'] = 'inline; filename="swissimmo-fristen.ics"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_pendenz_neu(request):
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.models import Pendenz
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_pendenzen')
    titel = (request.POST.get('titel') or '').strip()
    if not titel:
        messages.error(request, "Titel fehlt.")
        return redirect('fw_pendenzen')
    faellig = None
    if request.POST.get('faellig_am'):
        try:
            faellig = date.fromisoformat(request.POST['faellig_am'])
        except Exception:
            faellig = None
    lg_id = request.POST.get('liegenschaft_id') or None
    Pendenz.objects.create(
        titel=titel,
        beschreibung=(request.POST.get('beschreibung') or '').strip(),
        kategorie=request.POST.get('kategorie', 'aufgabe'),
        faellig_am=faellig,
        liegenschaft_id=lg_id if lg_id else None,
        erstellt_von=request.user,
    )
    log_aktion(request, "Pendenz erstellt", titel, '')
    messages.success(request, f"✅ Pendenz „{titel}“ erfasst.")
    return redirect('fw_pendenzen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_pendenz_toggle(request, pk):
    from django.shortcuts import redirect
    from core.models import Pendenz
    if request.method != 'POST':
        return redirect('fw_pendenzen')
    p = get_object_or_404(Pendenz, id=pk)
    p.erledigt = not p.erledigt
    p.erledigt_am = timezone.now().date() if p.erledigt else None
    p.save()
    return redirect('fw_pendenzen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_pendenz_loeschen(request, pk):
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.models import Pendenz
    if request.method != 'POST':
        return redirect('fw_pendenzen')
    p = get_object_or_404(Pendenz, id=pk)
    from core.auth import log_aktion
    titel = p.titel
    p.delete()
    log_aktion(request, "Pendenz gelöscht", titel, '')
    messages.success(request, "Pendenz gelöscht.")
    return redirect('fw_pendenzen')


# ============================================================
# MAHN-HISTORIE (revisionssicher) + Mahngebühren
# ============================================================

MAHN_GEBUEHR = {1: Decimal('0.00'), 2: Decimal('20.00'), 3: Decimal('40.00')}


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_mahnung_erfassen(request):
    """Erfasst einen revisionssicheren Mahnschritt in der Historie und legt
    optional eine Mahngebühr als Debitorenrechnung an."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Mahnung, DebitorenRechnung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_mahnwesen')

    rechnung = get_object_or_404(DebitorenRechnung.objects.select_related('vertrag__mieter'),
                                 id=request.POST.get('rechnung_id'))
    try:
        stufe = int(request.POST.get('stufe') or 1)
    except ValueError:
        stufe = 1
    stufe = min(max(stufe, 1), 3)

    try:
        gebuehr = Decimal(str(request.POST.get('gebuehr') or MAHN_GEBUEHR.get(stufe, Decimal('0'))).replace(',', '.'))
    except Exception:
        gebuehr = MAHN_GEBUEHR.get(stufe, Decimal('0.00'))

    heute = timezone.now().date()
    m = Mahnung.objects.create(
        debitoren_rechnung=rechnung, vertrag=rechnung.vertrag, stufe=stufe,
        datum=heute, betrag_offen=rechnung.offener_betrag, gebuehr=gebuehr,
        versandart=request.POST.get('versandart', 'manuell'),
        erstellt_von=request.user,
    )

    # Mahngebühr als separate Debitorenrechnung (falls > 0)
    if gebuehr > 0 and rechnung.vertrag_id:
        DebitorenRechnung.objects.create(
            vertrag=rechnung.vertrag,
            liegenschaft=rechnung.liegenschaft or (rechnung.vertrag.einheit.liegenschaft if rechnung.vertrag.einheit_id else None),
            titel=f"Mahngebühr {stufe}. Mahnung",
            beschreibung=f"Mahngebühr zu: {rechnung.titel}",
            datum=heute, faellig_am=heute + _timedelta(days=30),
            betrag=gebuehr, status='offen',
        )

    log_aktion(request, f"{stufe}. Mahnung erfasst",
               rechnung.vertrag.mieter.display_name if rechnung.vertrag_id else rechnung.titel,
               f"offen CHF {rechnung.offener_betrag}, Gebühr CHF {gebuehr}")
    messages.success(request,
        f"✅ {stufe}. Mahnung erfasst" + (f" · Mahngebühr CHF {gebuehr} gestellt." if gebuehr > 0 else "."))
    ziel = '/neu/mahnwesen/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_mahnlauf(request):
    """Sammel-Mahnlauf über ALLE fälligen offenen Debitoren (statt einzeln).
    Erzeugt Mahnungen je Stufe (idempotent), stellt Mahngebühr + optional
    Verzugszins und verschickt Zahlungserinnerungen per E-Mail."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    from core.services.automation import run_mahnlauf
    if request.method != 'POST':
        return redirect('fw_mahnwesen')
    basis = _global_filter(request)
    mit_zins = request.POST.get('mit_zins') == 'on'
    send_email = request.POST.get('kein_versand') != 'on'
    res = run_mahnlauf(aktive_lg=basis['aktive_lg'], send_email=send_email,
                       mit_zins=mit_zins, user=request.user)
    log_aktion(request, "Mahnlauf ausgeführt", "Sammellauf",
               f"{res['gemahnt']} gemahnt, {res['emails']} E-Mails, Gebühren CHF {res['gebuehren']}, Zins CHF {res['zins']}")
    if res['gemahnt']:
        teile = [f"{res['gemahnt']} Mahnung(en) erstellt"]
        if send_email:
            teile.append(f"{res['emails']} E-Mail(s) versandt")
        if res['gebuehren'] > 0:
            teile.append(f"Gebühren CHF {res['gebuehren']}")
        if res['zins'] > 0:
            teile.append(f"Verzugszins CHF {res['zins']}")
        messages.success(request, "✅ Mahnlauf: " + ", ".join(teile) + ".")
    else:
        messages.success(request, "Mahnlauf: keine neuen Mahnungen fällig — alles aktuell.")
    ziel = '/neu/mahnwesen/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return redirect(ziel)


# ============================================================
# QR-BELEG FÜR AD-HOC-DEBITORENRECHNUNG (z.B. Sonnerie, Ersatz)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_debitor_qr_pdf(request, pk):
    """QR-Einzahlungsschein (A4) für eine beliebige Debitorenrechnung —
    ermöglicht Ad-hoc-Weiterverrechnungen (Schlüssel, Sonnerie, Ersatz …)
    mit QR-Rechnung inkl. QRR-Referenz."""
    from django.http import HttpResponse
    from core.services.debitor_qr import generate_debitor_qr_pdf

    r = get_object_or_404(DebitorenRechnung.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft'), id=pk)
    pdf = generate_debitor_qr_pdf(r)
    if pdf is None:
        return HttpResponse("Keine IBAN hinterlegt (Liegenschaft oder Verwaltung).", status=400)
    # Auto-Ablage in die Akte (pro Rechnung eigener Titel) -> Portal
    if r.vertrag_id:
        from core.services.ablage import ablegen
        ablegen(pdf, f"Rechnung: {r.titel} (#{r.id})", kategorie='korrespondenz', vertrag=r.vertrag, dedup=True)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Rechnung_{r.id}.pdf"'
    return resp


# ============================================================
# CREATE-/ACTION-VIEWS: alles in /neu/ (ersetzt /app/-Links)
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kreditor_neu(request):
    """Kreditorenrechnung erfassen (Status neu → im Kreditoren-Tab freigeben)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, Buchungskonto
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')

    def _dec(name):
        raw = (request.POST.get(name) or '').strip().replace(',', '.')
        try:
            return Decimal(raw) if raw else None
        except Exception:
            return None

    lieferant = (request.POST.get('lieferant') or '').strip()
    betrag = _dec('betrag')
    if not lieferant or not betrag or betrag <= 0:
        messages.error(request, "Lieferant und Betrag (> 0) sind erforderlich.")
        return redirect('fw_kreditoren')

    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id')).first()
    konto = Buchungskonto.objects.filter(id=request.POST.get('konto_id')).first() if request.POST.get('konto_id') else None
    kr = KreditorenRechnung.objects.create(
        lieferant=lieferant, betrag=betrag, mwst_satz=(_dec('mwst_satz') or Decimal('0.0')),
        liegenschaft=lg, konto=konto,
        datum=(date.fromisoformat(request.POST['datum']) if request.POST.get('datum') else timezone.now().date()),
        faellig_am=(date.fromisoformat(request.POST['faellig_am']) if request.POST.get('faellig_am') else None),
        referenz=(request.POST.get('referenz') or '').strip(),
        is_hnk_relevant=request.POST.get('is_hnk_relevant') == 'on',
        status='neu',
    )
    if request.FILES.get('beleg_scan'):
        kr.beleg_scan = request.FILES['beleg_scan']
        kr.save()
    log_aktion(request, "Kreditorenrechnung erfasst", lieferant, f"CHF {betrag}")
    messages.success(request, f"✅ Kreditorenrechnung '{lieferant}' über CHF {betrag} erfasst (Status: Neu — bitte freigeben).")
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_kreditor_freigeben(request, pk):
    """Kreditorenrechnung freigeben: bucht Aufwand (netto) an Kreditoren (2000)
    + Vorsteuer-Split (1170). Erfordert ein Aufwandskonto."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, Buchungskonto, Buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    k = get_object_or_404(KreditorenRechnung, id=pk)
    if k.status != 'neu':
        messages.info(request, "Rechnung ist bereits freigegeben oder bezahlt.")
        return redirect('fw_kreditoren')

    # Aufwandskonto zuweisen (aus Formular oder bestehendes)
    if request.POST.get('konto_id'):
        k.konto = Buchungskonto.objects.filter(id=request.POST['konto_id']).first()
    if not k.konto:
        messages.error(request, "Bitte zuerst ein Aufwandskonto zuweisen (in der Zeile wählen).")
        return redirect('fw_kreditoren')

    with transaction.atomic():
        k.status = 'freigegeben'
        k.save()
        from finance.booking import buche
        datum_b = k.datum or timezone.now().date()
        brutto = k.betrag or Decimal('0.00')
        vorsteuer = Decimal('0.00')
        if (k.mwst_satz or 0) > 0:
            satz = k.mwst_satz
            vorsteuer = (brutto * satz / (Decimal('100') + satz)).quantize(Decimal('0.01'))
            k.mwst_betrag = vorsteuer
            k.save(update_fields=['mwst_betrag'])
        netto = brutto - vorsteuer
        buche(k.konto, "2000", netto, f"Rechnung {k.lieferant} - {k.referenz}",
              datum=datum_b, liegenschaft=k.liegenschaft, kreditor=k, user=request.user)
        if vorsteuer > 0:
            buche("1170", "2000", vorsteuer, f"Vorsteuer {k.mwst_satz}% {k.lieferant}",
                  datum=datum_b, liegenschaft=k.liegenschaft, kreditor=k, user=request.user)
    log_aktion(request, "Kreditorenrechnung freigegeben", k.lieferant, f"CHF {k.betrag}")
    messages.success(request, f"✅ '{k.lieferant}' freigegeben und verbucht.")
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dienstleister_neu(request):
    """Handwerker / Dienstleister erfassen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Handwerker
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_dienstleister')
    firma = (request.POST.get('firma') or '').strip()
    if not firma:
        messages.error(request, "Firma ist erforderlich.")
        return redirect('fw_dienstleister')
    Handwerker.objects.create(
        firma=firma, branche=request.POST.get('branche', 'allgemein'),
        kontaktperson=(request.POST.get('kontaktperson') or '').strip(),
        email=(request.POST.get('email') or '').strip(),
        telefon=(request.POST.get('telefon') or '').strip(),
    )
    log_aktion(request, "Dienstleister erfasst", firma, '')
    messages.success(request, f"✅ Dienstleister '{firma}' erfasst.")
    return redirect('fw_dienstleister')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_asset_neu(request):
    """Gerät / Asset erfassen (Portfolio)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet, Einheit
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_assets')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id')).first()
    if not lg:
        messages.error(request, "Liegenschaft ist erforderlich.")
        return redirect('fw_assets')
    g = Geraet.objects.create(
        liegenschaft=lg,
        einheit=Einheit.objects.filter(id=request.POST.get('einheit_id')).first() if request.POST.get('einheit_id') else None,
        kategorie=request.POST.get('kategorie', 'sonstiges'),
        sonstiges_bezeichnung=(request.POST.get('sonstiges_bezeichnung') or '').strip(),
        marke=(request.POST.get('marke') or '').strip(),
        modell=(request.POST.get('modell') or '').strip(),
        installations_datum=(date.fromisoformat(request.POST['installations_datum']) if request.POST.get('installations_datum') else None),
        garantie_bis=(date.fromisoformat(request.POST['garantie_bis']) if request.POST.get('garantie_bis') else None),
    )
    log_aktion(request, "Asset erfasst", f"{g.marke} {g.modell}", str(lg))
    messages.success(request, "✅ Asset / Gerät erfasst.")
    ziel = '/neu/assets/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dokument_neu(request):
    """Dokument hochladen (Portfolio-Ablage)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Dokument as PDokument, Einheit
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_dokumente')
    if not request.FILES.get('datei'):
        messages.error(request, "Bitte eine Datei auswählen.")
        return redirect('fw_dokumente')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id')).first()
    PDokument.objects.create(
        titel=(request.POST.get('titel') or request.FILES['datei'].name).strip(),
        kategorie=request.POST.get('kategorie', 'sonstiges'),
        liegenschaft=lg,
        einheit=Einheit.objects.filter(id=request.POST.get('einheit_id')).first() if request.POST.get('einheit_id') else None,
        datei=request.FILES['datei'],
    )
    log_aktion(request, "Dokument hochgeladen", request.POST.get('titel', ''), '')
    messages.success(request, "✅ Dokument hochgeladen.")
    ziel = '/neu/dokumente/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_nebenkosten_neu(request):
    """Neue Nebenkosten-Abrechnungsperiode anlegen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import AbrechnungsPeriode
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_nebenkosten')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id')).first()
    bez = (request.POST.get('bezeichnung') or '').strip()
    try:
        start = date.fromisoformat(request.POST.get('start_datum'))
        ende = date.fromisoformat(request.POST.get('ende_datum'))
    except Exception:
        start = ende = None
    if not lg or not bez or not start or not ende:
        messages.error(request, "Liegenschaft, Bezeichnung, Start- und Enddatum sind erforderlich.")
        return redirect('fw_nebenkosten')
    p = AbrechnungsPeriode.objects.create(liegenschaft=lg, bezeichnung=bez, start_datum=start, ende_datum=ende)
    log_aktion(request, "Abrechnungsperiode erstellt", bez, str(lg))
    messages.success(request, f"✅ Abrechnungsperiode '{bez}' erstellt.")
    return redirect(f'/neu/nebenkosten/{p.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_buchung_neu(request):
    """Manuelle Buchung erfassen (Soll an Haben)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_buchhaltung')
    soll = Buchungskonto.objects.filter(id=request.POST.get('soll_konto_id')).first()
    haben = Buchungskonto.objects.filter(id=request.POST.get('haben_konto_id')).first()
    try:
        betrag = Decimal(str(request.POST.get('betrag') or '0').replace(',', '.'))
    except Exception:
        betrag = Decimal('0')
    text = (request.POST.get('beleg_text') or '').strip()
    if not soll or not haben or betrag <= 0 or not text:
        messages.error(request, "Soll-, Haben-Konto, Betrag (> 0) und Belegtext sind erforderlich.")
        return redirect('fw_buchhaltung')
    if soll.id == haben.id:
        messages.error(request, "Soll- und Haben-Konto müssen unterschiedlich sein.")
        return redirect('fw_buchhaltung')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id')).first() if request.POST.get('liegenschaft_id') else None
    Buchung.objects.create(
        datum=(date.fromisoformat(request.POST['datum']) if request.POST.get('datum') else timezone.now().date()),
        beleg_text=text, liegenschaft=lg, soll_konto=soll, haben_konto=haben,
        betrag=betrag, erstellt_von=request.user)
    log_aktion(request, "Manuelle Buchung", text, f"{soll.nummer}/{haben.nummer} CHF {betrag}")
    messages.success(request, f"✅ Buchung erfasst: {soll.nummer} an {haben.nummer} · CHF {betrag}.")
    return redirect('fw_buchhaltung')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kommunikation_senden(request):
    """Verschickt die verfasste Mitteilung per E-Mail an die gewählten Mieter."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kommunikation')
    betreff = (request.POST.get('betreff') or 'Mitteilung').strip()
    text = (request.POST.get('text') or '').strip()
    ids = request.POST.getlist('empfaenger_id')
    if not text or not ids:
        messages.error(request, "Text und mindestens ein Empfänger erforderlich.")
        return redirect('fw_kommunikation')
    gesendet = 0
    for mid in ids:
        m = Mieter.objects.filter(id=mid).first()
        if m and m.email:
            if send_ticket_email(m.email, betreff, text):
                gesendet += 1
    log_aktion(request, "Rundschreiben per E-Mail", betreff, f"{gesendet} Empfänger")
    messages.success(request, f"✅ {gesendet} E-Mail(s) versendet." if gesendet else "Keine E-Mail versendet (fehlende Adressen).")
    return redirect('fw_kommunikation')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_serienbrief_pdf(request):
    """Erzeugt ein Sammel-PDF (ein Brief pro Empfänger, Fenstercouvert) für
    einen echten postalischen Rundbrief an alle gewählten Mieter."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from core.auth import log_aktion
    from core.services.serienbrief import generate_serienbrief_pdf
    from core.services.ablage import ablegen
    if request.method != 'POST':
        return redirect('fw_kommunikation')
    betreff = (request.POST.get('betreff') or 'Mitteilung').strip()
    text = (request.POST.get('text') or '').strip()
    ids = request.POST.getlist('empfaenger_id')
    if not text or not ids:
        messages.error(request, "Text und mindestens ein Empfänger erforderlich.")
        return redirect('fw_kommunikation')

    vw = Verwaltung.objects.first()
    absender = {
        'firma': vw.firma if vw else 'Meine Verwaltung',
        'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
    }

    # Empfänger auflösen (Adresse + Objekt/Liegenschaft aus aktivem Vertrag).
    # Bei 2-Personen-Verträgen werden BEIDE Namen adressiert; sind beide Personen
    # gewählt, entsteht trotzdem nur EIN Brief (Dedup über Vertrag).
    from django.db.models import Q as _Q
    empfaenger = []
    verarbeitete_vertraege = set()
    for mid in ids:
        m = Mieter.objects.filter(id=mid).first()
        if not m:
            continue
        v = (Mietvertrag.objects.filter(_Q(mieter=m) | _Q(mitmieter=m), status='aktiv')
             .select_related('einheit__liegenschaft', 'mieter', 'mitmieter').first())
        if v:
            if v.id in verarbeitete_vertraege:
                continue  # zweite Person desselben Vertrags → kein Doppelbrief
            verarbeitete_vertraege.add(v.id)
            lg = v.einheit.liegenschaft if v.einheit_id else None
            prim = v.mieter or m
            zweit = (v.mitmieter.display_name if v.mitmieter else (v.mitmieter_name or '')).strip()
            name = prim.display_name + (f" & {zweit}" if zweit else '')
            empfaenger.append({
                '_mieter_id': prim.id, '_vertrag_id': v.id,
                'name': name, 'anrede': prim.anrede or '',
                'strasse': prim.strasse or (lg.strasse if lg else ''),
                'plz': prim.plz or (lg.plz if lg else ''),
                'ort': prim.ort or (lg.ort if lg else ''),
                'objekt': (f"{lg.strasse}, {lg.ort} · {v.einheit.bezeichnung}" if lg else ''),
                'liegenschaft': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else ''),
            })
        else:
            empfaenger.append({
                '_mieter_id': m.id, '_vertrag_id': None,
                'name': m.display_name, 'anrede': m.anrede or '',
                'strasse': m.strasse or '', 'plz': m.plz or '', 'ort': m.ort or '',
                'objekt': '', 'liegenschaft': '',
            })
    if not empfaenger:
        messages.error(request, "Keine gültigen Empfänger gefunden.")
        return redirect('fw_kommunikation')

    logo_path = None
    if vw and getattr(vw, 'logo', None):
        try:
            logo_path = vw.logo.path
        except Exception:
            logo_path = None

    pdf = generate_serienbrief_pdf(absender, betreff, text, empfaenger, logo_path=logo_path)

    # Auto-Ablage: pro Empfänger eine eigene (einseitige) Brief-Kopie in dessen
    # Akte ablegen — erscheint automatisch im Mieterportal (portal-sichtbar).
    abgelegt = 0
    for e in empfaenger:
        m = Mieter.objects.filter(id=e.get('_mieter_id')).first()
        if not m:
            continue
        v = Mietvertrag.objects.filter(id=e.get('_vertrag_id')).first() if e.get('_vertrag_id') else None
        einzel = generate_serienbrief_pdf(absender, betreff, text, [e], logo_path=logo_path)
        # Ablage am Vertrag (erscheint im Portal beider Personen) + am Hauptmieter
        if ablegen(einzel, f"Brief: {betreff}", kategorie='korrespondenz', vertrag=v, mieter=m):
            abgelegt += 1

    log_aktion(request, "Serienbrief-PDF erzeugt", betreff, f"{len(empfaenger)} Empfänger · {abgelegt} abgelegt")
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="serienbrief_{date.today().isoformat()}.pdf"'
    return resp
