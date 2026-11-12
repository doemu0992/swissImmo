# core/views/fw/einstellungen_aktionen.py
#
# Einstellungen-Hub und Mandantenwechsel.
# Aus aktionen.py herausgeloest (reiner Umzug ohne Aenderung am Code).


from django.shortcuts import render
from django.utils.translation import gettext as _

from core.auth import (rolle_erforderlich, TEAM_ROLLEN)


from ._basis import (_global_filter)


# ══════════════════════════════════════════════════════════════
# UI-MODUS (Einfach/Profi) + EINSTELLUNGEN-HUB
# ══════════════════════════════════════════════════════════════
@rolle_erforderlich(*TEAM_ROLLEN)
def fw_einstellungen(request):
    """Zentrale Einstellungen-Seite — bündelt die früheren 8 Profil-Dropdown-
    Punkte (Account, Abonnement, Benutzer, Logbuch, Vorlagen, Integrationen,
    Rechtsgrundlagen) als eine Hub-Seite mit Sektionen."""
    basis = _global_filter(request)
    karten = [
        {'titel': _('Account'), 'sub': _('Verwaltungs-Stammdaten, Logo, Absender'), 'url': '/neu/account/', 'icon': 'person'},
        {'titel': _('Benutzer & Rollen'), 'sub': _('Team-Mitglieder und Berechtigungen'), 'url': '/neu/benutzer/', 'icon': 'person'},
        {'titel': _('Vorlagen'), 'sub': _('Textvorlagen mit Platzhaltern'), 'url': '/neu/vorlagen/', 'icon': 'dokument'},
        {'titel': _('Integrationen'), 'sub': _('E-Mail, DocuSeal, KI, Banken, Portal-Feed'), 'url': '/neu/integrationen/', 'icon': 'einstellungen'},
        {'titel': _('Abonnement'), 'sub': _('Plan und Rechnungsstellung'), 'url': '/neu/abonnement/', 'icon': 'einstellungen'},
        {'titel': _('Anmeldung & Sicherheit'), 'sub': _('Zwei-Faktor-Anmeldung für Sie und Ihr Team'),
         'url': '/konto/zwei-faktor/', 'icon': 'gesperrt'},
        {'titel': _('Zahlungsfreigabe'), 'sub': _('Freigabelimite für Lieferantenzahlungen (Vier-Augen-Prinzip)'),
         'url': '/neu/einstellungen/zahlungsfreigabe/', 'icon': 'gesperrt'},
        {'titel': _('Daten'), 'sub': _('Import für Wechselkunden, Mandatsexport, Buchungsjournal für Banana und Abacus'),
         'url': '/neu/einstellungen/daten/', 'icon': 'dokument'},
        {'titel': _('API-Zugang'), 'sub': _('Schlüssel für Treuhand und Buchhaltungssoftware (nur Lesen)'),
         'url': '/neu/einstellungen/api/', 'icon': 'einstellungen'},
        {'titel': _('E-Mail-Eingang'), 'sub': _('Adressen für Ticket-Antworten und Rechnungen, eigenes Postfach nur bei Bedarf'),
         'url': '/neu/postfaecher/', 'icon': 'wartet'},
        {'titel': _('Logbuch'), 'sub': _('Wer hat wann was geändert'), 'url': '/neu/logbuch/', 'icon': 'verlauf'},
        {'titel': _('Rechtsgrundlagen'), 'sub': _('OR/VMWG-Artikel mit Anwendung im Programm'), 'url': '/neu/rechtsgrundlagen/', 'icon': 'recht'},
        # E1.1: Das Regelwerk hing bis hierher unter «Erweitert» im
        # Einfachmodus. Mit den fuenf Bereichen hat es dort keinen Platz mehr —
        # Fristenregeln sind eine Einstellung, keine Tagesarbeit. Ohne diese
        # Kachel waere die Seite beim Umbau unauffindbar geworden, wie schon
        # einmal in Phase 4a (vier Etappen lang).
        {'titel': _('Regelwerk (Fristen)'), 'sub': _('Kündigungstermine und Fristen je Kanton'),
         'url': '/neu/regelwerk/', 'icon': 'recht'},
        # Audit F3: Die Tabelle war gebaut und speist Abnahme und Ersatzplanung,
        # hatte aber keinen einzigen Link. Sie ist eine Einstellung — Werte,
        # die man einmal festlegt und selten ändert.
        {'titel': _('Lebensdauertabelle'), 'sub': _('Nutzungsdauern für Zeitwert bei Abnahme und Ersatzplanung'),
         'url': '/neu/lebensdauer/', 'icon': 'verlauf'},
        # Der Wortlaut der Schlussbestimmungen gehört der Verwaltung, nicht dem Code.
        {'titel': _('Abnahmeprotokoll (Texte)'), 'sub': _('Wortlaut der Schlussbestimmungen: Haftung, Mietzinsdepot, Mängelrüge'),
         'url': '/neu/abnahme-texte/', 'icon': 'recht'},
        # Das Archiv (Etappe 2) hatte keinen Link: Wer eine Akte archivierte, sah es
        # nur einmal als Weiterleitung und fand es danach nicht wieder.
        {'titel': _('Archiv'), 'sub': _('Archivierte Akten ansehen und wiederherstellen'),
         'url': '/neu/archiv/', 'icon': 'dokument'},
        # Nur der Betreiber (Superuser): `darf_oeffnen` blendet die Kachel für alle anderen aus.
        {'titel': _('Betreiber-Portal'), 'sub': _('Kunden, Abonnements und Verschlüsselung der Installation (Betreiber)'),
         'url': '/betreiber/', 'icon': 'gesperrt'},
    ]
    # Kacheln, die die Rolle nicht öffnen darf (Logbuch, Archiv …), führten in die 403
    # (DESIGN-07). Die Rollen werden einmal gelesen, nicht je Kachel.
    from core.auth import darf_oeffnen, eigene_rollen
    meine = eigene_rollen(request.user)
    karten = [k for k in karten if darf_oeffnen(request.user, k['url'], meine)]
    return render(request, 'fw/einstellungen.html', {
        **basis, 'nav': 'einstellungen', 'karten': karten,
    })


