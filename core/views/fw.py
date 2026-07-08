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
from django.db.models import Q, Sum
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from core.auth import rolle_erforderlich, TEAM_ROLLEN, SCHREIB_ROLLEN, ROLLE_VERWALTUNG
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
    }
    return render(request, 'fw/debitoren.html', context)


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
        qs = qs.filter(vertraege__einheit__liegenschaft=aktive_lg).distinct()

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
        vertrag_je_mieter.setdefault(v.mieter_id, []).append(v)

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

    dok20 = dokumente[:20]
    tab_liste = [
        ('objekte', 'Objekte', len(einheiten_rows)),
        ('finanzen', 'Finanzen', None),
        ('unterhalt', 'Unterhalt', unterhalt.count() or None),
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
        'perioden': perioden,
        'tab_liste': tab_liste,
    })


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

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('finanzen', 'Finanzen', len(offene) or None),
        ('mietzins', 'Mietzins', anpassungen.count() or None),
        ('dokumente', 'Dokumente', None),
    ]
    return render(request, 'fw/vertrag_detail.html', {
        **basis, 'nav': 'vertraege', 'v': v,
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
        'tab_liste': tab_liste,
    })


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
            log_aktion(request, "Vertragsstatus geändert", str(v.mieter), erlaubt[neu])
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

    context = {
        **basis, 'nav': 'mahnwesen', 'rows': rows,
        'stufe_filter': stufe_filter, 'stufe_chips': stufe_chips,
        'total': total,
        'mahnstufen': MAHN_STUFEN,
        'counts': counts, 'summe': summe,
        'anzahl_total': counts[1] + counts[2] + counts[3],
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
        try:
            konto_bank = Buchungskonto.objects.get(nummer="1020")
            konto_deb = Buchungskonto.objects.get(nummer="1100")
            Buchung.objects.create(
                datum=heute, beleg_text=f"Bankabgleich {vertrag.mieter} - {rechnung.titel}",
                liegenschaft=vertrag.einheit.liegenschaft,
                soll_konto=konto_bank, haben_konto=konto_deb, betrag=betrag,
                zahlungseingang=zahlung, erstellt_von=request.user,
            )
        except Buchungskonto.DoesNotExist:
            pass

    log_aktion(request, "Zahlung via Bankabgleich verbucht", str(vertrag),
               f"CHF {betrag} auf {rechnung.titel}")
    messages.success(request, f"✅ CHF {betrag} verbucht — {vertrag.mieter.display_name} ({rechnung.titel}).")
    from django.shortcuts import redirect as _r
    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'
    return _r(ziel)


# ============================================================
# PERSON-DETAIL (Mieter) — in der neuen Shell
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_person_detail(request, pk):
    from rentals.models import Dokument as RentalsDokument
    from tickets.models import SchadenMeldung
    m = get_object_or_404(Mieter, id=pk)
    basis = _global_filter(request)

    vertraege = (m.vertraege.select_related('einheit__liegenschaft').order_by('-beginn'))
    aktive = [v for v in vertraege if v.status == 'aktiv']

    offene = (DebitorenRechnung.objects
              .filter(vertrag__mieter=m, status__in=['offen', 'teilbezahlt'])
              .select_related('vertrag').order_by('faellig_am'))
    total_offen = sum((r.offener_betrag for r in offene), Decimal('0.00'))

    zahlungen = (Zahlungseingang.objects.filter(vertrag__mieter=m, status='verbucht')
                 .order_by('-datum_eingang')[:15])
    dokumente = RentalsDokument.objects.filter(mieter=m).order_by('-datum')[:15]

    vertrag_rows = []
    for v in vertraege:
        label, cls = VERTRAG_PILL.get(v.status, (v.status, 'bg-slate-100 text-slate-500'))
        vertrag_rows.append({'v': v, 'label': label, 'cls': cls,
                             'brutto': (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0'))})

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('vertraege', 'Verträge', vertraege.count() or None),
        ('finanzen', 'Finanzen', offene.count() or None),
        ('dokumente', 'Dokumente', dokumente.count() or None),
    ]
    return render(request, 'fw/person_detail.html', {
        **basis, 'nav': 'personen', 'm': m,
        'vertrag_rows': vertrag_rows,
        'anzahl_aktive': len(aktive),
        'brutto_monat': sum((r['brutto'] for r in vertrag_rows if r['v'].status == 'aktiv'), Decimal('0.00')),
        'offene': offene, 'total_offen': total_offen,
        'zahlungen': zahlungen, 'dokumente': dokumente,
        'telefon': m.mobile or m.telefon_privat or m.telefon_geschaeft,
        'tab_liste': tab_liste,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_person_form(request, pk=None):
    """Person (Mieter/Kontakt) erfassen oder bearbeiten — Fairwalter-Stil."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    m = get_object_or_404(Mieter, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
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
        obj.save()
        log_aktion(request, "Person bearbeitet" if pk else "Person erstellt", obj.display_name, '')
        messages.success(request, f"✅ {obj.display_name} gespeichert.")
        return redirect(f'/neu/personen/{obj.id}/')

    return render(request, 'fw/person_form.html', {
        **basis, 'nav': 'personen', 'm': m,
        'ist_neu': m is None,
    })


# ============================================================
# ETAPPE D: KREDITOREN (Rechnungseingang -> Freigabe -> Zahlung)
# ============================================================

KRED_PILL = {
    'neu':         ('Neu / Prüfen', 'bg-amber-50 text-amber-700'),
    'freigegeben': ('Freigegeben',  'bg-sky-50 text-sky-700'),
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
        faellig = k.faellig_am
        if k.status == 'freigegeben':
            total_offen += betrag
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
            'kann_bezahlen': k.status == 'freigegeben',
        })

    status_chips = [('', 'Alle')] + [(k, v[0]) for k, v in KRED_PILL.items() if k != 'storniert']

    return render(request, 'fw/kreditoren.html', {
        **basis, 'nav': 'kreditoren', 'rows': rows,
        'status_filter': status_filter, 'status_chips': status_chips,
        'total_offen': total_offen, 'total_neu': total_neu, 'anzahl_neu': anzahl_neu,
        'anzahl': len(rows),
        'darf_bezahlen': hat_rolle(request.user, VERWALTUNGS_ROLLEN),
        'meldung': list(messages.get_messages(request)),
    })


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

    k = get_object_or_404(KreditorenRechnung, id=request.POST.get('rechnung_id'))
    if k.status == 'bezahlt':
        messages.error(request, "Diese Rechnung ist bereits bezahlt.")
        return redirect('fw_kreditoren')
    if k.status != 'freigegeben':
        messages.error(request, "Nur freigegebene Rechnungen können bezahlt werden.")
        return redirect('fw_kreditoren')

    with transaction.atomic():
        k.status = 'bezahlt'
        k.save()
        try:
            konto_bank = Buchungskonto.objects.get(nummer="1020")
            konto_kred = Buchungskonto.objects.get(nummer="2000")
            Buchung.objects.create(
                datum=timezone.now().date(),
                beleg_text=f"Zahlung {k.lieferant} - {k.referenz}",
                liegenschaft=k.liegenschaft,
                soll_konto=konto_kred, haben_konto=konto_bank,
                betrag=k.betrag or Decimal('0.00'),
                kreditoren_rechnung=k, erstellt_von=request.user,
            )
        except Buchungskonto.DoesNotExist:
            pass

    log_aktion(request, "Kreditorenrechnung bezahlt (Bankabgleich)",
               k.lieferant or f"Rechnung #{k.id}", f"CHF {k.betrag}")
    messages.success(request, f"✅ CHF {k.betrag} an {k.lieferant or 'Lieferant'} bezahlt.")
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
    return render(request, 'fw/schaeden.html', {
        **basis, 'nav': 'schadensfaelle', 'rows': rows,
        'status_filter': status_filter, 'status_chips': chips, 'q': q,
        'anzahl': len(rows), 'offen': offen, 'in_arbeit': in_arbeit,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_schaden_detail(request, pk):
    from tickets.models import SchadenMeldung
    t = get_object_or_404(
        SchadenMeldung.objects.select_related('liegenschaft', 'betroffene_einheit', 'gemeldet_von'), id=pk)
    basis = _global_filter(request)

    s_label, s_cls = TICKET_PILL.get(t.status, (t.status, 'bg-slate-100 text-slate-500'))
    p_label, p_cls = PRIO_PILL.get((t.prioritaet or '').lower(), (t.prioritaet or 'Mittel', 'bg-slate-100 text-slate-500'))
    nachrichten = t.nachrichten.order_by('erstellt_am')
    auftraege = t.handwerker_auftraege.select_related('handwerker').order_by('-beauftragt_am')
    melder = (t.gemeldet_von.display_name if t.gemeldet_von_id
              else f"{t.melder_vorname or ''} {t.melder_nachname or ''}".strip() or '—')

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('verlauf', 'Verlauf', nachrichten.count() or None),
        ('handwerker', 'Handwerker', auftraege.count() or None),
    ]
    return render(request, 'fw/schaden_detail.html', {
        **basis, 'nav': 'schadensfaelle', 't': t,
        's_label': s_label, 's_cls': s_cls, 'p_label': p_label, 'p_cls': p_cls,
        'nachrichten': nachrichten, 'auftraege': auftraege, 'melder': melder,
        'tab_liste': tab_liste,
    })


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
    })


# ============================================================
# ETAPPE D: BUCHHALTUNG (Erfolgsrechnung + Journal)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_buchhaltung(request):
    from finance.models import Buchung, Buchungskonto
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    # --- ERFOLGSRECHNUNG (Storno-Paare heben sich selbst auf, nicht filtern) ---
    qs = Buchung.objects.all()
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    konten = Buchungskonto.objects.filter(typ__in=['ertrag', 'aufwand'])

    ertraege, aufwaende = [], []
    total_ertrag = total_aufwand = Decimal('0.00')
    for k in konten:
        soll = qs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        haben = qs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        if k.typ == 'ertrag':
            saldo = haben - soll
            if saldo:
                ertraege.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_ertrag += saldo
        else:
            saldo = soll - haben
            if saldo:
                aufwaende.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_aufwand += saldo
    ertraege.sort(key=lambda x: x['nummer'])
    aufwaende.sort(key=lambda x: x['nummer'])
    erfolg = total_ertrag - total_aufwand

    # --- BUCHUNGSJOURNAL (letzte 60) ---
    journal = (qs.select_related('soll_konto', 'haben_konto', 'liegenschaft')
               .order_by('-datum', '-id')[:60])

    tab_liste = [
        ('erfolg', 'Erfolgsrechnung', None),
        ('journal', 'Journal', journal.count() or None),
    ]
    return render(request, 'fw/buchhaltung.html', {
        **basis, 'nav': 'buchhaltung',
        'ertraege': ertraege, 'aufwaende': aufwaende,
        'total_ertrag': total_ertrag, 'total_aufwand': total_aufwand, 'erfolg': erfolg,
        'journal': journal,
        'tab_liste': tab_liste,
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

    start_date = date(jahr, monat, 1)
    _, last_day = _calendar.monthrange(jahr, monat)
    end_date = date(jahr, monat, last_day)
    titel = f"Miete & NK {monat:02d}/{jahr}"

    try:
        konto_deb = Buchungskonto.objects.get(nummer="1100")
        konto_ertrag = Buchungskonto.objects.get(nummer="3000")
        konto_nk = Buchungskonto.objects.get(nummer="3020")
    except Buchungskonto.DoesNotExist:
        messages.error(request, "Standard-Konten (1100, 3000, 3020) fehlen. Bitte zuerst Kontenplan laden.")
        return redirect(f'/neu/sollstellung/?jahr={jahr}&monat={monat}')

    vertraege = (Mietvertrag.objects.filter(status='aktiv', beginn__lte=end_date)
                 .exclude(ende__lt=start_date).select_related('mieter', 'einheit__liegenschaft'))

    erstellt = 0
    with transaction.atomic():
        for v in vertraege:
            if DebitorenRechnung.objects.filter(vertrag=v, titel=titel).exclude(status='storniert').exists():
                continue
            v_start = max(start_date, v.beginn)
            v_ende = min(end_date, v.ende) if v.ende else end_date
            faktor = Decimal((v_ende - v_start).days + 1) / Decimal(last_day)
            netto = round((v.netto_mietzins or Decimal('0')) * faktor, 2)
            nk = round((v.nebenkosten or Decimal('0')) * faktor, 2)
            if netto + nk <= 0:
                continue
            rechnung = DebitorenRechnung.objects.create(
                vertrag=v, liegenschaft=v.einheit.liegenschaft, einheit=v.einheit,
                titel=titel, betrag=netto + nk, faellig_am=start_date)
            if netto > 0:
                Buchung.objects.create(datum=start_date, beleg_text=f"Mietertrag {v.mieter} - {monat:02d}/{jahr}",
                                       liegenschaft=v.einheit.liegenschaft, soll_konto=konto_deb, haben_konto=konto_ertrag,
                                       betrag=netto, debitoren_rechnung=rechnung, erstellt_von=request.user)
            if nk > 0:
                Buchung.objects.create(datum=start_date, beleg_text=f"NK-Akonto {v.mieter} - {monat:02d}/{jahr}",
                                       liegenschaft=v.einheit.liegenschaft, soll_konto=konto_deb, haben_konto=konto_nk,
                                       betrag=nk, debitoren_rechnung=rechnung, erstellt_von=request.user)
            erstellt += 1

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
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_nebenkosten_detail(request, pk):
    from finance.models import AbrechnungsPeriode, KreditorenRechnung
    p = get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), id=pk)
    basis = _global_filter(request)
    lg = p.liegenschaft

    # HNK-relevante Kreditorenrechnungen dieser Periode
    kosten_rechnungen = (KreditorenRechnung.objects.filter(
        liegenschaft=lg, is_hnk_relevant=True,
        datum__gte=p.start_datum, datum__lte=p.ende_datum).exclude(status='storniert'))
    total_kosten = sum((r.betrag or Decimal('0')) for r in kosten_rechnungen)

    alle_einheiten = lg.einheiten.all() if lg else []
    total_flaeche = sum(e.flaeche_m2 for e in alle_einheiten if e.flaeche_m2) or 1
    tage_periode = (p.ende_datum - p.start_datum).days + 1

    vertraege = (Mietvertrag.objects.filter(einheit__liegenschaft=lg, beginn__lte=p.ende_datum)
                 .exclude(ende__lt=p.start_datum).select_related('mieter', 'einheit')) if lg else []

    abrechnungen = []
    total_akonto = Decimal('0.00')
    for v in vertraege:
        v_start = max(v.beginn, p.start_datum)
        v_ende = min(v.ende, p.ende_datum) if v.ende else p.ende_datum
        tage_bewohnt = (v_ende - v_start).days + 1
        zeit_faktor = Decimal(tage_bewohnt) / Decimal(tage_periode)
        flaeche = v.einheit.flaeche_m2 or 0
        anteil = Decimal(flaeche) / Decimal(total_flaeche)
        mieter_kosten = round(total_kosten * anteil * zeit_faktor, 2)
        monate = round(tage_bewohnt / 30)
        akonto = round((v.nebenkosten or Decimal('0')) * Decimal(monate), 2)
        total_akonto += akonto
        saldo = mieter_kosten - akonto
        abrechnungen.append({
            'v': v, 'mieter': v.mieter.display_name, 'einheit': v.einheit.bezeichnung,
            'flaeche': flaeche, 'tage': tage_bewohnt,
            'kosten': mieter_kosten, 'akonto': akonto, 'saldo': saldo,
        })

    belege = p.belege.all().order_by('-datum')

    tab_liste = [
        ('abrechnung', 'Mieter-Abrechnung', len(abrechnungen) or None),
        ('belege', 'Belege', belege.count() or None),
    ]
    return render(request, 'fw/nebenkosten_detail.html', {
        **basis, 'nav': 'nebenkosten', 'p': p,
        'total_kosten': total_kosten, 'total_akonto': total_akonto,
        'saldo_total': total_kosten - total_akonto,
        'abrechnungen': abrechnungen, 'belege': belege,
        'kreditoren': kosten_rechnungen,
        'tab_liste': tab_liste,
    })


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
    })


# ============================================================
# ETAPPE D: KOMMUNIKATION (Mitteilungs-Assistent mit Live-Vorschau)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kommunikation(request):
    from crm.models import Verwaltung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    vw = Verwaltung.objects.first()
    absender = {
        'firma': vw.firma if vw else 'Meine Verwaltung',
        'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
    }

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

    # Belegte Einheiten (aktiver Vertrag inkl. Nebenobjekte) ausschliessen
    belegte = set(Mietvertrag.objects.filter(status='aktiv').values_list('einheit_id', flat=True))
    for nid in Mietvertrag.objects.filter(status='aktiv').values_list('nebenobjekte', flat=True):
        if nid:
            belegte.add(nid)

    lg_qs = Liegenschaft.objects.select_related('mandant').prefetch_related('einheiten').order_by('strasse')
    if aktive_lg:
        lg_qs = lg_qs.filter(id=aktive_lg.id)

    liegenschaften = []
    for lg in lg_qs:
        objekte = []
        for e in lg.einheiten.all().order_by('bezeichnung'):
            if e.id in belegte:
                continue
            objekte.append({
                'id': e.id, 'bezeichnung': e.bezeichnung,
                'typ': e.get_typ_display(), 'etage': e.etage or '',
                'ewid': e.ewid or '', 'zimmer': float(e.zimmer) if e.zimmer else None,
                'flaeche': float(e.flaeche_m2) if e.flaeche_m2 else None,
                'netto': float(e.nettomiete_aktuell or 0), 'nk': float(e.nebenkosten_aktuell or 0),
                'kaution_monate': e.standard_kautionsmonate or 3,
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
        'aktueller_lik': float(vw.aktueller_lik_punkte) if vw else 107.1,
        'heute_iso': timezone.now().date().isoformat(),
    })


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
    einheit = get_object_or_404(Einheit, id=P.get('einheit_id'))

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
        mit_teile = [P.get('mit_anrede', '').strip(), P.get('mit_vorname', '').strip(),
                     P.get('mit_nachname', '').strip()]
        mitmieter = ' '.join(t for t in mit_teile if t).strip() or P.get('mitmieter_name', '').strip()
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
    with transaction.atomic():
        vertrag = Mietvertrag.objects.create(
            mieter=mieter, einheit=einheit,
            status='aktiv' if P.get('aktiv_setzen') == 'on' else 'entwurf',
            beginn=beginn, ende=datum('ende'),
            erstmals_kuendbar_auf=datum('erstmals_kuendbar'),
            kuendigungsfrist_monate=int(P.get('kuendigungsfrist') or 3),
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
            weitere_vorbehalte=P.get('weitere_vorbehalte', '').strip(),
            basis_referenzzinssatz=dec('basis_referenzzinssatz') or Decimal('1.75'),
            basis_lik_punkte=dec('basis_lik_punkte') or Decimal('107.1'),
            kostensteigerung_datum=datum('kostensteigerung_datum'),
            kautions_betrag=dec('kautions_betrag') or None,
            kautions_konto=P.get('kautions_konto', '').strip(),
        )
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

    log_aktion(request, "Mietvertrag erstellt (Assistent)", str(mieter),
               f"{einheit.bezeichnung}, ab {beginn}")
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
    from core.auth import log_aktion, hat_rolle
    vw = Verwaltung.objects.first() or Verwaltung.objects.create(firma="Meine Verwaltung")
    basis = _global_filter(request)

    if request.method == 'POST' and hat_rolle(request.user, SCHREIB_ROLLEN):
        P = request.POST
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
        vw.save()
        log_aktion(request, "Account/Stammdaten bearbeitet", vw.firma, '')
        messages.success(request, "✅ Stammdaten gespeichert.")
        return redirect('/neu/account/')

    return render(request, 'fw/account.html', {**basis, 'nav': 'account', 'vw': vw})


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
    """Team-Mitglieder (Django-User + Rolle)."""
    from django.contrib.auth.models import User
    from core.auth import ROLLE_EIGENTUEMER
    basis = _global_filter(request)
    users = User.objects.filter(is_active=True).order_by('username')
    rows = []
    for u in users:
        rollen = list(u.groups.values_list('name', flat=True))
        if ROLLE_EIGENTUEMER in rollen and len(rollen) == 1:
            continue  # reine Eigentümer-Portal-Accounts hier nicht zeigen
        rows.append({'u': u, 'rolle': ', '.join(rollen) or ('Superuser' if u.is_superuser else '—'),
                     'name': (u.get_full_name() or u.username)})
    return render(request, 'fw/benutzer.html', {**basis, 'nav': 'benutzer', 'rows': rows})


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
]

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_vorlagen(request):
    from crm.models import Vorlage
    basis = _global_filter(request)
    vorlagen = Vorlage.objects.all()
    return render(request, 'fw/vorlagen.html', {**basis, 'nav': 'vorlagen', 'vorlagen': vorlagen})


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vorlage_form(request, pk=None):
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Vorlage
    from core.auth import log_aktion
    vl = get_object_or_404(Vorlage, id=pk) if pk else None
    basis = _global_filter(request)
    if request.method == 'POST':
        obj = vl or Vorlage()
        obj.name = request.POST.get('name', '').strip()
        obj.kategorie = request.POST.get('kategorie', 'brief')
        obj.betreff = request.POST.get('betreff', '').strip()
        obj.inhalt = request.POST.get('inhalt', '')
        if not obj.name:
            messages.error(request, "Bezeichnung ist erforderlich.")
            return redirect(request.path)
        obj.save()
        log_aktion(request, "Vorlage bearbeitet" if pk else "Vorlage erstellt", obj.name, '')
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

def fw_abonnemente(request):
    return fw_stub(request, 'Abonnement', 'fa-star',
                   'Dein swissImmo-Abo und die Abrechnung. Aktuell ist die Vollversion aktiv.')


# ============================================================
# LIEGENSCHAFT + OBJEKT CRUD (neu / bearbeiten)
# ============================================================

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_liegenschaft_form(request, pk=None):
    """Liegenschaft erfassen oder bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mandant
    from core.auth import log_aktion
    lg = get_object_or_404(Liegenschaft, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
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
        obj.save()
        log_aktion(request, "Liegenschaft bearbeitet" if pk else "Liegenschaft erstellt",
                   f"{obj.strasse}, {obj.ort}", '')
        messages.success(request, f"✅ Liegenschaft {obj.strasse} gespeichert.")
        return redirect(f'/neu/liegenschaften/{obj.id}/')

    return render(request, 'fw/liegenschaft_form.html', {
        **basis, 'nav': 'liegenschaften', 'lg': lg, 'ist_neu': lg is None,
        'mandanten': Mandant.objects.all().order_by('firma_oder_name'),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_form(request, pk=None):
    """Mietobjekt (Einheit) erfassen oder bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    e = get_object_or_404(Einheit, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
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
        log_aktion(request, "Objekt bearbeitet" if pk else "Objekt erstellt",
                   f"{obj.bezeichnung} ({obj.liegenschaft.strasse})", '')
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
    from core.auth import log_aktion
    md = get_object_or_404(Mandant, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
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
        log_aktion(request, "Mandant bearbeitet" if pk else "Mandant erstellt", obj.firma_oder_name, '')
        messages.success(request, f"✅ Mandant {obj.firma_oder_name} gespeichert.")
        return redirect('/neu/mandate/')

    alle_lg = Liegenschaft.objects.all().order_by('strasse')
    zugeordnet = set(Liegenschaft.objects.filter(mandant=md).values_list('id', flat=True)) if md else set()
    return render(request, 'fw/mandat_form.html', {
        **basis, 'nav': 'mandate', 'md': md, 'ist_neu': md is None,
        'alle_liegenschaften': alle_lg, 'zugeordnet': zugeordnet,
    })


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
    from core.auth import log_aktion
    ziel = get_object_or_404(User, id=pk) if pk else None
    basis = _global_filter(request)

    if request.method == 'POST':
        P = request.POST
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
        log_aktion(request, "Benutzer bearbeitet" if pk else "Benutzer erstellt", ziel.username, rolle)
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
