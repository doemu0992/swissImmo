"""Automatisierter Schadensfall-Workflow: Vorlagen-Texte + Platzhalter-Ersetzung
für die Kommunikation rund um ein Ticket (Handwerker beauftragen, Melder informieren)."""

import re

from django.utils.translation import gettext, gettext_lazy

from core.services.dokumentsprache import STANDARD, auf_deutsch, in_sprache, sprache_von

# Standard-Vorlagen (greifen, wenn keine passende Vorlage in der DB existiert).
DEFAULT_VORLAGEN = {
    'ticket_handwerker': {
        'betreff': 'Reparaturauftrag: {objekt} (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\n"
            "Wir beauftragen Sie mit der Behebung des folgenden Schadens:\n\n"
            "Objekt: {objekt}\n"
            "Schaden: {schaden}\n\n"
            "Bitte kontaktieren Sie den Mieter {melder_name} ({melder_tel}) direkt "
            "zur Terminvereinbarung. Als Referenz nutzen Sie bitte Ticket #{ticket_id}.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_melder': {
        'betreff': 'Ihre Schadenmeldung wurde weitergegeben (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\n"
            "Vielen Dank für Ihre Meldung „{schaden}“.\n\n"
            "Wir haben den Auftrag an die Firma {handwerker} weitergegeben. "
            "Diese wird sich in Kürze für einen Termin bei Ihnen melden.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_erledigt': {
        'betreff': 'Schaden behoben (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\n"
            "Der von Ihnen gemeldete Schaden „{schaden}“ wurde behoben und das Ticket "
            "abgeschlossen.\n\nSollte das Problem weiterhin bestehen, melden Sie sich bitte bei uns.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_melder_status': {
        'betreff': 'Statusupdate zu Ihrer Meldung (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\n"
            "Der Status Ihrer Schadenmeldung „{schaden}“ wurde aktualisiert: {status}.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
}

DEFAULT_VORLAGEN.update({
    'ticket_auftrag_storniert': {
        'betreff': 'Auftrag storniert (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\nunser Auftrag „{schaden}“ ({objekt}) wird storniert. Bitte führen Sie "
            "keine Arbeiten aus und stellen Sie keine Rechnung dafür.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_termin': {
        'betreff': 'Termin für Ihre Reparatur: {termin} (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\n"
            "für „{schaden}“ wurde ein Termin vereinbart:\n\n"
            "Wann: {termin}\nWer: {handwerker}\nWo: {objekt}\n\n"
            "Bitte stellen Sie den Zutritt sicher. Können Sie nicht, antworten Sie auf diese "
            "Mail, dann verschieben wir den Termin. Der Kalendereintrag hängt an.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_termin_handwerker': {
        'betreff': 'Termin bestätigt: {termin} (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\nDer Termin für „{schaden}“ ({objekt}) ist festgelegt: {termin}.\n"
            "Mieter: {melder_name} ({melder_tel}).\nDer Kalendereintrag hängt an.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_termin_abgesagt': {
        'betreff': 'Termin abgesagt (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\nDer Termin für „{schaden}“ ({objekt}) am {termin} wurde abgesagt. "
            "Ein neuer Termin folgt.\n\nFreundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_erinnerung_handwerker': {
        'betreff': 'Erinnerung: Reparaturauftrag {objekt} (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\nzu unserem Auftrag „{schaden}“ ({objekt}) haben wir noch keine "
            "Rückmeldung oder Terminbestätigung. Bitte melden Sie sich beim Mieter {melder_name} "
            "({melder_tel}) und bestätigen Sie uns den Termin. Referenz: Ticket #{ticket_id}.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_erinnerung_rechnung': {
        'betreff': 'Erinnerung: Rechnung zu Ticket #{ticket_id}',
        'inhalt': (
            "{gruss}\n\nfür den ausgeführten Auftrag „{schaden}“ ({objekt}) liegt uns noch "
            "keine Rechnung vor. Bitte senden Sie sie mit der Referenz Ticket #{ticket_id}.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_erinnerung_mieter': {
        'betreff': 'Erinnerung zu Ihrer Meldung (Ticket #{ticket_id})',
        'inhalt': (
            "{gruss}\n\nzu Ihrer Meldung „{schaden}“ warten wir auf Ihre "
            "Rückmeldung. Bitte antworten Sie auf diese Mail.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
})

#: Vorlagen, die an den MIETER (Melder) gehen: Sie erscheinen in dessen Korrespondenzsprache
#: (D11, `Mieter.sprache`). Alle übrigen gehen an Handwerker und bleiben deutsch — der
#: Handwerker hat im Bestand keine Sprache. `ticket_termin_abgesagt` geht an beide: Die Sprache
#: bestimmt der Aufrufer.
MIETER_VORLAGEN = (
    'ticket_melder', 'ticket_erledigt', 'ticket_melder_status',
    'ticket_termin', 'ticket_termin_abgesagt', 'ticket_erinnerung_mieter',
)


def melder_sprache(ticket):
    """Korrespondenzsprache des Melders: `Mieter.sprache`, wenn das Ticket an einem Mieter hängt.

    Wer über den Aushang oder intern erfasst wurde, ist keiner Person im Bestand zugeordnet:
    Deutsch (die Bestätigung nach dem Absenden folgt der Sprache der Anfrage, siehe
    `send_ticket_receipt`)."""
    return sprache_von(ticket.gemeldet_von) if ticket.gemeldet_von_id else STANDARD


def _mieter_der_einheit(ticket):
    """Der Mieter der betroffenen Einheit (einziger aktiver Vertrag), sonst None.

    Für intern erfasste Tickets ohne Melder. Mehrere Mieter oder eine fremde Adresse im Ticket
    (E-Mail des Melders weicht von der des Mieters ab) ergeben keinen Treffer: lieber der
    neutrale Gruss als der falsche Name."""
    if not ticket.betroffene_einheit_id:
        return None
    from rentals.models import Mietvertrag
    mieter = {v.mieter_id: v.mieter for v in
              Mietvertrag.alle_organisationen.filter(einheit_id=ticket.betroffene_einheit_id, status='aktiv')
              .select_related('mieter')}
    if len(mieter) != 1:
        return None
    m = next(iter(mieter.values()))
    if ticket.email_melder and m.email and ticket.email_melder.strip().lower() != m.email.strip().lower():
        return None
    return m


def melder_gruss(ticket, sprache=None):
    """«Guten Tag Frau Muster» für den Melder des Tickets.

    Reihenfolge: der verknüpfte Mieter; sonst der Name aus der Meldung (mit der Anrede aus dem
    Formular, falls angegeben); sonst der Mieter der betroffenen Einheit; sonst «Guten Tag» —
    nie ein Platzhalterwort."""
    from core.services.anrede import mail_gruss, mieter_gruss
    if ticket.gemeldet_von_id:
        return mieter_gruss(ticket.gemeldet_von, sprache)
    if (ticket.melder_vorname or '').strip() or (ticket.melder_nachname or '').strip():
        return mail_gruss(ticket.melder_anrede, ticket.melder_vorname, ticket.melder_nachname, sprache=sprache)
    return mieter_gruss(_mieter_der_einheit(ticket), sprache)


_ALTE_ANREDE = re.compile(r'^Guten Tag \{melder_name\}(,?)[ \t]*$', re.MULTILINE)


def _alte_anrede_ersetzen(text):
    """Eine gespeicherte Vorlage mit «Guten Tag {melder_name}» in der Grusszeile grüsst nun mit
    `{gruss}`. Der Text in der Datenbank bleibt unverändert; nur die Ausgabe ändert sich — und
    «Guten Tag Mieter» (der frühere Ersatzwert ohne Namen) kommt nicht mehr vor."""
    return _ALTE_ANREDE.sub(r'{gruss}\1', text or '')


TICKET_PLATZHALTER = [
    ('{gruss}', gettext_lazy('Gruss an den Empfänger (Guten Tag Herr Muster)')),
    ('{melder_name}', gettext_lazy('Name des Melders')),
    ('{melder_tel}', gettext_lazy('Telefon des Melders')),
    ('{objekt}', gettext_lazy('Objekt / Einheit')),
    ('{liegenschaft}', gettext_lazy('Liegenschaft (Strasse, Ort)')),
    ('{schaden}', gettext_lazy('Titel des Schadens')),
    ('{ticket_id}', gettext_lazy('Ticket-Nummer')),
    ('{handwerker}', gettext_lazy('Beauftragte Handwerkerfirma')),
    ('{status}', gettext_lazy('Aktueller Status')),
]


def ticket_kontext(ticket, handwerker=None, status=None, termin=None, gruss=None):
    """Baut das Platzhalter-Dict für ein Ticket.

    Enthält sowohl die Schaden-spezifischen Platzhalter ({melder_name}, {schaden} …)
    ALS AUCH die allgemeinen Vorlagen-Platzhalter ({mieter_name}, {vermieter},
    {datum}, {objekt}, {liegenschaft}) — damit Vorlagen mit beliebigen der in der
    Editor-Hilfe gelisteten Platzhalter funktionieren."""
    from core.zeit import datum_heute
    lg = ticket.liegenschaft
    melder = (ticket.gemeldet_von.display_name if ticket.gemeldet_von_id
              else f"{ticket.melder_vorname or ''} {ticket.melder_nachname or ''}".strip() or 'Mieter')
    objekt = ticket.betroffene_einheit.bezeichnung if ticket.betroffene_einheit_id else (lg.strasse if lg else '')

    # Vermieter = Eigentümer der Liegenschaft, sonst Verwaltung
    vermieter = ''
    if lg and lg.eigentuemer_id:
        vermieter = lg.eigentuemer.firma_oder_name
    else:
        # Ohne Eigentuemer tritt die Verwaltung als Vermieterin auf — und zwar
        # die des Tickets, nicht die erste im Bestand.
        try:
            vw = ticket.organisation
            vermieter = (vw.firma if vw else '') or 'Ihre Liegenschaftsverwaltung'
        except Exception:
            vermieter = 'Ihre Liegenschaftsverwaltung'

    mieter_adresse = ''
    if ticket.gemeldet_von_id:
        mg = ticket.gemeldet_von
        mieter_adresse = f"{mg.strasse or ''}, {mg.plz or ''} {mg.ort or ''}".strip(' ,')

    return {
        # Gruss an den Empfänger der Mail (Mieter oder Handwerker, siehe `vorlage_text`)
        'gruss': gruss if gruss is not None else melder_gruss(ticket, sprache=melder_sprache(ticket)),
        # Schaden-spezifisch
        'melder_name': melder,
        'melder_tel': ticket.tel_melder or ticket.mieter_telefon or '',
        'schaden': ticket.titel,
        'ticket_id': str(ticket.id),
        'handwerker': (handwerker.firma if handwerker else ''),
        'status': status or auf_deutsch(ticket.get_status_display),
        'termin': termin or '',
        # Allgemeine Vorlagen-Platzhalter (Alias/Kompatibilität)
        'mieter_name': melder,
        'mieter_adresse': mieter_adresse,
        'objekt': objekt,
        'liegenschaft': f"{lg.strasse}, {lg.ort}" if lg else '',
        'vermieter': vermieter,
        'datum': datum_heute().strftime('%d.%m.%Y'),
    }


def _ersetze(text, kontext):
    # Der zentrale Dienst ersetzt (Modul 5); unbekannte Platzhalter bleiben
    # stehen wie bisher.
    from core.services.platzhalter import ersetze
    return ersetze(text, kontext)


def vorlage_text(kategorie, ticket, handwerker=None, status=None, termin=None, sprache=None,
                 empfaenger=None):
    """Gibt (betreff, inhalt) für eine Ticket-Kategorie zurück — aus der DB-Vorlage
    (erste passende) oder aus DEFAULT_VORLAGEN, mit ersetzten Platzhaltern.

    `sprache`: Sprache des Empfängers. Ohne Angabe Deutsch — nie die der angemeldeten Person:
    Wer mit französischer Oberfläche beauftragt, schreibt dem Handwerker trotzdem deutsch. Übersetzt
    werden nur die Standardtexte; eine eigene DB-Vorlage der Verwaltung gilt, wie sie geschrieben ist
    (nur die Grusszeile «Guten Tag {melder_name}» wird zu `{gruss}`).

    `empfaenger`: 'melder' oder 'handwerker' — wer den Gruss `{gruss}` bekommt. Ohne Angabe der Melder
    für die Mieter-Vorlagen (`MIETER_VORLAGEN`), sonst der Handwerker. `ticket_termin_abgesagt` geht
    an beide: dort sagt es der Aufrufer."""
    from crm.models import Vorlage
    with in_sprache(sprache or STANDARD):
        db_kat = kategorie if kategorie != 'ticket_melder_status' else 'ticket_melder'
        v = Vorlage.objects.filter(kategorie=db_kat).order_by('name').first()
        d = DEFAULT_VORLAGEN.get(kategorie, {})
        standard = {k: gettext(d[k]) if d.get(k) else '' for k in ('betreff', 'inhalt')}
        if v and (v.inhalt or v.betreff):
            betreff = v.betreff or standard['betreff']
            inhalt = _alte_anrede_ersetzen(v.inhalt) if v.inhalt else standard['inhalt']
        else:
            betreff, inhalt = standard['betreff'], standard['inhalt']
        # Der Status in der Sprache des Empfängers (nicht fest deutsch wie im Protokoll).
        status = status or str(ticket.get_status_display())
        if empfaenger is None:
            empfaenger = 'melder' if kategorie in MIETER_VORLAGEN else 'handwerker'
        from core.services.anrede import handwerker_gruss
        gruss = melder_gruss(ticket) if empfaenger == 'melder' else handwerker_gruss(handwerker)
        kontext = ticket_kontext(ticket, handwerker=handwerker, status=status, termin=termin, gruss=gruss)
        return _ersetze(betreff, kontext), _ersetze(inhalt, kontext)
