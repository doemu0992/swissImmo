# core/views/fw/_rest.py
#
# Der noch nicht aufgeteilte Rest der urspruenglichen fw.py (Etappe 1,
# siehe docs/ETAPPE-1-ZERLEGEN.md). Schrumpft mit jedem Block und faellt
# am Ende ganz weg. Importiert wird weiterhin ueber core.views.fw --
# das __init__.py haelt die Fassade stabil.
"""
Fairwalter-Rebuild: neue Oberfläche (/neu/…) auf bestehendem Backend.
Referenz: Original-Screenshots in REBUILD.md. Server-gerendert, testbar.

Der 'Globale Filter' (?lg=<id>) filtert alle Kennzahlen auf eine Liegenschaft —
er wird in _global_filter() gelesen und an jede Seite durchgereicht.
"""
import logging
import os
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

# Geteilte Helfer — seit Etappe 1 in _basis.py (siehe dort, warum).
# Bis Etappe 1 kamen diese beiden aus dem Mahnwesen-Block, der sie
# nebenbei importierte. Seit der Block in mahnwesen.py steht, werden
# sie hier direkt bezogen — gleiche Quelle, gleiche Objekte.
from core.services.mahnstufen import (  # noqa: F401
    stufe_fuer_tage as _stufe_fuer_tage,
    eigentuemer_von_rechnung as _eigentuemer_von_rechnung,
)
# Bis Etappe 1 zog der Assets-Block dieses Alias nebenbei herein, und der
# ganze Rest der Datei benutzte es mit (17 Stellen). Seit der Block in
# assets.py steht, wird es hier direkt bezogen — gleiche Quelle.
from datetime import timedelta as _timedelta  # noqa: F401
# Ebenfalls von einem verschobenen Block geliefert (MWST, Block 22).
import calendar as _calendar  # noqa: F401
# Der Vertragserstellungs-Block braucht anfangsmietzins_auto_ablegen aus
# dem Mietzins-Block. Solange er hier steht, wird der Name von dort
# bezogen; zieht er um, wandert diese Zeile mit.
from .mietzins import anfangsmietzins_auto_ablegen  # noqa: F401
from ._basis import (  # noqa: F401
    _global_filter, VERTRAG_PILL, _kaution_bilanziert, _mwst_beleg, _parse_adresse,
    _mwst_bereits_verbucht, _mwst_periode, _num,
    _pendenz_ziel, _vermietung_pipeline,
)

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum, F
from django.db.models.functions import ExtractMonth
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from core.auth import (rolle_erforderlich, darf_oeffnen, TEAM_ROLLEN, SCHREIB_ROLLEN,
                       ROLLE_VERWALTUNG, VERWALTUNGS_ROLLEN)
