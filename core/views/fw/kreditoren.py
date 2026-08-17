# core/views/fw/kreditoren.py
#
# Rechnungseingang, Freigabe, Zahlung, Zahllauf und pain.001-Datei.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# pain.001 ist im Skill schweizer-fachlogik als Zahlungsstandard gefuehrt.
# Reiner Umzug, Blockinhalt gegen HEAD geprueft.

import logging
import os
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import (rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN,
                       TEAM_ROLLEN, VERWALTUNGS_ROLLEN)
from portfolio.models import Liegenschaft

logger = logging.getLogger(__name__)

from ._basis import _global_filter, _num
from core.tenancy import aktuelle_organisation


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
            logger.debug("Fehler bewusst übergangen", exc_info=True)
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
        # Letzte VERBUCHTE Zahlung (für «Zahlung stornieren»). Nutzt den Prefetch —
        # keine Extra-Abfrage je Zeile.
        _verbuchte = sorted((z for z in k.zahlungen.all() if z.status == 'verbucht'),
                            key=lambda z: (z.datum, z.id))
        letzte_zahlung = _verbuchte[-1] if _verbuchte else None
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
            'letzte_zahlung': letzte_zahlung,
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


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_kreditoren_pain001(request):
    """Erzeugt eine ISO-20022 pain.001-Zahlungsdatei aus allen freigegebenen
    Kreditorenrechnungen (für den e-Banking-Massenupload)."""
    from django.http import HttpResponse
    from django.contrib import messages
    from django.shortcuts import redirect
    from finance.models import KreditorenRechnung
    from crm.models import Organisation
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

    vw = aktuelle_organisation()
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


@rolle_erforderlich(ROLLE_VERWALTER)
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


@rolle_erforderlich(ROLLE_VERWALTER)
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
    from crm.models import Organisation
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
            vw = aktuelle_organisation()
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
    # 'teilbezahlt' MUSS mit rein: Nach einer Teilzahlung bleibt ein offener Rest —
    # ohne diesen Status verschwand die Rechnung aus dem Zahllauf und der Rest wurde
    # nie zur Zahlung vorgeschlagen (Live-Test H9).
    qs = (KreditorenRechnung.objects
          .filter(status__in=['freigegeben', 'in_zahlung', 'teilbezahlt'])
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

    vw = aktuelle_organisation()
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


@rolle_erforderlich(ROLLE_VERWALTER)
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


@rolle_erforderlich(ROLLE_VERWALTER)
def fw_kreditor_zahlung_stornieren(request, pk):
    """Storniert eine VERBUCHTE Lieferantenzahlung revisionssicher: Gegenbuchung
    zur Zahlungsbuchung (2000 an Bank), Zahlung → 'storniert', der offene Posten
    der Kreditorenrechnung öffnet sich wieder.

    Live-Test H9: `fw_zahlung_stornieren` deckt nur EINGEHENDE Zahlungen
    (Zahlungseingang) ab. Eine an den falschen Lieferanten oder mit falschem
    Betrag AUSGEFÜHRTE Zahlung liess sich gar nicht mehr rückgängig machen — nur
    per Handbuchung, und der offene Posten blieb falsch (bezahlt, obwohl das Geld
    zurückkommt)."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from finance.models import KreditorenZahlung, Buchung
    from finance.services import erstelle_storno_buchung
    from core.auth import log_aktion
    if request.method != 'POST':
        return redirect('fw_kreditoren')
    naechstes = request.POST.get('next') or '/neu/kreditoren/'
    try:
        with transaction.atomic():
            # Zeilensperre gegen Doppel-Storno (zwei parallele Requests).
            z = get_object_or_404(
                KreditorenZahlung.objects.select_for_update().select_related('kreditor'), id=pk)
            if z.status == 'storniert':
                messages.info(request, "Diese Zahlung ist bereits storniert.")
                return redirect(naechstes)
            k = z.kreditor
            # Die zur Zahlung gehörende Buchung finden und gegenbuchen. Diskriminator:
            # Sollkonto 2000 (die Rechnungsbuchung trägt 2000 im HABEN, nur die
            # Zahlung im SOLL), Betrag und Datum der Zahlung. Bei mehreren identischen
            # Zahlungen ist jede Umkehr finanziell gleichwertig (gleiche Konten/Betrag).
            buchung = (Buchung.objects.filter(
                kreditoren_rechnung=k, soll_konto__nummer='2000',
                betrag=z.betrag, datum=z.datum,
                ist_storno=False, storniert_am__isnull=True).order_by('id').first())
            if buchung is not None:
                erstelle_storno_buchung(buchung, benutzer=request.user)
            z.status = 'storniert'
            z.save(update_fields=['status'])
            # Rechnungsstatus nachführen (offener_betrag zählt nur 'verbucht'):
            if k.status != 'storniert':
                if k.offener_betrag <= 0:
                    k.status = 'bezahlt'
                elif k.offener_betrag >= (k.betrag or Decimal('0.00')):
                    k.status = 'freigegeben'
                else:
                    k.status = 'teilbezahlt'
                k.save(update_fields=['status'])
    except PermissionError as exc:
        messages.error(request, f"❌ {exc}")
        return redirect(naechstes)
    except Exception as exc:
        messages.error(request, f"❌ Zahlung konnte nicht storniert werden: {exc}")
        return redirect(naechstes)
    log_aktion(request, "Lieferantenzahlung storniert", k.lieferant or f"Rechnung #{k.id}",
               f"CHF {z.betrag}")
    messages.success(request, f"✅ Zahlung über CHF {z.betrag} an {k.lieferant or 'Lieferant'} "
                              f"storniert — offener Posten wieder offen.")
    return redirect(naechstes)
