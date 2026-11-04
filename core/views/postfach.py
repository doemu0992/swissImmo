"""E-Mail-Eingang — die Plattformadressen (Standard) und eigene Postfächer per IMAP (Erweitert).

STAND 4.11.2026. Der Standard braucht keine Zugangsdaten: Antworten auf Tickets und eingehende Rechnungen
laufen über zwei Adressen der Plattform (``core/services/antwort_eingang.py``), je Verwaltung, und wer sein
eigenes Postfach behalten will, richtet dort eine Weiterleitung ein. Der IMAP-Abruf mit hinterlegten
Zugangsdaten bleibt als Sonderfall («Erweitert»), und die Seite sagt, dass die Weiterleitung einfacher ist —
Passwörter ändern sich, die Verschlüsselung der Zugangsdaten macht jede Änderung mühsam.

Der ursprüngliche Text dieses Moduls (Postfächer einrichten) gilt für den Erweitert-Teil:

Bis hierher lagen die Zugangsdaten in Umgebungsvariablen; ändern hiess: jemand
mit Serverzugang bearbeitet eine Datei. Für **eine** Verwaltung ging das. Ab der
zweiten geht es nicht mehr — jede hat ihr eigenes Postfach bei ihrem eigenen
Anbieter, und keine soll dafür bei uns anrufen müssen.

DREI ENTSCHEIDUNGEN, DIE MAN BEIM LESEN SUCHEN WÜRDE

**1. Das gespeicherte Geheimnis geht nie zurück ins Formular.** Weder als
`value`, noch als Sternchen, noch als Länge. Ein Passwortfeld, das den
gespeicherten Wert vorbefüllt, gibt ihn im HTML-Quelltext preis — an jeden, der
über eine offene Sitzung an den Bildschirm kommt.

**2. Ein leeres Passwortfeld heisst «unverändert», nicht «löschen».** Sonst
löscht jemand beim Ändern der Portnummer versehentlich den Zugang, und der
Ausfall fällt erst in der nächsten Nacht auf. Wer den Zugang wirklich entfernen
will, schaltet das Postfach ab oder löscht es.

**3. Ändern dürfen nur Inhaber und Verwalter.** Lesezugriff und
Sachbearbeitung sehen den Zustand — dass der Abruf klemmt, sollen sie merken —,
ändern aber nichts. Ein Postfachzugang ist der Schlüssel zur gesamten
Geschäftskorrespondenz einer Verwaltung.
"""
from django.contrib import messages
from django.utils.translation import gettext
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auth import INHABER_ROLLEN, TEAM_ROLLEN, VERWALTUNGS_ROLLEN, hat_rolle, log_aktion, rolle_erforderlich
from core.models import Postfach
from core.services.geheimnis import UMGEBUNGSNAME, schluessel_vorhanden
from core.views.fw._basis import _global_filter
from core.services.dokumentsprache import auf_deutsch


def _darf_aendern(request):
    """Nur für die Anzeige — ob Knöpfe erscheinen. Nicht die Absicherung.

    Die Absicherung steht am Dekorator der jeweiligen View. Das war zuerst
    anders gelöst (alle Views auf `TEAM_ROLLEN`, dazu eine Prüfung im Rumpf),
    und der Registrylauf in `core/tests/test_sicherheit.py` hat es zu Recht
    beanstandet: «Für ALLE Team-Rollen schreibbar, auch Lesend». Die Prüfung
    im Rumpf funktionierte zwar, aber der Dekorator sagte etwas anderes — und
    er ist es, den `darf_oeffnen` und jeder Prüflauf lesen. Eine Absicherung,
    die nur im Rumpf steht, ist von aussen nicht als solche erkennbar.
    """
    return hat_rolle(getattr(request, 'user', None), VERWALTUNGS_ROLLEN)


