# core/views/fw/debitoren_liste.py
#
# Debitorenliste mit Mahnstufe und CSV-Export.
# Aus listen.py herausgeloest (reiner Umzug ohne Aenderung am Code).

from datetime import timedelta as _timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from core.services.mahnstufen import (Mahnstufen as _Mahnstufen,
                                      eigentuemer_von_rechnung as _eigentuemer_von_rechnung)
from core.auth import (rolle_erforderlich)
from core.auth import FINANZ_LESE_ROLLEN
from finance.models import DebitorenRechnung, Zahlungseingang
from rentals.models import Mietvertrag
from core.views.fw._liste import (csv_antwort, query_mit)


from ._basis import (_global_filter, STATUS_PILL)
from core.tenancy import aktuelle_organisation


# ============================================================
# ETAPPE B: LISTEN ALS DATENTABELLEN
# ============================================================

def _mahnstufe(faellig, heute, status, eigentuemer=None, stufen=None):
    """Mahnstufen-Badge aus Fälligkeit + den Mahnstufen der Organisation
    (crm.MahnStufe, ggf. vom Eigentümer übersteuert; core.services.mahnstufen).
    'Fällig' als Fallback, wenn überfällig, aber noch unter der ersten aktiven
    Stufe. `stufen`: ein `Mahnstufen`-Lader, damit eine Liste die Datenbank
    nicht je Zeile fragt."""
    if status not in ('offen', 'teilbezahlt') or not faellig:
        return None
    stufen = stufen or _Mahnstufen()
    tage = stufen.tage_im_verzug(faellig, heute, eigentuemer)
    if tage is None:
        return None
    s = stufen.stufe_fuer_tage(tage, eigentuemer)
    if s:
        return {'label': s['label'], 'cls': s['cls'], 'tage': tage}
    return {'label': _('Fällig'), 'cls': 'fw-warn-flaeche fw-warnton', 'tage': tage}


@rolle_erforderlich(*FINANZ_LESE_ROLLEN)
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

    # --- Ampel: Zahlungsstatus auf einen Blick -----------------------------
    # Grün = bezahlt · Gelb = offen, Fälligkeit liegt noch vor uns ·
    # Rot = offen und überfällig (Zahlungsrückstand). Die Zählung steht VOR dem
    # Ampelfilter, sonst zeigte jede Ampel nur noch die eigene Zahl. Die
    # Fälligkeit ist `faellig_am`, ersatzweise `datum` — als Q statt als
    # Annotation, damit die späteren Aggregate unverändert bleiben.
    ampel_filter = request.GET.get('ampel', '')
    ueberfaellig_q = (Q(faellig_am__lt=heute)
                      | Q(faellig_am__isnull=True, datum__lt=heute))
    ampel_basis = qs
    if ampel_filter == 'gruen':
        qs = qs.filter(status='bezahlt')
    elif ampel_filter == 'gelb':
        qs = qs.filter(status__in=('offen', 'teilbezahlt')).exclude(ueberfaellig_q)
    elif ampel_filter == 'rot':
        qs = qs.filter(status__in=('offen', 'teilbezahlt')).filter(ueberfaellig_q)
    else:
        ampel_filter = ''

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

    def _ampel_zahl(teil):
        a = teil.annotate(_o=_offen_expr).aggregate(n=Count('id'), s=Sum('_o'))
        return {'n': a['n'] or 0, 'summe': a['s'] or Decimal('0.00')}
    _offen_basis = ampel_basis.filter(status__in=_OFFEN_STATUS)
    ampeln = [
        ('gruen', _('Bezahlt'), _ampel_zahl(ampel_basis.filter(status='bezahlt')),
         _('Eingang verbucht')),
        ('gelb', _('Offen, nicht fällig'), _ampel_zahl(_offen_basis.exclude(ueberfaellig_q)),
         _('Fälligkeit liegt vor uns')),
        ('rot', _('Überfällig'), _ampel_zahl(_offen_basis.filter(ueberfaellig_q)),
         _('Zahlungsrückstand — Mahnwesen')),
    ]

    # CSV: dieselbe Auswahl wie die Liste, aber ALLE Zeilen (nicht nur Seite 1).
    if request.GET.get('export') == 'csv':
        return _debitoren_csv(
            qs.annotate(_o=_offen_expr).order_by('faellig_am', 'datum', 'id'), heute)

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
    mahn_lader = _Mahnstufen()
    for r in seiten_objekte:
        lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
        einheit = r.einheit or (r.vertrag.einheit if r.vertrag_id else None)
        # `_o` kommt aus der Annotation (siehe oben) — identisch zu
        # r.offener_betrag, aber ohne die Zahlungen nachzuladen.
        offen = r._o if r.status in _OFFEN_STATUS else Decimal('0.00')
        faellig = r.faellig_am or r.datum
        mahn = _mahnstufe(faellig, heute, r.status, _eigentuemer_von_rechnung(r), mahn_lader)
        label, pill_cls = STATUS_PILL.get(r.status, (r.status, 'fw-flaeche2 fw-mutet'))
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
    from crm.models import Organisation
    vw = aktuelle_organisation()
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
        'status_chips': [('', _('Alle'))] + [(k, v[0]) for k, v in STATUS_PILL.items()],
        'ampeln': ampeln, 'ampel_filter': ampel_filter,
        'csv_url': query_mit(request, export='csv'),
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


def _debitoren_csv(rechnungen, heute):
    """Debitorenliste für die Tabellenkalkulation: eine Zeile je Rechnung.

    «Ampel» und «Tage überfällig» stehen als Text und Zahl drin, damit die
    Buchhaltung nach Rückständen filtern kann, ohne die Fälligkeit selbst zu
    rechnen.
    """
    ampel_text = {'bezahlt': _('grün'), 'gelb': _('gelb'), 'rot': _('rot')}

    def zeilen():
        for r in rechnungen:
            lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft
                                    if r.vertrag_id and r.vertrag.einheit_id else None)
            einheit = r.einheit or (r.vertrag.einheit if r.vertrag_id else None)
            faellig = r.faellig_am or r.datum
            offen_status = r.status in ('offen', 'teilbezahlt')
            tage = (heute - faellig).days if offen_status and faellig and faellig < heute else 0
            if r.status == 'bezahlt':
                ampel = ampel_text['bezahlt']
            elif offen_status:
                ampel = ampel_text['rot'] if tage > 0 else ampel_text['gelb']
            else:
                ampel = ''
            yield [faellig.strftime('%d.%m.%Y') if faellig else '',
                   r.vertrag.mieter.display_name if r.vertrag_id else '',
                   f"{lg.strasse}, {lg.ort}" if lg else '',
                   einheit.bezeichnung if einheit else '',
                   r.titel, r.betrag, r._o if offen_status else Decimal('0.00'),
                   STATUS_PILL.get(r.status, (r.status,))[0], ampel, tage]

    return csv_antwort(
        f'Debitoren_{heute:%Y-%m-%d}.csv',
        [_('Fällig'), _('Mieter'), _('Liegenschaft'), _('Objekt'), _('Titel'),
         _('Betrag (CHF)'), _('Offen (CHF)'), _('Status'), _('Ampel'), _('Tage überfällig')],
        zeilen())
