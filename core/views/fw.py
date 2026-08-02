# core/views/fw.py
"""
Fairwalter-Rebuild: neue Oberfläche (/neu/…) auf bestehendem Backend.
Referenz: Original-Screenshots in REBUILD.md. Server-gerendert, testbar.

Der 'Globale Filter' (?lg=<id>) filtert alle Kennzahlen auf eine Liegenschaft —
er wird in _global_filter() gelesen und an jede Seite durchgereicht.
"""
import os
import re
from datetime import date
from decimal import Decimal

from django.conf import settings
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


def _parse_adresse(text):
    """Grobe Zerlegung eines freien Adress-Strings in (strasse, plz, ort).
    Erkennt Formate wie «Musterstrasse 1, 8000 Zürich» oder «Musterstrasse 1
    8000 Zürich». Bei Unklarheit wandert der ganze Rest nach `ort`."""
    text = (text or '').strip()
    if not text:
        return '', '', ''
    teile = [t.strip() for t in text.split(',') if t.strip()]
    if len(teile) >= 2:
        strasse = teile[0]
        rest = teile[1]
    else:
        # kein Komma → letzten «PLZ Ort»-Block vom Strassenteil trennen
        m = re.search(r'(.*?)(\b\d{4}\b.*)$', text)
        if m and m.group(1).strip():
            strasse, rest = m.group(1).strip(), m.group(2).strip()
        else:
            return text, '', ''
    m = re.match(r'^\s*(\d{4,6})\s+(.*)$', rest)
    if m:
        return strasse, m.group(1), m.group(2).strip()
    return strasse, '', rest


def _num(wert):
    """Normalisiert eine im Formular eingegebene Zahl zu einem Decimal-tauglichen
    String: Schweizer Tausender-Apostroph (' und ’) raus, Komma → Punkt, CHF/
    Leerzeichen raus.

    Nötig, weil Beträge über den `chf`-Filter mit Apostroph angezeigt werden
    (CHF 12'500.00) und exakt so wieder ins Formular zurückkommen — `Decimal()`
    warf darauf eine InvalidOperation und die Aktion brach ab bzw. fiel still auf
    den Standardwert zurück (Praxis-Audit).
    """
    t = str(wert or '').strip()
    for weg in ("'", "\u2019", "\u00a0", " ", "CHF", "chf"):
        t = t.replace(weg, '')
    return t.replace(',', '.')


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
    'abgeschrieben': ('Abgeschrieben', 'bg-slate-100 text-slate-500'),
}


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_debitoren(request):
    heute = timezone.localdate()
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
    total_betrag = Decimal('0.00')     # Spaltensumme «Betrag» für den Tabellenfuss
    anzahl_offen = 0
    anzahl_ueberfaellig = 0
    for r in qs:
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        einheit = r.einheit or (r.vertrag.einheit if r.vertrag_id else None)
        offen = r.offener_betrag if r.status in ('offen', 'teilbezahlt') else Decimal('0.00')
        faellig = r.faellig_am or r.datum
        mahn = _mahnstufe(faellig, heute, r.status)
        if r.status != 'storniert':
            total_betrag += (r.betrag or Decimal('0.00'))
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

    # Pagination: die Debitorenliste wächst monatlich um eine Position je Vertrag —
    # ohne Seiten wird sie nach einem Jahr unbrauchbar lang. KPI-Summen oben
    # bleiben Gesamtwerte (vor dem Slicing berechnet).
    from django.core.paginator import Paginator
    paginator = Paginator(rows, 50)
    try:
        seite = max(1, int(request.GET.get('seite') or 1))
    except ValueError:
        seite = 1
    page = paginator.get_page(seite)
    rows_gesamt = len(rows)
    rows = list(page.object_list)

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
        # Nur noch nicht stornierte Originale umkehren (Doppel-Storno-Schutz).
        for b in Buchung.objects.filter(debitoren_rechnung=r, ist_storno=False,
                                        storniert_am__isnull=True):
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
    lgs = Liegenschaft.objects.all().order_by('strasse')
    if basis['aktive_lg']:
        lgs = lgs.filter(id=basis['aktive_lg'].id)
    rows, total_kosten, total_m2 = [], Decimal('0.00'), Decimal('0.00')
    for lg in lgs:
        kosten = (Buchung.objects.filter(liegenschaft=lg, datum__gte=von, datum__lte=bis,
                                          soll_konto__typ='aufwand', ist_storno=False,
                                          storniert_am__isnull=True)
                  .aggregate(s=Sum('betrag'))['s'] or Decimal('0.00'))
        m2 = sum((e.flaeche_m2 or Decimal('0')) for e in lg.einheiten.all()) or Decimal('0.00')
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

    ertrag_konten = list(Buchungskonto.objects.filter(typ='ertrag').values_list('id', flat=True))
    aufwand_konten = list(Buchungskonto.objects.filter(typ='aufwand').values_list('id', flat=True))
    mietertrag_konten = list(Buchungskonto.objects.filter(nummer__in=['3000', '3010']).values_list('id', flat=True))
    reparatur_konten = list(Buchungskonto.objects.filter(nummer='4000').values_list('id', flat=True))

    def _wert(bqs):
        def saldo(kids, positiv_haben):
            if not kids:
                return Decimal('0.00')
            s = bqs.filter(soll_konto_id__in=kids).aggregate(x=Sum('betrag'))['x'] or Decimal('0.00')
            h = bqs.filter(haben_konto_id__in=kids).aggregate(x=Sum('betrag'))['x'] or Decimal('0.00')
            return (h - s) if positiv_haben else (s - h)
        if typ == 'mietertrag':
            return saldo(mietertrag_konten, True)
        if typ == 'aufwand':
            return saldo(aufwand_konten, False)
        if typ == 'reparatur':
            return saldo(reparatur_konten, False)
        return saldo(ertrag_konten, True) - saldo(aufwand_konten, False)   # ergebnis

    # Ein storniertes Original zählte hier weiter, seine Gegenbuchung war
    # ausgeblendet — der Storno hob sich in der Auswertung also nie auf.
    base_q = Buchung.objects.filter(datum__year=jahr, ist_storno=False,
                                    storniert_am__isnull=True)
    if aktive_lg:
        base_q = base_q.filter(liegenschaft=aktive_lg)

    # Monatsverlauf
    monate = []
    max_abs = Decimal('0.01')
    total = Decimal('0.00')
    for m in range(1, 13):
        w = _wert(base_q.filter(datum__month=m))
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
        max_lg = Decimal('0.01')
        for lg in Liegenschaft.objects.order_by('strasse'):
            w = _wert(Buchung.objects.filter(datum__year=jahr, ist_storno=False,
                                             storniert_am__isnull=True, liegenschaft=lg))
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
    aktueller_ref_zins = _vw.aktueller_referenzzinssatz if _vw else Decimal('1.75')
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
    messages.success(request, f"✅ Sollmietzins ab {ab.strftime('%d.%m.%Y')} erfasst "
                     f"(Referenz CHF {netto + nk}, zu zahlen CHF {zu_zahlen}).")
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


def _formulare_prozesse(v):
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
        'formular_gruppen': _formulare_prozesse(v),
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
        'docuseal_konfiguriert': docuseal_konfiguriert(),
    })


def _formular_kanton_label(vertrag):
    """Kürzel des Kantons für das amtliche Formular (SO/ZH/BE/…). Leer, wenn
    keine Liegenschaft/kein Kanton bestimmbar."""
    from core.services.kantone import kanton_fuer_liegenschaft
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    return kanton_fuer_liegenschaft(lg) if lg else ''