@rolle_erforderlich(*TEAM_ROLLEN)
def postfach_liste(request):
    """Oben die zwei Plattformadressen, darunter eingeklappt die eigenen Postfächer.

    Bei den Postfächern bewusst beide Zeilen immer, statt nur der vorhandenen: Ein Zweck, den es
    nicht gibt, ist der häufigere Zustand und der, den man sucht.
    """
    basis = _global_filter(request)
    vorhanden = {p.zweck: p for p in Postfach.objects.all()}
    zeilen = [{'zweck': wert, 'bezeichnung': text, 'postfach': vorhanden.get(wert),
               'unlesbar': bool(vorhanden.get(wert)) and not vorhanden[wert].zugang_lesbar}
              for wert, text in Postfach.ZWECKE]
    karten = _adresskarten(request, vorhanden)
    return render(request, 'core/postfach_liste.html', {
        **basis, 'nav': 'einstellungen', 'zeilen': zeilen,
        'darf_aendern': _darf_aendern(request),
        'darf_erneuern': hat_rolle(getattr(request, 'user', None), INHABER_ROLLEN),
        'antwort': karten and karten['antwort'], 'rechnung': karten and karten['rechnung'],
        'erweitert_offen': any(z['postfach'] for z in zeilen),
        'plattform_status': _plattform_status(request),
        # Ohne Schlüssel lässt sich kein Passwort ablegen. Das gehört auf die
        # Seite und nicht in ein Serverprotokoll — sonst speichert jemand
        # dreimal und versteht die Fehlermeldung nicht.
        'schluessel_fehlt': not schluessel_vorhanden(),
        'schluessel_name': UMGEBUNGSNAME,
    })


def _plattform_status(request):
    """Die kleine Zeile «Plattform-Postfach zuletzt abgerufen» — nur für den Inhaber und nur, wenn das
    Plattform-Postfach eingerichtet ist. Sie betrifft die ganze Installation, darum steht dort kein Servername
    und kein Benutzer (der Fehlertext ist schon so formuliert, siehe ``plattform_postfach.verbinden``)."""
    from core.models import PlattformEingangStatus
    from core.services.plattform_postfach import plattform_eingang_status
    if not plattform_eingang_status()['imap'] or not hat_rolle(getattr(request, 'user', None), INHABER_ROLLEN):
        return None
    eintrag = PlattformEingangStatus.objects.filter(pk=1).first()
    return {'abruf': eintrag.letzter_abruf if eintrag else None,
            'fehler': eintrag.letzter_fehler if eintrag else ''}


def _letzter_eingang(zweck):
    """Wann zuletzt eine Mail an diese Adresse der EIGENEN Verwaltung ankam (``objects`` filtert über den
    Mandantenkontext des Requests)."""
    from tickets.models import EingegangeneMail
    eintrag = EingegangeneMail.objects.filter(zweck=zweck).order_by('-erstellt_am').first()
    return eintrag.erstellt_am if eintrag else None


def _adresskarten(request, vorhanden):
    """Die zwei Karten «Antworten auf Tickets» und «Eingehende Rechnungen»: nur die Adressen der EIGENEN
    Verwaltung (aus dem Kontext), ob der Empfang auf dem Server eingerichtet ist und wann zuletzt etwas kam."""
    from crm.models import Organisation
    from core.services import antwort_eingang as ae
    from core.services.plattform_postfach import plattform_eingang_status
    org = Organisation.objects.filter(pk=request.organisation.pk).first()
    if org is None:
        return None
    kanaele = plattform_eingang_status()
    eingang = kanaele['eingerichtet']
    antwort_pf = vorhanden.get(Postfach.ZWECK_ANTWORTEN)
    # Ein eigenes Postfach gilt nur, wenn es nutzbar ist (wie `tickets.workflow.reply_to`).
    eigenes = bool(antwort_pf and antwort_pf.aktiv and '@' in (antwort_pf.benutzer or '')
                   and antwort_pf.zugang_lesbar)
    unlesbar = bool(antwort_pf and antwort_pf.aktiv and not antwort_pf.zugang_lesbar)
    rechnung_pf = vorhanden.get(Postfach.ZWECK_RECHNUNGEN)
    return {
        'antwort': {
            'adresse': ae.antwort_adresse(org),
            'eigenes_postfach': antwort_pf.benutzer if eigenes else '',
            'plattform_gilt': not eigenes and eingang,
            'eingang_fehlt': not eigenes and not eingang,
            'kanal_brevo': kanaele['brevo'], 'kanal_imap': kanaele['imap'],
            'postfach_unlesbar': unlesbar,
            'alt_bis': org.antwort_kennung_alt_bis if ae.alte_kennung_gilt(org) else None,
            'letzter_eingang': _letzter_eingang(ae.ZWECK_ANTWORTEN),
        },
        'rechnung': {
            'adresse': ae.rechnungs_adresse(org),
            'eingang_ok': eingang,
            # Anhänge lassen sich nur dann nicht laden, wenn Brevo der EINZIGE Kanal ist und der Schlüssel fehlt;
            # über das Plattform-Postfach liegen sie in der Mail selbst.
            'anhaenge_ok': not kanaele['anhaenge_fehlen'],
            'kanal_brevo': kanaele['brevo'], 'kanal_imap': kanaele['imap'],
            'eigenes_postfach': rechnung_pf.benutzer if (rechnung_pf and rechnung_pf.aktiv
                                                         and rechnung_pf.zugang_lesbar) else '',
            'alt_bis': org.antwort_kennung_alt_bis if ae.alte_kennung_gilt(org) else None,
            'letzter_eingang': _letzter_eingang(ae.ZWECK_RECHNUNGEN),
        },
    }


