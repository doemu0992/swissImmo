"""Postfächer einrichten — Liste, Formular, Verbindungstest.

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
    """Beide Zwecke nebeneinander — auch der noch nicht eingerichtete.

    Bewusst beide Zeilen immer, statt nur der vorhandenen: Ein Zweck, den es
    nicht gibt, ist der häufigere Zustand und der, den man sucht. Eine leere
    Liste beantwortete die Frage «wo richte ich den Rechnungseingang ein?»
    nicht.
    """
    basis = _global_filter(request)
    vorhanden = {p.zweck: p for p in Postfach.objects.all()}
    zeilen = [{'zweck': wert, 'bezeichnung': text, 'postfach': vorhanden.get(wert)}
              for wert, text in Postfach.ZWECKE]
    return render(request, 'core/postfach_liste.html', {
        **basis, 'nav': 'einstellungen', 'zeilen': zeilen,
        'darf_aendern': _darf_aendern(request),
        'darf_erneuern': hat_rolle(getattr(request, 'user', None), INHABER_ROLLEN),
        'antwort': _antwortadresse_karte(request, vorhanden.get(Postfach.ZWECK_ANTWORTEN)),
        # Ohne Schlüssel lässt sich kein Passwort ablegen. Das gehört auf die
        # Seite und nicht in ein Serverprotokoll — sonst speichert jemand
        # dreimal und versteht die Fehlermeldung nicht.
        'schluessel_fehlt': not schluessel_vorhanden(),
        'schluessel_name': UMGEBUNGSNAME,
    })


def _antwortadresse_karte(request, antwort_postfach):
    """Die Karte «Ihre Antwortadresse»: nur die Adresse der EIGENEN Verwaltung (aus dem Kontext) und
    welche Adresse gerade gilt (eigenes Postfach oder Plattformadresse)."""
    from crm.models import Organisation
    from core.services.antwort_eingang import alte_kennung_gilt, antwort_adresse, eingang_aktiv
    org = Organisation.objects.filter(pk=request.organisation.pk).first()
    if org is None:
        return None
    eigenes = bool(antwort_postfach and antwort_postfach.aktiv and '@' in (antwort_postfach.benutzer or ''))
    return {
        'adresse': antwort_adresse(org),
        'eigenes_postfach': antwort_postfach.benutzer if eigenes else '',
        'plattform_gilt': not eigenes and eingang_aktiv(),
        'eingang_fehlt': not eigenes and not eingang_aktiv(),
        'alt_bis': org.antwort_kennung_alt_bis if alte_kennung_gilt(org) else None,
    }


@rolle_erforderlich(*INHABER_ROLLEN)
@require_POST
def antwortadresse_erneuern(request):
    """Neue Kennung für die Antwortadresse der Verwaltung. Die bisherige bleibt 30 Tage gültig.

    Nur der Inhaber: Mails, die schon unterwegs sind, tragen die alte Adresse. Protokolliert."""
    from crm.models import Organisation
    from core.services.antwort_eingang import kennung_erneuern
    org = get_object_or_404(Organisation.objects.filter(pk=request.organisation.pk))
    kennung_erneuern(org)
    log_aktion(request, 'Antwortadresse erneuert', org.firma, 'Die bisherige Adresse gilt noch 30 Tage.')
    messages.success(request, gettext('Die Antwortadresse wurde erneuert. Die bisherige Adresse gilt noch 30 Tage.'))
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
