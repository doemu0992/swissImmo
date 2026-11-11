# core/views/fw/berichte.py
#
# Berichte, Betriebsrechnung, Leerstand, Betriebskostenspiegel, Auswertung, Mieterspiegel.
# Aus listen.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.db.models.functions import ExtractMonth
from django.shortcuts import get_object_or_404, render
from django.utils import dateformat, timezone
from django.utils.translation import gettext as _, gettext_lazy

from core.auth import (rolle_erforderlich, TEAM_ROLLEN)
from core.auth import FINANZ_LESE_ROLLEN
from finance.models import DebitorenRechnung
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag


from ._basis import (_global_filter)
from core.tenancy import aktuelle_organisation
from core.utils.parameter import jahr_streng


def _berichte_v8(heute, aktive_lg):
    """Diagramme und Mandatstabelle nach konzept-v8 (#berichte). NUR LESEND.

      Zahlungsquote   `faelle.lage.verlaeufe()['eingang']` — dieselbe Reihe
                      wie die Verlaufslinie auf «Heute» (Ist in % vom Soll
                      je Fälligkeitsmonat, `None` = nichts fällig)
      Ausstände > 30  offener Betrag (nach Teilzahlungen) je Liegenschaft,
                      älter als 30 Tage seit Fälligkeit — dieselbe Grenze wie
                      die Spalten 31–60/61–90/>90 der Aging-Seite
      Mandate         `faelle.lage.mandate()` plus Liegenschaften, Soll/Monat
                      (Netto + NK der Einheiten, wie «Mieterspiegel» oben)
                      und Ausstände > 30 aus derselben Liegenschaftsrechnung

    Die Mandatstabelle zeigt ganze Mandate. Ist eine Liegenschaft gewählt,
    bleibt nur ihr Mandat stehen — aber ganz, sonst stünde «2 Liegenschaften»
    neben den Zahlen einer einzigen.

    Abfragen: verlaeufe 4, mandate 1, Liegenschaften 1, offene Rechnungen 2.
    """
    from faelle import lage as _lage

    enden = _lage._monatsenden(heute)
    reihe = _lage.verlaeufe(heute, aktive_lg).get('eingang') or []
    monate = [dateformat.format(e, 'M') for e in enden]

    lgs = list(Liegenschaft.objects.annotate(
        soll=Sum(Coalesce(F('einheiten__nettomiete_aktuell'), Decimal('0'))
                 + Coalesce(F('einheiten__nebenkosten_aktuell'), Decimal('0'))))
        .order_by('strasse'))
    ueber30 = defaultdict(lambda: Decimal('0.00'))
    offen = (DebitorenRechnung.objects.filter(status__in=['offen', 'teilbezahlt'])
             .select_related('vertrag__einheit')
             .prefetch_related('zahlungseingaenge'))
    for r in offen:
        faellig = r.faellig_am or r.datum
        if not faellig or (heute - faellig).days <= 30:
            continue
        betrag = r.offener_betrag
        if betrag <= 0:
            continue
        lg_id = r.liegenschaft_id or (r.vertrag.einheit.liegenschaft_id
                                      if r.vertrag_id and r.vertrag.einheit_id else None)
        if lg_id:
            ueber30[lg_id] += betrag

    balken = sorted(
        ({'lab': lg.strasse, 'wert': ueber30.get(lg.id, Decimal('0.00')),
          'url': f'/neu/liegenschaften/{lg.id}/'}
         for lg in lgs if not aktive_lg or lg.id == aktive_lg.id),
        key=lambda z: -z['wert'])

    je_mandat = defaultdict(lambda: {'lgs': 0, 'soll': Decimal('0.00'), 'ueber30': Decimal('0.00')})
    for lg in lgs:
        if lg.eigentuemer_id:
            m = je_mandat[lg.eigentuemer_id]
            m['lgs'] += 1
            m['soll'] += lg.soll or Decimal('0.00')
            m['ueber30'] += ueber30.get(lg.id, Decimal('0.00'))
    mandate = []
    for z in _lage.mandate(heute):
        if aktive_lg and z['mandat'].id != aktive_lg.eigentuemer_id:
            continue
        mandate.append({**z, **je_mandat[z['mandat'].id]})

    gemessen = [w for w in reihe if w is not None]
    return {
        'bericht_von': enden[0].replace(day=1), 'bericht_bis': enden[-1],
        'quote_werte': reihe, 'quote_monate': monate,
        'quote_min': min(gemessen) if gemessen else None,
        'quote_max': max(gemessen) if gemessen else None,
        'ausstand_balken': balken,
        'ausstand_summe': sum((b['wert'] for b in balken), Decimal('0.00')),
        'mandat_zeilen': mandate,
    }


