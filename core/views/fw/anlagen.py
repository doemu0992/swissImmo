# core/views/fw/anlagen.py
#
# Block 10 der 33 (Etappe 1, siehe docs/ETAPPE-1-ZERLEGEN.md): Anlagen und
# Abschluss — Abschreibungen, Erneuerungsfonds, Periodensperre.
#
# Unveraendert uebernommen. Neu sind nur die Importe hier oben.

from datetime import date
from decimal import Decimal

from django.shortcuts import render
from django.utils import timezone

from core.auth import rolle_erforderlich, ROLLE_VERWALTUNG, TEAM_ROLLEN
from portfolio.models import Liegenschaft

from ._basis import _global_filter, _num


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
                # Auf Anwesenheit prüfen, nicht auf den Wert 'on'. Den schickt der
                # Browser nur, solange das Kästchen kein value-Attribut trägt —
                # ein späteres value="1" hätte die Aktivierungsbuchung stillschweigend
                # abgeschaltet, und das Anlagekonto liefe wieder ins Minus.
                if wert > 0 and request.POST.get('aktivieren'):
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
