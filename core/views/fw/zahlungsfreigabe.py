# core/views/fw/zahlungsfreigabe.py
"""Einstellung der Freigabelimite für Kreditorenzahlungen (Vier-Augen-Prinzip, Etappe 2).

Die Limite gehört der Organisation (`Organisation.freigabelimit_kreditoren`).
Ändern darf sie nur der Inhaber: Wer das Limit hochsetzt, hebt das
Vier-Augen-Prinzip für alle Zahlungen darunter auf. Jede Änderung steht im
Aktivitätslog (alter und neuer Wert, wer).

Dazu die Freigabe der Auszahlungen ohne Rechnung (Etappe 4): Eigentümerauszahlung,
Rückerstattung von Mieterguthaben, Kautionsrückzahlung. Die Auszahlungswege legen eine
gesperrte Auszahlung hier vor (`auszahlung_gesperrt_melden`); eine zweite Person gibt sie
auf der Seite «Auszahlungen» frei (`finance/freigabe.py`).
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from core.auth import (FINANZ_VERWALTUNGS_ROLLEN, INHABER_ROLLEN, TEAM_ROLLEN, VERWALTUNGS_ROLLEN,
                       ZAHLUNGSFREIGABE_ROLLEN, hat_rolle, log_aktion, rolle_erforderlich)
from core.utils.betrag import betrag_normalisieren
from core.tenancy import organisation_der_anfrage

from ._basis import _global_filter

ZIEL = '/neu/einstellungen/zahlungsfreigabe/'
AUSZAHLUNGEN = '/neu/einstellungen/zahlungsfreigabe/auszahlungen/'
#: Obergrenze, damit ein Tippfehler (zu viele Nullen) nicht still alles freigibt.
MAX_LIMIT = Decimal('99999999.99')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_zahlungsfreigabe(request):
    """Zeigt das Limit und wer freigibt; der Inhaber ändert es."""
    from finance.models import AuszahlungsFreigabe
    org = organisation_der_anfrage(request)
    return render(request, 'fw/zahlungsfreigabe.html', {
        **_global_filter(request), 'nav': 'einstellungen', 'org': org,
        'darf_aendern': hat_rolle(request.user, INHABER_ROLLEN),
        'offene_auszahlungen': AuszahlungsFreigabe.objects.filter(verbraucht_am__isnull=True).count(),
    })


@rolle_erforderlich(*INHABER_ROLLEN)
def fw_zahlungsfreigabe_speichern(request):
    """Speichert das Limit der eigenen Organisation (keine ID im Pfad)."""
    if request.method != 'POST':
        return redirect(ZIEL)
    org = organisation_der_anfrage(request)
    roh = betrag_normalisieren(request.POST.get('freigabelimit'))
    if request.POST.get('ohne_limit') == 'on' or not roh:
        neu = None
    else:
        try:
            neu = Decimal(roh).quantize(Decimal('0.01'))
        except InvalidOperation:
            neu = False
        if neu is not False and not (Decimal('0') <= neu <= MAX_LIMIT):
            neu = False
        if neu is False:
            messages.error(request, '❌ ' + gettext('Bitte einen Betrag in CHF zwischen 0 und 99 999 999.99 eingeben.'))
            return redirect(ZIEL)
    alt = org.freigabelimit_kreditoren
    if neu == alt:
        return redirect(ZIEL)
    org.freigabelimit_kreditoren = neu
    org.save(update_fields=['freigabelimit_kreditoren'])
    log_aktion(request, 'Freigabelimite Kreditorenzahlungen geändert', str(org),
               f"{'keine' if alt is None else f'CHF {alt}'} → {'keine (Vier-Augen-Prinzip aus)' if neu is None else f'CHF {neu}'}",
               kategorie='sicherheit')
    messages.success(request, '✅ ' + gettext('Freigabelimite gespeichert.'))
    return redirect(ZIEL)


# ── Auszahlungen ohne Rechnung (Etappe 4) ─────────────────────────────────────
def _name(user):
    return (user.get_full_name() or user.get_username()) if user else ''


def auszahlung_gesperrt_melden(request, gesperrt):
    """Legt eine gesperrte Auszahlung zur Freigabe vor, protokolliert und meldet es dem Auslöser.

    Von allen Auszahlungswegen aufgerufen, NACHDEM die Transaktion der Auszahlung zurückgerollt ist
    (der Antrag soll bestehen bleiben, die Buchung nicht)."""
    from finance.freigabe import auszahlung_vorlegen
    antrag, neu = auszahlung_vorlegen(gesperrt, request.user)
    art = antrag.get_art_display()
    if neu:
        log_aktion(request, 'Auszahlung zur Freigabe vorgelegt', gesperrt.bezug_text or art,
                   f'{art} · CHF {gesperrt.betrag} · IBAN {gesperrt.iban or "—"}', kategorie='sicherheit')
    log_aktion(request, 'Auszahlung gesperrt (Vier-Augen-Prinzip)', gesperrt.bezug_text or art,
               f'{art} · CHF {gesperrt.betrag} · {gesperrt}', kategorie='sicherheit')
    messages.error(request, '⛔ ' + gettext(
        '%(text)s Sie ist vorgelegt und erscheint unter Einstellungen → Zahlungsfreigabe → Auszahlungen; '
        'danach die Auszahlung erneut auslösen.') % {'text': gesperrt})
    return antrag


def _ziel_der(antrag):
    """Wohin der Antrag gehört (die Seite, auf der die Auszahlung ausgelöst wird)."""
    if antrag.art == 'eigentuemer':
        return f'/neu/mandate/{antrag.bezug_id}/kontokorrent/'
    if antrag.art in ('kaution', 'schlussabrechnung'):
        return f'/neu/vertraege/{antrag.bezug_id}/'
    return '/neu/bankabgleich/'


@rolle_erforderlich(*FINANZ_VERWALTUNGS_ROLLEN)
def fw_auszahlungsfreigaben(request):
    """Offene und zuletzt ausgeführte Auszahlungsfreigaben der Organisation."""
    from finance.models import AuszahlungsFreigabe
    org = organisation_der_anfrage(request)
    darf = hat_rolle(request.user, ZAHLUNGSFREIGABE_ROLLEN)
    offen = list(AuszahlungsFreigabe.objects.filter(verbraucht_am__isnull=True)
                 .select_related('beantragt_von', 'freigegeben_von'))
    for a in offen:
        a.ziel = _ziel_der(a)
        a.vorleger = _name(a.beantragt_von)
        a.freigeber = _name(a.freigegeben_von)
        a.gueltig = bool(a.freigegeben_von_id and a.freigabe_betrag == a.betrag
                         and a.freigabe_iban == (a.iban or '').replace(' ', '').upper())
        a.eigene = a.beantragt_von_id == request.user.pk
        a.kann_freigeben = bool(darf and not a.gueltig and a.beantragt_von_id and not a.eigene)
    erledigt = list(AuszahlungsFreigabe.objects.filter(verbraucht_am__isnull=False)
                    .select_related('beantragt_von', 'freigegeben_von').order_by('-verbraucht_am')[:10])
    return render(request, 'fw/auszahlungsfreigaben.html', {
        **_global_filter(request), 'nav': 'einstellungen', 'org': org,
        'offen': offen, 'erledigt': erledigt, 'darf_freigeben': darf,
    })


@rolle_erforderlich(*ZAHLUNGSFREIGABE_ROLLEN)
def fw_auszahlungsfreigabe_freigeben(request, pk):
    """Gibt einen vorgelegten Antrag frei: nie der Vorleger, nur für den gesehenen Betrag und IBAN."""
    from finance.freigabe import FreigabeFehler, auszahlung_freigeben
    from finance.models import AuszahlungsFreigabe
    if request.method != 'POST':
        return redirect(AUSZAHLUNGEN)
    get_object_or_404(AuszahlungsFreigabe, pk=pk)                       # fremde ID -> 404
    with transaction.atomic():
        antrag = (AuszahlungsFreigabe.objects.select_for_update(of=('self',))
                  .select_related('organisation').filter(pk=pk).first())
        if antrag is None:                  # zwischen Prüfung und Sperre zurückgenommen oder ausgeführt
            messages.error(request, '⛔ ' + gettext('Dieser Antrag wurde inzwischen zurückgenommen.'))
            return redirect(AUSZAHLUNGEN)
        try:
            auszahlung_freigeben(antrag, request.user, gesehen_betrag=request.POST.get('betrag'),
                                 gesehen_iban=request.POST.get('iban'))
        except FreigabeFehler as exc:
            log_aktion(request, 'Auszahlungsfreigabe abgelehnt', antrag.bezug_text or antrag.get_art_display(),
                       f'{antrag.get_art_display()} · CHF {antrag.betrag} · {exc}', kategorie='sicherheit')
            messages.error(request, '⛔ ' + str(exc))
        else:
            log_aktion(request, 'Auszahlung freigegeben (Vier-Augen-Prinzip)',
                       antrag.bezug_text or antrag.get_art_display(),
                       f'{antrag.get_art_display()} · CHF {antrag.betrag} · IBAN {antrag.freigabe_iban or "—"} · '
                       f'vorgelegt von {_name(antrag.beantragt_von)}', kategorie='sicherheit')
            messages.success(request, '✅ ' + gettext(
                'Die Auszahlung ist freigegeben. Sie kann jetzt ausgelöst werden; die Freigabe gilt für einmal.'))
    return redirect(AUSZAHLUNGEN)


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def fw_auszahlungsfreigabe_zuruecknehmen(request, pk):
    """Verwirft einen offenen Antrag (Vorlage und Freigabe). Die Auszahlung ist danach wieder gesperrt."""
    from finance.models import AuszahlungsFreigabe
    if request.method != 'POST':
        return redirect(AUSZAHLUNGEN)
    get_object_or_404(AuszahlungsFreigabe, pk=pk)
    with transaction.atomic():
        antrag = (AuszahlungsFreigabe.objects.select_for_update(of=('self',))
                  .filter(pk=pk, verbraucht_am__isnull=True).first())
        if antrag is not None:
            log_aktion(request, 'Auszahlungsfreigabe zurückgenommen', antrag.bezug_text or antrag.get_art_display(),
                       f'{antrag.get_art_display()} · CHF {antrag.betrag}', kategorie='sicherheit')
            antrag.delete()
            messages.success(request, gettext('Vorlage und Freigabe sind verworfen.'))
    return redirect(AUSZAHLUNGEN)
