"""Automatisierter Schadensfall-Workflow: Vorlagen-Texte + Platzhalter-Ersetzung
für die Kommunikation rund um ein Ticket (Handwerker beauftragen, Melder informieren)."""

# Standard-Vorlagen (greifen, wenn keine passende Vorlage in der DB existiert).
DEFAULT_VORLAGEN = {
    'ticket_handwerker': {
        'betreff': 'Reparaturauftrag: {objekt} (Ticket #{ticket_id})',
        'inhalt': (
            "Sehr geehrte Damen und Herren\n\n"
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
            "Guten Tag {melder_name}\n\n"
            "Vielen Dank für Ihre Meldung „{schaden}“.\n\n"
            "Wir haben den Auftrag an die Firma {handwerker} weitergegeben. "
            "Diese wird sich in Kürze für einen Termin bei Ihnen melden.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_erledigt': {
        'betreff': 'Schaden behoben (Ticket #{ticket_id})',
        'inhalt': (
            "Guten Tag {melder_name}\n\n"
            "Der von Ihnen gemeldete Schaden „{schaden}“ wurde behoben und das Ticket "
            "abgeschlossen.\n\nSollte das Problem weiterhin bestehen, melden Sie sich bitte bei uns.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
    'ticket_melder_status': {
        'betreff': 'Statusupdate zu Ihrer Meldung (Ticket #{ticket_id})',
        'inhalt': (
            "Guten Tag {melder_name}\n\n"
            "Der Status Ihrer Schadenmeldung „{schaden}“ wurde aktualisiert: {status}.\n\n"
            "Freundliche Grüsse\nIhre Liegenschaftsverwaltung"
        ),
    },
}

TICKET_PLATZHALTER = [
    ('{melder_name}', 'Name des Melders'),
    ('{melder_tel}', 'Telefon des Melders'),
    ('{objekt}', 'Objekt / Einheit'),
    ('{liegenschaft}', 'Liegenschaft (Strasse, Ort)'),
    ('{schaden}', 'Titel des Schadens'),
    ('{ticket_id}', 'Ticket-Nummer'),
    ('{handwerker}', 'Beauftragte Handwerkerfirma'),
    ('{status}', 'Aktueller Status'),
]


def ticket_kontext(ticket, handwerker=None, status=None):
    """Baut das Platzhalter-Dict für ein Ticket.

    Enthält sowohl die Schaden-spezifischen Platzhalter ({melder_name}, {schaden} …)
    ALS AUCH die allgemeinen Vorlagen-Platzhalter ({mieter_name}, {vermieter},
    {datum}, {objekt}, {liegenschaft}) — damit Vorlagen mit beliebigen der in der
    Editor-Hilfe gelisteten Platzhalter funktionieren."""
    import datetime
    lg = ticket.liegenschaft
    melder = (ticket.gemeldet_von.display_name if ticket.gemeldet_von_id
              else f"{ticket.melder_vorname or ''} {ticket.melder_nachname or ''}".strip() or 'Mieter')
    objekt = ticket.betroffene_einheit.bezeichnung if ticket.betroffene_einheit_id else (lg.strasse if lg else '')

    # Vermieter = Mandant (Eigentümer) der Liegenschaft, sonst Verwaltung
    vermieter = ''
    if lg and lg.mandant_id:
        vermieter = lg.mandant.firma_oder_name
    else:
        try:
            from crm.models import Verwaltung
            vw = Verwaltung.objects.first()
            vermieter = (vw.firma if vw else '') or 'Ihre Liegenschaftsverwaltung'
        except Exception:
            vermieter = 'Ihre Liegenschaftsverwaltung'

    mieter_adresse = ''
    if ticket.gemeldet_von_id:
        mg = ticket.gemeldet_von
        mieter_adresse = f"{mg.strasse or ''}, {mg.plz or ''} {mg.ort or ''}".strip(' ,')

    return {
        # Schaden-spezifisch
        'melder_name': melder,
        'melder_tel': ticket.tel_melder or ticket.mieter_telefon or '',
        'schaden': ticket.titel,
        'ticket_id': str(ticket.id),
        'handwerker': (handwerker.firma if handwerker else ''),
        'status': status or ticket.get_status_display(),
        # Allgemeine Vorlagen-Platzhalter (Alias/Kompatibilität)
        'mieter_name': melder,
        'mieter_adresse': mieter_adresse,
        'objekt': objekt,
        'liegenschaft': f"{lg.strasse}, {lg.ort}" if lg else '',
        'vermieter': vermieter,
        'datum': datetime.date.today().strftime('%d.%m.%Y'),
    }


def _ersetze(text, kontext):
    for key, val in kontext.items():
        text = text.replace('{' + key + '}', str(val))
    return text


def vorlage_text(kategorie, ticket, handwerker=None, status=None):
    """Gibt (betreff, inhalt) für eine Ticket-Kategorie zurück — aus der DB-Vorlage
    (erste passende) oder aus DEFAULT_VORLAGEN, mit ersetzten Platzhaltern."""
    from crm.models import Vorlage
    db_kat = kategorie if kategorie != 'ticket_melder_status' else 'ticket_melder'
    v = Vorlage.objects.filter(kategorie=db_kat).order_by('name').first()
    if v and (v.inhalt or v.betreff):
        betreff = v.betreff or DEFAULT_VORLAGEN.get(kategorie, {}).get('betreff', '')
        inhalt = v.inhalt or DEFAULT_VORLAGEN.get(kategorie, {}).get('inhalt', '')
    else:
        d = DEFAULT_VORLAGEN.get(kategorie, {})
        betreff, inhalt = d.get('betreff', ''), d.get('inhalt', '')
    kontext = ticket_kontext(ticket, handwerker=handwerker, status=status)
    return _ersetze(betreff, kontext), _ersetze(inhalt, kontext)
