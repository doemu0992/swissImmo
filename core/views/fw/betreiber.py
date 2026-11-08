# core/views/fw/betreiber.py
"""Betreiber-Konsole, Etappe 1: lesende Kundenliste über alle Verwaltungen.

NUR FÜR DEN BETREIBER (Superuser, mit Zwei-Faktor wie alle). Gezeigt werden Zähler, Abostufe und Befunde (was bei einer
Verwaltung fehlt) — keine Verträge, Personen oder Buchungen, und es gibt kein «Als Kunde einloggen». Ändern kann diese
Seite noch nichts; Anlegen und Abo-Verwaltung folgen in eigenen Etappen.
"""
from django.shortcuts import render

from core.auth import BETREIBER_ROLLEN, rolle_erforderlich
from core.services import betreiber

from ._basis import _global_filter


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber(request):
    zeilen = betreiber.kunden()
    return render(request, 'fw/betreiber.html', {
        **_global_filter(request),
        # Der Bestandsfilter der Kopfzeile listet die Liegenschaften EINER Verwaltung: Auf dieser Seite wären das
        # Kundenadressen. Der Betreiber sieht hier keine, also bleibt das Auswahlmenü leer.
        'alle_liegenschaften': [], 'aktive_lg': None, 'lg_query': '',
        'nav': 'einstellungen', 'kunden': zeilen,
        'mit_befund': sum(1 for k in zeilen if k.befunde),
    })


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber_neu(request):
    """Etappe 2: Kunde anlegen. Derselbe Dienst wie der Befehl `organisation_anlegen`, plus Einladung per Mail.

    Der Inhaber bekommt KEIN Passwort vom Betreiber: Das Konto entsteht mit unbrauchbarem Passwort, die Person setzt ihres
    über den Link der Einladungs-Mail selbst. Geht die Mail nicht hinaus, zeigt die Seite den Link einmal an, damit der
    Betreiber ihn weitergeben kann. Protokolliert wird im Kontext der NEUEN Verwaltung (das Logbuch braucht eine).
    """
    from django.contrib import messages
    from django.db import transaction
    from django.shortcuts import redirect
    from django.utils.translation import gettext

    from core.auth import log_aktion
    from core.services.einladung import einladung_senden
    from core.services.onboarding import OnboardingFehler, organisation_anlegen
    from core.tenancy import organisation_kontext

    werte = {k: (request.POST.get(k) or '').strip() for k in ('firma', 'benutzer', 'email', 'vorname', 'nachname')}
    if request.method == 'POST':
        try:
            with transaction.atomic():
                organisation, benutzer, neu = organisation_anlegen(
                    firma=werte['firma'], benutzername=werte['benutzer'], email=werte['email'],
                    passwort=None, vorname=werte['vorname'], nachname=werte['nachname'])
        except OnboardingFehler as fehler:
            messages.error(request, str(fehler))
        else:
            gesendet, link = einladung_senden(request, benutzer, organisation, neu=neu)
            with organisation_kontext(organisation):
                log_aktion(request, 'Kunde angelegt', objekt=organisation.firma,
                           details=f'Inhaber {benutzer.get_username()}, Einladung {"gesendet" if gesendet else "nicht gesendet"}',
                           kategorie='sicherheit')
            if gesendet:
                messages.success(request, gettext('%(firma)s ist angelegt. Die Einladung ging an %(mail)s.')
                                 % {'firma': organisation.firma, 'mail': benutzer.email})
            else:
                messages.warning(request, gettext(
                    '%(firma)s ist angelegt, aber die Einladung ging nicht hinaus. Link zum Setzen des Passworts '
                    '(gilt kurz und einmal): %(link)s') % {'firma': organisation.firma, 'link': link})
            return redirect('/neu/betreiber/')
    return render(request, 'fw/betreiber_neu.html', {
        **_global_filter(request),
        'alle_liegenschaften': [], 'aktive_lg': None, 'lg_query': '',
        'nav': 'einstellungen', 'w': werte,
    })