@rolle_erforderlich(*TEAM_ROLLEN)
def fw_mandant_wechseln(request):
    """Wechselt die aktive Organisation — nur in eine eigene.

    WARUM ES DAS BRAUCHT (E1.2)

    `crm.Mitgliedschaft` erlaubt seit Etappe 4.1 mehrere Organisationen je
    Person; die Middleware liest dafür längst einen Sessionwert. Was fehlte,
    war die Auswahl: Wer für zwei Verwaltungen arbeitet, landete immer in der
    ältesten. Die Middleware protokolliert das seither bei jeder Anfrage —
    ein Hinweis, den niemand liest.

    DER HEIKLE TEIL

    Dieser View setzt den Mandantenkontext. Ein POST mit einer fremden
    Organisations-ID darf ihn NICHT setzen, sonst ist die gesamte
    Mandantentrennung mit einem Formularfeld auszuhebeln — sie hängt an
    genau diesem Wert.

    Geprüft wird deshalb nicht «gibt es diese Organisation?», sondern «hat
    DIESER Benutzer dort eine Mitgliedschaft?». `alle_organisationen` ist hier
    richtig und nicht etwa der Fehler: Die Abfrage bestimmt den Kontext erst,
    kann ihn also nicht voraussetzen — deshalb ist sie auf `benutzer` und
    `organisation_id` zugleich eingeschränkt.

    ZWEITE SCHICHT: `core.middleware_tenancy._organisation_fuer` ehrt den
    Sessionwert ohnehin nur, wenn er zu einer echten Mitgliedschaft passt.
    Wird eine Mitgliedschaft später entzogen, greift der alte Sessionwert
    also nicht mehr. Das ist Absicht — die obere Schicht umgeht irgendwann
    jemand.

    Bei einer unbekannten oder fremden ID passiert nichts: keine Änderung,
    keine Fehlermeldung, die verrät, ob es die Organisation gibt.
    """
    from django.shortcuts import redirect
    from crm.models import Mitgliedschaft
    from core.middleware_tenancy import SESSION_SCHLUESSEL

    if request.method == 'POST':
        try:
            gewuenscht = int(request.POST.get('organisation') or 0)
        except (TypeError, ValueError):
            gewuenscht = 0
        if gewuenscht and Mitgliedschaft.alle_organisationen.filter(
                benutzer=request.user, organisation_id=gewuenscht).exists():
            request.session[SESSION_SCHLUESSEL] = gewuenscht
            # Der globale Liegenschaftsfilter braucht hier nichts: Er steht im
            # URL-Parameter `?lg=`, nicht in der Session (`_basis._global_filter`).
            # Die Umleitung auf `/neu/` laesst ihn ohnehin fallen.

    return redirect('/neu/')
