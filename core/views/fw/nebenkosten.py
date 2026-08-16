# core/views/fw/nebenkosten.py
#
# Heiz- und Nebenkostenabrechnung: Perioden, Verteilschluessel, Verbuchung,
# Versand, Akonto-Anpassung. Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Nebenkosten sind im Skill schweizer-fachlogik ausdruecklich als Bereich
# genannt, in dem nichts umgerechnet oder geraten werden darf. Deshalb hier
# derselbe Nachweis wie ueberall: Blockinhalt Zeile fuer Zeile identisch mit
# HEAD, geaendert sind nur die Importe.

import logging
from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import rolle_erforderlich, ROLLE_VERWALTER, SCHREIB_ROLLEN, TEAM_ROLLEN
from crm.models import Mieter
from finance.models import DebitorenRechnung, Zahlungseingang
from portfolio.models import Einheit, Liegenschaft
from rentals.models import Mietvertrag

from ._basis import _global_filter, _num

logger = logging.getLogger(__name__)


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
    from core.utils.billing import hole_abrechnung
    p = get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), id=pk)
    basis = _global_filter(request)
    lg = p.liegenschaft

    # Nach dem Verbuchen den EINGEFRORENEN Stand zeigen (identisch zu den Buchungen).
    result = hole_abrechnung(p)
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
        'warnungen': result.get('warnungen', []),
        'tab_liste': tab_liste,
    })


@rolle_erforderlich(ROLLE_VERWALTER)
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
        # Ergebnis EINFRIEREN: ab jetzt zeigen Detailseite/PDF/Versand genau diese
        # verbuchten Zahlen, auch wenn Belege/Flächen/Verträge später ändern.
        from core.utils.billing import _jsonable as _nk_jsonable
        import json as _nk_json
        p.snapshot_json = _nk_json.dumps(_nk_jsonable(result))
        p.save(update_fields=['abgeschlossen', 'snapshot_json'])
    log_aktion(request, "NK-Abrechnung verbucht", p.bezeichnung, f"{n_nach} Nachzahlungen, {n_gut} Gutschriften")
    messages.success(request, f"✅ Abrechnung verbucht: {n_nach} Nachzahlung(en), {n_gut} Gutschrift(en).")
    for _w in result.get('warnungen', []):
        messages.warning(request, f"⚠️ {_w}")
    return redirect(f'/neu/nebenkosten/{p.id}/')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_nebenkosten_versand(request, pk):
    """Erzeugt je Mieter eine Nebenkosten-Abrechnung (PDF), legt sie in dessen
    Akte (→ Mieterportal) und liefert alle zusammen als Sammel-PDF."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from finance.models import AbrechnungsPeriode
    from crm.models import Organisation
    from core.utils.billing import hole_abrechnung
    from core.services.nk_abrechnung import generate_nk_pdf_einzeln, generate_nk_pdf_sammel
    from core.services.ablage import ablegen
    from core.auth import log_aktion

    p = get_object_or_404(AbrechnungsPeriode.objects.select_related('liegenschaft'), id=pk)
    if request.method != 'POST':
        return redirect(f'/neu/nebenkosten/{p.id}/')

    # Verbuchte Periode → eingefrorener Stand (gleiche Zahlen wie die Buchungen).
    result = hole_abrechnung(p)
    if result.get('error'):
        messages.error(request, result['error'])
        return redirect(f'/neu/nebenkosten/{p.id}/')

    vw = p.organisation      # die Verwaltung DIESER Abrechnungsperiode
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
            logger.debug("Fehler bewusst übergangen", exc_info=True)

    if not kontexte:
        messages.error(request, "Keine abzurechnenden Mieter in dieser Periode gefunden.")
        return redirect(f'/neu/nebenkosten/{p.id}/')

    log_aktion(request, "NK-Abrechnungen versendet", p.bezeichnung, f"{abgelegt} abgelegt")
    sammel = generate_nk_pdf_sammel(kontexte)
    resp = HttpResponse(sammel, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="Nebenkostenabrechnungen_{p.bezeichnung}.pdf"'
    return resp


@rolle_erforderlich(ROLLE_VERWALTER)
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