@rolle_erforderlich(*FINANZ_LESE_ROLLEN)
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
    from core.services.archiv import ausblenden
    einh = ausblenden(Einheit.objects.all())
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
    auf = HandwerkerAuftrag.objects.exclude(status='storniert').filter(beauftragt_am__year=heute.year)
    if aktive_lg:
        auf = auf.filter(ticket__liegenschaft=aktive_lg)
    reparatur_eff = sum((a.kosten_effektiv or Decimal('0') for a in auf), Decimal('0.00'))

    lgq = basis['lg_query']
    berichte = [
        {'gruppe': _('Finanzen'), 'items': [
            {'icon': 'bericht', 'farbe': 'marke', 'titel': _('Erfolgsrechnung & Bilanz'),
             'sub': _('Ertrag/Aufwand, Aktiven/Passiven, Journal'), 'url': '/neu/buchhaltung/' + lgq,
             'kennzahl': None, 'pdf': True},
            {'icon': 'bericht', 'farbe': 'primaer', 'titel': _('MWST-Abrechnung'),
             'sub': _('Umsatz-/Vorsteuer, ESTV-Export'), 'url': '/neu/mwst/', 'kennzahl': None, 'pdf': False},
            {'icon': 'zaehler', 'farbe': 'info', 'titel': _('Finanz-Cockpit'),
             'sub': _('Offene Posten + Monatsabschluss'), 'url': '/neu/finanzen/' + lgq, 'kennzahl': None, 'pdf': False},
        ]},
        {'gruppe': _('Forderungen & Zahlungen'), 'items': [
            {'icon': 'bericht', 'farbe': 'rose', 'titel': _('Debitoren-Altersstruktur'),
             'sub': _('Offene Forderungen nach Fälligkeitsalter'), 'url': '/neu/mahnwesen/aging/' + lgq,
             'kennzahl': _('CHF %(betrag)s überfällig') % {'betrag': f"{deb_ueberf:,.0f}".replace(',', "'")}, 'pdf': False},
            {'icon': 'rechnung', 'farbe': 'marke', 'titel': _('Mieterkonten'),
             'sub': _('Kontoblatt je Mieter (Forderungen/Zahlungen)'), 'url': '/neu/mieterkonten/' + lgq,
             'kennzahl': _('CHF %(betrag)s offen') % {'betrag': f"{deb_offen:,.0f}".replace(',', "'")}, 'pdf': True},
            {'icon': 'rechnung', 'farbe': 'amber', 'titel': _('Lieferantenkonten'),
             'sub': _('Kontoblatt je Lieferant (Kreditoren)'), 'url': '/neu/lieferantenkonten/' + lgq,
             'kennzahl': _('CHF %(betrag)s offen') % {'betrag': f"{kred_offen:,.0f}".replace(',', "'")}, 'pdf': False},
        ]},
        {'gruppe': _('Portfolio'), 'items': [
            {'icon': 'filtern', 'farbe': 'emerald', 'titel': _('Mieterspiegel'),
             'sub': _('Rent Roll je Liegenschaft (Soll/Ist/Leerstand)'), 'url': '/neu/mieterspiegel/' + lgq,
             'kennzahl': _('CHF %(betrag)s Soll · %(quote)s%% leer') % {'betrag': f"{soll_mietzins:,.0f}".replace(',', "'"), 'quote': leerstandsquote}, 'pdf': True},
            {'icon': 'recht', 'farbe': 'teal', 'titel': _('Eigentümer-Abrechnungen'),
             'sub': _('Mandatsabrechnung & Kontokorrent je Eigentümer'), 'url': '/neu/mandate/',
             'kennzahl': None, 'pdf': True},
        ]},
        {'gruppe': _('Objekte & Unterhalt'), 'items': [
            {'icon': 'geld', 'farbe': 'orange', 'titel': _('Reparaturkosten'),
             'sub': _('Kosten je Liegenschaft (offen/effektiv)'), 'url': '/neu/schaeden/kosten/' + lgq,
             'kennzahl': f"CHF {reparatur_eff:,.0f} {heute.year}".replace(',', "'"), 'pdf': False},
            {'icon': 'senden', 'farbe': 'info', 'titel': _('Objekt-Feed (Portale)'),
             'sub': _('Vermarktungs-Feed für Homegate/Flatfox'), 'url': '/neu/integrationen/',
             'kennzahl': None, 'pdf': False},
        ]},
    ]
    from core.auth import hat_rolle
    v8 = _berichte_v8(heute, aktive_lg)
    if not hat_rolle(request.user, TEAM_ROLLEN):
        # Die Buchhaltung bekommt nur die Berichte, die sie öffnen darf (keine
        # toten Links), und keine Mandatsliste: Sie führt Eigentümernamen.
        from core.auth import darf_oeffnen, eigene_rollen
        meine = eigene_rollen(request.user)
        berichte = [dict(g, items=[i for i in g['items'] if darf_oeffnen(request.user, i['url'], meine)])
                    for g in berichte]
        berichte = [g for g in berichte if g['items']]
        v8['mandat_zeilen'] = []
        v8['ausstand_balken'] = [dict(z, url='') for z in v8.get('ausstand_balken') or []]
    return render(request, 'fw/berichte.html', {**basis, 'nav': 'berichte', 'berichte': berichte,
                                                'heute': heute, **v8})


