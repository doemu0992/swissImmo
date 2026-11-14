# core/views/fw/betreiber.py
"""Betreiber-Portal: Kundenliste, Kunde anlegen, Abo-Verwaltung (ein eigener Bereich unter /betreiber/).

NUR FÜR DEN BETREIBER (Superuser, mit Zwei-Faktor wie alle). Gezeigt werden Zähler, Abostufe und Befunde (was bei einer
Verwaltung fehlt) — keine Verträge, Personen oder Buchungen, und es gibt kein «Als Kunde einloggen». Ändern kann diese
Seite noch nichts; Anlegen und Abo-Verwaltung folgen in eigenen Etappen.
"""
from django.shortcuts import render

from core.zeit import datum_heute

from core.auth import BETREIBER_ROLLEN, rolle_erforderlich
from core.services import betreiber



@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber(request):
    from core.services import datenpflege
    zeilen = betreiber.kunden()
    return render(request, 'fw/betreiber.html', {
        'aktiv': 'kunden', 'kunden': zeilen, 'pflege': datenpflege.faellig(datum_heute()),
        'mit_befund': sum(1 for k in zeilen if k.befunde),
    })


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber_csp(request):
    """CSP-Meldungen aus dem Anwendungs-Log, zusammengefasst — damit der Betreiber vor `enforce` nicht auf den Server muss."""
    from core.services import csp_meldungen
    return render(request, 'fw/betreiber_csp.html', {'aktiv': 'csp', **csp_meldungen.uebersicht()})


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber_lik(request):
    """Monatswerte des Landesindex nachtragen (statt im Code): die Reihe der letzten Monate und ein Formular.

    Der Wert kommt vom Betreiber aus der BFS-Publikation; der Live-Wert der HEV-Seite wird nur als Vorschlag
    gezeigt, nie selbständig übernommen. Ein bestehender Monat wird überschrieben (Korrektur), die Quelle ist Pflicht.
    """
    from datetime import timedelta
    from decimal import Decimal, InvalidOperation

    from django.conf import settings
    from django.contrib import messages
    from django.shortcuts import redirect
    from django.utils.translation import gettext

    from core.models import LikWert, SicherheitsEreignis
    from core.auth import client_ip
    from core.utils.betrag import betrag_parsen
    from core.services import lik

    heute = datum_heute()
    fehler = None
    vor = heute.replace(day=1) - timedelta(days=1)                # der Vormonat: der jüngste, der veröffentlicht sein kann
    werte = {'jahr': vor.year, 'monat': vor.month, 'punkte': '', 'quelle': ''}
    if request.method == 'POST' and request.POST.get('aktion') == 'loeschen':
        # Nur nachgetragene Werte lassen sich löschen; die Reihe im Code bleibt (sie ändert ein Deployment).
        try:
            eintrag = LikWert.objects.filter(pk=int(request.POST.get('pk') or 0), basis=lik.LIK_BASIS).first()
        except (TypeError, ValueError):
            eintrag = None
        if eintrag is not None:
            SicherheitsEreignis.objects.create(
                aktion='LIK-Wert gelöscht', objekt=f'{eintrag.monat:02d}/{eintrag.jahr}',
                ip_adresse=client_ip(request) or None,
                details=f'{eintrag.punkte} Punkte, Quelle: {eintrag.quelle}')
            messages.success(request, gettext('LIK %(monat)s/%(jahr)s gelöscht.')
                             % {'monat': f'{eintrag.monat:02d}', 'jahr': eintrag.jahr})
            eintrag.delete()
        return redirect('fw_betreiber_lik')
    if request.method == 'POST':
        werte.update({k: (request.POST.get(k) or '').strip() for k in ('jahr', 'monat', 'punkte', 'quelle')})
        try:
            jahr, monat = int(werte['jahr']), int(werte['monat'])
            punkte = betrag_parsen(werte['punkte']).quantize(Decimal('0.1'))
        except (ValueError, InvalidOperation):
            jahr = monat = punkte = None
        quelle = werte['quelle'][:200]
        if jahr is None or not (1 <= monat <= 12):
            fehler = gettext('Jahr, Monat und Punkte müssen Zahlen sein (Monat 1 bis 12).')
        elif (jahr, monat) >= (heute.year, heute.month) or jahr < 2020:
            fehler = gettext('Der Monat liegt vor 2020 oder ist noch nicht veröffentlicht: Das BFS gibt den Wert eines '
                             'Monats erst Anfang des Folgemonats bekannt.')
        elif lik.lik_punkte_fuer(*((jahr, monat - 1) if monat > 1 else (jahr - 1, 12))) is None:
            fehler = gettext('Der Vormonat fehlt noch. Bitte die Monate der Reihe nach eintragen, sonst entsteht eine '
                             'Lücke.')
        elif not (Decimal('100') <= punkte <= Decimal('140')):
            fehler = gettext('Der Wert liegt ausserhalb von 100 bis 140 Punkten (Basis Dezember 2020 = 100). Tippfehler?')
        elif not quelle:
            fehler = gettext('Die Quelle ist Pflicht, zum Beispiel «BFS, Medienmitteilung vom 05.11.2026».')
        else:
            alt = lik.lik_punkte_fuer(jahr, monat)
            LikWert.objects.update_or_create(
                jahr=jahr, monat=monat, basis=lik.LIK_BASIS,
                defaults={'punkte': punkte, 'quelle': quelle, 'erfasst_von': request.user})
            SicherheitsEreignis.objects.create(
                aktion='LIK-Wert nachgetragen', objekt=f'{monat:02d}/{jahr}', ip_adresse=client_ip(request) or None,
                details=f'{punkte} Punkte (vorher {alt if alt is not None else "kein Wert"}), Quelle: {quelle}')
            messages.success(request, gettext('LIK %(monat)s/%(jahr)s mit %(punkte)s Punkten gespeichert.')
                             % {'monat': f'{monat:02d}', 'jahr': jahr, 'punkte': punkte})
            return redirect('fw_betreiber_lik')

    reihen = lik.lik_reihen()
    nachgetragen = {(w.jahr, w.monat): w for w in LikWert.objects.filter(basis=lik.LIK_BASIS)}
    zeilen = []
    for jahr in sorted(reihen, reverse=True):
        for monat in range(12, 0, -1):
            wert = reihen[jahr][monat - 1]
            if wert is None:
                continue
            eigener = nachgetragen.get((jahr, monat))
            zeilen.append({'jahr': jahr, 'monat': monat, 'punkte': wert, 'pk': eigener.pk if eigener else None,
                           'quelle': eigener.quelle if eigener else gettext('im Code (BFS-Tabelle)')})
        if len(zeilen) >= 18:
            break
    letzter = lik.letzter_tabellenmonat()
    live = None
    if getattr(settings, 'LIK_LIVE_ABRUF', False):
        try:
            stand, punkte_live, _basis = lik.aktueller_lik_wert(live=True)
            if stand and punkte_live and (not letzter or (stand.year, stand.month) > letzter):
                live = {'monat': f'{stand.month:02d}/{stand.year}', 'punkte': punkte_live}
        except Exception:                                    # noqa: BLE001 — ein Vorschlag darf die Seite nie stören
            live = None
    return render(request, 'fw/betreiber_lik.html', {
        'aktiv': 'lik', 'zeilen': zeilen[:18], 'w': werte, 'fehler': fehler, 'live': live,
        'letzter': f'{letzter[1]:02d}/{letzter[0]}' if letzter else None, 'basis': lik.LIK_BASIS,
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

    from datetime import date

    werte = {k: (request.POST.get(k) or '').strip()
             for k in ('firma', 'strasse', 'plz', 'ort', 'telefon', 'benutzer', 'email', 'vorname', 'nachname',
                       'abrechnung_ab')}
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
            if not (werte['strasse'] and werte['plz'] and werte['ort']):
                # Ohne Anschrift lässt sich keine Rechnung zustellen (Adressfenster, Einzahlungsschein).
                raise OnboardingFehler(gettext('Strasse, PLZ und Ort sind Pflicht: Sie stehen auf der Rechnung.'))
            with transaction.atomic():
                organisation, benutzer, neu = organisation_anlegen(
                    firma=werte['firma'], benutzername=werte['benutzer'], email=werte['email'],
                    passwort=None, vorname=werte['vorname'], nachname=werte['nachname'],
                    strasse=werte['strasse'], plz=werte['plz'], ort=werte['ort'], telefon=werte['telefon'])
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
            if ab:
                _sofort_abrechnen(request, organisation)
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


def _sofort_abrechnen(request, org):
    """Stellt die fällige Rechnung sofort, wenn «Abrechnung ab» gesetzt und die Periode (mit Vorlauf) erreicht ist.

    Abo-Rechnungen sind im Voraus zu bezahlen; der Betreiber wartet nicht auf den täglichen Lauf. Idempotent: Ist die
    Periode schon verrechnet, geschieht nichts. Meldet die erstellte Rechnung mit Fälligkeit.
    """
    from django.contrib import messages
    from django.utils.translation import gettext

    from abo import dienst
    from abo.models import Abonnement
    from core.auth import log_aktion
    from core.tenancy import organisation_kontext

    abo = Abonnement.alle_organisationen.filter(organisation=org).first()
    if abo is None or abo.uneingeschraenkt:
        return None
    try:
        rechnung = dienst.rechnung_stellen(org, abo)
    except dienst.PreiseNichtFestgelegt:
        return None
    if rechnung is not None:
        with organisation_kontext(org):
            log_aktion(request, 'Rechnung gestellt', objekt=org.firma, kategorie='sicherheit',
                       details=f'{rechnung.nummer}, {rechnung.periode_von} bis {rechnung.periode_bis}, '
                               f'CHF {rechnung.brutto}, fällig {rechnung.faellig_am}')
        messages.success(request, gettext('Rechnung %(nr)s über CHF %(betrag)s erstellt, fällig am %(datum)s.')
                         % {'nr': rechnung.nummer, 'betrag': rechnung.brutto,
                            'datum': rechnung.faellig_am.strftime('%d.%m.%Y')})
        _versenden(request, org, rechnung)
    return rechnung


def _versenden(request, org, rechnung, erinnerung=False):
    """Schickt die Rechnung mit PDF an die Verwaltung und protokolliert es. Meldet Erfolg oder den Grund des Scheiterns."""
    from django.contrib import messages
    from django.utils.translation import gettext

    from abo import dienst
    from core.auth import log_aktion
    from core.tenancy import organisation_kontext

    try:
        an = dienst.rechnung_senden(rechnung, erinnerung=erinnerung)
    except (dienst.RechnungNichtSendbar, OSError) as fehler:
        messages.warning(request, gettext('Rechnung %(nr)s nicht versandt: %(grund)s')
                         % {'nr': rechnung.nummer, 'grund': fehler})
        return False
    with organisation_kontext(org):
        log_aktion(request, 'Zahlungserinnerung gesendet' if erinnerung else 'Rechnung gesendet', objekt=org.firma,
                   details=f'{rechnung.nummer} an {an}', kategorie='sicherheit')
    messages.success(request, (gettext('Zahlungserinnerung zu %(nr)s ging an %(an)s.') if erinnerung
                               else gettext('Rechnung %(nr)s ging an %(an)s.')) % {'nr': rechnung.nummer, 'an': an})
    return True


def _stammdaten_speichern(request, org):
    """Speichert Firma, Adresse und Kontaktdaten (an der Organisation) sowie Ansprechperson, Status und Notizen (Kartei).

    Alles wird geprüft, bevor etwas geschrieben wird; bei einem Fehler bleibt der bisherige Stand.
    """
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    from django.db import transaction
    from django.utils.translation import gettext

    from abo.models import Kundenstamm
    from core.services import betreiber

    def feld(name, grenze):
        return (request.POST.get(name) or '').strip()[:grenze]

    def mail(name):
        wert = feld(name, 254)
        if wert:
            try:
                validate_email(wert)
            except ValidationError as fehler:
                raise ValueError(gettext('Ungültige E-Mail-Adresse: %(wert)s') % {'wert': wert}) from fehler
        return wert

    firma, strasse, plz, ort = feld('firma', 100), feld('strasse', 100), feld('plz', 10), feld('ort', 100)
    if not (firma and strasse and plz and ort):
        raise ValueError(gettext('Firma, Strasse, PLZ und Ort sind Pflicht.'))
    status = feld('status', 12)
    if status not in dict(Kundenstamm.STATUS):
        raise ValueError(gettext('Unbekannter Status.'))
    organisation_werte = dict(firma=firma, strasse=strasse, plz=plz, ort=ort, telefon=feld('telefon', 30),
                              email=mail('email'), mwst_uid=feld('mwst_uid', 20))
    stamm_werte = dict(
        status=status, natel=feld('natel', 30), website=feld('website', 200), ansprechperson=feld('ansprechperson', 120),
        ansprech_funktion=feld('ansprech_funktion', 120), ansprech_email=mail('ansprech_email'),
        ansprech_telefon=feld('ansprech_telefon', 30), ansprech_natel=feld('ansprech_natel', 30),
        rechnung_email=mail('rechnung_email'), notizen=(request.POST.get('notizen') or '').strip()[:8000])
    with transaction.atomic():
        for name, wert in organisation_werte.items():
            setattr(org, name, wert)
        org.save(update_fields=list(organisation_werte))
        stamm = betreiber.kartei(org)
        for name, wert in stamm_werte.items():
            setattr(stamm, name, wert)
        stamm.save()


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
    from django.utils import timezone

    from abo.models import AboRechnung, Abonnement, KundenKontakt, Kundenstamm
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
                                'schliesst': [f.FUNKTIONEN.get(k) or f.MODULE.get(k, k) for k in folgen['schliesst']]}
                else:
                    dienst.plan_wechseln(org, stufe, jaehrlich)
                    protokoll('Stufe gewechselt', f'{stufe}, {"jährlich" if jaehrlich else "monatlich"}')
                    messages.success(request, gettext('Stufe gesetzt.'))
            elif aktion == 'einstellen' and abo is not None:
                module = [k for k in request.POST.getlist('module') if k in f.MODULE]
                ab = (request.POST.get('abrechnung_ab') or '').strip()
                abo.abrechnung_ab = date.fromisoformat(ab) if ab else None
                abo.uneingeschraenkt = bool(request.POST.get('bestandsschutz'))
                abo.save(update_fields=['abrechnung_ab', 'uneingeschraenkt'])
                dienst.module_setzen(org, abo, module)
                _sofort_abrechnen(request, org)
                protokoll('Abonnement eingestellt',
                          f'Module {",".join(module) or "-"}, Abrechnung ab {abo.abrechnung_ab or "-"}, '
                          f'Bestandsschutz {"an" if abo.uneingeschraenkt else "aus"}')
                messages.success(request, gettext('Abonnement gespeichert.'))
            elif aktion == 'stamm':
                _stammdaten_speichern(request, org)
                protokoll('Kundendaten geändert')
                messages.success(request, gettext('Kundendaten gespeichert.'))
            elif aktion == 'status':
                status = request.POST.get('status', '')
                if status not in dict(Kundenstamm.STATUS):
                    raise ValueError(gettext('Unbekannter Status.'))
                stamm = betreiber.kartei(org)
                stamm.status = status
                stamm.save(update_fields=['status', 'geaendert_am'])
                protokoll('Kundendaten geändert', f'Status {stamm.get_status_display()}')
                messages.success(request, gettext('Status gesetzt.'))
            elif aktion == 'kontakt':
                text = (request.POST.get('text') or '').strip()
                art = request.POST.get('art') or KundenKontakt.ART_NOTIZ
                if not text:
                    raise ValueError(gettext('Der Eintrag ist leer.'))
                if art not in dict(KundenKontakt.ARTEN) or art == KundenKontakt.ART_SUPPORT:
                    raise ValueError(gettext('Unbekannte Art.'))
                KundenKontakt.alle_organisationen.create(
                    organisation=org, zeitpunkt=timezone.now(), art=art, text=text[:4000],
                    erfasst_von=request.user.get_username())
                messages.success(request, gettext('Eintrag gespeichert.'))
            elif aktion == 'support_erledigt':
                eintrag = KundenKontakt.alle_organisationen.filter(
                    organisation=org, art=KundenKontakt.ART_SUPPORT, pk=request.POST.get('eintrag') or 0).first()
                if eintrag is None:
                    raise ValueError(gettext('Diese Anfrage gehört nicht zu dieser Verwaltung.'))
                eintrag.erledigt_am = None if eintrag.erledigt_am else timezone.now()
                eintrag.save(update_fields=['erledigt_am'])
                messages.success(request, gettext('Anfrage als erledigt markiert.') if eintrag.erledigt_am
                                 else gettext('Anfrage wieder geöffnet.'))
            elif aktion == 'kontakt_loeschen':
                eintrag = KundenKontakt.alle_organisationen.filter(
                    organisation=org, pk=request.POST.get('eintrag') or 0).first()
                if eintrag is None:
                    raise ValueError(gettext('Dieser Eintrag gehört nicht zu dieser Verwaltung.'))
                eintrag.delete()
                messages.success(request, gettext('Eintrag gelöscht.'))
            elif aktion in ('senden', 'erinnern'):
                rechnung = AboRechnung.alle_organisationen.filter(
                    organisation=org, pk=request.POST.get('rechnung') or 0).first()
                if rechnung is None:
                    raise ValueError(gettext('Diese Rechnung gehört nicht zu dieser Verwaltung.'))
                if rechnung.status != AboRechnung.STATUS_OFFEN:
                    raise ValueError(gettext('Nur offene Rechnungen lassen sich senden oder anmahnen.'))
                _versenden(request, org, rechnung, erinnerung=(aktion == 'erinnern'))
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
                return redirect(f'{ziel}?tab={_REITER_NACH_AKTION.get(aktion, "uebersicht")}')
        # Fehler oder Rückfrage: die Seite zeigen, auf der die Eingabe gemacht wurde (das Formular behält die Werte).
        if aktion == 'stamm':
            return _seite_bearbeiten(request, org, werte=request.POST)
        if aktion in ('plan', 'einstellen'):
            return _seite_abo(request, org, vorschau)
        return redirect(f'{ziel}?tab={_REITER_NACH_AKTION.get(aktion, "uebersicht")}')

    tab = request.GET.get('tab', 'uebersicht')
    return _seite_kunde(request, org, tab if tab in REITER_KUNDE else 'uebersicht')


#: Reiter der Kundenseite (Schlüssel, Beschriftung) und der Reiter, auf dem eine Aktion landet.
REITER_KUNDE = ('uebersicht', 'stamm', 'verlauf', 'finanzen', 'abo')
_REITER_NACH_AKTION = {
    'stamm': 'stamm', 'status': 'uebersicht', 'kontakt': 'verlauf', 'kontakt_loeschen': 'verlauf',
    'senden': 'finanzen', 'erinnern': 'finanzen', 'support_erledigt': 'verlauf', 'bezahlt': 'finanzen', 'storno': 'finanzen',
    'plan': 'abo', 'einstellen': 'abo', 'abo_anlegen': 'abo',
}


def _kunden_kontext(org):
    from abo import dienst
    from abo.models import Abonnement
    from core import funktionen as f
    abo = Abonnement.alle_organisationen.filter(organisation=org).first()
    return {
        'aktiv': 'kunden', 'org': org, 'abo': abo,
        'k': next(k for k in betreiber.kunden() if k.organisation.pk == org.pk),
        'stamm': betreiber.kartei(org), 'jaehrlich': org.abo_jaehrlich,
        'stufen': [(s, f.STUFEN_NAMEN[s]) for s in f.STUFEN_REIHENFOLGE],
        'nutzung': dienst.nutzung_von(org),
    }


def _seite_kunde(request, org, tab):
    """Die Kundenseite: Kopf mit Kennzahlen und fünf Reiter, nur zum Lesen. Geändert wird auf eigenen Seiten."""
    from django.utils.translation import gettext

    from abo.models import AboRechnung, KundenKontakt, Kundenstamm
    from core import funktionen as f
    kontext = _kunden_kontext(org)
    abo = kontext['abo']
    verlauf = betreiber.verlauf(org)
    rechnungen = list(AboRechnung.alle_organisationen.filter(organisation=org).order_by('-rechnungsdatum', '-pk')[:50])
    kontext.update({
        'tab': tab, 'heute': datum_heute(),
        'reiter': [('uebersicht', gettext('Übersicht'), ''), ('stamm', gettext('Stammdaten'), ''),
                   ('verlauf', gettext('Verlauf'), len(verlauf) or ''),
                   ('finanzen', gettext('Finanzen'), sum(1 for r in rechnungen if r.status == AboRechnung.STATUS_OFFEN) or ''),
                   ('abo', gettext('Abonnement'), '')], 'finanzen': betreiber.finanzen(org), 'verlauf': verlauf,
        'verlauf_kurz': verlauf[:3], 'rechnungen': rechnungen,
        'offene': sum(1 for r in rechnungen if r.status == AboRechnung.STATUS_OFFEN),
        'module': [(k, n, f.modul_monatspreis(f.stufe_von(org), k)) for k, n in f.MODULE.items()
                   if abo and k in (abo.zusatzmodule or [])],
        'stati': Kundenstamm.STATUS, 'arten': [a for a in KundenKontakt.ARTEN if a[0] != KundenKontakt.ART_SUPPORT],
        'support_offen': kontext['k'].support_offen,
    })
    return render(request, 'fw/betreiber_kunde.html', kontext)


def _seite_bearbeiten(request, org, werte=None):
    """Die Seite zum Ändern der Stammdaten und der Ansprechperson. `werte` = eben abgeschickte Eingabe (bei einem Fehler)."""
    from abo.models import Kundenstamm
    kontext = _kunden_kontext(org)
    s = kontext['stamm']
    if werte is None:
        werte = {'firma': org.firma, 'strasse': org.strasse, 'plz': org.plz, 'ort': org.ort, 'telefon': org.telefon,
                 'email': org.email, 'mwst_uid': org.mwst_uid, 'natel': s.natel, 'website': s.website,
                 'status': s.status, 'ansprechperson': s.ansprechperson, 'ansprech_funktion': s.ansprech_funktion,
                 'ansprech_email': s.ansprech_email, 'ansprech_telefon': s.ansprech_telefon,
                 'ansprech_natel': s.ansprech_natel, 'rechnung_email': s.rechnung_email, 'notizen': s.notizen}
    kontext.update({'w': {k: werte.get(k, '') for k in (
        'firma', 'strasse', 'plz', 'ort', 'telefon', 'email', 'mwst_uid', 'natel', 'website', 'status', 'ansprechperson',
        'ansprech_funktion', 'ansprech_email', 'ansprech_telefon', 'ansprech_natel', 'rechnung_email', 'notizen')},
        'stati': Kundenstamm.STATUS})
    return render(request, 'fw/betreiber_kunde_bearbeiten.html', kontext)


def _seite_abo(request, org, vorschau=None):
    """Die Seite zum Ändern des Abonnements: Stufe (mit Folgen vorab), Module, «Abrechnung ab», Bestandsschutz."""
    from core import funktionen as f
    kontext = _kunden_kontext(org)
    abo = kontext['abo']
    stufe = f.stufe_von(org)
    kontext.update({'vorschau': vorschau,
                    'module': [(k, n, f.MODULPREISE[k]['monat'], f.modul_inklusive(stufe, k)) for k, n in f.MODULE.items()],
                    'zugebucht': set(abo.zusatzmodule or []) if abo else set()})
    return render(request, 'fw/betreiber_kunde_abo.html', kontext)


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber_kunde_bearbeiten(request, pk):
    return _seite_bearbeiten(request, _kunde_oder_404(pk))


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber_kunde_abo(request, pk):
    return _seite_abo(request, _kunde_oder_404(pk))


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber_rechnung_pdf(request, pk, rechnung):
    """Die Abo-Rechnung einer Verwaltung als PDF mit QR-Einzahlungsschein. Nur der Betreiber; die Rechnung muss zur Verwaltung gehören."""
    from django.contrib import messages
    from django.http import HttpResponse
    from django.shortcuts import get_object_or_404, redirect
    from django.utils.translation import gettext

    from abo.models import AboRechnung
    from abo.rechnung_pdf import abo_rechnung_pdf

    org = _kunde_oder_404(pk)
    beleg = get_object_or_404(AboRechnung.alle_organisationen.select_related('organisation'),
                              pk=rechnung, organisation=org)
    pdf = abo_rechnung_pdf(beleg)
    if pdf is None:
        messages.warning(request, gettext('Es ist keine Zahlungsverbindung (IBAN) des Rechnungsstellers hinterlegt.'))
        return redirect(f'/betreiber/{org.pk}/')
    antwort = HttpResponse(pdf, content_type='application/pdf')
    antwort['Content-Disposition'] = f'inline; filename="{beleg.nummer}.pdf"'
    return antwort