from core.views.dashboard_view import _berechne_aufgaben
from crm.models import Mieter
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_dashboard(request):
    heute = timezone.localdate()
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
    # «Gekündigt» = gekündigt UND noch laufend (ende in der Zukunft/offen). Ein
    # gekündigter Vertrag, dessen Ende bereits vorbei ist, zählt als BEENDET
    # (v_beendet oben) — sonst würde er doppelt gezählt und die Status-Summe
    # stimmte nicht mit der Objektzahl überein (Live-Test J: «4 vs 5»).
    v_gekuendigt = (vertraege.filter(status='gekuendigt')
                    .filter(Q(ende__isnull=True) | Q(ende__gte=heute)).count())
    v_zukuenftig = vertraege.filter(beginn__gt=heute).exclude(status__in=['archiviert', 'gekuendigt']).count()

    # --- LEERSTAND-KARTE (Tabs: Leerstand / Gekündigt / Bevorstehend) ---
    belegte_ids = set(vertraege.filter(status='aktiv').values_list('einheit_id', flat=True))
    for neben_id in vertraege.filter(status='aktiv').values_list('nebenobjekte', flat=True):
        if neben_id:
            belegte_ids.add(neben_id)
    leerstand_objekte = (einheiten.exclude(id__in=belegte_ids)
                         .select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'))
    # Nur noch LAUFENDE gekündigte Verträge (Ende offen/künftig) — bereits
    # abgelaufene sind beendet und gehören nicht in die «Gekündigt»-Liste
    # (konsistent zu v_gekuendigt, Live-Test J).
    gekuendigte = (vertraege.filter(status='gekuendigt')
                   .filter(Q(ende__isnull=True) | Q(ende__gte=heute))
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
    _deb = (DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
            .prefetch_related('zahlungseingaenge'))
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
    # --- DIE EINE INBOX (ersetzt Cockpit-Widgets, «Heute zu tun» und Aufgaben) ---
    from core.services.inbox import sammle_inbox, TYP_META
    from core.navigation import aktueller_modus
    ui_modus = aktueller_modus(request)
    inbox, inbox_mehr, inbox_typen = sammle_inbox(
        aktive_lg=aktive_lg, lg_query=basis['lg_query'], modus=ui_modus,
        pendenz_ziel=_pendenz_ziel)
    inbox_chips = [{'key': k, 'label': TYP_META[k]['label'], 'n': inbox_typen.get(k, 0)}
                   for k in ('geld', 'frist', 'schaden', 'prozess', 'aufgabe')
                   if inbox_typen.get(k)]
    inbox_dringend = sum(1 for e in inbox if e['dringend'])

    # --- Analytics fürs Dashboard (rein additiv, DEFENSIV: dürfen das Cockpit
    #     nie brechen — jede Auswertung ist in try/except gekapselt und liefert
    #     im Fehlerfall einfach nichts, die Karte wird dann ausgeblendet). ---
    dash_aktivitaet = []
    try:
        from core.models import AktivitaetsLog
        dash_aktivitaet = list(AktivitaetsLog.objects.select_related('benutzer')
                               .order_by('-id')[:6])
    except Exception:
        logger.debug("Dashboard-Aktivität übersprungen", exc_info=True)

    belegung_conic = ''
    try:
        # Design-System-Tokens statt fester Hex-Werte → Donut-Segmente und
        # Legenden-Swatches stimmen in Hell UND Dunkel exakt überein.
        _cols = {'wohnen': 'var(--ds-brand)', 'parkplatz': 'var(--ds-info)',
                 'gewerbe': 'var(--ds-warn)', 'weitere': 'var(--ds-faint)'}
        _tot = sum(breakdown.values())
        if _tot:
            _stops = []
            _acc = 0.0
            for _k in ('wohnen', 'parkplatz', 'gewerbe', 'weitere'):
                _pct = breakdown.get(_k, 0) / _tot * 100
                _stops.append(f"{_cols[_k]} {_acc:.2f}% {_acc + _pct:.2f}%")
                _acc += _pct
            belegung_conic = "conic-gradient(" + ", ".join(_stops) + ")"
    except Exception:
        logger.debug("Dashboard-Belegung übersprungen", exc_info=True)

    dash_chart = None
    try:
        from finance.models import Buchung
        import calendar as _cal
        # 12 Monate rückwärts inkl. aktuellem Monat
        _months = []
        _y, _m = heute.year, heute.month
        for _ in range(12):
            _months.append((_y, _m))
            _m -= 1
            if _m == 0:
                _m = 12
                _y -= 1
        _months.reverse()
        _first = date(_months[0][0], _months[0][1], 1)
        # Ist-Mietertrag = Habenbuchungen auf 3000/3010 (ohne Storni), pro Monat
        _bq = Buchung.objects.filter(ist_storno=False,
                                     haben_konto__nummer__in=['3000', '3010'],
                                     datum__gte=_first)
        if aktive_lg:
            _bq = _bq.filter(liegenschaft=aktive_lg)
        _sums = {}
        for _r in _bq.values('datum__year', 'datum__month').annotate(s=Sum('betrag')):
            _sums[(_r['datum__year'], _r['datum__month'])] = float(_r['s'] or 0)
        _ist = [_sums.get((yy, mm), 0.0) for (yy, mm) in _months]
        _soll = float(soll_potenzial or 0)
        _mx = max(_ist + [_soll, 1.0])
        _W, _H, _P = 620.0, 210.0, 24.0

        def _pt(i, val):
            x = (i / 11.0) * _W
            yv = _H - _P - (val / _mx) * (_H - 2 * _P)
            return (x, yv)

        _ist_pairs = [_pt(i, v) for i, v in enumerate(_ist)]
        _ist_points = " ".join(f"{x:.1f},{y:.1f}" for (x, y) in _ist_pairs)
        _soll_y = _H - _P - (_soll / _mx) * (_H - 2 * _P)
        _area = ("M" + " ".join(f"{x:.1f},{y:.1f}" for (x, y) in _ist_pairs)
                 + f" L{_W:.0f},{_H:.0f} L0,{_H:.0f} Z")
        dash_chart = {
            'ist_points': _ist_points,
            'soll_y': f"{_soll_y:.1f}",
            'area': _area,
            'last_x': f"{_ist_pairs[-1][0]:.1f}",
            'last_y': f"{_ist_pairs[-1][1]:.1f}",
            'has_data': any(v > 0 for v in _ist),
        }
    except Exception:
        logger.debug("Dashboard-Chart übersprungen", exc_info=True)
        dash_chart = None

    context = {
        **basis,
        'nav': 'dashboard',
        'dash_aktivitaet': dash_aktivitaet,
        'belegung_conic': belegung_conic,
        'dash_chart': dash_chart,
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
        'kpis': kpis,
        'heute': heute,
        'inbox': inbox,
        'inbox_mehr': inbox_mehr,
        'inbox_chips': inbox_chips,
        'inbox_dringend': inbox_dringend,
    }
    return render(request, 'fw/dashboard.html', context)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_finanzen(request):
    """Finanz-Cockpit — EIN Arbeitskorb statt 11 Menüs einzeln abzuklappern.

    Die Reihenfolge der Abschnitte bildet den realen Buchhalter-Ablauf ab:
    Eingänge klären (Bank) → Eingangsrechnungen freigeben → Zahllauf →
    weiterverrechnen → mahnen → Perioden abschliessen (Sollstellung, MWST).
    Jede Kachel zeigt Anzahl + CHF + Direktlink auf die bestehende Funktion.
    """
    from finance.models import KreditorenRechnung, Buchungskonto, Buchung
    from core.models import Pendenz
    import calendar as _cal

    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    # ---------- Debitoren (offene Forderungen) ----------
    deb = DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
    if aktive_lg:
        deb = deb.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    deb = [r for r in deb.select_related('vertrag').prefetch_related('zahlungseingaenge') if r.offener_betrag > 0]
    deb_offen_chf = sum((r.offener_betrag for r in deb), Decimal('0.00'))
    deb_ueberf = [r for r in deb if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) < heute]
    deb_ueberf_chf = sum((r.offener_betrag for r in deb_ueberf), Decimal('0.00'))

    # ---------- Kreditoren (Eingangsrechnungen) ----------
    kred = KreditorenRechnung.objects.exclude(status='storniert')
    if aktive_lg:
        kred = kred.filter(liegenschaft=aktive_lg)
    kred = list(kred.prefetch_related('zahlungen', 'weiterverrechnungen'))
    zur_freigabe = [k for k in kred if k.status == 'neu']
    zur_zahlung = [k for k in kred if k.status in ('freigegeben', 'teilbezahlt') and k.offener_betrag > 0]
    in_zahlung = [k for k in kred if k.status == 'in_zahlung']
    # Weiterverrechnung: nur *angefangene* (bereits teilweise weiterverrechnete) Rechnungen
    # als Todo führen — sonst würde jede Lieferantenrechnung fälschlich als "zu
    # verrechnen" markiert (Weiterverrechnung ist ein bewusster Einzelentscheid).
    offen_wv = [k for k in kred if k.weiterverrechnet_betrag > 0 and k.offen_weiterzuverrechnen > 0]

    def _chf(items, attr='offener_betrag'):
        return sum((getattr(k, attr) or Decimal('0.00') for k in items), Decimal('0.00'))

    # ---------- Kaution-Freigabefristen (fällige Pendenzen) ----------
    kaut = Pendenz.objects.filter(erledigt=False, quelle__startswith='auto:kautionfreigabe:')
    if aktive_lg:
        kaut = kaut.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    kaut_faellig = kaut.filter(faellig_am__lte=heute).count()
    kaut_offen = kaut.count()

    # ---------- Durchlaufkonto 1190: ungeklärte/geparkte Positionen ----------
    durchlauf_saldo = Decimal('0.00')
    k1190 = Buchungskonto.objects.filter(nummer='1190').first()
    if k1190:
        bq = Buchung.objects.all()
        if aktive_lg:
            bq = bq.filter(liegenschaft=aktive_lg)
        soll = bq.filter(soll_konto=k1190).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        haben = bq.filter(haben_konto=k1190).aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        durchlauf_saldo = soll - haben

    # ---------- Arbeitskorb (Reihenfolge = Prozess) ----------
    # Volle Tailwind-Klassen (CDN-sicher, keine dynamisch zusammengesetzten Namen).
    P = {
        'sky':    ('bg-sky-100 text-sky-600',       'bg-sky-600 hover:bg-sky-700'),
        'amber':  ('bg-amber-100 text-amber-600',   'bg-amber-500 hover:bg-amber-600'),
        'indigo': ('bg-indigo-100 text-indigo-600', 'bg-indigo-600 hover:bg-indigo-700'),
        'violet': ('bg-violet-100 text-violet-600', 'bg-violet-600 hover:bg-violet-700'),
        'rose':   ('bg-rose-100 text-rose-600',     'bg-rose-600 hover:bg-rose-700'),
        'teal':   ('bg-teal-100 text-teal-600',     'bg-teal-600 hover:bg-teal-700'),
    }
    _korb = [
        ('bank', 'fa-right-left', 'sky', 'Zahlungseingänge abgleichen',
         'Offene Forderungen mit Bankgutschriften verbuchen',
         len(deb), deb_offen_chf, '/neu/bankabgleich/', 'Abgleichen', bool(deb_ueberf)),
        ('freigabe', 'fa-stamp', 'amber', 'Eingangsrechnungen freigeben',
         'Neu erfasste Kreditoren prüfen & freigeben',
         len(zur_freigabe), _chf(zur_freigabe, 'betrag'), '/neu/kreditoren/', 'Freigeben', False),
        ('zahllauf', 'fa-money-bill-transfer', 'indigo', 'Zahllauf ausführen',
         'Freigegebene Kreditoren zur Zahlung (pain.001)',
         len(zur_zahlung), _chf(zur_zahlung), '/neu/kreditoren/', 'Zahlen',
         any((k.faellig_am and k.faellig_am < heute) for k in zur_zahlung)),
        ('weiterverrechnung', 'fa-share-from-square', 'violet', 'Weiterverrechnungen abschliessen',
         'Angefangene Weiterverrechnungen an Mieter fertigstellen',
         len(offen_wv), _chf(offen_wv, 'offen_weiterzuverrechnen'), '/neu/kreditoren/', 'Weiterverrechnen', False),
        ('mahnen', 'fa-envelope-open-text', 'rose', 'Überfällige Forderungen mahnen',
         'Fällige Debitoren mit Mahnung anstossen',
         len(deb_ueberf), deb_ueberf_chf, '/neu/mahnwesen/', 'Mahnen', bool(deb_ueberf)),
        ('kaution', 'fa-shield-halved', 'teal', 'Kautionen freigeben',
         'Rückzahlungsfristen nach Auszug (Art. 257e)',
         kaut_offen, None, '/neu/kautionen/', 'Kautionen', kaut_faellig > 0),
    ]
    arbeitskorb = [{
        'key': k, 'icon': ic, 'icon_cls': P[f][0], 'btn_cls': P[f][1],
        'titel': t, 'sub': s, 'anzahl': n, 'chf': c,
        'url': u + basis['lg_query'], 'cta': cta, 'dringend': d,
    } for (k, ic, f, t, s, n, c, u, cta, d) in _korb]
    offene_posten = sum(1 for i in arbeitskorb if i['anzahl'])
    dringend_n = sum(1 for i in arbeitskorb if i['dringend'])

    # ---------- Monatsabschluss-Checkliste (Ampel) ----------
    j, m = heute.year, heute.month
    soll_titel = f"Miete & NK {m:02d}/{j}"
    soll_qs = DebitorenRechnung.objects.filter(titel=soll_titel).exclude(status='storniert')
    if aktive_lg:
        soll_qs = soll_qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    soll_gelaufen = soll_qs.exists()

    # MWST: welches Quartal ist als letztes abgeschlossen und damit abrechnungsreif?
    aktuelles_q = (m - 1) // 3 + 1
    letztes_q = aktuelles_q - 1 or 4
    letztes_q_jahr = j if aktuelles_q > 1 else j - 1

    checkliste = [
        {'titel': f'Sollstellung Miete {m:02d}/{j} gebucht', 'ok': soll_gelaufen,
         'url': '/neu/sollstellung/' + basis['lg_query'],
         'hinweis': 'Monatlicher Mietenlauf erzeugt Debitoren + Buchungen'},
        {'titel': 'Eingangsrechnungen alle freigegeben', 'ok': not zur_freigabe,
         'url': '/neu/kreditoren/' + basis['lg_query'],
         'hinweis': f'{len(zur_freigabe)} noch offen' if zur_freigabe else 'keine offenen'},
        {'titel': 'Zahllauf ausgeführt', 'ok': not zur_zahlung,
         'url': '/neu/kreditoren/' + basis['lg_query'],
         'hinweis': f'{len(zur_zahlung)} zur Zahlung' if zur_zahlung else 'nichts offen'},
        {'titel': 'Zahlungseingänge abgeglichen', 'ok': not deb_ueberf,
         'url': '/neu/bankabgleich/' + basis['lg_query'],
         'hinweis': f'{len(deb_ueberf)} überfällig' if deb_ueberf else 'keine überfälligen'},
        {'titel': f'MWST-Abrechnung Q{letztes_q}/{letztes_q_jahr} prüfen', 'ok': None,
         'url': f'/neu/mwst/?jahr={letztes_q_jahr}&quartal={letztes_q}',
         'hinweis': 'Quartalsweise an die ESTV — manuell bestätigen'},
    ]
    erledigt_n = sum(1 for c in checkliste if c['ok'] is True)
    pflicht_n = sum(1 for c in checkliste if c['ok'] is not None)

    return render(request, 'fw/finanzen.html', {
        **basis, 'nav': 'finanzen',
        'arbeitskorb': arbeitskorb,
        'offene_posten': offene_posten, 'dringend_n': dringend_n,
        'deb_offen_chf': deb_offen_chf, 'deb_ueberf_chf': deb_ueberf_chf,
        'kred_zahllauf_chf': _chf(zur_zahlung), 'in_zahlung_n': len(in_zahlung),
        'durchlauf_saldo': durchlauf_saldo,
        'checkliste': checkliste, 'erledigt_n': erledigt_n, 'pflicht_n': pflicht_n,
        'heute': heute,
    })


# ============================================================
# ETAPPE B: LISTEN ALS DATENTABELLEN
# ============================================================

def _mahnstufe(faellig, heute, status, eigentuemer=None):
    """Mahnstufen-Badge aus Fälligkeit + der Mahnkonfig des Eigentümers
    (core.services.mahnstufen). 'Fällig' als Fallback, wenn überfällig, aber
    noch unter der ersten aktiven Stufe. eigentuemer=None → Standard (14/30/60)."""
    if status not in ('offen', 'teilbezahlt') or not faellig or faellig >= heute:
        return None
    tage = (heute - faellig).days
    s = _stufe_fuer_tage(tage, eigentuemer)
    if s:
        return {'label': s['label'], 'cls': s['cls'], 'tage': tage}
    return {'label': 'Fällig', 'cls': 'bg-amber-50 text-amber-600', 'tage': tage}


STATUS_PILL = {
    'offen':       ('Offen',       'bg-amber-50 text-amber-700'),
    'teilbezahlt': ('Teilbezahlt', 'bg-sky-50 text-sky-700'),
    'bezahlt':     ('Bezahlt',     'bg-emerald-50 text-emerald-700'),
    'storniert':   ('Storniert',   'bg-slate-100 text-slate-500'),
    'abgeschrieben': ('Abgeschrieben', 'bg-slate-100 text-slate-500'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_debitoren(request):
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (DebitorenRechnung.objects
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft__eigentuemer',
                          'liegenschaft__eigentuemer', 'einheit__liegenschaft')
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

    # --- KPI-Summen als DB-Aggregate ---------------------------------------
    # Vorher lief hier eine Python-Schleife über ALLE Rechnungen (inkl. der
    # vorgeladenen Zahlungen), nur um vier Summen zu bilden und danach auf 50
    # Zeilen zu paginieren. Bei 12 Liegenschaften/1 Jahr waren das ~9'200 ORM-
    # Objekte und ~500 ms für eine Seite, die 50 Zeilen zeigt — und es wächst
    # linear mit jedem Monat Sollstellung. Die Summen rechnet jetzt die
    # Datenbank, materialisiert wird nur die angezeigte Seite (Profiling).
    from django.db.models import OuterRef, Subquery, Count, Value, DecimalField
    from django.db.models.functions import Coalesce, Greatest
    _GELD = DecimalField(max_digits=12, decimal_places=2)
    _NULL = Value(Decimal('0.00'), output_field=_GELD)
    _OFFEN_STATUS = ('offen', 'teilbezahlt')

    # Verbuchte Zahlungen je Rechnung als SUBQUERY, nicht als JOIN: ein Join auf
    # die Zahlungen vervielfacht die Rechnungszeilen (eine Zeile je Zahlung) und
    # würde damit Sum('betrag') für Rechnungen mit Teilzahlungen verfälschen.
    _bezahlt = Subquery(
        Zahlungseingang.objects
        .filter(debitoren_rechnung=OuterRef('pk'), status='verbucht')
        .values('debitoren_rechnung').annotate(s=Sum('betrag')).values('s')[:1],
        output_field=_GELD)
    # Spiegelt DebitorenRechnung.offener_betrag: max(0, betrag − verbucht).
    _offen_expr = Greatest(F('betrag') - Coalesce(_bezahlt, _NULL), _NULL, output_field=_GELD)
    _faellig_expr = Coalesce('faellig_am', 'datum')   # datum hat Default → nie NULL

    total_betrag = (qs.exclude(status='storniert')
                    .aggregate(s=Sum('betrag'))['s'] or Decimal('0.00'))
    offene_qs = qs.filter(status__in=_OFFEN_STATUS)
    _agg = offene_qs.annotate(_o=_offen_expr).aggregate(s=Sum('_o'), n=Count('id'))
    total_offen = _agg['s'] or Decimal('0.00')
    anzahl_offen = _agg['n'] or 0
    # _mahnstufe() liefert für JEDE überfällige offene Rechnung einen Treffer
    # (Fallback «Fällig», wenn noch unter der ersten Stufe). Die Zahl ist damit
    # exakt «offen und fällig vor heute» — reines SQL, ohne Eigentümer-Lookup.
    anzahl_ueberfaellig = (offene_qs.annotate(_f=_faellig_expr)
                           .filter(_f__lt=heute).count())

    # --- Sortierung + Pagination in SQL ------------------------------------
    # Reihenfolge wie bisher: offene Posten zuerst (älteste Fälligkeit oben),
    # erledigte danach (neuste oben). Zwei Querysets, weil eine einzelne
    # ORDER BY-Klausel die Richtung nicht pro Gruppe umdrehen kann.
    offene_sortiert = offene_qs.annotate(_f=_faellig_expr, _o=_offen_expr).order_by('_f', 'id')
    andere_sortiert = (qs.exclude(status__in=_OFFEN_STATUS)
                       .annotate(_f=_faellig_expr, _o=_offen_expr).order_by('-_f', '-id'))

    from django.core.paginator import Paginator, Page
    try:
        seite = max(1, int(request.GET.get('seite') or 1))
    except ValueError:
        seite = 1
    n_offen_rows = offene_sortiert.count()
    rows_gesamt = n_offen_rows + andere_sortiert.count()
    # Paginator über eine Platzhalter-Sequenz: das Template nutzt von `page` nur
    # die Pager-Metadaten (Nummer, Seitenzahl, vor/zurück), nie object_list.
    paginator = Paginator(range(rows_gesamt), 50)
    page = paginator.get_page(seite)
    _start = (page.number - 1) * paginator.per_page
    _ende = _start + paginator.per_page
    seiten_objekte = []
    if _start < n_offen_rows:                       # Teil der Seite liegt in den offenen
        seiten_objekte += list(offene_sortiert[_start:min(_ende, n_offen_rows)])
    if _ende > n_offen_rows:                        # …und/oder in den erledigten
        seiten_objekte += list(andere_sortiert[max(0, _start - n_offen_rows):_ende - n_offen_rows])

    rows = []
    for r in seiten_objekte:
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        einheit = r.einheit or (r.vertrag.einheit if r.vertrag_id else None)
        # `_o` kommt aus der Annotation (siehe oben) — identisch zu
        # r.offener_betrag, aber ohne die Zahlungen nachzuladen.
        offen = r._o if r.status in _OFFEN_STATUS else Decimal('0.00')
        faellig = r.faellig_am or r.datum
        mahn = _mahnstufe(faellig, heute, r.status, _eigentuemer_von_rechnung(r))
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
    # (Sortierung und Seitenauswahl sind oben bereits in SQL erledigt.)
    # Das Template iteriert `page` (nicht `rows`) — ein Page-Objekt ist über
    # seine object_list iterierbar. Der Paginator oben kennt nur die Platzhalter-
    # Sequenz für die Metadaten (Seitenzahl, vor/zurück); die tatsächlichen
    # Zeilen werden hier eingesetzt, damit beides zusammenpasst.
    page = Page(rows, page.number, paginator)

    aktive_vertraege = (Mietvertrag.objects.filter(status='aktiv')
                        .select_related('mieter', 'einheit__liegenschaft').order_by('einheit__liegenschaft__strasse'))
    if aktive_lg:
        aktive_vertraege = aktive_vertraege.filter(einheit__liegenschaft=aktive_lg)

    # Live-Vorschau (wie im Vertragsassistenten): Empfänger je Vertrag + Absender.
    vertrag_daten = {}
    for v in aktive_vertraege:
        m = v.mieter
        lg = v.einheit.liegenschaft if v.einheit_id else None
        vertrag_daten[str(v.id)] = {
            'mieter': m.display_name if m else '',
            'strasse': (m.strasse or '') if m else '',
            'plz': (m.plz or '') if m else '', 'ort': (m.ort or '') if m else '',
            'objekt': (v.einheit.bezeichnung if v.einheit_id else ''),
            'adresse': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else ''),
        }
    from crm.models import Verwaltung
    vw = Verwaltung.objects.first()
    absender = {
        'firma': vw.firma if vw else '', 'strasse': vw.strasse if vw else '',
        'plz': vw.plz if vw else '', 'ort': vw.ort if vw else '',
        'iban': (vw.iban or '') if vw else '',
    }

    context = {
        **basis,
        'nav': 'debitoren',
        'rows': rows,
        'status_filter': status_filter,
        'q': q,
        'status_chips': [('', 'Alle')] + [(k, v[0]) for k, v in STATUS_PILL.items()],
        'total_offen': total_offen,
        'total_betrag': total_betrag,
        'anzahl_offen': anzahl_offen,
        'anzahl_ueberfaellig': anzahl_ueberfaellig,
        'aktive_vertraege': aktive_vertraege,
        'vertrag_daten': vertrag_daten,
        'absender': absender,
        'heute_iso': heute.isoformat(),
        'faellig_iso': (heute + _timedelta(days=30)).isoformat(),
        'page': page, 'rows_gesamt': rows_gesamt,
    }
    return render(request, 'fw/debitoren.html', context)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_debitor_neu(request):
    """Ad-hoc-Debitorenrechnung (Weiterverrechnung: Sonnerie/Schlüssel/Ersatz …).
    Bucht Debitor an das gewählte Ertragskonto (Standard 3600 «Übrige Erträge»)
    und ermöglicht anschliessend die QR-Rechnung. NICHT auf 3000 — Schlüssel-
    ersatz & Co. sind kein Mietertrag (verfälscht Mieterspiegel + Honorarbasis)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_debitoren')

    titel = (request.POST.get('titel') or '').strip()
    try:
        betrag = Decimal((_num(request.POST.get('betrag')) or '0'))
    except Exception:
        betrag = Decimal('0')
    if not titel or betrag <= 0:
        messages.error(request, "Titel und ein Betrag > 0 sind erforderlich.")
        return redirect('fw_debitoren')

    vertrag = None
    if request.POST.get('vertrag_id'):
        vertrag = Mietvertrag.objects.filter(id=request.POST['vertrag_id']).select_related('einheit__liegenschaft').first()
    lg = vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None
    heute = timezone.localdate()
    faellig = heute + _timedelta(days=30)

    # Ertragskonto: explizit gewählt (Feld konto_haben) oder Standard 3600.
    konto_haben = None
    if request.POST.get('konto_haben'):
        konto_haben = Buchungskonto.objects.filter(id=request.POST['konto_haben']).first()
    haben_nr = konto_haben.nummer if konto_haben else "3600"

    with transaction.atomic():
        rechnung = DebitorenRechnung.objects.create(
            vertrag=vertrag, liegenschaft=lg,
            einheit=(vertrag.einheit if vertrag else None),
            titel=titel, beschreibung=(request.POST.get('beschreibung') or '').strip(),
            datum=heute, faellig_am=faellig, betrag=betrag, status='offen',
            konto_haben=konto_haben,
        )
        from finance.booking import buche
        buche("1100", haben_nr, betrag, f"Weiterverrechnung: {titel}", datum=heute,
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

    # Gegenkonto der Aufwandsminderung: Kopf-Konto, sonst (bei Split) das Konto der
    # grössten Position, sonst 4000. So trifft die Weiterverrechnung einer aufge-
    # teilten Rechnung das tatsächliche Aufwandskonto statt pauschal 4000.
    if k.konto_id:
        aufwand_konto = k.konto.nummer
    else:
        _grp = k.positionen.order_by('-betrag').first()
        aufwand_konto = _grp.konto.nummer if _grp else '4000'

    if request.method == 'POST':
        # Alle Schreibvorgänge dieser Weiterverrechnung in EINER Transaktion +
        # Zeilensperre auf die Kreditorenrechnung: verhindert Teilzustände (einige
        # Mieter belastet, andere nicht) bei Abbruch und den Über-Weiterverrechnungs-
        # Race (min(grund, offen) ist ohne Lock ein Check-then-act).
        with transaction.atomic():
            k = KreditorenRechnung.objects.select_for_update().get(id=k.id)
            def _dec(x, d='0'):
                try:
                    return Decimal(_num(x) or d)
                except Exception:
                    return Decimal(d)

            def _verrechne(vertrag, grund, zuschlag, titel):
                """Erstellt eine verknüpfte Debitorenrechnung + ertragsneutrale
                Durchreichung über 1190 (Zuschlag als Ertrag 3600). Gibt (rechnung, total)."""
                lg2 = vertrag.einheit.liegenschaft if vertrag.einheit_id else k.liegenschaft
                zuschlag = max(zuschlag, Decimal('0'))
                total = (grund + zuschlag).quantize(Decimal('0.01'))
                rechnung = DebitorenRechnung.objects.create(
                    vertrag=vertrag, liegenschaft=lg2, einheit=vertrag.einheit,
                    titel=titel, beschreibung=f"Weiterverrechnung Lieferantenrechnung {k.lieferant}"
                                              + (f" · {k.referenz}" if k.referenz else ''),
                    datum=heute, faellig_am=heute + _timedelta(days=30), betrag=total,
                    status='offen', quell_kreditor=k, weiterverrechnung_zuschlag=zuschlag)
                buche("1100", "1190", grund, f"Weiterverrechnung {vertrag.mieter}: {titel}",
                      datum=heute, liegenschaft=lg2, debitor=rechnung, kreditor=k, user=request.user)
                # Der Aufwand wurde bei der Freigabe nur mit dem NETTO gebucht (Vorsteuer
                # separat auf 1170). Die Aufwandsminderung darf ihn deshalb ebenfalls nur
                # netto entlasten; der im durchgereichten Brutto enthaltene MWST-Anteil ist
                # AUSGANGS-Umsatzsteuer (2200) — sonst würde der Aufwand negativ und die
                # zurückgeholte Vorsteuer bliebe unversteuert.
                satz = k.mwst_satz or Decimal('0')
                if satz > 0:
                    netto = (grund / (Decimal('1') + satz / Decimal('100'))).quantize(Decimal('0.01'))
                    mwst = grund - netto
                else:
                    netto, mwst = grund, Decimal('0.00')
                buche("1190", aufwand_konto, netto, f"Aufwandsminderung Weiterverrechnung: {k.lieferant}",
                      datum=heute, liegenschaft=lg2, debitor=rechnung, kreditor=k, user=request.user)
                if mwst > 0:
                    buche("1190", "2200", mwst, f"MWST Weiterverrechnung {satz}% {vertrag.mieter}",
                          datum=heute, liegenschaft=lg2, debitor=rechnung, kreditor=k, user=request.user)
                if zuschlag > 0:
                    buche("1100", "3600", zuschlag, f"Zuschlag Weiterverrechnung {vertrag.mieter}",
                          datum=heute, liegenschaft=lg2, debitor=rechnung, user=request.user)
                return rechnung, total

            # --- Doppelverrechnungs-Schutz (bindend): eine HNK-relevante Rechnung
            # fliesst bereits über die periodische NK-Abrechnung an die Mieter. Sie
            # zusätzlich direkt weiterzuverrechnen würde doppelt belasten. Nur mit
            # bewusstem Override (Häkchen) zulassen.
            if (k.is_hnk_relevant or k.hnk_betrag > 0) and request.POST.get('hnk_override') != 'on':
                messages.error(request, "Diese Rechnung ist HNK-relevant und wird bereits über die "
                                        "Nebenkostenabrechnung verteilt. Direkte Weiterverrechnung nur, wenn "
                                        "du das Häkchen «Trotzdem direkt weiterverrechnen» setzt (sonst doppelte Belastung).")
                return redirect(request.path)

            # --- Modus «verteilen»: Fremdkosten in EINEM Schritt nach Verteilschlüssel
            # auf alle aktiven Mieter der Liegenschaft aufteilen. ---
            if request.POST.get('modus') == 'verteilen':
                lg = k.liegenschaft
                if not lg:
                    messages.error(request, "Für die Verteilung muss die Rechnung einer Liegenschaft zugeordnet sein.")
                    return redirect(request.path)
                schluessel = request.POST.get('schluessel') or 'm2'
                grund_total = k.offen_weiterzuverrechnen
                if grund_total <= 0:
                    messages.error(request, "Nichts mehr offen zum Weiterverrechnen.")
                    return redirect(request.path)
                zielvertraege = list(Mietvertrag.objects.filter(status='aktiv', einheit__liegenschaft=lg)
                                     .select_related('mieter', 'einheit'))
                if not zielvertraege:
                    messages.error(request, "Keine aktiven Mietverhältnisse in dieser Liegenschaft.")
                    return redirect(request.path)

                def _gewicht(e):
                    if schluessel == 'einheit':
                        return Decimal('1')
                    if schluessel == 'wertquote':
                        return Decimal(str(e.wertquote or 0))
                    return Decimal(str(e.flaeche_m2 or 0))   # Default m²

                gew = [(v, _gewicht(v.einheit)) for v in zielvertraege if v.einheit_id]
                total_w = sum((w for _, w in gew), Decimal('0'))
                if total_w <= 0:
                    messages.error(request, "Für diesen Verteilschlüssel fehlen die Werte (m²/Wertquote) an den Objekten.")
                    return redirect(request.path)

                verteilt = Decimal('0.00'); anzahl = 0
                titel = (request.POST.get('titel') or f"Weiterverrechnung: {k.lieferant}").strip()
                for i, (v, w) in enumerate(gew):
                    anteil = (grund_total - verteilt) if i == len(gew) - 1 \
                        else (grund_total * w / total_w).quantize(Decimal('0.01'))
                    if anteil <= 0:
                        continue
                    _verrechne(v, anteil, Decimal('0'), titel)
                    verteilt += anteil; anzahl += 1
                log_aktion(request, "Weiterverrechnung verteilt", str(lg),
                           f"CHF {grund_total} aus {k.lieferant} auf {anzahl} Mieter ({schluessel})")
                messages.success(request, f"✅ CHF {grund_total} nach {schluessel} auf {anzahl} Mieter verteilt — "
                                          "QR-Rechnungen über den QR-Button in den Debitoren.")
                return redirect('/neu/debitoren/')

            # --- Einzel-Weiterverrechnung an einen Mieter ---
            vertrag_id = request.POST.get('vertrag_id')
            vertrag = Mietvertrag.objects.filter(id=vertrag_id).select_related('mieter', 'einheit__liegenschaft').first()
            if not vertrag:
                messages.error(request, "Bitte einen Mieter/Vertrag wählen.")
                return redirect(request.path)
            grund = _dec(request.POST.get('betrag'), str(k.offen_weiterzuverrechnen))
            zuschlag = _dec(request.POST.get('zuschlag'), '0')
            if grund <= 0:
                messages.error(request, "Betrag muss grösser als 0 sein.")
                return redirect(request.path)
            grund = min(grund, k.offen_weiterzuverrechnen)
            titel = (request.POST.get('titel') or f"Weiterverrechnung: {k.lieferant}").strip()
            rechnung, total = _verrechne(vertrag, grund, zuschlag, titel)

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

    # Live-Vorschau (wie bei der Ad-hoc-Rechnung): Empfänger je Vertrag + Absender
    vertrag_daten = {}
    for v in vertraege:
        m = v.mieter
        lg = v.einheit.liegenschaft if v.einheit_id else None
        vertrag_daten[str(v.id)] = {
            'mieter': m.display_name if m else '',
            'strasse': (m.strasse or '') if m else '',
            'plz': (m.plz or '') if m else '', 'ort': (m.ort or '') if m else '',
            'objekt': (v.einheit.bezeichnung if v.einheit_id else ''),
            'adresse': (f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else ''),
        }
    from crm.models import Verwaltung as _Vw
    _vw = _Vw.objects.first()
    absender = {
        'firma': _vw.firma if _vw else '', 'strasse': _vw.strasse if _vw else '',
        'plz': _vw.plz if _vw else '', 'ort': _vw.ort if _vw else '',
        'iban': (_vw.iban or '') if _vw else '',
    }
    # Verteil-Vorschau: aktive Mieter der Liegenschaft je Schlüssel
    verteil_mieter = 0
    if k.liegenschaft_id:
        verteil_mieter = Mietvertrag.objects.filter(status='aktiv', einheit__liegenschaft=k.liegenschaft).count()
    return render(request, 'fw/weiterverrechnung.html', {
        **basis, 'nav': 'kreditoren', 'k': k, 'vertraege': vertraege,
        'offen_wv': k.offen_weiterzuverrechnen, 'aufwand_konto': aufwand_konto,
        'vertrag_daten': vertrag_daten, 'absender': absender,
        'heute_iso': heute.isoformat(),
        'faellig_iso': (heute + _timedelta(days=30)).isoformat(),
        'ist_hnk': bool(k.is_hnk_relevant or k.hnk_betrag > 0),
        'verteil_mieter': verteil_mieter,
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_debitor_abschreiben(request, pk):
    """Bucht eine uneinbringliche Forderung als Debitorenverlust ab (Aufwand 3805
    an Forderungen 1100 über den offenen Betrag, Status 'abgeschrieben').
    Teilzahlungen bleiben verbucht — abgeschrieben wird nur der Rest. Grund
    (z.B. Verlustschein) wird im Beleg + Logbuch festgehalten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.booking import buche, ensure_kontenplan
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_debitoren')
    with transaction.atomic():
        # Zeilensperre: ohne sie schreiben zwei parallele Requests denselben
        # Betrag zweimal ab (Aufwand + MWST-Korrektur doppelt).
        r = get_object_or_404(
            DebitorenRechnung.objects.select_for_update().select_related('vertrag__mieter'), id=pk)
        if r.status not in ('offen', 'teilbezahlt'):
            messages.info(request, "Nur offene oder teilbezahlte Forderungen können abgeschrieben werden.")
            return redirect('fw_debitoren')
        offen = r.offener_betrag
        if offen <= 0:
            messages.info(request, "Kein offener Betrag — nichts abzuschreiben.")
            return redirect('fw_debitoren')
        grund = (request.POST.get('grund') or '').strip()
        mieter_name = r.vertrag.mieter.display_name if r.vertrag_id and r.vertrag.mieter_id else ''
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        # MWST-Korrektur (Audit K1, Entgeltsminderung Art. 41 MWSTG): Steckt im
        # offenen Betrag abgegrenzte MWST, die nie vereinnahmt wird, muss sie
        # zurückgeholt werden — sonst wird Steuer abgeliefert, die es nie gab.
        #
        # Massgebend ist, was auf DIESER Rechnung tatsächlich an MWST gebucht
        # wurde, nicht das heutige Flag am Vertrag: Wird ein Vertrag später
        # optiert, hätte das Flag auf alte steuerfreie Rechnungen eine
        # Phantom-Korrektur gebucht — und umgekehrt bei einer De-Option die
        # echte Korrektur unterschlagen.
        from django.db.models import Sum as _Sum
        from finance.models import Buchung as _B
        # Storno-Paar beidseitig ausblenden: `ist_storno=False` entfernt die
        # Gegenbuchung, `storniert_am__isnull=True` das stornierte Original.
        _mw = _B.objects.filter(debitoren_rechnung=r, ist_storno=False,
                                storniert_am__isnull=True)
        _h = _mw.filter(haben_konto__nummer='2200').aggregate(s=_Sum('betrag'))['s'] or Decimal('0.00')
        _s = _mw.filter(soll_konto__nummer='2200').aggregate(s=_Sum('betrag'))['s'] or Decimal('0.00')
        mwst_gebucht = _h - _s
        mwst_anteil = Decimal('0.00')
        if mwst_gebucht > 0 and r.betrag > 0:
            # Anteilig auf den noch offenen Teil — Teilzahlungen haben ihren
            # Steueranteil bereits vereinnahmt.
            mwst_anteil = min((mwst_gebucht * offen / r.betrag).quantize(Decimal('0.01')),
                              mwst_gebucht)
        ensure_kontenplan()
        text = f"Forderungsverlust {r.titel} {mieter_name}".strip()
        if grund:
            text += f" ({grund})"
        buche('3805', '1100', offen - mwst_anteil, text, datum=timezone.localdate(),
              liegenschaft=lg, debitor=r, user=request.user)
        if mwst_anteil > 0:
            buche('2200', '1100', mwst_anteil,
                  f"MWST-Korrektur Forderungsverlust {r.titel} (Entgeltsminderung)",
                  datum=timezone.localdate(), liegenschaft=lg, debitor=r, user=request.user)
        r.status = 'abgeschrieben'
        r.save(update_fields=['status'])
    log_aktion(request, "Forderungsverlust gebucht", r.titel,
               f"CHF {offen} · {grund or 'ohne Grundangabe'}")
    messages.success(request, f"✅ Forderung '{r.titel}' als Debitorenverlust abgeschrieben (CHF {offen}, Konto 3805).")
    return redirect('fw_debitoren')


def _mahngebuehr_historie_ausgleichen(rechnung, user=None):
    """Wird eine Mahngebühr-Forderung storniert, ist die in der Mahn-Historie
    (finance.Mahnung.gebuehr) ausgewiesene Gebühr gegenstandslos → auf 0 setzen
    (mit Vermerk). Ohne das zeigt die Historie z.B. weiter 40.-, obwohl die Gebühr
    per Gegenbuchung zurückgenommen wurde (Nutzer-Bug). Gibt die Anzahl korrigierter
    Historien-Einträge zurück."""
    import re
    from finance.models import Mahnung
    if not rechnung.stammrechnung_id:
        return 0
    m = re.match(r'\s*Mahngeb.hr\s+(\d)\.', rechnung.titel or '')
    if not m:
        return 0
    stufe = int(m.group(1))
    n = 0
    for mn in Mahnung.objects.filter(debitoren_rechnung_id=rechnung.stammrechnung_id,
                                     stufe=stufe, gebuehr__gt=0):
        alt = mn.gebuehr
        mn.gebuehr = Decimal('0.00')
        verm = f"Mahngebühr CHF {alt} storniert"
        mn.bemerkung = (f"{mn.bemerkung} · {verm}" if mn.bemerkung else verm)[:255]
        mn.save(update_fields=['gebuehr', 'bemerkung'])
        n += 1
    return n


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_debitor_stornieren(request, pk):
    """Storniert eine (versehentlich erstellte) Debitorenrechnung revisionssicher:
    Status → storniert und alle zugehörigen Buchungen werden per Gegenbuchung
    aufgehoben. Bereits (teil-)bezahlte Rechnungen werden blockiert — dort müssen
    zuerst die Zahlungen storniert werden."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchung, Zahlungseingang
    from finance.services import erstelle_storno_buchung
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

    # Abgeleitete Mahngebühren/Zins-Forderungen mitstornieren: Wird die
    # Hauptforderung aufgehoben, ist auch die darauf gestellte Mahngebühr
    # gegenstandslos. Nur unbezahlte Folgeforderungen — eine bereits bezahlte
    # Mahngebühr bräuchte erst eine Zahlungsstornierung (Live-Test E).
    folge = list(DebitorenRechnung.objects.filter(stammrechnung=r)
                 .exclude(status='storniert'))
    folge_bezahlt = [f for f in folge
                     if Zahlungseingang.objects.filter(debitoren_rechnung=f, status='verbucht').exists()]
    n_folge = 0
    with transaction.atomic():
        # Nur noch nicht stornierte Originale umkehren (Doppel-Storno-Schutz).
        for b in Buchung.objects.filter(debitoren_rechnung=r, ist_storno=False,
                                        storniert_am__isnull=True):
            erstelle_storno_buchung(b, benutzer=request.user)
        r.status = 'storniert'
        r.save()
        # Wird eine Mahngebühr-Forderung selbst storniert, die Historien-Gebühr
        # gleich mit auf 0 ziehen (sonst zeigt die Mahn-Historie weiter z.B. 40.-).
        _mahngebuehr_historie_ausgleichen(r, request.user)
        for f in folge:
            if f in folge_bezahlt:
                continue
            for b in Buchung.objects.filter(debitoren_rechnung=f, ist_storno=False,
                                            storniert_am__isnull=True):
                erstelle_storno_buchung(b, benutzer=request.user)
            f.status = 'storniert'
            f.save(update_fields=['status'])
            _mahngebuehr_historie_ausgleichen(f, request.user)
            n_folge += 1

    log_aktion(request, "Debitorenrechnung storniert", r.titel,
               f"CHF {r.betrag}" + (f" · {n_folge} Mahngebühr(en) mitstorniert" if n_folge else ""))
    hinweis = f" {n_folge} zugehörige Mahngebühr(en) mitstorniert." if n_folge else ""
    if folge_bezahlt:
        hinweis += (f" {len(folge_bezahlt)} bereits bezahlte Mahngebühr(en) blieben bestehen — "
                    f"dort zuerst die Zahlung stornieren.")
    messages.success(request, f"✅ Rechnung '{r.titel}' storniert (revisionssicher, mit Gegenbuchung).{hinweis}")
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

    # Drei Abfragen für das ganze Portfolio statt fünf je Liegenschaft. Die
    # Liste ist der Einstieg in die Bewirtschaftung und wurde bei 38
    # Liegenschaften mit 195 Abfragen aufgebaut — das wächst linear mit dem
    # Bestand und bremst auf einem Ein-Worker-Hosting spürbar.
    lgs = list(liegenschaften)
    lg_ids = [lg.id for lg in lgs]

    einheiten_je_lg = defaultdict(list)
    for e_id, e_lg in Einheit.objects.filter(
            liegenschaft_id__in=lg_ids).values_list('id', 'liegenschaft_id'):
        einheiten_je_lg[e_lg].append(e_id)

    belegt_je_lg = defaultdict(set)
    ertrag_je_lg = defaultdict(lambda: Decimal('0.00'))
    vertraege_je_lg = defaultdict(int)
    vertrag_lg = {}
    for v_id, v_lg, e_id, netto, nk in Mietvertrag.objects.filter(
            status='aktiv', einheit__liegenschaft_id__in=lg_ids).values_list(
            'id', 'einheit__liegenschaft_id', 'einheit_id', 'netto_mietzins', 'nebenkosten'):
        vertrag_lg[v_id] = v_lg
        vertraege_je_lg[v_lg] += 1
        ertrag_je_lg[v_lg] += (netto or Decimal('0')) + (nk or Decimal('0'))
        if e_id:
            belegt_je_lg[v_lg].add(e_id)

    # Nebenobjekte (Parkplatz, Keller) zählen als belegt. Zugeordnet werden sie
    # der Liegenschaft des HAUPTobjekts — wie bisher; ein Parkplatz in einer
    # anderen Liegenschaft färbt deren Leerstand also nicht ein.
    if vertrag_lg:
        for v_id, neben_id in Mietvertrag.objects.filter(
                id__in=vertrag_lg).values_list('id', 'nebenobjekte'):
            if neben_id:
                belegt_je_lg[vertrag_lg[v_id]].add(neben_id)

    rows = []
    for lg in lgs:
        einheiten = einheiten_je_lg.get(lg.id, [])
        belegte = belegt_je_lg.get(lg.id, set())
        anzahl = len(einheiten)
        leer = sum(1 for e_id in einheiten if e_id not in belegte)
        belegt = anzahl - leer
        rows.append({'lg': lg, 'einheiten_count': anzahl,
                     'leer': leer, 'belegt': belegt,
                     'verm_pct': round(belegt / anzahl * 100) if anzahl else 0,
                     'mietertrag': ertrag_je_lg[lg.id],
                     'vertraege_count': vertraege_je_lg[lg.id]})

    return render(request, 'fw/liegenschaften.html', {
        **basis, 'nav': 'liegenschaften', 'rows': rows,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_berichte(request):
    """Berichte & Auswertungen — ein zentraler Ort für alle Reports/Exporte,
    mit ein paar aktuellen Kennzahlen je Bericht."""
    from finance.models import KreditorenRechnung
    from tickets.models import HandwerkerAuftrag
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    # --- Forderungen (Debitoren) ---
    deb = DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
    if aktive_lg:
        deb = deb.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))
    deb = [r for r in deb.select_related('vertrag').prefetch_related('zahlungseingaenge') if r.offener_betrag > 0]
    deb_offen = sum((r.offener_betrag for r in deb), Decimal('0.00'))
    deb_ueberf = sum((r.offener_betrag for r in deb
                      if (r.faellig_am or r.datum) and (r.faellig_am or r.datum) < heute), Decimal('0.00'))

    # --- Verbindlichkeiten (Kreditoren) ---
    kred = KreditorenRechnung.objects.exclude(status='storniert')
    if aktive_lg:
        kred = kred.filter(liegenschaft=aktive_lg)
    kred = kred.prefetch_related('zahlungen', 'weiterverrechnungen')
    kred_offen = sum((k.offener_betrag for k in kred), Decimal('0.00'))

    # --- Portfolio (Soll-Mietzins / Leerstand) ---
    einh = Einheit.objects.all()
    if aktive_lg:
        einh = einh.filter(liegenschaft=aktive_lg)
    einh = list(einh)
    belegte = set(Mietvertrag.objects.filter(status='aktiv').values_list('einheit_id', flat=True))
    for nid in Mietvertrag.objects.filter(status='aktiv').values_list('nebenobjekte', flat=True):
        if nid:
            belegte.add(nid)
    soll_mietzins = sum(((e.nettomiete_aktuell or Decimal('0')) + (e.nebenkosten_aktuell or Decimal('0')) for e in einh), Decimal('0.00'))
    leer_n = sum(1 for e in einh if e.id not in belegte)
    leerstandsquote = round(leer_n / len(einh) * 100, 1) if einh else 0.0

    # --- Reparaturkosten laufendes Jahr (effektiv) ---
    auf = HandwerkerAuftrag.objects.filter(beauftragt_am__year=heute.year)
    if aktive_lg:
        auf = auf.filter(ticket__liegenschaft=aktive_lg)
    reparatur_eff = sum((a.kosten_effektiv or Decimal('0') for a in auf), Decimal('0.00'))

    lgq = basis['lg_query']
    berichte = [
        {'gruppe': 'Finanzen', 'items': [
            {'icon': 'fa-calculator', 'farbe': 'indigo', 'titel': 'Erfolgsrechnung & Bilanz',
             'sub': 'Ertrag/Aufwand, Aktiven/Passiven, Journal', 'url': '/neu/buchhaltung/' + lgq,
             'kennzahl': None, 'pdf': True},
            {'icon': 'fa-percent', 'farbe': 'violet', 'titel': 'MWST-Abrechnung',
             'sub': 'Umsatz-/Vorsteuer, ESTV-Export', 'url': '/neu/mwst/', 'kennzahl': None, 'pdf': False},
            {'icon': 'fa-gauge-high', 'farbe': 'sky', 'titel': 'Finanz-Cockpit',
             'sub': 'Arbeitskorb + Monatsabschluss', 'url': '/neu/finanzen/' + lgq, 'kennzahl': None, 'pdf': False},
        ]},
        {'gruppe': 'Forderungen & Zahlungen', 'items': [
            {'icon': 'fa-chart-column', 'farbe': 'rose', 'titel': 'Debitoren-Altersstruktur',
             'sub': 'Offene Forderungen nach Fälligkeitsalter', 'url': '/neu/mahnwesen/aging/' + lgq,
             'kennzahl': f"CHF {deb_ueberf:,.0f} überfällig".replace(',', "'"), 'pdf': False},
            {'icon': 'fa-file-invoice-dollar', 'farbe': 'indigo', 'titel': 'Mieterkonten',
             'sub': 'Kontoblatt je Mieter (Forderungen/Zahlungen)', 'url': '/neu/mieterkonten/' + lgq,
             'kennzahl': f"CHF {deb_offen:,.0f} offen".replace(',', "'"), 'pdf': True},
            {'icon': 'fa-file-invoice', 'farbe': 'amber', 'titel': 'Lieferantenkonten',
             'sub': 'Kontoblatt je Lieferant (Kreditoren)', 'url': '/neu/lieferantenkonten/' + lgq,
             'kennzahl': f"CHF {kred_offen:,.0f} offen".replace(',', "'"), 'pdf': False},
        ]},
        {'gruppe': 'Portfolio', 'items': [
            {'icon': 'fa-table-list', 'farbe': 'emerald', 'titel': 'Mieterspiegel',
             'sub': 'Rent Roll je Liegenschaft (Soll/Ist/Leerstand)', 'url': '/neu/mieterspiegel/' + lgq,
             'kennzahl': f"CHF {soll_mietzins:,.0f} Soll · {leerstandsquote}% leer".replace(',', "'"), 'pdf': True},
            {'icon': 'fa-scale-balanced', 'farbe': 'teal', 'titel': 'Eigentümer-Abrechnungen',
             'sub': 'Mandatsabrechnung & Kontokorrent je Eigentümer', 'url': '/neu/mandate/',
             'kennzahl': None, 'pdf': True},
        ]},
        {'gruppe': 'Objekte & Unterhalt', 'items': [
            {'icon': 'fa-coins', 'farbe': 'orange', 'titel': 'Reparaturkosten',
             'sub': 'Kosten je Liegenschaft (offen/effektiv)', 'url': '/neu/schaeden/kosten/' + lgq,
             'kennzahl': f"CHF {reparatur_eff:,.0f} {heute.year}".replace(',', "'"), 'pdf': False},
            {'icon': 'fa-bullhorn', 'farbe': 'sky', 'titel': 'Objekt-Feed (Portale)',
             'sub': 'Vermarktungs-Feed für Homegate/Flatfox', 'url': '/neu/integrationen/',
             'kennzahl': None, 'pdf': False},
        ]},
    ]
    return render(request, 'fw/berichte.html', {**basis, 'nav': 'berichte', 'berichte': berichte})


AUSWERTUNG_TYPEN = [
    ('mietertrag', 'Mietertrag', 'ertrag'),
    ('aufwand', 'Aufwand (total)', 'aufwand'),
    ('reparatur', 'Reparaturen (Unterhalt)', 'aufwand'),
    ('ergebnis', 'Nettoergebnis', 'ergebnis'),
]


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_betriebsrechnung_pdf(request, pk):
    """Gebäudescharfe Betriebsrechnung (Ertrag − Aufwand) einer Liegenschaft als
    PDF, für ein wählbares Kalenderjahr (?jahr=YYYY)."""
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from core.services.gebaeude_report import betriebsrechnung_pdf
    lg = get_object_or_404(Liegenschaft, id=pk)
    try:
        jahr = int(request.GET.get('jahr') or timezone.localdate().year)
    except ValueError:
        jahr = timezone.localdate().year
    pdf = betriebsrechnung_pdf(lg, jahr, verwaltung=Verwaltung.objects.first())
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Betriebsrechnung_{jahr}_{lg.strasse}.pdf"'
    return resp


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_leerstand_verlauf(request):
    """Leerstands-Zeitverlauf: monatliche Leerquote über die letzten Monate,
    fürs ganze Portfolio oder gefiltert auf die aktive Liegenschaft."""
    from core.services.rendite import leerstand_zeitverlauf
    basis = _global_filter(request)
    aktive_lg = basis.get('aktive_lg')
    try:
        monate = max(3, min(36, int(request.GET.get('monate') or 12)))
    except ValueError:
        monate = 12
    reihe = leerstand_zeitverlauf(lg=aktive_lg, monate=monate)
    max_quote = max((r['quote'] for r in reihe), default=0.0)
    schnitt = round(sum(r['quote'] for r in reihe) / len(reihe), 1) if reihe else 0.0
    aktuell_quote = reihe[-1]['quote'] if reihe else 0.0
    return render(request, 'fw/leerstand_verlauf.html', {
        **basis, 'nav': 'berichte', 'reihe': reihe, 'monate': monate,
        'max_quote': max_quote, 'schnitt': schnitt, 'aktuell_quote': aktuell_quote,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_betriebskostenspiegel(request):
    """Betriebs-/Nebenkostenspiegel: Aufwand je Liegenschaft und Jahr, umgelegt
    auf CHF/m² — quervergleichbar über das Portfolio."""
    from finance.models import Buchung
    from django.db.models import Sum
    basis = _global_filter(request)
    heute = timezone.localdate()
    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    von, bis = date(jahr, 1, 1), date(jahr, 12, 31)
    lgs = list(Liegenschaft.objects.all().order_by('strasse'))
    if basis['aktive_lg']:
        lgs = [lg for lg in lgs if lg.id == basis['aktive_lg'].id]

    # Aufwand und Fläche in je EINER gruppierten Abfrage, nicht zwei je
    # Liegenschaft — sonst wächst der Seitenaufbau linear mit dem Portfolio.
    lg_ids = [lg.id for lg in lgs]
    kosten_je_lg = {
        r['liegenschaft']: r['s'] for r in
        Buchung.objects.filter(liegenschaft_id__in=lg_ids, datum__gte=von, datum__lte=bis,
                               soll_konto__typ='aufwand', ist_storno=False,
                               storniert_am__isnull=True)
        .order_by().values('liegenschaft').annotate(s=Sum('betrag'))}
    m2_je_lg = {
        r['liegenschaft']: r['s'] for r in
        Einheit.objects.filter(liegenschaft_id__in=lg_ids)
        .order_by().values('liegenschaft').annotate(s=Sum('flaeche_m2'))}

    rows, total_kosten, total_m2 = [], Decimal('0.00'), Decimal('0.00')
    for lg in lgs:
        kosten = kosten_je_lg.get(lg.id) or Decimal('0.00')
        m2 = m2_je_lg.get(lg.id) or Decimal('0.00')
        pro_m2 = (kosten / m2) if m2 else None
        rows.append({'lg': lg, 'kosten': kosten, 'm2': m2, 'pro_m2': pro_m2})
        total_kosten += kosten
        total_m2 += m2
    schnitt = (total_kosten / total_m2) if total_m2 else None
    # Farb-/Vergleichsmarker relativ zum Portfolioschnitt.
    for r in rows:
        if r['pro_m2'] is not None and schnitt:
            r['abweichung'] = (r['pro_m2'] - schnitt)
    return render(request, 'fw/betriebskostenspiegel.html', {
        **basis, 'nav': 'berichte', 'rows': rows, 'jahr': jahr,
        'total_kosten': total_kosten, 'total_m2': total_m2, 'schnitt': schnitt,
        'jahre': list(range(heute.year, heute.year - 6, -1)),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_auswertung(request):
    """Interaktive Auswertung: Kennzahl (Mietertrag/Aufwand/Reparaturen/Ergebnis)
    im Monatsverlauf eines Jahres + Vergleich je Liegenschaft — mit Filtern."""
    from finance.models import Buchung, Buchungskonto
    from django.db.models import Sum
    import calendar as _cal
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    typ = request.GET.get('typ', 'mietertrag')
    if typ not in dict((t[0], t) for t in AUSWERTUNG_TYPEN):
        typ = 'mietertrag'
    typ_label = dict((t[0], t[1]) for t in AUSWERTUNG_TYPEN)[typ]

    # Ein Durchgang durch den Kontenplan statt vier — die Zuordnung geschieht
    # danach in Python.
    ertrag_konten, aufwand_konten, mietertrag_konten, reparatur_konten = [], [], [], []
    for kid, ktyp, knr in Buchungskonto.objects.values_list('id', 'typ', 'nummer'):
        if ktyp == 'ertrag':
            ertrag_konten.append(kid)
        elif ktyp == 'aufwand':
            aufwand_konten.append(kid)
        if knr in ('3000', '3010'):
            mietertrag_konten.append(kid)
        elif knr == '4000':
            reparatur_konten.append(kid)

    # Ein storniertes Original zählte hier weiter, seine Gegenbuchung war
    # ausgeblendet — der Storno hob sich in der Auswertung also nie auf.
    base_q = Buchung.objects.filter(datum__year=jahr, ist_storno=False,
                                    storniert_am__isnull=True)
    if aktive_lg:
        base_q = base_q.filter(liegenschaft=aktive_lg)

    def _summen(bqs, gruppe):
        """Soll- und Haben-Summen je (Gruppenwert, Konto) — ZWEI Abfragen für
        die ganze Auswertung.

        Vorher wurde je Monat und je Liegenschaft einzeln aggregiert: bei der
        Kennzahl «Ergebnis» vier Abfragen pro Zelle, also 48 allein für den
        Monatsverlauf plus vier je Liegenschaft. Das wächst mit dem Portfolio,
        obwohl die Datenmenge dieselbe bleibt — gruppiert holt die Datenbank
        alles in einem Durchgang."""
        def hol(feld):
            werte = {}
            for r in bqs.order_by().values(gruppe, feld).annotate(t=Sum('betrag')):
                werte.setdefault(r[gruppe], {})[r[feld]] = r['t']
            return werte
        return hol('soll_konto'), hol('haben_konto')

    def _wert(soll_map, haben_map, schluessel):
        """Kennzahl für eine Gruppe (ein Monat / eine Liegenschaft)."""
        def saldo(kids, positiv_haben):
            if not kids:
                return Decimal('0.00')
            kset = set(kids)
            s = sum((b for k, b in soll_map.get(schluessel, {}).items() if k in kset),
                    Decimal('0.00'))
            h = sum((b for k, b in haben_map.get(schluessel, {}).items() if k in kset),
                    Decimal('0.00'))
            return (h - s) if positiv_haben else (s - h)
        if typ == 'mietertrag':
            return saldo(mietertrag_konten, True)
        if typ == 'aufwand':
            return saldo(aufwand_konten, False)
        if typ == 'reparatur':
            return saldo(reparatur_konten, False)
        return saldo(ertrag_konten, True) - saldo(aufwand_konten, False)   # ergebnis

    # Monatsverlauf
    m_soll, m_haben = _summen(base_q.annotate(_mon=ExtractMonth('datum')), '_mon')
    monate = []
    max_abs = Decimal('0.01')
    total = Decimal('0.00')
    for m in range(1, 13):
        w = _wert(m_soll, m_haben, m)
        monate.append({'m': m, 'name': date(2000, m, 1).strftime('%b'), 'wert': w})
        total += w
        if abs(w) > max_abs:
            max_abs = abs(w)
    for mm in monate:
        mm['pct'] = int(abs(mm['wert']) / max_abs * 100)
        mm['neg'] = mm['wert'] < 0

    # Vergleich je Liegenschaft (nur ohne aktiven LG-Filter sinnvoll)
    lg_rows = []
    if not aktive_lg:
        lg_soll, lg_haben = _summen(base_q, 'liegenschaft')
        max_lg = Decimal('0.01')
        for lg in Liegenschaft.objects.order_by('strasse'):
            w = _wert(lg_soll, lg_haben, lg.id)
            if w == 0:
                continue
            lg_rows.append({'lg': lg, 'wert': w})
            if abs(w) > max_lg:
                max_lg = abs(w)
        lg_rows.sort(key=lambda r: -r['wert'])
        for r in lg_rows:
            r['pct'] = int(abs(r['wert']) / max_lg * 100)
            r['neg'] = r['wert'] < 0

    if request.GET.get('pdf') == '1':
        from crm.models import Verwaltung
        from core.services.auswertung_pdf import generate_auswertung_pdf
        from django.http import HttpResponse
        lg_name = f"{aktive_lg.strasse}, {aktive_lg.ort}" if aktive_lg else "Alle Liegenschaften"
        pdf = generate_auswertung_pdf(typ_label, jahr, lg_name, total, monate, lg_rows,
                                      Verwaltung.objects.first())
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Auswertung_{typ}_{jahr}.pdf"'
        return resp

    return render(request, 'fw/auswertung.html', {
        **basis, 'nav': 'auswertung', 'jahr': jahr, 'typ': typ, 'typ_label': typ_label,
        'typen': AUSWERTUNG_TYPEN, 'jahre': list(range(heute.year, heute.year - 6, -1)),
        'monate': monate, 'total': total, 'lg_rows': lg_rows,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterspiegel(request):
    """Mieterspiegel (Rent Roll) — immer pro Liegenschaft. Ohne Auswahl eine
    Übersicht aller Liegenschaften zur Auswahl; mit Auswahl der Rent Roll der
    einzelnen Liegenschaft (On-Screen und als PDF)."""
    from core.services.mieterspiegel import berechne_mieterspiegel, generate_mieterspiegel_pdf
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    alle_lgs = list(Liegenschaft.objects.order_by('strasse'))

    # Keine Liegenschaft gewählt → Auswahl-Übersicht (eine Karte je Liegenschaft)
    if not aktive_lg:
        uebersicht = berechne_mieterspiegel(alle_lgs)
        return render(request, 'fw/mieterspiegel_auswahl.html', {
            **basis, 'nav': 'liegenschaften', 'uebersicht': uebersicht,
            'stichtag': timezone.localdate(),
        })

    spiegel = berechne_mieterspiegel([aktive_lg])

    if request.GET.get('pdf') == '1':
        from crm.models import Verwaltung
        from django.http import HttpResponse
        pdf = generate_mieterspiegel_pdf(spiegel, Verwaltung.objects.first(), stichtag=timezone.localdate())
        resp = HttpResponse(pdf, content_type='application/pdf')
        fname = (aktive_lg.strasse or 'Mieterspiegel').replace(' ', '_')
        resp['Content-Disposition'] = f'inline; filename="Mieterspiegel_{fname}.pdf"'
        return resp

    # Kennzahlen der EINEN gewählten Liegenschaft (kein Gesamttotal über alle)
    b = spiegel[0] if spiegel else None
    gesamt = b['totals'] if b else {
        'soll_brutto': Decimal('0.00'), 'ist_brutto': Decimal('0.00'),
        'leer_fr': Decimal('0.00'), 'anzahl': 0, 'leer': 0, 'leerstandsquote': 0.0}

    return render(request, 'fw/mieterspiegel.html', {
        **basis, 'nav': 'liegenschaften', 'spiegel': spiegel, 'gesamt': gesamt,
        'stichtag': timezone.localdate(), 'alle_lgs': alle_lgs,
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

    # Nach Liegenschaft gruppieren (Überschrift + Akkordeon je Liegenschaft)
    gruppen = []
    for row in rows:
        lg = row['e'].liegenschaft
        if gruppen and gruppen[-1]['lg'].id == lg.id:
            gruppen[-1]['rows'].append(row)
        else:
            gruppen.append({'lg': lg, 'rows': [row]})
    for g in gruppen:
        g['anzahl'] = len(g['rows'])
        g['belegt'] = sum(1 for r in g['rows'] if r['mieter'])
        g['leer'] = g['anzahl'] - g['belegt']

    return render(request, 'fw/objekte.html', {
        **basis, 'nav': 'objekte', 'rows': rows, 'gruppen': gruppen,
        'typ_filter': typ_filter, 'q': q,
        'typ_chips': [('', 'Alle'), ('wohnen', 'Wohnen'), ('parkplatz', 'Parkplatz'), ('gewerbe', 'Gewerbe')],
        'vermietet_count': vermietet_count,
        'leer_count': len(rows) - vermietet_count,
    })

# Design-System-Chip-Variante je Status (fw-chip fw-<variant>)
VERTRAG_CHIP = {'aktiv': 'good', 'gekuendigt': 'crit',
                'entwurf': 'mut', 'archiviert': 'mut'}


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
            'chip': VERTRAG_CHIP.get(v.status, 'mut'),
        })

    return render(request, 'fw/vertraege.html', {
        **basis, **_vermietung_pipeline('vertraege', basis['lg_query']), 'nav': 'vertraege', 'rows': rows,
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
                       | Q(firmen_name__icontains=q) | Q(email__icontains=q) | Q(ort__icontains=q)
                       | Q(mobile__icontains=q) | Q(telefon_privat__icontains=q)
                       | Q(telefon_geschaeft__icontains=q))

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

    lg = get_object_or_404(Liegenschaft.objects.select_related('eigentuemer', 'verwaltung'), id=pk)
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

    # Dokumente der Liegenschaft — nach Objekt (Einheit) gruppiert. Vertrags-
    # gebundene Dokumente (Mietvertrag, Mietzinsanpassung, Kündigung …) erscheinen
    # hier bewusst NICHT — sie leben am Mietverhältnis (Objekt → «Verhältnisse»)
    # und bei der Person. Der Liegenschafts-Tab zeigt nur gebäude-/objektbezogene
    # Dokumente ohne Vertragsbezug (Versicherung, Pläne, Reglemente …).
    einheiten = [row['einheit'] for row in einheiten_rows]
    from collections import defaultdict
    buckets = defaultdict(list)
    from datetime import datetime as _dt
    def _sortkey(val):
        # date ODER datetime → immer als datetime vergleichbar machen
        if val is None:
            return _dt.min
        if isinstance(val, _dt):
            return val.replace(tzinfo=None)
        return _dt.combine(val, _dt.min.time())
    for d in (RentalsDokument.objects
              .filter(Q(liegenschaft=lg) | Q(einheit__liegenschaft=lg))
              .filter(vertrag__isnull=True)
              .select_related('einheit').distinct().order_by('-datum')):
        eid = d.einheit_id
        buckets[eid].append({'titel': d.bezeichnung or d.titel, 'kategorie': d.kategorie,
                             'datum': d.ablage_zeit, 'url': d.datei.url if d.datei else None,
                             'id': d.id, 'del_url': f'/neu/dokument/{d.id}/loeschen/'})
    for d in (PortfolioDokument.objects
              .filter(Q(liegenschaft=lg) | Q(einheit__liegenschaft=lg))
              .select_related('einheit').distinct().order_by('-datum')):
        buckets[d.einheit_id].append({'titel': d.titel, 'kategorie': d.kategorie,
                                      'datum': d.datum, 'url': d.datei.url if d.datei else None,
                                      'id': d.id, 'del_url': f'/neu/dokumente/{d.id}/loeschen/'})
    for lst in buckets.values():
        lst.sort(key=lambda d: _sortkey(d['datum']), reverse=True)
    # Reihenfolge: Liegenschaft (allgemein) zuerst, dann je Objekt
    dok_gruppen = []
    if buckets.get(None):
        dok_gruppen.append({'einheit': None, 'label': 'Liegenschaft (allgemein)',
                            'dokumente': buckets[None]})
    for e in einheiten:
        if buckets.get(e.id):
            dok_gruppen.append({'einheit': e, 'label': e.bezeichnung,
                                'dokumente': buckets[e.id]})
    dok_total = sum(len(g['dokumente']) for g in dok_gruppen)

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

    # Technik: allgemeine Geräte (Heizung/Boiler/…) + Zähler (Allgemeinstrom/…)
    from portfolio.models import Geraet, Zaehler
    lg_geraete = list(Geraet.objects.filter(liegenschaft=lg).order_by('kategorie'))
    lg_zaehler = list(Zaehler.objects.filter(liegenschaft=lg).order_by('typ'))
    technik_count = len(lg_geraete) + len(lg_zaehler)

    tab_liste = [
        ('objekte', 'Objekte', len(einheiten_rows)),
        ('finanzen', 'Finanzen', None),
        ('technik', 'Technik', technik_count or None),
        ('unterhalt', 'Unterhalt', unterhalt.count() or None),
        ('fristen', 'Fristen', len(wartungsfristen) or None),
        ('schaeden', 'Schäden', tickets.count() or None),
        ('dokumente', 'Dokumente', dok_total or None),
    ]
    from core.services.rendite import liegenschaft_rendite
    rendite = liegenschaft_rendite(lg)
    return render(request, 'fw/liegenschaft_detail.html', {
        **basis, 'nav': 'liegenschaften', 'lg': lg,
        'einheiten_rows': einheiten_rows,
        'total_einheiten': len(einheiten_rows),
        'vermietet': vermietet,
        'leerstand': len(einheiten_rows) - vermietet,
        'soll_monat': soll_monat,
        'rendite': rendite,
        'tickets': tickets,
        'dok_gruppen': dok_gruppen,
        'dok_total': dok_total,
        'unterhalt': unterhalt,
        'wartungsfristen': wartungsfristen,
        'perioden': perioden,
        'versicherungen': list(lg.versicherungen.all()),
        'heute_iso': timezone.localdate().isoformat(),
        'lg_geraete': lg_geraete,
        'lg_zaehler': lg_zaehler,
        'geraet_kategorien': GERAET_KATEGORIEN,
        'zaehler_typen': ZAEHLER_TYPEN,
        'tab_liste': tab_liste,
    })


# Kuratierte Standard-Ausstattungsmerkmale (CH) für die schnelle Häkchen-Liste
MERKMALE_STANDARD = [
    'Balkon', 'Terrasse', 'Sitzplatz', 'Garten (Mitbenützung)', 'Lift',
    'Einbauküche', 'Geschirrspüler', 'Glaskeramik-Kochfeld', 'Steamer / Dampfgarer',
    'Waschmaschine (in Wohnung)', 'Waschturm', 'Anschluss Waschmaschine',
    'Keller / Kellerabteil', 'Estrich / Estrichabteil', 'Reduit',
    'Cheminée', 'Parkett', 'Plattenboden', 'Laminat',
    'Bad/WC', 'Sep. WC', 'Dusche', 'Badewanne',
    'Kabel-TV', 'Glasfaser', 'Rollläden / Storen', 'Lamellenstoren',
    'Barrierefrei / Rollstuhlgängig', 'Minergie', 'Bodenheizung',
    'Garage', 'Aussenparkplatz', 'Veloraum', 'Trockenraum',
    'Möbliert', 'Haustiere erlaubt',
]


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_merkmale_speichern(request, pk):
    """Speichert die Ausstattungsmerkmale (Häkchen + eigene) eines Objekts."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    e = get_object_or_404(Einheit, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{e.id}/')
    gewaehlt = [m.strip() for m in request.POST.getlist('merkmale') if m.strip()]
    # Eigene Merkmale (Komma- oder Zeilen-getrennt) ergänzen
    eigene = (request.POST.get('merkmale_eigene') or '').replace('\n', ',')
    for m in eigene.split(','):
        m = m.strip()
        if m and m not in gewaehlt:
            gewaehlt.append(m)
    # Reihenfolge stabil + dedupliziert
    seen, clean = set(), []
    for m in gewaehlt:
        if m not in seen:
            seen.add(m); clean.append(m)
    e.merkmale = clean
    e.save(update_fields=['merkmale'])
    log_aktion(request, "Ausstattungsmerkmale gespeichert", e.bezeichnung, f"{len(clean)} Merkmale")
    messages.success(request, "✅ Ausstattungsmerkmale gespeichert.")
    return redirect(f'/neu/objekte/{e.id}/')


def merkmale_optionen(aktuelle=None):
    """Standardliste + alle bereits irgendwo verwendeten eigenen Merkmale."""
    optionen = list(MERKMALE_STANDARD)
    seen = set(optionen)
    for e in Einheit.objects.exclude(merkmale=[]).only('merkmale'):
        for m in (e.merkmale or []):
            if m and m not in seen:
                seen.add(m); optionen.append(m)
    for m in (aktuelle or []):
        if m and m not in seen:
            seen.add(m); optionen.append(m)
    return optionen


# Vorschlagslisten (datalist) für Geräte-Kategorien und Zähler-Typen
GERAET_KATEGORIEN = [
    'Heizung', 'Boiler / Wassererwärmer', 'Wärmepumpe', 'Lüftung', 'Klimaanlage',
    'Aufzug', 'Waschmaschine', 'Tumbler', 'Geschirrspüler', 'Backofen', 'Kochfeld',
    'Kühlschrank', 'Dampfabzug', 'Rauchmelder', 'Solaranlage', 'Photovoltaik',
    'Gartengerät', 'Tor / Antrieb', 'Sonstiges',
]
ZAEHLER_TYPEN = [
    'Allgemeinstrom', 'Strom', 'Wasser kalt', 'Wasser warm', 'Gas',
    'Wärmezähler', 'Öl', 'Fernwärme', 'Sonstiges',
]


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
        from core.models import Pendenz
        bez = f"{wf.bezeichnung} · {wf.liegenschaft}"
        # Zugehörige Auto-Frist-Pendenz(en) mitlöschen — sie hängen nur über einen
        # `quelle`-String (kein FK) und würden sonst als verwaiste Frist stehen bleiben.
        Pendenz.objects.filter(quelle__startswith=f"auto:wartung:{wf.id}:").delete()
        wf.delete()
        log_aktion(request, "Wartungsfrist gelöscht", bez, '')
        messages.success(request, "🗑️ Frist gelöscht.")
    return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_wartungsfrist_bearbeiten(request, pk):
    """Wartungs-/Versicherungsfrist bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Wartungsfrist
    from core.auth import log_aktion
    wf = get_object_or_404(Wartungsfrist.objects.select_related('liegenschaft'), id=pk)
    lg_id = wf.liegenschaft_id
    if request.method != 'POST':
        return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')
    bez = (request.POST.get('bezeichnung') or '').strip()
    faellig = (request.POST.get('naechste_faelligkeit') or '').strip()
    if not bez or not faellig:
        messages.error(request, "Bezeichnung und Fälligkeitsdatum sind erforderlich.")
        return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')
    try:
        wf.naechste_faelligkeit = date.fromisoformat(faellig)
    except ValueError:
        messages.error(request, "Ungültiges Datum.")
        return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')
    wf.art = request.POST.get('art', wf.art) or wf.art
    wf.bezeichnung = bez
    wf.anbieter = (request.POST.get('anbieter') or '').strip()
    try:
        wf.intervall_monate = max(0, int(request.POST.get('intervall_monate') or wf.intervall_monate))
    except ValueError:
        pass
    wf.notiz = (request.POST.get('notiz') or '').strip()
    wf.save()
    log_aktion(request, "Wartungsfrist bearbeitet", bez, '')
    messages.success(request, f'✅ Frist „{bez}" aktualisiert.')
    return redirect(f'/neu/liegenschaften/{lg_id}/?tab=fristen')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_objekt_detail(request, pk):
    from portfolio.models import Geraet, Zaehler, Ausstattung
    from core.services.raumkatalog import RAUMTYPEN, RAUM_KATALOG
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=pk)
    basis = _global_filter(request)

    aktiver_vertrag = (Mietvertrag.objects.filter(einheit=e, status='aktiv')
                       .select_related('mieter').order_by('-beginn').first())
    if not aktiver_vertrag:
        aktiver_vertrag = (Mietvertrag.objects
                           .filter(nebenobjekte=e, status='aktiv')
                           .select_related('mieter').order_by('-beginn').first())
    # «Verhältnisse»: jedes Mietverhältnis (= Vertrag) an diesem Objekt — aktiv
    # UND beendet — als Bündel mit den zugehörigen Dokumenten (Vertrag, Mietzins-
    # anpassung, Kündigung, Protokoll …). Das Verhältnis IST der Vertrag; die
    # Dokumente hängen bereits per FK daran (rentals.Dokument.vertrag).
    from rentals.models import Dokument as RentalsDokument
    from django.db.models import Q as _Q
    from collections import defaultdict
    _vertraege = (Mietvertrag.objects.filter(_Q(einheit=e) | _Q(nebenobjekte=e))
                  .select_related('mieter', 'mitmieter')
                  .distinct().order_by('-beginn'))
    _dok_pro_vertrag = defaultdict(list)
    for d in (RentalsDokument.objects.filter(vertrag__in=_vertraege)
              .order_by('-datum')):
        _dok_pro_vertrag[d.vertrag_id].append(d)
    verhaeltnisse = []
    for v in _vertraege:
        namen = [v.mieter.display_name if v.mieter else '']
        if v.mitmieter_id:
            namen.append(v.mitmieter.display_name)
        elif v.mitmieter_name:
            namen.append(v.mitmieter_name)
        verhaeltnisse.append({
            'v': v,
            'namen': ' · '.join(n for n in namen if n),
            'pill': _vertrag_status_pill(v),
            'dokumente': _dok_pro_vertrag.get(v.id, []),
        })
    verhaeltnisse_dok_total = sum(len(x['dokumente']) for x in verhaeltnisse)

    geraete = Geraet.objects.filter(einheit=e).order_by('kategorie')
    zaehler = Zaehler.objects.filter(einheit=e).order_by('typ')
    fotos = list(e.fotos.all())

    # Sollmietzins-Komponenten (datierte Netto-/NK-Historie). Die aktuell gültige
    # Zeile wird markiert; sie steuert nettomiete_aktuell/nebenkosten_aktuell.
    sollmietzinse = list(e.sollmietzinse.all())
    aktueller_soll = e.aktueller_sollmietzins()
    aktueller_soll_id = aktueller_soll.id if aktueller_soll else None

    # Staffelmiete (Art. 269c):
    #  - OBJEKT-Vorlage (Plan, belegt neue Verträge vor) — wie Sollmietzins.
    #  - Stufen des AKTIVEN Vertrags (live, verrechnungswirksam) — nur wenn der
    #    laufende Vertrag tatsächlich eine Staffelmiete ist.
    staffelvorlagen = list(e.staffelvorlagen.all())
    zeige_staffelvorlage = (e.mietrecht_kategorie == 'gewerbe')
    staffelstufen = list(aktiver_vertrag.staffelstufen.all()) if aktiver_vertrag else []
    zeige_staffel = bool(aktiver_vertrag) and aktiver_vertrag.mietzins_modell == 'staffel'


    # Aktuelle Marktwerte als Vorbelegung für die Indexbasis neuer Sollmietzins-Zeilen
    from crm.models import Verwaltung as _Vw
    _vw = _Vw.objects.first()
    aktueller_ref_zins = _vw.aktueller_referenzzinssatz if _vw else Decimal('1.25')
    aktueller_lik = _vw.aktueller_lik_punkte if _vw else Decimal('107.1')

    # Ausstattung/Raumbuch — die Räume entstehen aus den erfassten Assets.
    ausst = list(Ausstattung.objects.filter(einheit=e)
                 .prefetch_related('schaeden__handwerker_auftraege'))
    raeume = []
    for a in ausst:
        zw = a.zeitwert()
        n_schaden = a.schaeden.count()
        row = {'a': a, 'zeitwert': zw, 'lebensdauer': a.effektive_lebensdauer(),
               'rest': a.rest_jahre(), 'ersatz_status': a.ersatz_status(),
               'schaden_anzahl': n_schaden,
               'reparaturkosten': a.reparatur_kosten_total() if n_schaden else None}
        if raeume and raeume[-1]['raum'] == a.raum:
            raeume[-1]['elemente'].append(row)
        else:
            raeume.append({'raum': a.raum, 'elemente': [row]})
    ausst_count = len(ausst)

    # Schlüsselregister: Bestand + offene Ausgaben je Schlüssel, Empfänger-Auswahl
    from portfolio.models import Schluessel
    from crm.models import Handwerker as _Hw
    schluessel_rows = []
    for sch in (Schluessel.objects.filter(einheit=e)
                .prefetch_related('ausgaben__mieter', 'ausgaben__handwerker')):
        offene = [a for a in sch.ausgaben.all() if a.rueckgabe_am is None]
        schluessel_rows.append({'s': sch, 'offene': offene,
                                'verfuegbar': max(0, sch.anzahl - len(offene))})
    schluessel_empfaenger = {
        'mieter': list({v.mieter for v in _vertraege if v.status == 'aktiv' and v.mieter_id}),
        'handwerker': list(_Hw.objects.order_by('firma')),
    }
    schluessel_offen_count = sum(len(r['offene']) for r in schluessel_rows)

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('fotos', 'Fotos', len(fotos) or None),
        ('raumbuch', 'Raumbuch', ausst_count or None),
        ('verhaeltnisse', 'Verhältnisse', len(verhaeltnisse) or None),
        ('mietzins', 'Mietzins', len(sollmietzinse) or None),
        ('geraete', 'Geräte', geraete.count() or None),
        ('zaehler', 'Zähler', zaehler.count() or None),
        ('schluessel', 'Schlüssel', len(schluessel_rows) or None),
    ]
    from django.contrib import messages
    return render(request, 'fw/objekt_detail.html', {
        **basis, 'nav': 'objekte', 'e': e,
        'aktiver_vertrag': aktiver_vertrag,
        'vertrag_pill': _vertrag_status_pill(aktiver_vertrag) if aktiver_vertrag else None,
        'verhaeltnisse': verhaeltnisse,
        'verhaeltnisse_dok_total': verhaeltnisse_dok_total,
        'geraete': geraete,
        'zaehler': zaehler,
        'sollmietzinse': sollmietzinse,
        'aktueller_soll_id': aktueller_soll_id,
        'staffelstufen': staffelstufen,
        'zeige_staffel': zeige_staffel,
        'staffelvorlagen': staffelvorlagen,
        'zeige_staffelvorlage': zeige_staffelvorlage,
        'aktueller_ref_zins': aktueller_ref_zins,
        'aktueller_lik': aktueller_lik,
        'fotos': fotos,
        'raeume': raeume,
        'ausst_count': ausst_count,
        'raumtypen': RAUMTYPEN,
        'raum_katalog': RAUM_KATALOG,
        'zustand_choices': Ausstattung.ZUSTAND,
        'geraet_kategorien': GERAET_KATEGORIEN,
        'zaehler_typen': ZAEHLER_TYPEN,
        'merkmale_gewaehlt': e.merkmale or [],
        'merkmale_optionen': merkmale_optionen(e.merkmale or []),
        'tab_liste': tab_liste,
        'schluessel_rows': schluessel_rows,
        'schluessel_empfaenger': schluessel_empfaenger,
        'schluessel_offen_count': schluessel_offen_count,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_add(request, pk):
    """Erfasst ein Ausstattungselement (Raumbuch) am Objekt. Der Raum ergibt sich
    aus dem eingegebenen Raumnamen — kein separates Raum-CRUD nötig."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.auth import log_aktion
    e = get_object_or_404(Einheit, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')

    raum = (request.POST.get('raum') or '').strip()
    kategorie = (request.POST.get('kategorie') or '').strip()
    if not raum or not kategorie:
        messages.error(request, "Raum und Kategorie sind Pflichtfelder.")
        return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else None
        except Exception:
            return None

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    def _int(x, default=None):
        try:
            return int(x)
        except Exception:
            return default

    # Sortierung ans Ende des jeweiligen Raums
    letzte = (Ausstattung.objects.filter(einheit=e, raum=raum)
              .order_by('-sortierung').first())
    sort = (letzte.sortierung + 1) if letzte else 0

    a = Ausstattung.objects.create(
        einheit=e, raum=raum, kategorie=kategorie,
        bezeichnung=(request.POST.get('bezeichnung') or '').strip(),
        marke=(request.POST.get('marke') or '').strip(),
        modell=(request.POST.get('modell') or '').strip(),
        material=(request.POST.get('material') or '').strip(),
        menge=_int(request.POST.get('menge'), 1) or 1,
        einbau_datum=_date(request.POST.get('einbau_datum')),
        neuwert=_dec(request.POST.get('neuwert')),
        lebensdauer_jahre=_int(request.POST.get('lebensdauer_jahre')),
        zustand=request.POST.get('zustand') or 'gut',
        garantie_bis=_date(request.POST.get('garantie_bis')),
        notiz=(request.POST.get('notiz') or '').strip(),
        sortierung=sort,
    )
    if request.FILES.get('foto'):
        a.foto = request.FILES['foto']
        a.save(update_fields=['foto'])
    log_aktion(request, "Ausstattung erfasst", e.bezeichnung, f"{raum} · {kategorie}")
    messages.success(request, f"✅ «{kategorie}» im Raum «{raum}» erfasst.")
    return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_edit(request, pk):
    """Bearbeitet ein bestehendes Ausstattungselement (Marke/Modell/Material,
    Neuwert, Einbaudatum, Zustand, Garantie, Lebensdauer, Notiz, Foto). So lassen
    sich die aus dem Katalog geladenen Elemente mit echten Daten ergänzen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.auth import log_aktion
    a = get_object_or_404(Ausstattung.objects.select_related('einheit'), id=pk)
    eid = a.einheit_id
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{eid}/#obj-raumbuch')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else None
        except Exception:
            return None

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    def _int(x, default=None):
        try:
            return int(x)
        except Exception:
            return default

    P = request.POST
    raum = (P.get('raum') or '').strip()
    kategorie = (P.get('kategorie') or '').strip()
    if not raum or not kategorie:
        messages.error(request, "Raum und Kategorie sind Pflichtfelder.")
        return redirect(f'/neu/objekte/{eid}/#obj-raumbuch')
    a.raum = raum
    a.kategorie = kategorie
    a.bezeichnung = (P.get('bezeichnung') or '').strip()
    a.marke = (P.get('marke') or '').strip()
    a.modell = (P.get('modell') or '').strip()
    a.material = (P.get('material') or '').strip()
    a.menge = _int(P.get('menge'), a.menge) or 1
    a.einbau_datum = _date(P.get('einbau_datum'))
    a.neuwert = _dec(P.get('neuwert'))
    a.lebensdauer_jahre = _int(P.get('lebensdauer_jahre'))
    a.zustand = P.get('zustand') or a.zustand
    a.garantie_bis = _date(P.get('garantie_bis'))
    a.notiz = (P.get('notiz') or '').strip()
    if request.FILES.get('foto'):
        a.foto = request.FILES['foto']
    a.save()
    log_aktion(request, "Ausstattung bearbeitet", a.einheit.bezeichnung, f"{raum} · {kategorie}")
    messages.success(request, f"✅ «{kategorie}» aktualisiert.")
    return redirect(f'/neu/objekte/{eid}/#obj-raumbuch')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_katalog(request, pk):
    """Legt für einen Raumtyp die Standard-Ausstattung aus dem Katalog an
    (Schnellerfassung). Vorhandene Elemente werden nicht dupliziert."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    from core.services.raumkatalog import RAUM_KATALOG
    from core.auth import log_aktion
    e = get_object_or_404(Einheit, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')

    raumtyp = (request.POST.get('raumtyp') or '').strip()
    elemente = RAUM_KATALOG.get(raumtyp)
    if not elemente:
        messages.error(request, "Unbekannter Raumtyp.")
        return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')

    vorhanden = set(Ausstattung.objects.filter(einheit=e, raum=raumtyp)
                    .values_list('kategorie', flat=True))
    n = 0
    for i, (kat, jahre) in enumerate(elemente):
        if kat in vorhanden:
            continue
        Ausstattung.objects.create(
            einheit=e, raum=raumtyp, kategorie=kat,
            lebensdauer_jahre=jahre, zustand='gut', sortierung=i)
        n += 1
    if n:
        log_aktion(request, "Raumkatalog geladen", e.bezeichnung, f"{raumtyp}: {n} Elemente")
        messages.success(request, f"✅ {n} Element(e) für «{raumtyp}» angelegt — jetzt Details ergänzen.")
    else:
        messages.info(request, f"«{raumtyp}» ist bereits vollständig erfasst.")
    return redirect(f'/neu/objekte/{e.id}/#obj-raumbuch')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_ausstattung_del(request, pk):
    """Entfernt ein Ausstattungselement."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Ausstattung
    a = get_object_or_404(Ausstattung.objects.select_related('einheit'), id=pk)
    eid = a.einheit_id
    if request.method == 'POST':
        a.delete()
        messages.success(request, "Ausstattungselement entfernt.")
    return redirect(f'/neu/objekte/{eid}/#obj-raumbuch')


# --- Geräte (Objekt + allgemeine Liegenschafts-Geräte wie Heizung/Boiler) ---

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_geraet_add(request):
    """Erfasst ein Gerät. Ziel ist entweder ein Objekt (`einheit_id`) oder eine
    Liegenschaft (`liegenschaft_id`, z.B. Heizung, Boiler, Lüftung)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/liegenschaften/')

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    eid = request.POST.get('einheit_id')
    lid = request.POST.get('liegenschaft_id')
    kategorie = (request.POST.get('kategorie') or '').strip()
    if not kategorie:
        kategorie = (request.POST.get('sonstiges_bezeichnung') or 'sonstiges').strip() or 'sonstiges'

    kwargs = dict(
        kategorie=kategorie,
        sonstiges_bezeichnung=(request.POST.get('sonstiges_bezeichnung') or '').strip(),
        marke=(request.POST.get('marke') or '').strip(),
        modell=(request.POST.get('modell') or '').strip(),
        seriennummer=(request.POST.get('seriennummer') or '').strip(),
        kapazitaet=(request.POST.get('kapazitaet') or '').strip(),
        standort=(request.POST.get('standort') or '').strip(),
        installations_datum=_date(request.POST.get('installations_datum')),
        garantie_bis=_date(request.POST.get('garantie_bis')),
        notiz=(request.POST.get('notiz') or '').strip(),
    )
    if eid:
        e = get_object_or_404(Einheit, id=eid)
        Geraet.objects.create(einheit=e, **kwargs)
        log_aktion(request, "Gerät erfasst", e.bezeichnung, kategorie)
        messages.success(request, f"✅ Gerät «{kategorie}» erfasst.")
        return redirect(f'/neu/objekte/{e.id}/?tab=geraete')
    if lid:
        lg = get_object_or_404(Liegenschaft, id=lid)
        Geraet.objects.create(liegenschaft=lg, **kwargs)
        log_aktion(request, "Gerät erfasst", str(lg), kategorie)
        messages.success(request, f"✅ Gerät «{kategorie}» erfasst.")
        return redirect(f'/neu/liegenschaften/{lg.id}/?tab=technik')
    messages.error(request, "Kein Ziel angegeben.")
    return redirect('/neu/liegenschaften/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_geraet_del(request, pk):
    """Entfernt ein Gerät (Objekt- oder Liegenschaftsebene)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    g = get_object_or_404(Geraet, id=pk)
    eid, lid = g.einheit_id, g.liegenschaft_id
    if request.method == 'POST':
        from core.models import Pendenz
        # Verwaiste Auto-Garantie-Pendenz mitlöschen (hängt nur über `quelle`).
        Pendenz.objects.filter(quelle=f"auto:garantie:{g.id}").delete()
        g.delete()
        messages.success(request, "Gerät entfernt.")
    if eid:
        return redirect(f'/neu/objekte/{eid}/?tab=geraete')
    return redirect(f'/neu/liegenschaften/{lid}/?tab=technik')


# --- Zähler (Objekt + allgemeine Liegenschafts-Zähler wie Allgemeinstrom) ---

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehler_add(request):
    """Erfasst einen Zähler. Ziel ist entweder ein Objekt (`einheit_id`) oder eine
    Liegenschaft (`liegenschaft_id`, z.B. Allgemeinstrom, Hauptwasser)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Zaehler
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/liegenschaften/')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else Decimal('0.00')
        except Exception:
            return Decimal('0.00')

    typ = (request.POST.get('typ') or '').strip()
    nummer = (request.POST.get('zaehler_nummer') or '').strip()
    if not typ or not nummer:
        messages.error(request, "Typ und Zähler-Nr. sind Pflichtfelder.")
        ref = request.META.get('HTTP_REFERER') or '/neu/liegenschaften/'
        return redirect(ref)

    kwargs = dict(
        typ=typ, zaehler_nummer=nummer,
        standort=(request.POST.get('standort') or '').strip(),
        aktueller_stand=_dec(request.POST.get('aktueller_stand')),
    )
    eid = request.POST.get('einheit_id')
    lid = request.POST.get('liegenschaft_id')
    if eid:
        e = get_object_or_404(Einheit, id=eid)
        Zaehler.objects.create(einheit=e, **kwargs)
        log_aktion(request, "Zähler erfasst", e.bezeichnung, f"{typ} · {nummer}")
        messages.success(request, f"✅ Zähler «{typ}» erfasst.")
        return redirect(f'/neu/objekte/{e.id}/?tab=zaehler')
    if lid:
        lg = get_object_or_404(Liegenschaft, id=lid)
        Zaehler.objects.create(liegenschaft=lg, **kwargs)
        log_aktion(request, "Zähler erfasst", str(lg), f"{typ} · {nummer}")
        messages.success(request, f"✅ Zähler «{typ}» erfasst.")
        return redirect(f'/neu/liegenschaften/{lg.id}/?tab=technik')
    messages.error(request, "Kein Ziel angegeben.")
    return redirect('/neu/liegenschaften/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehler_edit(request, pk):
    """Bearbeitet einen bestehenden Zähler (Typ/Nr./Standort/Stand)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Zaehler
    from core.auth import log_aktion
    z = get_object_or_404(Zaehler, id=pk)
    eid, lid = z.einheit_id, z.liegenschaft_id
    ziel = (f'/neu/objekte/{eid}/?tab=zaehler' if eid
            else f'/neu/liegenschaften/{lid}/?tab=technik')
    if request.method != 'POST':
        return redirect(ziel)

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else Decimal('0.00')
        except Exception:
            return z.aktueller_stand

    typ = (request.POST.get('typ') or '').strip()
    nummer = (request.POST.get('zaehler_nummer') or '').strip()
    if not typ or not nummer:
        messages.error(request, "Typ und Zähler-Nr. sind Pflichtfelder.")
        return redirect(ziel)
    z.typ = typ
    z.zaehler_nummer = nummer
    z.standort = (request.POST.get('standort') or '').strip()
    z.aktueller_stand = _dec(request.POST.get('aktueller_stand'))
    z.save()
    log_aktion(request, "Zähler bearbeitet", f"{typ} · {nummer}", '')
    messages.success(request, f"✅ Zähler «{typ}» aktualisiert.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zaehler_del(request, pk):
    """Entfernt einen Zähler (Objekt- oder Liegenschaftsebene)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Zaehler
    z = get_object_or_404(Zaehler, id=pk)
    eid, lid = z.einheit_id, z.liegenschaft_id
    if request.method == 'POST':
        z.delete()
        messages.success(request, "Zähler entfernt.")
    if eid:
        return redirect(f'/neu/objekte/{eid}/?tab=zaehler')
    return redirect(f'/neu/liegenschaften/{lid}/?tab=technik')


# --- Schlüsselverwaltung (Register + Ausgabe/Rücknahme je Objekt) ---

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_add(request):
    """Erfasst einen Schlüssel im Register eines Objekts."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Schluessel
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/objekte/')
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'),
                          id=request.POST.get('einheit_id'))
    nummer = (request.POST.get('schluessel_nummer') or '').strip()
    typ = (request.POST.get('typ') or 'Wohnung').strip()
    try:
        anzahl = max(1, int(request.POST.get('anzahl') or 1))
    except (TypeError, ValueError):
        anzahl = 1
    if not nummer:
        messages.error(request, "Schlüssel-Nr. ist ein Pflichtfeld.")
        return redirect(f'/neu/objekte/{e.id}/?tab=schluessel')
    Schluessel.objects.create(liegenschaft=e.liegenschaft, einheit=e,
                              typ=typ, schluessel_nummer=nummer, anzahl=anzahl)
    log_aktion(request, "Schlüssel erfasst", f"{e.bezeichnung}", f"{typ} {nummer} × {anzahl}")
    messages.success(request, f"✅ Schlüssel {nummer} ({typ}, {anzahl}×) erfasst.")
    return redirect(f'/neu/objekte/{e.id}/?tab=schluessel')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_del(request, pk):
    """Entfernt einen Schlüssel aus dem Register (inkl. Ausgabe-Historie)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Schluessel
    sch = get_object_or_404(Schluessel, id=pk)
    eid = sch.einheit_id
    if request.method == 'POST':
        if sch.ausgaben.filter(rueckgabe_am__isnull=True).exists():
            messages.error(request, "Schlüssel ist noch ausgegeben — zuerst Rücknahme erfassen.")
        else:
            sch.delete()
            messages.success(request, "Schlüssel entfernt.")
    return redirect(f'/neu/objekte/{eid}/?tab=schluessel' if eid else '/neu/objekte/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_ausgabe(request, pk):
    """Gibt einen Schlüssel an einen Mieter oder Handwerker aus."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Schluessel, SchluesselAusgabe
    from crm.models import Handwerker
    from core.auth import log_aktion
    sch = get_object_or_404(Schluessel, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{sch.einheit_id}/?tab=schluessel')
    offen = sch.ausgaben.filter(rueckgabe_am__isnull=True).count()
    if offen >= sch.anzahl:
        messages.error(request, f"Alle {sch.anzahl} Exemplare von {sch.schluessel_nummer} sind bereits ausgegeben.")
        return redirect(f'/neu/objekte/{sch.einheit_id}/?tab=schluessel')
    empf = (request.POST.get('empfaenger') or '')
    mieter = handwerker = None
    name = ''
    if empf.startswith('mieter:'):
        mieter = Mieter.objects.filter(id=empf.split(':', 1)[1]).first()
        name = mieter.display_name if mieter else ''
    elif empf.startswith('handwerker:'):
        handwerker = Handwerker.objects.filter(id=empf.split(':', 1)[1]).first()
        name = handwerker.firma if handwerker else ''
    if not (mieter or handwerker):
        messages.error(request, "Bitte Empfänger (Mieter oder Handwerker) wählen.")
        return redirect(f'/neu/objekte/{sch.einheit_id}/?tab=schluessel')
    SchluesselAusgabe.objects.create(schluessel=sch, mieter=mieter, handwerker=handwerker,
                                     ausgegeben_am=timezone.localdate())
    log_aktion(request, "Schlüssel ausgegeben", sch.schluessel_nummer, name)
    messages.success(request, f"✅ Schlüssel {sch.schluessel_nummer} an {name} ausgegeben.")
    return redirect(f'/neu/objekte/{sch.einheit_id}/?tab=schluessel')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schluessel_rueckgabe(request, pk):
    """Erfasst die Rücknahme einer offenen Schlüsselausgabe."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import SchluesselAusgabe
    from core.auth import log_aktion
    a = get_object_or_404(SchluesselAusgabe.objects.select_related('schluessel'), id=pk)
    if request.method == 'POST' and a.rueckgabe_am is None:
        a.rueckgabe_am = timezone.localdate()
        a.save(update_fields=['rueckgabe_am'])
        wer = a.mieter.display_name if a.mieter_id else (a.handwerker.firma if a.handwerker_id else '')
        log_aktion(request, "Schlüssel zurückgenommen", a.schluessel.schluessel_nummer, wer)
        messages.success(request, f"✅ Schlüssel {a.schluessel.schluessel_nummer} zurückgenommen.")
    return redirect(f'/neu/objekte/{a.schluessel.einheit_id}/?tab=schluessel')


# --- Sollmietzins-Komponenten (datierte Netto-/NK-Historie je Objekt) ---

@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_sollmietzins_add(request):
    """Erfasst eine datierte Sollmietzins-Zeile (gültig ab) für ein Objekt.
    Der aktuell gültige Wert wird automatisch auf die Einheit abgeleitet;
    neue Verträge übernehmen ihn ab dem Mietbeginn (Bestand bleibt unberührt)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Sollmietzins
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/objekte/')

    def _dec(x):
        try:
            v = _num(x)
            return Decimal(v) if v else Decimal('0.00')
        except Exception:
            return Decimal('0.00')

    e = get_object_or_404(Einheit, id=request.POST.get('einheit_id'))
    ziel = f'/neu/objekte/{e.id}/?tab=mietzins'
    ab_raw = (request.POST.get('gueltig_ab') or '').strip()
    try:
        ab = date.fromisoformat(ab_raw)
    except ValueError:
        messages.error(request, "Bitte ein gültiges «gültig ab»-Datum angeben.")
        return redirect(ziel)
    netto = _dec(request.POST.get('netto_mietzins'))
    # Einstellplatz → keine Nebenkosten
    nk = Decimal('0.00') if e.ist_einstellplatz else _dec(request.POST.get('nebenkosten'))
    # Rabatt/Erlass (Gratismonat): mindert nur die Verrechnung, nicht die Referenz.
    # "mietzinsfrei" = voller Netto-Erlass → Rabatt = Netto-Referenz.
    if request.POST.get('mietzinsfrei'):
        rabatt_netto = netto
    else:
        rabatt_netto = _dec(request.POST.get('rabatt_netto'))
    rabatt_nk = _dec(request.POST.get('rabatt_nk'))
    rabatt_netto = min(max(rabatt_netto, Decimal('0.00')), netto)   # 0..Referenz
    rabatt_nk = min(max(rabatt_nk, Decimal('0.00')), nk)

    def _dec_opt(x):
        v = _num(x)
        try:
            return Decimal(v) if v else None
        except Exception:
            return None

    Sollmietzins.objects.create(
        einheit=e, gueltig_ab=ab, netto_mietzins=netto, nebenkosten=nk,
        rabatt_netto=rabatt_netto, rabatt_nk=rabatt_nk,
        basis_referenzzinssatz=_dec_opt(request.POST.get('basis_referenzzinssatz')),
        basis_lik_punkte=_dec_opt(request.POST.get('basis_lik_punkte')),
        notiz=(request.POST.get('notiz') or '').strip()[:200],
    )
    zu_zahlen = max(Decimal('0'), netto - rabatt_netto) + max(Decimal('0'), nk - rabatt_nk)
    log_aktion(request, "Sollmietzins erfasst", e.bezeichnung,
               f"ab {ab}: Referenz {netto}+{nk}, Rabatt {rabatt_netto}/{rabatt_nk}, zu zahlen {zu_zahlen}")
    # Ein Erlass ist eine Geld-Entscheidung — die Bestätigung muss ihn benennen
    # und nicht nur eine Summe zeigen, in der er schon verrechnet ist. Ein voller
    # Erlass bekommt zusätzlich einen Warnton statt eines Häkchens.
    if rabatt_netto >= netto > 0:
        messages.warning(
            request,
            f"⚠️ Sollmietzins ab {ab.strftime('%d.%m.%Y')} erfasst — "
            f"Nettomietzins CHF {netto} VOLLSTÄNDIG ERLASSEN (Gratismonat). "
            f"Verrechnet wird nur CHF {zu_zahlen}. War das nicht beabsichtigt, "
            f"Zeile löschen und ohne Rabatt neu erfassen.")
    elif rabatt_netto > 0 or rabatt_nk > 0:
        messages.success(
            request,
            f"✅ Sollmietzins ab {ab.strftime('%d.%m.%Y')} erfasst — Referenz "
            f"CHF {netto + nk}, davon CHF {rabatt_netto + rabatt_nk} Rabatt, "
            f"zu zahlen CHF {zu_zahlen}.")
    else:
        messages.success(request, f"✅ Sollmietzins ab {ab.strftime('%d.%m.%Y')} erfasst "
                         f"(CHF {zu_zahlen}).")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_sollmietzins_del(request, pk):
    """Entfernt eine Sollmietzins-Zeile und führt den Aktuellwert der Einheit nach."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Sollmietzins
    s = get_object_or_404(Sollmietzins, id=pk)
    e = s.einheit
    if request.method == 'POST':
        s.delete()
        e.sync_aktuelle_miete()
        messages.success(request, "Sollmietzins-Zeile entfernt.")
    return redirect(f'/neu/objekte/{e.id}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffelvorlage_add(request):
    """Erfasst eine datierte Stufe der OBJEKT-Staffelmiete-Vorlage (Plan). Belegt
    neue Verträge im Wizard vor — wird selbst nicht verrechnet."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import StaffelVorlage
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('/neu/objekte/')
    e = get_object_or_404(Einheit, id=request.POST.get('einheit_id'))
    ziel = f'/neu/objekte/{e.id}/?tab=mietzins'
    try:
        ab = date.fromisoformat((request.POST.get('gueltig_ab') or '').strip())
    except ValueError:
        messages.error(request, "Bitte ein gültiges «gültig ab»-Datum angeben.")
        return redirect(ziel)

    def _dec(x):
        try:
            return Decimal(_num(x))
        except Exception:
            return None

    netto = _dec(request.POST.get('netto_mietzins'))
    if netto is None or netto <= 0:
        messages.error(request, "Bitte einen gültigen Netto-Mietzins angeben.")
        return redirect(ziel)
    StaffelVorlage.objects.create(
        einheit=e, gueltig_ab=ab, netto_mietzins=netto,
        notiz=(request.POST.get('notiz') or '').strip()[:200])
    log_aktion(request, "Staffel-Vorlage erfasst", e.bezeichnung, f"ab {ab}: {netto}")
    messages.success(request, f"✅ Staffel-Vorlage ab {ab.strftime('%d.%m.%Y')} erfasst.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffelvorlage_del(request, pk):
    """Entfernt eine Stufe der Objekt-Staffelmiete-Vorlage."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import StaffelVorlage
    s = get_object_or_404(StaffelVorlage, id=pk)
    eid = s.einheit_id
    if request.method == 'POST':
        s.delete()
        messages.success(request, "Staffel-Vorlage-Zeile entfernt.")
    return redirect(f'/neu/objekte/{eid}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffel_add(request):
    """Erfasst eine Staffelstufe (Art. 269c) für den AKTIVEN Vertrag eines Objekts.
    Staffelmiete ist vertragsgebunden — die Stufe treibt direkt die Sollstellung
    (effektiver_netto_mietzins ab Stichtag)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Mietvertrag, Staffelstufe
    if request.method != 'POST':
        return redirect('/neu/objekte/')
    v = get_object_or_404(Mietvertrag, id=request.POST.get('vertrag_id'))
    ziel = f'/neu/objekte/{v.einheit_id}/?tab=mietzins'
    try:
        ab = date.fromisoformat((request.POST.get('ab_datum') or '').strip())
    except ValueError:
        messages.error(request, "Bitte ein gültiges Stichtag-Datum angeben.")
        return redirect(ziel)

    def _dec(x):
        try:
            return Decimal(_num(x))
        except Exception:
            return None

    netto = _dec(request.POST.get('netto_mietzins'))
    if netto is None or netto <= 0:
        messages.error(request, "Bitte einen gültigen Netto-Mietzins angeben.")
        return redirect(ziel)
    Staffelstufe.objects.create(vertrag=v, ab_datum=ab, netto_mietzins=netto)
    # Damit die Stufe im Mietenlauf greift, muss das Vertragsmodell 'staffel' sein.
    if v.mietzins_modell != 'staffel':
        v.mietzins_modell = 'staffel'
        v.save(update_fields=['mietzins_modell'])
    messages.success(request, f"✅ Staffelstufe ab {ab.strftime('%d.%m.%Y')} erfasst.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_staffel_del(request, pk):
    """Entfernt eine Staffelstufe des aktiven Vertrags."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Staffelstufe
    s = get_object_or_404(Staffelstufe, id=pk)
    eid = s.vertrag.einheit_id
    if request.method == 'POST':
        s.delete()
        messages.success(request, "Staffelstufe entfernt.")
    return redirect(f'/neu/objekte/{eid}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_anpassung_del(request, pk):
    """Entfernt eine (versehentlich erstellte) Mietzinsanpassung. Danach folgt die
    Sollstellung wieder dem vorherigen Mietzins — bereits gestellte Rechnungen
    bleiben unverändert (nur künftige Sollläufe)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import MietzinsAnpassung
    from core.auth import log_aktion
    from portfolio.models import Sollmietzins
    a = get_object_or_404(MietzinsAnpassung, id=pk)
    vid = a.vertrag_id
    if request.method == 'POST':
        log_aktion(request, "Mietzinsanpassung gelöscht", str(a.vertrag),
                   f"wirksam {a.wirksam_ab}: CHF {a.neuer_netto_mietzins}")
        # Die aus dieser Anpassung erzeugte Sollmietzins-Zeile im Objekt
        # ebenfalls entfernen und den aktuellen Mietzins der Einheit neu ableiten.
        einheiten = {z.einheit for z in a.sollmietzins_zeilen.all()}
        Sollmietzins.objects.filter(quelle_anpassung=a).delete()
        a.delete()
        for e in einheiten:
            if e:
                e.sync_aktuelle_miete()
        messages.success(request, "Mietzinsanpassung entfernt.")
    return redirect(f'/neu/vertraege/{vid}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_nkart(request, pk):
    """Setzt die Nebenkosten-Abrechnungsart des Objekts (Standard für neue Verträge)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    e = get_object_or_404(Einheit, id=pk)
    if request.method == 'POST':
        art = request.POST.get('nk_abrechnungsart')
        if art in ('akonto', 'pauschal'):
            e.nk_abrechnungsart = art
            e.save(update_fields=['nk_abrechnungsart'])
            messages.success(request, "Nebenkosten-Abrechnungsart aktualisiert.")
    return redirect(f'/neu/objekte/{e.id}/?tab=mietzins')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_geraet_edit(request, pk):
    """Bearbeitet ein bestehendes Gerät (Kategorie/Marke/Modell/Daten)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    g = get_object_or_404(Geraet, id=pk)
    eid, lid = g.einheit_id, g.liegenschaft_id
    ziel = (f'/neu/objekte/{eid}/?tab=geraete' if eid
            else f'/neu/liegenschaften/{lid}/?tab=technik')
    if request.method != 'POST':
        return redirect(ziel)

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    kategorie = (request.POST.get('kategorie') or '').strip()
    if not kategorie:
        messages.error(request, "Kategorie ist ein Pflichtfeld.")
        return redirect(ziel)
    g.kategorie = kategorie
    g.sonstiges_bezeichnung = (request.POST.get('sonstiges_bezeichnung') or '').strip()
    g.marke = (request.POST.get('marke') or '').strip()
    g.modell = (request.POST.get('modell') or '').strip()
    g.seriennummer = (request.POST.get('seriennummer') or '').strip()
    g.kapazitaet = (request.POST.get('kapazitaet') or '').strip()
    g.standort = (request.POST.get('standort') or '').strip()
    g.installations_datum = _date(request.POST.get('installations_datum'))
    g.garantie_bis = _date(request.POST.get('garantie_bis'))
    g.notiz = (request.POST.get('notiz') or '').strip()
    g.save()
    log_aktion(request, "Gerät bearbeitet", kategorie, '')
    messages.success(request, f"✅ Gerät «{kategorie}» aktualisiert.")
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_lebensdauer(request):
    """Editierbare paritätische Lebensdauertabelle (Mieterverband/HEV).
    Grundlage für den Zeitwert-/Mieteranteil bei der Wohnungsabnahme."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Lebensdauer
    from core.auth import log_aktion, hat_rolle
    basis = _global_filter(request)

    if request.method == 'POST':
        if not hat_rolle(request.user, SCHREIB_ROLLEN):
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect('/neu/lebensdauer/')
        aktion = request.POST.get('aktion')
        if aktion == 'speichern':
            n = 0
            for row in Lebensdauer.objects.all():
                val = request.POST.get(f'jahre_{row.id}')
                bem = request.POST.get(f'bemerkung_{row.id}')
                changed = False
                if val and val.isdigit() and int(val) != row.jahre and int(val) > 0:
                    row.jahre = int(val); changed = True
                if bem is not None and bem.strip() != row.bemerkung:
                    row.bemerkung = bem.strip(); changed = True
                if changed:
                    row.save(); n += 1
            log_aktion(request, "Lebensdauertabelle bearbeitet", f"{n} Werte")
            messages.success(request, f"✅ {n} Wert(e) aktualisiert." if n else "Keine Änderung.")
        elif aktion == 'neu':
            kat = (request.POST.get('kategorie') or '').strip()
            jahre = request.POST.get('jahre')
            if kat and jahre and jahre.isdigit() and int(jahre) > 0:
                _, created = Lebensdauer.objects.get_or_create(
                    kategorie=kat, defaults={'jahre': int(jahre),
                                             'bemerkung': (request.POST.get('bemerkung') or '').strip()})
                messages.success(request, f"✅ «{kat}» hinzugefügt." if created else "Kategorie existiert bereits.")
            else:
                messages.error(request, "Kategorie und Jahre (> 0) sind Pflicht.")
        elif aktion == 'loeschen':
            Lebensdauer.objects.filter(id=request.POST.get('id') or None).delete()
            messages.success(request, "Kategorie entfernt.")
        elif aktion == 'seed':
            from core.services.raumkatalog import seed_lebensdauer
            n = seed_lebensdauer()
            messages.success(request, f"✅ {n} Standardwert(e) ergänzt." if n else "Alle Standardwerte bereits vorhanden.")
        return redirect('/neu/lebensdauer/')

    from django.contrib import messages as _m
    return render(request, 'fw/lebensdauer.html', {
        **basis, 'nav': 'assets',
        'rows': Lebensdauer.objects.all(),
        'meldung': list(_m.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_foto_upload(request, pk):
    """Hängt Fotos an ein Mietobjekt (für Exposé, Portal-Feed, Vermarktung)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import EinheitFoto
    from core.auth import log_aktion
    from core.utils.uploads import validiere_bild
    e = get_object_or_404(Einheit, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/objekte/{e.id}/')
    start = e.fotos.count()
    n = 0
    abgelehnt = 0
    for f in request.FILES.getlist('fotos'):
        ok, _fehler = validiere_bild(f)
        if not ok:
            abgelehnt += 1
            continue
        EinheitFoto.objects.create(einheit=e, bild=f, reihenfolge=start + n)
        n += 1
    if n:
        log_aktion(request, "Objekt-Fotos hochgeladen", e.bezeichnung, f"{n} Foto(s)")
        messages.success(request, f"✅ {n} Foto(s) hinzugefügt.")
    if abgelehnt:
        messages.error(request, f"{abgelehnt} Datei(en) abgelehnt (kein gültiges Bild oder zu gross).")
    elif not n:
        messages.error(request, "Keine Datei ausgewählt.")
    return redirect(f'/neu/objekte/{e.id}/#obj-fotos')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_objekt_foto_loeschen(request, pk):
    """Entfernt ein einzelnes Objekt-Foto."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import EinheitFoto
    foto = get_object_or_404(EinheitFoto.objects.select_related('einheit'), id=pk)
    eid = foto.einheit_id
    if request.method == 'POST':
        foto.delete()
        messages.success(request, "Foto entfernt.")
    return redirect(f'/neu/objekte/{eid}/#obj-fotos')


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


def _formulare_prozesse(v, user=None):
    """Bündelt ALLE für diesen Vertrag zutreffenden Formulare/Prozesse in Gruppen —
    kontextabhängig nach Status/Objektart, mit «bereits erstellt»-Kennzeichnung.
    Ein Ort für alles: der «Formulare & Prozesse»-Tab am Vertrag."""
    from rentals.models import Dokument
    from core.services.formularpflicht import formularpflicht_fuer_liegenschaft
    e = v.einheit
    lg = e.liegenschaft if e else None
    wohnraum = bool(e) and getattr(e, 'mietrecht_kategorie', '') != 'gewerbe' and not getattr(e, 'ist_einstellplatz', False)
    aktiv = v.status == 'aktiv'
    gek = v.status == 'gekuendigt'
    beendet = v.status in ('gekuendigt', 'archiviert')
    hat_kaution = bool(v.kautions_einbezahlt_am)
    sperrkonto = hat_kaution and not getattr(v, 'ist_kautionsversicherung', False)
    pflicht = formularpflicht_fuer_liegenschaft(lg)[0] if lg else 'unbekannt'

    labels = [b or '' for b in Dokument.objects.filter(vertrag=v).values_list('bezeichnung', flat=True)]

    def hat(prefix):
        return any(b.startswith(prefix) for b in labels)

    gruppen = [
        {'titel': 'Mietrechtliche Formulare', 'icon': 'fa-scale-balanced', 'items': [
            {'titel': 'Anfangsmietzins (Art. 270)', 'icon': 'fa-file-invoice',
             'url': f'/neu/mietzins/{v.id}/anfangsmietzins/', 'erledigt': hat('Anfangsmietzins'),
             'pflicht': (pflicht == 'ja' and wohnraum),
             'sub': ('Formularpflicht' if (pflicht == 'ja' and wohnraum) else 'Mitteilung des Anfangsmietzinses')},
            {'titel': 'Mietzinsanpassung (Art. 269d)', 'icon': 'fa-arrow-trend-up',
             'url': f'/neu/mietzins/{v.id}/anpassung/', 'verfuegbar': aktiv,
             'sub': 'Erhöhung / Senkung amtlich mitteilen'},
            {'titel': 'Kündigung (Art. 266)', 'icon': 'fa-file-circle-xmark',
             'url': f'/neu/vertraege/{v.id}/kuendigen/', 'verfuegbar': not gek,
             'erledigt': v.kuendigungen.exists(), 'sub': 'Vermieter- / Mieterkündigung'},
        ]},
        {'titel': 'Kaution (Art. 257e)', 'icon': 'fa-shield-halved', 'items': [
            {'titel': 'Hinterlegungsbestätigung', 'icon': 'fa-file-pdf',
             'url': f'/neu/vertraege/{v.id}/kaution-beleg/hinterlegung/', 'verfuegbar': hat_kaution,
             'erledigt': hat('Kaution-Bestätigung'), 'sub': 'an die Mieterschaft'},
            {'titel': 'Freigabe an Bank', 'icon': 'fa-building-columns',
             'url': f'/neu/vertraege/{v.id}/kaution-beleg/freigabe/', 'verfuegbar': sperrkonto,
             'erledigt': hat('Kaution-Freigabe'), 'sub': 'Sperrkonto freigeben'},
        ]},
        {'titel': 'Prozesse', 'icon': 'fa-gears', 'items': [
            {'titel': 'Zahlungsverzug (Art. 257d)', 'icon': 'fa-gavel',
             'url': f'/neu/vertraege/{v.id}/verzug/', 'sub': 'Frist + Kündigungsandrohung'},
            {'titel': 'Mängelrüge (Art. 259)', 'icon': 'fa-triangle-exclamation',
             'url': f'/neu/vertraege/{v.id}/maengelruege/', 'erledigt': hat('Mängelrüge'),
             'sub': 'Fristansetzung zur Mängelbehebung'},
            {'titel': 'Untermiete (Art. 262)', 'icon': 'fa-people-arrows',
             'url': f'/neu/vertraege/{v.id}/untermiete/', 'erledigt': hat('Untermiete-'),
             'sub': 'Zustimmung / Ablehnung'},
            {'titel': 'Wohnungsabnahme', 'icon': 'fa-clipboard-check',
             'url': f'/neu/vertraege/{v.id}/abnahme/neu/', 'sub': 'Ein- / Auszugsprotokoll'},
            {'titel': 'Schlussabrechnung', 'icon': 'fa-file-invoice-dollar',
             'url': f'/neu/vertraege/{v.id}/schlussabrechnung/', 'verfuegbar': (aktiv or beendet),
             'sub': 'beim Auszug'},
        ]},
        {'titel': 'Vertrag & Beilagen', 'icon': 'fa-file-contract', 'items': [
            {'titel': 'Mietvertrag (PDF)', 'icon': 'fa-file-contract', 'url': f'/vertrag/{v.id}/pdf/', 'sub': 'kompletter Vertrag'},
            {'titel': 'QR-Rechnung', 'icon': 'fa-qrcode', 'url': f'/vertrag/{v.id}/qr/', 'sub': 'Einzahlungsschein QR-IBAN'},
            {'titel': 'Begleitbrief', 'icon': 'fa-envelope', 'url': f'/vertrag/{v.id}/dokument/begleitbrief/', 'sub': 'Anschreiben zur Unterzeichnung'},
            {'titel': 'Allgemeine Bedingungen', 'icon': 'fa-file-lines', 'url': f'/vertrag/{v.id}/dokument/allgemeine-bedingungen/', 'sub': 'Vertragsbeilage'},
            {'titel': 'Hausordnung', 'icon': 'fa-list-check', 'url': f'/vertrag/{v.id}/dokument/hausordnung/', 'sub': 'Vertragsbeilage'},
            {'titel': 'Wohnungsausweis', 'icon': 'fa-id-card', 'url': f'/vertrag/{v.id}/dokument/wohnungsausweis/', 'sub': 'Mieter- und Objektdaten'},
        ]},
    ]
    for g in gruppen:
        for it in g['items']:
            it.setdefault('verfuegbar', True)
            it.setdefault('erledigt', False)
            it.setdefault('pflicht', False)
            # Was die Rolle ohnehin nicht öffnen darf, gar nicht erst als
            # Verknüpfung anbieten — sonst führt der Klick in eine Absage.
            # Die Rollen stehen an der View selbst (siehe `darf_oeffnen`), es
            # gibt hier also keine zweite Liste, die veralten könnte.
            if user is not None and not darf_oeffnen(user, it['url']):
                it['verfuegbar'] = False
                it['gesperrt'] = True
    return gruppen


def _wg_kandidaten(vertrag):
    """Personen, die als weitere WG-Mieter hinzugefügt werden können — alle Mieter
    ausser den bereits am Vertrag beteiligten Parteien (max. 50 für die Auswahl)."""
    from crm.models import Mieter
    aus = {vertrag.mieter_id, vertrag.mitmieter_id}
    if vertrag.pk:
        aus |= {m.id for m in vertrag.weitere_mieter.all()}
    return list(Mieter.objects.exclude(id__in=[i for i in aus if i])
                .order_by('nachname', 'vorname')[:50])


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
    mietzins_komponenten = list(v.mietzins_komponenten.all())
    dokumente = RentalsDokument.objects.filter(vertrag=v).order_by('-datum')[:15]

    rechnungs_rows = []
    for r in rechnungen:
        label, pill_cls = STATUS_PILL.get(r.status, (r.status, 'bg-slate-100 text-slate-500'))
        rechnungs_rows.append({'r': r, 'status_label': label, 'pill_cls': pill_cls,
                               'offen': r.offener_betrag if r.status in ('offen', 'teilbezahlt') else Decimal('0.00')})

    from core.models import AktivitaetsLog
    verlauf = list(AktivitaetsLog.objects.filter(ziel_typ='vertrag', ziel_id=v.id)
                   .select_related('benutzer')[:50])
    # Meilensteine, die NICHT über log_aktion laufen (z.B. der Webhook-Rücklauf
    # der digitalen Unterschrift), als synthetische Ereignisse einmischen — der
    # Rücklauf-Zeitstempel gehört in den Verlauf, nicht in den Seitenkopf.
    from types import SimpleNamespace
    if v.unterzeichnet_am:
        verlauf.append(SimpleNamespace(
            benutzer=None,
            aktion="Unterschriebener Vertrag zurückerhalten",
            details=f"Digital unterzeichnet von {v.mieter.display_name} — Rücklauf via DocuSeal, automatisch abgelegt.",
            zeitpunkt=v.unterzeichnet_am))
    verlauf.sort(key=lambda x: x.zeitpunkt, reverse=True)

    # Akte komplettieren: Schäden am Mietobjekt + offene Pendenzen/Fristen zum
    # Vertrag — alles zum Mietverhältnis an EINEM Ort (kein Menü-Wechsel nötig).
    from tickets.models import SchadenMeldung
    from core.models import Pendenz
    schaeden = list(SchadenMeldung.objects.filter(betroffene_einheit=v.einheit)
                    .order_by('-erstellt_am')[:15]) if v.einheit_id else []
    vertrag_pendenzen = []
    _heute = timezone.localdate()
    for p in Pendenz.objects.filter(erledigt=False, vertrag=v).order_by('faellig_am'):
        _purl, _plabel, _pwide, _pmodal = _pendenz_ziel(p)
        vertrag_pendenzen.append({'p': p, 'url': _purl, 'label': _plabel or 'Öffnen',
                                  'wide': _pwide, 'modal': _pmodal,
                                  'ueberfaellig': bool(p.faellig_am and p.faellig_am < _heute)})
    # Datierte Fristen (Teilmenge) für die Finanzen-Karte — analog zum Kontakt, damit
    # die 257d-Frist + Track & Trace auch unter «Finanzen» direkt sichtbar ist.
    vertrag_fristen = [e for e in vertrag_pendenzen if e['p'].faellig_am]

    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('finanzen', 'Finanzen', len(offene) or None),
        ('mietzins', 'Mietzins', anpassungen.count() or None),
        ('schaeden', 'Schäden', len(schaeden) or None),
        ('pendenzen', 'Pendenzen', len(vertrag_pendenzen) or None),
        ('formulare', 'Formulare', None),
        ('dokumente', 'Dokumente', None),
        ('verlauf', 'Verlauf', len(verlauf) or None),
    ]
    from core.services.docuseal_service import docuseal_konfiguriert
    return render(request, 'fw/vertrag_detail.html', {
        'formular_gruppen': _formulare_prozesse(v, request.user),
        **basis, 'nav': 'vertraege', 'v': v, 'verlauf': verlauf,
        'vertrag_pill': _vertrag_status_pill(v),
        'brutto': (v.netto_mietzins or Decimal('0')) + (v.nebenkosten or Decimal('0')),
        'rechnungs_rows': rechnungs_rows,
        'total_offen': total_offen,
        'anzahl_offen': len(offene),
        'zahlungen': zahlungen,
        'anpassungen': anpassungen,
        'mietzins_komponenten': mietzins_komponenten,
        'heute_iso': timezone.localdate().isoformat(),
        'dokumente': dokumente,
        'nebenobjekte': v.nebenobjekte.all(),
        'weitere_mieter': list(v.weitere_mieter.all()),
        'wg_kandidaten': _wg_kandidaten(v),
        'erstellbare_dokumente': _erstellbare_dokumente(v),
        'kuendigungen': v.kuendigungen.all(),
        'formular_kanton': _formular_kanton_label(v),
        'tab_liste': tab_liste,
        'vertrag_schaeden': schaeden,
        'vertrag_pendenzen': vertrag_pendenzen,
        'vertrag_fristen': vertrag_fristen,
        'vt_zugang_next': f'/neu/vertraege/{v.id}/?tab=pendenzen',
        'vt_fin_zugang_next': f'/neu/vertraege/{v.id}/?tab=finanzen',
        'docuseal_konfiguriert': docuseal_konfiguriert(),
    })


def _formular_kanton_label(vertrag):
    """Kürzel des Kantons für das amtliche Formular (SO/ZH/BE/…). Leer, wenn
    keine Liegenschaft/kein Kanton bestimmbar."""
    from core.services.kantone import kanton_fuer_liegenschaft
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    return kanton_fuer_liegenschaft(lg) if lg else ''




GUTHABEN_AUSBEZAHLT = '[ausbezahlt]'


def _guthaben_positionen(vertrag):
    """Noch nicht ausbezahlte Mieterguthaben (2030) dieses Vertrags."""
    from finance.models import Zahlungseingang as _Z
    return list(_Z.objects.filter(vertrag=vertrag, status='verbucht', konto__nummer='2030')
                .exclude(bemerkung__contains=GUTHABEN_AUSBEZAHLT))


def _guthaben_bilanziert(vertrag):
    """Summe der noch offenen Mieterguthaben (2030) dieses Vertrags."""
    return sum((z.betrag for z in _guthaben_positionen(vertrag)),
               Decimal('0.00')).quantize(Decimal('0.01'))


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
            return Decimal(_num(x))
        except Exception:
            return Decimal('0.00')

    if request.method == 'POST':
        try:
            auszug = date.fromisoformat(request.POST.get('auszug_datum') or '')
        except Exception:
            auszug = v.ende or timezone.localdate()
        kaution_verrechnen = request.POST.get('kaution_verrechnen') == 'on'

        positionen = []
        texte = request.POST.getlist('pos_text')
        betraege = request.POST.getlist('pos_betrag')
        richtungen = request.POST.getlist('pos_richtung')
        # `pos_mwst` ist ein <select> (nicht Checkbox), damit die Indizes mit den
        # übrigen Listen ausgerichtet bleiben — eine nicht angehakte Checkbox
        # sendet gar nichts und würde die Zuordnung verschieben.
        steuerflags = request.POST.getlist('pos_mwst')
        for i, txt in enumerate(texte):
            txt = (txt or '').strip()
            betr = _dec(betraege[i] if i < len(betraege) else '0')
            if not txt or betr == 0:
                continue
            richtung = richtungen[i] if i < len(richtungen) else 'zulasten'
            steuerbar = (steuerflags[i] if i < len(steuerflags) else '0') == '1'
            positionen.append({'text': txt, 'betrag': betr,
                               'zulasten': (richtung == 'zulasten'),
                               'steuerbar': steuerbar})

        # Die bilanzierte Kaution (2010-Saldo) als Obergrenze mitgeben, damit
        # Anzeige/PDF exakt das gutschreiben, was die Buchung freigibt (QS-Befund).
        daten = berechne_schlussabrechnung(v, auszug, positionen,
                                           kaution_verrechnen=kaution_verrechnen,
                                           kaution_bilanziert=_kaution_bilanziert(v))
        aktion = request.POST.get('aktion', 'pdf')

        if aktion == 'buchen':
            # Idempotenz: eine Schlussabrechnung wird pro Vertrag nur EINMAL verbucht.
            # Ohne diese Sperre erzeugte ein Doppelklick / Zurück-Navigieren einen
            # zweiten Nachzahlungs-Debitor + eine doppelte 1100/3000-Buchung.
            #
            # Geprüft werden die BUCHUNGSSPUREN, nicht `kautions_zurueckbezahlt_am`:
            # Letzteres wird auch gesetzt, wenn die Kaution separat zurückbezahlt
            # wurde — dann war die Schlussabrechnung komplett blockiert, obwohl sie
            # noch nie lief. Umgekehrt fehlte eine Sperre für den Gutschrift-Fall
            # ohne Kaution, wo ein Doppelklick zweimal Mieterguthaben buchte (Audit).
            from finance.models import Buchung as _BIdem
            schon_verbucht = (
                DebitorenRechnung.objects.filter(
                    vertrag=v, titel="Schlussabrechnung (Nachzahlung)"
                ).exclude(status='storniert').exists()
                # storniert_am mitprüfen — sonst widerspricht diese Hälfte der
                # ersten: die schliesst stornierte Rechnungen bereits aus, damit
                # eine Schlussabrechnung nach einem Storno neu erstellt werden
                # kann. Ohne den Filter blockierte die stehengebliebene
                # Original-Buchung genau das.
                or _BIdem.objects.filter(
                    beleg_text__contains=f"Schlussabrechnung [V{v.pk}]",
                    ist_storno=False, storniert_am__isnull=True
                ).exists()
            )
            if schon_verbucht:
                if request.POST.get('embed'):
                    return render(request, 'fw/_modal_done.html', {'msg': 'Schlussabrechnung bereits verbucht'})
                messages.info(request, "Diese Schlussabrechnung wurde bereits verbucht.")
                return redirect(f'/neu/vertraege/{v.id}/')
            try:
                with transaction.atomic():
                    from finance.booking import buche
                    heute = timezone.localdate()
                    lg_s = v.einheit.liegenschaft if v.einheit_id else None
                    dat_s = auszug or heute

                    # ── 1) NUR die NEUEN Positionen buchen (Schäden, Reinigung, NK-Saldo) ──
                    # Bereits gestellte Mietforderungen bleiben unangetastet: Storno +
                    # Neubuchung auf 3000 (früheres Verhalten) vernichtete deren MWST-
                    # Abgrenzung (2200) und verschob Schadenersatz in den Mietertrag —
                    # was Mieterspiegel und Honorarbasis verfälschte (Audit K2/W5).
                    neu_saldo = (daten['zwischen'] - daten['offen_total']).quantize(Decimal('0.01'))
                    # MWST-Anteil aus dem Gesamtbetrag herauslösen: `zwischen`
                    # enthält ihn bereits als eigene Zeile. Der Ertrag (3600) darf
                    # nur den Nettoteil bekommen, die Steuer gehört auf 2200 —
                    # sonst fehlt sie in der ESTV-Abrechnung (Audit).
                    mwst_neu = daten.get('mwst_neu') or Decimal('0.00')
                    netto_neu = (neu_saldo - mwst_neu).quantize(Decimal('0.01'))
                    if neu_saldo > 0:
                        rech = DebitorenRechnung.objects.create(
                            vertrag=v, liegenschaft=lg_s, einheit=v.einheit,
                            titel="Schlussabrechnung (Nachzahlung)", datum=dat_s,
                            faellig_am=dat_s + _timedelta(days=30), betrag=neu_saldo, status='offen')
                        if netto_neu != 0:
                            buche("1100", "3600", netto_neu,
                                  f"Schlussabrechnung [V{v.pk}] {v.mieter} (Schäden/Nebenkosten)",
                                  datum=dat_s, liegenschaft=lg_s, debitor=rech, user=request.user)
                        if mwst_neu > 0:
                            buche("1100", "2200", mwst_neu,
                                  f"MWST Schlussabrechnung [V{v.pk}] {v.mieter}",
                                  datum=dat_s, liegenschaft=lg_s, debitor=rech, user=request.user)
                    elif neu_saldo < 0:
                        # Gutschrift zugunsten Mieter → als echtes Guthaben (2030) führen,
                        # damit es im Mieterkonto sichtbar und auszahlbar ist.
                        from finance.booking import konto as _k_s
                        if netto_neu != 0:
                            buche("3600", "2030", abs(netto_neu),
                                  f"Schlussabrechnung [V{v.pk}] {v.mieter} — Gutschrift",
                                  datum=dat_s, liegenschaft=lg_s, user=request.user)
                        if mwst_neu < 0:
                            # Spiegelbildliche Steuerkorrektur: der Umsatz wird
                            # gemindert, also auch die geschuldete MWST.
                            buche("2200", "2030", abs(mwst_neu),
                                  f"MWST-Korrektur Schlussabrechnung [V{v.pk}] {v.mieter}",
                                  datum=dat_s, liegenschaft=lg_s, user=request.user)
                        Zahlungseingang.objects.create(
                            vertrag=v, betrag=abs(neu_saldo), datum_eingang=dat_s,
                            buchungs_monat=dat_s.replace(day=1),
                            bemerkung="Schlussabrechnung — Guthaben Mieter"[:255],
                            konto=_k_s("2030"), liegenschaft=lg_s,
                            erstellt_von=request.user, status='verbucht')

                    # ── 2) Kaution bilanziell abwickeln (Audit K3) ──
                    # Früher wurden nur Vertragsfelder gesetzt — 1015/2010 blieben ewig
                    # in der Bilanz stehen (stille Drift bei jedem Mieterwechsel).
                    #   Sperrkonto freigeben:  1020 an 1015
                    #   Verrechnung mit OP:    2010 an 1100
                    #   Rest an Mieter:        2010 an 1020
                    # Freigegeben werden darf nur, was tatsächlich in der Bilanz steht.
                    # Das Vertragsfeld `kautions_betrag` ist bloss der VEREINBARTE Betrag —
                    # ohne diese Prüfung wurde eine nie einbezahlte Kaution «freigegeben»
                    # und ausbezahlt: 1015 und 2010 rutschten ins Minus und offene
                    # Mietforderungen galten als getilgt (Audit, kritisch).
                    kaution_bil = _kaution_bilanziert(v)
                    if kaution_verrechnen and (v.kautions_betrag or 0) > 0 \
                            and kaution_bil <= 0 and not v.ist_kautionsversicherung:
                        # Kaution vereinbart, aber nie eingegangen (oder bereits
                        # aufgelöst): das Kautionsthema ist mit dem Auszug erledigt,
                        # es gibt aber nichts freizugeben und nichts auszuzahlen.
                        v.kautions_zurueckbezahlt_am = auszug
                        v.kautions_rueckzahlung_betrag = Decimal('0.00')
                        v.kautions_abzug_betrag = Decimal('0.00')
                        v.save(update_fields=['kautions_zurueckbezahlt_am',
                                              'kautions_rueckzahlung_betrag',
                                              'kautions_abzug_betrag'])
                        messages.warning(request,
                            f"Hinweis: Für diesen Vertrag ist keine Kaution bilanziert "
                            f"(vereinbart CHF {v.kautions_betrag}). Es wurde weder ein "
                            f"Sperrkonto freigegeben noch eine Rückzahlung gebucht.")
                    if kaution_verrechnen and (v.kautions_betrag or 0) > 0 \
                            and (kaution_bil > 0 or v.ist_kautionsversicherung):
                        kaution = min(v.kautions_betrag or Decimal('0.00'), kaution_bil)
                        v.kautions_zurueckbezahlt_am = auszug
                        if v.ist_kautionsversicherung:
                            # Versicherung: kein Depot, keine Rückzahlung an den Mieter.
                            v.kautions_rueckzahlung_betrag = Decimal('0.00')
                            v.save()
                        else:
                            # Offene Forderungen NACH Schritt 1 (inkl. neuer Schlussabrechnung)
                            offene_op = list(DebitorenRechnung.objects
                                             .filter(vertrag=v, status__in=['offen', 'teilbezahlt'])
                                             .order_by('faellig_am', 'id'))
                            offen_nachher = sum((r.offener_betrag for r in offene_op), Decimal('0.00'))
                            verrechnet = min(kaution, offen_nachher)
                            rueck = (kaution - verrechnet).quantize(Decimal('0.01'))
                            v.kautions_rueckzahlung_betrag = rueck
                            v.kautions_abzug_betrag = verrechnet
                            v.save()
                            from finance.models import Buchung as _BS
                            beleg_k = f"Kaution Schlussabrechnung [V{v.pk}] {v.mieter}"
                            if not _BS.objects.filter(beleg_text__startswith=beleg_k,
                                                      ist_storno=False,
                                                      storniert_am__isnull=True).exists():
                                buche("1020", "1015", kaution, f"{beleg_k} — Sperrkonto freigegeben",
                                      datum=dat_s, liegenschaft=lg_s, user=request.user)
                                if verrechnet > 0:
                                    buche("2010", "1100", verrechnet,
                                          f"{beleg_k} — Verrechnung offene Forderungen",
                                          datum=dat_s, liegenschaft=lg_s, user=request.user)
                                if rueck > 0:
                                    buche("2010", "1020", rueck, f"{beleg_k} — Rückzahlung an Mieter",
                                          datum=dat_s, liegenschaft=lg_s, user=request.user)
                            # OP-Nebenbuch nachführen: die verrechnete Kaution tilgt die
                            # offenen Rechnungen (sonst Drift Hauptbuch 1100 ↔ Debitorenliste).
                            rest_v = verrechnet
                            for r_op in offene_op:
                                if rest_v <= 0:
                                    break
                                teil = min(rest_v, r_op.offener_betrag)
                                if teil <= 0:
                                    continue
                                Zahlungseingang.objects.create(
                                    vertrag=v, betrag=teil, datum_eingang=dat_s,
                                    buchungs_monat=(r_op.faellig_am or r_op.datum or dat_s).replace(day=1),
                                    bemerkung=f"Verrechnung Mietkaution — {r_op.titel}"[:255],
                                    debitoren_rechnung=r_op, liegenschaft=lg_s,
                                    erstellt_von=request.user, status='verbucht')
                                r_op.status = 'bezahlt' if r_op.offener_betrag <= 0 else 'teilbezahlt'
                                r_op.save(update_fields=['status'])
                                rest_v -= teil

                    # ── 3) Mieterguthaben (2030) mit auszahlen ──
                    # Ein Guthaben aus Schritt 1 wäre sonst eine Sackgasse: die
                    # Schlussabrechnung weist es dem Mieter als Rückzahlung aus, gebucht
                    # wurde aber nur die Kaution — der Rest bliebe für einen längst
                    # ausgezogenen Mieter dauerhaft auf 2030 stehen (Audit).
                    guthaben_pos = _guthaben_positionen(v)
                    guthaben_offen = sum((z.betrag for z in guthaben_pos), Decimal('0.00'))
                    if guthaben_offen > 0:
                        buche("2030", "1020", guthaben_offen,
                              f"Schlussabrechnung [V{v.pk}] {v.mieter} — Guthaben ausbezahlt",
                              datum=dat_s, liegenschaft=lg_s, user=request.user)
                        for z_g in guthaben_pos:
                            z_g.bemerkung = f"{z_g.bemerkung} {GUTHABEN_AUSBEZAHLT}"[:255]
                            z_g.save(update_fields=['bemerkung'])
                        v.kautions_rueckzahlung_betrag = (
                            (v.kautions_rueckzahlung_betrag or Decimal('0.00')) + guthaben_offen)
                        v.save(update_fields=['kautions_rueckzahlung_betrag'])
            except PermissionError as exc:
                # Rückdatierter Auszug in eine gesperrte Periode: als Meldung
                # zeigen statt als HTTP 500 (Audit).
                messages.error(request, f"❌ {exc}")
                return redirect(f'/neu/vertraege/{v.id}/')
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
                betrag = m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung
                if betrag:
                    txt = f"{m.raum + ': ' if m.raum else ''}{m.beschreibung}"
                    if m.mieteranteil is not None and m.ausstattung_id:
                        txt += " (Zeitwert)"
                    prefill_positionen.append({'text': txt[:90], 'betrag': betrag})
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
        'auszug_default': (v.ende or timezone.localdate()).isoformat(),
        'abnahmen': v.abnahmen.all(),
        'embed_base': ('fw/base_embed.html' if request.GET.get('embed') == '1' else None),
    })


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
                return Decimal((_num(P.get(key)) or str(fallback)))
            except Exception:
                return fallback
        vw.aktueller_referenzzinssatz = dec('aktueller_referenzzinssatz', vw.aktueller_referenzzinssatz)
        vw.aktueller_lik_punkte = dec('aktueller_lik_punkte', vw.aktueller_lik_punkte)
        vw.nk_honorar_prozent = dec('nk_honorar_prozent', vw.nk_honorar_prozent)
        # LIK-Basis + Stand-Monat
        vw.lik_basis = (P.get('lik_basis') or vw.lik_basis or 'Dezember 2020').strip()
        stand_raw = (P.get('aktueller_lik_stand') or '').strip()  # 'YYYY-MM' aus <input type=month>
        if stand_raw:
            try:
                jahr, monat = stand_raw.split('-')[:2]
                vw.aktueller_lik_stand = date(int(jahr), int(monat), 1)
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
        # Logo hochladen oder entfernen
        if P.get('logo_entfernen') == '1' and vw.logo:
            vw.logo.delete(save=False)
            vw.logo = None
        elif request.FILES.get('logo'):
            vw.logo = request.FILES['logo']
        # Digitale Unterschrift: direkt gezeichnet ODER hochgeladen. Bisher nur
        # im Django-Admin hinterlegbar, obwohl jeder Brief sie braucht.
        # Verwaltung.save() macht den weissen Hintergrund automatisch transparent.
        from core.services.unterschrift import uebernehme_aus_formular
        uebernehme_aus_formular(vw, request)
        vw.save()
        log_aktion(request, "Account/Stammdaten bearbeitet", vw.firma,
                   diff_model(alt_snap, snapshot_model(vw), vw))
        messages.success(request, "✅ Stammdaten gespeichert.")
        return redirect('/neu/account/')

    def _url(feld):
        f = getattr(vw, feld, None)
        try:
            return f.url if f else ''
        except Exception:
            return ''
    from core.services.unterschrift import unterschrift_url as _sig_url
    sig_url = _sig_url(vw)
    return render(request, 'fw/account.html', {
        **basis, 'nav': 'account', 'vw': vw,
        'logo_url': _url('logo'), 'unterschrift_url': sig_url,
        'unterschrift_verwaist': bool(getattr(vw, 'unterschrift_bild', None)) and not sig_url,
        'kann_reset': hat_rolle(request.user, [ROLLE_VERWALTUNG]),
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_datenreset(request):
    """GEFAHRENZONE: löscht ALLE operativen Daten (Liegenschaften, Objekte,
    Verträge, Personen, Buchungen, Rechnungen, Schäden, Vorlagen, Mandate,
    Verwaltungs-Stammdaten …) und startet mit einer leeren, frisch geseedeten
    Datenbank. Benutzerkonten/Rollen bleiben erhalten (Login bleibt gültig).
    Erfordert Bestätigungstext 'LÖSCHEN'."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.db import connection
    from django.apps import apps
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('/neu/account/')
    if (request.POST.get('bestaetigung') or '').strip().upper() != 'LÖSCHEN':
        messages.error(request, "Zum Zurücksetzen bitte «LÖSCHEN» eingeben.")
        return redirect('/neu/account/#gefahrenzone')

    # Eigene App-Daten (Framework/Benutzer bleiben erhalten)
    OWN_APPS = {'core', 'crm', 'finance', 'mietprozess', 'portfolio', 'rentals', 'tickets'}
    # Auth-Tabellen NIE anfassen (Login/Rollen bleiben), auch wenn ein Modell
    # im 'core'-App-Label darauf zeigen sollte.
    KEEP = {'auth_user', 'auth_group', 'auth_user_groups', 'auth_group_permissions',
            'auth_permission', 'auth_user_user_permissions', 'django_admin_log',
            'django_content_type', 'django_session', 'django_migrations'}
    tabellen = sorted({m._meta.db_table for m in apps.get_models()
                       if m._meta.app_label in OWN_APPS and m._meta.db_table not in KEEP})

    with connection.constraint_checks_disabled():
        with connection.cursor() as cur:
            for t in tabellen:
                cur.execute(f'DELETE FROM "{t}"')

    # Referenz-/Stammdaten frisch aufsetzen
    from finance.booking import ensure_kontenplan
    from core.services.raumkatalog import seed_lebensdauer
    try:
        ensure_kontenplan()
    except Exception:
        logger.debug("Fehler bewusst übergangen", exc_info=True)
    try:
        seed_lebensdauer()
    except Exception:
        logger.debug("Fehler bewusst übergangen", exc_info=True)

    log_aktion(request, "Datenbank zurückgesetzt", f"{len(tabellen)} Tabellen geleert")
    messages.success(request, "✅ Alle Daten wurden gelöscht — du startest mit einer leeren Datenbank.")
    return redirect('/neu/')


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
    vw = Verwaltung.objects.first()
    # Nur nachladen, wenn der gespeicherte Stand wirklich alt ist. Der Aufruf
    # holt zwei externe Seiten (je timeout=10) und war mit gut einer Sekunde
    # die langsamste Route der Anwendung — bei nicht erreichbaren Quellen bis
    # zu 20 s, in denen der Arbeitsprozess blockiert. Der tägliche Lauf
    # aktualisiert die Werte ohnehin; dieser Weg ist nur die Handnachholung,
    # wenn der Lauf ausgefallen ist.
    stand = getattr(vw, 'letztes_update_marktdaten', None) if vw else None
    veraltet = stand is None or (timezone.now() - stand).days >= 1
    if veraltet and hat_rolle(request.user, SCHREIB_ROLLEN):
        try:
            from core.utils.market_data import update_verwaltung_rates
            update_verwaltung_rates()
            quelle = 'internet'
            vw = Verwaltung.objects.first()
        except Exception:
            logger.warning("Marktdaten-Livenachladen fehlgeschlagen", exc_info=True)
            quelle = 'gespeichert'
    return JsonResponse({
        'ref_zins': float(vw.aktueller_referenzzinssatz) if vw else 1.25,
        'lik': float(vw.aktueller_lik_punkte) if vw else 107.8,
        'stand': vw.letztes_update_marktdaten.strftime('%d.%m.%Y %H:%M') if vw and vw.letztes_update_marktdaten else None,
        'quelle': quelle,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_benutzer(request):
    """Team-Mitglieder (Django-User + Rolle). Portal-Konten (Mieter/Eigentümer)
    werden hier NICHT angezeigt — die werden über Person bzw. Eigentuemer verwaltet."""
    from django.contrib.auth.models import User
    from core.auth import ROLLE_EIGENTUEMER
    basis = _global_filter(request)
    # Die drei Dinge, die unten je Benutzer geprüft werden, gleich mitladen —
    # sonst sind es drei Abfragen pro Zeile (gemessen: 103 für 33 Benutzer).
    users = (User.objects.filter(is_active=True)
             .select_related('mieter_profil', 'eigentuemer_profil')
             .prefetch_related('groups').order_by('username'))
    rows = []
    for u in users:
        # Reine Portal-Zugänge ausblenden (Mieter- oder Eigentümer-Portal)
        if getattr(u, 'mieter_profil', None) is not None:
            continue
        if getattr(u, 'eigentuemer_profil', None) is not None:
            continue
        # `.values_list()` umgeht prefetch_related und fragt je Benutzer nach —
        # über `.all()` gehen wollen wir genau das nicht (gemessen: 32 Abfragen).
        rollen = [g.name for g in u.groups.all()]
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
    """Verzeichnis der mietrechtlichen Gesetzesartikel (OR/VMWG/ZGB) mit
    Kurzfassung, Stichworten, amtlichem Volltext-Link (Fedlex) und Suche.
    Wo ein Artikel in der Software angewandt wird, steht es als Overlay dabei."""
    from core.services import gesetzestexte, mietrecht
    basis = _global_filter(request)
    q = (request.GET.get('q') or '').strip()

    # "Im Programm angewandt"-Overlay: Zitat ('Art. 257e OR') → Anwendungstext
    anwendung = {}
    for key, text in mietrecht.ANWENDUNG.items():
        ref = mietrecht.ref(key)
        if ref:
            anwendung[ref] = text

    gruppen = gesetzestexte.gesetze_uebersicht(q)
    treffer = 0
    for g in gruppen:
        for a in g['artikel']:
            a['anwendung'] = anwendung.get(f"Art. {a['art']} {a['gesetz']}", '')
            treffer += 1

    return render(request, 'fw/rechtsgrundlagen.html', {
        **basis, 'nav': 'rechtsgrundlagen', 'gruppen': gruppen, 'q': q,
        'treffer': treffer, 'gesamt': len(gesetzestexte.REGISTER),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_eigentuemer_liste(request):
    """Eigentümer (Eigentümer, für die verwaltet wird)."""
    from crm.models import Eigentuemer
    basis = _global_filter(request)
    eigentuemer = Eigentuemer.objects.all().order_by('firma_oder_name')
    rows = []
    for md in eigentuemer:
        anzahl_lg = Liegenschaft.objects.filter(eigentuemer=md).count()
        rows.append({'md': md, 'anzahl_lg': anzahl_lg})
    return render(request, 'fw/mandate.html', {**basis, 'nav': 'mandate', 'rows': rows})


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterwechsel(request):
    """Mieterwechsel-Cockpit: EINE Übersicht über alle Vertragswechsel — gekündigte
    UND auslaufende (befristete) Verträge — als Pipeline von Gekündigt/Läuft aus →
    Rücknahme → Nachmieter → neuer Vertrag → Übergabe → Abrechnung."""
    from rentals.models import Kuendigung
    from mietprozess.models import Mietbewerbung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    try:
        monate = int(request.GET.get('monate', '12'))
    except ValueError:
        monate = 12
    grenze = None if monate == 0 else heute + _timedelta(days=int(monate * 30.44))

    def _row(v, ende, gekuendigt, k=None):
        e = v.einheit if v else None
        lg = e.liegenschaft if e else None
        tage = (ende - heute).days if ende else None
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

        kaution_status = v.kautions_status if v else 'keine'
        kaution_offen = kaution_status in ('erwartet', 'einbezahlt')
        kaution_erledigt = kaution_status in ('zurueckbezahlt', 'keine')
        offene_forderungen = (DebitorenRechnung.objects
                              .filter(vertrag=v, status__in=['offen', 'teilbezahlt']).count()) if v else 0
        schluss_offen = bool(auszug and (kaution_offen or offene_forderungen > 0))

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
        elif gekuendigt:
            stufe, farbe, aktion = 'Gekündigt', 'rose', 'Objekt ausschreiben / Rücknahme planen'
        else:
            stufe, farbe, aktion = 'Läuft aus', 'slate', 'Ausschreiben oder Kündigung erfassen'

        return {
            'k': k, 'v': v, 'einheit': e, 'liegenschaft': lg, 'gekuendigt': gekuendigt,
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
        }

    rows = []
    behandelte_vids = set()

    # 1) Gekündigte Verträge (laufende Kündigungen) — immer relevant, kein Horizont
    kq = (Kuendigung.objects.filter(status__in=['erfasst', 'bestaetigt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft')
          .order_by('per_datum', 'berechneter_termin'))
    if aktive_lg:
        kq = kq.filter(vertrag__einheit__liegenschaft=aktive_lg)
    for k in kq:
        v = k.vertrag
        if not v or v.id in behandelte_vids:
            continue
        behandelte_vids.add(v.id)
        rows.append(_row(v, k.per_datum or k.berechneter_termin, gekuendigt=True, k=k))

    # 2) Auslaufende befristete Verträge (aktiv, befristet mit Ende, ohne laufende
    #    Kündigung). `ist_befristet` grenzt sauber gegen unbefristete Verträge ab,
    #    bei denen ein gesetztes `ende` aus einer Kündigung stammt.
    vq = (Mietvertrag.objects.filter(status='aktiv', ist_befristet=True, ende__isnull=False)
          .select_related('mieter', 'einheit__liegenschaft'))
    if aktive_lg:
        vq = vq.filter(einheit__liegenschaft=aktive_lg)
    if grenze:
        vq = vq.filter(ende__lte=grenze)
    for v in vq.order_by('ende'):
        if v.id in behandelte_vids:
            continue
        behandelte_vids.add(v.id)
        rows.append(_row(v, v.ende, gekuendigt=False))

    rows.sort(key=lambda r: (r['ende'] or heute))
    offen = [r for r in rows if r['stufe'] != 'Abgeschlossen']
    return render(request, 'fw/mieterwechsel.html', {
        **basis, **_vermietung_pipeline('mieterwechsel', basis['lg_query']), 'nav': 'mieterwechsel', 'rows': rows,
        'anzahl': len(rows), 'offen': len(offen), 'monate': monate,
        'gekuendigt_n': sum(1 for r in rows if r['gekuendigt']),
        'auslaufend_n': sum(1 for r in rows if not r['gekuendigt']),
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
          .select_related('liegenschaft').prefetch_related('fotos')
          .order_by('verfuegbar_ab', 'liegenschaft__strasse'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    heute = timezone.localdate()
    rows = []
    for e in qs:
        lg = e.liegenschaft
        bew = list(Mietbewerbung.objects.filter(einheit=e).exclude(status='abgelehnt'))
        _fotos = list(e.fotos.all())
        rows.append({
            'e': e, 'liegenschaft': lg,
            'titelbild': _fotos[0].bild.url if _fotos else None,
            'fotos_n': len(_fotos),
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
        **basis, **_vermietung_pipeline('vermarktung', basis['lg_query']), 'nav': 'vermarktung', 'rows': rows, 'anzahl': len(rows),
        'summe_bewerbungen': sum(r['bewerbungen'] for r in rows),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_expose_pdf(request, pk):
    """Exposé/Inserat (PDF) für ein Mietobjekt — Eckdaten, Mietzins, Kontakt."""
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from core.services.expose import generate_expose_pdf, objekt_titel
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=pk)
    pdf = generate_expose_pdf(e, Verwaltung.objects.first())
    resp = HttpResponse(pdf, content_type='application/pdf')
    lg = e.liegenschaft
    fname = f"Expose_{(lg.strasse if lg else e.bezeichnung)}".replace(' ', '_').replace('/', '-')
    resp['Content-Disposition'] = f'inline; filename="{fname}.pdf"'
    return resp


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
         'beschreibung': 'Kreditoren-Belege beim Hochladen automatisch auslesen (Lieferant, Betrag, IBAN, QR-Referenz) — inkl. Foto-Belegen via Bild-KI und E-Mail-Eingang für Handwerker-Rechnungen.',
         'detail': (('Nutzbar unter Kreditoren → «Beleg scannen (KI)» (Mehrfach-Upload). '
                     + (f"E-Mail-Eingang aktiv: {os.environ.get('RECHNUNGS_IMAP_USER')} (fetch_rechnungen)."
                        if os.environ.get('RECHNUNGS_IMAP_USER')
                        else 'E-Mail-Eingang: RECHNUNGS_IMAP_USER/PASSWORD setzen + Scheduled Task «manage.py fetch_rechnungen --einmal».'))
                    if gesetzt('GROQ_API_KEY')
                    else 'GROQ_API_KEY hinterlegen — ohne Key läuft nur die regelbasierte Erkennung aus Text-PDFs.'),
         'aktion': None},
        {'key': 'bank', 'name': 'Banken-Abgleich (camt.053 / QR)', 'icon': 'fa-building-columns', 'farbe': 'sky',
         'aktiv': True, 'status': 'Aktiv',
         'beschreibung': 'Importiere camt.053-Kontoauszüge und ordne Zahlungseingänge automatisch per QR-Referenz den Debitoren zu.',
         'detail': 'Nutzbar im Bereich Bankabgleich.',
         'aktion': 'bank_link'},
    ]
    # Vermarktungs-Portale (Objekt-Feed)
    from crm.models import Verwaltung
    from portfolio.models import Einheit
    vw = Verwaltung.objects.first()
    token = (vw.portal_feed_token if vw else '') or ''
    feed_pfad = f"/neu/vermarktung/feed.json?token={token}" if token else ''
    ausgeschrieben_n = Einheit.objects.filter(zur_ausschreibung=True).count()
    return render(request, 'fw/integrationen.html', {
        **basis, 'nav': 'integrationen', 'integrationen': integrationen,
        'portal_token': token, 'portal_feed_pfad': feed_pfad,
        'portal_ausgeschrieben_n': ausgeschrieben_n,
    })


def fw_vermarktung_feed(request):
    """Öffentlicher, token-gesicherter Objekt-Feed für Immobilien-Portale
    (Homegate, ImmoScout24/SMG, Flatfox …). ?format=csv für CSV, sonst JSON.

    Kein Login — die Absicherung erfolgt über ?token= (Verwaltung.portal_feed_token).
    """
    from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
    from crm.models import Verwaltung
    from core.services.portal_feed import feed_objekte, feed_csv_rows
    import csv as _csv
    import io

    import hmac
    vw = Verwaltung.objects.first()
    erwartet = (vw.portal_feed_token if vw else '') or ''
    token = request.GET.get('token', '')
    # Konstant-zeitiger Vergleich (kein Timing-Seitenkanal beim Token-Raten).
    if not erwartet or not hmac.compare_digest(str(token), str(erwartet)):
        return HttpResponseForbidden("Ungültiger oder fehlender Feed-Token.")

    base = f"{request.scheme}://{request.get_host()}"
    objekte = feed_objekte(base_url=base)

    if request.GET.get('format') == 'csv':
        buf = io.StringIO()
        w = _csv.writer(buf, delimiter=';')
        for row in feed_csv_rows(objekte):
            w.writerow(row)
        resp = HttpResponse(buf.getvalue(), content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename="vermarktung_feed.csv"'
        return resp

    return JsonResponse({
        'anbieter': (vw.firma if vw else ''),
        'anzahl': len(objekte),
        'objekte': objekte,
    }, json_dumps_params={'ensure_ascii': False})


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_integration_portal_token(request):
    """Erzeugt/rotiert oder entfernt den Portal-Feed-Token."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Verwaltung
    from core.auth import log_aktion
    import secrets
    if request.method != 'POST':
        return redirect('/neu/integrationen/')
    vw = Verwaltung.objects.first() or Verwaltung.objects.create(firma='Meine Verwaltung', strasse='', plz='', ort='')
    if request.POST.get('aktion') == 'entfernen':
        vw.portal_feed_token = ''
        vw.save(update_fields=['portal_feed_token'])
        log_aktion(request, "Portal-Feed deaktiviert", vw.firma, '')
        messages.success(request, "Portal-Feed deaktiviert (Token entfernt).")
    else:
        vw.portal_feed_token = secrets.token_urlsafe(24)
        vw.save(update_fields=['portal_feed_token'])
        log_aktion(request, "Portal-Feed-Token erzeugt", vw.firma, '')
        messages.success(request, "✅ Neuer Portal-Feed-Token erzeugt.")
    return redirect('/neu/integrationen/')


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
     'nicht': ['Multi-Eigentuemer (voll)', 'KI-Analysen', 'API-Zugang']},
    {'key': 'premium', 'name': 'Premium', 'preis_einheit': Decimal('2.90'),
     'grund': Decimal('149'), 'gratis_bis': 0, 'farbe': 'purple',
     'zielgruppe': 'Grössere Verwaltungen & Treuhänder',
     'features': ['Alles aus Pro', 'Multi-Eigentuemer & Mandatsabrechnung',
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
        raw = _num(request.POST.get(name))
        try:
            return Decimal(raw) if raw else None
        except Exception:
            return None

    lieferant = (request.POST.get('lieferant') or '').strip()
    betrag = _dec('betrag')
    if not lieferant or not betrag or betrag <= 0:
        messages.error(request, "Lieferant und Betrag (> 0) sind erforderlich.")
        return redirect('fw_kreditoren')

    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    konto = Buchungskonto.objects.filter(id=request.POST.get('konto_id') or None).first() if request.POST.get('konto_id') else None
    # Kein Konto gewählt? Aus Lieferanten-Gedächtnis bzw. Schlüsselwörtern vorschlagen
    # (setzt darüber auch die HNK-Relevanz — is_hnk_relevant leitet unten aus dem Konto ab).
    if konto is None:
        from finance.lieferanten import lieferant_vorschlag, konto_aus_text
        from finance.booking import konto as _konto
        _vp = lieferant_vorschlag(lieferant)
        if _vp and _vp.standard_konto_id:
            konto = _vp.standard_konto
        else:
            _nr = konto_aus_text(lieferant)
            if _nr:
                konto = _konto(_nr)

    def _dat_iso(name):
        try:
            return date.fromisoformat(request.POST.get(name) or '')
        except ValueError:
            return None
    kr = KreditorenRechnung.objects.create(
        lieferant=lieferant, betrag=betrag, mwst_satz=(_dec('mwst_satz') or Decimal('0.0')),
        liegenschaft=lg, konto=konto,
        leistungs_von=_dat_iso('leistungs_von'), leistungs_bis=_dat_iso('leistungs_bis'),
        datum=(date.fromisoformat(request.POST['datum']) if request.POST.get('datum') else timezone.localdate()),
        faellig_am=(date.fromisoformat(request.POST['faellig_am']) if request.POST.get('faellig_am') else None),
        referenz=(request.POST.get('referenz') or '').strip(),
        # IBAN wurde bisher nur im Bearbeiten-Formular erfasst — eine manuell
        # angelegte Rechnung konnte damit NIE in einen Zahllauf (Praxis-Audit).
        iban=(request.POST.get('iban') or '').strip().replace(' ', ''),
        # NK-relevant, wenn Checkbox gesetzt ODER das gewählte Konto HNK-relevant ist
        is_hnk_relevant=(request.POST.get('is_hnk_relevant') == 'on'
                         or bool(konto and konto.is_hnk_relevant)),
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


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kreditor_scan(request):
    """KI-Rechnungsscanner: Belege hochladen (auch MEHRERE gleichzeitig) → jeder
    wird DIREKT gescannt (Groq-KI, Vision für Foto-Belege, Regex-Fallback) und
    als Kreditorenrechnung (Status Neu) mit den erkannten Daten angelegt. Die
    Erkennungs-Methode wird ehrlich gemeldet; Werte sind per Klick auf die
    Zeile korrigierbar (Edit-Panel mit Beleg-Vorschau)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.services.belegimport import beleg_importieren
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')

    dateien = request.FILES.getlist('beleg_scan')[:20]
    if not dateien:
        messages.error(request, "Bitte mindestens einen Beleg (PDF oder Foto) auswählen.")
        return redirect('fw_kreditoren')

    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    for datei in dateien:
        kr, daten = beleg_importieren(datei, liegenschaft=lg)
        methode = daten.get('methode')
        log_aktion(request, "Beleg gescannt (KI-Rechnungsscanner)",
                   kr.lieferant or datei.name, f"Methode: {methode} · CHF {kr.betrag or 0}")
        _kreditor_scan_meldung(request, kr, daten, datei.name)
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


def _kreditor_scan_meldung(request, kr, daten, dateiname):
    """Toast je gescanntem Beleg — Methode ehrlich ausweisen."""
    from django.contrib import messages
    methode = daten.get('methode')
    zusammenfassung = (f"«{kr.lieferant or 'Lieferant unbekannt'}»"
                       f"{f' · CHF {kr.betrag}' if kr.betrag else ''}"
                       f"{f' · {kr.datum.strftime(chr(37)+chr(100)+chr(46)+chr(37)+chr(109)+chr(46)+chr(37)+chr(89))}' if kr.datum else ''}")
    konto_hint = f" · Konto {daten['konto_auto']} automatisch zugeteilt" if daten.get('konto_auto') else ''
    if methode in ('ki', 'vision', 'qr'):
        messages.success(request, f"🤖 Beleg gescannt ({daten.get('hinweis')}): {zusammenfassung}{konto_hint} — bitte prüfen und freigeben.")
    elif methode == 'regex':
        messages.warning(request, f"Beleg regelbasiert ausgelesen (KI nicht aktiv/erreichbar): {zusammenfassung} — bitte Werte prüfen.")
    else:
        messages.warning(request, f"Beleg «{dateiname}» gespeichert, aber nicht auslesbar: {daten.get('hinweis')} Werte bitte manuell ergänzen.")


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kreditor_bearbeiten(request, pk):
    """Korrigiert eine noch nicht verbuchte Kreditorenrechnung (Status Neu) —
    v.a. zum Nachbessern gescannter Werte. Verbuchte Rechnungen sind gesperrt."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, Buchungskonto
    from core.auth import log_aktion
    k = get_object_or_404(KreditorenRechnung, id=pk)
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    if k.status != 'neu':
        messages.error(request, "Nur unverbuchte Rechnungen (Status Neu) können bearbeitet werden.")
        return redirect('fw_kreditoren')

    def _dec(name):
        raw = _num(request.POST.get(name))
        try:
            return Decimal(raw) if raw else None
        except Exception:
            return None

    def _dat(name):
        try:
            return date.fromisoformat(request.POST.get(name) or '')
        except ValueError:
            return None

    k.lieferant = (request.POST.get('lieferant') or '').strip()
    betrag = _dec('betrag')
    k.betrag = betrag if betrag and betrag > 0 else None
    k.datum = _dat('datum') or k.datum
    k.faellig_am = _dat('faellig_am')
    k.leistungs_von = _dat('leistungs_von')
    k.leistungs_bis = _dat('leistungs_bis')
    k.referenz = (request.POST.get('referenz') or '').strip()
    k.iban = re.sub(r'\s+', '', request.POST.get('iban') or '')[:50]
    if request.POST.get('liegenschaft_id'):
        k.liegenschaft = Liegenschaft.objects.filter(id=request.POST['liegenschaft_id']).first()
    if request.POST.get('konto_id'):
        k.konto = Buchungskonto.objects.filter(id=request.POST['konto_id']).first()
    # NK-Relevanz: Checkbox ODER (neu zugewiesenes) HNK-Konto
    k.is_hnk_relevant = (request.POST.get('is_hnk_relevant') == 'on'
                         or bool(k.konto and k.konto.is_hnk_relevant))
    k.fehlermeldung = ''
    k.save()
    log_aktion(request, "Kreditorenrechnung bearbeitet", k.lieferant, f"CHF {k.betrag or 0}")
    messages.success(request, f"✅ Rechnung «{k.lieferant}» aktualisiert.")
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

    # Aufwandskonto zuweisen (aus Formular oder bestehendes). Mit Kostenaufteilung
    # ist das Kopf-Konto optional — dann bucht jede Position ihr eigenes Konto.
    if request.POST.get('konto_id'):
        k.konto = Buchungskonto.objects.filter(id=request.POST['konto_id']).first()
    positionen = list(k.positionen.select_related('konto', 'liegenschaft'))
    if positionen:
        # Aufteilung muss aufgehen (Summe der Positionen == Rechnungsbetrag).
        if abs(k.positionen_differenz) > Decimal('0.01'):
            messages.error(request, f"Die Kostenaufteilung stimmt nicht: Summe der Positionen "
                                    f"weicht um CHF {k.positionen_differenz} vom Rechnungsbetrag ab.")
            return redirect('fw_kreditoren')
    elif not k.konto:
        messages.error(request, "Bitte zuerst ein Aufwandskonto zuweisen (oder die Rechnung aufteilen).")
        return redirect('fw_kreditoren')

    with transaction.atomic():
        # Zeilensperre + Re-Check gegen Doppelklick-Race: der Status-Check oben ist
        # ohne Lock — zwei parallele Requests würden sonst doppelten Aufwand buchen.
        gesperrt = KreditorenRechnung.objects.select_for_update().filter(id=k.id).first()
        if not gesperrt or gesperrt.status != 'neu':
            messages.info(request, "Rechnung ist bereits freigegeben oder bezahlt.")
            return redirect('fw_kreditoren')
        # NK-Relevanz automatisch vom Konto ableiten: HNK-Konto (4100–4140/4400)
        # ⇒ Rechnung fliesst in die Nebenkostenabrechnung — kein vergessenes
        # Häkchen mehr. (Nur aktivieren, nie eine manuelle Wahl deaktivieren.)
        if positionen and any(p.is_hnk_relevant for p in positionen) and not k.is_hnk_relevant:
            k.is_hnk_relevant = True
        elif k.konto and k.konto.is_hnk_relevant and not k.is_hnk_relevant:
            k.is_hnk_relevant = True
        k.status = 'freigegeben'
        k.save()
        from finance.booking import buche
        datum_b = k.datum or timezone.localdate()
        brutto = k.betrag or Decimal('0.00')
        satz = k.mwst_satz or Decimal('0')

        def _netto(brutto_teil):
            if satz > 0:
                vs = (brutto_teil * satz / (Decimal('100') + satz)).quantize(Decimal('0.01'))
                return brutto_teil - vs, vs
            return brutto_teil, Decimal('0.00')

        vorsteuer_total = Decimal('0.00')
        if positionen:
            # Jede Position einzeln buchen (eigenes Konto/Objekt).
            for p in positionen:
                netto_p, vs_p = _netto(p.betrag)
                vorsteuer_total += vs_p
                text = f"Rechnung {k.lieferant}{f' · {p.bezeichnung}' if p.bezeichnung else ''}"
                buche(p.konto, "2000", netto_p, text[:255], datum=datum_b,
                      liegenschaft=p.liegenschaft or k.liegenschaft, kreditor=k, user=request.user)
        else:
            netto, vorsteuer_total = _netto(brutto)
            buche(k.konto, "2000", netto, f"Rechnung {k.lieferant} - {k.referenz}",
                  datum=datum_b, liegenschaft=k.liegenschaft, kreditor=k, user=request.user)
        if vorsteuer_total > 0:
            k.mwst_betrag = vorsteuer_total
            k.save(update_fields=['mwst_betrag'])
            buche("1170", "2000", vorsteuer_total, f"Vorsteuer {k.mwst_satz}% {k.lieferant}",
                  datum=datum_b, liegenschaft=k.liegenschaft, kreditor=k, user=request.user)
        # Lieferanten-Gedächtnis fortschreiben: dieses Konto wird künftig für
        # denselben Lieferanten automatisch vorgeschlagen.
        from finance.lieferanten import lerne_lieferant
        lerne_lieferant(k.lieferant, konto=k.konto, iban=k.iban)
    log_aktion(request, "Kreditorenrechnung freigegeben", k.lieferant, f"CHF {k.betrag}")
    messages.success(request, f"✅ '{k.lieferant}' freigegeben und verbucht.")
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_mietzins_add(request, pk):
    """Fügt dem Mietverhältnis eine datierte Mietzins-Komponente hinzu (gültig ab,
    Netto, NK) — für Gratismonate/gestaffelten Start. Massgeblich für die Sollstellung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Mietvertrag, VertragMietzins
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag, id=pk)
    # Rücksprung: Objekt-Mietzins-Tab (wenn von dort erfasst) sonst Vertrag-Tab.
    _nxt = request.POST.get('next') or ''
    ziel = _nxt if _nxt.startswith('/neu/') else f'/neu/vertraege/{v.id}/?tab=mietzins'
    if request.method != 'POST':
        return redirect(ziel)

    def _dec(name):
        raw = _num(request.POST.get(name))
        try:
            return Decimal(raw)
        except Exception:
            return None
    try:
        gab = date.fromisoformat(request.POST.get('gueltig_ab') or '')
    except ValueError:
        gab = None
    netto = _dec('netto_mietzins')
    nk = _dec('nebenkosten')
    if not gab or netto is None or nk is None or netto < 0 or nk < 0:
        messages.error(request, "Gültig-ab-Datum, Netto und NK (≥ 0) sind erforderlich.")
        return redirect(ziel)
    # Rabatt/Erlass (Option B): mindert nur die Verrechnung, nicht die Referenz.
    # "mietzinsfrei" = Nettomietzins voll erlassen → Rabatt = Netto-Referenz.
    if request.POST.get('mietzinsfrei'):
        rabatt_netto = netto
    else:
        rabatt_netto = _dec('rabatt_netto') or Decimal('0.00')
    rabatt_nk = _dec('rabatt_nk') or Decimal('0.00')
    if rabatt_netto < 0 or rabatt_nk < 0:
        messages.error(request, "Rabatt-Werte dürfen nicht negativ sein.")
        return redirect(ziel)
    rabatt_netto = min(rabatt_netto, netto)   # Rabatt nie grösser als Referenz
    rabatt_nk = min(rabatt_nk, nk)
    VertragMietzins.objects.update_or_create(
        vertrag=v, gueltig_ab=gab,
        defaults={'netto_mietzins': netto, 'nebenkosten': nk,
                  'rabatt_netto': rabatt_netto, 'rabatt_nk': rabatt_nk,
                  'notiz': (request.POST.get('notiz') or '').strip()[:200]})
    zu_zahlen = max(Decimal('0'), netto - rabatt_netto) + max(Decimal('0'), nk - rabatt_nk)
    log_aktion(request, "Mietzins-Komponente erfasst", str(v),
               f"ab {gab:%d.%m.%Y}: Referenz Netto {netto} / NK {nk}, "
               f"Rabatt {rabatt_netto}/{rabatt_nk}, zu zahlen {zu_zahlen}", ziel=v)
    messages.success(request, f"✅ Komponente ab {gab:%d.%m.%Y} gespeichert "
                     f"(Referenz CHF {netto + nk}, zu zahlen CHF {zu_zahlen}).")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_mietzins_del(request, pk):
    """Entfernt eine Mietzins-Komponente."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import VertragMietzins
    k = get_object_or_404(VertragMietzins.objects.select_related('vertrag'), id=pk)
    vid = k.vertrag_id
    _nxt = request.POST.get('next') or ''
    ziel = _nxt if _nxt.startswith('/neu/') else f'/neu/vertraege/{vid}/?tab=mietzins'
    if request.method == 'POST':
        k.delete()
        messages.success(request, "Komponente entfernt.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kreditor_position_add(request, pk):
    """Fügt einer noch nicht verbuchten Kreditorenrechnung eine Kostenposition
    hinzu (Konto + optional Objekt + Betrag + HNK). Ermöglicht das Aufteilen
    einer Sammel-/Mischrechnung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, KreditorPosition, Buchungskonto
    from core.auth import log_aktion
    k = get_object_or_404(KreditorenRechnung, id=pk)
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    if k.status != 'neu':
        messages.error(request, "Nur unverbuchte Rechnungen (Status Neu) können aufgeteilt werden.")
        return redirect('fw_kreditoren')
    konto = Buchungskonto.objects.filter(id=request.POST.get('konto_id') or None).first()
    try:
        betrag = Decimal(_num(request.POST.get('betrag')))
    except Exception:
        betrag = None
    if not konto or not betrag or betrag <= 0:
        messages.error(request, "Konto und Betrag (> 0) sind für eine Position erforderlich.")
        return redirect('fw_kreditoren')
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first() or k.liegenschaft
    einheit = Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first()
    KreditorPosition.objects.create(
        rechnung=k, konto=konto, betrag=betrag,
        bezeichnung=(request.POST.get('bezeichnung') or '').strip()[:200],
        liegenschaft=lg, einheit=einheit,
        is_hnk_relevant=(request.POST.get('is_hnk_relevant') == 'on' or bool(konto.is_hnk_relevant)))
    log_aktion(request, "Kreditor-Position hinzugefügt", k.lieferant, f"{konto.nummer} · CHF {betrag}")
    messages.success(request, f"✅ Position {konto.nummer} über CHF {betrag} hinzugefügt.")
    return redirect('/neu/kreditoren/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_kreditor_position_del(request, pk):
    """Entfernt eine Kostenposition (nur solange die Rechnung unverbucht ist)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorPosition
    p = get_object_or_404(KreditorPosition.objects.select_related('rechnung'), id=pk)
    if request.method == 'POST':
        if p.rechnung.status != 'neu':
            messages.error(request, "Nur unverbuchte Rechnungen können geändert werden.")
        else:
            p.delete()
            messages.success(request, "Position entfernt.")
    return redirect('/neu/kreditoren/')


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
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    if not lg:
        messages.error(request, "Liegenschaft ist erforderlich.")
        return redirect('fw_assets')
    g = Geraet.objects.create(
        liegenschaft=lg,
        einheit=Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first() if request.POST.get('einheit_id') else None,
        kategorie=request.POST.get('kategorie', 'sonstiges'),
        sonstiges_bezeichnung=(request.POST.get('sonstiges_bezeichnung') or '').strip(),
        marke=(request.POST.get('marke') or '').strip(),
        modell=(request.POST.get('modell') or '').strip(),
        seriennummer=(request.POST.get('seriennummer') or '').strip(),
        kapazitaet=(request.POST.get('kapazitaet') or '').strip(),
        standort=(request.POST.get('standort') or '').strip(),
        installations_datum=(date.fromisoformat(request.POST['installations_datum']) if request.POST.get('installations_datum') else None),
        garantie_bis=(date.fromisoformat(request.POST['garantie_bis']) if request.POST.get('garantie_bis') else None),
        notiz=(request.POST.get('notiz') or '').strip(),
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
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    PDokument.objects.create(
        titel=(request.POST.get('titel') or request.FILES['datei'].name).strip(),
        kategorie=request.POST.get('kategorie', 'sonstiges'),
        liegenschaft=lg,
        einheit=Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first() if request.POST.get('einheit_id') else None,
        datei=request.FILES['datei'],
    )
    log_aktion(request, "Dokument hochgeladen", request.POST.get('titel', ''), '')
    messages.success(request, "✅ Dokument hochgeladen.")
    ziel = '/neu/dokumente/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dokument_loeschen(request, pk):
    """Portfolio-/Objekt-Dokument löschen (hochgeladene Ablage)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Dokument as PDokument
    from core.auth import log_aktion
    d = get_object_or_404(PDokument, id=pk)
    if request.method == 'POST':
        titel = d.titel
        d.delete()
        log_aktion(request, "Dokument gelöscht", titel, '')
        messages.success(request, "🗑️ Dokument gelöscht.")
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
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
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
def fw_dienstleister_bearbeiten(request, pk):
    """Dienstleister / Handwerker bearbeiten (Stammdaten)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Handwerker
    from core.auth import log_aktion
    h = get_object_or_404(Handwerker, id=pk)
    if request.method != 'POST':
        return redirect('fw_dienstleister')
    firma = (request.POST.get('firma') or '').strip()
    if not firma:
        messages.error(request, "Firma ist erforderlich.")
        return redirect('fw_dienstleister')
    h.firma = firma
    h.branche = request.POST.get('branche', h.branche) or h.branche
    h.kontaktperson = (request.POST.get('kontaktperson') or '').strip()
    h.email = (request.POST.get('email') or '').strip()
    h.telefon = (request.POST.get('telefon') or '').strip()
    h.save()
    log_aktion(request, "Dienstleister bearbeitet", firma, '')
    messages.success(request, f"✅ Dienstleister '{firma}' aktualisiert.")
    return redirect('fw_dienstleister')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_dienstleister_loeschen(request, pk):
    """Dienstleister / Handwerker löschen (Stammdaten)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Handwerker
    from core.auth import log_aktion
    h = get_object_or_404(Handwerker, id=pk)
    if request.method == 'POST':
        firma = h.firma
        h.delete()
        log_aktion(request, "Dienstleister gelöscht", firma, '')
        messages.success(request, f"🗑️ Dienstleister '{firma}' gelöscht.")
    return redirect('fw_dienstleister')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_asset_bearbeiten(request, pk):
    """Asset / Gerät (Portfolio-Assetliste) bearbeiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    g = get_object_or_404(Geraet, id=pk)
    ziel = '/neu/assets/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    if request.method != 'POST':
        return redirect(ziel)

    def _date(x):
        try:
            return date.fromisoformat(x)
        except Exception:
            return None

    kategorie = (request.POST.get('kategorie') or '').strip()
    if kategorie:
        g.kategorie = kategorie
    g.sonstiges_bezeichnung = (request.POST.get('sonstiges_bezeichnung') or '').strip()
    g.marke = (request.POST.get('marke') or '').strip()
    g.modell = (request.POST.get('modell') or '').strip()
    g.seriennummer = (request.POST.get('seriennummer') or '').strip()
    g.kapazitaet = (request.POST.get('kapazitaet') or '').strip()
    g.standort = (request.POST.get('standort') or '').strip()
    g.installations_datum = _date(request.POST.get('installations_datum'))
    g.garantie_bis = _date(request.POST.get('garantie_bis'))
    g.notiz = (request.POST.get('notiz') or '').strip()
    g.save()
    log_aktion(request, "Asset bearbeitet", f"{g.kategorie} {g.marke}".strip(), '')
    messages.success(request, "✅ Asset aktualisiert.")
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_asset_loeschen(request, pk):
    """Asset / Gerät (Portfolio-Assetliste) löschen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Geraet
    from core.auth import log_aktion
    g = get_object_or_404(Geraet, id=pk)
    if request.method == 'POST':
        from core.models import Pendenz
        bez = f"{g.kategorie} {g.marke}".strip()
        # Verwaiste Auto-Garantie-Pendenz mitlöschen (hängt nur über `quelle`).
        Pendenz.objects.filter(quelle=f"auto:garantie:{g.id}").delete()
        g.delete()
        log_aktion(request, "Asset gelöscht", bez, '')
        messages.success(request, "🗑️ Asset gelöscht.")
    ziel = '/neu/assets/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_kreditor_loeschen(request, pk):
    """Kreditorenrechnung löschen — NUR solange sie noch nicht verbucht ist
    (Status 'neu'). Verbuchte Rechnungen werden aus Revisionsgründen nicht
    gelöscht, sondern per Storno der Buchung rückgängig gemacht."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung
    from core.auth import log_aktion
    k = get_object_or_404(KreditorenRechnung, id=pk)
    if request.method == 'POST':
        if k.status != 'neu':
            messages.error(request, "Bereits verbuchte Rechnung kann nicht gelöscht werden — "
                                    "bitte die zugehörige Buchung stornieren.")
        else:
            lief = k.lieferant
            k.delete()
            log_aktion(request, "Kreditorenrechnung gelöscht", lief, '')
            messages.success(request, f"🗑️ Kreditorenrechnung '{lief}' gelöscht.")
    ziel = '/neu/kreditoren/'
    if lgq := request.POST.get('lg'):
        ziel += f'?lg={lgq}'
    return redirect(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_nebenkosten_loeschen(request, pk):
    """Nebenkosten-Abrechnungsperiode löschen — nur solange nicht abgeschlossen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import AbrechnungsPeriode
    from core.auth import log_aktion
    p = get_object_or_404(AbrechnungsPeriode, id=pk)
    if request.method == 'POST':
        if getattr(p, 'abgeschlossen', False):
            messages.error(request, "Abgeschlossene Periode kann nicht gelöscht werden.")
            return redirect(f'/neu/nebenkosten/{p.id}/')
        bez = p.bezeichnung
        p.delete()
        log_aktion(request, "Abrechnungsperiode gelöscht", bez, '')
        messages.success(request, f"🗑️ Abrechnungsperiode '{bez}' gelöscht.")
    return redirect('fw_nebenkosten')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_buchung_neu(request):
    """Manuelle Buchung erfassen (Soll an Haben)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_buchhaltung')

    def _konto_aus_post(feld_nummer, feld_id):
        """Akzeptiert die KONTONUMMER (Tastatureingabe) oder die ID (Alt-Formulare).
        Die Nummer ist der Weg, den ein Buchhalter erwartet — vorher gab es nur
        ein <select> über den ganzen Kontenplan (Audit)."""
        nr = (request.POST.get(feld_nummer) or '').strip()
        if nr:
            # Die datalist zeigt «4000 Unterhalt» — nur der führende Zahlenteil zählt.
            nr = nr.split()[0].strip()
            k = Buchungskonto.objects.filter(nummer=nr).first()
            if k:
                return k
        return Buchungskonto.objects.filter(id=request.POST.get(feld_id) or None).first()

    # Serienerfassung: zurück zur Maske statt auf die Übersicht, damit ein Stapel
    # ohne Neuaufklappen und ohne erneutes Tippen von Datum/Konten läuft.
    weiter = request.POST.get('weiter') == '1'

    def _zurueck(fehler=False):
        if not weiter:
            return redirect('fw_buchhaltung')
        # Werte für die nächste Zeile in der Session merken.
        request.session['bu_serie'] = True
        return redirect('/neu/buchhaltung/?tab=journal#buchform')

    soll = _konto_aus_post('soll_konto', 'soll_konto_id')
    haben = _konto_aus_post('haben_konto', 'haben_konto_id')
    try:
        betrag = Decimal((_num(request.POST.get('betrag')) or '0'))
    except Exception:
        betrag = Decimal('0')
    text = (request.POST.get('beleg_text') or '').strip()
    if not soll or not haben or betrag <= 0 or not text:
        messages.error(request, "Soll-, Haben-Konto (gültige Nummer), Betrag (> 0) und Belegtext sind erforderlich.")
        return _zurueck(fehler=True)
    if soll.id == haben.id:
        messages.error(request, "Soll- und Haben-Konto müssen unterschiedlich sein.")
        return _zurueck(fehler=True)
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first() if request.POST.get('liegenschaft_id') else None
    bu_datum = (date.fromisoformat(request.POST['datum']) if request.POST.get('datum')
                else timezone.localdate())
    try:
        Buchung.objects.create(
            datum=bu_datum, beleg_text=text, liegenschaft=lg,
            soll_konto=soll, haben_konto=haben,
            betrag=betrag, erstellt_von=request.user)
    except PermissionError as exc:          # Periodensperre
        messages.error(request, f"❌ {exc}")
        return _zurueck(fehler=True)
    log_aktion(request, "Manuelle Buchung", text, f"{soll.nummer}/{haben.nummer} CHF {betrag}")
    messages.success(request, f"✅ Buchung erfasst: {soll.nummer} an {haben.nummer} · CHF {betrag}.")
    # Datum, Konten und Liegenschaft für den nächsten Beleg vorhalten.
    request.session['bu_letzt'] = {
        'datum': bu_datum.isoformat(), 'soll': soll.nummer, 'haben': haben.nummer,
        'lg': lg.id if lg else None,
    }
    return _zurueck()


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_buchung_stornieren(request, pk):
    """Storniert eine Journalbuchung durch eine revisionssichere Gegenbuchung.
    Die Originalbuchung bleibt erhalten (append-only, OR 958f). Nur Verwaltung —
    ein Storno ist ein buchhalterischer Korrektureingriff (nicht Sachbearbeitung)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchung
    from finance.booking import storniere_buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_buchhaltung')
    b = get_object_or_404(Buchung, id=pk)
    # Eine EINZELNE Abschlussbuchung darf nicht im Journal storniert werden — das
    # liesse das Geschäftsjahr halb geschlossen zurück (ein Teil der Erfolgskonten
    # gegen 2970 saldiert, der Rest offen) und verschöbe Vorjahresaufwand ins
    # laufende Jahr. Ein Abschluss wird atomar über «Abschluss zurücknehmen»
    # gelöst (Audit-Befund H6).
    from core.services.jahresabschluss import BELEG_PREFIX as _ABSCHLUSS_PREFIX
    if b.beleg_text.startswith(_ABSCHLUSS_PREFIX):
        messages.error(request, "Abschlussbuchungen lassen sich nicht einzeln stornieren. "
                                "Bitte den Jahresabschluss gesamthaft über «Abschluss zurücknehmen» aufheben.")
        return redirect('fw_buchhaltung')
    try:
        gegen = storniere_buchung(b, user=request.user)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('fw_buchhaltung')
    except PermissionError as e:
        messages.error(request, str(e))
        return redirect('fw_buchhaltung')
    log_aktion(request, "Buchung storniert", b.beleg_text,
               f"Beleg #{b.beleg_nr} → Storno #{gegen.beleg_nr} · CHF {b.betrag}")
    messages.success(request, f"✅ Beleg #{b.beleg_nr} storniert (Gegenbuchung #{gegen.beleg_nr}).")
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
    from core.utils.email_service import journal_email
    gesendet = 0
    for mid in ids:
        m = Mieter.objects.filter(id=mid).first()
        if m and m.email:
            if send_ticket_email(m.email, betreff, text):
                gesendet += 1
                journal_email(betreff, text, mieter=m, user=request.user, empfaenger=m.email)
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

    pdf = generate_serienbrief_pdf(absender, betreff, text, empfaenger,
                                   logo_path=logo_path, signatur=(vw,))

    # Auto-Ablage: pro Empfänger eine eigene (einseitige) Brief-Kopie in dessen
    # Akte ablegen — erscheint automatisch im Mieterportal (portal-sichtbar).
    abgelegt = 0
    for e in empfaenger:
        m = Mieter.objects.filter(id=e.get('_mieter_id')).first()
        if not m:
            continue
        v = Mietvertrag.objects.filter(id=e.get('_vertrag_id')).first() if e.get('_vertrag_id') else None
        einzel = generate_serienbrief_pdf(absender, betreff, text, [e],
                                          logo_path=logo_path, signatur=(vw,))
        # Titel mit aufgelösten Platzhaltern ({liegenschaft} etc.) — nicht roh.
        from core.services.serienbrief import _ersetze
        betreff_aufgeloest = _ersetze(betreff, e) or betreff
        # Ablage am Vertrag (erscheint im Portal beider Personen) + am Hauptmieter
        if ablegen(einzel, f"Brief: {betreff_aufgeloest}", kategorie='korrespondenz', vertrag=v, mieter=m):
            abgelegt += 1

    log_aktion(request, "Serienbrief-PDF erzeugt", betreff, f"{len(empfaenger)} Empfänger · {abgelegt} abgelegt")
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="serienbrief_{date.today().isoformat()}.pdf"'
    return resp


# ══════════════════════════════════════════════════════════════
# UI-MODUS (Einfach/Profi) + EINSTELLUNGEN-HUB
# ══════════════════════════════════════════════════════════════

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_modus_wechsel(request):
    """Schaltet die Oberfläche zwischen Einfach- und Profi-Modus um (Session)."""
    from django.shortcuts import redirect
    from core.navigation import UI_MODI, SESSION_KEY
    if request.method == 'POST':
        modus = request.POST.get('modus')
        if modus in UI_MODI:
            request.session[SESSION_KEY] = modus
    ziel = request.META.get('HTTP_REFERER') or '/neu/'
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_einstellungen(request):
    """Zentrale Einstellungen-Seite — bündelt die früheren 8 Profil-Dropdown-
    Punkte (Account, Abonnement, Benutzer, Logbuch, Vorlagen, Integrationen,
    Rechtsgrundlagen) als eine Hub-Seite mit Sektionen."""
    basis = _global_filter(request)
    karten = [
        {'titel': 'Account', 'sub': 'Verwaltungs-Stammdaten, Logo, Absender', 'url': '/neu/account/', 'icon': 'fa-id-card'},
        {'titel': 'Benutzer & Rollen', 'sub': 'Team-Mitglieder und Berechtigungen', 'url': '/neu/benutzer/', 'icon': 'fa-users'},
        {'titel': 'Vorlagen', 'sub': 'Textvorlagen mit Platzhaltern', 'url': '/neu/vorlagen/', 'icon': 'fa-file-lines'},
        {'titel': 'Integrationen', 'sub': 'E-Mail, DocuSeal, KI, Banken, Portal-Feed', 'url': '/neu/integrationen/', 'icon': 'fa-plug'},
        {'titel': 'Abonnement', 'sub': 'Plan und Rechnungsstellung', 'url': '/neu/abonnement/', 'icon': 'fa-star'},
        {'titel': 'Logbuch', 'sub': 'Wer hat wann was geändert', 'url': '/neu/logbuch/', 'icon': 'fa-clock-rotate-left'},
        {'titel': 'Rechtsgrundlagen', 'sub': 'OR/VMWG-Artikel mit Anwendung im Programm', 'url': '/neu/rechtsgrundlagen/', 'icon': 'fa-scale-balanced'},
    ]
    return render(request, 'fw/einstellungen.html', {
        **basis, 'nav': 'einstellungen', 'karten': karten,
    })




@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zahlung_zuordnen(request):
    """Ordnet eine geparkte Zahlung (Durchlaufkonto 1190 / Mieterguthaben 2030)
    nachträglich einer offenen Debitorenrechnung zu — Audit-Befund «1190 ist
    eine Sackgasse». Bucht Parkkonto an 1100, verknüpft den Zahlungseingang
    mit Vertrag+Rechnung und führt den OP-Status nach. Ein Überschuss über den
    offenen Betrag bleibt als Rest-Guthaben auf dem Parkkonto liegen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.booking import buche
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')

    from core.services.zahlungszuordnung import zuordnen, ZuordnungsFehler

    with transaction.atomic():
        # Zeilensperre: ohne sie buchen zwei parallele Zuordnungen dieselbe
        # Forderung doppelt aus.
        zahlung = get_object_or_404(
            Zahlungseingang.objects.select_for_update(), id=request.POST.get('zahlung_id'))
        rechnung = get_object_or_404(
            DebitorenRechnung.objects.select_for_update(), id=request.POST.get('rechnung_id'))
        park_nr = zahlung.konto.nummer if zahlung.konto_id else ''
        vertrag = rechnung.vertrag
        try:
            betrag, rest, gelernt = zuordnen(zahlung, rechnung, user=request.user)
        except ZuordnungsFehler as e:
            messages.error(request, str(e))
            return redirect('fw_bankabgleich')
        except PermissionError as e:
            messages.error(request, f"Periodensperre: {e}")
            return redirect('fw_bankabgleich')

    log_aktion(request, "Geparkte Zahlung zugeordnet", str(vertrag),
               f"CHF {betrag} von {park_nr} auf {rechnung.titel}"
               + (f" · Absender «{gelernt}» gemerkt" if gelernt else ""))
    messages.success(request, f"✅ CHF {betrag} zugeordnet — {vertrag.mieter.display_name} "
                              f"({rechnung.titel}){f' · Rest CHF {rest} bleibt als Guthaben' if rest > 0 else ''}.")
    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'
    from django.shortcuts import redirect as _r
    return _r(ziel)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zahlungen_sammel_zuordnen(request):
    """Ordnet mehrere geparkte Zahlungen auf einen Schlag EINEM Mieter zu.

    Zahlt jemand monatlich ohne QR-Referenz, sammeln sich auf dem Durchlaufkonto
    schnell ein Dutzend gleich aussehender Posten an — einzeln zugeordnet ist das
    eine Viertelstunde Klickarbeit. Hier wird pro Zahlung die ÄLTESTE offene
    Forderung des Mieters getilgt; ein Überschuss bleibt als Guthaben stehen.
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    from core.services.zahlungszuordnung import sammel_zuordnen

    if request.method != 'POST':
        return redirect('fw_bankabgleich')

    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'

    ids = [i for i in request.POST.getlist('zahlung_ids') if i.isdigit()]
    vertrag = Mietvertrag.objects.filter(id=request.POST.get('vertrag_id') or 0) \
        .select_related('mieter', 'einheit__liegenschaft').first()
    if not ids:
        messages.warning(request, "Keine Zahlung ausgewählt.")
        return redirect(ziel)
    if vertrag is None:
        messages.error(request, "Kein Mieter gewählt — die Zahlungen bleiben ungeklärt.")
        return redirect(ziel)

    with transaction.atomic():
        # Zeilensperre wie bei der Einzelzuordnung: sonst bucht ein paralleler
        # Lauf dieselbe Forderung ein zweites Mal aus.
        zahlungen = list(Zahlungseingang.objects.select_for_update()
                         .filter(id__in=ids, status='verbucht',
                                 konto__nummer__in=['1190', '2030'])
                         .select_related('konto'))
        anzahl, summe, rest, fehler, gelernt = sammel_zuordnen(
            zahlungen, vertrag, user=request.user)

    if anzahl:
        log_aktion(request, "Zahlungen sammelweise zugeordnet", str(vertrag),
                   f"{anzahl} Zahlung(en), CHF {summe}"
                   + (f", Rest CHF {rest} als Guthaben" if rest else "")
                   + (f" · Absender «{gelernt}» gemerkt" if gelernt else ""))
        messages.success(
            request,
            f"✅ {anzahl} Zahlung(en) zugeordnet (CHF {summe}) — "
            f"{vertrag.mieter.display_name}"
            + (f" · CHF {rest} bleiben als Guthaben" if rest else "")
            + (f" · Absender «{gelernt}» gemerkt, künftige Zahlungen treffen selbst"
               if gelernt else "") + ".")
    for f in fehler:
        messages.warning(request, f"Nicht zugeordnet — {f}")
    if not anzahl and not fehler:
        messages.warning(request, "Nichts zugeordnet — die gewählten Zahlungen liegen "
                                  "nicht mehr auf einem Parkkonto.")
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_zahler_zuordnungen(request):
    """Die gelernten Absender: wer zahlt für welchen Mietvertrag.

    Diese Zuordnungen entstehen still im Hintergrund — jede manuelle Zuordnung
    einer geparkten Zahlung merkt sich den Absender, und beim nächsten Import
    trifft die Zahlung von allein. Genau deshalb braucht es diese Seite: Eine
    Automatik, die niemand einsehen und korrigieren kann, ist keine Hilfe,
    sondern ein blinder Fleck. Zieht ein Mieter aus und der Nachmieter heisst
    zufällig ähnlich, oder wurde beim ersten Mal danebengegriffen, ordnet das
    Programm sonst dauerhaft falsch zu — und niemand sieht, warum.
    """
    from finance.models import ZahlerZuordnung
    basis = _global_filter(request)

    zuordnungen = list(ZahlerZuordnung.objects
                       .select_related('vertrag__mieter',
                                       'vertrag__einheit__liegenschaft')
                       .order_by('-treffer', 'name_anzeige', 'name_norm'))

    # Auswahl zum Umbiegen: aktive Verträge reichen — auf einen beendeten
    # Vertrag zu zeigen wäre eine neue Fehlerquelle, keine Korrektur.
    vertraege = []
    for v in (Mietvertrag.objects.filter(status='aktiv')
              .select_related('mieter', 'einheit__liegenschaft')
              .order_by('id')):
        lg = v.einheit.liegenschaft if v.einheit_id and v.einheit.liegenschaft_id else None
        teile = [v.mieter.display_name if v.mieter_id else '—']
        if lg:
            teile.append(lg.strasse)
        if v.einheit_id and v.einheit.bezeichnung:
            teile.append(v.einheit.bezeichnung)
        vertraege.append({'id': v.id, 'label': ' · '.join(teile)})
    vertraege.sort(key=lambda x: x['label'].lower())

    return render(request, 'fw/zahler_zuordnungen.html', {
        **basis, 'nav': 'bankabgleich',
        'zuordnungen': zuordnungen, 'vertraege': vertraege,
        'getroffen_n': sum(z.treffer for z in zuordnungen),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_zahler_zuordnung_speichern(request):
    """Gelernten Absender auf einen anderen Vertrag umbiegen oder vergessen.

    Bewusst ohne Buchungswirkung: Bereits verbuchte Zahlungen bleiben, wie sie
    gebucht wurden. Geändert wird nur, was das Programm beim NÄCHSTEN Import
    tut — eine Regel für die Zukunft, keine rückwirkende Umbuchung.
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.auth import log_aktion
    from finance.models import ZahlerZuordnung

    if request.method != 'POST':
        return redirect('fw_zahler_zuordnungen')

    eintrag = (ZahlerZuordnung.objects
               .filter(id=request.POST.get('id') or 0)
               .select_related('vertrag__mieter').first())
    if eintrag is None:
        messages.error(request, "Diese Zuordnung gibt es nicht mehr.")
        return redirect('fw_zahler_zuordnungen')

    name = eintrag.name_anzeige or eintrag.name_norm

    if request.POST.get('aktion') == 'loeschen':
        eintrag.delete()
        log_aktion(request, "Zahler-Zuordnung gelöscht", name, '')
        messages.success(request, f"✅ «{name}» wird nicht mehr automatisch zugeordnet — "
                                  f"künftige Zahlungen landen wieder zur Prüfung "
                                  f"im Bankabgleich.")
        return redirect('fw_zahler_zuordnungen')

    ziel = (Mietvertrag.objects.filter(id=request.POST.get('vertrag_id') or 0)
            .select_related('mieter').first())
    if ziel is None:
        messages.error(request, "Kein Mieter gewählt — die Zuordnung bleibt unverändert.")
        return redirect('fw_zahler_zuordnungen')
    if ziel.id == eintrag.vertrag_id:
        return redirect('fw_zahler_zuordnungen')

    alt = (eintrag.vertrag.mieter.display_name
           if eintrag.vertrag_id and eintrag.vertrag.mieter_id else '—')
    eintrag.vertrag = ziel
    # Die Trefferzahl gehört zur alten Regel und würde die neue fälschlich
    # als bewährt ausweisen.
    eintrag.treffer = 0
    eintrag.zuletzt = None
    eintrag.save(update_fields=['vertrag', 'treffer', 'zuletzt'])
    log_aktion(request, "Zahler-Zuordnung geändert", name,
               f"{alt} → {ziel.mieter.display_name}")
    messages.success(request, f"✅ «{name}» zahlt neu für {ziel.mieter.display_name}. "
                              f"Bereits verbuchte Zahlungen bleiben unverändert.")
    return redirect('fw_zahler_zuordnungen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bankbewegung_zuordnen(request):
    """Ordnet eine offene Bankbewegung zu und bucht sie.

    Ohne diesen Schritt bleibt eine Belastung ewig im Eingang liegen: Der Auszug
    nennt kein Gegenkonto — ob eine Zahlung an einen Lieferanten, eine Gebühr,
    ein Hypothekarzins oder eine Eigentümer-Auszahlung dahintersteckt, weiss nur
    der Buchhalter. Deshalb wird geraten NICHTS, sondern gefragt.

    Drei Wege:
      kreditor  — Belastung tilgt eine Kreditorenrechnung: 2000 an Bank
      konto     — freies Gegenkonto (Gebühr, Zins, Eigentümer): Gegenkonto an Bank
                  bzw. bei einer Gutschrift Bank an Gegenkonto
      ignorieren— gehört nicht in diese Buchhaltung (z.B. Umbuchung eigenes Konto)
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Bankbewegung, KreditorenRechnung, Buchungskonto
    from finance.booking import buche
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')
    ziel = '/neu/bankabgleich/'
    if aktive := request.POST.get('lg'):
        ziel += f'?lg={aktive}'

    bew = get_object_or_404(Bankbewegung, id=request.POST.get('bewegung_id'))
    if bew.status != 'offen':
        messages.info(request, "Diese Bankbewegung ist bereits erledigt.")
        return redirect(ziel)

    art = request.POST.get('art')
    # Das VALUTADATUM ist buchhalterisch massgebend; vorher landete jede Zahlung
    # im Datum des Erfassungstags (Praxis-Audit).
    dat = bew.valuta or bew.datum
    bank_nr = bew.konto.nummer
    betrag = abs(bew.betrag)

    if art == 'ignorieren':
        bew.status = 'ignoriert'
        bew.bemerkung = (request.POST.get('bemerkung') or 'Nicht buchungsrelevant')[:255]
        bew.save(update_fields=['status', 'bemerkung'])
        log_aktion(request, "Bankbewegung ignoriert", str(bew), bew.bemerkung)
        messages.success(request, "Bewegung als nicht buchungsrelevant markiert.")
        return redirect(ziel)

    try:
        with transaction.atomic():
            if art == 'kreditor':
                from finance.models import KreditorenZahlung
                kr = get_object_or_404(KreditorenRechnung,
                                       id=request.POST.get('kreditor_id'))
                if bew.betrag >= 0:
                    messages.error(request, "Eine Gutschrift kann keine Lieferantenrechnung tilgen.")
                    return redirect(ziel)
                offen_kr = kr.offener_betrag
                if offen_kr <= 0:
                    messages.error(request, "Diese Lieferantenrechnung ist bereits bezahlt.")
                    return redirect(ziel)
                # Nie mehr tilgen als offen ist — der Rest bleibt im Eingang.
                betrag = min(betrag, offen_kr)
                # Gleicher Weg wie die manuelle Zahlung (KreditorenZahlung +
                # 2000 an Bank), damit es nur EINEN Zahlungspfad gibt.
                KreditorenZahlung.objects.create(
                    kreditor=kr, betrag=betrag, datum=dat,
                    bemerkung=f"Bankabgleich {bew.text or bew.gegenpartei}"[:255],
                    erstellt_von=request.user)
                buchung = buche('2000', bank_nr, betrag,
                                f"Zahlung {kr.lieferant} - {kr.referenz}"[:255],
                                datum=dat, liegenschaft=kr.liegenschaft, kreditor=kr,
                                user=request.user)
                kr.status = 'bezahlt' if kr.offener_betrag <= 0 else 'teilbezahlt'
                kr.save(update_fields=['status'])
                bew.liegenschaft = kr.liegenschaft
                text = f"Kreditor {kr.lieferant}"
            else:
                gegen_nr = (request.POST.get('gegenkonto') or '').strip().split()[0] if request.POST.get('gegenkonto') else ''
                gegen = Buchungskonto.objects.filter(nummer=gegen_nr).first()
                if not gegen:
                    messages.error(request, "Bitte ein gültiges Gegenkonto angeben.")
                    return redirect(ziel)
                lg_b = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
                bez = (request.POST.get('beleg_text') or bew.text or 'Bankbewegung')[:255]
                if bew.betrag < 0:      # Ausgang: Aufwand/Aktivum an Bank
                    buchung = buche(gegen, bank_nr, betrag, bez, datum=dat,
                                    liegenschaft=lg_b, user=request.user)
                else:                   # Eingang: Bank an Ertrag/Passivum
                    buchung = buche(bank_nr, gegen, betrag, bez, datum=dat,
                                    liegenschaft=lg_b, user=request.user)
                bew.liegenschaft = lg_b
                text = f"{gegen.nummer} {gegen.bezeichnung}"
            bew.status = 'verbucht'
            bew.bemerkung = text[:255]
            # Beleg an der Auszugszeile festhalten — sonst ist im Nachhinein nicht
            # belegbar, WELCHE Buchung diese Bankbewegung erledigt hat (Revision).
            bew.buchung = buchung
            bew.save(update_fields=['status', 'bemerkung', 'liegenschaft', 'buchung'])
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(ziel)
    except Exception as exc:
        messages.error(request, f"❌ Bewegung konnte nicht gebucht werden: {exc}")
        return redirect(ziel)

    log_aktion(request, "Bankbewegung verbucht", str(bew), text)
    messages.success(request, f"✅ CHF {betrag} verbucht ({text}) — Valuta {dat:%d.%m.%Y}.")
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_mwst_verbuchen(request):
    """Bucht die MWST-Abrechnung einer Periode aus (Audit K4/N2).

    Effektiv:  2200 an 1170 (Vorsteuer verrechnen) + 2200 an 2201 (Schuld ESTV)
    Saldosatz: 2200 an 2201 über die Saldosatz-Zahllast; der Überschuss auf 2200
               (Differenz Normalsatz ./. Saldosatz) ist Ertrag → 2200 an 3600.
    Ohne diese Ausbuchung wächst Konto 2200 unbegrenzt weiter.

    Gegenkonto ist das Abrechnungskonto 2201, NICHT die Bank: Am Periodenende
    entsteht nur die Schuld, gezahlt wird erst mit der Abrechnung (Frist 60
    Tage). Die frühere Buchung gegen 1020 liess den Banksaldo ab dem Stichtag
    vom realen Kontoauszug abweichen — der Bankabgleich zeigte eine
    Dauerdifferenz, und die echte Zahlung wurde beim Import ein zweites Mal
    gebucht (Audit). Die Zahlung selbst läuft später als 2201 an 1020."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.booking import buche
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_mwst')
    heute = timezone.localdate()
    # Der globale Filter kommt aus der Query-String — hier wird per POST gesendet.
    # Ohne diese Zeile lief die Verbuchung immer über das GESAMTE Portfolio, während
    # die Anzeige daneben nur eine Liegenschaft zeigte (Audit).
    aktive_lg = None
    if lg_id := (request.POST.get('lg') or request.GET.get('lg')):
        aktive_lg = Liegenschaft.objects.filter(id=lg_id).first()
    try:
        jahr = int(request.POST.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    quartal = request.POST.get('quartal', '')
    ziel = f'/neu/mwst/?jahr={jahr}' + (f'&quartal={quartal}' if quartal else '')
    if aktive_lg:
        ziel += f'&lg={aktive_lg.id}'

    if _mwst_bereits_verbucht(jahr, quartal, aktive_lg):
        messages.info(request, "Diese MWST-Periode wurde bereits verbucht.")
        return redirect(ziel)

    # Beträge NEU aus dem Hauptbuch rechnen statt aus dem POST übernehmen — sonst
    # bestimmt der Client, was der ESTV geschuldet wird (Audit).
    p = _mwst_periode(jahr, quartal, aktive_lg)
    umsatzsteuer, vorsteuer = p['umsatzsteuer'], p['vorsteuer']
    zahllast, methode = p['zahllast'], p['methode']
    if umsatzsteuer <= 0 and vorsteuer <= 0:
        messages.info(request, "Für diese Periode gibt es keine MWST zu verbuchen.")
        return redirect(ziel)

    beleg = _mwst_beleg(jahr, quartal)
    ende = date(jahr, 12, 31) if quartal not in ('1', '2', '3', '4') else \
        date(jahr, int(quartal) * 3, _calendar.monthrange(jahr, int(quartal) * 3)[1])
    try:
        with transaction.atomic():
            if methode == 'saldo':
                if zahllast > 0:
                    buche('2200', '2201', zahllast, f"{beleg} — Zahllast ESTV (Saldosatz)",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                # Rest von 2200 ist der Saldosatz-Vorteil (Ertrag) bzw. — falls der
                # Saldosatz teurer war als die effektiv fakturierte Steuer — ein
                # Aufwand. Beide Richtungen ausbuchen, sonst bleibt 2200 stehen und
                # die Erfolgsmeldung wäre unehrlich.
                vorteil = (umsatzsteuer - zahllast).quantize(Decimal('0.01'))
                if vorteil > 0:
                    buche('2200', '3600', vorteil,
                          f"{beleg} — Saldosteuersatz-Vorteil (Ertrag)",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                elif vorteil < 0:
                    buche('4500', '2200', abs(vorteil),
                          f"{beleg} — Saldosteuersatz-Nachteil (Aufwand)",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                # Bei der Saldosatz-Methode ist der Vorsteuerabzug mit dem Satz
                # abgegolten. Ein Soll-Saldo auf 1170 würde sonst ewig stehen
                # bleiben und die Bilanz aufblähen → als Aufwand ausbuchen.
                if vorsteuer > 0:
                    buche('4500', '1170', vorsteuer,
                          f"{beleg} — Vorsteuer im Saldosatz abgegolten",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
            else:
                # Nur den tatsächlich verrechenbaren Teil umbuchen; negative
                # Beträge (2200 im Soll) darf buche() gar nicht erst sehen.
                verrechenbar = min(vorsteuer, umsatzsteuer)
                if verrechenbar > 0:
                    buche('2200', '1170', verrechenbar,
                          f"{beleg} — Vorsteuer verrechnet",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                if zahllast > 0:
                    buche('2200', '2201', zahllast, f"{beleg} — Zahllast ESTV",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
                elif zahllast < 0:
                    buche('2201', '1170', abs(zahllast), f"{beleg} — Vorsteuerguthaben ESTV",
                          datum=ende, liegenschaft=aktive_lg, user=request.user)
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(ziel)
    except Exception as exc:
        messages.error(request, f"❌ MWST-Abrechnung konnte nicht verbucht werden: {exc}")
        return redirect(ziel)

    log_aktion(request, "MWST-Abrechnung verbucht", beleg, f"Zahllast CHF {zahllast}")
    messages.success(request, f"✅ {beleg} verbucht — Zahllast CHF {zahllast} "
                              f"({'Saldosteuersatz' if methode == 'saldo' else 'effektive Methode'}).")
    return redirect(ziel)


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_zahlung_stornieren(request, pk):
    """Storniert einen Zahlungseingang revisionssicher (Audit W7): Gegenbuchungen
    zu allen Buchungen der Zahlung, Status → storniert, OP-Status der Rechnung
    wird zurückgerollt. Bisher gab es das nur in der Alt-API — eine falsch
    zugeordnete Zahlung war in der neuen Oberfläche nur per Handbuchung zu
    korrigieren (und der OP-Status blieb falsch)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Buchung
    from finance.services import erstelle_storno_buchung
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_bankabgleich')
    try:
        with transaction.atomic():
            # Zeilensperre: zwei parallele Stornos würden sonst doppelte
            # Gegenbuchungen erzeugen.
            z = get_object_or_404(
                Zahlungseingang.objects.select_for_update()
                .select_related('debitoren_rechnung', 'vertrag__mieter'), id=pk)
            if z.status == 'storniert':
                messages.info(request, "Diese Zahlung ist bereits storniert.")
                return redirect(request.POST.get('next') or '/neu/bankabgleich/')

            # Eine Bankgutschrift kann sich auf mehrere Zahlungseingänge verteilt
            # haben: der zugeordnete Teil plus ein Überschuss als Mieterguthaben
            # (bank_referenz «…:ueber») bzw. ein Rest aus der Zuordnung («…:rest»).
            # Ohne diese Geschwister bliebe das Guthaben nach dem Storno stehen —
            # der Mieter behielte ein Guthaben aus einer Zahlung, die es nicht gibt.
            zahlungen = [z]
            if z.bank_referenz:
                zahlungen += list(Zahlungseingang.objects.select_for_update().filter(
                    bank_referenz__startswith=f"{z.bank_referenz}:", status='verbucht')
                    .exclude(id=z.id))
            for zz in zahlungen:
                for b in Buchung.objects.filter(zahlungseingang=zz, ist_storno=False,
                                                storniert_am__isnull=True):
                    erstelle_storno_buchung(b, benutzer=request.user)
                zz.status = 'storniert'
                zz.save(update_fields=['status'])
            rech = z.debitoren_rechnung
            if rech and rech.status not in ('storniert', 'abgeschrieben'):
                rech.status = 'offen' if rech.offener_betrag >= rech.betrag else 'teilbezahlt'
                rech.save(update_fields=['status'])
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(request.POST.get('next') or '/neu/bankabgleich/')
    except Exception as exc:
        messages.error(request, f"❌ Zahlung konnte nicht storniert werden: {exc}")
        return redirect(request.POST.get('next') or '/neu/bankabgleich/')

    log_aktion(request, "Zahlungseingang storniert", f"Zahlung #{z.id}",
               f"CHF {z.betrag} · {z.vertrag.mieter if z.vertrag_id else 'ohne Vertrag'}")
    messages.success(request, f"✅ Zahlung über CHF {z.betrag} storniert — offener Posten wieder offen.")
    return redirect(request.POST.get('next') or '/neu/bankabgleich/')
