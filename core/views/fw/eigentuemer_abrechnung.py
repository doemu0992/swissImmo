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
from django.utils.translation import gettext
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.auth import rolle_erforderlich, VERWALTUNGS_ROLLEN
from core.utils.betrag import betrag_normalisieren
from portfolio.models import Liegenschaft

from ._basis import _global_filter, _num
from core.utils.parameter import jahr_streng


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

    # Abschlussbuchungen ausklammern, wie das Kontokorrent es tut
    # (`eigentuemer_kontokorrent.kontokorrent`): Der Jahresabschluss je
    # Liegenschaft saldiert alle Erfolgskonten per 31.12. gegen 2970. Ohne den
    # Ausschluss zeigte die Abrechnung — Seite UND PDF — nach dem Abschluss
    # Ertrag 0, Aufwand 0, Saldo 0, während das Kontokorrent weiter 8'000 nannte
    # (Audit FUNK-02).
    from core.services.jahresabschluss import abschluss_buchungen_q

    zeilen = []
    sum_ertrag = sum_aufwand = Decimal('0.00')
    for lg in liegenschaften:
        bqs = (Buchung.objects.filter(liegenschaft=lg, datum__gte=von, datum__lte=bis)
               .exclude(abschluss_buchungen_q()))
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
        jahr = jahr_streng(request.GET.get('jahr') or heute.year)
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
    from core.services.eigentuemer_kontokorrent import auszahlungs_stand, kontokorrent, liquiditaet
    md = get_object_or_404(Eigentuemer, id=pk)
    basis = _global_filter(request)
    heute = timezone.localdate()
    jahr_param = request.GET.get('jahr', '')
    jahr = None
    if jahr_param and jahr_param != 'alle':
        try:
            jahr = jahr_streng(jahr_param)
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
    # Nur Bankkonten — das Kautionssperrkonto 1015 gehört den Mietern und stand
    # hier bisher als erste Wahl in der Liste (Audit FUNK-01). Jedes mit seinem
    # Saldo, damit die Maske zeigt, was gedeckt ist.
    from finance.booking import bankkonten as _bankkonten, kontosaldo
    bankkonten = [{'nummer': k.nummer, 'bezeichnung': k.bezeichnung, 'saldo': kontosaldo(k)}
                  for k in _bankkonten()]
    liq = liquiditaet(md)

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
        'liq': liq, 'auszahlungs_stand': auszahlungs_stand(md),
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
        messages.error(request, gettext('Kein Geschäftsjahr gewählt.'))
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
        messages.success(request, '✅ ' + gettext('Verwaltungshonorar %(jahr)s verbucht: CHF %(summe)s über %(anzahl)s Liegenschaft(en) (Soll 4500 / Haben %(gegen)s).') % {'jahr': jahr, 'summe': summe, 'anzahl': anzahl, 'gegen': gegen})
    else:
        messages.warning(request, gettext('Kein Honorar zu buchen (bereits gebucht oder kein Mietertrag).'))
    return redirect(f'/neu/mandate/{md.id}/kontokorrent/?jahr={jahr}')


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_eigentuemer_mahnstufen(request, pk):
    """Übersteuerung der Mahnstufen für EINEN Eigentümer: je Stufe der Organisation
    (crm.MahnStufe) aktiv / ab_tage / gebuehr / kuendigung. Speichert nach
    Eigentuemer.mahn_konfig (JSON). Stufen, die hier nicht abweichen, gelten wie
    bei der Organisation (`/neu/mahnstufen/`). Siehe core.services.mahnstufen."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Eigentuemer
    from core.services.mahnstufen import stufen_der_organisation
    from core.auth import log_aktion
    md = get_object_or_404(Eigentuemer, id=pk)
    if request.method == 'POST':
        konfig = []
        for basis in stufen_der_organisation(md.organisation):
            s = basis['stufe']
            try:
                ab = max(0, int(request.POST.get(f'ab_tage_{s}') or basis['ab_tage']))
            except ValueError:
                ab = basis['ab_tage']
            try:
                geb = Decimal(betrag_normalisieren(request.POST.get(f'gebuehr_{s}')) or '0')
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
        messages.success(request, '✅ ' + gettext('Mahnstufen gespeichert.'))
        return redirect(f'/neu/mandate/{md.id}/mahnstufen/')
    from core.services.mahnstufen import roh_konfig
    return render(request, 'fw/eigentuemer_mahnstufen.html', {
        **_global_filter(request), 'nav': 'mandate', 'md': md, 'stufen': roh_konfig(md),
    })


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_eigentuemer_auszahlung(request, pk):
    """Erfasst eine Auszahlung an den Eigentümer und bucht sie:
    Soll 2850 (Kontokorrent Eigentümer) / Haben Bank.

    Nur aus eingegangenem Geld (Liquiditätsbasis, siehe
    `eigentuemer_kontokorrent.liquiditaet`), nur gegen ein Bankkonto, das den
    Betrag deckt, und nie vom Kautionssperrkonto 1015 — atomar und gesperrt, so
    dass zwei gleichzeitige Auszahlungen die Deckung nicht überschreiten."""
    from django.shortcuts import redirect
    from django.contrib import messages
    from crm.models import Eigentuemer
    from finance.models import Buchungskonto
    from finance.booking import konto as _konto
    from core.auth import log_aktion
    from core.services.eigentuemer_kontokorrent import AuszahlungNichtMoeglich, buche_auszahlung
    from core.views.fw.zahlungsfreigabe import auszahlung_gesperrt_melden
    from finance.freigabe import AuszahlungGesperrt
    md = get_object_or_404(Eigentuemer, id=pk)
    if request.method != 'POST':
        return redirect('fw_eigentuemer_kontokorrent', pk=md.id)
    try:
        betrag = Decimal((_num(request.POST.get('betrag')) or '0')).quantize(Decimal('0.01'))
    except Exception:
        betrag = Decimal('0')
    if betrag <= 0:
        messages.error(request, gettext('Betrag muss grösser als 0 sein.'))
        return redirect('fw_eigentuemer_kontokorrent', pk=md.id)
    try:
        datum = date.fromisoformat(request.POST['datum']) if request.POST.get('datum') else timezone.localdate()
    except ValueError:
        datum = timezone.localdate()
    konto_nr = (request.POST.get('konto_nummer') or '').strip() or '1020'
    bank = Buchungskonto.objects.filter(nummer=konto_nr).first()
    if bank is None and konto_nr == '1020':
        bank = _konto('1020')
    if bank is None:
        messages.error(request, gettext('Das Bankkonto «%(nummer)s» gibt es nicht.') % {'nummer': konto_nr})
        return redirect('fw_eigentuemer_kontokorrent', pk=md.id)
    bemerkung = (request.POST.get('bemerkung') or '').strip()

    try:
        buchung = buche_auszahlung(md, betrag, bank=bank, datum=datum, bemerkung=bemerkung,
                                   user=request.user, stand=request.POST.get('stand') or None)
    except AuszahlungGesperrt as gesperrt:
        # Vier-Augen-Prinzip: ab der Freigabelimite nichts gebucht, die Auszahlung ist vorgelegt.
        auszahlung_gesperrt_melden(request, gesperrt)
        return redirect('fw_eigentuemer_kontokorrent', pk=md.id)
    except (AuszahlungNichtMoeglich, PermissionError) as e:
        messages.error(request, '❌ ' + str(e))
        return redirect('fw_eigentuemer_kontokorrent', pk=md.id)

    log_aktion(request, "Eigentümer-Auszahlung", md.firma_oder_name,
               f"CHF {betrag} ab {bank.nummer} · Beleg #{buchung.beleg_nr if buchung else '—'}")
    messages.success(request, '✅ ' + gettext('Auszahlung CHF %(betrag)s an %(firma_oder_name)s verbucht (Soll 2850 / Haben %(nummer)s).') % {'betrag': betrag, 'firma_oder_name': md.firma_oder_name, 'nummer': bank.nummer})
    return redirect('fw_eigentuemer_kontokorrent', pk=md.id)
