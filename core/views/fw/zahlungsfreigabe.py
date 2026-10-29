# core/views/fw/zahlungsfreigabe.py
"""Einstellung der Freigabelimite für Kreditorenzahlungen (Vier-Augen-Prinzip, Etappe 2).

Die Limite gehört der Organisation (`Organisation.freigabelimit_kreditoren`).
Ändern darf sie nur der Inhaber: Wer das Limit hochsetzt, hebt das
Vier-Augen-Prinzip für alle Zahlungen darunter auf. Jede Änderung steht im
Aktivitätslog (alter und neuer Wert, wer).
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext

from core.auth import INHABER_ROLLEN, TEAM_ROLLEN, hat_rolle, log_aktion, rolle_erforderlich
from core.utils.betrag import betrag_normalisieren
from core.tenancy import organisation_der_anfrage

from ._basis import _global_filter

ZIEL = '/neu/einstellungen/zahlungsfreigabe/'
#: Obergrenze, damit ein Tippfehler (zu viele Nullen) nicht still alles freigibt.
MAX_LIMIT = Decimal('99999999.99')


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_zahlungsfreigabe(request):
    """Zeigt das Limit und wer freigibt; der Inhaber ändert es."""
    org = organisation_der_anfrage(request)
    return render(request, 'fw/zahlungsfreigabe.html', {
        **_global_filter(request), 'nav': 'einstellungen', 'org': org,
        'darf_aendern': hat_rolle(request.user, INHABER_ROLLEN),
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