AUSWERTUNG_TYPEN = [
    ('mietertrag', gettext_lazy('Mietertrag'), 'ertrag'),
    ('aufwand', gettext_lazy('Aufwand (total)'), 'aufwand'),
    ('reparatur', gettext_lazy('Reparaturen (Unterhalt)'), 'aufwand'),
    ('ergebnis', gettext_lazy('Nettoergebnis'), 'ergebnis'),
]


@rolle_erforderlich(*FINANZ_LESE_ROLLEN)
def fw_betriebsrechnung_pdf(request, pk):
    """Gebäudescharfe Betriebsrechnung (Ertrag − Aufwand) einer Liegenschaft als
    PDF, für ein wählbares Kalenderjahr (?jahr=YYYY)."""
    from django.http import HttpResponse
    from crm.models import Organisation
    from core.services.gebaeude_report import betriebsrechnung_pdf
    lg = get_object_or_404(Liegenschaft, id=pk)
    try:
        jahr = jahr_streng(request.GET.get('jahr') or timezone.localdate().year)
    except ValueError:
        jahr = timezone.localdate().year
    # Briefkopf vom Objekt der Auswertung.
    pdf = betriebsrechnung_pdf(lg, jahr, verwaltung=lg.organisation)
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
        jahr = jahr_streng(request.GET.get('jahr') or heute.year)
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


@rolle_erforderlich(*FINANZ_LESE_ROLLEN)
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
        jahr = jahr_streng(request.GET.get('jahr') or heute.year)
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
    #
    # Abschlussbuchungen ausklammern (Zwilling von FUNK-02): Der Jahresabschluss
    # saldiert alle Erfolgskonten per 31.12. gegen 2970. Ohne den Ausschluss zeigte
    # die Auswertung eines abgeschlossenen Jahres Mietertrag 0 (gemessen 28.10.2026:
    # 10'000 vor, 0 nach dem Abschluss).
    from core.services.jahresabschluss import abschluss_buchungen_q
    base_q = (Buchung.objects.filter(datum__year=jahr, ist_storno=False,
                                     storniert_am__isnull=True)
              .exclude(abschluss_buchungen_q()))
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
        # 'M' über dateformat folgt der Sprache; strftime('%b') gab «Mar/May/Oct» auch auf Deutsch.
        monate.append({'m': m, 'name': dateformat.format(date(2000, m, 1), 'M'), 'wert': w})
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
        from crm.models import Organisation
        from core.services.auswertung_pdf import generate_auswertung_pdf
        from django.http import HttpResponse
        lg_name = f"{aktive_lg.strasse}, {aktive_lg.ort}" if aktive_lg else "Alle Liegenschaften"
        pdf = generate_auswertung_pdf(typ_label, jahr, lg_name, total, monate, lg_rows,
                                      aktuelle_organisation())
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
        from crm.models import Organisation
        from django.http import HttpResponse
        # Das PDF ist (noch) nur deutsch formuliert: fest deutsch berechnen und
        # erzeugen, sonst stünde der übersetzte Objekttyp im deutschen Text.
        # Wer bei internen Berichten der Empfänger ist, ist offen (D11).
        from core.services.dokumentsprache import STANDARD, in_sprache
        with in_sprache(STANDARD):
            spiegel = berechne_mieterspiegel([aktive_lg])
            pdf = generate_mieterspiegel_pdf(spiegel, aktuelle_organisation(), stichtag=timezone.localdate())
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
