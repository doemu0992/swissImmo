"""Mails, die eine neu eingegangene Schadenmeldung auslöst — für jeden Eingangsweg gleich.

Wege: QR-Aushang (`/report/<id>/`), Webformular (`/schaden/melden/`), Mieterportal, interne
Erfassung. Bis zum 3.11.2026 bekam die Verwaltung nur beim Mieterportal eine Mail; ein Mieter, der
über den Aushang oder das Webformular meldete, erschien nur als Badge im Cockpit (und das
Webformular schickte nicht einmal eine Eingangsbestätigung).
"""
import logging

logger = logging.getLogger(__name__)

#: Herkunft im Kopf der Verwaltungsmail.
HERKUNFT_AUSHANG = 'über den QR-Aushang'
HERKUNFT_WEB = 'über das Webformular'


def verwaltung_informieren(ticket, herkunft):
    """Mail an die Verwaltung des Tickets (``Organisation.email``). True, wenn versendet.

    Läuft im Mandantenkontext des Tickets (die öffentlichen Ansichten setzen ihn). Ein Fehler
    blockiert die Meldung nie; fehlt die Adresse, steht das im Protokoll statt in keinem Wort."""
    from core.utils.email_service import send_neue_meldung_intern
    adresse = (getattr(ticket.organisation, 'email', '') or '').strip()
    if not adresse:
        logger.warning("Ticket #%s: Die Verwaltung hat keine E-Mail-Adresse, die neue Meldung erscheint "
                       "nur im Cockpit", ticket.pk)
        return False
    try:
        return send_neue_meldung_intern(ticket, [adresse], herkunft=herkunft)
    except Exception:
        logger.exception("Benachrichtigung der Verwaltung zu Ticket #%s fehlgeschlagen", ticket.pk)
        return False


def eingangsbestaetigung_text(ticket, sprache):
    """(Betreff, Text) der Eingangsbestätigung an einen bekannten Melder, in dessen Sprache.

    Der Betreff trägt «Ticket #N»: Die Antwort des Melders wird darüber (``fetch_replies``) dem Ticket
    zugeordnet."""
    from django.utils.translation import gettext as _
    from core.services.dokumentsprache import in_sprache
    with in_sprache(sprache):
        betreff = _("Eingangsbestätigung: %(titel)s (Ticket #%(id)s)") % {'titel': ticket.titel, 'id': ticket.id}
        text = _("Guten Tag\n\nWir haben Ihre Schadenmeldung '%(titel)s' erhalten (Ticket #%(id)s) und "
                 "kümmern uns darum. Sobald ein Handwerker beauftragt wurde, informieren wir Sie.\n\n"
                 "Freundliche Grüsse\nIhre Liegenschaftsverwaltung") % {'titel': ticket.titel, 'id': ticket.id}
    return betreff, text
