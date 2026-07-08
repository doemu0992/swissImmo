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

from core.auth import rolle_erforderlich, TEAM_ROLLEN, SCHREIB_ROLLEN
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
                           .filter(als_nebenobjekt_in_vertraegen=e, status='aktiv')
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
                'bank': vw.bank_name, 'iban': _iban_format(vw.iban),
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