@rolle_erforderlich(*INHABER_ROLLEN)
@require_POST
def antwortadresse_erneuern(request):
    """Neue Kennung für die Plattformadressen der Verwaltung (Antworten UND Rechnungen hängen an derselben
    Kennung). Die bisherige bleibt 30 Tage gültig.

    Nur der Inhaber: Mails, die schon unterwegs sind, tragen die alte Adresse, und eine eingerichtete
    Weiterleitung im Mailprogramm muss auf die neue Rechnungsadresse umgestellt werden. Protokolliert."""
    from crm.models import Organisation
    from core.services.antwort_eingang import kennung_erneuern
    org = get_object_or_404(Organisation.objects.filter(pk=request.organisation.pk))
    kennung_erneuern(org)
    log_aktion(request, 'Antwortadresse erneuert', org.firma,
               'Antwort- und Rechnungsadresse. Die bisherigen Adressen gelten noch 30 Tage.')
    messages.success(request, gettext('Die Adressen wurden erneuert. Die bisherigen Adressen gelten noch 30 Tage — stellen Sie Weiterleitungen auf die neue Rechnungsadresse um.'))
    return redirect('postfach_liste')


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
def postfach_form(request, zweck):
    """Anlegen und Bearbeiten — je Zweck genau eines."""
    if zweck not in dict(Postfach.ZWECKE):
        raise PermissionDenied('Unbekannter Zweck.')

    basis = _global_filter(request)
    postfach = Postfach.objects.filter(zweck=zweck).first()

    if request.method == 'POST':
        fehler = _speichern(request, postfach, zweck)
        if not fehler:
            return redirect('postfach_liste')
        for text in fehler:
            messages.error(request, text)
        # Nach einem Fehler die EINGABE zurückgeben, nicht den gespeicherten
        # Stand — sonst tippt die Verwalterin alles noch einmal.
        eingabe = request.POST
    else:
        eingabe = None

    return render(request, 'core/postfach_form.html', {
        **basis, 'nav': 'einstellungen', 'postfach': postfach, 'zweck': zweck,
        'zweck_text': dict(Postfach.ZWECKE)[zweck], 'eingabe': eingabe,
        'verfahren_wahl': Postfach.VERFAHREN,
        'schluessel_fehlt': not schluessel_vorhanden(),
        'schluessel_name': UMGEBUNGSNAME,
    })


