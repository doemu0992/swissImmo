# core/views/fw/listen.py
#
# Die Listenansichten als Datentabellen: Debitoren, Liegenschaften,
# Berichte, Betriebsrechnung, Leerstand, Betriebskostenspiegel,
# Auswertung, Mieterspiegel, Objekte, Vertraege, Personen.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# fw_debitoren traegt die in "Performance optimization" umgebaute
# Aggregation (Subquery statt Python-Schleife, Page ueber vorbereitete
# Zeilen). Der Umzug fasst davon nichts an.

import logging
from collections import defaultdict
from datetime import date, timedelta as _timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import ExtractMonth
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.services.mahnstufen import (stufe_fuer_tage as _stufe_fuer_tage,
                                      eigentuemer_von_rechnung as _eigentuemer_von_rechnung)
from core.auth import (rolle_erforderlich, ROLLE_VERWALTUNG, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from crm.models import Mieter, Organisation
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

logger = logging.getLogger(__name__)

from ._basis import (_global_filter, _num, _vermietung_pipeline,
                     STATUS_PILL, VERTRAG_PILL)


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
    from crm.models import Organisation
    vw = Organisation.objects.first()
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
    from crm.models import Organisation as _Vw
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
    from crm.models import Organisation
    from core.services.gebaeude_report import betriebsrechnung_pdf
    lg = get_object_or_404(Liegenschaft, id=pk)
    try:
        jahr = int(request.GET.get('jahr') or timezone.localdate().year)
    except ValueError:
        jahr = timezone.localdate().year
    pdf = betriebsrechnung_pdf(lg, jahr, verwaltung=Organisation.objects.first())
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
        from crm.models import Organisation
        from core.services.auswertung_pdf import generate_auswertung_pdf
        from django.http import HttpResponse
        lg_name = f"{aktive_lg.strasse}, {aktive_lg.ort}" if aktive_lg else "Alle Liegenschaften"
        pdf = generate_auswertung_pdf(typ_label, jahr, lg_name, total, monate, lg_rows,
                                      Organisation.objects.first())
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
        pdf = generate_mieterspiegel_pdf(spiegel, Organisation.objects.first(), stichtag=timezone.localdate())
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
