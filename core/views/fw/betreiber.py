# core/views/fw/betreiber.py
"""Betreiber-Portal: Kundenliste, Kunde anlegen, Abo-Verwaltung (ein eigener Bereich unter /betreiber/).

NUR FÜR DEN BETREIBER (Superuser, mit Zwei-Faktor wie alle). Gezeigt werden Zähler, Abostufe und Befunde (was bei einer
Verwaltung fehlt) — keine Verträge, Personen oder Buchungen, und es gibt kein «Als Kunde einloggen». Ändern kann diese
Seite noch nichts; Anlegen und Abo-Verwaltung folgen in eigenen Etappen.
"""
from django.shortcuts import render

from core.auth import BETREIBER_ROLLEN, rolle_erforderlich
from core.services import betreiber



@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber(request):
    zeilen = betreiber.kunden()
    return render(request, 'fw/betreiber.html', {
        'aktiv': 'kunden', 'kunden': zeilen,
        'mit_befund': sum(1 for k in zeilen if k.befunde),
    })


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber_csp(request):
    """CSP-Meldungen aus dem Anwendungs-Log, zusammengefasst — damit der Betreiber vor `enforce` nicht auf den Server muss."""
    from core.services import csp_meldungen
    return render(request, 'fw/betreiber_csp.html', {'aktiv': 'csp', **csp_meldungen.uebersicht()})


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

    from datetime import date

    werte = {k: (request.POST.get(k) or '').strip()
             for k in ('firma', 'benutzer', 'email', 'vorname', 'nachname', 'abrechnung_ab')}
    if request.method == 'POST':
        try:
            ab = date.fromisoformat(werte['abrechnung_ab']) if werte['abrechnung_ab'] else None
        except ValueError:
            messages.error(request, gettext('Das Datum «Abrechnung ab» ist ungültig.'))
            ab, fehler_datum = None, True
        else:
            fehler_datum = False
        try:
            if fehler_datum:
                raise OnboardingFehler('')
            with transaction.atomic():
                organisation, benutzer, neu = organisation_anlegen(
                    firma=werte['firma'], benutzername=werte['benutzer'], email=werte['email'],
                    passwort=None, vorname=werte['vorname'], nachname=werte['nachname'])
                if ab:
                    # Ende der Testphase: bis dahin stellt der Abrechnungslauf nichts in Rechnung.
                    abo = organisation.abonnement
                    abo.abrechnung_ab = ab
                    abo.save(update_fields=['abrechnung_ab'])
        except OnboardingFehler as fehler:
            if str(fehler):
                messages.error(request, str(fehler))
        else:
            gesendet, link = einladung_senden(request, benutzer, organisation, neu=neu)
            with organisation_kontext(organisation):
                log_aktion(request, 'Kunde angelegt', objekt=organisation.firma,
                           details=f'Inhaber {benutzer.get_username()}, Einladung {"gesendet" if gesendet else "nicht gesendet"}, '
                                   f'Abrechnung ab {ab or "nicht gesetzt"}',
                           kategorie='sicherheit')
            if gesendet:
                messages.success(request, gettext('%(firma)s ist angelegt. Die Einladung ging an %(mail)s.')
                                 % {'firma': organisation.firma, 'mail': benutzer.email})
            else:
                messages.warning(request, gettext(
                    '%(firma)s ist angelegt, aber die Einladung ging nicht hinaus. Link zum Setzen des Passworts '
                    '(gilt kurz und einmal): %(link)s') % {'firma': organisation.firma, 'link': link})
            return redirect('/betreiber/')
    return render(request, 'fw/betreiber_neu.html', {
        'aktiv': 'kunden', 'w': werte,
    })