def _speichern(request, postfach, zweck):
    """Formular übernehmen. Gibt die Fehlermeldungen zurück (leer = geklappt)."""
    daten = request.POST
    verfahren = daten.get('verfahren') or Postfach.VERFAHREN_PASSWORT
    if verfahren not in dict(Postfach.VERFAHREN):
        return ['Unbekanntes Verfahren.']

    neu = postfach is None
    if neu:
        postfach = Postfach(organisation=request.organisation, zweck=zweck)

    postfach.verfahren = verfahren
    postfach.aktiv = daten.get('aktiv') == 'an'
    postfach.benutzer = (daten.get('benutzer') or '').strip()
    postfach.server = (daten.get('server') or '').strip()
    postfach.ordner = (daten.get('ordner') or 'INBOX').strip() or 'INBOX'
    postfach.mandant_id = (daten.get('mandant_id') or '').strip()
    postfach.anwendung_id = (daten.get('anwendung_id') or '').strip()

    try:
        port = int(daten.get('port') or 993)
    except (TypeError, ValueError):
        return ['Der Port muss eine Zahl sein.']
    if not 1 <= port <= 65535:
        return ['Der Port muss zwischen 1 und 65535 liegen.']
    postfach.port = port

    fehler = []
    if not postfach.benutzer:
        fehler.append('Benutzername beziehungsweise E-Mail-Adresse fehlt.')
    if verfahren == Postfach.VERFAHREN_PASSWORT and not postfach.server:
        fehler.append('IMAP-Server fehlt.')

    # LEER HEISST UNVERÄNDERT — siehe Kopf.
    neues_passwort = daten.get('passwort') or ''
    neuer_token = daten.get('refresh_token') or ''
    if (neues_passwort or neuer_token) and not schluessel_vorhanden():
        fehler.append(f'{UMGEBUNGSNAME} ist auf dem Server nicht gesetzt — ohne diesen '
                      'Schlüssel lassen sich Zugangsdaten nicht ablegen.')
    if fehler:
        return fehler

    if neues_passwort:
        postfach.passwort = neues_passwort
    if neuer_token:
        postfach.refresh_token = neuer_token

    if verfahren == Postfach.VERFAHREN_PASSWORT and not postfach.passwort_geheim:
        return ['Passwort fehlt.']
    if not neu and not (neues_passwort or neuer_token) and not postfach.zugang_lesbar:
        # «Leer heisst unverändert» hilft hier nicht: Das Gespeicherte ist unlesbar (Schlüssel gewechselt).
        return ['Die gespeicherten Zugangsdaten lassen sich nicht mehr lesen — bitte das Passwort neu eingeben.']
    if verfahren == Postfach.VERFAHREN_OAUTH2 and not (postfach.mandant_id
                                                       and postfach.anwendung_id):
        return ['Für OAuth2 werden Verzeichnis-ID und Anwendungs-ID gebraucht.']

    postfach.save()
    log_aktion(request, 'Postfach gespeichert' if not neu else 'Postfach angelegt',
               auf_deutsch(postfach.get_zweck_display),
               f'{postfach.benutzer} auf {postfach.server or "(OAuth2)"}')
    messages.success(request, gettext('Postfach «%(get_zweck_display)s» gespeichert. Prüfen Sie die Verbindung.') % {'get_zweck_display': postfach.get_zweck_display()})
    return []


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
@require_POST
def postfach_test(request, zweck):
    """Verbindung jetzt prüfen — mit einer Meldung, aus der etwas folgt.

    Ohne diesen Knopf merkt eine Verwaltung erst beim nächsten nächtlichen
    Lauf, dass etwas falsch ist, und dann meldet es niemand: Ein Abruf, der
    seit drei Wochen nichts holt, sieht aus wie ein Postfach ohne neue Post.
    """
    from core.services.postfach_abruf import AbrufFehler, verbinden, _schliessen

    postfach = get_object_or_404(Postfach.objects.filter(zweck=zweck))
    try:
        verbindung = verbinden(postfach)
    except AbrufFehler as fehler:
        postfach.fehler_vermerken(str(fehler))
        messages.error(request, str(fehler))
    else:
        _schliessen(verbindung)
        postfach.letzter_test = timezone.now()
        postfach.letzter_fehler = ''
        postfach.letzter_fehler_am = None
        postfach.save(update_fields=['letzter_test', 'letzter_fehler', 'letzter_fehler_am'])
        messages.success(request, gettext('Verbindung zu %(server)s steht — Anmeldung als %(benutzer)s hat geklappt.') % {'server': postfach.server, 'benutzer': postfach.benutzer})
    log_aktion(request, 'Postfach-Verbindung geprüft', auf_deutsch(postfach.get_zweck_display),
               postfach.letzter_fehler or 'erfolgreich')
    return redirect('postfach_liste')


@rolle_erforderlich(*VERWALTUNGS_ROLLEN)
@require_POST
def postfach_loeschen(request, zweck):
    """Postfach entfernen — der einzige Weg, ein Geheimnis loszuwerden.

    Bewusst getrennt vom Formular: Löschen ist nicht dasselbe wie ein leeres
    Feld absenden, und genau diese Verwechslung soll die Oberfläche gar nicht
    erst anbieten.
    """
    postfach = get_object_or_404(Postfach.objects.filter(zweck=zweck))
    bezeichnung, adresse = postfach.get_zweck_display(), postfach.benutzer
    bezeichnung_de = auf_deutsch(postfach.get_zweck_display)
    postfach.delete()
    log_aktion(request, 'Postfach gelöscht', bezeichnung_de, adresse)
    messages.success(request, gettext('Postfach «%(bezeichnung)s» gelöscht. Der Abruf für diesen Zweck ist damit abgeschaltet.') % {'bezeichnung': bezeichnung})
    return redirect('postfach_liste')
