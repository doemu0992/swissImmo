# core/views/fw/dashboard.py
#
# Die Einstiegsseiten der Oberflaeche: das Dashboard mit der Inbox und die
# Finanzuebersicht. Sie standen im KOPFBEREICH der urspruenglichen fw.py,
# vor dem ersten Blockkommentar — deshalb kommen sie zuletzt, als 34. und
# letzter Umzug der Etappe 1 (siehe docs/ETAPPE-1-ZERLEGEN.md).
#
# Damit ist _rest.py leer und faellt weg: Es gibt keine "noch nicht
# aufgeteilte" Restdatei mehr.

import logging
from collections import defaultdict
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.shortcuts import render
from django.utils import timezone

from core.auth import rolle_erforderlich, TEAM_ROLLEN
from core.services.mahnstufen import (stufe_fuer_tage as _stufe_fuer_tage,
                                      eigentuemer_von_rechnung as _eigentuemer_von_rechnung)
from finance.models import DebitorenRechnung
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter, _num, _pendenz_ziel, STATUS_PILL

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
    # Phase 4b: Der Arbeitsvorrat steht UEBER den Kennzahlen. Er ist die
    # erste Oberflaeche, auf der die Bausteine aus Phase 4a erscheinen — Fall,
    # Eingang und Lauf hatten bis hierher keine View.
    #
    # Er ist KEINE zweite Liste neben der Inbox: Die einzelnen Pendenzen und
    # die Wartungsfristen sind aus `core/services/inbox.py` hierher gewandert,
    # nicht kopiert (KONZEPT-UI.md G2). Die Inbox fuehrt weiter die
    # Sammelposten.
    from faelle.arbeitsvorrat import arbeitsvorrat
    context.update(arbeitsvorrat(request, aktive_lg=aktive_lg))
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