def _kunde_oder_404(pk):
    from django.http import Http404

    from crm.models import Organisation
    org = Organisation.objects.filter(pk=pk).first()
    if org is None:
        raise Http404
    return org


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber_kunde(request, pk):
    """Etappe 3: Abo-Verwaltung einer Verwaltung — Stufe, Module, Abrechnung, Rechnungen, Zahlung, Storno.

    Nur die Dienste in `abo/dienst.py` (dieselben wie der Befehl `abo_einstellen`); nichts wird gelöscht, eine Rechnung wird
    storniert, ein Modul ausgeschaltet. Ein Planwechsel zeigt vorher, was er schliesst (`folgen_des_wechsels`) und
    verlangt dann eine Bestätigung. Jede Änderung steht im Logbuch DIESER Verwaltung. Gezeigt werden Zähler und Abo-Daten,
    keine Verträge, Personen oder Buchungen.
    """
    from datetime import date

    from django.contrib import messages
    from django.shortcuts import redirect
    from django.utils.translation import gettext

    from abo import dienst
    from abo.models import AboRechnung, Abonnement
    from core import funktionen as f
    from core.auth import log_aktion
    from core.tenancy import organisation_kontext

    org = _kunde_oder_404(pk)
    abo = Abonnement.alle_organisationen.filter(organisation=org).first()
    ziel = f'/betreiber/{org.pk}/'
    vorschau = None

    def protokoll(aktion, details=''):
        with organisation_kontext(org):
            log_aktion(request, aktion, objekt=org.firma, details=details, kategorie='sicherheit')

    if request.method == 'POST':
        aktion = request.POST.get('aktion', '')
        try:
            if aktion == 'abo_anlegen':
                dienst.abonnement_anlegen(org)
                protokoll('Abonnement angelegt')
            elif aktion == 'plan':
                stufe = request.POST.get('stufe', '')
                jaehrlich = request.POST.get('intervall') == 'jaehrlich'
                if stufe not in f.STUFEN:
                    raise ValueError(gettext('Unbekannte Stufe.'))
                folgen = dienst.folgen_des_wechsels(org, stufe)
                if (folgen['schliesst'] or folgen['bestand_ueber']) and not request.POST.get('bestaetigt'):
                    vorschau = {'stufe': stufe, 'jaehrlich': jaehrlich, 'folgen': folgen,
                                'schliesst': [f.FUNKTIONEN.get(k, k) for k in folgen['schliesst']]}
                else:
                    dienst.plan_wechseln(org, stufe, jaehrlich)
                    protokoll('Stufe gewechselt', f'{stufe}, {"jährlich" if jaehrlich else "monatlich"}')
                    messages.success(request, gettext('Stufe gesetzt.'))
            elif aktion == 'einstellen' and abo is not None:
                module = [k for k in request.POST.getlist('module') if k in f.MODULE]
                ab = (request.POST.get('abrechnung_ab') or '').strip()
                abo.zusatzmodule = module
                abo.abrechnung_ab = date.fromisoformat(ab) if ab else None
                abo.uneingeschraenkt = bool(request.POST.get('bestandsschutz'))
                abo.save()
                protokoll('Abonnement eingestellt',
                          f'Module {",".join(module) or "-"}, Abrechnung ab {abo.abrechnung_ab or "-"}, '
                          f'Bestandsschutz {"an" if abo.uneingeschraenkt else "aus"}')
                messages.success(request, gettext('Abonnement gespeichert.'))
            elif aktion in ('bezahlt', 'storno'):
                rechnung = AboRechnung.alle_organisationen.filter(
                    organisation=org, pk=request.POST.get('rechnung') or 0).first()
                if rechnung is None:
                    raise ValueError(gettext('Diese Rechnung gehört nicht zu dieser Verwaltung.'))
                if rechnung.status != AboRechnung.STATUS_OFFEN:
                    raise ValueError(gettext('Nur offene Rechnungen lassen sich bezahlen oder stornieren.'))
                if aktion == 'bezahlt':
                    datum = (request.POST.get('datum') or '').strip()
                    dienst.als_bezahlt(rechnung, date.fromisoformat(datum) if datum else None)
                    protokoll('Zahlung bestätigt', f'Rechnung {rechnung.nummer}')
                    messages.success(request, gettext('Zahlung bestätigt.'))
                else:
                    dienst.stornieren(rechnung)
                    protokoll('Rechnung storniert', f'Rechnung {rechnung.nummer}')
                    messages.success(request, gettext('Rechnung storniert.'))
            else:
                raise ValueError(gettext('Unbekannte Aktion.'))
        except ValueError as fehler:
            messages.error(request, str(fehler))
        else:
            if vorschau is None:
                return redirect(ziel)

    abo = Abonnement.alle_organisationen.filter(organisation=org).first()
    kunde = next(k for k in betreiber.kunden() if k.organisation.pk == org.pk)
    return render(request, 'fw/betreiber_kunde.html', {
        'aktiv': 'kunden', 'k': kunde, 'org': org, 'abo': abo, 'vorschau': vorschau,
        'stufen': [(s, f.STUFEN_NAMEN[s]) for s in f.STUFEN_REIHENFOLGE],
        'module': list(f.MODULE.items()), 'zugebucht': set(abo.zusatzmodule or []) if abo else set(),
        'rechnungen': AboRechnung.alle_organisationen.filter(organisation=org).order_by('-rechnungsdatum', '-pk')[:50],
        'nutzung': dienst.nutzung_von(org),
        'jaehrlich': org.abo_jaehrlich,
    })