def _kaution_bilanziert(vertrag):
    """Wie viel Kaution dieses Vertrags steht noch als Verbindlichkeit (2010) in
    der Bilanz?

    Massgebend für jede Freigabe/Rückzahlung ist dieser Betrag — NICHT das
    Vertragsfeld `kautions_betrag`, das nur den vereinbarten Betrag festhält.
    Ohne die Unterscheidung wird eine nie einbezahlte Kaution «zurückbezahlt»
    (Audit, kritisch). Eine bereits erfolgte Auflösung hat 2010 belastet und
    senkt den Wert automatisch — das verhindert zugleich eine zweite Auflösung
    über einen anderen Weg.
    """
    from django.db.models import Sum, Q as _Q
    from finance.models import Buchung

    def _saldo_2010(qs):
        h = qs.filter(haben_konto__nummer='2010').aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        s = qs.filter(soll_konto__nummer='2010').aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
        return (h - s).quantize(Decimal('0.01'))

    offen = Buchung.objects.filter(ist_storno=False, storniert_am__isnull=True)
    # 1) Bevorzugt die vertragsgetaggten Buchungen (`Mietkaution [V<pk>] …`) —
    #    präzise auch bei mehreren Verträgen desselben Mieters.
    getaggt = offen.filter(beleg_text__contains=f"[V{vertrag.pk}]")
    if getaggt.filter(_Q(soll_konto__nummer='2010') | _Q(haben_konto__nummer='2010')).exists():
        return _saldo_2010(getaggt)
    # 2) Fallback für manuell journalisierte Kautionen ohne Vertrags-Tag: nur wenn
    #    eine Einzahlung dokumentiert ist UND das Konto sie überhaupt trägt.
    if not vertrag.kautions_einbezahlt_am:
        return Decimal('0.00')
    lg = vertrag.einheit.liegenschaft if vertrag.einheit_id else None
    gesamt = _saldo_2010(offen.filter(liegenschaft=lg) if lg else offen)
    return max(min(vertrag.kautions_betrag or Decimal('0.00'), gesamt), Decimal('0.00'))


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

        daten = berechne_schlussabrechnung(v, auszug, positionen, kaution_verrechnen=kaution_verrechnen)
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
                or _BIdem.objects.filter(
                    beleg_text__contains=f"Schlussabrechnung [V{v.pk}]", ist_storno=False
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
                            if not _BS.objects.filter(beleg_text__startswith=beleg_k, ist_storno=False).exists():
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
                return Decimal(_num(x)) if str(x).strip() else None
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
        assets = P.getlist('m_ausstattung')
        neuwerte = P.getlist('m_neuwert')
        fotos = list(request.FILES.getlist('m_foto'))
        from portfolio.models import Ausstattung as _Ausstattung
        for i, b in enumerate(beschr):
            b = (b or '').strip()
            if not b:
                continue
            aid = (assets[i] if i < len(assets) else '').strip()
            element = None
            if aid.isdigit():
                element = _Ausstattung.objects.filter(id=int(aid), einheit=v.einheit).first()
            nw = _dec(neuwerte[i] if i < len(neuwerte) else '')
            if nw is None and element is not None:
                nw = element.neuwert
            mangel = AbnahmeMangel(
                protokoll=prot,
                raum=(raeume[i] if i < len(raeume) else '').strip(),
                beschreibung=b,
                verursacher=(verurs[i] if i < len(verurs) else 'abnutzung'),
                kostenschaetzung=_dec(kosten[i] if i < len(kosten) else ''),
                ausstattung=element,
                neuwert=nw,
                foto=(fotos.pop(0) if fotos else None),
            )
            # Mieteranteil nach Lebensdauertabelle berechnen und einfrieren
            mangel.mieteranteil = mangel.berechne_mieteranteil(stichtag=datum)
            mangel.save()
        # Passende Auszugs-Pendenzen automatisch abhaken
        if prot.typ == 'auszug':
            from core.services.automation import erledige_pendenzen_fuer
            kw = ['Wohnungsabnahme', 'Abnahmetermin']
            if prot.zaehler_strom or prot.zaehler_wasser or prot.zaehler_gas:
                kw.append('Zählerstände')
            if prot.schluessel_anzahl is not None:
                kw.append('Schlüssel')
            # Ohne dem Mieter zugeordnete Mängel gibt es nichts zu rügen — die
            # 267a-Frist-Pendenz ist dann gegenstandslos. Mit Mieter-Mängeln
            # bleibt sie offen, bis die Rüge (fw_abnahme_ruege_267a) erzeugt ist.
            if not prot.maengel.filter(verursacher='mieter').exists():
                kw.append('Mängelrüge Art. 267a')
            erledige_pendenzen_fuer(v, kw, user=request.user)
            # Neue Wohnadresse ab Auszugsdatum als datierte Adress-Zeile hinterlegen
            # (Wegzug-Adresse) — für Haupt- und Mitmieter. Wird zum Stichtag zur
            # effektiven Zustelladresse (Nachsendung an die neue Adresse).
            neue_adr = (prot.neue_adresse or '').strip()
            if neue_adr:
                from crm.models import MieterAdresse
                strasse, plz, ort = _parse_adresse(neue_adr)
                for person in (v.mieter, v.mitmieter):
                    if not person:
                        continue
                    MieterAdresse.objects.get_or_create(
                        mieter=person, art='wohn', gueltig_ab=datum,
                        defaults=dict(strasse=strasse, plz=plz, ort=ort,
                                      quelle=f'auszug:{prot.id}',
                                      notiz='Wegzug gemäss Abnahmeprotokoll'))
                    person.sync_effektive_adresse()
        log_aktion(request, "Wohnungsabnahme erfasst", str(v.mieter), f"{prot.get_typ_display()} {datum}", ziel=v)
        if P.get('embed'):
            typ_txt = prot.get_typ_display()
            return render(request, 'fw/_modal_done.html', {'msg': f"{typ_txt} erfasst ({prot.maengel.count()} Mängel)"})
        messages.success(request, f"✅ Abnahmeprotokoll erfasst ({prot.maengel.count()} Mängel).")
        return redirect(f'/neu/abnahme/{prot.id}/')

    embed = request.GET.get('embed') == '1'
    from portfolio.models import Ausstattung
    elemente = list(Ausstattung.objects.filter(einheit=v.einheit))
    return render(request, 'fw/abnahme_neu.html', {
        **basis, 'nav': 'vertraege', 'v': v, 'raeume': ABNAHME_RAEUME,
        'elemente': elemente,
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
        'hat_mieter_maengel': any(m.verursacher == 'mieter' for m in prot.maengel.all()),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_ruege_267a(request, pk):
    """Sofortige Mängelrüge nach Rückgabe (Art. 267a OR) aus dem Auszugs-
    Abnahmeprotokoll: rügt alle dem Mieter zugeordneten Mängel schriftlich —
    muss SOFORT nach der Abnahme versendet werden, sonst verwirken die
    Ersatzansprüche. Legt das PDF ab und hakt die Checklisten-Pendenz ab."""
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from crm.models import Verwaltung
    from core.services.mietprozess_briefe import rueckgabe_maengelruege_pdf
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related(
        'vertrag__mieter', 'vertrag__einheit__liegenschaft'), id=pk)
    v = prot.vertrag
    maengel = [{'raum': m.raum, 'beschreibung': m.beschreibung,
                'betrag': (m.mieteranteil if m.mieteranteil is not None else m.kostenschaetzung)}
               for m in prot.maengel.all() if m.verursacher == 'mieter']
    if not maengel:
        messages.info(request, "Keine dem Mieter zugeordneten Mängel im Protokoll — keine Rüge nötig.")
        return redirect(f'/neu/abnahme/{prot.id}/')
    pdf = rueckgabe_maengelruege_pdf(v, maengel, verwaltung=Verwaltung.objects.first(),
                                     abnahme_datum=prot.datum)
    ablegen(pdf, f"Mängelrüge Art. 267a {prot.datum:%d.%m.%Y}",
            kategorie='vertrag', vertrag=v, dedup=True)
    from core.services.automation import erledige_pendenzen_fuer
    erledige_pendenzen_fuer(v, ['Mängelrüge Art. 267a'], user=request.user)
    log_aktion(request, "Mängelrüge Art. 267a erstellt", str(v.mieter),
               f"{len(maengel)} Mängel", ziel=v)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Maengelruege_267a_{v.mieter.nachname}.pdf"'
    return resp


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_abnahme_loeschen(request, pk):
    """Abnahmeprotokoll löschen (inkl. Mängel-Positionen)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Abnahmeprotokoll
    from core.auth import log_aktion
    prot = get_object_or_404(Abnahmeprotokoll.objects.select_related('vertrag'), id=pk)
    vid = prot.vertrag_id
    if request.method == 'POST':
        log_aktion(request, "Abnahmeprotokoll gelöscht", str(prot.vertrag) if vid else '', '')
        prot.delete()
        messages.success(request, "🗑️ Abnahmeprotokoll gelöscht.")
    return redirect(f'/neu/vertraege/{vid}/' if vid else '/neu/vertraege/')


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
            # Aktives Mietverhältnis → Objekt aus der Vermarktung/Feed nehmen.
            if neu == 'aktiv' and v.einheit_id and v.einheit.zur_ausschreibung:
                v.einheit.zur_ausschreibung = False
                v.einheit.save(update_fields=['zur_ausschreibung'])
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
        # Bereinigung der verwaisten Vertragspaket-Dokumente passiert zentral in
        # Mietvertrag.delete() (greift auch auf dem API-Löschpfad).
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
    heute = timezone.localdate()
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


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_debitoren_aging(request):
    """Debitoren-Altersstruktur (OP-Aging): offene Forderungen nach
    Fälligkeitsalter (nicht fällig / 1–30 / 31–60 / 61–90 / >90 Tage),
    gruppiert je Mieter — die Risikosicht fürs Mahnwesen."""
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    qs = (DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__mieter', 'vertrag__einheit__liegenschaft', 'liegenschaft'))
    if aktive_lg:
        qs = qs.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg))

    BUCKETS = ['nicht_faellig', 'd30', 'd60', 'd90', 'd90plus']

    def bucket(tage):
        if tage <= 0:
            return 'nicht_faellig'
        if tage <= 30:
            return 'd30'
        if tage <= 60:
            return 'd60'
        if tage <= 90:
            return 'd90'
        return 'd90plus'

    gruppen = {}
    total = {b: Decimal('0.00') for b in BUCKETS}
    total['summe'] = Decimal('0.00')
    for r in qs:
        offen = r.offener_betrag
        if offen <= 0:
            continue
        faellig = r.faellig_am or r.datum
        tage = (heute - faellig).days if faellig else 0
        b = bucket(tage)
        if r.vertrag_id and r.vertrag.mieter_id:
            key = ('m', r.vertrag.mieter_id)
            name = r.vertrag.mieter.display_name
            lg = r.vertrag.einheit.liegenschaft if r.vertrag.einheit_id else None
            objekt = (f"{lg.strasse}" if lg else '')
        else:
            key = ('t', (r.titel or 'Diverse'))
            name = r.titel or 'Diverse'
            objekt = r.liegenschaft.strasse if r.liegenschaft_id else ''
        g = gruppen.setdefault(key, {'name': name, 'objekt': objekt,
                                     **{b: Decimal('0.00') for b in BUCKETS},
                                     'summe': Decimal('0.00'), 'aeltester': 0})
        g[b] += offen
        g['summe'] += offen
        g['aeltester'] = max(g['aeltester'], tage)
        total[b] += offen
        total['summe'] += offen

    rows = sorted(gruppen.values(), key=lambda g: (-g['aeltester'], -float(g['summe'])))
    ueberfaellig_summe = total['d30'] + total['d60'] + total['d90'] + total['d90plus']

    return render(request, 'fw/debitoren_aging.html', {
        **basis, 'nav': 'mahnwesen', 'rows': rows, 'total': total,
        'ueberfaellig_summe': ueberfaellig_summe, 'anzahl': len(rows), 'heute': heute,
    })


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
    from django.db.models import Q as _Q, Sum
    from finance.models import Buchungskonto, KreditorenRechnung
    heute = timezone.localdate()
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

    # Kürzliche Abgleiche (verbuchte Zahlungen) als Kontext.
    # Erst filtern, DANN slicen — ein bereits geslicetes QuerySet lässt sich nicht
    # mehr filtern (TypeError → HTTP 500, sobald ein Liegenschaftsfilter aktiv ist).
    letzte_qs = (Zahlungseingang.objects.filter(status='verbucht')
                 .select_related('vertrag__mieter')
                 .prefetch_related('bankbewegungen'))
    if aktive_lg:
        letzte_qs = letzte_qs.filter(vertrag__einheit__liegenschaft=aktive_lg)
    letzte = list(letzte_qs.order_by('-erstellt_am')[:8])
    # Wer wurde da abgeglichen? Die Zeile zeigte «Mieter · Bemerkung» in EINER
    # gekürzten Spalte — auf dem Handy blieb davon «B..» übrig. Titel (wer) und
    # Herkunft (woher der Beleg kam) werden deshalb getrennt bereitgestellt;
    # ohne Vertrag tritt der erkannte Absender an die Stelle des Mieternamens,
    # sonst begann die Zeile mit einem führenden « · ».
    from core.services import zahler as _zahler
    for z in letzte:
        bew = next(iter(z.bankbewegungen.all()), None)
        name, rest, _geraten = _zahler.aus_bewegung(
            (bew.gegenpartei if bew else ''),
            (bew.text if bew else '') or (z.bemerkung or ''))
        if z.vertrag_id and z.vertrag.mieter_id:
            z.titel = z.vertrag.mieter.display_name
            z.zusatz = ' · '.join(t for t in [name, rest] if t)
        else:
            z.titel = name or (rest or 'Ohne Vertrag')
            z.zusatz = rest if name else ''

    # Geparkte Zahlungen (Durchlaufkonto 1190 / Mieterguthaben 2030) mit
    # Zuordnungs-Aktion — Audit-Befund: ohne diese Liste ist jede ungeklärte
    # Gutschrift eine Sackgasse.
    # Der Liegenschaftsfilter greift nur auf Positionen, die überhaupt einer
    # Liegenschaft zugeordnet sind; wirklich ungeklärtes Geld (ohne Vertrag und
    # ohne Liegenschaft) bleibt immer sichtbar, sonst wäre es erneut unauffindbar.
    geparkt_qs = (Zahlungseingang.objects
                  .filter(status='verbucht', konto__nummer__in=['1190', '2030'])
                  .select_related('vertrag__mieter', 'konto'))
    if aktive_lg:
        geparkt_qs = geparkt_qs.filter(
            _Q(liegenschaft=aktive_lg)
            | _Q(vertrag__einheit__liegenschaft=aktive_lg)
            | _Q(liegenschaft__isnull=True, vertrag__isnull=True))
    geparkt = list(geparkt_qs.order_by('-datum_eingang')
                   .prefetch_related('bankbewegungen'))
    # Wer hat bezahlt? Stand bisher nirgends — die Zeile zeigte nur den
    # abgeschnittenen Importtext («Bank-CSV UNG…»). Der Auftraggeber liegt in
    # der zugehörigen Auszugszeile (Bankbewegung.gegenpartei); Mitteilung und
    # Referenz gleich mit, das sind die Anhaltspunkte für die Zuordnung.
    from core.services import zahler as _zahler
    for z in geparkt:
        bew = next(iter(z.bankbewegungen.all()), None)
        roh_text = (bew.text if bew else '') or ''
        if not roh_text:
            # Altbestand (vor der Auszugszeile) trägt den Text nur in der Bemerkung.
            t = (z.bemerkung or '').split('UNGEKLÄRT:', 1)
            roh_text = (t[1] if len(t) > 1 else t[0]).strip()
        z.zahler, z.mitteilung, z.zahler_geraten = _zahler.aus_bewegung(
            (bew.gegenpartei if bew else ''), roh_text)
        if not z.zahler and z.vertrag_id and z.vertrag.mieter_id:
            z.zahler, z.zahler_geraten = z.vertrag.mieter.display_name, False
        z.ref = ((bew.referenz if bew else '') or '').strip()
    # 1190 (Aktiv, ungeklärt) und 2030 (Passiv, Mieterguthaben) sind fachlich
    # verschieden und werden nicht zu einer Summe vermischt.
    geparkt_unklar = sum((z.betrag for z in geparkt if z.konto and z.konto.nummer == '1190'),
                         Decimal('0.00'))
    geparkt_guthaben = sum((z.betrag for z in geparkt if z.konto and z.konto.nummer == '2030'),
                           Decimal('0.00'))

    # --- BANK-EINGANG: offene Auszugszeilen ---
    # Das war der Kern des Befunds: Der Screen hiess «Bankabgleich», zeigte aber
    # nie eine Bankbewegung — nur offene Debitoren zum Quittieren. Abstimmen
    # konnte man damit nichts (Praxis-Audit).
    from finance.models import Bankbewegung, Kontoauszug
    bew_qs = (Bankbewegung.objects.filter(status='offen')
              .select_related('konto', 'liegenschaft').order_by('-datum', '-id'))
    if aktive_lg:
        bew_qs = bew_qs.filter(_Q(liegenschaft=aktive_lg) | _Q(liegenschaft__isnull=True))
    bewegungen = list(bew_qs[:100])
    bew_offen_n = bew_qs.count()
    # Summen über ALLE offenen Bewegungen, nicht nur die ersten 100 — sonst
    # unterschlägt der Kopf Geld, das weiter unten in der Liste liegt.
    bew_eingang = (bew_qs.filter(betrag__gt=0).aggregate(t=Sum('betrag'))['t']
                   or Decimal('0.00'))
    bew_ausgang = (bew_qs.filter(betrag__lt=0).aggregate(t=Sum('betrag'))['t']
                   or Decimal('0.00'))

    # Letzter Auszug je Bankkonto + Saldoabgleich
    letzter_auszug = Kontoauszug.objects.select_related('konto').order_by('-bis', '-id').first()
    saldo_abgleich = None
    if letzter_auszug and letzter_auszug.schlusssaldo is not None:
        from finance.models import Buchung as _BB
        # Ohne `storniert_am__isnull=True` meldete der Abstimmungsnachweis eine
        # Differenz zum Auszug, die es nicht gibt (storniertes Original zählte
        # weiter, Gegenbuchung war ausgeblendet).
        _bq = _BB.objects.filter(ist_storno=False, storniert_am__isnull=True)
        if letzter_auszug.bis:
            _bq = _bq.filter(datum__lte=letzter_auszug.bis)
        _s = _bq.filter(soll_konto=letzter_auszug.konto).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        _h = _bq.filter(haben_konto=letzter_auszug.konto).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        _buch = (_s - _h).quantize(Decimal('0.01'))
        saldo_abgleich = {
            'auszug': letzter_auszug, 'buchhaltung': _buch,
            'differenz': (letzter_auszug.schlusssaldo - _buch).quantize(Decimal('0.01')),
        }

    # Mieter-Auswahl für die Sammelzuordnung: je Vertrag EIN Eintrag, nur wo es
    # überhaupt etwas zu tilgen gibt. `rows` enthält je offene Rechnung eine Zeile.
    sammel_vertraege = []
    _gesehen = set()
    for _r in rows:
        _v = getattr(_r.get('r'), 'vertrag', None) if isinstance(_r, dict) else None
        if _v is None or _v.id in _gesehen:
            continue
        _gesehen.add(_v.id)
        _offene = sum(1 for x in rows
                      if isinstance(x, dict) and getattr(x.get('r'), 'vertrag_id', None) == _v.id)
        sammel_vertraege.append({
            'id': _v.id,
            'label': f"{_r.get('mieter')} · {_r.get('objekt')} ({_offene} offen)",
        })
    sammel_vertraege.sort(key=lambda x: x['label'].lower())

    bankkonten = Buchungskonto.objects.filter(nummer__startswith='10').order_by('nummer')

    from django.contrib import messages
    return render(request, 'fw/bankabgleich.html', {
        **basis, 'nav': 'bankabgleich', 'rows': rows,
        'bewegungen': bewegungen, 'bew_offen_n': bew_offen_n,
        'bew_eingang': bew_eingang, 'bew_ausgang': bew_ausgang,
        'saldo_abgleich': saldo_abgleich, 'bankkonten': bankkonten,
        'aufwandkonten': Buchungskonto.objects.all().order_by('nummer'),
        # 'neu' gehört dazu: die Belastung hat die Bank BEREITS verlassen. Wer nur
        # freigegebene Rechnungen anbietet, lässt eine reale Zahlung unzuordenbar.
        'offene_kreditoren': (KreditorenRechnung.objects
                              .filter(status__in=['neu', 'freigegeben', 'in_zahlung',
                                                  'teilbezahlt'])
                              .select_related('liegenschaft')
                              .order_by('faellig_am', 'id')[:200]),
        'total_offen': total_offen, 'anzahl': len(rows),
        'letzte': letzte,
        'geparkt': geparkt,
        # Für die Sammelzuordnung: je Mieter EIN Eintrag mit der Zahl seiner
        # offenen Forderungen — die Auswahl trifft den Mieter, nicht die
        # einzelne Rechnung; getilgt wird dann automatisch die älteste zuerst.
        'sammel_vertraege': sammel_vertraege,
        'geparkt_unklar': geparkt_unklar, 'geparkt_guthaben': geparkt_guthaben,
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
    # Status-Guard: auf stornierte/bezahlte Rechnungen darf keine Zahlung gebucht
    # werden — sonst springt eine STORNIERTE Rechnung auf «bezahlt» und das
    # Mieterkonto zeigt ein Haben ohne Soll (real im Audit passiert).
    if rechnung.status not in ('offen', 'teilbezahlt'):
        messages.error(request, f"«{rechnung.titel}» ist {rechnung.get_status_display()} — "
                                "darauf kann keine Zahlung verbucht werden.")
        return redirect('fw_bankabgleich')

    offen = rechnung.offener_betrag
    raw = (request.POST.get('betrag') or '').strip()
    if raw:
        try:
            betrag = Decimal(_num(raw))
        except Exception:
            messages.error(request, f"Ungültiger Betrag «{raw}».")
            return redirect('fw_bankabgleich')
    else:
        betrag = offen
    # Explizite 0/Negativ-Eingabe ist ein Tippfehler — abbrechen statt still
    # auf 0.01 zu klemmen (verwirrende Mini-Teilzahlung).
    if betrag <= 0:
        messages.error(request, "Betrag muss grösser als 0 sein.")
        return redirect('fw_bankabgleich')
    betrag = min(betrag, offen)

    heute = timezone.localdate()
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


def _camt_tx_details(el, richtung='CRDT'):
    """Liest Referenz / Mitteilung / Bank-Tx-Ref / Gegenpartei aus einem
    camt-Teilbaum (<Ntry> oder einzelne <TxDtls>).

    Die Gegenpartei ist bei einer Gutschrift der Auftraggeber (<Dbtr>), bei einer
    Belastung der Zahlungsempfaenger (<Cdtr>) — sonst bleibt der Lieferantenname
    im Bank-Eingang leer."""
    referenz = info = acct_ref = dbtr_name = ''
    gegen_tag = 'Dbtr' if richtung == 'CRDT' else 'Cdtr'
    in_dbtr = False
    for sub in el.iter():
        ln = _camt_localname(sub.tag)
        if ln == 'CdtrRefInf':
            ref_el = _camt_find(sub, 'Ref')
            if ref_el is not None and ref_el.text:
                referenz = ref_el.text.strip().replace(' ', '')
        elif ln == 'Ustrd' and not info and sub.text:
            info = sub.text.strip()
        elif ln in ('AcctSvcrRef', 'TxId', 'EndToEndId') and not acct_ref and sub.text:
            # 'NOTPROVIDED' ist bei Swiss-QR-Gutschriften der Standardwert und
            # KEINE eindeutige Transaktionsreferenz.
            _cand = sub.text.strip()
            if _cand.upper() != 'NOTPROVIDED':
                acct_ref = _cand
        elif ln == gegen_tag:
            in_dbtr = True
        elif ln == 'Nm' and in_dbtr and not dbtr_name and sub.text:
            dbtr_name = sub.text.strip(); in_dbtr = False
    return {'referenz': referenz, 'info': info,
            'acct_ref': acct_ref, 'dbtr_name': dbtr_name}


def _camt_kopf(xml_bytes):
    """Liest Kopfdaten des Auszugs: IBAN, Periode und Schlusssaldo.

    Ohne den Schlusssaldo gibt es keinen Abstimmungsnachweis — man kann Zahlungen
    zuordnen, aber nie belegen, dass das Buchhaltungskonto mit dem realen
    Bankkonto übereinstimmt (Praxis-Audit).
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return {}
    kopf = {'iban': '', 'von': None, 'bis': None,
            'eroeffnung': None, 'schluss': None}
    # IBAN des Auszugskontos
    for el in root.iter():
        if _camt_localname(el.tag) == 'IBAN' and el.text:
            kopf['iban'] = el.text.strip().replace(' ', '')
            break
    # Periode <FrToDt><FrDtTm>/<ToDtTm>
    for el in root.iter():
        ln = _camt_localname(el.tag)
        if ln in ('FrDtTm', 'ToDtTm') and el.text:
            try:
                d = date.fromisoformat(el.text.strip()[:10])
            except ValueError:
                continue
            kopf['von' if ln == 'FrDtTm' else 'bis'] = d
    # Salden: <Bal> mit <Cd> OPBD (Eröffnung) bzw. CLBD (Schluss)
    for bal in root.iter():
        if _camt_localname(bal.tag) != 'Bal':
            continue
        code = ''
        for sub in bal.iter():
            if _camt_localname(sub.tag) == 'Cd' and sub.text:
                code = sub.text.strip().upper()
                break
        amt = _camt_find(bal, 'Amt')
        if amt is None or not (amt.text or '').strip():
            continue
        try:
            wert = Decimal(amt.text.strip())
        except Exception:
            continue
        # Ein Habensaldo auf dem Bankkonto (CRDT) ist Guthaben → positiv.
        vz = _camt_find(bal, 'CdtDbtInd')
        if vz is not None and (vz.text or '').strip() == 'DBIT':
            wert = -wert
        if code in ('OPBD', 'PRCD'):
            kopf['eroeffnung'] = wert
        elif code in ('CLBD', 'CLAV'):
            kopf['schluss'] = wert
    return kopf


def _camt_parse(xml_bytes, nur_gutschriften=True):
    """Parst einen camt.053-Kontoauszug (ISO 20022) namespace-agnostisch.

    `nur_gutschriften=False` liefert AUCH Belastungen (negatives Vorzeichen).
    Ohne Belastungen — Lieferantenzahlungen, Gebühren, Zinsen, Daueraufträge —
    ist das Bankkonto strukturell nicht abstimmbar (Praxis-Audit).
    """
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_bytes)
    eintraege = []
    # Alle <Ntry>-Elemente unabhängig von der Verschachtelungstiefe
    for ntry in root.iter():
        if _camt_localname(ntry.tag) != 'Ntry':
            continue
        cdtdbt = _camt_find(ntry, 'CdtDbtInd')
        richtung = (cdtdbt.text or '').strip() if cdtdbt is not None else ''
        if richtung not in ('CRDT', 'DBIT'):
            continue
        if nur_gutschriften and richtung != 'CRDT':
            continue
        vorzeichen = Decimal('1') if richtung == 'CRDT' else Decimal('-1')
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
        # Valutadatum separat — es ist das buchhalterisch massgebende Datum und
        # wich bisher stillschweigend dem Erfassungstag (Praxis-Audit).
        valuta = None
        v_el = _camt_find(ntry, 'ValDt', 'Dt')
        if v_el is not None and v_el.text:
            try:
                valuta = date.fromisoformat(v_el.text.strip()[:10])
            except Exception:
                valuta = None
        # Sammelbuchung: enthält der Eintrag mehrere <TxDtls>, ist jede davon eine
        # eigene Zahlung mit eigener QRR. Ohne diese Aufteilung würde der GESAMT-
        # betrag der zuletzt gefundenen Referenz zugeordnet und alle übrigen Mieter
        # blieben unbezahlt (Audit, kritisch) — Schweizer Banken fassen QR-Eingänge
        # eines Tages regelmässig so zusammen.
        txdtls = [t for t in ntry.iter() if _camt_localname(t.tag) == 'TxDtls']
        if len(txdtls) > 1:
            summe_tx = Decimal('0.00')
            teil_eintraege = []
            for tx in txdtls:
                tx_amt = _camt_find(tx, 'Amt')
                try:
                    tx_betrag = Decimal((tx_amt.text or '0').strip()) if tx_amt is not None else None
                except Exception:
                    tx_betrag = None
                if tx_betrag is None or tx_betrag <= 0:
                    teil_eintraege = []      # unvollständig → als Ganzes behandeln
                    break
                teil_eintraege.append((tx, tx_betrag))
                summe_tx += tx_betrag
            # Nur aufteilen, wenn die Einzelbeträge den Eintrag exakt ergeben —
            # sonst ginge Geld verloren oder würde doppelt verbucht.
            if teil_eintraege and summe_tx == betrag:
                for tx, tx_betrag in teil_eintraege:
                    eintraege.append({
                        'betrag': tx_betrag * vorzeichen, 'datum': datum, 'valuta': valuta,
                        **_camt_tx_details(tx, richtung),
                    })
                continue

        # Referenz + Info + Bank-Tx-Ref (Duplikatschutz) + Auftraggebername (Fuzzy)
        referenz = ''
        info = ''
        acct_ref = ''
        dbtr_name = ''
        # Bei einer BELASTUNG ist die Gegenpartei der Zahlungsempfänger (<Cdtr>),
        # nicht der Auftraggeber — sonst bleibt der Lieferantenname im Bank-Eingang
        # leer und die Zeile ist für den Buchhalter nicht zuordenbar (Praxis-Audit).
        gegen_tag = 'Dbtr' if richtung == 'CRDT' else 'Cdtr'
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
                # 'NOTPROVIDED' ist bei Swiss-QR-Gutschriften der Standard-EndToEndId
                # und KEINE eindeutige Transaktionsreferenz — sonst würden mehrere
                # verschiedene Zahlungen fälschlich als Duplikat verworfen (Datenverlust).
                _cand = sub.text.strip()
                if _cand.upper() != 'NOTPROVIDED':
                    acct_ref = _cand
            elif ln == gegen_tag:
                in_dbtr = True
            elif ln == 'Nm' and in_dbtr and not dbtr_name and sub.text:
                dbtr_name = sub.text.strip(); in_dbtr = False
        eintraege.append({'betrag': betrag * vorzeichen, 'referenz': referenz,
                          'datum': datum, 'valuta': valuta,
                          'info': info, 'acct_ref': acct_ref, 'dbtr_name': dbtr_name})
    return eintraege


def _bank_csv_parse(raw):
    """Parst einen Bank-Kontoauszug als CSV (PostFinance/Raiffeisen/ZKB/UBS-Exporte).

    Header-basiert und tolerant: Trennzeichen (; , Tab) wird erkannt, Spalten
    werden über Schlüsselwörter gefunden (Datum, Betrag/Gutschrift, Referenz,
    Text/Mitteilung, Auftraggeber). Nur Gutschriften (positive Beträge bzw.
    Gutschrift-Spalte) werden übernommen. Rückgabe: gleiche Struktur wie
    _camt_parse → derselbe Zuordnungs-/Verbuchungspfad."""
    import csv as _csv
    import io as _io
    import re as _re

    text = None
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, AttributeError):
            continue
    if text is None:
        raise ValueError("Datei-Codierung nicht erkannt")

    # Trennzeichen aus den ersten nicht-leeren Zeilen bestimmen
    probe = [z for z in text.splitlines() if z.strip()][:10]
    if not probe:
        return []
    zaehl = {d: sum(z.count(d) for z in probe) for d in (';', ',', '\t')}
    delim = max(zaehl, key=zaehl.get)
    zeilen = list(_csv.reader(_io.StringIO(text), delimiter=delim))

    KEY = {
        'datum': ('datum', 'date', 'buchungsdatum', 'valuta', 'booking'),
        'betrag': ('betrag', 'amount', 'umsatz'),
        'gut': ('gutschrift', 'credit', 'haben', 'eingang'),
        'last': ('lastschrift', 'belastung', 'debit', 'soll', 'ausgang'),
        'ref': ('referenz', 'reference', 'qrr', 'esr', 'referenznummer'),
        'text': ('mitteilung', 'buchungstext', 'beschreibung', 'verwendungszweck',
                 'text', 'details', 'avisierung', 'zahlungszweck'),
        # Ohne Treffer hier bleibt der Auftraggeber leer und die Zeile im
        # Bankabgleich sagt nur «von der Bank nicht geliefert» — darum breit fassen.
        'name': ('auftraggeber', 'absender', 'zahlungspflichtiger', 'einzahler',
                 'name', 'gegenpartei', 'debitor', 'begünstigter', 'beguenstigter',
                 'partner', 'kontoinhaber', 'zahler', 'counterparty', 'payer'),
    }

    def _spalte(kopf, schluessel):
        for i, z in enumerate(kopf):
            zl = (z or '').strip().lower()
            if any(k in zl for k in KEY[schluessel]):
                return i
        return None

    # Header-Zeile suchen (erste Zeile mit Datum- UND Betrag/Gutschrift-Spalte)
    kopf_idx = None
    sp = {}
    for i, z in enumerate(zeilen[:15]):
        if _spalte(z, 'datum') is not None and (
                _spalte(z, 'betrag') is not None or _spalte(z, 'gut') is not None):
            kopf_idx = i
            sp = {k: _spalte(z, k) for k in KEY}
            break
    if kopf_idx is None:
        raise ValueError("Keine Kopfzeile mit Datum- und Betrag-/Gutschrift-Spalte gefunden. "
                         "Erwartet werden Spalten wie «Datum», «Betrag» oder «Gutschrift», "
                         "optional «Referenz», «Mitteilung», «Auftraggeber».")

    def _dec(s):
        s = (s or '').strip().replace("'", '').replace(' ', '').replace(' ', '')
        s = s.replace('CHF', '').replace('chf', '')
        if not s:
            return None
        if ',' in s and '.' not in s:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
        try:
            return Decimal(s)
        except Exception:
            return None

    def _datum(s):
        from datetime import datetime as _dt
        s = (s or '').strip()[:10]
        for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%d.%m.%y'):
            try:
                return _dt.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    eintraege = []
    for z in zeilen[kopf_idx + 1:]:
        if not any((c or '').strip() for c in z):
            continue

        def wert(k):
            i = sp.get(k)
            return z[i] if i is not None and i < len(z) else ''

        # Gutschrift bestimmen: eigene Spalte hat Vorrang, sonst positiver Betrag
        betrag = _dec(wert('gut')) if sp.get('gut') is not None else None
        if betrag is None:
            b = _dec(wert('betrag'))
            if b is None or b <= 0:
                continue   # Belastung/Leerzeile → kein Zahlungseingang
            if sp.get('last') is not None and _dec(wert('last')):
                continue   # Zeile ist als Belastung markiert
            betrag = b
        if betrag is None or betrag <= 0:
            continue

        info = (wert('text') or '').strip()
        referenz = (wert('ref') or '').strip().replace(' ', '')
        if not referenz:
            # QRR (27-stellig) auch aus dem Buchungstext fischen
            m27 = _re.search(r'\b(\d[\d ]{25,40}\d)\b', info)
            if m27:
                kandidat = m27.group(1).replace(' ', '')
                if len(kandidat) == 27:
                    referenz = kandidat
        eintraege.append({
            'betrag': betrag, 'referenz': referenz, 'datum': _datum(wert('datum')),
            'info': info, 'acct_ref': '', 'dbtr_name': (wert('name') or '').strip(),
        })
    return eintraege


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_camt_import(request):
    """Importiert einen Bank-Kontoauszug — camt.053 (ISO 20022) ODER CSV-Export
    der Bank. Gutschriften werden per QRR-Referenz den offenen Debitoren-
    rechnungen zugeordnet und als Zahlungseingang (Bank an Debitoren) verbucht;
    Unzuordenbares wird auf dem Durchlaufkonto 1190 geparkt."""
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

    roh = datei.read()
    # Format erkennen: XML (camt.053) beginnt mit '<' — alles andere als Bank-CSV parsen.
    kopf_bytes = roh.lstrip(b'\xef\xbb\xbf \t\r\n')
    ist_xml = kopf_bytes.startswith(b'<')
    try:
        if ist_xml:
            # nur_gutschriften=False: Belastungen (Lieferantenzahlungen, Gebühren,
            # Zinsen, Daueraufträge) gehören dazu, sonst ist die Bank nicht
            # abstimmbar (Praxis-Audit).
            eintraege = _camt_parse(roh, nur_gutschriften=False)
            auszug_kopf = _camt_kopf(roh)
        else:
            eintraege = _bank_csv_parse(roh)
            auszug_kopf = {}
    except Exception as e:
        messages.error(request, f"Datei konnte nicht gelesen werden "
                                f"({'kein gültiges camt.053' if ist_xml else 'CSV-Format nicht erkannt'}): {e}")
        return redirect('fw_bankabgleich')

    quelle = 'camt.053' if ist_xml else 'Bank-CSV'
    if not eintraege:
        messages.warning(request, "Keine Bewegungen im Kontoauszug gefunden.")
        return redirect('fw_bankabgleich')

    # Zielkonto der Bank: wählbar, damit mehrere Bankkonten buchbar sind.
    # Vorher war «1020» im ganzen Import hart verdrahtet (Praxis-Audit).
    bank_nr = (request.POST.get('bank_konto') or '1020').strip()
    konto_bank_obj = Buchungskonto.objects.filter(nummer=bank_nr).first()
    if konto_bank_obj is None:
        bank_nr, konto_bank_obj = '1020', _park_konto('1020')

    # Kontoauszug mit Schlusssaldo festhalten — die Grundlage des Abstimmungsnachweises.
    from finance.models import Kontoauszug, Bankbewegung
    auszug = Kontoauszug.objects.create(
        konto=konto_bank_obj, iban=(auszug_kopf.get('iban') or '')[:34],
        von=auszug_kopf.get('von'), bis=auszug_kopf.get('bis'),
        eroeffnungssaldo=auszug_kopf.get('eroeffnung'),
        schlusssaldo=auszug_kopf.get('schluss'),
        dateiname=datei.name[:255], quelle=quelle, importiert_von=request.user)

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
    gelernt_treffer = 0     # über einen früher von Hand zugeordneten Absender
    geklaert = 0            # auf Durchlaufkonto 1190 geparkt (Mieter unbekannt)
    guthaben = 0            # Überzahlung auf 2030 (Mieter bekannt)
    duplikate = 0
    gesperrt = 0            # von der Periodensperre abgewiesen
    belastungen = 0         # Ausgänge — landen im Bank-Eingang zur Zuordnung
    bewegungen_neu = []     # persistierte Auszugszeilen
    komposit_lauf = {}      # Laufnummern für referenzlose Zahlungen
    heute = timezone.localdate()

    # Das Bankkonto steckt in bank_nr/konto_bank_obj — kein hart verdrahtetes 1020 mehr.
    konto_clearing, _ = Buchungskonto.objects.get_or_create(
        nummer="1190", defaults={'bezeichnung': 'Durchlaufkonto (ungeklärte Zahlungen)', 'typ': 'bilanz'})
    # W6: Überzahlung eines BEKANNTEN Mieters ist kein ungeklärter Posten, sondern
    # eine echte Verbindlichkeit → 2030 «Guthaben Mieter» statt Durchlaufkonto 1190.
    konto_guthaben = _park_konto("2030")

    # Fuzzy-Index: offener Betrag → Rechnungen (für referenzlose Gutschriften)
    def _norm(s):
        return ''.join(ch for ch in (s or '').lower() if ch.isalnum())

    def _verbuche(rechnung, betrag, e, via):
        vertrag = rechnung.vertrag
        with transaction.atomic():
            zahlung = Zahlungseingang.objects.create(
                vertrag=vertrag, betrag=betrag, datum_eingang=e['datum'] or heute,
                buchungs_monat=(rechnung.faellig_am or rechnung.datum or heute).replace(day=1),
                bemerkung=f"{quelle}-Import ({via}) {rechnung.titel}",
                bank_referenz=e.get('acct_ref', ''),
                liegenschaft=vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None,
                debitoren_rechnung=rechnung, erstellt_von=request.user, status='verbucht',
            )
            rechnung.status = 'bezahlt' if rechnung.offener_betrag <= 0 else 'teilbezahlt'
            rechnung.save()
            from finance.booking import buche
            buche(bank_nr, "1100", betrag, f"{quelle} {vertrag.mieter} - {rechnung.titel}",
                  datum=e['datum'] or heute,
                  liegenschaft=vertrag.einheit.liegenschaft if vertrag and vertrag.einheit_id else None,
                  zahlung=zahlung, user=request.user)
        # Auszugszeile als erledigt markieren und mit der Zahlung verknüpfen —
        # so ist im Bank-Eingang sichtbar, was noch offen ist.
        _bew = Bankbewegung.objects.filter(bank_referenz=e.get('acct_ref', ''),
                                           status='offen').first()
        if _bew is not None:
            _bew.status = 'verbucht'
            _bew.zahlung = zahlung
            _bew.liegenschaft = zahlung.liegenschaft
            _bew.save(update_fields=['status', 'zahlung', 'liegenschaft'])
        if rechnung.status == 'bezahlt':
            for k in [k for k, v in ref_index.items() if v is rechnung]:
                ref_index.pop(k, None)

    def _eintrag_verarbeiten(e):
        """Verarbeitet EINEN Kontoauszugs-Eintrag. Läuft in der Schleife unten in
        einem try/except für die Periodensperre — sonst reisst eine gesperrte
        Periode den ganzen Import mit HTTP 500 ab: die bis dahin verbuchten Zeilen
        blieben gespeichert, der Rest ginge kommentarlos verloren (Audit)."""
        nonlocal verbucht, geklaert, guthaben, duplikate, fuzzy, zugeordnet_summe, belastungen
        nonlocal gelernt_treffer

        # 0) Duplikatschutz über Bank-Transaktionsreferenz. Fehlt eine eindeutige
        #    Referenz (kein AcctSvcrRef/TxId, EndToEndId=NOTPROVIDED), wird ein
        #    zusammengesetzter Schlüssel aus Datum|Betrag|Auftraggeber|QRR gebildet —
        #    so wird der erneute Import derselben Datei nicht doppelt verbucht, ohne
        #    verschiedene ref-lose Zahlungen fälschlich zu verschmelzen.
        aref = e.get('acct_ref', '')
        if not aref:
            _dat = (e.get('datum') or heute)
            aref = f"camt:{_dat:%Y-%m-%d}|{e.get('betrag','')}|{_norm(e.get('dbtr_name',''))}|{e.get('referenz','')}"
            # Laufnummer je Schlüssel: zwei ECHTE Zahlungen am selben Tag über
            # denselben Betrag (z.B. zwei Mieter mit gleicher Miete, beide ohne
            # Auftraggebername) ergaben sonst denselben Schlüssel — die zweite
            # wurde als «Duplikat» verworfen und das Geld verschwand (Audit).
            # Beim erneuten Import derselben Datei entstehen dieselben Nummern,
            # die Idempotenz bleibt also erhalten.
            # Auf Feldlänge kürzen (bank_referenz = 140 Zeichen), bevor die
            # Laufnummer angehängt wird — ein langer Auftraggebername hätte den
            # Import sonst mit einem DataError abgebrochen. Die Kürzung ist
            # deterministisch, der Wiederholungs-Import erzeugt denselben Wert.
            aref = aref[:130]
            komposit_lauf[aref] = komposit_lauf.get(aref, 0) + 1
            if komposit_lauf[aref] > 1:
                aref = f"{aref}#{komposit_lauf[aref]}"
        aref = aref[:140]
        e['acct_ref'] = aref
        if (Zahlungseingang.objects.filter(bank_referenz=aref).exists()
                or Bankbewegung.objects.filter(bank_referenz=aref).exists()):
            duplikate += 1
            return

        betrag_e = e['betrag']

        # Jede Zeile des Auszugs wird festgehalten — auch die, die sich nicht
        # automatisch zuordnen lässt. Erst dadurch ist das Bankkonto abstimmbar
        # und der Auszug im Programm nachvollziehbar (Praxis-Audit).
        bew = Bankbewegung.objects.create(
            auszug=auszug, konto=konto_bank_obj,
            datum=e.get('datum') or heute, valuta=e.get('valuta'),
            betrag=betrag_e,
            text=(e.get('info') or '')[:255],
            gegenpartei=(e.get('dbtr_name') or '')[:160],
            referenz=(e.get('referenz') or '')[:40],
            bank_referenz=aref, status='offen')
        bewegungen_neu.append(bew)

        def _bew_erledigt(zahlung_obj=None, notiz=''):
            """Auszugszeile abhaken. Auch eine auf 1190 geparkte Gutschrift IST
            gebucht — bliebe sie «offen», zeigte der Saldoabgleich eine Differenz,
            die es gar nicht gibt."""
            bew.status = 'verbucht'
            if zahlung_obj is not None:
                bew.zahlung = zahlung_obj
                bew.liegenschaft = zahlung_obj.liegenschaft
            if notiz:
                bew.bemerkung = notiz[:255]
            bew.save(update_fields=['status', 'zahlung', 'liegenschaft', 'bemerkung'])

        # Belastungen wandern in den Bank-Eingang zur Zuordnung. Automatisch
        # buchen wäre geraten — das Gegenkonto (Lieferant, Gebühr, Zins, Miete
        # des Eigentümers) steht nicht im Auszug.
        if betrag_e < 0:
            belastungen += 1
            return

        rechnung = ref_index.get(e['referenz']) if e['referenz'] else None

        # 1) Exakte QRR-Referenz
        if rechnung and rechnung.vertrag_id and rechnung.offener_betrag > 0:
            offen = rechnung.offener_betrag
            betrag = min(max(betrag_e, Decimal('0.01')), offen)
            _verbuche(rechnung, betrag, e, 'Referenz')
            verbucht += 1; zugeordnet_summe += betrag
            # Überzahlung: den vollen Bankeingang abbilden — der Überschuss wird als
            # Mieterguthaben auf 2030 gebucht. Ohne das läge auf 1020 weniger als auf
            # dem realen Kontoauszug → Bankabgleich geht nie auf und die Überzahlung
            # verschwindet. 2030 statt 1190 (Audit W6): der Mieter ist bekannt, das
            # ist eine echte Verbindlichkeit und kein ungeklärter Durchlaufposten.
            ueberschuss = betrag_e - offen
            if ueberschuss > 0:
                with transaction.atomic():
                    z_ueber = Zahlungseingang.objects.create(
                        vertrag=rechnung.vertrag, betrag=ueberschuss,
                        datum_eingang=e['datum'] or heute,
                        buchungs_monat=(e['datum'] or heute).replace(day=1),
                        bemerkung=f"{quelle} Überzahlung {rechnung.titel} (Guthaben Mieter)"[:255],
                        bank_referenz=f"{aref}:ueber"[:140], konto=konto_guthaben,
                        liegenschaft=rechnung.vertrag.einheit.liegenschaft if rechnung.vertrag.einheit_id else None,
                        erstellt_von=request.user, status='verbucht')
                    from finance.booking import buche
                    buche(bank_nr, "2030", ueberschuss,
                          f"{quelle} Überzahlung {rechnung.vertrag.mieter} - {rechnung.titel}",
                          datum=e['datum'] or heute,
                          liegenschaft=rechnung.vertrag.einheit.liegenschaft if rechnung.vertrag.einheit_id else None,
                          zahlung=z_ueber, user=request.user)
                guthaben += 1; zugeordnet_summe += ueberschuss
            return

        # 2) Fuzzy: exakter Betrag + Name des Auftraggebers passt eindeutig
        name = _norm(e.get('dbtr_name', '')) or _norm(e.get('info', ''))
        kandidaten = [r for r in offene if r.vertrag_id and r.offener_betrag == betrag_e
                      and name and r.vertrag.mieter and _norm(r.vertrag.mieter.nachname) and _norm(r.vertrag.mieter.nachname) in name]
        if len(kandidaten) == 1:
            r = kandidaten[0]
            _verbuche(r, betrag_e, e, 'Name+Betrag')
            verbucht += 1; fuzzy += 1; zugeordnet_summe += betrag_e
            return

        # 2b) Gelernter Absender: Wurde dieser Zahler schon einmal von Hand
        # zugeordnet, gilt die Entscheidung weiter. Konservativ — nur wenn der
        # Vertrag GENAU EINE offene Rechnung hat und der Betrag hineinpasst.
        # Bei mehreren offenen Rechnungen wäre die Wahl geraten, und geratene
        # Zahlungszuordnungen sind teurer als eine Minute Handarbeit.
        from core.services import zahler as _zahler
        absender, _rest_txt, _ = _zahler.aus_bewegung(e.get('dbtr_name'), e.get('info'))
        gelernter_vertrag = _zahler.finde_vertrag(absender) if absender else None
        if gelernter_vertrag is not None:
            kand = [r for r in offene if r.vertrag_id == gelernter_vertrag.id
                    and r.offener_betrag > 0]
            if len(kand) == 1 and betrag_e <= kand[0].offener_betrag:
                _verbuche(kand[0], betrag_e, e, f'gelernter Absender {absender}')
                _zahler.zaehle_treffer(absender)
                verbucht += 1; gelernt_treffer += 1; zugeordnet_summe += betrag_e
                return

        # 3) Nicht zuordenbar → parken (nichts geht verloren).
        # Trägt die Zahlung eine QRR, deren Rechnung bereits bezahlt ist, ist der
        # Zahler bekannt: das ist eine Doppelzahlung des Mieters und gehört als
        # Guthaben auf 2030, nicht als «ungeklärt» auf 1190 — dort wäre sie
        # optisch ein Fremdeingang und der Mieter bekäme sein Geld nie zurück.
        bekannte = ref_index.get(e['referenz']) if e['referenz'] else None
        if bekannte is None and e['referenz']:
            bekannte = (DebitorenRechnung.objects
                        .filter(qr_referenz=e['referenz'], vertrag__isnull=False)
                        .select_related('vertrag__einheit__liegenschaft').first())
        with transaction.atomic():
            from finance.booking import buche
            if bekannte is not None and bekannte.vertrag_id:
                v_b = bekannte.vertrag
                lg_b = v_b.einheit.liegenschaft if v_b.einheit_id else None
                zahlung = Zahlungseingang.objects.create(
                    vertrag=v_b, betrag=betrag_e, datum_eingang=e['datum'] or heute,
                    buchungs_monat=(e['datum'] or heute).replace(day=1),
                    bemerkung=f"{quelle} Doppelzahlung {bekannte.titel} (Guthaben Mieter)"[:255],
                    bank_referenz=aref, konto=konto_guthaben, liegenschaft=lg_b,
                    erstellt_von=request.user, status='verbucht')
                buche(bank_nr, "2030", betrag_e,
                      f"{quelle} Doppelzahlung {v_b.mieter} - {bekannte.titel}",
                      datum=e['datum'] or heute, liegenschaft=lg_b,
                      zahlung=zahlung, user=request.user)
                _bew_erledigt(zahlung, f"Doppelzahlung → 2030 ({bekannte.titel})")
                guthaben += 1
                return
            zahlung = Zahlungseingang.objects.create(
                betrag=betrag_e, datum_eingang=e['datum'] or heute,
                buchungs_monat=(e['datum'] or heute).replace(day=1),
                bemerkung=f"{quelle} UNGEKLÄRT: {e.get('dbtr_name','') or e.get('info','') or e.get('referenz','')}"[:255],
                bank_referenz=aref, konto=konto_clearing,
                erstellt_von=request.user, status='verbucht')
            buche(bank_nr, "1190", betrag_e,
                  f"{quelle} ungeklärt: {e.get('dbtr_name','') or e.get('referenz','')}",
                  datum=e['datum'] or heute, zahlung=zahlung, user=request.user)
        _bew_erledigt(zahlung, "ungeklärt → Durchlaufkonto 1190")
        geklaert += 1

    for e in eintraege:
        try:
            _eintrag_verarbeiten(e)
        except PermissionError:
            gesperrt += 1

    log_aktion(request, f"{quelle}-Import", datei.name,
               f"{verbucht} verbucht (davon {fuzzy} fuzzy, {gelernt_treffer} gelernter "
               f"Absender), CHF {zugeordnet_summe}, "
               f"{geklaert} auf 1190, {guthaben} Guthaben auf 2030, {duplikate} Duplikate, "
               f"{gesperrt} Periodensperre")
    if verbucht or geklaert or guthaben or belastungen:
        teile = [f"{verbucht} Zahlung(en) zugeordnet (CHF {zugeordnet_summe})"]
        if fuzzy:
            teile.append(f"davon {fuzzy} über Name/Betrag")
        if gelernt_treffer:
            teile.append(f"{gelernt_treffer} über einen früher zugeordneten Absender")
        if guthaben:
            teile.append(f"{guthaben} Überzahlung(en) als Mieterguthaben (2030)")
        if geklaert:
            teile.append(f"{geklaert} ungeklärt auf Durchlaufkonto 1190 geparkt")
        if duplikate:
            teile.append(f"{duplikate} Duplikat(e) übersprungen")
        messages.success(request, f"✅ {quelle}-Import: " + ", ".join(teile) + ".")
    else:
        messages.warning(request,
            f"Keine neuen Gutschriften verbucht ({duplikate} Duplikat(e) übersprungen).")
    if belastungen:
        messages.info(request, f"ℹ️ {belastungen} Belastung(en) übernommen — sie liegen im "
                               f"Bank-Eingang zur Zuordnung. Das Gegenkonto (Lieferant, "
                               f"Gebühr, Zins) steht nicht im Auszug und wird bewusst nicht geraten.")
    # Saldoabgleich: der Nachweis, dass Buchhaltung und Bankkonto übereinstimmen.
    if auszug.schlusssaldo is not None:
        from django.db.models import Sum as _SumB
        _bq = Buchung.objects.filter(ist_storno=False, storniert_am__isnull=True)
        if auszug.bis:
            _bq = _bq.filter(datum__lte=auszug.bis)
        _s = _bq.filter(soll_konto=konto_bank_obj).aggregate(t=_SumB('betrag'))['t'] or Decimal('0.00')
        _h = _bq.filter(haben_konto=konto_bank_obj).aggregate(t=_SumB('betrag'))['t'] or Decimal('0.00')
        buch_saldo = (_s - _h).quantize(Decimal('0.01'))
        diff = (auszug.schlusssaldo - buch_saldo).quantize(Decimal('0.01'))
        if diff == 0:
            messages.success(request, f"✅ Saldoabgleich {bank_nr}: Buchhaltung und Auszug "
                                      f"stimmen überein (CHF {buch_saldo}).")
        else:
            messages.warning(request, f"⚠️ Saldoabgleich {bank_nr}: Auszug CHF "
                                      f"{auszug.schlusssaldo}, Buchhaltung CHF {buch_saldo} — "
                                      f"Differenz CHF {diff}. Offene Bewegungen im Bank-Eingang "
                                      f"zuordnen, dann stimmt es.")
    if gesperrt:
        # Nie stillschweigend überspringen — der Import gälte sonst als vollständig.
        messages.error(request, f"⚠️ {gesperrt} Zahlung(en) konnten nicht verbucht werden: "
                                f"die Buchungsperiode ist gesperrt. Periode öffnen und die "
                                f"Datei erneut importieren — bereits verbuchte Zahlungen "
                                f"werden dabei als Duplikat übersprungen.")

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
    # Kündigung …) — pro Objekt gruppiert (Objekt = Einheit des Vertrags).
    # Gruppierung nach Mietverhältnis (= Vertrag) — konsistent zum «Verhältnisse»-
    # Tab am Objekt. Ohne Vertragsbezug → «Persönlich».
    from collections import defaultdict
    dok_buckets = defaultdict(list)
    vtr_meta = {}
    for d in (RentalsDokument.objects.filter(_Q(mieter=m) | _Q(vertrag_id__in=_vids))
              .select_related('einheit__liegenschaft', 'vertrag__einheit__liegenschaft')
              .distinct().order_by('-datum')):
        vid = d.vertrag_id
        if vid and vid not in vtr_meta:
            vtr_meta[vid] = d.vertrag
        dok_buckets[vid].append(d)   # Modell-Objekt behalten (Portal-Toggle braucht d.id)

    def _verhaeltnis_label(v):
        e = v.einheit
        obj = f"{e.bezeichnung} · {e.liegenschaft.strasse}" if e else 'Objekt'
        bis = v.ende.strftime('%d.%m.%Y') if v.ende else 'laufend'
        return f"{obj} · {v.beginn:%d.%m.%Y}–{bis}"

    dok_gruppen = []
    # Reihenfolge: Verhältnisse (Verträge) wie in der Vertragsliste (neueste zuerst)
    geordnet = list(vertraege) + [v for vid, v in vtr_meta.items()
                                  if vid not in {x.id for x in vertraege}]
    for v in geordnet:
        docs = dok_buckets.get(v.id)
        if docs:
            dok_gruppen.append({'einheit': v.einheit, 'vertrag': v,
                                'label': _verhaeltnis_label(v), 'dokumente': docs})
    if dok_buckets.get(None):
        dok_gruppen.append({'einheit': None, 'vertrag': None,
                            'label': 'Persönlich (ohne Vertragsbezug)',
                            'dokumente': dok_buckets[None]})
    dok_total = sum(len(g['dokumente']) for g in dok_gruppen)

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
        ('dokumente', 'Dokumente', dok_total or None),
        ('aktivitaet', 'Journal', m.kommunikationen.count() or None),
        ('verlauf', 'Verlauf', len(verlauf) or None),
    ]
    return render(request, 'fw/person_detail.html', {
        **basis, 'nav': 'personen', 'm': m, 'verlauf': verlauf,
        'vertrag_rows': vertrag_rows,
        'anzahl_aktive': len(aktive),
        'brutto_monat': sum((r['brutto'] for r in vertrag_rows if r['v'].status == 'aktiv'), Decimal('0.00')),
        'offene': offene, 'total_offen': total_offen,
        'zahlungen': zahlungen, 'dok_gruppen': dok_gruppen, 'dok_total': dok_total,
        'telefon': m.mobile or m.telefon_privat or m.telefon_geschaeft,
        'kommunikationen': m.kommunikationen.select_related('vertrag', 'erstellt_von')[:50],
        'portal_user': getattr(m, 'benutzer', None),
        'tab_liste': tab_liste,
        'adress_verlauf': list(m.adressen.all()),
        'heute': timezone.localdate().isoformat(),
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


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterkonto(request, pk):
    """Mieterkontoblatt (on-screen): alle Forderungen (Sollstellungen) und Zahlungen
    chronologisch mit laufendem Saldo — dieselbe Datenbasis wie der PDF-Auszug."""
    from core.services.mieterkonto import berechne_mieterkonto
    from django.db.models import Q as _Q
    m = get_object_or_404(Mieter, id=pk)
    basis = _global_filter(request)

    von = bis = None
    try:
        if request.GET.get('von'):
            von = date.fromisoformat(request.GET['von'])
        if request.GET.get('bis'):
            bis = date.fromisoformat(request.GET['bis'])
    except ValueError:
        von = bis = None

    zeilen, endsaldo = berechne_mieterkonto(m, von=von, bis=bis)
    total_soll = sum((z['soll'] for z in zeilen), Decimal('0.00'))
    total_haben = sum((z['haben'] for z in zeilen), Decimal('0.00'))

    # Offene Posten (OP): noch nicht (voll) bezahlte Forderungen
    vids = list(Mietvertrag.objects.filter(_Q(mieter=m) | _Q(mitmieter=m)).values_list('id', flat=True))
    op = [r for r in DebitorenRechnung.objects.filter(vertrag_id__in=vids, status__in=['offen', 'teilbezahlt'])
          .select_related('vertrag__einheit__liegenschaft').order_by('faellig_am') if r.offener_betrag > 0]
    heute = timezone.localdate()
    op_rows = [{
        'r': r, 'offen': r.offener_betrag,
        'faellig': r.faellig_am or r.datum,
        'ueberfaellig': bool((r.faellig_am or r.datum) and (r.faellig_am or r.datum) < heute),
    } for r in op]

    return render(request, 'fw/mieterkonto.html', {
        **basis, 'nav': 'mieterkonten', 'm': m,
        'zeilen': zeilen, 'endsaldo': endsaldo,
        'total_soll': total_soll, 'total_haben': total_haben,
        'op_rows': op_rows, 'op_total': sum((o['offen'] for o in op_rows), Decimal('0.00')),
        'von': von, 'bis': bis,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mieterkonten(request):
    """Übersicht aller Mieterkonten: pro Mieter der aktuelle Saldo (Forderungen −
    Zahlungen). Einstieg ins einzelne Kontoblatt."""
    from core.services.mieterkonto import berechne_mieterkonto
    from django.db.models import Q as _Q
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    filter_op = request.GET.get('filter') == 'offen'

    vtr = Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft')
    if aktive_lg:
        vtr = vtr.filter(einheit__liegenschaft=aktive_lg)
    # Ein Mieter kann mehrere Verträge haben → pro Mieter EIN Konto.
    mieter_map = {}
    for v in vtr:
        if not v.mieter_id:
            continue
        eintrag = mieter_map.setdefault(v.mieter_id, {'mieter': v.mieter, 'objekte': set(), 'aktiv': False})
        if v.einheit_id and v.einheit.liegenschaft_id:
            eintrag['objekte'].add(f"{v.einheit.liegenschaft.strasse} · {v.einheit.bezeichnung}")
        if v.status == 'aktiv':
            eintrag['aktiv'] = True

    # Suche: bei mehr als einer Handvoll Mieter ist Scrollen keine Bedienung.
    q = (request.GET.get('q') or '').strip()
    q_klein = q.lower()

    rows = []
    total_offen = Decimal('0.00')
    gesamt_n = 0            # alle Mieter — unabhängig von Filter und Suche
    offen_gesamt_n = 0
    for mid, data in mieter_map.items():
        _, saldo = berechne_mieterkonto(data['mieter'])
        gesamt_n += 1
        if saldo > 0:
            total_offen += saldo
            offen_gesamt_n += 1
        if filter_op and saldo <= 0:
            continue
        objekt_text = ' · '.join(sorted(data['objekte'])[:1]) or '—'
        if q_klein and q_klein not in (data['mieter'].display_name or '').lower() \
                and q_klein not in objekt_text.lower():
            continue
        rows.append({
            'm': data['mieter'], 'saldo': saldo,
            'objekt': objekt_text,
            'objekte_n': len(data['objekte']),
            'aktiv': data['aktiv'],
        })
    # offene zuerst (grösster Schuldsaldo oben), dann Name
    rows.sort(key=lambda r: (-(r['saldo'] if r['saldo'] > 0 else Decimal('0')), (r['m'].nachname or '').lower()))

    return render(request, 'fw/mieterkonten.html', {
        **basis, 'nav': 'mieterkonten', 'rows': rows, 'q': q,
        # «Alle (N)» zählte bisher die bereits gefilterten Zeilen — in der
        # gefilterten Ansicht stand am «Alle»-Knopf also die falsche Zahl.
        'total_offen': total_offen, 'anzahl': gesamt_n,
        'offen_n': offen_gesamt_n, 'treffer_n': len(rows),
        'filter_op': filter_op,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_lieferantenkonten(request):
    """Übersicht Lieferantenkonten (Kreditoren): pro Lieferant offener Betrag
    (was die Verwaltung dem Lieferanten noch schuldet). Einstieg ins Kontoblatt."""
    from finance.models import KreditorenRechnung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    filter_op = request.GET.get('filter') == 'offen'

    kred = KreditorenRechnung.objects.exclude(status='storniert')
    if aktive_lg:
        kred = kred.filter(liegenschaft=aktive_lg)

    gruppen = {}
    for k in kred:
        name = (k.lieferant or '').strip() or '— ohne Lieferant —'
        g = gruppen.setdefault(name, {'name': name, 'anzahl': 0, 'offen': Decimal('0.00'),
                                      'volumen': Decimal('0.00')})
        g['anzahl'] += 1
        g['offen'] += k.offener_betrag
        g['volumen'] += (k.betrag or Decimal('0.00'))

    rows = list(gruppen.values())
    total_offen = sum((g['offen'] for g in rows), Decimal('0.00'))
    if filter_op:
        rows = [g for g in rows if g['offen'] > 0]
    rows.sort(key=lambda g: (-g['offen'], g['name'].lower()))

    return render(request, 'fw/lieferantenkonten.html', {
        **basis, 'nav': 'lieferantenkonten', 'rows': rows,
        'total_offen': total_offen, 'anzahl': len(gruppen),
        'offen_n': sum(1 for g in gruppen.values() if g['offen'] > 0),
        'filter_op': filter_op,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_lieferantenkonto(request):
    """Kontoblatt eines Lieferanten: alle Rechnungen (Belastung) und Zahlungen
    (Ausgang) chronologisch mit laufendem offenem Saldo. Lieferant via ?name=."""
    from finance.models import KreditorenRechnung, KreditorenZahlung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    name = (request.GET.get('name') or '').strip()

    kred = KreditorenRechnung.objects.exclude(status='storniert')
    if aktive_lg:
        kred = kred.filter(liegenschaft=aktive_lg)
    if name == '— ohne Lieferant —':
        kred = kred.filter(Q(lieferant='') | Q(lieferant__isnull=True))
    else:
        kred = kred.filter(lieferant=name)
    kred = list(kred.select_related('liegenschaft').prefetch_related('zahlungen'))

    bewegungen = []
    for k in kred:
        d = k.datum or k.faellig_am or heute
        bewegungen.append({'datum': d, 'text': f"Rechnung{(' ' + k.referenz) if k.referenz else ''}",
                           'belastung': k.betrag or Decimal('0.00'), 'zahlung': Decimal('0.00'), 'sort': 0})
        for z in k.zahlungen.all():
            if z.status != 'verbucht':
                continue
            bewegungen.append({'datum': z.datum, 'text': z.bemerkung or 'Zahlung',
                               'belastung': Decimal('0.00'), 'zahlung': z.betrag or Decimal('0.00'), 'sort': 1})
    bewegungen.sort(key=lambda b: (b['datum'], b['sort']))
    saldo = Decimal('0.00')
    for b in bewegungen:
        saldo += b['belastung'] - b['zahlung']
        b['saldo'] = saldo

    total_belastung = sum((b['belastung'] for b in bewegungen), Decimal('0.00'))
    total_zahlung = sum((b['zahlung'] for b in bewegungen), Decimal('0.00'))

    # Offene Posten (unbezahlte/teilbezahlte Rechnungen)
    op = [{'k': k, 'offen': k.offener_betrag, 'faellig': k.faellig_am or k.datum,
           'ueberfaellig': bool((k.faellig_am or k.datum) and (k.faellig_am or k.datum) < heute)}
          for k in kred if k.offener_betrag > 0]
    op.sort(key=lambda o: (o['faellig'] or heute))

    # Verlauf: alle protokollierten Aktionen zu diesem Lieferanten (Rechnung
    # erstellt/gescannt/bearbeitet/freigegeben/bezahlt/gelöscht, Dienstleister-
    # Änderungen). Kreditorenrechnungen tragen den Lieferanten als Log-Objekt —
    # der Abgleich läuft über den Namen (kein FK am Modell).
    from core.models import AktivitaetsLog
    verlauf = []
    if name and name != '— ohne Lieferant —':
        verlauf = list(AktivitaetsLog.objects.filter(objekt__iexact=name)
                       .select_related('benutzer')[:50])

    return render(request, 'fw/lieferantenkonto.html', {
        **basis, 'nav': 'lieferantenkonten', 'name': name,
        'bewegungen': bewegungen, 'endsaldo': saldo,
        'total_belastung': total_belastung, 'total_zahlung': total_zahlung,
        'op_rows': op, 'op_total': sum((o['offen'] for o in op), Decimal('0.00')),
        'rechnungen_n': len(kred),
        'verlauf': verlauf,
    })


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
def fw_kommunikation_loeschen(request, pk):
    """Journal-Eintrag (Kommunikation) löschen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Kommunikation
    from core.auth import log_aktion
    k = get_object_or_404(Kommunikation.objects.select_related('mieter'), id=pk)
    mid = k.mieter_id
    if request.method == 'POST':
        log_aktion(request, "Journal-Eintrag gelöscht", str(k.mieter) if k.mieter_id else '', k.typ)
        k.delete()
        messages.success(request, "🗑️ Journal-Eintrag gelöscht.")
    return redirect(f'/neu/personen/{mid}/?tab=aktivitaet')


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


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_rentals_dokument_loeschen(request, pk):
    """Dokument (Vertrags-/Mieter-Ablage) löschen — überall dort, wo Dokumente
    in Akten gezeigt werden (Person, Vertrag, Objekt, Liegenschaft, Portal)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from rentals.models import Dokument as RentalsDokument
    from core.auth import log_aktion
    d = get_object_or_404(RentalsDokument, id=pk)
    ref = request.META.get('HTTP_REFERER')
    ziel = ref or (f'/neu/personen/{d.mieter_id}/' if d.mieter_id else '/neu/dokumente/')
    if request.method == 'POST':
        titel = d.bezeichnung or d.titel or 'Dokument'
        d.delete()
        log_aktion(request, "Dokument gelöscht", titel, '')
        messages.success(request, "🗑️ Dokument gelöscht.")
    return redirect(ziel)


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


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_person_dsg_loeschen(request, pk):
    """DSG-Löschung: anonymisiert die Personendaten (Recht auf Löschung), behält
    aber die Buchungsbelege (10-Jahres-Aufbewahrung Art. 958f OR). Bewerber-
    Dokumente (Ausweis/Lohn/Betreibung) werden physisch gelöscht."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.services.dsg import anonymisiere_person
    from core.auth import log_aktion
    m = get_object_or_404(Mieter, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/personen/{m.id}/')
    name = m.display_name
    grund = (request.POST.get('grund') or '').strip()
    ok, meldung = anonymisiere_person(m, grund=grund, user=request.user)
    if ok:
        log_aktion(request, "DSG-Anonymisierung", name, grund or "Personendaten anonymisiert (Belege bleiben).")
        messages.success(request, f"🔒 {meldung}")
    else:
        messages.error(request, f"❌ {meldung}")
    return redirect(f'/neu/personen/{m.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_person_adresse_neu(request, pk):
    """Fügt eine datierte Adress-Zeile hinzu (Wohn- oder Korrespondenzadresse)
    mit «gültig ab» — analog zum Sollmietzins. Der Auto-Sync führt danach die
    effektive Zustelladresse nach."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import MieterAdresse
    from core.auth import log_aktion
    m = get_object_or_404(Mieter, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/personen/{m.id}/')
    P = request.POST
    art = P.get('art', 'wohn')
    if art not in ('wohn', 'korrespondenz'):
        art = 'wohn'
    try:
        gab = date.fromisoformat((P.get('gueltig_ab') or '').strip())
    except ValueError:
        messages.error(request, "❌ Ungültiges «gültig ab»-Datum.")
        return redirect(f'/neu/personen/{m.id}/')
    strasse = P.get('strasse', '').strip()
    plz = P.get('plz', '').strip()
    ort = P.get('ort', '').strip()
    if not (strasse or plz or ort):
        messages.error(request, "❌ Bitte mindestens Strasse oder PLZ/Ort erfassen.")
        return redirect(f'/neu/personen/{m.id}/')
    MieterAdresse.objects.update_or_create(
        mieter=m, art=art, gueltig_ab=gab,
        defaults=dict(strasse=strasse, adresszusatz=P.get('adresszusatz', '').strip(),
                      plz=plz, ort=ort, quelle='manuell',
                      notiz=P.get('notiz', '').strip()))
    m.sync_effektive_adresse()
    log_aktion(request, "Adresse hinterlegt", m.display_name,
               f"{art} ab {gab:%d.%m.%Y}: {strasse}, {plz} {ort}", ziel=m)
    messages.success(request, "✅ Adresse gespeichert.")
    return redirect(f'/neu/personen/{m.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_person_adresse_loeschen(request, pk):
    """Entfernt eine datierte Adress-Zeile und führt die effektive Adresse nach."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import MieterAdresse
    from core.auth import log_aktion
    adr = get_object_or_404(MieterAdresse, id=pk)
    m = adr.mieter
    if request.method == 'POST':
        info = f"{adr.get_art_display()} ab {adr.gueltig_ab:%d.%m.%Y}"
        adr.delete()
        m.sync_effektive_adresse()
        log_aktion(request, "Adresse entfernt", m.display_name, info, ziel=m)
        messages.success(request, "✅ Adress-Zeile entfernt.")
    return redirect(f'/neu/personen/{m.id}/')


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
        obj.land = P.get('land', '').strip() or 'Schweiz'
        gd = P.get('geburtsdatum', '').strip()
        try:
            obj.geburtsdatum = date.fromisoformat(gd) if gd else None
        except ValueError:
            obj.geburtsdatum = None
        # --- Identität / Vermietungsprüfung ---
        obj.zivilstand = P.get('zivilstand', '').strip()
        obj.nationalitaet = P.get('nationalitaet', '').strip()
        obj.heimatort = P.get('heimatort', '').strip()
        obj.ahv_nummer = P.get('ahv_nummer', '').strip()
        obj.sprache = P.get('sprache', 'de').strip() or 'de'
        obj.telefon_geschaeft = P.get('telefon_geschaeft', '').strip()
        # --- Aufenthalt ---
        obj.aufenthaltsbewilligung = P.get('aufenthaltsbewilligung', '').strip()
        bgb = P.get('bewilligung_gueltig_bis', '').strip()
        try:
            obj.bewilligung_gueltig_bis = date.fromisoformat(bgb) if bgb else None
        except ValueError:
            obj.bewilligung_gueltig_bis = None
        # --- Beruf & Bonität ---
        obj.erwerbsstatus = P.get('erwerbsstatus', '').strip()
        obj.beruf = P.get('beruf', '').strip()
        obj.arbeitgeber = P.get('arbeitgeber', '').strip()
        obj.einkommen_jahr = P.get('einkommen_jahr', '').strip()
        bd = P.get('bonitaet_datum', '').strip()
        try:
            obj.bonitaet_datum = date.fromisoformat(bd) if bd else None
        except ValueError:
            obj.bonitaet_datum = None
        # --- Versicherung & Notfall ---
        obj.haftpflicht_gesellschaft = P.get('haftpflicht_gesellschaft', '').strip()
        obj.haftpflicht_police = P.get('haftpflicht_police', '').strip()
        obj.notfall_name = P.get('notfall_name', '').strip()
        obj.notfall_telefon = P.get('notfall_telefon', '').strip()
        obj.notfall_beziehung = P.get('notfall_beziehung', '').strip()
        # --- Haushalt ---
        def _pint(key):
            try:
                return max(0, int(P.get(key, '') or 0))
            except ValueError:
                return 0
        obj.haushalt_erwachsene = _pint('haushalt_erwachsene')
        obj.haushalt_kinder = _pint('haushalt_kinder')
        obj.haustiere = P.get('haustiere') == 'on'
        obj.haustiere_details = P.get('haustiere_details', '').strip()
        # --- Finanzen ---
        obj.bank_name = P.get('bank_name', '').strip()
        obj.iban = P.get('iban', '').strip()
        obj.betreibung_ergebnis = P.get('betreibung_ergebnis', '').strip()
        # --- Zahlungsverkehr ---
        obj.zahlungsart = P.get('zahlungsart', '').strip()
        obj.ebill_email = P.get('ebill_email', '').strip()
        obj.mahnsperre = P.get('mahnsperre') == 'on'
        obj.zahler_name = P.get('zahler_name', '').strip()
        obj.zahler_adresse = P.get('zahler_adresse', '').strip()
        obj.zahler_iban = P.get('zahler_iban', '').strip()
        # --- Vorvermieter-Referenz ---
        obj.ref_vermieter_name = P.get('ref_vermieter_name', '').strip()
        obj.ref_vermieter_telefon = P.get('ref_vermieter_telefon', '').strip()
        obj.ref_vermieter_email = P.get('ref_vermieter_email', '').strip()
        # --- Vertretung / Beistand ---
        obj.vertretung_art = P.get('vertretung_art', '').strip()
        obj.vertretung_name = P.get('vertretung_name', '').strip()
        obj.vertretung_kontakt = P.get('vertretung_kontakt', '').strip()
        obj.notizen = P.get('notizen', '').strip()

        # --- Pflichtfeld-Validierung ---
        # Nachname nur bei Privatpersonen Pflicht; Firma UND Verein/Stiftung
        # brauchen stattdessen den Firmen-/Organisationsnamen.
        fehler = []
        if obj.typ in ('firma', 'verein'):
            if not obj.firmen_name:
                fehler.append("Firmen-/Organisationsname ist erforderlich.")
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
        # --- Datierte Adress-Historie pflegen (Wohn- + Korrespondenzadresse) ---
        # Die Formularfelder bearbeiten die AKTUELLE Zeile (Korrektur), nicht einen
        # Umzug — ein Umzug entsteht über Vertragsbeginn/Auszug mit eigenem «gültig ab».
        from crm.models import MieterAdresse
        from datetime import date as _date
        heute = timezone.localdate()
        SENTINEL = _date(2000, 1, 1)
        w = (P.get('strasse', '').strip(), P.get('adresszusatz', '').strip(),
             P.get('plz', '').strip(), P.get('ort', '').strip())
        wohn = obj.aktuelle_wohnadresse(heute)
        if any(w):
            if wohn:
                if (wohn.strasse, wohn.adresszusatz, wohn.plz, wohn.ort) != w:
                    wohn.strasse, wohn.adresszusatz, wohn.plz, wohn.ort = w
                    wohn.save()
            else:
                MieterAdresse.objects.create(
                    mieter=obj, art='wohn', gueltig_ab=SENTINEL,
                    strasse=w[0], adresszusatz=w[1], plz=w[2], ort=w[3], quelle='manuell')
        k = (P.get('k_strasse', '').strip(), P.get('k_adresszusatz', '').strip(),
             P.get('k_plz', '').strip(), P.get('k_ort', '').strip())
        korr = obj.aktuelle_korrespondenzadresse(heute)
        if any(k):
            if korr:
                korr.strasse, korr.adresszusatz, korr.plz, korr.ort = k
                korr.save()
            else:
                MieterAdresse.objects.create(
                    mieter=obj, art='korrespondenz', gueltig_ab=SENTINEL,
                    strasse=k[0], adresszusatz=k[1], plz=k[2], ort=k[3], quelle='manuell')
        elif korr and korr.quelle == 'manuell':
            korr.delete()  # Korrespondenzadresse geleert → kein Zustell-Vorrang mehr
        obj.sync_effektive_adresse(heute)
        aenderungen = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Person bearbeitet" if pk else "Person erstellt",
                   obj.display_name, aenderungen, ziel=obj)
        messages.success(request, f"✅ {obj.display_name} gespeichert.")
        return redirect(f'/neu/personen/{obj.id}/')

    return render(request, 'fw/person_form.html', {
        **basis, 'nav': 'personen', 'm': m,
        'ist_neu': m is None,
        'korr_adr': m.aktuelle_korrespondenzadresse() if m else None,
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
    if typ in ('firma', 'verein') and firmen_name:
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
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    # prefetch_related: ohne 'zahlungen' löst offener_betrag je Zeile eine eigene
    # SUM-Abfrage aus, ohne 'positionen' je Zeile zwei weitere (N+1 → Timeout).
    qs = (KreditorenRechnung.objects.exclude(status='storniert')
          .select_related('liegenschaft', 'konto')
          .prefetch_related('zahlungen', 'positionen__konto', 'positionen__einheit'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    status_filter = request.GET.get('status', '')
    if status_filter in KRED_PILL:
        qs = qs.filter(status=status_filter)

    # Volltextsuche über Lieferant, Referenz und Betrag — bei einigen hundert
    # Rechnungen ist Scrollen keine Suche (Praxis-Audit).
    suche = (request.GET.get('q') or '').strip()
    if suche:
        from django.db.models import Q as _Qk
        bedingung = (_Qk(lieferant__icontains=suche) | _Qk(referenz__icontains=suche)
                     | _Qk(iban__icontains=suche.replace(' ', '')))
        try:
            bedingung |= _Qk(betrag=Decimal(_num(suche)))
        except Exception:
            pass
        qs = qs.filter(bedingung)

    # Sortierung: Fälligkeit zuerst ist die Arbeitsreihenfolge der Kreditoren-
    # buchhaltung; '-id' (Erfassungsreihenfolge) bleibt als Option erhalten.
    SORTIERUNGEN = {
        'faellig': ['faellig_am', 'id'],
        '-faellig': ['-faellig_am', '-id'],
        'betrag': ['betrag', 'id'],
        '-betrag': ['-betrag', '-id'],
        'lieferant': ['lieferant', 'id'],
        'neu': ['-id'],
    }
    sortierung = request.GET.get('sort') or 'faellig'
    if sortierung not in SORTIERUNGEN:
        sortierung = 'faellig'
    qs = qs.order_by(*SORTIERUNGEN[sortierung])

    # Kennzahlen über den GANZEN gefilterten Bestand — die Seite zeigt nur einen
    # Ausschnitt, die Summen dürfen davon nicht abhängen.
    from django.db.models import Sum as _SumK, Count as _CountK
    _kpi = (KreditorenRechnung.objects.exclude(status='storniert')
            .filter(status='neu'))
    if aktive_lg:
        _kpi = _kpi.filter(liegenschaft=aktive_lg)
    _kpi_agg = _kpi.aggregate(s=_SumK('betrag'), n=_CountK('id'))
    total_neu = _kpi_agg['s'] or Decimal('0.00')
    anzahl_neu = _kpi_agg['n'] or 0
    gesamt_anzahl = qs.count()

    from django.core.paginator import Paginator
    paginator = Paginator(qs, 50)
    seite = paginator.get_page(request.GET.get('seite') or 1)

    rows = []
    total_offen = Decimal('0.00')     # freigegeben, noch nicht bezahlt (diese Seite)
    for k in seite.object_list:
        label, cls = KRED_PILL.get(k.status, (k.status, 'bg-slate-100 text-slate-500'))
        betrag = k.betrag or Decimal('0.00')
        offen_betrag = k.offener_betrag
        faellig = k.faellig_am
        if k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt'):
            total_offen += offen_betrag
        rows.append({
            'k': k, 'betrag': betrag, 'status_label': label, 'pill_cls': cls,
            'faellig': faellig,
            'ueberfaellig': bool(faellig and faellig < heute and k.status != 'bezahlt'),
            'lieferant': k.lieferant or 'Wird gescannt …',
            'objekt': f"{k.liegenschaft.strasse}, {k.liegenschaft.ort}" if k.liegenschaft else '—',
            'konto': f"{k.konto.nummer} {k.konto.bezeichnung}" if k.konto else None,
            'beleg_url': k.beleg_scan.url if k.beleg_scan else None,
            'beleg_ist_pdf': bool(k.beleg_scan and str(k.beleg_scan.name).lower().endswith('.pdf')),
            'kann_bezahlen': k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt'),
            'in_zahlung': k.status == 'in_zahlung',
            'teilbezahlt': k.status == 'teilbezahlt',
            'offen_betrag': offen_betrag,
            'offen_wv': k.offen_weiterzuverrechnen,
            'kann_weiterverrechnen': (k.status in ('freigegeben', 'in_zahlung', 'teilbezahlt', 'bezahlt')
                                      and k.offen_weiterzuverrechnen > 0),
            'positionen': list(k.positionen.all()) if k.status == 'neu' else [],
            'pos_summe': k.positionen_summe if k.status == 'neu' else Decimal('0.00'),
            'pos_diff': k.positionen_differenz if k.status == 'neu' else Decimal('0.00'),
        })

    status_chips = [('', 'Alle')] + [(k, v[0]) for k, v in KRED_PILL.items() if k != 'storniert']

    from finance.models import Buchungskonto
    aufwand_konten = Buchungskonto.objects.filter(typ='aufwand').order_by('nummer')
    liegenschaften = Liegenschaft.objects.order_by('strasse')
    # Für pain.001: freigegebene Rechnungen mit gültiger IBAN
    # «Zahlbar» zählt über den ganzen Bestand, nicht nur die aktuelle Seite —
    # sonst behauptet der Zahllauf-Knopf eine falsche Zahl.
    _zb = KreditorenRechnung.objects.filter(status='freigegeben').exclude(iban='')
    if aktive_lg:
        _zb = _zb.filter(liegenschaft=aktive_lg)
    # Querystring ohne 'seite' — damit Filter/Suche/Sortierung beim Blättern
    # erhalten bleiben (bisher fiel der Filter beim Seitenwechsel weg).
    _qp = request.GET.copy()
    _qp.pop('seite', None)
    query_ohne_seite = _qp.urlencode()
    return render(request, 'fw/kreditoren.html', {
        **basis, 'nav': 'kreditoren', 'rows': rows,
        'status_filter': status_filter, 'status_chips': status_chips,
        'suche': suche, 'sortierung': sortierung,
        'seite': seite, 'query_ohne_seite': query_ohne_seite,
        'total_offen': total_offen, 'total_neu': total_neu, 'anzahl_neu': anzahl_neu,
        'anzahl': gesamt_anzahl,
        'anzahl_zahlbar': _zb.count(),
        'darf_bezahlen': hat_rolle(request.user, VERWALTUNGS_ROLLEN),
        'aufwand_konten': aufwand_konten, 'liegenschaften': liegenschaften,
        'ki_aktiv': bool(getattr(settings, 'GROQ_API_KEY', None)),
        'rechnungs_mail': os.environ.get('RECHNUNGS_IMAP_USER', ''),
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
            return Decimal(_num(x))
        except Exception:
            return None
    offen = k.offener_betrag
    # Leeres Feld = Vollzahlung; eine EXPLIZITE 0 ist ein Tippfehler und darf
    # NICHT still zur Vollzahlung werden (Decimal('0') ist falsy — die frühere
    # `or offen`-Logik zahlte bei Eingabe «0» kommentarlos den vollen Betrag).
    raw = (request.POST.get('betrag') or '').strip()
    betrag = _dec(raw) if raw else offen
    if betrag is None or betrag <= 0:
        messages.error(request, f"Ungültiger Betrag «{raw}» — Zahlung nicht ausgeführt.")
        return redirect('fw_kreditoren')
    betrag = min(betrag, offen)
    if betrag <= 0:
        messages.error(request, "Kein offener Betrag zu bezahlen.")
        return redirect('fw_kreditoren')

    # Valutadatum und Bankkonto sind wählbar — «heute» und «1020» waren stille
    # Annahmen und bei mehreren Bankkonten schlicht falsch (Praxis-Audit).
    try:
        valuta = date.fromisoformat(request.POST.get('valuta') or '')
    except ValueError:
        valuta = timezone.localdate()
    bank_nr = (request.POST.get('bank_konto') or '1020').strip()
    if not Buchungskonto.objects.filter(nummer=bank_nr).exists():
        bank_nr = '1020'
    try:
        with transaction.atomic():
            from finance.booking import buche
            zahlung = KreditorenZahlung.objects.create(
                kreditor=k, betrag=betrag, datum=valuta,
                bemerkung=f"Zahlung {k.lieferant}", erstellt_von=request.user)
            buche("2000", bank_nr, betrag, f"Zahlung {k.lieferant} - {k.referenz}",
                  datum=valuta, liegenschaft=k.liegenschaft, kreditor=k, user=request.user)
            k.status = 'bezahlt' if k.offener_betrag <= 0 else 'teilbezahlt'
            k.save(update_fields=['status'])
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect('fw_kreditoren')

    log_aktion(request, "Kreditorenrechnung bezahlt", k.lieferant or f"Rechnung #{k.id}",
               f"CHF {betrag}" + (f" (offen CHF {k.offener_betrag})" if k.status == 'teilbezahlt' else ""))
    messages.success(request, f"✅ CHF {betrag} an {k.lieferant or 'Lieferant'} bezahlt"
                              + (f" — noch offen CHF {k.offener_betrag}." if k.status == 'teilbezahlt' else "."))
    ziel = '/neu/kreditoren/'
    if lg := request.POST.get('lg'):
        ziel += f'?lg={lg}'
    return redirect(ziel)


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_zahllauf(request):
    """Zahllauf: Vorschlagsliste → Auswahl → pain.001 → Sammelbestätigung.

    Vorher war der Zahllauf ein einzelner Link, der ALLE freigegebenen Rechnungen
    ungefragt in eine Datei packte, und danach musste jede der ~40 Zahlungen
    einzeln als bezahlt geklickt werden. Beides ist in der Praxis unbrauchbar:
    ein Zahllauf ist eine bewusste Auswahl, und die Rückmeldung der Bank betrifft
    den ganzen Lauf, nicht eine Rechnung.
    """
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenRechnung, KreditorenZahlung, Buchungskonto
    from crm.models import Verwaltung
    from core.services.pain001 import generate_pain001
    from core.auth import log_aktion

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    def _ziel():
        z = '/neu/zahllauf/'
        if aktive_lg:
            z += f'?lg={aktive_lg.id}'
        return z

    def _auswahl(status):
        ids = [i for i in request.POST.getlist('rechnung_ids') if str(i).isdigit()]
        qs = KreditorenRechnung.objects.filter(id__in=ids, status__in=status)
        if aktive_lg:
            qs = qs.filter(liegenschaft=aktive_lg)
        return list(qs.select_related('liegenschaft'))

    def _datum(name, standard):
        try:
            return date.fromisoformat(request.POST.get(name) or '')
        except ValueError:
            return standard

    if request.method == 'POST':
        aktion = request.POST.get('aktion')

        # --- 1) Zahlungsdatei für die AUSGEWÄHLTEN Rechnungen ---
        if aktion == 'datei':
            rechnungen = _auswahl(['freigegeben'])
            if not rechnungen:
                messages.error(request, "Keine Rechnung ausgewählt.")
                return redirect(_ziel())
            vw = Verwaltung.objects.first()
            debtor_iban = ((vw.iban if vw else '') or '').strip()
            if not debtor_iban:
                messages.error(request, "Für die Zahlungsdatei fehlt die IBAN der "
                                        "Verwaltung (Profil → Account).")
                return redirect(_ziel())
            # Ausführungsdatum ist frei wählbar — die Bank führt den Lauf an
            # diesem Tag aus; «heute» war eine stille Annahme (Praxis-Audit).
            exec_date = _datum('ausfuehrungsdatum', heute)
            jetzt = timezone.now()
            msg_id = f"SWISSIMMO-{jetzt.strftime('%Y%m%d%H%M%S')}"
            xml, anzahl, summe, skipped = generate_pain001(
                rechnungen, debtor_name=(vw.firma if vw else 'Immobilienverwaltung'),
                debtor_iban=debtor_iban, msg_id=msg_id,
                exec_date=exec_date.isoformat(),
                now_iso=jetzt.strftime('%Y-%m-%dT%H:%M:%S'))
            if anzahl == 0:
                messages.error(request, "Keine zahlbare Rechnung in der Auswahl "
                                        "(IBAN oder Betrag fehlt).")
                return redirect(_ziel())
            uebersprungen = {rid for rid, _ in skipped}
            n = 0
            for r in rechnungen:
                if r.id in uebersprungen:
                    continue
                r.status = 'in_zahlung'
                r.zahlung_ausfuehrung = exec_date
                r.save(update_fields=['status', 'zahlung_ausfuehrung'])
                n += 1
            log_aktion(request, "Zahllauf erzeugt", msg_id,
                       f"{anzahl} Zahlungen, CHF {summe}, Ausführung {exec_date}")
            resp = HttpResponse(xml, content_type='application/xml')
            resp['Content-Disposition'] = f'attachment; filename="{msg_id}.xml"'
            return resp

        # --- 2) Sammelbestätigung: ausgewählte Zahlungen verbuchen ---
        if aktion == 'bezahlt':
            rechnungen = _auswahl(['in_zahlung', 'freigegeben', 'teilbezahlt'])
            if not rechnungen:
                messages.error(request, "Keine Rechnung ausgewählt.")
                return redirect(_ziel())
            bank_nr = (request.POST.get('bank_konto') or '1020').strip()
            if not Buchungskonto.objects.filter(nummer=bank_nr).exists():
                bank_nr = '1020'
            valuta = _datum('valuta', heute)
            from finance.booking import buche
            n, summe, gesperrt = 0, Decimal('0.00'), 0
            for r in rechnungen:
                offen = r.offener_betrag
                if offen <= 0:
                    continue
                try:
                    with transaction.atomic():
                        KreditorenZahlung.objects.create(
                            kreditor=r, betrag=offen, datum=valuta,
                            bemerkung=f"Zahllauf {valuta:%d.%m.%Y}"[:255],
                            erstellt_von=request.user)
                        buche('2000', bank_nr, offen,
                              f"Zahlung {r.lieferant} - {r.referenz}"[:255],
                              datum=valuta, liegenschaft=r.liegenschaft,
                              kreditor=r, user=request.user)
                        r.status = 'bezahlt' if r.offener_betrag <= 0 else 'teilbezahlt'
                        r.save(update_fields=['status'])
                    n += 1
                    summe += offen
                except PermissionError:
                    # Nie stillschweigend überspringen — der Lauf gälte sonst
                    # als vollständig verbucht.
                    gesperrt += 1
            log_aktion(request, "Zahllauf verbucht", f"{n} Zahlungen",
                       f"CHF {summe} · Valuta {valuta} · Konto {bank_nr}")
            if n:
                messages.success(request, f"✅ {n} Zahlung(en) über CHF {summe} verbucht "
                                          f"(2000 an {bank_nr}, Valuta {valuta:%d.%m.%Y}).")
            if gesperrt:
                messages.error(request, f"⚠️ {gesperrt} Zahlung(en) nicht verbucht: die "
                                        f"Buchungsperiode ist gesperrt.")
            return redirect(_ziel())

        # --- 3) Auswahl zurück auf «freigegeben» (Lauf nicht ausgeführt) ---
        if aktion == 'zuruecksetzen':
            rechnungen = _auswahl(['in_zahlung'])
            for r in rechnungen:
                r.status = 'freigegeben'
                r.save(update_fields=['status'])
            log_aktion(request, "Zahllauf zurückgesetzt", f"{len(rechnungen)} Rechnungen", '')
            messages.success(request, f"↩︎ {len(rechnungen)} Rechnung(en) wieder freigegeben.")
            return redirect(_ziel())

        return redirect(_ziel())

    # --- GET: Vorschlagsliste ---
    qs = (KreditorenRechnung.objects
          .filter(status__in=['freigegeben', 'in_zahlung'])
          .select_related('liegenschaft')
          .prefetch_related('zahlungen')
          .order_by('faellig_am', 'id'))
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    vorschlag, laufend = [], []
    summe_vorschlag = Decimal('0.00')
    summe_laufend = Decimal('0.00')
    ohne_iban = 0
    for r in qs:
        offen = r.offener_betrag
        zeile = {
            'k': r, 'offen': offen,
            'iban': (r.iban or '').strip(),
            'faellig': r.faellig_am,
            'ueberfaellig': bool(r.faellig_am and r.faellig_am < heute),
            'objekt': (f"{r.liegenschaft.strasse}, {r.liegenschaft.ort}"
                       if r.liegenschaft else '—'),
        }
        if r.status == 'in_zahlung':
            laufend.append(zeile); summe_laufend += offen
        else:
            vorschlag.append(zeile); summe_vorschlag += offen
            if not zeile['iban']:
                ohne_iban += 1

    vw = Verwaltung.objects.first()
    from django.contrib import messages as _msg
    return render(request, 'fw/zahllauf.html', {
        **basis, 'nav': 'kreditoren',
        'vorschlag': vorschlag, 'laufend': laufend,
        'summe_vorschlag': summe_vorschlag, 'summe_laufend': summe_laufend,
        'ohne_iban': ohne_iban, 'heute': heute,
        'verwaltung_iban': ((vw.iban if vw else '') or '').strip(),
        'bankkonten': Buchungskonto.objects.filter(nummer__startswith='10').order_by('nummer'),
        'meldung': list(_msg.get_messages(request)),
    })


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


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_schaden_kosten(request):
    """Reparaturkosten-Übersicht je Liegenschaft: Kostenschätzungen (offen) und
    effektive Kosten aus den Handwerker-Aufträgen — das Reparaturbudget im Blick."""
    from tickets.models import SchadenMeldung, HandwerkerAuftrag
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    try:
        jahr = int(request.GET.get('jahr') or 0)
    except ValueError:
        jahr = 0

    auf = HandwerkerAuftrag.objects.select_related('ticket__liegenschaft', 'handwerker')
    if aktive_lg:
        auf = auf.filter(ticket__liegenschaft=aktive_lg)
    if jahr:
        auf = auf.filter(beauftragt_am__year=jahr)

    gruppen = {}
    for a in auf:
        lg = a.ticket.liegenschaft if a.ticket_id else None
        key = lg.id if lg else 0
        g = gruppen.setdefault(key, {'lg': lg, 'auftraege': 0, 'geschaetzt': Decimal('0.00'),
                                     'effektiv': Decimal('0.00'), 'offen': Decimal('0.00')})
        g['auftraege'] += 1
        gesch = a.kosten_geschaetzt or Decimal('0.00')
        eff = a.kosten_effektiv
        g['geschaetzt'] += gesch
        if eff is not None:
            g['effektiv'] += eff
        else:
            g['offen'] += gesch   # noch nicht abgerechnet → offene Kostenschätzung

    # Schaden-Zähler je Liegenschaft
    schaeden = SchadenMeldung.objects.all()
    if aktive_lg:
        schaeden = schaeden.filter(liegenschaft=aktive_lg)
    if jahr:
        schaeden = schaeden.filter(erstellt_am__year=jahr)
    s_total, s_offen = {}, {}
    for t in schaeden.values('liegenschaft_id', 'status'):
        k = t['liegenschaft_id'] or 0
        s_total[k] = s_total.get(k, 0) + 1
        if t['status'] != 'erledigt':
            s_offen[k] = s_offen.get(k, 0) + 1

    rows = []
    for key, g in gruppen.items():
        g['schaeden'] = s_total.get(key, 0)
        g['schaeden_offen'] = s_offen.get(key, 0)
        g['name'] = f"{g['lg'].strasse}, {g['lg'].ort}" if g['lg'] else '— ohne Liegenschaft —'
        rows.append(g)
    rows.sort(key=lambda g: (-(g['effektiv'] + g['offen']), g['name'].lower()))

    total = {
        'auftraege': sum(g['auftraege'] for g in rows),
        'geschaetzt': sum((g['geschaetzt'] for g in rows), Decimal('0.00')),
        'effektiv': sum((g['effektiv'] for g in rows), Decimal('0.00')),
        'offen': sum((g['offen'] for g in rows), Decimal('0.00')),
        'schaeden': sum(g['schaeden'] for g in rows),
    }
    return render(request, 'fw/schaden_kosten.html', {
        **basis, 'nav': 'schadensfaelle', 'rows': rows, 'total': total,
        'jahr': jahr, 'jahre': list(range(heute.year, heute.year - 5, -1)),
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
    lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
    if not titel or not lg:
        messages.error(request, "Titel und Liegenschaft sind erforderlich.")
        return redirect('fw_schaeden')

    einheit = Einheit.objects.filter(id=request.POST.get('einheit_id') or None).first() if request.POST.get('einheit_id') else None
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
    # Fotos (Mehrfach-Upload) anhängen
    from tickets.models import SchadenFoto
    for f in request.FILES.getlist('fotos'):
        SchadenFoto.objects.create(schaden=t, bild=f, hochgeladen_von=request.user)
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

    fotos = list(t.fotos.all())
    # Raumbuch-Elemente des betroffenen Objekts (zum Verknüpfen)
    from portfolio.models import Ausstattung
    ausstattung_elemente = (list(Ausstattung.objects.filter(einheit=t.betroffene_einheit))
                            if t.betroffene_einheit_id else [])
    tab_liste = [
        ('uebersicht', 'Übersicht', None),
        ('verlauf', 'Verlauf', nachrichten.count() or None),
        ('handwerker', 'Handwerker & Kosten', len(auftraege) or None),
        ('fotos', 'Fotos', len(fotos) or None),
    ]
    from django.contrib import messages
    return render(request, 'fw/schaden_detail.html', {
        **basis, 'nav': 'schadensfaelle', 't': t,
        's_label': s_label, 's_cls': s_cls, 'p_label': p_label, 'p_cls': p_cls,
        'nachrichten': nachrichten, 'auftraege': auftraege, 'melder': melder,
        'kosten_geschaetzt': kosten_geschaetzt, 'kosten_effektiv': kosten_effektiv,
        'fotos': fotos,
        'tab_liste': tab_liste,
        'ausstattung_elemente': ausstattung_elemente,
        'handwerker_liste': handwerker_liste, 'auftrag_vorschlag': auftrag_vorschlag,
        'melder_email': melder_email, 'status_wahl': TICKET_PILL,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_ausstattung(request, pk):
    """Verknüpft eine Schadenmeldung mit einem Raumbuch-Element (oder löst die
    Verknüpfung). Baut die Reparaturhistorie/Lebenszykluskosten am Element auf."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung
    from portfolio.models import Ausstattung
    from core.auth import log_aktion
    t = get_object_or_404(SchadenMeldung, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{t.id}/')
    aid = (request.POST.get('ausstattung_id') or '').strip()
    if aid.isdigit() and t.betroffene_einheit_id:
        el = Ausstattung.objects.filter(id=int(aid), einheit=t.betroffene_einheit).first()
        t.ausstattung = el
        t.save(update_fields=['ausstattung'])
        if el:
            log_aktion(request, "Schaden mit Element verknüpft", f"Ticket #{t.id}", f"{el.raum} · {el.kategorie}")
            messages.success(request, f"✅ Mit «{el.kategorie}» ({el.raum}) verknüpft.")
    else:
        t.ausstattung = None
        t.save(update_fields=['ausstattung'])
        messages.success(request, "Verknüpfung aufgehoben.")
    return redirect(f'/neu/schaeden/{t.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_ersatzplanung(request):
    """Garantie- & Ersatzplanung: Raumbuch-Elemente nach Restnutzungsdauer
    (Lebensdauertabelle), Jahres-Ersatzbudget und Lebenszykluskosten.
    ?pdf=1 → Budget-Report als PDF."""
    from core.services.ersatzplanung import berechne_ersatzplanung, fonds_deckung
    heute = timezone.localdate()
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    daten = berechne_ersatzplanung(aktive_lg=aktive_lg, heute=heute)
    deckung = fonds_deckung(aktive_lg, daten['budget_total'], daten['horizont_jahre'])

    if request.GET.get('pdf') == '1':
        from django.http import HttpResponse
        from crm.models import Verwaltung
        from core.services.ersatzplanung_pdf import generate_ersatzplanung_pdf
        lg_name = (f"{aktive_lg.strasse}, {aktive_lg.ort}" if aktive_lg
                   else "Alle Liegenschaften")
        pdf = generate_ersatzplanung_pdf(daten, lg_name, verwaltung=Verwaltung.objects.first(),
                                         deckung=deckung)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = 'inline; filename="Ersatzplanung.pdf"'
        return resp

    f = request.GET.get('status', '')
    rows = [r for r in daten['rows'] if not f or f == r['status']]

    chips = [('', 'Alle'), ('faellig', 'Ersatz fällig'), ('bald', 'Bald fällig'),
             ('ok', 'Im Nutzungszeitraum'), ('unbekannt', 'Keine Datenbasis')]
    return render(request, 'fw/ersatzplanung.html', {
        **basis, 'nav': 'assets', 'rows': rows, 'status_filter': f, 'chips': chips,
        'n_faellig': daten['n_faellig'], 'n_bald': daten['n_bald'],
        'n_ok': daten['n_ok'], 'n_unbekannt': daten['n_unbekannt'],
        'jahres_budget': daten['jahres_budget'], 'budget_total': daten['budget_total'],
        'horizont_jahre': daten['horizont_jahre'], 'deckung': deckung,
        'anzahl': len(rows),
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_foto_upload(request, pk):
    """Hängt ein oder mehrere Fotos an eine Schadenmeldung (Dokumentation)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung, SchadenFoto
    from core.auth import log_aktion
    from core.utils.uploads import validiere_bild
    t = get_object_or_404(SchadenMeldung, id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/schaeden/{t.id}/')
    dateien = request.FILES.getlist('fotos')
    n = 0
    abgelehnt = 0
    for f in dateien:
        ok, _fehler = validiere_bild(f)
        if not ok:
            abgelehnt += 1
            continue
        SchadenFoto.objects.create(schaden=t, bild=f, hochgeladen_von=request.user)
        n += 1
    if n:
        log_aktion(request, "Schaden-Fotos hochgeladen", f"Ticket #{t.id}", f"{n} Foto(s)")
        messages.success(request, f"✅ {n} Foto(s) hinzugefügt.")
    if abgelehnt:
        messages.error(request, f"{abgelehnt} Datei(en) abgelehnt (kein gültiges Bild oder zu gross).")
    elif not n:
        messages.error(request, "Keine Datei ausgewählt.")
    return redirect(f'/neu/schaeden/{t.id}/#sc-fotos')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_foto_loeschen(request, pk):
    """Entfernt ein einzelnes Schaden-Foto."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenFoto
    from core.auth import log_aktion
    foto = get_object_or_404(SchadenFoto.objects.select_related('schaden'), id=pk)
    tid = foto.schaden_id
    if request.method == 'POST':
        foto.delete()
        log_aktion(request, "Schaden-Foto gelöscht", f"Ticket #{tid}", '')
        messages.success(request, "Foto entfernt.")
    return redirect(f'/neu/schaeden/{tid}/#sc-fotos')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_schaden_loeschen(request, pk):
    """Schadensmeldung (Ticket) löschen — inkl. Fotos/Nachrichten (cascade)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from tickets.models import SchadenMeldung
    from core.auth import log_aktion
    t = get_object_or_404(SchadenMeldung, id=pk)
    if request.method == 'POST':
        titel = t.titel or (t.beschreibung or '')[:40]
        t.delete()
        log_aktion(request, "Schadensmeldung gelöscht", titel, '')
        messages.success(request, "🗑️ Schadensmeldung gelöscht.")
    return redirect('/neu/schaeden/')


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


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_auftrag_pdf(request, pk):
    """Reparaturauftrag (PDF) für einen Handwerker-Auftrag."""
    from django.http import HttpResponse
    from tickets.models import HandwerkerAuftrag
    from crm.models import Verwaltung
    from core.services.handwerker_auftrag_pdf import generate_auftrag_pdf
    a = get_object_or_404(
        HandwerkerAuftrag.objects.select_related('ticket__liegenschaft', 'ticket__betroffene_einheit', 'handwerker'),
        id=pk)
    pdf = generate_auftrag_pdf(a, Verwaltung.objects.first())
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Reparaturauftrag_{a.id}.pdf"'
    return resp


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
        raw = _num(request.POST.get(name))
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
        # Eigentümer aktiv informieren — sonst bemerkt er die Anfrage erst beim
        # nächsten Portal-Login und die Reparatur liegt tagelang auf Eis.
        mandant = getattr(a.ticket.liegenschaft, 'mandant', None) if a.ticket.liegenschaft_id else None
        mail_info = ""
        if mandant and mandant.email:
            from core.utils.email_service import send_ticket_email
            lg = a.ticket.liegenschaft
            kosten_txt = f"CHF {a.kosten_geschaetzt}" if a.kosten_geschaetzt else "noch offen"
            text = (f"Guten Tag {mandant.kontaktperson or mandant.firma_oder_name}\n\n"
                    f"Für Ihre Liegenschaft {lg.strasse}, {lg.plz} {lg.ort} liegt eine Reparatur "
                    f"zur Freigabe bereit:\n\n"
                    f"Schaden: {a.ticket.titel}\n"
                    f"Geschätzte Kosten: {kosten_txt}\n\n"
                    f"Bitte melden Sie sich im Eigentümer-Portal an, um die Reparatur "
                    f"freizugeben oder abzulehnen.\n\nFreundliche Grüsse\nIhre Verwaltung")
            if send_ticket_email(mandant.email, f"Reparaturfreigabe angefragt — {lg.strasse}", text):
                mail_info = f" E-Mail an {mandant.email} gesendet."
        messages.info(request, f"ℹ️ Reparatur zur Freigabe an den Eigentümer weitergeleitet (Portal).{mail_info}")

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
    heute = timezone.localdate()
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

    # Raumbuch portfolioweit — Ausstattung je Objekt (Raum entsteht aus Assets)
    from portfolio.models import Ausstattung
    aqs = (Ausstattung.objects.select_related('einheit__liegenschaft')
           .order_by('einheit__liegenschaft__strasse', 'einheit__bezeichnung', 'raum', 'sortierung'))
    if aktive_lg:
        aqs = aqs.filter(einheit__liegenschaft=aktive_lg)
    ZUSTAND_CLS = {
        'neuwertig': 'bg-emerald-50 text-emerald-700', 'gut': 'bg-emerald-50 text-emerald-700',
        'gebraucht': 'bg-amber-50 text-amber-700', 'defekt': 'bg-rose-50 text-rose-700'}
    # Raumbuch pro Objekt gruppiert (Objekt → Räume → Elemente)
    from collections import OrderedDict
    _obj = OrderedDict()
    ausst_count = 0
    for a in aqs:
        e = a.einheit
        if not e:
            continue
        ausst_count += 1
        entry = _obj.setdefault(e.id, {'einheit': e, 'raeume': OrderedDict(), 'count': 0})
        entry['count'] += 1
        entry['raeume'].setdefault(a.raum, []).append({
            'a': a, 'zustand_cls': ZUSTAND_CLS.get(a.zustand, 'bg-slate-100 text-slate-500'),
        })
    raumbuch_objekte = [{
        'einheit': v['einheit'], 'count': v['count'],
        'raeume': [{'raum': r, 'elemente': els} for r, els in v['raeume'].items()],
    } for v in _obj.values()]

    return render(request, 'fw/assets.html', {
        **basis, 'nav': 'assets', 'rows': rows,
        'g_filter': g_filter, 'garantie_chips': chips, 'q': q,
        'anzahl': len(rows), 'n_aktiv': n_aktiv, 'n_bald': n_bald, 'n_abgelaufen': n_abgelaufen,
        'raumbuch_objekte': raumbuch_objekte, 'ausst_count': ausst_count,
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        'einheiten': Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'),
    })


# ============================================================
# HYPOTHEKEN (Finanzierung je Liegenschaft)
# ============================================================

@rolle_erforderlich(*TEAM_ROLLEN)
def fw_hypotheken(request):
    """Hypotheken je Liegenschaft: Schuld, Zinssatz/-kosten, Ablauf/Fälligkeit.
    Gruppiert nach Liegenschaft (Akkordeon), mit Erfassen/Löschen und
    Ablauf-Warnung für die Refinanzierung."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import Hypothek
    from core.auth import log_aktion, hat_rolle
    heute = timezone.localdate()
    grenze = heute + _timedelta(days=180)
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']

    if request.method == 'POST' and hat_rolle(request.user, SCHREIB_ROLLEN):
        aktion = request.POST.get('aktion')
        if aktion == 'neu':
            lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()

            def _dec(x):
                try:
                    return Decimal(_num(x) or '0')
                except Exception:
                    return Decimal('0.00')

            def _date(x):
                try:
                    return date.fromisoformat(x)
                except Exception:
                    return None
            if lg:
                Hypothek.objects.create(
                    liegenschaft=lg, bank=(request.POST.get('bank') or '').strip(),
                    bezeichnung=(request.POST.get('bezeichnung') or '').strip(),
                    betrag=_dec(request.POST.get('betrag')),
                    zinssatz=_dec(request.POST.get('zinssatz')),
                    typ=request.POST.get('typ') or 'fest',
                    beginn=_date(request.POST.get('beginn')),
                    ablauf=_date(request.POST.get('ablauf')),
                    notiz=(request.POST.get('notiz') or '').strip())
                log_aktion(request, "Hypothek erfasst", lg.strasse, f"CHF {request.POST.get('betrag')}")
                messages.success(request, "✅ Hypothek erfasst.")
            else:
                messages.error(request, "Liegenschaft ist Pflicht.")
        elif aktion == 'loeschen':
            Hypothek.objects.filter(id=request.POST.get('id') or None).delete()
            messages.success(request, "Hypothek gelöscht.")
        return redirect('/neu/hypotheken/' + (f'?lg={aktive_lg.id}' if aktive_lg else ''))

    qs = Hypothek.objects.select_related('liegenschaft').order_by(
        'liegenschaft__strasse', 'ablauf', 'id')
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)

    gruppen = []
    total_schuld = total_zins = Decimal('0.00')
    n_ablaufend = 0
    for hy in qs:
        ablauf_status = 'ok'
        if hy.ablauf:
            if hy.ablauf < heute:
                ablauf_status = 'abgelaufen'; n_ablaufend += 1
            elif hy.ablauf < grenze:
                ablauf_status = 'bald'; n_ablaufend += 1
        total_schuld += hy.betrag
        total_zins += hy.jaehrlicher_zins
        row = {'hy': hy, 'zins': hy.jaehrlicher_zins, 'ablauf_status': ablauf_status}
        if gruppen and gruppen[-1]['lg'].id == hy.liegenschaft_id:
            gruppen[-1]['rows'].append(row)
        else:
            gruppen.append({'lg': hy.liegenschaft, 'rows': [row]})
    for g in gruppen:
        g['schuld'] = sum((r['hy'].betrag for r in g['rows']), Decimal('0.00'))
        g['zins'] = sum((r['zins'] for r in g['rows']), Decimal('0.00'))
        vw = g['lg'].versicherungswert or Decimal('0')
        g['belehnung'] = int((g['schuld'] / vw * 100).to_integral_value()) if vw > 0 else None
    avg_zins = (total_zins / total_schuld * 100).quantize(Decimal('0.001')) if total_schuld > 0 else Decimal('0.000')

    return render(request, 'fw/hypotheken.html', {
        **basis, 'nav': 'hypotheken', 'gruppen': gruppen,
        'total_schuld': total_schuld, 'total_zins': total_zins,
        'avg_zins': avg_zins, 'n_ablaufend': n_ablaufend,
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        'kann_schreiben': hat_rolle(request.user, SCHREIB_ROLLEN),
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
            return Decimal(_num(x) or '0')
        except Exception:
            return Decimal('0.00')

    if request.method == 'POST':
        aktion = request.POST.get('aktion')
        if aktion == 'anlage_neu':
            lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
            try:
                adatum = date.fromisoformat(request.POST.get('anschaffungsdatum'))
            except Exception:
                adatum = heute
            if lg and request.POST.get('bezeichnung', '').strip():
                wert = _dec(request.POST.get('anschaffungswert'))
                anl = Anlage.objects.create(
                    liegenschaft=lg, bezeichnung=request.POST['bezeichnung'].strip(),
                    anschaffungswert=wert,
                    anschaffungsdatum=adatum,
                    nutzungsdauer_jahre=int(request.POST.get('nutzungsdauer_jahre') or 10),
                    restwert=_dec(request.POST.get('restwert')))
                # Aktivierung buchen (Audit K5): ohne Gegenbuchung wurde nur der
                # AfA-Aufwand (6800 an 1500) gebucht → Konto 1500 lief negativ
                # (Aktivum mit Habensaldo, falsche Bilanz). Gegenkonto wählbar:
                # bereits bezahlt (Bank 1020) oder offen (Kreditor 2000).
                gegen_nr = request.POST.get('gegenkonto') or '2000'
                if gegen_nr not in ('1020', '2000'):
                    gegen_nr = '2000'
                # Kein Default 'on' — eine abgewählte Checkbox sendet gar nichts,
                # der Default hätte sie damit unabwählbar gemacht und JEDE Anlage
                # aktiviert (auch eine bereits in Vorjahren aktivierte).
                if wert > 0 and request.POST.get('aktivieren') == 'on':
                    from finance.booking import buche as _buche_a
                    _buche_a('1500', gegen_nr, wert,
                             f"Aktivierung Anlage: {anl.bezeichnung}",
                             datum=adatum, liegenschaft=lg, user=request.user)
                    messages.success(request, f"✅ Anlage erfasst und aktiviert "
                                              f"(1500 an {gegen_nr}, CHF {wert}).")
                else:
                    messages.success(request, "✅ Anlage erfasst (ohne Aktivierungsbuchung).")
            else:
                messages.error(request, "Bezeichnung und Liegenschaft sind Pflicht.")
        elif aktion == 'afa_lauf':
            jahr = int(request.POST.get('jahr') or heute.year)
            n, summe = run_abschreibungen(jahr, user=request.user)
            log_aktion(request, "AfA-Lauf", str(jahr), f"{n} Abschreibungen, CHF {summe}")
            messages.success(request, f"✅ AfA-Lauf {jahr}: {n} Abschreibung(en) gebucht (CHF {summe})." if n
                             else f"AfA-Lauf {jahr}: nichts zu buchen (bereits erledigt oder keine Anlagen).")
        elif aktion == 'fonds_set':
            lg = Liegenschaft.objects.filter(id=request.POST.get('liegenschaft_id') or None).first()
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

def _ist_abgeschlossen(jahr, liegenschaft=None):
    from core.services.jahresabschluss import ist_abgeschlossen
    return ist_abgeschlossen(jahr, liegenschaft)


def _erfolg_bilanz(aktive_lg, jahr):
    """Erfolgsrechnung + Bilanz für ein Geschäftsjahr (oder 'alle').

    Ausgelagert, weil die Seite /neu/buchhaltung/ UND ihr PDF-Abzug exakt
    dieselben Zahlen zeigen müssen. Zwei Kopien dieser Rechnung würden
    auseinanderdriften — und ein Abschluss, der je nach Ausgabeweg anders
    aussieht, ist wertlos.
    """
    from finance.models import Buchung, Buchungskonto
    qs = Buchung.objects.all()
    if aktive_lg:
        qs = qs.filter(liegenschaft=aktive_lg)
    if jahr != 'alle':
        qs = qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))

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

    # Abschlussbuchungen aus der ERFOLGSRECHNUNG ausklammern — sie saldieren die
    # Erfolgskonten per 31.12. gegen 2970. Ohne diesen Ausschluss zeigte die
    # Erfolgsrechnung nach dem Jahresabschluss überall null, obwohl das Jahr
    # gelaufen ist (Audit). Die Bilanz braucht sie dagegen, weil erst sie das
    # Ergebnis auf 2970 stellt — bilanz_qs bleibt deshalb unangetastet.
    from core.services.jahresabschluss import abschluss_buchungen_q
    qs = qs.exclude(abschluss_buchungen_q())

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
        else:  # bilanz / aktiv / passiv — kumulativ bis Jahresende
            soll = bilanz_qs.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            haben = bilanz_qs.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
            saldo = soll - haben  # Sollsaldo: >0 tendenziell Aktivum, <0 Passivum
            if saldo == 0:
                continue
            if k.typ == 'aktiv':
                # Immer Aktivseite (Soll−Haben) — auch bei negativem Saldo sichtbar.
                aktiven.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': saldo})
                total_aktiven += saldo
            elif k.typ == 'passiv':
                # Immer Passivseite (Haben−Soll). Ein Soll-Saldo (z.B. Ausschüttung
                # via Kontokorrent) MINDERT das Eigenkapital → negative Passivzeile.
                passiven.append({'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': -saldo})
                total_passiven += -saldo
            elif saldo > 0:
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
    return {
        'ertraege': ertraege, 'aufwaende': aufwaende,
        'total_ertrag': total_ertrag, 'total_aufwand': total_aufwand, 'erfolg': erfolg,
        'aktiven': aktiven, 'passiven': passiven,
        'total_aktiven': total_aktiven, 'total_passiven': total_passiven,
        'passiven_mit_erfolg': passiven_mit_erfolg, 'bilanz_differenz': bilanz_differenz,
        'kum_erfolg': kum_erfolg, 'erfolg_vortrag': erfolg_vortrag,
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_buchhaltung(request):
    from finance.models import Buchung, Buchungskonto
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    # --- Jahresabschluss buchen (Erfolgskonten an 2970) — Audit W4 ---
    if request.method == 'POST' and request.POST.get('aktion') == 'jahresabschluss':
        from django.shortcuts import redirect
        from django.contrib import messages
        from core.services.jahresabschluss import buche_jahresabschluss, ist_abgeschlossen
        from core.auth import log_aktion
        try:
            j_ab = int(request.POST.get('jahr') or heute.year)
        except ValueError:
            j_ab = heute.year
        if not (2000 <= j_ab <= 2100):
            messages.error(request, "Ungültiges Geschäftsjahr.")
            return redirect(f'/neu/buchhaltung/?jahr={heute.year}')
        if ist_abgeschlossen(j_ab, aktive_lg):
            messages.info(request, f"Das Geschäftsjahr {j_ab} ist bereits abgeschlossen.")
            return redirect(f'/neu/buchhaltung/?jahr={j_ab}')
        try:
            n_ab, erg = buche_jahresabschluss(j_ab, liegenschaft=aktive_lg, user=request.user)
        except PermissionError as exc:
            messages.error(request, f"❌ {exc}")
            return redirect(f'/neu/buchhaltung/?jahr={j_ab}')
        except Exception as exc:
            messages.error(request, f"❌ Jahresabschluss fehlgeschlagen: {exc}")
            return redirect(f'/neu/buchhaltung/?jahr={j_ab}')
        log_aktion(request, "Jahresabschluss gebucht", str(j_ab),
                   f"{n_ab} Konten, Ergebnis CHF {erg}")
        gesperrt_hinweis = ""
        if n_ab and not aktive_lg:
            # Periode versiegeln: Ohne Sperre liessen sich nach dem Abschluss
            # weiter Erfolgsbuchungen ins geschlossene Jahr schreiben, die nie
            # mehr saldiert würden — Bilanz und Erfolgsrechnung liefen
            # auseinander (Audit). Nur beim portfolioweiten Abschluss, ein
            # Einzelabschluss sperrt die übrigen Liegenschaften nicht mit.
            from crm.models import Verwaltung
            vw_sperre = Verwaltung.objects.first()
            if vw_sperre is not None:
                stichtag = date(j_ab, 12, 31)
                if not vw_sperre.buchung_gesperrt_bis or vw_sperre.buchung_gesperrt_bis < stichtag:
                    vw_sperre.buchung_gesperrt_bis = stichtag
                    vw_sperre.save(update_fields=['buchung_gesperrt_bis'])
                    gesperrt_hinweis = (f" Die Periode bis 31.12.{j_ab} ist jetzt für "
                                        f"Buchungen gesperrt.")
        if n_ab:
            art = "Gewinn" if erg >= 0 else "Verlust"
            messages.success(request, f"✅ Jahresabschluss {j_ab} gebucht: {n_ab} Erfolgskonto/-konten "
                                      f"gegen 2970 saldiert · {art} CHF {abs(erg)}.{gesperrt_hinweis}")
        else:
            messages.info(request, f"Jahr {j_ab}: keine Erfolgsbuchungen zum Abschliessen.")
        return redirect(f'/neu/buchhaltung/?jahr={j_ab}')

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

    # Erfolgsrechnung + Bilanz kommen aus EINER Quelle (siehe _erfolg_bilanz) —
    # die Seite und ihr PDF-Abzug dürfen nie unterschiedliche Zahlen zeigen.
    _eb = _erfolg_bilanz(aktive_lg, jahr)
    ertraege = _eb['ertraege']; aufwaende = _eb['aufwaende']
    total_ertrag = _eb['total_ertrag']; total_aufwand = _eb['total_aufwand']
    erfolg = _eb['erfolg']
    aktiven = _eb['aktiven']; passiven = _eb['passiven']
    total_aktiven = _eb['total_aktiven']; total_passiven = _eb['total_passiven']
    passiven_mit_erfolg = _eb['passiven_mit_erfolg']
    bilanz_differenz = _eb['bilanz_differenz']
    kum_erfolg = _eb['kum_erfolg']; erfolg_vortrag = _eb['erfolg_vortrag']

    # --- BUCHUNGSJOURNAL (durchsuch- und filterbar, seitenweise) ---
    # Vorher: hart die letzten 60 Zeilen, ohne Suche und ohne Filter. Damit war
    # der Alltag eines Buchhalters — einen Beleg wiederfinden, einen Monat
    # durchsehen, ein Konto kontrollieren — schlicht nicht möglich (Audit).
    # Die Abschlussbuchungen sind hier bewusst wieder drin: im JOURNAL müssen
    # sie sichtbar sein, nur aus der Erfolgsrechnung sind sie ausgeklammert.
    from django.db.models import Q as _QJ
    j_qs = Buchung.objects.all()
    if aktive_lg:
        j_qs = j_qs.filter(liegenschaft=aktive_lg)
    j_von = (request.GET.get('von') or '').strip()
    j_bis = (request.GET.get('bis') or '').strip()
    j_konto = (request.GET.get('konto') or '').strip()
    j_suche = (request.GET.get('q') or '').strip()
    if j_von:
        try:
            j_qs = j_qs.filter(datum__gte=date.fromisoformat(j_von))
        except ValueError:
            j_von = ''
    if j_bis:
        try:
            j_qs = j_qs.filter(datum__lte=date.fromisoformat(j_bis))
        except ValueError:
            j_bis = ''
    if not (j_von or j_bis) and jahr != 'alle':
        # Ohne eigene Datumswahl gilt der Jahresfilter der Seite.
        j_qs = j_qs.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
    if j_konto:
        j_qs = j_qs.filter(_QJ(soll_konto__nummer=j_konto) | _QJ(haben_konto__nummer=j_konto))
    if j_suche:
        # Belegtext ODER Beleg-Nr. Letztere ist numerisch — nur wenn die Eingabe
        # eine Zahl ist (auch mit führendem #), wird sie als Nummer gesucht.
        such_q = _QJ(beleg_text__icontains=j_suche)
        _nr = j_suche.lstrip('#').strip()
        if _nr.isdigit():
            such_q = such_q | _QJ(beleg_nr=int(_nr))
        j_qs = j_qs.filter(such_q)
    j_qs = j_qs.select_related('soll_konto', 'haben_konto', 'liegenschaft').order_by('-datum', '-id')
    j_total = j_qs.count()
    j_summe = j_qs.aggregate(s=Sum('betrag'))['s'] or Decimal('0.00')
    try:
        j_seite = max(1, int(request.GET.get('seite') or 1))
    except ValueError:
        j_seite = 1
    J_PRO_SEITE = 100
    j_seiten = max(1, (j_total + J_PRO_SEITE - 1) // J_PRO_SEITE)
    j_seite = min(j_seite, j_seiten)
    journal = j_qs[(j_seite - 1) * J_PRO_SEITE: j_seite * J_PRO_SEITE]
    # Filter beim Blättern erhalten (ohne `seite`, die wird pro Link gesetzt).
    j_query = '&'.join(
        f"{k}={v}" for k, v in (('von', j_von), ('bis', j_bis), ('konto', j_konto), ('q', j_suche))
        if v)

    tab_liste = [
        ('erfolg', 'Erfolgsrechnung', None),
        ('bilanz', 'Bilanz', None),
        ('journal', 'Journal', j_total or None),
    ]

    # Werte des zuletzt erfassten Belegs (Serienerfassung)
    _letzt = request.session.get('bu_letzt') or {}
    _letzt_datum = None
    if _letzt.get('datum'):
        try:
            _letzt_datum = date.fromisoformat(_letzt['datum'])
        except ValueError:
            _letzt_datum = None
    return render(request, 'fw/buchhaltung.html', {
        **basis, 'nav': 'buchhaltung',
        'ertraege': ertraege, 'aufwaende': aufwaende,
        'total_ertrag': total_ertrag, 'total_aufwand': total_aufwand, 'erfolg': erfolg,
        'aktiven': aktiven, 'passiven': passiven,
        'total_aktiven': total_aktiven, 'total_passiven': total_passiven,
        'passiven_mit_erfolg': passiven_mit_erfolg, 'bilanz_differenz': bilanz_differenz,
        'kum_erfolg': kum_erfolg, 'erfolg_vortrag': erfolg_vortrag,
        'journal': journal,
        'j_total': j_total, 'j_summe': j_summe, 'j_seite': j_seite, 'j_seiten': j_seiten,
        'j_von': j_von, 'j_bis': j_bis, 'j_konto': j_konto, 'j_suche': j_suche,
        'j_query': j_query,
        'tab_liste': tab_liste,
        'jahr': jahr, 'jahre': list(range(heute.year, heute.year - 5, -1)),
        'alle_konten': Buchungskonto.objects.all().order_by('nummer'),
        'liegenschaften': Liegenschaft.objects.order_by('strasse'),
        # Vorbelegung der Erfassungsmaske aus dem letzten Beleg (Serienerfassung).
        'serienerfassung': bool(request.session.pop('bu_serie', False)),
        'letztes_datum': _letzt_datum, 'letztes_soll': _letzt.get('soll', ''),
        'letztes_haben': _letzt.get('haben', ''), 'letzte_lg_id': _letzt.get('lg'),
        'jahr_abgeschlossen': (_ist_abgeschlossen(jahr, aktive_lg)
                               if isinstance(jahr, int) else False),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kontenplan(request):
    """Kontenplan mit SALDENLISTE und Pflege der Konten.

    Zwei Lücken auf einmal (Audit): Es gab weder eine Saldenliste — das Werkzeug,
    mit dem ein Buchhalter jeden Abschluss beginnt — noch eine Möglichkeit, im
    neuen UI ein Konto anzulegen oder umzubenennen. Der Hinweis in der
    Buchungsmaske verwies auf einen «Kontenplan-Tab», den es nicht gab; der
    Kontenrahmen war faktisch eine Python-Liste.

    Anders als Bilanz und Erfolgsrechnung blendet die Saldenliste Konten mit
    Saldo 0 NICHT aus — sonst sind bebuchte, aber ausgeglichene Konten (z.B. ein
    geleertes Durchlaufkonto) im ganzen UI unerreichbar.
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.db.models import Sum
    from finance.models import Buchungskonto, Buchung
    from core.auth import log_aktion, hat_rolle, VERWALTUNGS_ROLLEN

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    kann_schreiben = hat_rolle(request.user, VERWALTUNGS_ROLLEN)

    if request.method == 'POST' and kann_schreiben:
        aktion = request.POST.get('aktion')
        nr = (request.POST.get('nummer') or '').strip()
        bez = (request.POST.get('bezeichnung') or '').strip()
        typ = request.POST.get('typ') or 'bilanz'
        if aktion == 'neu':
            if not nr or not bez:
                messages.error(request, "Nummer und Bezeichnung sind Pflicht.")
            elif Buchungskonto.objects.filter(nummer=nr).exists():
                messages.error(request, f"Konto {nr} existiert bereits.")
            elif typ not in ('aufwand', 'ertrag', 'bilanz', 'aktiv', 'passiv'):
                messages.error(request, "Ungültiger Kontotyp.")
            else:
                Buchungskonto.objects.create(
                    nummer=nr, bezeichnung=bez, typ=typ,
                    is_hnk_relevant=(request.POST.get('hnk') == 'on'),
                    standard_verteilschluessel=(request.POST.get('schluessel') or 'm2'))
                log_aktion(request, "Konto angelegt", f"{nr} {bez}", typ)
                messages.success(request, f"✅ Konto {nr} «{bez}» angelegt.")
        elif aktion == 'bearbeiten':
            k = Buchungskonto.objects.filter(id=request.POST.get('konto_id') or None).first()
            if not k:
                messages.error(request, "Konto nicht gefunden.")
            else:
                # Die NUMMER bleibt unveränderlich: sie steckt in Belegtexten,
                # Exporten und im Buchungscode. Umbenennen ja, umnummerieren nein.
                k.bezeichnung = bez or k.bezeichnung
                if typ in ('aufwand', 'ertrag', 'bilanz', 'aktiv', 'passiv'):
                    k.typ = typ
                k.is_hnk_relevant = (request.POST.get('hnk') == 'on')
                if request.POST.get('schluessel'):
                    k.standard_verteilschluessel = request.POST['schluessel']
                k.save()
                log_aktion(request, "Konto geändert", f"{k.nummer} {k.bezeichnung}", k.typ)
                messages.success(request, f"✅ Konto {k.nummer} aktualisiert.")
        return redirect(f'/neu/kontenplan/{basis["lg_query"]}')

    # --- Saldenliste ---
    jahr_param = request.GET.get('jahr', str(heute.year))
    try:
        jahr = int(jahr_param)
    except ValueError:
        jahr = heute.year
    bqs = Buchung.objects.filter(datum__gte=date(jahr, 1, 1), datum__lte=date(jahr, 12, 31))
    if aktive_lg:
        bqs = bqs.filter(liegenschaft=aktive_lg)
    soll_map = {r['soll_konto']: r['t'] for r in
                bqs.values('soll_konto').annotate(t=Sum('betrag'))}
    haben_map = {r['haben_konto']: r['t'] for r in
                 bqs.values('haben_konto').annotate(t=Sum('betrag'))}

    zeilen, t_soll, t_haben = [], Decimal('0.00'), Decimal('0.00')
    for k in Buchungskonto.objects.all().order_by('nummer'):
        s = soll_map.get(k.id) or Decimal('0.00')
        h = haben_map.get(k.id) or Decimal('0.00')
        zeilen.append({'k': k, 'soll': s, 'haben': h, 'saldo': s - h,
                       'bewegt': bool(s or h)})
        t_soll += s
        t_haben += h

    return render(request, 'fw/kontenplan.html', {
        **basis, 'nav': 'buchhaltung', 'zeilen': zeilen,
        'total_soll': t_soll, 'total_haben': t_haben,
        'differenz': t_soll - t_haben,
        'jahr': jahr, 'jahre': list(range(heute.year, heute.year - 5, -1)),
        'kann_schreiben': kann_schreiben,
        'typen': [('bilanz', 'Bilanz'), ('aktiv', 'Aktivum'), ('passiv', 'Passivum / Eigenkapital'),
                  ('aufwand', 'Aufwand'), ('ertrag', 'Ertrag')],
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kontoblatt(request, nummer):
    """Kontoauszug/Kontoblatt eines Kontos: alle Buchungen mit laufendem Saldo.
    Bilanzkonten kumulativ (mit Eröffnungssaldo aus Vorjahren)."""
    from finance.models import Buchung, Buchungskonto
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
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

    ist_bilanz = konto.typ in ('bilanz', 'aktiv', 'passiv')
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
def fw_buchhaltung_pdf(request):
    """Erfolgsrechnung und Bilanz als PDF.

    Der Berichte-Hub versprach für «Erfolgsrechnung & Bilanz» ein PDF, es gab
    aber nur den CSV-Journal-Export. Für die Übergabe ans Treuhandbüro und die
    Ablage beim Eigentümer braucht es den Abschluss auf Papier.
    """
    from django.http import HttpResponse
    from core.services.abschluss_pdf import generate_abschluss_pdf
    from crm.models import Verwaltung

    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    jahr_param = request.GET.get('jahr', str(heute.year))
    if jahr_param == 'alle':
        jahr = 'alle'
    else:
        try:
            jahr = int(jahr_param)
        except ValueError:
            jahr = heute.year

    daten = _erfolg_bilanz(aktive_lg, jahr)
    lg_name = f"{aktive_lg.strasse}, {aktive_lg.ort}" if aktive_lg else "Gesamtes Portfolio"
    pdf = generate_abschluss_pdf(daten, jahr, lg_name,
                                 verwaltung=Verwaltung.objects.first(), erstellt_am=heute)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="Erfolgsrechnung_Bilanz_{jahr}.pdf"'
    return resp


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_buchhaltung_export(request):
    """Exportiert das Buchungsjournal des Jahres als CSV (Treuhänder-Handover)."""
    import csv
    from django.http import HttpResponse
    from finance.models import Buchung
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
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
    heute = timezone.localdate()
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


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_eigentuemer_kontokorrent(request, pk):
    """Kontokorrent Eigentümer (on-screen): Ergebnis der Liegenschaften −
    Auszahlungen = offener Saldo. Einstieg zum Erfassen einer Auszahlung."""
    from crm.models import Mandant
    from core.services.eigentuemer_kontokorrent import kontokorrent
    from finance.models import Buchungskonto
    md = get_object_or_404(Mandant, id=pk)
    basis = _global_filter(request)
    heute = timezone.localdate()
    jahr_param = request.GET.get('jahr', '')
    jahr = None
    if jahr_param and jahr_param != 'alle':
        try:
            jahr = int(jahr_param)
        except ValueError:
            jahr = None

    if request.GET.get('pdf') == '1':
        from crm.models import Verwaltung
        from core.services.eigentuemer_kontokorrent import generate_kontokorrent_pdf
        from django.http import HttpResponse
        pdf = generate_kontokorrent_pdf(md, jahr, Verwaltung.objects.first())
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Kontokorrent_{md.firma_oder_name}_{jahr or "alle"}.pdf"'
        return resp

    kk = kontokorrent(md, jahr=jahr)
    bankkonten = list(Buchungskonto.objects.filter(nummer__in=['1020', '1015']).order_by('nummer'))

    # Verwaltungshonorar-Vorschau nur bei gewähltem Geschäftsjahr (Honorar wird
    # je Jahr gebucht). Ohne Jahr (kumuliert) keine Buchung anbieten.
    honorar = None
    if jahr and (md.honorar_prozent or Decimal('0')) > 0:
        from core.services.verwaltungshonorar import honorar_vorschau
        h_zeilen, h_total, h_prozent = honorar_vorschau(md, jahr)
        honorar = {'zeilen': h_zeilen, 'total': h_total, 'prozent': h_prozent,
                   'offen_n': sum(1 for z in h_zeilen if not z['gebucht'] and z['honorar'] > 0)}

    from django.contrib import messages
    return render(request, 'fw/eigentuemer_kontokorrent.html', {
        **basis, 'nav': 'mandate', 'md': md, 'kk': kk, 'honorar': honorar,
        'jahr': jahr, 'jahr_param': jahr_param,
        'jahre': list(range(heute.year, heute.year - 5, -1)),
        'bankkonten': bankkonten, 'heute': heute,
        'meldung': list(messages.get_messages(request)),
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_eigentuemer_honorar(request, pk):
    """Bucht das Verwaltungshonorar (Soll 4500 / Haben Bank) je Liegenschaft
    für das gewählte Geschäftsjahr. Idempotent."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mandant
    from core.services.verwaltungshonorar import buche_honorar
    from core.auth import log_aktion
    md = get_object_or_404(Mandant, id=pk)
    if request.method != 'POST':
        return redirect('fw_eigentuemer_kontokorrent', pk=md.id)
    try:
        jahr = int(request.POST.get('jahr') or 0)
    except ValueError:
        jahr = 0
    if not jahr:
        messages.error(request, "Kein Geschäftsjahr gewählt.")
        return redirect(f'/neu/mandate/{md.id}/kontokorrent/')
    # Gegenkonto: Eigentümer-Kontokorrent (kein Geldfluss am 31.12.) — siehe W3.
    # Whitelist, sonst liesse sich per POST ein beliebiges Konto ansteuern.
    gegen = request.POST.get('konto_nummer') or '2850'
    if gegen not in ('2850', '1020'):
        gegen = '2850'
    try:
        anzahl, summe = buche_honorar(md, jahr, gegen_nummer=gegen, user=request.user)
    except PermissionError as e:
        messages.error(request, str(e))
        return redirect(f'/neu/mandate/{md.id}/kontokorrent/?jahr={jahr}')
    if anzahl:
        log_aktion(request, "Verwaltungshonorar gebucht", md.firma_oder_name,
                   f"{jahr} · {anzahl} Liegenschaft(en) · CHF {summe}")
        messages.success(request, f"✅ Verwaltungshonorar {jahr} verbucht: CHF {summe} "
                                  f"über {anzahl} Liegenschaft(en) (Soll 4500 / Haben {gegen}).")
    else:
        messages.warning(request, "Kein Honorar zu buchen (bereits gebucht oder kein Mietertrag).")
    return redirect(f'/neu/mandate/{md.id}/kontokorrent/?jahr={jahr}')


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_eigentuemer_auszahlung(request, pk):
    """Erfasst eine Auszahlung an den Eigentümer und bucht sie:
    Soll 2850 (Kontokorrent Eigentümer) / Haben Bank."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mandant
    from finance.models import Buchungskonto, EigentuemerAuszahlung
    from finance.booking import buche, konto as _konto
    from core.auth import log_aktion
    md = get_object_or_404(Mandant, id=pk)
    if request.method != 'POST':
        return redirect('fw_eigentuemer_kontokorrent', pk=md.id)
    try:
        betrag = Decimal((_num(request.POST.get('betrag')) or '0')).quantize(Decimal('0.01'))
    except Exception:
        betrag = Decimal('0')
    if betrag <= 0:
        messages.error(request, "Betrag muss grösser als 0 sein.")
        return redirect('fw_eigentuemer_kontokorrent', pk=md.id)
    try:
        datum = date.fromisoformat(request.POST['datum']) if request.POST.get('datum') else timezone.localdate()
    except ValueError:
        datum = timezone.localdate()
    bank = Buchungskonto.objects.filter(nummer=request.POST.get('konto_nummer') or '1020').first() or _konto('1020')
    bemerkung = (request.POST.get('bemerkung') or '').strip()

    try:
        buchung = buche('2850', bank, betrag,
                        f"Auszahlung Eigentümer {md.firma_oder_name}" + (f" — {bemerkung}" if bemerkung else ""),
                        datum=datum, user=request.user)
    except PermissionError as e:
        messages.error(request, str(e))
        return redirect('fw_eigentuemer_kontokorrent', pk=md.id)

    EigentuemerAuszahlung.objects.create(
        mandant=md, betrag=betrag, datum=datum, konto=bank,
        bemerkung=bemerkung, erstellt_von=request.user)
    log_aktion(request, "Eigentümer-Auszahlung", md.firma_oder_name,
               f"CHF {betrag} ab {bank.nummer} · Beleg #{buchung.beleg_nr if buchung else '—'}")
    messages.success(request, f"✅ Auszahlung CHF {betrag} an {md.firma_oder_name} verbucht (Soll 2850 / Haben {bank.nummer}).")
    return redirect('fw_eigentuemer_kontokorrent', pk=md.id)


# ============================================================
# ETAPPE D: SOLLSTELLUNG MIETE (monatlicher Mietenlauf)
# ============================================================

import calendar as _calendar


def _sollstellung_kontext(request):
    """Vorschau: aktive Verträge + Soll je Vertrag für den gewählten Monat."""
    heute = timezone.localdate()
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
        # Wie im tatsächlichen Lauf (run_sollstellung) die VERRECHNETEN Werte nutzen
        # (Staffel/Index/Gratismonat/Komponenten berücksichtigt) — sonst weicht die
        # Vorschau-Summe vom real gestellten Debitor ab.
        netto = round((v.verrechneter_netto_mietzins(start_date) or Decimal('0')) * faktor, 2)
        nk = round((v.verrechnete_nebenkosten(start_date) or Decimal('0')) * faktor, 2)
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

    heute = timezone.localdate()
    try:
        jahr = int(request.POST.get('jahr') or heute.year)
        monat = int(request.POST.get('monat') or heute.month)
    except ValueError:
        jahr, monat = heute.year, heute.month
    # Bereichs-Validierung: Monat 13 / Jahr 20260 crashte sonst mit HTTP 500
    # tief in run_sollstellung (date(jahr, 13, 1)).
    if not (1 <= monat <= 12) or not (2000 <= jahr <= 2100):
        messages.error(request, f"Ungültiger Monat {monat:02d}/{jahr} — bitte Monat 1–12 wählen.")
        return redirect('fw_sollstellung')

    titel = f"Miete & NK {monat:02d}/{jahr}"
    # Der Lauf muss demselben Liegenschaftsfilter folgen wie die Vorschau darüber
    # — sonst stellt ein Klick auf «Sollstellung starten» dem ganzen Portfolio
    # Rechnung, obwohl der Dialog die gefilterte Anzahl nannte (Praxis-Audit).
    # `lg` kommt beim POST aus dem Formular-Feld (_global_filter liest nur GET).
    lauf_lg = Liegenschaft.objects.filter(id=request.POST.get('lg') or None).first()
    from core.services.automation import run_sollstellung
    try:
        erstellt = run_sollstellung(jahr, monat, user=request.user, liegenschaft=lauf_lg)
    except RuntimeError as e:
        messages.error(request, f"{e}")
        return redirect(f'/neu/sollstellung/?jahr={jahr}&monat={monat}')

    log_aktion(request, "Sollstellung ausgeführt", titel,
               f"{erstellt} Rechnungen erstellt"
               + (f" · nur {lauf_lg.strasse}" if lauf_lg else " · ganzes Portfolio"))
    umfang = f" ({lauf_lg.strasse})" if lauf_lg else ""
    if erstellt:
        messages.success(request, f"✅ Sollstellung {titel}{umfang}: {erstellt} Rechnung(en) erstellt.")
    else:
        messages.success(request, f"Sollstellung {titel}{umfang}: alles bereits gestellt — "
                                  f"nichts Neues erzeugt.")
    ziel = f'/neu/sollstellung/?jahr={jahr}&monat={monat}'
    if lauf_lg:
        ziel += f'&lg={lauf_lg.id}'
    return redirect(ziel)


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

    heute = timezone.localdate()
    n_nach = n_gut = 0
    with transaction.atomic():
        # Zeilensperre + Re-Check gegen Doppelklick-Race: der p.abgeschlossen-Check
        # oben läuft ohne Lock — zwei parallele Requests würden sonst beide buchen
        # (doppelte NK-Nachzahlungsdebitoren + Buchungen).
        p = AbrechnungsPeriode.objects.select_for_update().get(id=p.id)
        if p.abgeschlossen:
            messages.error(request, "Diese Periode ist bereits abgeschlossen und verbucht.")
            return redirect(f'/neu/nebenkosten/{p.id}/')
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
            else:  # Guthaben → als ECHTES Mieterguthaben führen (Audit-Befund W1):
                # 3020 an 2030 (Verbindlichkeit gegenüber Mieter) statt 3020/1100 —
                # 1100 wurde sonst ohne Nebenbuch-Beleg entlastet und das Guthaben
                # war nirgends sichtbar. Der Zahlungseingang (Konto 2030) erscheint
                # im Mieterkonto als Haben und kann dort mit einer offenen
                # Rechnung verrechnet oder ausbezahlt werden.
                konto_2030 = _konto("2030")
                buche("3020", "2030", abs(saldo), f"NK-Gutschrift {v.mieter} - {p.bezeichnung}",
                      datum=heute, liegenschaft=v.einheit.liegenschaft, user=request.user)
                Zahlungseingang.objects.create(
                    vertrag=v, betrag=abs(saldo), datum_eingang=heute,
                    buchungs_monat=heute.replace(day=1),
                    bemerkung=f"NK-Gutschrift {p.bezeichnung} (Guthaben Mieter)",
                    konto=konto_2030, liegenschaft=v.einheit.liegenschaft,
                    erstellt_von=request.user, status='verbucht')
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
        neu = _num(request.POST.get(f'akonto_{vid}'))
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
    heute = timezone.localdate()

    vw = Verwaltung.objects.first()
    curr_zins = vw.aktueller_referenzzinssatz if vw else None
    curr_lik = vw.aktueller_lik_punkte if vw else None

    # N+1 vermeiden: alle datierten Relationen vorladen, damit die Mietzins-Methoden
    # (effektive_basis / effektiver_netto_mietzins / _sollmietzins_zeile) den
    # Prefetch-Cache nutzen statt pro Vertrag zu queryen.
    qs = (Mietvertrag.objects.filter(status='aktiv')
          .select_related('mieter', 'einheit__liegenschaft')
          .prefetch_related('anpassungen', 'staffelstufen',
                            'mietzins_komponenten', 'einheit__sollmietzinse')
          .order_by('einheit__liegenschaft__strasse'))
    if aktive_lg:
        qs = qs.filter(einheit__liegenschaft=aktive_lg)

    pot_filter = request.GET.get('potenzial', '')
    # Verwaltung genau EINMAL laden (statt pro Vertrag via v.mietzinspotenzial).
    curr_zins_vw = vw.aktueller_referenzzinssatz if vw else None
    curr_lik_vw = vw.aktueller_lik_punkte if vw else None

    def _potenzial(v):
        if curr_zins_vw is None:
            return 'neutral'
        basis_zins, basis_lik = v.effektive_basis(heute)
        if curr_zins_vw < basis_zins:
            return 'decrease'
        if curr_zins_vw > basis_zins:
            return 'increase'
        if curr_lik_vw is not None and curr_lik_vw > (basis_lik + Decimal('1.5')):
            return 'increase'
        return 'neutral'

    rows = []
    n_inc = n_dec = 0
    for v in qs:
        pot = _potenzial(v)
        if pot == 'increase':
            n_inc += 1
        elif pot == 'decrease':
            n_dec += 1
        if pot_filter and pot_filter != pot:
            continue
        label, cls, icon = POTENZIAL_PILL.get(pot, POTENZIAL_PILL['neutral'])
        letzte = list(v.anpassungen.all())
        letzte_anpassung = max((a.wirksam_ab for a in letzte), default=None)
        # EFFEKTIVE Werte zeigen (wirksame Anpassungen + Staffelstufen) — nicht
        # die eingefrorene Vertragsbasis. Sonst stimmen die Zahlen hier nicht mit
        # den tatsächlich verrechneten/erfassten Mietzinsen überein.
        eff_zins, eff_lik = v.effektive_basis(heute)
        rows.append({
            'v': v, 'mieter': v.mieter.display_name,
            'objekt': f"{v.einheit.liegenschaft.strasse} · {v.einheit.bezeichnung}",
            'netto': v.effektiver_netto_mietzins(heute) or Decimal('0'),
            'basis_zins': eff_zins, 'basis_lik': eff_lik,
            'pot': pot, 'pot_label': label, 'pot_cls': cls, 'pot_icon': icon,
            'letzte_anpassung': letzte_anpassung,
            'anpassungen': len(letzte),
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
            return Decimal(_num(x))
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
            wirksam_ab = naechster_anpassungstermin(v, timezone.localdate())
        begruendung = (request.POST.get('begruendung') or '').strip()
        mit_vorbehalt = request.POST.get('mit_vorbehalt') == 'on'
        vorbehalt_text = (request.POST.get('vorbehalt_text') or '').strip()

        # Server-seitige Fristenkontrolle (Art. 269d OR): eine Mietzinserhöhung darf
        # frühestens auf den nächsten ordentlichen Kündigungstermin nach Ablauf der
        # 10-tägigen Ankündigungsfrist wirksam werden. Ein zu frühes Datum (Client
        # manipuliert / Tippfehler) würde ein rechtlich anfechtbares Formular erzeugen.
        if neu_netto > (v.netto_mietzins or Decimal('0')):
            frueh = naechster_anpassungstermin(v, timezone.localdate())
            if wirksam_ab < frueh:
                messages.error(request, f"❌ Wirksamkeitsdatum zu früh: Eine Mietzinserhöhung kann "
                                        f"frühestens auf {frueh.strftime('%d.%m.%Y')} wirksam werden "
                                        f"(Kündigungsfrist + 10-Tage-Ankündigung, Art. 269d OR).")
                return redirect(f'/neu/mietzins/{v.id}/anpassung/')

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

        # Idempotent pro (Vertrag, wirksam_ab, neuer Mietzins): Mehrfaches Generieren
        # des PDF (Vorschau) darf keine Duplikate der Anpassung + Anfechtungs-Pendenz
        # erzeugen. Nur beim erstmaligen Erfassen werden Pendenz + Log geschrieben.
        anp, anp_created = MietzinsAnpassung.objects.get_or_create(
            vertrag=v, wirksam_ab=wirksam_ab, neuer_netto_mietzins=neu_netto,
            defaults={
                'alter_netto_mietzins': v.netto_mietzins,
                'alter_referenzzinssatz': v.basis_referenzzinssatz, 'neuer_referenzzinssatz': neu_zins,
                'alter_lik_index': v.basis_lik_punkte, 'neuer_lik_index': neu_lik,
                'erhoehung_prozent_total': pot.get('delta_prozent'),
                'begruendung': begruendung or 'Anpassung an Referenzzinssatz und Teuerung',
            })
        # Die Objekt-Sollmietzins-Zeile (gültig ab = wirksam_ab) wird jetzt zentral
        # in MietzinsAnpassung.save() geführt — über ALLE Erfassungswege. Hier kein
        # separater Aufruf mehr nötig.
        if anp_created:
            log_aktion(request, "Mietzinsanpassung erstellt", str(v),
                       f"neu CHF {neu_netto}, wirksam {wirksam_ab}", ziel=v)

        # Anfechtungsfrist-Pendenz bei einer Erhöhung: der Mieter kann die
        # Mietzinserhöhung innert 30 Tagen ab Empfang anfechten (Art. 270b OR).
        if anp_created and neu_netto > (v.netto_mietzins or Decimal('0')):
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
    naechster_termin = naechster_anpassungstermin(v, timezone.localdate())

    # Indexmiete (Art. 269b): die amtliche Index-Mitteilung (Art. 269d) wird direkt
    # aus der LIK-Entwicklung vorbefüllt — neuer Nettomietzins + fertige Begründung.
    index_vorschlag = None
    if v.mietzins_modell == 'index':
        from core.services.mietrecht import index_anpassung_vorschlag
        index_vorschlag = index_anpassung_vorschlag(v, aktuell_lik)
        if index_vorschlag:
            vorschlag_netto = index_vorschlag['neu_netto']

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
        'pot': pot, 'index_vorschlag': index_vorschlag,
    })


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_mietzins_massenanpassung(request):
    """Mietzins-Massenanpassung nach Referenzzins-/LIK-Änderung: für die in der
    Mietzins-Liste angehakten Verträge wird das Potenzial berechnet (Vorschau) und
    per Bestätigung je Vertrag eine MietzinsAnpassung + amtliches Formular erzeugt
    (Sammel-PDF). Fristen nach Art. 269d OR werden je Vertrag einzeln bestimmt."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from rentals.models import MietzinsAnpassung
    from rentals.services import berechne_mietpotenzial, naechster_anpassungstermin
    from core.utils import get_current_ref_zins, get_current_lik
    from core.auth import log_aktion

    if request.method != 'POST':
        return redirect('fw_mietzins')
    basis = _global_filter(request)
    vw = Verwaltung.objects.first()

    def _dec(x, default='0'):
        try:
            return Decimal(_num(x))
        except Exception:
            return Decimal(default)

    aktuell_ref = _dec(get_current_ref_zins())
    aktuell_lik = _dec(get_current_lik())
    from core.services.lik import aktueller_lik_wert
    _auto_stand, _auto_lik, _auto_basis = aktueller_lik_wert()
    aktuell_lik_stand = _auto_stand or (vw.aktueller_lik_stand if vw else None)
    lik_basis = _auto_basis or (vw.lik_basis if vw else 'Dezember 2020')

    ids = request.POST.getlist('vertrag_id')
    vertraege = list(Mietvertrag.objects.filter(id__in=ids, status='aktiv')
                     .select_related('mieter', 'einheit__liegenschaft'))
    if not vertraege:
        messages.error(request, "Keine Verträge ausgewählt.")
        return redirect('fw_mietzins')

    heute = timezone.localdate()
    rows = []
    for v in vertraege:
        pot = berechne_mietpotenzial(v, aktuell_ref, aktuell_lik) or {}
        neu_netto = pot.get('neu_chf')
        termin = naechster_anpassungstermin(v, heute)
        delta = (neu_netto - (v.netto_mietzins or Decimal('0'))) if neu_netto is not None else None
        rows.append({
            'v': v, 'pot': pot, 'neu_netto': neu_netto, 'termin': termin,
            'delta': delta,
            'basis_fehlt': not ((v.basis_referenzzinssatz or 0) > 0 and (v.basis_lik_punkte or 0) > 0),
            'unveraendert': (delta is not None and delta == 0),
        })

    aktion = request.POST.get('aktion', 'vorschau')
    if aktion != 'ausfuehren':
        machbar = [r for r in rows if not r['basis_fehlt'] and r['neu_netto'] is not None and r['delta']]
        return render(request, 'fw/mietzins_massen.html', {
            **basis, 'nav': 'mietzins', 'rows': rows, 'machbar': len(machbar),
            'aktuell_ref': aktuell_ref, 'aktuell_lik': aktuell_lik,
        })

    # --- Ausführen: je Vertrag Anpassung erfassen + amtliches Formular, dann Sammel-PDF ---
    from core.services.formular_fill import fill_mietzins
    from core.services.amtliche_formulare_so import mietzins_so_pdf
    from core.services.ablage import ablegen
    from core.models import Pendenz
    import io as _io
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    erfasst = uebersprungen = 0
    for r in rows:
        v = r['v']
        if r['basis_fehlt'] or r['neu_netto'] is None or not r['delta']:
            uebersprungen += 1
            continue
        neu_netto = r['neu_netto']
        wirksam_ab = r['termin']
        pot = r['pot']
        anp, anp_created = MietzinsAnpassung.objects.get_or_create(
            vertrag=v, wirksam_ab=wirksam_ab, neuer_netto_mietzins=neu_netto,
            defaults={
                'alter_netto_mietzins': v.netto_mietzins,
                'alter_referenzzinssatz': v.basis_referenzzinssatz, 'neuer_referenzzinssatz': aktuell_ref,
                'alter_lik_index': v.basis_lik_punkte, 'neuer_lik_index': aktuell_lik,
                'erhoehung_prozent_total': pot.get('delta_prozent'),
                'begruendung': 'Anpassung an Referenzzinssatz und Teuerung (Massenanpassung)',
            })
        if anp_created:
            log_aktion(request, "Mietzinsanpassung erstellt (Massenlauf)", str(v),
                       f"neu CHF {neu_netto}, wirksam {wirksam_ab}", ziel=v)
            if neu_netto > (v.netto_mietzins or Decimal('0')):
                Pendenz.objects.create(
                    titel=f"Anfechtungsfrist Mietzinserhöhung läuft ab – {v.mieter.display_name}",
                    beschreibung=(f"Erhöhung auf CHF {neu_netto} (wirksam {wirksam_ab:%d.%m.%Y}). Der Mieter kann "
                                  "sie innert 30 Tagen ab Empfang des amtlichen Formulars bei der "
                                  "Schlichtungsbehörde anfechten (Art. 270b OR)."),
                    kategorie='frist', faellig_am=heute + _timedelta(days=30), vertrag=v,
                    liegenschaft=v.einheit.liegenschaft if v.einheit_id else None,
                    erstellt_von=request.user if request.user.is_authenticated else None,
                )
        daten = {
            'alt_netto': v.netto_mietzins, 'neu_netto': neu_netto,
            'nebenkosten': v.nebenkosten,
            'alt_zins': v.basis_referenzzinssatz, 'neu_zins': aktuell_ref,
            'alt_lik': v.basis_lik_punkte, 'neu_lik': aktuell_lik,
            'lik_basis': lik_basis,
            'alt_lik_stand': v.basis_lik_stand, 'neu_lik_stand': aktuell_lik_stand,
            'zins_pct': None, 'lik_pct': None, 'kosten_pct': None,
            'total_pct': pot.get('delta_prozent'),
            'wirksam_ab': wirksam_ab,
            'begruendung': 'Anpassung an Referenzzinssatz und Teuerung',
            'schlichtungsbehoerde': '', 'mit_vorbehalt': False, 'vorbehalt_text': '',
        }
        pdf = fill_mietzins(v, daten, verwaltung=vw)
        if pdf is None:
            pdf = mietzins_so_pdf(v, daten, verwaltung=vw)
        ablegen(pdf, f"Mietzinsanpassung wirksam {wirksam_ab:%d.%m.%Y}",
                kategorie='vertrag', vertrag=v, dedup=True)
        try:
            for page in PdfReader(_io.BytesIO(pdf)).pages:
                writer.add_page(page)
        except Exception:
            pass
        erfasst += 1

    if not erfasst:
        messages.error(request, "Keine Anpassung möglich (Basisdaten fehlen oder kein Potenzial).")
        return redirect('fw_mietzins')

    log_aktion(request, "Mietzins-Massenanpassung", f"{erfasst} Verträge",
               f"Ref {aktuell_ref}% · LIK {aktuell_lik}")
    out = _io.BytesIO()
    writer.write(out)
    resp = HttpResponse(out.getvalue(), content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="Mietzinsanpassungen_Sammel.pdf"'
    return resp


def _vormiete_fuer(vertrag):
    """Letzter beendeter Vertrag desselben Objekts (für die Vormiete-Angabe)."""
    if not vertrag.einheit_id:
        return None
    return (Mietvertrag.objects.filter(einheit=vertrag.einheit).exclude(id=vertrag.id)
            .filter(beginn__lt=vertrag.beginn or timezone.localdate())
            .order_by('-beginn').first())


def anfangsmietzins_auto_ablegen(vertrag, verwaltung=None):
    """Erzeugt bei Vertrags-Aktivierung automatisch das amtliche Anfangsmietzins-
    Formular (Art. 270 Abs. 2 OR) und legt es in der Akte ab — aber NUR wenn im
    Kanton der Liegenschaft Formularpflicht besteht und es sich um Wohnraum handelt
    (kein Gewerbe, kein Einstellplatz). So steht das Formular spätestens zur
    Schlüsselübergabe bereit (30-Tage-Anfechtungsfrist ab Erhalt). Vormiete wird
    aus dem letzten beendeten Vertrag gezogen, sonst «unbekannt» (Art. 270 zulässig).
    Gibt (True, pflicht) bei Erzeugung zurück, sonst (False, grund)."""
    from crm.models import Verwaltung
    from core.services.formular_fill import fill_anfangsmietzins
    from core.services.formularpflicht import formularpflicht_fuer_liegenschaft
    from core.services.ablage import ablegen
    einheit = vertrag.einheit
    if not einheit:
        return False, 'kein_objekt'
    if getattr(einheit, 'mietrecht_kategorie', '') == 'gewerbe' or getattr(einheit, 'ist_einstellplatz', False):
        return False, 'kein_wohnraum'
    pflicht, info = formularpflicht_fuer_liegenschaft(einheit.liegenschaft)
    if pflicht not in ('ja', 'teilweise'):
        return False, 'keine_pflicht'
    # Anfangsmiete aus der datierten Sollmietzins-Tabelle zum Vertragsbeginn.
    soll = einheit.aktueller_sollmietzins(vertrag.beginn)
    anf_netto = (soll.netto_mietzins if soll else vertrag.netto_mietzins) or Decimal('0')
    anf_nk = (soll.nebenkosten if soll else vertrag.nebenkosten) or Decimal('0')
    vor = _vormiete_fuer(vertrag)
    vor_soll = vor.einheit.aktueller_sollmietzins(vor.beginn) if (vor and vor.einheit_id) else None
    from core.services.lik import LIK_BASIS
    _bq = vor or vertrag  # Berechnungsgrundlagen: Vorvertrag, sonst aktueller Vertrag
    daten = {
        'anfang_netto': anf_netto,
        'anfang_nk': anf_nk,
        'vormiete_netto': ((vor_soll.netto_mietzins if vor_soll else (vor.netto_mietzins if vor else 0)) or Decimal('0')),
        'vormiete_nk': ((vor_soll.nebenkosten if vor_soll else (vor.nebenkosten if vor else 0)) or Decimal('0')),
        'beginn': vertrag.beginn,
        'grund_choice': 'unbekannt' if not vor else 'anpassung',
        'begruendung': '',
        'basis_ref': _bq.basis_referenzzinssatz,
        'basis_lik': _bq.basis_lik_punkte,
        'basis_lik_basis': LIK_BASIS,
        'pflicht_info': info,
    }
    vw = verwaltung or (einheit.liegenschaft.verwaltung if einheit.liegenschaft else None) or Verwaltung.objects.first()
    pdf = fill_anfangsmietzins(vertrag, daten, verwaltung=vw)
    ablegen(pdf, f"Anfangsmietzins-Formular {vertrag.beginn:%d.%m.%Y}" if vertrag.beginn else "Anfangsmietzins-Formular",
            kategorie='vertrag', vertrag=vertrag, dedup=True)
    return True, pflicht


@rolle_erforderlich(ROLLE_VERWALTUNG)
def fw_anfangsmietzins(request, vertrag_id):
    """Amtliches Formular zur Mitteilung des Anfangsmietzinses (Art. 270 OR /
    Art. 19 VMWG) — bei Neuabschluss dem neuen Mieter mit Angabe der Vormiete und
    Hinweis auf das 30-Tage-Anfechtungsrecht zuzustellen. GET: Formular · POST: PDF."""
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from core.services.formular_fill import fill_anfangsmietzins, hat_original
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    vw = Verwaltung.objects.first()
    lg = v.einheit.liegenschaft

    def _dec(x, d='0'):
        try:
            return Decimal(_num(x) or d)
        except Exception:
            return Decimal(d)

    # Anfangsmiete aus der datierten Sollmietzins-Tabelle («Mietzins gültig ab»)
    # zum Vertragsbeginn ziehen — Fallback auf die Vertrags-/Objektwerte.
    soll = v.einheit.aktueller_sollmietzins(v.beginn) if v.einheit_id else None
    soll_netto = soll.netto_mietzins if soll else (v.netto_mietzins or Decimal('0'))
    soll_nk = soll.nebenkosten if soll else (v.nebenkosten or Decimal('0'))

    # Vormiete-Vorschlag: letzter beendeter Vertrag desselben Objekts (Sollmietzins
    # per dessen Beginn, sonst dessen Vertragswerte).
    vormiete = _vormiete_fuer(v)
    if vormiete and vormiete.einheit_id:
        vsoll = vormiete.einheit.aktueller_sollmietzins(vormiete.beginn)
        vor_netto = vsoll.netto_mietzins if vsoll else (vormiete.netto_mietzins or Decimal('0'))
        vor_nk = vsoll.nebenkosten if vsoll else (vormiete.nebenkosten or Decimal('0'))
    else:
        vor_netto = vor_nk = ''

    # Berechnungsgrundlagen: Referenzzinssatz + LIK-Punkte + LIK-Basis. Quelle =
    # Vorvertrag (falls vorhanden), sonst der aktuelle Vertrag (immer gesetzt).
    from core.services.lik import LIK_BASIS
    _bq = vormiete or v
    basis_ref = _bq.basis_referenzzinssatz
    basis_lik = _bq.basis_lik_punkte
    basis_lik_basis = LIK_BASIS

    if request.method == 'POST':
        daten = {
            'anfang_netto': _dec(request.POST.get('anfang_netto'), str(soll_netto or 0)),
            'anfang_nk': _dec(request.POST.get('anfang_nk'), str(soll_nk or 0)),
            'vormiete_netto': _dec(request.POST.get('vormiete_netto')),
            'vormiete_nk': _dec(request.POST.get('vormiete_nk')),
            'beginn': v.beginn,
            'grund_choice': request.POST.get('grund_choice') or 'anpassung',
            'begruendung': (request.POST.get('begruendung') or '').strip(),
            'basis_ref': (request.POST.get('basis_ref') or basis_ref or ''),
            'basis_lik': (request.POST.get('basis_lik') or basis_lik or ''),
            'basis_lik_basis': (request.POST.get('basis_lik_basis') or basis_lik_basis or ''),
            'vorbehalte': (request.POST.get('vorbehalte') or '').strip(),
        }
        from core.services.formularpflicht import formularpflicht_fuer_liegenschaft
        _pflicht, pflicht_info = formularpflicht_fuer_liegenschaft(lg)
        daten['pflicht_info'] = pflicht_info
        # Immer das Original-Formular des Kantons, wenn hinterlegt — sonst
        # kanton-adaptives Fallback-Formular.
        pdf = fill_anfangsmietzins(v, daten, verwaltung=vw)
        ablegen(pdf, f"Anfangsmietzins-Formular {v.beginn:%d.%m.%Y}" if v.beginn else "Anfangsmietzins-Formular",
                kategorie='vertrag', vertrag=v, dedup=True)
        log_aktion(request, "Anfangsmietzins-Formular erstellt", str(v),
                   f"Anfangsmiete CHF {daten['anfang_netto']}", ziel=v)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Anfangsmietzins_{v.mieter.nachname}.pdf"'
        return resp

    from core.services.formularpflicht import formularpflicht_fuer_liegenschaft, pflicht_label
    from core.services.kantone import kanton_fuer_liegenschaft
    pflicht, pflicht_info = formularpflicht_fuer_liegenschaft(lg)
    return render(request, 'fw/anfangsmietzins.html', {
        **basis, 'nav': 'mietzins', 'v': v, 'lg': lg,
        'anfang_netto': soll_netto, 'anfang_nk': soll_nk,
        'soll': soll,
        'vormiete': vormiete,
        'vormiete_netto': vor_netto,
        'vormiete_nk': vor_nk,
        'pflicht': pflicht, 'pflicht_info': pflicht_info,
        'pflicht_label': pflicht_label(pflicht),
        'hat_original': hat_original(kanton_fuer_liegenschaft(lg), 'anfangsmietzins'),
        'basis_ref': basis_ref, 'basis_lik': basis_lik, 'basis_lik_basis': basis_lik_basis,
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
            'id': d.id, 'loeschbar': True,
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
    lg_map = {}
    for v in vertraege:
        m = v.mieter
        if m.id in gesehen:
            continue
        gesehen.add(m.id)
        lg = v.einheit.liegenschaft
        lg_label = f"{lg.strasse}, {lg.ort}"
        lg_map[lg.id] = lg_label
        empfaenger.append({
            'id': m.id, 'name': m.display_name,
            'anrede': m.anrede or '',
            'strasse': m.strasse or lg.strasse,
            'plz': m.plz or lg.plz, 'ort': m.ort or lg.ort,
            'email': m.email or '',
            'objekt': f"{lg.strasse}, {lg.ort} · {v.einheit.bezeichnung}",
            'lg_id': lg.id, 'lg_label': lg_label,
        })
        # Mitmieter (Ehe-/Wohnpartner mit eigenem Mieter-Datensatz) separat
        # adressieren — er ist Vertragspartei und muss z. B. bei Familienwohnungen
        # eigene Post erhalten; bisher fiel er aus dem Serienbrief.
        if v.mitmieter_id and v.mitmieter_id not in gesehen:
            gesehen.add(v.mitmieter_id)
            mm = v.mitmieter
            empfaenger.append({
                'id': mm.id, 'name': mm.display_name,
                'anrede': mm.anrede or '',
                'strasse': mm.strasse or lg.strasse,
                'plz': mm.plz or lg.plz, 'ort': mm.ort or lg.ort,
                'email': mm.email or '',
                'objekt': f"{lg.strasse}, {lg.ort} · {v.einheit.bezeichnung}",
                'lg_id': lg.id, 'lg_label': lg_label,
            })
    empfaenger.sort(key=lambda e: e['name'])
    liegenschaften_wahl = [{'id': k, 'label': lbl} for k, lbl in sorted(lg_map.items(), key=lambda kv: kv[1])]

    # ?mieter=<id>: Empfänger vorauswählen (E-Mail-Button auf der Personenseite)
    try:
        vorwahl_mieter = int(request.GET.get('mieter') or 0)
    except (TypeError, ValueError):
        vorwahl_mieter = 0

    return render(request, 'fw/kommunikation.html', {
        **basis, 'nav': 'kommunikation',
        'absender': absender, 'empfaenger': empfaenger,
        'anzahl_empfaenger': len(empfaenger),
        'liegenschaften_wahl': liegenschaften_wahl,
        'vorlagen': vorlagen, 'logo_url': logo_url,
        'vorwahl_mieter': vorwahl_mieter,
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

    # Bearbeiten-Modus: der Assistent editiert einen bestehenden ENTWURF (voll).
    edit_id = request.GET.get('edit')
    edit_vertrag = (Mietvertrag.objects
                    .filter(id=edit_id, status='entwurf')
                    .select_related('einheit__liegenschaft', 'mieter', 'mitmieter').first()
                    if edit_id else None)

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
    # Im Bearbeiten-Modus das Objekt des Entwurfs immer einschliessen (sonst kann
    # der Assistent es nicht vorbelegen).
    if edit_vertrag:
        belegte.discard(edit_vertrag.einheit_id)

    lg_qs = Liegenschaft.objects.select_related('mandant').prefetch_related('einheiten').order_by('strasse')
    if vorwahl_e:
        lg_qs = lg_qs.filter(id=vorwahl_e.liegenschaft_id)
    elif aktive_lg and not edit_vertrag:
        lg_qs = lg_qs.filter(id=aktive_lg.id)

    liegenschaften = []
    for lg in lg_qs:
        objekte = []
        for e in lg.einheiten.all().order_by('bezeichnung'):
            if e.id in belegte:
                continue
            if vorwahl_e and e.id != vorwahl_einheit:
                continue   # bei Vorwahl nur genau dieses Objekt
            # Datierte Sollmietzins-Historie (gültig ab) — neue Verträge
            # übernehmen die zum Mietbeginn gültige Zeile automatisch.
            sollplan = [{'ab': s.gueltig_ab.isoformat(),
                         'netto': float(s.netto_mietzins or 0),
                         'nk': float(s.nebenkosten or 0),
                         'ref': float(s.basis_referenzzinssatz) if s.basis_referenzzinssatz is not None else None,
                         'lik': float(s.basis_lik_punkte) if s.basis_lik_punkte is not None else None}
                        for s in e.sollmietzinse.all()]  # bereits -gueltig_ab sortiert
            # Objekt-Staffelmiete-Vorlage (aufsteigend nach gueltig_ab) → belegt
            # einen neuen Gewerbe-Vertrag als Staffelmiete vor.
            staffelvorlage = [{'ab': s.gueltig_ab.isoformat(), 'netto': float(s.netto_mietzins or 0)}
                              for s in e.staffelvorlagen.all()]
            objekte.append({
                'id': e.id, 'bezeichnung': e.bezeichnung,
                'typ': e.get_typ_display(), 'typ_code': e.typ, 'etage': e.etage or '',
                'ewid': e.ewid or '', 'zimmer': float(e.zimmer) if e.zimmer else None,
                'flaeche': float(e.flaeche_m2) if e.flaeche_m2 else None,
                'netto': float(e.nettomiete_aktuell or 0), 'nk': float(e.nebenkosten_aktuell or 0),
                'sollplan': sollplan,
                'staffelvorlage': staffelvorlage,
                'nk_abrechnungsart': e.nk_abrechnungsart or 'akonto',
                'kaution_monate': e.standard_kautionsmonate or 3,
                'vertrag_titel': e.vertrag_titel, 'kategorie': e.mietrecht_kategorie,
                'ist_einstellplatz': e.ist_einstellplatz,
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

    # Prefill-Daten für den Bearbeiten-Modus (Entwurf).
    edit_json = None
    if edit_vertrag:
        ev = edit_vertrag
        edit_json = {
            'id': ev.id, 'lg_id': ev.einheit.liegenschaft_id, 'einheit_id': ev.einheit_id,
            'mieter_id': ev.mieter_id, 'mit_mieter_id': ev.mitmieter_id or '',
            'mitmieter_name': ev.mitmieter_name or '', 'familienwohnung': bool(ev.familienwohnung),
            'anzahl_personen': ev.anzahl_personen or 1,
            'beginn': ev.beginn.isoformat() if ev.beginn else '',
            'ende': ev.ende.isoformat() if ev.ende else '', 'unbefristet': not ev.ist_befristet,
            'erstmals_kuendbar': ev.erstmals_kuendbar_auf.isoformat() if ev.erstmals_kuendbar_auf else '',
            'kuendigungsfrist': ev.kuendigungsfrist_monate, 'kuendigungstermine': ev.kuendigungstermine or '',
            'mitbenutzung': ev.mitbenutzung or '', 'nebenraeume': ev.nebenraeume or '',
            'besondere_vereinbarungen': ev.besondere_vereinbarungen or '',
            'weitere_vorbehalte': ev.weitere_vorbehalte or '', 'zweckbestimmung': ev.zweckbestimmung or '',
            'zahlungsrhythmus': ev.zahlungsrhythmus or 'monatlich',
            'netto_mietzins': float(ev.netto_mietzins or 0), 'nebenkosten': float(ev.nebenkosten or 0),
            'nk_abrechnungsart': ev.nk_abrechnungsart or 'akonto',
            'verteilschluessel': ev.verteilschluessel or 'm2',
            'mwst_pflichtig': bool(ev.mwst_pflichtig), 'mwst_satz': float(ev.mwst_satz or 8.1),
            'mietzins_modell': ev.mietzins_modell or 'fest',
            'basis_referenzzinssatz': float(ev.basis_referenzzinssatz) if ev.basis_referenzzinssatz is not None else None,
            'basis_lik_punkte': float(ev.basis_lik_punkte) if ev.basis_lik_punkte is not None else None,
            'kautions_betrag': float(ev.kautions_betrag) if ev.kautions_betrag else '',
            'kautions_konto': ev.kautions_konto or '',
        }

    from core.services.docuseal_service import docuseal_konfiguriert
    return render(request, 'fw/vertrag_neu.html', {
        **basis, 'nav': 'vertraege',
        'liegenschaften': liegenschaften, 'mieter': mieter,
        'verwaltung': verwaltung,
        'aktueller_ref_zins': float(vw.aktueller_referenzzinssatz) if vw else 1.75,
        **_lik_assistent_defaults(vw),
        'heute_iso': timezone.localdate().isoformat(),
        'vorwahl_einheit': vorwahl_einheit or '',
        'edit_vertrag': edit_vertrag, 'edit_json': edit_json,
        'docuseal_konfiguriert': docuseal_konfiguriert(),
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
        neu_typ = P.get('mieter_typ', 'person')
        if neu_typ not in ('person', 'firma', 'verein'):
            neu_typ = 'person'
        mieter = Mieter.objects.create(
            typ=neu_typ,
            anrede=P.get('anrede', 'Herr') if neu_typ == 'person' else '',
            vorname=P.get('vorname', '').strip(),
            nachname=P.get('nachname', '').strip(),
            firmen_name=P.get('firmen_name', '').strip(),
            kontaktperson=P.get('kontaktperson', '').strip(),
            uid_nummer=P.get('uid_nummer', '').strip(),
            strasse=P.get('m_strasse', '').strip(), plz=P.get('m_plz', '').strip(),
            ort=P.get('m_ort', '').strip(), email=P.get('m_email', '').strip(),
        )

    def dec(key, default='0'):
        try:
            return Decimal((_num(P.get(key)) or str(default)))
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

    beginn = datum('beginn') or timezone.localdate()

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

    # Einstellplätze (Parkplatz/Garage, Art. 266e) haben keine separaten
    # Nebenkosten — serverseitig hart auf 0 setzen, egal was übermittelt wurde.
    _nk = Decimal('0.00') if einheit.ist_einstellplatz else dec('nebenkosten')

    # Bearbeiten-Modus: bestehenden ENTWURF aktualisieren statt neu anlegen.
    edit_id = P.get('edit_id')
    editing = (Mietvertrag.objects.filter(id=edit_id, status='entwurf').first()
               if edit_id else None)

    # Befristet = explizit angehakt (Checkbox «unbefristet» aus) UND ein Enddatum
    # gesetzt. So bleibt `ende` bei einem unbefristeten Vertrag leer, und ein
    # später via Kündigung gesetztes `ende` macht den Vertrag nicht «befristet».
    _ende = datum('ende')
    _ist_befristet = (P.get('ist_befristet') == '1') and bool(_ende)

    felder = dict(
        mieter=mieter, einheit=einheit,
        status='aktiv' if P.get('aktiv_setzen') == 'on' else 'entwurf',
        beginn=beginn, ende=_ende, ist_befristet=_ist_befristet,
        erstmals_kuendbar_auf=datum('erstmals_kuendbar'),
        kuendigungsfrist_monate=_kfrist,
        kuendigungstermine=P.get('kuendigungstermine', '').strip() or 'Ende jedes Monats ausser Dezember',
        mitmieter_name=mitmieter, mitmieter=zweiter_obj, familienwohnung=familienwohnung,
        anzahl_personen=int(P.get('anzahl_personen') or 1),
        besondere_vereinbarungen=P.get('besondere_vereinbarungen', '').strip(),
        mitbenutzung=P.get('mitbenutzung', '').strip(),
        nebenraeume=P.get('nebenraeume', '').strip(),
        netto_mietzins=dec('netto_mietzins'), nebenkosten=_nk,
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
        solidarhaftung=P.get('solidarhaftung', 'on') != 'off',
    )

    # Weitere WG-Mieter (bestehende Personen, mehrfach) — als M2M nach dem Save.
    _wg_ids = [i for i in P.getlist('weitere_mieter') if str(i).strip().isdigit()]

    with transaction.atomic():
        if editing:
            for _k, _v in felder.items():
                setattr(editing, _k, _v)
            editing.save()
            vertrag = editing
            vertrag.staffelstufen.all().delete()   # Staffel neu aus dem Formular aufbauen
        else:
            vertrag = Mietvertrag.objects.create(**felder)
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
                    betrag = Decimal(_num(netto_list[i])) if i < len(netto_list) and str(netto_list[i]).strip() else None
                except Exception:
                    betrag = None
                if ab_d and betrag and betrag > 0:
                    Staffelstufe.objects.create(vertrag=vertrag, ab_datum=ab_d, netto_mietzins=betrag)
        # WG: weitere Mieter setzen (Haupt- und 2. Mieter ausgenommen, keine Dubletten).
        if _wg_ids:
            aus = {mieter.id}
            if zweiter_obj:
                aus.add(zweiter_obj.id)
            ids = [int(i) for i in _wg_ids if int(i) not in aus]
            vertrag.weitere_mieter.set(Mieter.objects.filter(id__in=ids))
        elif editing:
            vertrag.weitere_mieter.clear()
    # Wohnadresse = Objektadresse ab Mietbeginn — als datierte Adress-Zeile
    # (gültig ab = Vertragsbeginn). Der tägliche Lauf (run_adress_umzuege) bzw.
    # sync_effektive_adresse führt die effektiven Flat-Felder am Stichtag nach.
    from crm.models import MieterAdresse
    lg = einheit.liegenschaft
    obj_strasse = f"{lg.strasse}{(', ' + einheit.etage) if einheit.etage else ''}"

    def setze_zukunftsadresse(person):
        if not person:
            return
        MieterAdresse.objects.get_or_create(
            mieter=person, art='wohn', gueltig_ab=beginn,
            defaults=dict(strasse=obj_strasse, plz=lg.plz, ort=lg.ort,
                          quelle=f'vertrag:{vertrag.id}',
                          notiz='Einzug gemäss Mietvertrag'))
        # Wenn der Einzug bereits erreicht ist, effektive Adresse sofort nachführen.
        person.sync_effektive_adresse()

    setze_zukunftsadresse(mieter)
    setze_zukunftsadresse(zweiter_obj)
    for _wg in vertrag.weitere_mieter.all():
        setze_zukunftsadresse(_wg)

    # Vertragsdokumente NUR erzeugen, wenn der Vertrag als AKTIV gesetzt wird
    # (→ erscheinen in der Akte + im Mieterportal). Ein Entwurf bleibt dokumentlos,
    # bis er aktiviert wird — dann werden die PDFs einmalig erzeugt (auch beim
    # Aktivieren eines bearbeiteten Entwurfs). Fehler dürfen nicht blockieren.
    anzahl_dok = 0
    if P.get('aktiv_setzen') == 'on':
        # Aktives Mietverhältnis → Objekt aus der Vermarktung/Feed/Exposé nehmen
        # (auch beim direkten Vertragsweg, nicht nur über Bewerbung→Vertrag).
        if vertrag.einheit_id and vertrag.einheit.zur_ausschreibung:
            vertrag.einheit.zur_ausschreibung = False
            vertrag.einheit.save(update_fields=['zur_ausschreibung'])
        try:
            from core.views.pdf import erzeuge_und_ablege_vertragspaket
            anzahl_dok = len(erzeuge_und_ablege_vertragspaket(vertrag))
        except Exception:
            anzahl_dok = 0
        # Amtliches Anfangsmietzins-Formular (Art. 270 Abs. 2 OR) automatisch
        # mitgenerieren, sofern Formularpflicht besteht — steht so zur
        # Schlüsselübergabe bereit (30-Tage-Anfechtungsfrist ab Erhalt).
        try:
            erzeugt, _grund = anfangsmietzins_auto_ablegen(vertrag, verwaltung=_vw)
            if erzeugt:
                messages.info(request, "📄 Amtliches Anfangsmietzins-Formular wurde automatisch erstellt "
                                       "(Formularpflicht) — bei Schlüsselübergabe aushändigen.")
        except Exception:
            pass

    # Nettomietzins 0 ist fast immer ein vergessenes Feld — warnen (nicht blockieren),
    # da ohne Mietzins die Sollstellung 0 verrechnet.
    if (vertrag.netto_mietzins or Decimal('0')) <= 0:
        messages.warning(request, "⚠️ Nettomietzins ist CHF 0 — bitte prüfen. Ohne Mietzins "
                                  "erzeugt der Mietenlauf keine Forderung.")

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

    log_aktion(request, "Mietvertrag bearbeitet (Assistent)" if editing else "Mietvertrag erstellt (Assistent)",
               str(mieter), f"{einheit.bezeichnung}, ab {beginn}", ziel=vertrag)
    _verb = "aktualisiert" if editing else "erstellt"
    if anzahl_dok:
        messages.success(
            request,
            f"✅ Mietvertrag für {mieter.display_name} {_verb} & aktiv gesetzt — "
            f"{anzahl_dok} Dokumente automatisch abgelegt (im Portal sichtbar).")
    elif editing:
        messages.success(request, f"✅ Vertrag (Entwurf) für {mieter.display_name} aktualisiert.")
    else:
        messages.success(request, f"✅ Mietvertrag (Entwurf) für {mieter.display_name} erstellt — "
                         "PDFs werden erst beim Aktivieren erzeugt.")

    # Optionaler Abschluss: direkt zur digitalen Unterschrift senden (DocuSeal).
    if P.get('abschluss') == 'senden':
        from core.services.docuseal_service import docuseal_senden
        ok, msg = docuseal_senden(vertrag)
        if ok:
            log_aktion(request, "Vertrag zur Unterschrift gesendet", str(mieter), msg, ziel=vertrag)
            messages.success(request, f"✍️ {msg}")
        else:
            messages.warning(request, f"Vertrag erstellt, aber Signaturversand nicht möglich: {msg}")
    return redirect(f'/neu/vertraege/{vertrag.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_vorschau(request):
    """Live-Vorschau des Vertragsassistenten: rendert das ECHTE Vertrags-PDF-
    Template als HTML aus den aktuellen Formularwerten (ohne zu speichern). So
    entspricht die Vorschau immer 1:1 dem generierten PDF — eine Quelle statt
    zwei divergierender Implementierungen."""
    from django.http import HttpResponse
    from crm.models import Mieter
    from core.services.pdf_service import render_vertrag_html
    if request.method != 'POST':
        return HttpResponse('', content_type='text/html')
    P = request.POST
    einheit = Einheit.objects.filter(id=P.get('einheit_id') or 0).select_related('liegenschaft').first()
    if not einheit:
        return HttpResponse(
            '<div style="font-family:Helvetica,sans-serif;color:#64748b;padding:40px;'
            'text-align:center;font-size:14px;">Bitte zuerst ein Objekt auswählen — '
            'dann erscheint hier die 1:1-Vorschau des Vertrags.</div>',
            content_type='text/html')

    def dec(key, default='0'):
        try:
            return Decimal((_num(P.get(key)) or str(default)))
        except Exception:
            return Decimal(default)

    def datum(key):
        try:
            return date.fromisoformat(P.get(key)) if P.get(key) else None
        except ValueError:
            return None

    # Mieter: bestehend oder transient aus den Feldern.
    mieter = None
    if P.get('mieter_id'):
        mieter = Mieter.objects.filter(id=P.get('mieter_id')).first()
    if mieter is None:
        mieter = Mieter(
            typ=P.get('mieter_typ', 'person'),
            anrede=P.get('anrede', '') if P.get('mieter_typ', 'person') == 'person' else '',
            vorname=P.get('vorname', '').strip(), nachname=P.get('nachname', '').strip(),
            firmen_name=P.get('firmen_name', '').strip(),
            strasse=P.get('m_strasse', '').strip(), plz=P.get('m_plz', '').strip(),
            ort=P.get('m_ort', '').strip(), email=P.get('m_email', '').strip())

    mitmieter = P.get('mitmieter_name', '').strip()
    if not mitmieter and (P.get('mit_vorname') or P.get('mit_nachname')):
        mitmieter = ' '.join(t for t in [P.get('mit_anrede', '').strip(),
                                          P.get('mit_vorname', '').strip(),
                                          P.get('mit_nachname', '').strip()] if t)

    _nk = Decimal('0.00') if einheit.ist_einstellplatz else dec('nebenkosten')
    _modell = P.get('mietzins_modell', 'fest')
    if _modell not in ('fest', 'index', 'staffel'):
        _modell = 'fest'
    # Transienter (nicht gespeicherter) Vertrag — nur zum Rendern.
    vertrag = Mietvertrag(
        mieter=mieter, einheit=einheit,
        beginn=datum('beginn') or timezone.localdate(), ende=datum('ende'),
        erstmals_kuendbar_auf=datum('erstmals_kuendbar'),
        kuendigungsfrist_monate=int(P.get('kuendigungsfrist') or 3),
        kuendigungstermine=P.get('kuendigungstermine', '').strip() or 'Ende jedes Monats ausser Dezember',
        mitmieter_name=mitmieter, familienwohnung=P.get('familienwohnung') == 'on',
        anzahl_personen=int(P.get('anzahl_personen') or 1),
        besondere_vereinbarungen=P.get('besondere_vereinbarungen', '').strip(),
        mitbenutzung=P.get('mitbenutzung', '').strip(),
        nebenraeume=P.get('nebenraeume', '').strip(),
        netto_mietzins=dec('netto_mietzins'), nebenkosten=_nk,
        nk_abrechnungsart=P.get('nk_abrechnungsart', 'akonto'),
        verteilschluessel=P.get('verteilschluessel', 'm2'),
        zahlungsrhythmus=P.get('zahlungsrhythmus', 'monatlich'),
        mwst_pflichtig=P.get('mwst_pflichtig') == 'on',
        mwst_satz=dec('mwst_satz') or Decimal('8.1'),
        mietzins_modell=_modell,
        zweckbestimmung=P.get('zweckbestimmung', '').strip(),
        weitere_vorbehalte=P.get('weitere_vorbehalte', '').strip(),
        basis_referenzzinssatz=dec('basis_referenzzinssatz') or Decimal('1.75'),
        basis_lik_punkte=dec('basis_lik_punkte') or Decimal('107.1'),
        kautions_betrag=dec('kautions_betrag') or None,
        kautions_konto=P.get('kautions_konto', '').strip())
    try:
        html = render_vertrag_html(vertrag, mit_unterschrift=False)
    except Exception as exc:
        html = ('<div style="font-family:Helvetica,sans-serif;color:#b91c1c;padding:24px;'
                f'font-size:13px;">Vorschau konnte nicht erstellt werden: {exc}</div>')
    return HttpResponse(html, content_type='text/html')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_bearbeiten(request, pk):
    """Bearbeitet einen bestehenden Mietvertrag.

    - Entwurf: alle Felder frei editierbar.
    - Aktiv/gekündigt/archiviert: nur UNKRITISCHE Felder (Fristen-Detail, Nebenräume,
      Vereinbarungen, Mitmieter …). Miete, Objekt, Mieter, Beginn, MWST und
      Abrechnungsart sind GESPERRT — serverseitig erzwungen, nicht nur im UI
      (Mietzinsänderungen laufen über das amtliche Formular Art. 269d). So bleibt
      die Buchhaltung konsistent."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mieter, Verwaltung
    from core.auth import log_aktion, snapshot_model, diff_model
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=pk)
    gesperrt = v.status != 'entwurf'   # nur Entwurf voll editierbar

    # Entwurf → voller Assistent (mit Live-Vorschau). Aktive/gekündigte Verträge
    # → reduziertes Formular (Miete/Objekt gesperrt).
    if not gesperrt and request.method == 'GET':
        from django.shortcuts import redirect
        return redirect(f'/neu/vertraege/neu/?edit={v.id}')

    if request.method == 'POST':
        P = request.POST
        alt = snapshot_model(v)

        def dec(key, default=None):
            raw = _num(P.get(key))
            try:
                return Decimal(raw) if raw else (Decimal(default) if default is not None else None)
            except Exception:
                return Decimal(default) if default is not None else None

        def datum(key):
            try:
                return date.fromisoformat(P.get(key)) if P.get(key) else None
            except ValueError:
                return None

        # --- Immer editierbar (unkritisch) ---
        v.ende = datum('ende')
        # Befristung folgt bei einem AKTIVEN Vertrag dem Enddatum (leer = unbefristet).
        # Bei gekündigten/archivierten Verträgen stammt `ende` aus der Kündigung —
        # die Befristungs-Kennung nicht anrühren.
        if v.status == 'aktiv':
            v.ist_befristet = bool(v.ende)
        v.erstmals_kuendbar_auf = datum('erstmals_kuendbar')
        try:
            v.kuendigungsfrist_monate = int(P.get('kuendigungsfrist') or v.kuendigungsfrist_monate)
        except ValueError:
            pass
        v.kuendigungstermine = P.get('kuendigungstermine', '').strip() or v.kuendigungstermine
        v.familienwohnung = P.get('familienwohnung') == 'on'
        v.mitmieter_name = P.get('mitmieter_name', '').strip()
        try:
            v.anzahl_personen = int(P.get('anzahl_personen') or v.anzahl_personen or 1)
        except ValueError:
            pass
        v.mitbenutzung = P.get('mitbenutzung', '').strip()
        v.nebenraeume = P.get('nebenraeume', '').strip()
        v.zweckbestimmung = P.get('zweckbestimmung', '').strip()
        v.besondere_vereinbarungen = P.get('besondere_vereinbarungen', '').strip()
        v.weitere_vorbehalte = P.get('weitere_vorbehalte', '').strip()

        # --- Nur bei Entwurf editierbar (kritisch) ---
        if not gesperrt:
            beginn = datum('beginn')
            if beginn:
                v.beginn = beginn
            neue_einheit = Einheit.objects.filter(id=P.get('einheit_id') or 0).first()
            if neue_einheit:
                v.einheit = neue_einheit
            neuer_mieter = Mieter.objects.filter(id=P.get('mieter_id') or 0).first()
            if neuer_mieter:
                v.mieter = neuer_mieter
            v.netto_mietzins = dec('netto_mietzins', '0')
            v.nebenkosten = Decimal('0.00') if v.einheit.ist_einstellplatz else dec('nebenkosten', '0')
            v.nk_abrechnungsart = P.get('nk_abrechnungsart', v.nk_abrechnungsart)
            v.verteilschluessel = P.get('verteilschluessel', v.verteilschluessel)
            v.zahlungsrhythmus = P.get('zahlungsrhythmus', v.zahlungsrhythmus)
            v.mwst_pflichtig = P.get('mwst_pflichtig') == 'on'
            _ms = dec('mwst_satz')
            if _ms is not None:
                v.mwst_satz = _ms
            v.kautions_betrag = dec('kautions_betrag') or None
            v.kautions_konto = P.get('kautions_konto', '').strip()
        v.save()
        _diff = diff_model(alt, snapshot_model(v), v)
        log_aktion(request, "Vertrag bearbeitet", str(v.mieter),
                   f"{v.einheit.bezeichnung} · {'Entwurf' if not gesperrt else 'nur Detailfelder'}"
                   + (f" · {_diff}" if _diff else ''), ziel=v)
        messages.success(request, "✅ Vertrag aktualisiert."
                         + ("" if not gesperrt else " (aktiver Vertrag — nur Detailfelder geändert)"))
        return redirect(f'/neu/vertraege/{v.id}/')

    verwaltung = v.einheit.liegenschaft.verwaltung or Verwaltung.objects.first()
    return render(request, 'fw/vertrag_bearbeiten.html', {
        **_global_filter(request), 'nav': 'vertraege', 'v': v, 'gesperrt': gesperrt,
        'objekte': Einheit.objects.select_related('liegenschaft').order_by('liegenschaft__strasse', 'bezeichnung'),
        'mieter_liste': Mieter.objects.order_by('nachname', 'firmen_name'),
        'nk_arten': Mietvertrag.NK_TYP_CHOICES,
        'verteil_choices': Mietvertrag.VERTEIL_CHOICES,
        'rhythmus_choices': Mietvertrag.ZAHLUNGSRHYTHMUS_CHOICES,
    })


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_signieren(request, pk):
    """Sendet einen bestehenden Vertrag zur digitalen Unterschrift (DocuSeal)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from core.services.docuseal_service import docuseal_senden
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit'), id=pk)
    if request.method == 'POST':
        ok, msg = docuseal_senden(v)
        if ok:
            log_aktion(request, "Vertrag zur Unterschrift gesendet", str(v.mieter), msg, ziel=v)
            messages.success(request, f"✍️ {msg}")
        else:
            messages.error(request, f"❌ {msg}")
    return redirect(f'/neu/vertraege/{v.id}/')


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
                pass
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
        pass
    try:
        seed_lebensdauer()
    except Exception:
        pass

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

        def decval(key):
            v = _num(P.get(key))
            try:
                return Decimal(v) if v else None
            except Exception:
                return None
        obj.baujahr = intval('baujahr')
        md_id = P.get('mandant_id') or ''
        obj.mandant = Mandant.objects.filter(id=md_id).first() if md_id else None
        obj.versicherungswert = decval('versicherungswert')
        obj.grundstuecksflaeche_m2 = decval('grundstuecksflaeche_m2')
        obj.gebaeudevolumen_m3 = decval('gebaeudevolumen_m3')
        # Bewertung (Rendite) + Energie/GEAK
        obj.verkehrswert = decval('verkehrswert')
        obj.anlagekosten = decval('anlagekosten')
        obj.kaufpreis = decval('kaufpreis')
        obj.energiebezugsflaeche_m2 = decval('energiebezugsflaeche_m2')
        _heiz = P.get('heizsystem', '').strip()
        obj.heizsystem = _heiz if _heiz in dict(Liegenschaft.HEIZ_CHOICES) else ''
        _ww = P.get('warmwasser', '').strip()
        obj.warmwasser = _ww if _ww in dict(Liegenschaft.WARMWASSER_CHOICES) else ''
        _gk = P.get('geak_klasse', '').strip().upper()
        obj.geak_klasse = _gk if _gk in dict(Liegenschaft.GEAK_KLASSEN) else ''
        _gkg = P.get('geak_klasse_gesamt', '').strip().upper()
        obj.geak_klasse_gesamt = _gkg if _gkg in dict(Liegenschaft.GEAK_KLASSEN) else ''
        obj.energietraeger = P.get('energietraeger', '').strip()
        try:
            _gd = P.get('geak_datum') or ''
            obj.geak_datum = date.fromisoformat(_gd) if _gd else None
        except ValueError:
            obj.geak_datum = None
        obj.hauswart_name = P.get('hauswart_name', '').strip()
        obj.hauswart_telefon = P.get('hauswart_telefon', '').strip()
        obj.sanitaer_name = P.get('sanitaer_name', '').strip()
        obj.sanitaer_telefon = P.get('sanitaer_telefon', '').strip()
        obj.elektriker_name = P.get('elektriker_name', '').strip()
        obj.elektriker_telefon = P.get('elektriker_telefon', '').strip()
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
        'heiz_choices': Liegenschaft.HEIZ_CHOICES,
        'warmwasser_choices': Liegenschaft.WARMWASSER_CHOICES,
        'geak_klassen': [k for k, _ in Liegenschaft.GEAK_KLASSEN],
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
def fw_versicherung_add(request, lg_id):
    """Versicherungspolice zu einer Liegenschaft erfassen (Register)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Versicherung
    from core.auth import log_aktion
    lg = get_object_or_404(Liegenschaft, id=lg_id)
    if request.method != 'POST':
        return redirect(f'/neu/liegenschaften/{lg.id}/')
    P = request.POST

    def dec(key):
        v = _num(P.get(key))
        try:
            return Decimal(v) if v else None
        except Exception:
            return None
    art = P.get('art', 'gebaeude')
    ablauf = None
    try:
        ablauf = date.fromisoformat((P.get('ablauf_datum') or '').strip()) if P.get('ablauf_datum') else None
    except ValueError:
        ablauf = None
    Versicherung.objects.create(
        liegenschaft=lg, art=art if art in dict(Versicherung.ART_CHOICES) else 'andere',
        gesellschaft=P.get('gesellschaft', '').strip(),
        policennummer=P.get('policennummer', '').strip(),
        versicherungssumme=dec('versicherungssumme'), jahrespraemie=dec('jahrespraemie'),
        ablauf_datum=ablauf, notiz=P.get('notiz', '').strip())
    log_aktion(request, "Versicherung erfasst", f"{lg.strasse}", P.get('gesellschaft', ''), ziel=lg)
    messages.success(request, "✅ Versicherung erfasst.")
    return redirect(f'/neu/liegenschaften/{lg.id}/?tab=finanzen')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_versicherung_loeschen(request, pk):
    """Versicherungspolice entfernen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from portfolio.models import Versicherung
    vs = get_object_or_404(Versicherung, id=pk)
    lg_id = vs.liegenschaft_id
    if request.method == 'POST':
        vs.delete()
        messages.success(request, "✅ Versicherung entfernt.")
    return redirect(f'/neu/liegenschaften/{lg_id}/?tab=finanzen')


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
            v = _num(P.get(key))
            try:
                return Decimal(v) if v else None
            except Exception:
                return None
        obj.zimmer = dec('zimmer')
        obj.flaeche_m2 = dec('flaeche_m2')
        obj.volumen_m3 = dec('volumen_m3')
        _wq = dec('wertquote')
        if _wq is not None:
            obj.wertquote = _wq
        obj.keller = P.get('keller', '').strip()
        obj.estrich = P.get('estrich', '').strip()
        obj.oto_dose = P.get('oto_dose', '').strip()
        obj.bodenbelag = P.get('bodenbelag', '').strip()
        obj.bodenbelag_nassraum = P.get('bodenbelag_nassraum', '').strip()

        def intval(key):
            v = str(P.get(key) or '').strip()
            try:
                return int(v) if v else None
            except ValueError:
                return None
        obj.letzte_renovation = intval('letzte_renovation')
        _km = intval('standard_kautionsmonate')
        if _km is not None:
            obj.standard_kautionsmonate = _km
        # Nebenobjekt-Zuordnung (Parkplatz/Keller → Hauptobjekt derselben Liegenschaft)
        gz_id = P.get('gehoert_zu_id') or ''
        if gz_id and gz_id != str(obj.pk or ''):
            obj.gehoert_zu = Einheit.objects.filter(id=gz_id, liegenschaft=obj.liegenschaft).first()
        else:
            obj.gehoert_zu = None
        obj.notizen = P.get('notizen', '').strip()
        # Der Mietzins wird NICHT mehr direkt am Objekt gepflegt — einzige Quelle
        # ist der datierte Sollmietzins (Objekt → Mietzins). nettomiete_aktuell/
        # nebenkosten_aktuell sind rein abgeleitet (sync_aktuelle_miete beim
        # Speichern einer Sollmietzins-Zeile) → kein Drift mehr zwischen Objekt-
        # Maske und Mietzins-Tab.
        obj.save()
        # Nur bei NEUanlage: optionalen Anfangsmietzins als erste Sollmietzins-Zeile
        # seeden (single source). Bestehende Objekte pflegen die Miete ausschliesslich
        # über den Mietzins-Tab.
        from portfolio.models import Sollmietzins
        if not pk:
            netto0 = dec('nettomiete_aktuell') or Decimal('0.00')
            nk0 = Decimal('0.00') if obj.ist_einstellplatz else (dec('nebenkosten_aktuell') or Decimal('0.00'))
            if netto0 > 0 or nk0 > 0:
                soll_ab_raw = (P.get('soll_gueltig_ab') or '').strip()
                try:
                    soll_ab = date.fromisoformat(soll_ab_raw) if soll_ab_raw else timezone.localdate()
                except ValueError:
                    soll_ab = timezone.localdate()
                Sollmietzins.objects.create(
                    einheit=obj, gueltig_ab=soll_ab,
                    netto_mietzins=netto0, nebenkosten=nk0, notiz='Ersterfassung')
        _diff = diff_model(alt_snap, snapshot_model(obj), obj) if pk else ''
        log_aktion(request, "Objekt bearbeitet" if pk else "Objekt erstellt",
                   f"{obj.bezeichnung} ({obj.liegenschaft.strasse})", _diff, ziel=obj)
        messages.success(request, f"✅ Objekt {obj.bezeichnung} gespeichert.")
        return redirect(f'/neu/objekte/{obj.id}/')

    vorwahl_lg = request.GET.get('lg') or (e.liegenschaft_id if e else None)
    sollmietzinse = list(e.sollmietzinse.all()) if e else []
    aktueller_soll = e.aktueller_sollmietzins() if e else None
    # Mögliche Hauptobjekte für die Nebenobjekt-Zuordnung (gehoert_zu): übrige
    # Einheiten derselben Liegenschaft (ohne sich selbst).
    hauptobjekte = []
    if e and e.liegenschaft_id:
        hauptobjekte = list(Einheit.objects.filter(liegenschaft_id=e.liegenschaft_id)
                            .exclude(id=e.id).order_by('bezeichnung'))
    return render(request, 'fw/objekt_form.html', {
        **basis, 'nav': 'objekte', 'e': e, 'ist_neu': e is None,
        'liegenschaften': Liegenschaft.objects.all().order_by('strasse'),
        'vorwahl_lg': str(vorwahl_lg) if vorwahl_lg else '',
        'typ_choices': Einheit.TYP_CHOICES,
        'sollmietzinse': sollmietzinse,
        'aktueller_soll_id': aktueller_soll.id if aktueller_soll else None,
        'heute_iso': timezone.localdate().isoformat(),
        'hauptobjekte': hauptobjekte,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_suche(request):
    """Globale Suche über Personen, Liegenschaften, Objekte und Verträge."""
    q = (request.GET.get('q') or '').strip()
    basis = _global_filter(request)
    personen, liegenschaften, objekte, vertraege = [], [], [], []

    if q:
        # Telefon-Suche: Nummern werden in vielen Formaten erfasst («079 123 45 67»,
        # «+41791234567») — Query UND Feldwerte auf reine Ziffern normalisieren,
        # damit der Anrufer vom Display direkt gefunden wird.
        personen_q = (Q(vorname__icontains=q) | Q(nachname__icontains=q)
                      | Q(firmen_name__icontains=q) | Q(email__icontains=q)
                      | Q(ort__icontains=q)
                      | Q(mobile__icontains=q) | Q(telefon_privat__icontains=q)
                      | Q(telefon_geschaeft__icontains=q))
        personen = list(Mieter.objects.filter(personen_q)
                        .order_by('nachname', 'firmen_name')[:20])
        ziffern = ''.join(ch for ch in q if ch.isdigit())
        if len(ziffern) >= 5 and len(personen) < 20:
            # Format-agnostischer Nachfilter über die Telefon-Felder.
            vorhandene = {p.id for p in personen}
            for p in Mieter.objects.exclude(id__in=vorhandene).exclude(
                    mobile='', telefon_privat='', telefon_geschaeft='')[:500]:
                nummern = ''.join(ch for ch in f"{p.mobile}|{p.telefon_privat}|{p.telefon_geschaeft}" if ch.isdigit())
                if ziffern in nummern:
                    personen.append(p)
                    if len(personen) >= 20:
                        break

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
        try:
            obj.honorar_prozent = Decimal((_num(P.get('honorar_prozent')) or '0'))
        except Exception:
            obj.honorar_prozent = Decimal('0.00')
        if not obj.firma_oder_name:
            messages.error(request, "Name / Firma ist erforderlich.")
            return redirect(request.path)
        # Digitale Unterschrift des Eigentümers — Briefe, die in seinem Namen
        # rausgehen (Schlussabrechnung, Kautionsbelege), tragen sie.
        from core.services.unterschrift import uebernehme_aus_formular
        uebernehme_aus_formular(obj, request)
        obj.save()
        # Liegenschaften zuordnen: gewählte -> dieser Mandant; abgewählte (bisher dieser) -> ohne Mandant.
        # Nur wenn das Formular den Zuordnungsblock wirklich mitgeschickt hat: Ein POST
        # ohne diesen Block (Teilformular, abgebrochenes Rendering) hätte sonst still
        # ALLE Liegenschaften vom Eigentümer gelöst — und damit u.a. seine Unterschrift
        # aus jedem Brief entfernt, weil die Briefe über die Liegenschaft an ihn kommen.
        if P.get('lg_zuordnung') == '1':
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
    from core.services.unterschrift import unterschrift_url as _sig_url
    sig_url = _sig_url(md) if md else ''
    return render(request, 'fw/mandat_form.html', {
        **basis, 'nav': 'mandate', 'md': md, 'ist_neu': md is None,
        'alle_liegenschaften': alle_lg, 'zugeordnet': zugeordnet,
        'unterschrift_url': sig_url,
        'unterschrift_verwaist': bool(md and getattr(md, 'unterschrift_bild', None)) and not sig_url,
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
        # Verknüpften Eigentümer-Portal-Login mitentfernen — sonst bleibt ein
        # Login zurück, dessen mandant_profil ins Leere zeigt.
        if md.benutzer_id:
            try:
                md.benutzer.delete()
            except Exception:
                pass
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
    heute = timezone.localdate()
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
        # Art. 267a Abs. 1 OR: Mängel, für die der Mieter einzustehen hat, müssen
        # SOFORT nach der Rückgabe gerügt werden — sonst sind die Ersatzansprüche
        # verwirkt (Praxis: 2-3 Arbeitstage; versteckte Mängel bleiben vorbehalten).
        ("Mängelrüge Art. 267a: sofort nach Abnahme versenden", tage(2), 'frist'),
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
        # Wirksames Ende: ausserordentlich → gewünschtes Datum. Ordentlich: ein zu
        # FRÜH gewünschtes Ende gilt von Gesetzes wegen auf den nächstmöglichen
        # Termin (Art. 266a Abs. 2 OR) — serverseitig auf den berechneten
        # ordentlichen Termin klemmen, sonst führen Vertragsende/Leerstand/
        # Sollstellung ein rechtlich unwirksames Datum.
        if ausserord and gewuenscht:
            per = gewuenscht
        elif gewuenscht and termin and gewuenscht < termin:
            per = termin
            messages.warning(request, f"⚠️ Gewünschtes Ende {gewuenscht:%d.%m.%Y} liegt vor dem "
                                      f"nächsten zulässigen Termin — die Kündigung gilt auf "
                                      f"{termin:%d.%m.%Y} (Art. 266a Abs. 2 OR).")
        else:
            per = gewuenscht or termin

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

    # Mindestfrist: Wohn-/Geschäftsräume 30 Tage, sonst 10 Tage (Art. 257d Abs. 1).
    # Die Frist läuft ab ZUGANG beim Mieter (Empfangstheorie), nicht ab Absendetag —
    # daher einen Zustellpuffer (Postweg + 7-tägige Abholfrist beim eingeschriebenen
    # Brief) aufschlagen, sonst wäre die Fristansetzung und eine darauf gestützte
    # ausserordentliche Kündigung zu kurz und damit nichtig.
    ZUSTELL_PUFFER = 7
    min_frist = 30 if v.ist_geschuetzt else 10
    default_frist = (heute + timedelta(days=min_frist + ZUSTELL_PUFFER)).isoformat()

    if request.method == 'POST':
        try:
            frist = date.fromisoformat(request.POST.get('frist_bis') or default_frist)
        except ValueError:
            frist = heute + timedelta(days=min_frist)
        vw = Verwaltung.objects.first()
        absender = {'firma': getattr(vw, 'firma', '') if vw else '', 'strasse': getattr(vw, 'strasse', '') if vw else '',
                    'plz': getattr(vw, 'plz', '') if vw else '', 'ort': getattr(vw, 'ort', '') if vw else ''}
        m = v.mieter
        _obj = v.einheit.bezeichnung if v.einheit_id else ''
        _lgz = f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else ''

        def _empf(name, strasse, plz, ort):
            return {'name': name, 'anrede': f"Sehr geehrte/r {name}",
                    'strasse': strasse, 'plz': plz, 'ort': ort,
                    'objekt': _obj, 'liegenschaft': _lgz}

        # Art. 266n OR erfasst ausdrücklich auch die Fristansetzung nach Art. 257d:
        # bei einer FAMILIENWOHNUNG muss sie dem Mieter UND dem Ehegatten SEPARAT
        # zugestellt werden — sonst ist die darauf gestützte ausserordentliche
        # Kündigung nichtig (Art. 266o OR). Zusätzlich erhalten solidarisch
        # haftende Mitmieter (WG) je eine eigene Kopie.
        emp = [_empf(m.display_name, m.strasse, m.plz, m.ort)]
        if v.familienwohnung:
            if v.mitmieter_id:
                m2 = v.mitmieter
                emp.append(_empf(m2.display_name, m2.strasse or m.strasse,
                                 m2.plz or m.plz, m2.ort or m.ort))
            elif (v.mitmieter_name or '').strip():
                # Ehegatte ohne eigene Personenakte → an die gemeinsame Wohnadresse.
                emp.append(_empf(v.mitmieter_name.strip(), m.strasse, m.plz, m.ort))
        elif v.mitmieter_id:
            emp.append(_empf(v.mitmieter.display_name, v.mitmieter.strasse or m.strasse,
                             v.mitmieter.plz or m.plz, v.mitmieter.ort or m.ort))
        for wm in (v.weitere_mieter.all() if v.pk else []):
            emp.append(_empf(wm.display_name, wm.strasse or m.strasse,
                             wm.plz or m.plz, wm.ort or m.ort))
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
        pdf = generate_serienbrief_pdf(absender, betreff, text, emp, signatur=(vw,))
        _suffix = f" ({len(emp)} Zustellungen)" if len(emp) > 1 else ""
        ablegen(pdf, f"Zahlungsaufforderung 257d – Frist {frist:%d.%m.%Y}{_suffix}",
                kategorie='korrespondenz', vertrag=v, dedup=False)
        if len(emp) > 1:
            messages.info(request, f"📮 {len(emp)} separat adressierte Briefe erzeugt "
                                   "(Art. 266n OR: Familienwohnung/Mitmieter) — jede Kopie "
                                   "einzeln per Einschreiben zustellen.")
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
    """Amtliches Kündigungsformular (PDF) — Original des zuständigen Kantons ausfüllen.
    Art. 266n OR: Kündigt der Vermieter eine Familienwohnung, werden zwei separat an
    Mieter UND Ehegatte adressierte Kopien erzeugt (sonst ist die Kündigung nichtig)."""
    from django.http import HttpResponse
    from django.contrib import messages
    from rentals.models import Kuendigung
    from crm.models import Verwaltung
    k = get_object_or_404(Kuendigung.objects.select_related(
        'vertrag__mieter', 'vertrag__mitmieter', 'vertrag__einheit__liegenschaft'), id=pk)
    vw = Verwaltung.objects.first()
    from core.services.formular_fill import kuendigung_zustellkopien
    from core.services.ablage import ablegen
    kopien = kuendigung_zustellkopien(k.vertrag, k, verwaltung=vw)

    for empf_name, pdf in kopien:
        suffix = f" — Zustellung an {empf_name}" if empf_name else ""
        ablegen(pdf, f"Kündigung {k.get_absender_display()} {k.eingang_datum:%d.%m.%Y}{suffix}",
                kategorie='vertrag', vertrag=k.vertrag, dedup=True)

    # Amtliches Formular erstellt → 'schriftlich bestätigen / Formular versenden' abhaken
    from core.services.automation import erledige_pendenzen_fuer
    erledige_pendenzen_fuer(k.vertrag, ['schriftlich', 'Kündigungsformular'],
                            user=request.user)

    if len(kopien) > 1:
        # Art. 266n: alle Kopien in EIN PDF bündeln (jede Seite separat versenden).
        from pypdf import PdfReader, PdfWriter
        import io as _io
        writer = PdfWriter()
        for _n, pdf in kopien:
            for page in PdfReader(_io.BytesIO(pdf)).pages:
                writer.add_page(page)
        out = _io.BytesIO(); writer.write(out); pdf_bytes = out.getvalue()
        messages.info(request, "Familienwohnung (Art. 266n OR): Es wurden zwei separat adressierte "
                               "Kopien erstellt — je Ehegatte einzeln und mit separater Post zustellen, "
                               "sonst ist die Kündigung nichtig.")
    else:
        pdf_bytes = kopien[0][1]

    resp = HttpResponse(bytes(pdf_bytes), content_type='application/pdf')
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
            return Decimal((_num(P.get(key)) or '0'))
        except Exception:
            return Decimal('0.00')

    if aktion == 'einzahlung':
        # Sperrkonto: Einzahlung auf Mietkonto bestätigen.
        # Statusänderung UND Bilanzbuchung (1015 an 2010) in EINER Transaktion —
        # scheitert die Buchung (z.B. Periodensperre), wird die Statusänderung
        # zurückgerollt und der Fehler angezeigt (kein stiller Nebenbuch-Drift).
        v.kautions_art = 'sperrkonto'
        v.kautions_einbezahlt_am = d('einbezahlt_am') or timezone.localdate()
        v.kautions_konto = P.get('kautions_konto', v.kautions_konto).strip() or v.kautions_konto
        try:
            with transaction.atomic():
                v.save(update_fields=['kautions_art', 'kautions_einbezahlt_am', 'kautions_konto'])
                from core.services.automation import buche_kaution_einzahlung
                buche_kaution_einzahlung(v, v.kautions_einbezahlt_am, user=request.user)
        except PermissionError as exc:
            messages.error(request, f"❌ {exc}")
            return redirect(f'/neu/vertraege/{v.id}/')
        except Exception as exc:
            messages.error(request, f"❌ Kautions-Einzahlung konnte nicht gebucht werden: {exc}")
            return redirect(f'/neu/vertraege/{v.id}/')
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
        # Nur auflösen, was bilanziert ist. Dieser Pfad und die Schlussabrechnung
        # hatten je eine EIGENE Belegtext-Sperre — jeder durfte einmal auflösen,
        # zusammen also zweimal (Audit). Der Saldo von 2010 ist die gemeinsame
        # Wahrheit und schliesst zugleich eine nie einbezahlte Kaution aus.
        if not v.ist_kautionsversicherung:
            bilanziert = _kaution_bilanziert(v)
            if bilanziert <= 0:
                messages.error(request, "❌ Für diesen Vertrag ist keine Kaution bilanziert "
                                        "(nicht einbezahlt oder bereits aufgelöst).")
                return redirect(f'/neu/vertraege/{v.id}/')
            total = min(total, bilanziert)
        # Bei Versicherung wird die Police aufgelöst — es gibt keine Rückzahlung an
        # den Mieter (er hat nur Prämien bezahlt); ein Einbehalt ist eine Schadenforderung.
        if v.ist_kautionsversicherung:
            rueck = Decimal('0.00')
        else:
            rueck = dec('rueckzahlung_betrag') if P.get('rueckzahlung_betrag') else (total - abzug)
        # Betragsvalidierung (B9): keine negativen Werte, und Rückzahlung + Einbehalt
        # dürfen die Kaution nicht übersteigen (sonst 2010/1015 mit falschem Saldo).
        if not v.ist_kautionsversicherung:
            if rueck < 0 or abzug < 0:
                messages.error(request, "❌ Rückzahlung und Einbehalt dürfen nicht negativ sein.")
                return redirect(f'/neu/vertraege/{v.id}/')
            if rueck + abzug > total + Decimal('0.01'):
                messages.error(request, f"❌ Rückzahlung (CHF {rueck}) + Einbehalt (CHF {abzug}) "
                                        f"übersteigt die Kaution (CHF {total}).")
                return redirect(f'/neu/vertraege/{v.id}/')
        v.kautions_zurueckbezahlt_am = d('zurueckbezahlt_am') or timezone.localdate()
        v.kautions_rueckzahlung_betrag = rueck
        v.kautions_abzug_betrag = abzug
        v.kautions_abzug_grund = P.get('abzug_grund', '').strip()
        # Statusfelder + alle Bilanz-/Ertragsbuchungen in EINER Transaktion — bricht
        # eine der (bis zu 3) Buchungen ab, wird nichts persistiert (kein Teilzustand:
        # Sperrkonto freigegeben, aber Rückzahlung fehlt). Der frühere Pfad buchte in
        # try/except: pass und liess bei Fehler den Vertrag «zurückbezahlt» ohne Hauptbuch.
        #  Sperrkonto:   1020 Bank an 1015 Sperrkonto (Freigabe des Depots)
        #  Rückzahlung:  2010 Kautionsverbindlichkeit an 1020 Bank (an Mieter)
        #  Einbehalt:    2010 Kautionsverbindlichkeit an 3600 (Ertrag Eigentümer)
        try:
            with transaction.atomic():
                v.save(update_fields=['kautions_zurueckbezahlt_am', 'kautions_rueckzahlung_betrag',
                                      'kautions_abzug_betrag', 'kautions_abzug_grund'])
                from finance.booking import buche as _buche
                from finance.models import Buchung as _B, DebitorenRechnung
                lg_k = v.einheit.liegenschaft if v.einheit_id else None
                # Vertrags-ID im Belegtext: nur so erkennt die Saldo-Prüfung
                # (_kaution_bilanziert) diese Auflösung und verhindert, dass die
                # Schlussabrechnung dieselbe Kaution ein zweites Mal freigibt.
                beleg = f"Kaution Auflösung [V{v.pk}] {v.mieter}"
                dat_k = v.kautions_zurueckbezahlt_am
                already = _B.objects.filter(beleg_text__startswith=beleg, ist_storno=False).exists()
                if v.ist_kautionsversicherung:
                    # Kein Depot → Einbehalt ist eine echte Schadenforderung an den Mieter.
                    if abzug > 0 and P.get('abzug_verrechnen') == 'on':
                        rech_e = DebitorenRechnung.objects.create(
                            vertrag=v, liegenschaft=lg_k, einheit=v.einheit,
                            betrag=abzug, datum=dat_k, faellig_am=dat_k + _timedelta(days=30),
                            status='offen', titel="Schadenersatz (Kautionsversicherung)",
                            beschreibung=v.kautions_abzug_grund or "Einbehalt aus Kaution")
                        _buche("1100", "3600", abzug, f"Schadenersatz {v.mieter}",
                               datum=dat_k, liegenschaft=lg_k, debitor=rech_e, user=request.user)
                elif (v.kautions_betrag or 0) > 0 and not already:
                    _buche("1020", "1015", v.kautions_betrag, f"{beleg} — Sperrkonto freigegeben",
                           datum=dat_k, liegenschaft=lg_k, user=request.user)
                    if rueck > 0:
                        _buche("2010", "1020", rueck, f"{beleg} — Rückzahlung an Mieter",
                               datum=dat_k, liegenschaft=lg_k, user=request.user)
                    if abzug > 0:
                        _buche("2010", "3600", abzug, f"{beleg} — Einbehalt (Ertrag)",
                               datum=dat_k, liegenschaft=lg_k, user=request.user)
        except PermissionError as exc:
            messages.error(request, f"❌ {exc}")
            return redirect(f'/neu/vertraege/{v.id}/')
        except Exception as exc:
            messages.error(request, f"❌ Kautions-Rückzahlung konnte nicht gebucht werden: {exc}")
            return redirect(f'/neu/vertraege/{v.id}/')
        from core.services.automation import erledige_pendenzen_fuer
        erledige_pendenzen_fuer(v, ['Kaution'], user=request.user)
        log_aktion(request, "Kaution zurückbezahlt", str(v.mieter),
                   f"Rückzahlung CHF {rueck}, Abzug CHF {abzug}", ziel=v)
        messages.success(request, f"✅ Rückzahlung erfasst: CHF {rueck} an Mieter, CHF {abzug} einbehalten.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_kaution_beleg(request, vertrag_id, art):
    """Kautions-Beleg als PDF (Art. 257e OR): `hinterlegung` = Bestätigung an die
    Mieterschaft, `freigabe` = Freigabeschreiben an die Bank. Wird in der Akte abgelegt."""
    from django.http import HttpResponse
    from crm.models import Verwaltung
    from core.services.mietprozess_briefe import kaution_hinterlegung_pdf, kaution_freigabe_pdf
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    vw = Verwaltung.objects.first()
    if art == 'freigabe':
        pdf = kaution_freigabe_pdf(v, verwaltung=vw)
        titel = f"Kaution-Freigabe (Bank) {v.mieter.nachname}"
    else:
        pdf = kaution_hinterlegung_pdf(v, verwaltung=vw)
        titel = f"Kaution-Bestätigung {v.mieter.nachname}"
    ablegen(pdf, titel, kategorie='vertrag', vertrag=v, dedup=True)
    log_aktion(request, "Kautions-Beleg erstellt", str(v.mieter), titel, ziel=v)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{titel.replace(" ", "_")}.pdf"'
    return resp


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_maengelruege(request, vertrag_id):
    """Mängelrüge / Fristansetzung (Art. 259 OR). GET: Formular · POST: PDF + Frist-Pendenz."""
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Verwaltung
    from core.services.mietprozess_briefe import maengelruege_pdf
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    from datetime import timedelta
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    if request.method == 'POST':
        mangel = (request.POST.get('mangel') or '').strip()
        try:
            frist = max(1, int(request.POST.get('frist_tage') or 14))
        except ValueError:
            frist = 14
        if not mangel:
            messages.error(request, "❌ Bitte den Mangel beschreiben.")
            return redirect(f'/neu/vertraege/{v.id}/maengelruege/')
        vw = Verwaltung.objects.first()
        pdf = maengelruege_pdf(v, mangel, frist_tage=frist, verwaltung=vw)
        ablegen(pdf, f"Mängelrüge {v.mieter.nachname} {timezone.localdate():%d.%m.%Y}",
                kategorie='vertrag', vertrag=v, dedup=False)
        # Frist-Pendenz zur Nachkontrolle der Mängelbehebung.
        try:
            from core.models import Pendenz
            faellig = timezone.localdate() + timedelta(days=frist)
            Pendenz.objects.create(
                titel=f"Mängelbehebung prüfen — {v.einheit.bezeichnung if v.einheit_id else ''}",
                beschreibung=(mangel[:200]), vertrag=v, faellig_am=faellig, kategorie='frist')
        except Exception:
            pass
        log_aktion(request, "Mängelrüge erstellt", str(v.mieter), f"Frist {frist} Tage", ziel=v)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Maengelruege_{v.mieter.nachname}.pdf"'
        return resp
    return render(request, 'fw/maengelruege.html', {**basis, 'nav': 'vertraege', 'v': v})


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_vertrag_wg(request, vertrag_id):
    """WG-Mieter verwalten: weitere gleichberechtigte Mitmieter hinzufügen/entfernen
    und die Solidarhaftung (Art. 143 ff. OR) umschalten. Additiv zum FK-Mitmieter
    (2. Mieter/Ehegatte)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Mieter
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter'), id=vertrag_id)
    if request.method != 'POST':
        return redirect(f'/neu/vertraege/{v.id}/')
    aktion = request.POST.get('aktion', '')
    if aktion == 'hinzufuegen':
        pid = request.POST.get('mieter_id')
        person = Mieter.objects.filter(id=pid).first() if (pid or '').isdigit() else None
        ausgeschlossen = {v.mieter_id, v.mitmieter_id}
        if not person:
            messages.error(request, "❌ Bitte eine bestehende Person auswählen.")
        elif person.id in ausgeschlossen:
            messages.warning(request, "Diese Person ist bereits Vertragspartei.")
        else:
            v.weitere_mieter.add(person)
            # Wohnadresse ab Mietbeginn auch für den WG-Mieter setzen.
            try:
                from crm.models import MieterAdresse
                e = v.einheit
                obj_strasse = f"{e.liegenschaft.strasse}{(', ' + e.etage) if e.etage else ''}"
                MieterAdresse.objects.get_or_create(
                    mieter=person, art='wohn', gueltig_ab=v.beginn,
                    defaults=dict(strasse=obj_strasse, plz=e.liegenschaft.plz, ort=e.liegenschaft.ort,
                                  quelle=f'vertrag:{v.id}', notiz='Einzug (WG) gemäss Mietvertrag'))
                person.sync_effektive_adresse()
            except Exception:
                pass
            log_aktion(request, "WG-Mieter hinzugefügt", str(person), str(v), ziel=v)
            messages.success(request, f"✅ {person.display_name} als WG-Mieter erfasst.")
    elif aktion == 'entfernen':
        pid = request.POST.get('mieter_id')
        person = Mieter.objects.filter(id=pid).first() if (pid or '').isdigit() else None
        if person:
            v.weitere_mieter.remove(person)
            log_aktion(request, "WG-Mieter entfernt", str(person), str(v), ziel=v)
            messages.info(request, f"{person.display_name} als WG-Mieter entfernt.")
    elif aktion == 'solidarhaftung':
        v.solidarhaftung = request.POST.get('wert') == 'on'
        v.save(update_fields=['solidarhaftung'])
        messages.success(request, "Solidarhaftung aktualisiert.")
    return redirect(f'/neu/vertraege/{v.id}/')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_untermiete(request, vertrag_id):
    """Zustimmung/Ablehnung zur Untervermietung (Art. 262 OR). GET: Formular · POST: PDF."""
    from django.http import HttpResponse
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Verwaltung
    from core.services.mietprozess_briefe import untermiete_zustimmung_pdf
    from core.services.ablage import ablegen
    from core.auth import log_aktion
    v = get_object_or_404(Mietvertrag.objects.select_related('mieter', 'einheit__liegenschaft'), id=vertrag_id)
    basis = _global_filter(request)
    if request.method == 'POST':
        untermieter = (request.POST.get('untermieter') or '').strip()
        entscheid = request.POST.get('entscheid') if request.POST.get('entscheid') in ('zustimmung', 'ablehnung') else 'zustimmung'
        bedingungen = (request.POST.get('bedingungen') or '').strip()
        if not untermieter:
            messages.error(request, "❌ Bitte die untermietende Person angeben.")
            return redirect(f'/neu/vertraege/{v.id}/untermiete/')
        vw = Verwaltung.objects.first()
        pdf = untermiete_zustimmung_pdf(v, untermieter, entscheid=entscheid, bedingungen=bedingungen, verwaltung=vw)
        wort = 'Zustimmung' if entscheid == 'zustimmung' else 'Ablehnung'
        ablegen(pdf, f"Untermiete-{wort} {v.mieter.nachname}", kategorie='vertrag', vertrag=v, dedup=False)
        log_aktion(request, f"Untermiete-{wort}", str(v.mieter), untermieter, ziel=v)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="Untermiete_{v.mieter.nachname}.pdf"'
        return resp
    return render(request, 'fw/untermiete.html', {**basis, 'nav': 'vertraege', 'v': v})


# ============================================================
# MWST-AUSWERTUNG (Umsatzsteuer vs. Vorsteuer = Zahllast)
# ============================================================

def _mwst_beleg(jahr, quartal):
    return f"MWST-Abrechnung {jahr}" + (f" Q{quartal}" if quartal in ('1', '2', '3', '4') else "")


def _mwst_bereits_verbucht(jahr, quartal, liegenschaft=None):
    """True, wenn für diese Periode ODER eine sie überlappende Periode desselben
    Jahres bereits abgerechnet wurde.

    Audit-Befund: Der Check verglich nur den eigenen Belegtext. Wer zuerst das
    ganze Jahr verbuchte und danach die vier Quartale, bekam eine fünffache
    Ausbuchung — «MWST-Abrechnung 2024 Q1» beginnt nicht mit dem Jahresbeleg,
    also schlug die Prüfung nie an. Jahr und Quartal überlappen sich immer, ein
    Treffer auf einer der beiden Ebenen blockiert daher die andere.
    """
    from django.db.models import Q as _Q
    from finance.models import Buchung
    # `storniert_am` mitprüfen: Eine stornierte Abrechnung behält ist_storno=False
    # (das Flag trägt die Gegenbuchung). Ohne diese Bedingung blieb die Periode
    # nach einem Storno dauerhaft gesperrt und liess sich nie neu verbuchen (Audit).
    qs = Buchung.objects.filter(beleg_text__startswith=f"MWST-Abrechnung {jahr}",
                                ist_storno=False, storniert_am__isnull=True)
    if liegenschaft:
        qs = qs.filter(liegenschaft=liegenschaft)
    if quartal not in ('1', '2', '3', '4'):
        return qs.exists()                      # Jahr: jede Quartalsabrechnung zählt
    # Quartal: nur das EIGENE Quartal oder eine Jahresabrechnung blockiert.
    # Der Jahresbeleg ist ein Präfix der Quartalsbelege, deshalb wird er über
    # den Trenner « — » abgegrenzt — sonst würde Q1 auch Q2 blockieren.
    return qs.filter(_Q(beleg_text__startswith=f"{_mwst_beleg(jahr, quartal)} ")
                     | _Q(beleg_text__startswith=f"{_mwst_beleg(jahr, '')} —")).exists()


def _mwst_periode(jahr, quartal, liegenschaft=None):
    """Rechnet eine MWST-Periode aus dem Hauptbuch — EINE Quelle für Anzeige,
    Verbuchung und ESTV-Export.

    Audit-Befund: Anzeige, Verbuchung und CSV-Export rechneten vorher jeweils
    eigenständig. Die Verbuchung übernahm die Beträge sogar ungeprüft aus dem
    POST (manipulierbar) und dem Export fehlte die Brutto-Rückrechnung des
    Saldosteuersatzes — die eingereichte Abrechnung wich damit von der
    angezeigten ab.
    """
    from finance.models import Buchungskonto, Buchung
    from django.db.models import Sum
    from crm.models import Verwaltung
    from core.services.mwst_estv import berechne_estv, MWST_NORMALSATZ

    if quartal in ('1', '2', '3', '4'):
        q = int(quartal)
        von = date(jahr, (q - 1) * 3 + 1, 1)
        m_end = q * 3
        bis = date(jahr, m_end, _calendar.monthrange(jahr, m_end)[1])
    else:
        von, bis = date(jahr, 1, 1), date(jahr, 12, 31)

    qs = Buchung.objects.filter(datum__gte=von, datum__lte=bis, ist_storno=False,
                                storniert_am__isnull=True)
    if liegenschaft:
        qs = qs.filter(liegenschaft=liegenschaft)
    # Die eigenen Abrechnungsbuchungen dürfen die Basis der nächsten Periode
    # nicht verfälschen (sonst frisst sich die Ausbuchung selbst).
    qs = qs.exclude(beleg_text__startswith=f"MWST-Abrechnung {jahr}")

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

    vw = Verwaltung.objects.first()
    methode = getattr(vw, 'mwst_methode', 'effektiv') if vw else 'effektiv'
    # Nettoumsatz aus der geschuldeten Steuer zurückrechnen — erfasst NK (3020),
    # optierte Wohnverhältnisse (3000) und Zuschläge (3600) gleichermassen.
    # Konto 3010 allein verfehlte diese (Audit K4).
    if umsatzsteuer > 0:
        umsatz_steuerbar = (umsatzsteuer / (MWST_NORMALSATZ / Decimal('100'))).quantize(Decimal('0.01'))
    else:
        umsatz_steuerbar = saldo('3010', soll_positiv=False)
    # Saldosteuersatz wird auf das BRUTTO-Entgelt (inkl. MWST) angewendet (ESTV-Regel).
    umsatz_brutto = (umsatz_steuerbar + umsatzsteuer).quantize(Decimal('0.01'))
    saldosatz = getattr(vw, 'saldosteuersatz', Decimal('0')) if vw else Decimal('0')
    estv = berechne_estv(
        umsatz_steuerbar=umsatz_steuerbar, umsatzsteuer=umsatzsteuer,
        vorsteuer_material=vorsteuer, vorsteuer_invest=Decimal('0'),
        methode=methode, saldosteuersatz=saldosatz, umsatz_brutto=umsatz_brutto)
    if methode == 'saldo':
        zahllast = estv['z500']

    return {
        'von': von, 'bis': bis,
        'umsatzsteuer': umsatzsteuer, 'vorsteuer': vorsteuer, 'zahllast': zahllast,
        'umsatz_steuerbar': umsatz_steuerbar, 'umsatz_brutto': umsatz_brutto,
        'estv': estv, 'methode': methode, 'saldosteuersatz': saldosatz,
        'saldo_vorteil': ((umsatzsteuer - zahllast).quantize(Decimal('0.01'))
                          if methode == 'saldo' else Decimal('0.00')),
        'verwaltung': vw,
    }


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mwst(request):
    """MWST-Abrechnung: geschuldete Umsatzsteuer (2200) minus Vorsteuer (1170) = Zahllast."""
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    quartal = request.GET.get('quartal', '')  # '', '1'..'4'
    p = _mwst_periode(jahr, quartal, aktive_lg)
    vw = p['verwaltung']

    return render(request, 'fw/mwst.html', {
        **basis, 'nav': 'mwst', 'jahr': jahr, 'quartal': quartal,
        'von': p['von'], 'bis': p['bis'],
        'umsatzsteuer': p['umsatzsteuer'], 'vorsteuer': p['vorsteuer'],
        'zahllast': p['zahllast'],
        'umsatz_steuerbar': p['umsatz_steuerbar'], 'umsatz_brutto': p['umsatz_brutto'],
        'estv': p['estv'], 'saldo_vorteil': p['saldo_vorteil'],
        'mwst_verbucht': _mwst_bereits_verbucht(jahr, quartal, aktive_lg),
        'mwst_methode': p['methode'], 'saldosteuersatz': p['saldosteuersatz'],
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
        vw.saldosteuersatz = Decimal((_num(request.POST.get('saldosteuersatz')) or '0'))
    except Exception:
        vw.saldosteuersatz = Decimal('0')
    vw.save(update_fields=['mwst_methode', 'mwst_uid', 'saldosteuersatz'])
    messages.success(request, "✅ MWST-Einstellungen gespeichert.")
    ziel = request.POST.get('zurueck') or '/neu/mwst/'
    return redirect(ziel)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mwst_estv_export(request):
    """ESTV-Abrechnung als CSV (offizielle Ziffern) für den gewählten Zeitraum.

    Rechnet über denselben Helper wie Anzeige und Verbuchung. Vorher hatte der
    Export eine eigene Rechnung ohne die Brutto-Rückrechnung des Saldosteuersatzes
    und ohne Liegenschaftsfilter — die eingereichte Abrechnung wich damit von der
    angezeigten ab (Audit).
    """
    from django.http import HttpResponse
    from core.services.mwst_estv import estv_csv
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()
    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year
    quartal = request.GET.get('quartal', '')
    p = _mwst_periode(jahr, quartal, aktive_lg)
    von, bis, estv, vw = p['von'], p['bis'], p['estv'], p['verwaltung']
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
    ('besichtigung', 'Besichtigung', 'bg-violet-50 text-violet-700'),
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
        **basis, **_vermietung_pipeline('bewerbungen', basis['lg_query']), 'nav': 'bewerbungen', 'spalten': spalten, 'gesamt': len(alle),
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_bewerber_vergleich(request, einheit_id):
    """Vergleicht alle Bewerber eines Objekts mit Eignungs-Score (Tragbarkeit,
    Betreibungen, Anstellung, Unterlagen) als Entscheidungshilfe für die Mieterwahl."""
    from mietprozess.models import Mietbewerbung
    from core.services.bewerber_scoring import bewerte_bewerbung
    e = get_object_or_404(Einheit.objects.select_related('liegenschaft'), id=einheit_id)
    basis = _global_filter(request)
    brutto_monat = (e.nettomiete_aktuell or Decimal('0')) + (e.nebenkosten_aktuell or Decimal('0'))

    qs = Mietbewerbung.objects.filter(einheit=e).order_by('-erstellt_am')
    mit_abgelehnt = request.GET.get('alle') == '1'
    if not mit_abgelehnt:
        qs = qs.exclude(status='abgelehnt')

    kandidaten = []
    for b in qs:
        bewertung = bewerte_bewerbung(b, brutto_monat)
        s_label, s_cls = dict((k, (l, c)) for k, l, c in BEWERBUNG_SPALTEN).get(b.status, (b.status, 'bg-slate-100 text-slate-500'))
        kandidaten.append({
            'b': b, 'name': f"{b.vorname} {b.nachname}",
            'haushalt': b.anzahl_erwachsene + b.anzahl_kinder,
            'bezug': b.gewuenschter_bezugstermin,
            'haustiere': b.haustiere, 'status': b.status,
            's_label': s_label, 's_cls': s_cls,
            **bewertung,
        })
    kandidaten.sort(key=lambda k: -k['score'])
    # Indikator-Spaltentitel aus dem ersten Kandidaten (fixe Reihenfolge)
    indikator_labels = [i['label'] for i in kandidaten[0]['indikatoren']] if kandidaten else []
    offene_n = sum(1 for k in kandidaten if k['status'] in ('neu', 'geprueft'))

    from django.contrib import messages
    return render(request, 'fw/bewerber_vergleich.html', {
        **basis, 'nav': 'vermarktung', 'e': e,
        'objekt': f"{e.liegenschaft.strasse}, {e.liegenschaft.ort}" if e.liegenschaft_id else e.bezeichnung,
        'brutto_monat': brutto_monat, 'jahresmiete': brutto_monat * 12,
        'kandidaten': kandidaten, 'indikator_labels': indikator_labels,
        'mit_abgelehnt': mit_abgelehnt, 'offene_n': offene_n,
        'meldung': list(messages.get_messages(request)),
    })


def _bewerber_mail(b, entscheid):
    """Baut (betreff, body) für Zusage/Absage — aus Vorlage (falls vorhanden) mit
    Platzhaltern, sonst Standardtext."""
    from crm.models import Vorlage, Verwaltung
    vw = Verwaltung.objects.first()
    e = b.einheit
    lg = e.liegenschaft if e else None
    objekt = f"{e.bezeichnung}" + (f", {lg.strasse}, {lg.plz} {lg.ort}" if lg else "")
    brutto = (e.nettomiete_aktuell or Decimal('0')) + (e.nebenkosten_aktuell or Decimal('0')) if e else Decimal('0')
    ctx = {
        'bewerber_name': f"{b.vorname} {b.nachname}",
        'objekt': objekt, 'liegenschaft': lg.strasse if lg else '',
        'miete': f"CHF {brutto:.2f}", 'vermieter': (vw.firma if vw else 'Ihre Liegenschaftsverwaltung'),
        'datum': timezone.now().strftime('%d.%m.%Y'),
    }
    kat = 'bewerber_zusage' if entscheid == 'zusage' else 'bewerber_absage'
    v = Vorlage.objects.filter(kategorie=kat).first()
    if v and v.inhalt:
        body = v.inhalt
        betreff = v.betreff or (f"Ihre Bewerbung für {objekt}")
        for k, val in ctx.items():
            body = body.replace('{' + k + '}', str(val))
            betreff = betreff.replace('{' + k + '}', str(val))
    elif entscheid == 'zusage':
        betreff = f"Zusage für Ihre Wohnungsbewerbung – {objekt}"
        body = (f"Guten Tag {ctx['bewerber_name']}\n\nWir freuen uns, Ihnen das Mietobjekt "
                f"{objekt} zusagen zu können. Wir melden uns in Kürze mit den Vertragsunterlagen.\n\n"
                f"Freundliche Grüsse\n{ctx['vermieter']}")
    else:
        betreff = f"Ihre Wohnungsbewerbung – {objekt}"
        body = (f"Guten Tag {ctx['bewerber_name']}\n\nVielen Dank für Ihre Bewerbung für {objekt} "
                f"und Ihr Interesse. Wir haben uns für eine andere Bewerbung entschieden und wünschen "
                f"Ihnen bei der weiteren Wohnungssuche viel Erfolg.\n\nFreundliche Grüsse\n{ctx['vermieter']}")
    return betreff, body


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerber_besichtigung(request, pk):
    """Lädt einen Bewerber zur Besichtigung ein: Termin speichern, Status setzen,
    Einladung per E-Mail (mit Journal-Eintrag)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.utils.email_service import send_ticket_email, journal_email
    from core.auth import log_aktion
    from datetime import datetime as _dt
    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft'), id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    termin_raw = (request.POST.get('termin') or '').strip()   # datetime-local: YYYY-MM-DDTHH:MM
    termin = None
    if termin_raw:
        try:
            termin = timezone.make_aware(_dt.fromisoformat(termin_raw))
        except Exception:
            termin = None
    if termin is None:
        messages.error(request, "Bitte einen gültigen Besichtigungstermin wählen.")
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    b.besichtigung_am = termin
    if b.status in ('neu', 'geprueft'):
        b.status = 'besichtigung'
    b.save(update_fields=['besichtigung_am', 'status'])
    lg = b.einheit.liegenschaft
    ok = False
    if b.email:
        betreff = f"Einladung zur Besichtigung — {lg.strasse}, {b.einheit.bezeichnung}"
        body = (f"Guten Tag {b.vorname} {b.nachname}\n\n"
                f"Gerne laden wir Sie zur Besichtigung des Objekts "
                f"{lg.strasse}, {lg.plz} {lg.ort} ({b.einheit.bezeichnung}) ein.\n\n"
                f"Termin: {timezone.localtime(termin).strftime('%A, %d.%m.%Y um %H:%M Uhr')}\n"
                f"Treffpunkt: Hauseingang {lg.strasse}\n\n"
                f"Bitte bestätigen Sie uns den Termin kurz per E-Mail. Falls er Ihnen "
                f"nicht passt, melden Sie sich für eine Alternative.\n\n"
                f"Freundliche Grüsse\nIhre Verwaltung")
        ok = send_ticket_email(b.email, betreff, body)
        if ok:
            journal_email(betreff, body, user=request.user,
                          empfaenger=f"{b.vorname} {b.nachname} <{b.email}> (Bewerbung)")
    # Termin ins Fristen-Center (idempotent pro Bewerbung — Termin-Änderung
    # aktualisiert die bestehende Pendenz statt eine zweite zu erzeugen).
    from core.models import Pendenz
    Pendenz.objects.update_or_create(
        quelle=f'besichtigung:{b.id}',
        defaults={
            'titel': f"Besichtigung {b.vorname} {b.nachname} — {b.einheit.bezeichnung}",
            'beschreibung': (f"Besichtigungstermin {timezone.localtime(termin).strftime('%d.%m.%Y %H:%M')} · "
                             f"{lg.strasse}, {lg.plz} {lg.ort}. Treffpunkt Hauseingang."),
            'kategorie': 'frist', 'faellig_am': termin.date(),
            'liegenschaft': lg, 'erledigt': False,
            'erstellt_von': request.user if request.user.is_authenticated else None,
        })
    log_aktion(request, "Besichtigung eingeladen", f"{b.vorname} {b.nachname}",
               timezone.localtime(termin).strftime('%d.%m.%Y %H:%M'))
    messages.success(request, f"✅ Besichtigung {timezone.localtime(termin).strftime('%d.%m.%Y %H:%M')} erfasst"
                              + (f" · Einladung an {b.email} gesendet." if ok else "."))
    return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerber_entscheid(request, pk):
    """Zusage/Absage einer Bewerbung: setzt Status + sendet dem Bewerber eine
    (Vorlagen-)E-Mail. entscheid = 'zusage' | 'absage'."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion
    b = get_object_or_404(Mietbewerbung.objects.select_related('einheit__liegenschaft'), id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    entscheid = request.POST.get('entscheid')
    if entscheid not in ('zusage', 'absage'):
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    ziel_status = 'zugesagt' if entscheid == 'zusage' else 'abgelehnt'
    # Idempotenz: dieselbe Entscheidung nicht doppelt setzen (sonst geht bei jedem
    # Klick erneut eine Zu-/Absage-Mail an den Bewerber raus).
    if b.status == ziel_status:
        messages.info(request, f"Diese Bewerbung wurde bereits {'zugesagt' if entscheid == 'zusage' else 'abgesagt'}.")
        return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')
    b.status = ziel_status
    b.save(update_fields=['status'])
    ok = False
    if b.email:
        betreff, body = _bewerber_mail(b, entscheid)
        ok = send_ticket_email(b.email, betreff, body)
        if ok:
            from core.utils.email_service import journal_email
            journal_email(betreff, body, user=request.user,
                          empfaenger=f"{b.vorname} {b.nachname} <{b.email}> (Bewerbung)")
    log_aktion(request, f"Bewerber-{entscheid.capitalize()}", f"{b.vorname} {b.nachname}",
               b.einheit.bezeichnung if b.einheit_id else '')
    wort = "Zusage" if entscheid == 'zusage' else "Absage"
    messages.success(request, f"✅ {wort} gesetzt" + (f" · E-Mail an {b.email} gesendet." if ok else "."))
    return redirect(f'/neu/vermarktung/{b.einheit_id}/bewerber/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_bewerber_absage_uebrige(request, einheit_id):
    """Sendet allen noch offenen (neu/geprüft) Bewerbern eines Objekts eine Absage
    — z. B. nach der Zusage an den gewählten Bewerber."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from mietprozess.models import Mietbewerbung
    from core.utils.email_service import send_ticket_email
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect(f'/neu/vermarktung/{einheit_id}/bewerber/')
    offene = Mietbewerbung.objects.filter(einheit_id=einheit_id, status__in=['neu', 'geprueft'])
    n = mails = 0
    for b in offene.select_related('einheit__liegenschaft'):
        b.status = 'abgelehnt'
        b.save(update_fields=['status'])
        n += 1
        if b.email:
            betreff, body = _bewerber_mail(b, 'absage')
            if send_ticket_email(b.email, betreff, body):
                mails += 1
                from core.utils.email_service import journal_email
                journal_email(betreff, body, user=request.user,
                              empfaenger=f"{b.vorname} {b.nachname} <{b.email}> (Bewerbung)")
    log_aktion(request, "Bewerber-Sammelabsage", f"Objekt #{einheit_id}", f"{n} abgesagt")
    messages.success(request, f"✅ {n} offene Bewerbung(en) abgesagt" + (f" · {mails} E-Mail(s) versendet." if mails else "."))
    return redirect(f'/neu/vermarktung/{einheit_id}/bewerber/')


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

    # Idempotenz am ECHTEN Marker (nicht am Status): existiert für DIESEN Bewerber
    # bereits ein Vertragsentwurf auf dieser Einheit, nicht erneut anlegen.
    # Wichtig: `fw_bewerber_entscheid` (Bewerber-Vergleich) setzt 'zugesagt' OHNE
    # Entwurf — der Status allein blockierte dann fälschlich die Umwandlung und
    # leitete auf einen fremden Entwurf derselben Einheit um.
    _bestehender = None
    if b.email:
        _bestehender = (Mietvertrag.objects
                        .filter(einheit=einheit, status='entwurf',
                                mieter__email__iexact=b.email,
                                mieter__nachname__iexact=b.nachname)
                        .order_by('-id').first())
    if _bestehender is None:
        _bestehender = (Mietvertrag.objects
                        .filter(einheit=einheit, status='entwurf',
                                mieter__vorname__iexact=b.vorname or '',
                                mieter__nachname__iexact=b.nachname or '')
                        .order_by('-id').first())
    if _bestehender:
        messages.info(request, "Für diese Bewerbung existiert bereits ein Vertragsentwurf.")
        return redirect(f'/neu/vertraege/{_bestehender.id}/')

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
            # Haushalt/Haustiere aus der Bewerbung in den Mieter-Stamm übernehmen.
            haushalt_erwachsene=b.anzahl_erwachsene or 0, haushalt_kinder=b.anzahl_kinder or 0,
            haustiere=bool(b.haustiere), haustiere_details=(b.haustiere_details or ''),
            # Bonität + Vorvermieter-Referenz aus der Bewerbung übernehmen (sonst
            # gehen sie beim Übergang Bewerber → Mieter verloren).
            betreibung_ergebnis=('offen' if b.hat_betreibungen else 'keine'),
            ref_vermieter_name=(b.aktueller_vermieter or ''),
            ref_vermieter_telefon=(b.telefon_vermieter or ''),
            ref_vermieter_email=(b.email_vermieter or ''),
        )

    # 2. Vertragsentwurf anlegen (mit Objekt-Defaults)
    from decimal import Decimal as _D
    beginn = b.gewuenschter_bezugstermin or timezone.localdate()
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
    # Objekt ist vergeben → aus der Vermarktung/Feed/Exposé nehmen.
    if einheit.zur_ausschreibung:
        einheit.zur_ausschreibung = False
        einheit.save(update_fields=['zur_ausschreibung'])
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
    heute = timezone.localdate()
    grenze = heute + _timedelta(days=horizont_tage)
    fristen = []

    aktive = Mietvertrag.objects.filter(status='aktiv').select_related('mieter', 'einheit__liegenschaft')
    gek = Mietvertrag.objects.filter(status='gekuendigt').select_related('mieter', 'einheit__liegenschaft')
    if aktive_lg:
        aktive = aktive.filter(einheit__liegenschaft=aktive_lg)
        gek = gek.filter(einheit__liegenschaft=aktive_lg)

    # a) Befristete Vertragsenden im Horizont (nur echte befristete Verhältnisse)
    for v in aktive.filter(ist_befristet=True, ende__range=[heute, grenze]).order_by('ende'):
        fristen.append({
            'kategorie': 'Befristetes Vertragsende', 'farbe': 'amber', 'icon': 'fa-hourglass-end',
            'titel': f"Vertrag {v.mieter.display_name} endet",
            'sub': f"{v.einheit.bezeichnung}, {v.einheit.liegenschaft.strasse}",
            'faellig': v.ende, 'url': f'/neu/vertraege/{v.id}/',
            'tage': (v.ende - heute).days, 'vertrag_id': v.id, 'kind': 'vertragsende',
        })

    # b) Gekündigte Verträge — Auszug/Übergabe steht an
    for v in gek.filter(ende__range=[heute, grenze]).order_by('ende'):
        fristen.append({
            'kategorie': 'Auszug (gekündigt)', 'farbe': 'rose', 'icon': 'fa-person-walking-arrow-right',
            'titel': f"Auszug {v.mieter.display_name}",
            'sub': f"{v.einheit.bezeichnung} — Abnahme & Kautionsabrechnung vorbereiten",
            'faellig': v.ende, 'url': f'/neu/vertraege/{v.id}/',
            'tage': (v.ende - heute).days, 'vertrag_id': v.id, 'kind': 'auszug',
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
    """Verknüpft eine Pendenz mit dem passenden Objekt/Schritt.
    Rückgabe: (url, label, wide, modal). `modal=True` → im Iframe-Popup öffnen
    (nur für Aktions-/Schritt-Formulare, deren Chrome im Embed ausgeblendet wird);
    `modal=False` → volle Seiten-Navigation. Eine Detailseite (Vertrag/Liegenschaft)
    gehört NICHT ins Popup — ihr Hero + Tabs + Tabellen werden im engen Iframe
    (v.a. mobil) abgeschnitten und kollidieren mit dem Pendenz-Titel."""
    q = p.quelle or ''
    if p.vertrag_id:
        if q.startswith('auto:ruecknahme:'):
            return (f'/neu/vertraege/{p.vertrag_id}/abnahme/neu/?typ=auszug', 'Rücknahme starten', False, True)
        return (f'/neu/vertraege/{p.vertrag_id}/', 'Vertrag öffnen', False, False)
    if p.liegenschaft_id:
        return (f'/neu/liegenschaften/{p.liegenschaft_id}/', 'Liegenschaft öffnen', False, False)
    return (None, None, False, False)


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_pendenzen(request):
    from core.models import Pendenz
    from crm.models import Mandant  # noqa
    basis = _global_filter(request)
    aktive_lg = basis['aktive_lg']
    heute = timezone.localdate()

    auto = _auto_fristen(aktive_lg)

    pq = Pendenz.objects.all().select_related('liegenschaft', 'vertrag__mieter')
    if aktive_lg:
        pq = pq.filter(Q(liegenschaft=aktive_lg) | Q(vertrag__einheit__liegenschaft=aktive_lg) | Q(liegenschaft__isnull=True, vertrag__isnull=True))
    offene = list(pq.filter(erledigt=False))
    erledigte = list(pq.filter(erledigt=True)[:20])

    # Doppelanzeige vermeiden: Vertragsende/Auszug erscheinen sowohl als read-only
    # Auto-Frist (_auto_fristen) als auch — nach dem Tageslauf — als persistente
    # Pendenz (auto:vertragsende:/auto:auszug:). Wo eine persistente Pendenz existiert,
    # die Auto-Frist herausfiltern (die Pendenz ist abhakbar, die Frist nicht).
    _pers = {(p.vertrag_id, 'vertragsende') for p in offene if (p.quelle or '').startswith('auto:vertragsende:')}
    _pers |= {(p.vertrag_id, 'auszug') for p in offene if (p.quelle or '').startswith('auto:auszug:')}
    if _pers:
        auto = [f for f in auto if (f.get('vertrag_id'), f.get('kind')) not in _pers]

    for p in offene:
        p.ueberfaellig = bool(p.faellig_am and p.faellig_am < heute)
        p.ziel_url, p.ziel_label, p.ziel_wide, p.ziel_modal = _pendenz_ziel(p)

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
    heute = timezone.localdate()

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
        url, label, wide, _modal = _pendenz_ziel(p)
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
    p.erledigt_am = timezone.localdate() if p.erledigt else None
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

    # Doppelerfassung derselben Mahnstufe verhindern (Doppelklick / erneutes Absenden).
    # Sonst entstünde ein zweiter Historien-Eintrag + eine doppelte Mahngebühr-Rechnung.
    if Mahnung.objects.filter(debitoren_rechnung=rechnung, stufe=stufe).exists():
        messages.info(request, f"Die {stufe}. Mahnung wurde für diese Rechnung bereits erfasst.")
        return redirect('fw_mahnwesen')

    try:
        gebuehr = Decimal((_num(request.POST.get('gebuehr')) or str(MAHN_GEBUEHR.get(stufe, Decimal('0')))))
    except Exception:
        gebuehr = MAHN_GEBUEHR.get(stufe, Decimal('0.00'))

    heute = timezone.localdate()
    # Mahnung + Mahngebühr-Rechnung + Hauptbuchbuchung in EINER Transaktion —
    # scheitert die Buchung (Periodensperre), bleibt keine Mahnung/Gebühr ohne
    # Gegenbuchung stehen. Das DB-Unique (debitoren_rechnung, stufe) fängt zudem
    # den Doppelklick-Race ab (der exists()-Check oben ist ohne Lock).
    from django.db import IntegrityError
    try:
        with transaction.atomic():
            Mahnung.objects.create(
                debitoren_rechnung=rechnung, vertrag=rechnung.vertrag, stufe=stufe,
                datum=heute, betrag_offen=rechnung.offener_betrag, gebuehr=gebuehr,
                versandart=request.POST.get('versandart', 'manuell'),
                erstellt_von=request.user,
            )
            # Mahngebühr als separate Debitorenrechnung (falls > 0) — inkl. Hauptbuch-
            # Buchung (Forderung an übrigen Ertrag), sonst driften Neben-/Hauptbuch.
            if gebuehr > 0 and rechnung.vertrag_id:
                lg_geb = rechnung.liegenschaft or (rechnung.vertrag.einheit.liegenschaft if rechnung.vertrag.einheit_id else None)
                geb_rechnung = DebitorenRechnung.objects.create(
                    vertrag=rechnung.vertrag,
                    liegenschaft=lg_geb,
                    titel=f"Mahngebühr {stufe}. Mahnung",
                    beschreibung=f"Mahngebühr zu: {rechnung.titel}",
                    datum=heute, faellig_am=heute + _timedelta(days=30),
                    betrag=gebuehr, status='offen',
                )
                from finance.booking import buche
                buche("1100", "3600", gebuehr, f"Mahngebühr {stufe}. Mahnung {rechnung.vertrag.mieter}",
                      datum=heute, liegenschaft=lg_geb, debitor=geb_rechnung, user=request.user)
    except IntegrityError:
        messages.info(request, f"Die {stufe}. Mahnung wurde für diese Rechnung bereits erfasst.")
        return redirect('fw_mahnwesen')
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect('fw_mahnwesen')
    except Exception as exc:
        messages.error(request, f"❌ Mahnung konnte nicht gebucht werden: {exc}")
        return redirect('fw_mahnwesen')

    # Beleg in die Vertrags-Akte. Ausserhalb der Transaktion und bewusst
    # fehlertolerant: Historie und Gebühr sind bereits gebucht, ein misslungenes
    # PDF darf den erfassten Mahnschritt nicht zurückrollen.
    if rechnung.vertrag_id:
        from core.services.ablage import ablage_mahnung
        ablage_mahnung(rechnung.vertrag, stufe=stufe, datum=heute,
                       betrag=f"{rechnung.offener_betrag:.2f}")

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


def _vermietung_pipeline(aktiv, lg_query=''):
    """Kontext für die Vermietungs-Pipeline-Leiste (Vermarktung → Bewerbung →
    Vertrag → Mieterwechsel) — auf allen vier Stufen-Seiten eingeblendet, damit
    der Prozess als EIN Ablauf erlebbar ist statt als vier Menüpunkte."""
    from mietprozess.models import Mietbewerbung
    from rentals.models import Kuendigung
    stufen = [
        {'key': 'vermarktung', 'label': 'Vermarktung', 'icon': 'fa-bullhorn',
         'url': '/neu/vermarktung/' + lg_query,
         'n': Einheit.objects.filter(zur_ausschreibung=True).count()},
        {'key': 'bewerbungen', 'label': 'Bewerbungen', 'icon': 'fa-user-check',
         'url': '/neu/bewerbungen/' + lg_query,
         'n': Mietbewerbung.objects.filter(status__in=['neu', 'geprueft']).count()},
        {'key': 'vertraege', 'label': 'Verträge', 'icon': 'fa-file-lines',
         'url': '/neu/vertraege/' + lg_query,
         'n': Mietvertrag.objects.filter(status='entwurf').count()},
        {'key': 'mieterwechsel', 'label': 'Mieterwechsel', 'icon': 'fa-right-left',
         'url': '/neu/mieterwechsel/' + lg_query,
         'n': Kuendigung.objects.filter(status__in=['erfasst', 'bestaetigt']).count()},
    ]
    for s in stufen:
        s['aktiv'] = (s['key'] == aktiv)
    return {'pipeline_stufen': stufen}


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


def _park_konto(nummer):
    from finance.booking import konto as _k
    return _k(nummer)


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
    from finance.api import erstelle_storno_buchung
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
