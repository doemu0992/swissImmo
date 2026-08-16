# core/views/fw/eigentuemer_abrechnung.py
#
# Abrechnung gegenueber dem Eigentuemer: Ergebnis je Liegenschaft,
# Kontokorrent, Verwaltungshonorar, Mahnstufen-Konfiguration, Auszahlung.
# Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md.
#
# Bewusst NICHT mit eigentuemer.py (Stammdaten-CRUD) zusammengelegt: Das eine
# pflegt Adressen, das andere bewegt Geld. Gleicher Gegenstand, verschiedene
# Verantwortung — und in Phase 2 sehr wahrscheinlich verschiedene
# Berechtigungen.

from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import rolle_erforderlich, VERWALTUNGS_ROLLEN
from portfolio.models import Liegenschaft

from ._basis import _global_filter, _num


# ============================================================
# EIGENTÜMER-/MANDATSABRECHNUNG
# ============================================================

def _mandat_abrechnung_daten(eigentuemer, jahr):
    """Erträge/Aufwände je Liegenschaft des Eigentümers für das Geschäftsjahr.
    Gibt (zeilen, totals) zurück — Basis für Anzeige und PDF."""
    from finance.models import Buchung, Buchungskonto
    import calendar as _cal
    von, bis = date(jahr, 1, 1), date(jahr, 12, 31)
    liegenschaften = Liegenschaft.objects.filter(eigentuemer=eigentuemer).order_by('strasse')
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
def fw_eigentuemer_abrechnung(request, pk):
    from crm.models import Eigentuemer
    md = get_object_or_404(Eigentuemer, id=pk)
    basis = _global_filter(request)
    heute = timezone.localdate()
    try:
        jahr = int(request.GET.get('jahr') or heute.year)
    except ValueError:
        jahr = heute.year

    if request.GET.get('pdf') == '1':
        from crm.models import Organisation
        from core.services.mandat_abrechnung import generate_mandat_abrechnung_pdf
        from django.http import HttpResponse
        zeilen, totals, von, bis = _mandat_abrechnung_daten(md, jahr)
        pdf = generate_mandat_abrechnung_pdf(md, jahr, zeilen, totals, von, bis, md.organisation)
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
    from crm.models import Eigentuemer
    from core.services.eigentuemer_kontokorrent import kontokorrent
    from finance.models import Buchungskonto
    md = get_object_or_404(Eigentuemer, id=pk)
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
        from crm.models import Organisation
        from core.services.eigentuemer_kontokorrent import generate_kontokorrent_pdf
        from django.http import HttpResponse
        pdf = generate_kontokorrent_pdf(md, jahr, md.organisation)
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
    from crm.models import Eigentuemer
    from core.services.verwaltungshonorar import buche_honorar
    from core.auth import log_aktion
    md = get_object_or_404(Eigentuemer, id=pk)
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
def fw_eigentuemer_mahnstufen(request, pk):
    """Mahnstufen-Konfiguration eines Eigentümers (feste 3 Stufen: aktiv / ab_tage /
    gebuehr / kuendigung). Speichert nach Eigentuemer.mahn_konfig (JSON). Leer =
    Standard 14/30/60. Siehe core.services.mahnstufen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Eigentuemer
    from core.services.mahnstufen import roh_konfig
    from core.auth import log_aktion
    md = get_object_or_404(Eigentuemer, id=pk)
    if request.method == 'POST':
        std_tage = {1: 14, 2: 30, 3: 60}
        konfig = []
        for s in (1, 2, 3):
            try:
                ab = max(0, int(request.POST.get(f'ab_tage_{s}') or std_tage[s]))
            except ValueError:
                ab = std_tage[s]
            try:
                geb = Decimal(str(request.POST.get(f'gebuehr_{s}') or '0').replace(',', '.'))
                geb = max(Decimal('0'), geb)
            except Exception:
                geb = Decimal('0')
            konfig.append({
                'stufe': s,
                'aktiv': request.POST.get(f'aktiv_{s}') == 'on',
                'ab_tage': ab,
                'gebuehr': f"{geb:.2f}",
                'kuendigung': request.POST.get(f'kuendigung_{s}') == 'on',
            })
        md.mahn_konfig = konfig
        md.save(update_fields=['mahn_konfig'])
        log_aktion(request, "Mahnstufen-Konfiguration geändert", md.firma_oder_name,
                   " · ".join(f"St{c['stufe']}:{'an' if c['aktiv'] else 'aus'}/{c['ab_tage']}T"
                              for c in konfig))
        messages.success(request, "✅ Mahnstufen gespeichert.")
        return redirect(f'/neu/mandate/{md.id}/mahnstufen/')
    return render(request, 'fw/eigentuemer_mahnstufen.html', {
        **_global_filter(request), 'nav': 'mandate', 'md': md, 'stufen': roh_konfig(md),
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_eigentuemer_auszahlung(request, pk):
    """Erfasst eine Auszahlung an den Eigentümer und bucht sie:
    Soll 2850 (Kontokorrent Eigentümer) / Haben Bank."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Eigentuemer
    from finance.models import Buchungskonto, EigentuemerAuszahlung
    from finance.booking import buche, konto as _konto
    from core.auth import log_aktion
    md = get_object_or_404(Eigentuemer, id=pk)
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
        eigentuemer=md, betrag=betrag, datum=datum, konto=bank,
        bemerkung=bemerkung, erstellt_von=request.user)
    log_aktion(request, "Eigentümer-Auszahlung", md.firma_oder_name,
               f"CHF {betrag} ab {bank.nummer} · Beleg #{buchung.beleg_nr if buchung else '—'}")
    messages.success(request, f"✅ Auszahlung CHF {betrag} an {md.firma_oder_name} verbucht (Soll 2850 / Haben {bank.nummer}).")
    return redirect('fw_eigentuemer_kontokorrent', pk=md.id)
