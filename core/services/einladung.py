"""Einladungslink statt Initialpasswort.

Bis 07.11.2026 vergab der Inhaber beim Anlegen eines Kontos ein Passwort und gab es der Person weiter, mündlich, per
Chat oder Mail. Ein Passwort, das der Inhaber kennt (und das unterwegs mitliest), ist kein Geheimnis der Person
mehr. (Analysebericht 06.11.2026.)

Jetzt bekommt ein neues Konto ein unbrauchbares Passwort und die Person eine Mail mit einem Link, über den sie ihr
Passwort selbst setzt. Der Link ist der von «Passwort vergessen»: Djangos Token-Mechanismus (`default_token_generator`),
einmal verwendbar (das gesetzte Passwort entwertet ihn) und befristet (`PASSWORD_RESET_TIMEOUT`, Standard drei Tage).
Läuft er ab oder geht die Mail verloren, sendet der Inhaber ihn erneut.

`einladung_senden` gibt den Link auch zurück: Schlägt der Versand fehl, kann der Inhaber ihn der Person selbst geben.
"""
import logging

from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.html import escape
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext

logger = logging.getLogger(__name__)


def einladungs_link(request, benutzer):
    """Absolute Adresse zum Setzen des Passworts (derselbe Weg wie «Passwort vergessen»)."""
    uid = urlsafe_base64_encode(force_bytes(benutzer.pk))
    token = default_token_generator.make_token(benutzer)
    return request.build_absolute_uri(reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token}))


def einladung_senden(request, benutzer, organisation=None, neu=True):
    """Sendet den Link per Mail. Gibt `(gesendet, link)` zurück; ohne E-Mail-Adresse wird nichts gesendet."""
    from core.utils.email_service import send_via_hoststar
    link = einladungs_link(request, benutzer)
    if not benutzer.email:
        return False, link
    firma = getattr(organisation, 'firma', '') or 'immoswiss'
    betreff = (gettext('Einladung zu immoswiss') if neu else gettext('Passwort für immoswiss setzen'))
    zeilen = [
        gettext('Guten Tag'),
        '',
        (gettext('%(firma)s hat für Sie ein Konto bei immoswiss angelegt.') % {'firma': firma} if neu
         else gettext('%(firma)s hat Ihnen einen Link zum Setzen Ihres Passworts gesendet.') % {'firma': firma}),
        '',
        gettext('Passwort festlegen:'),
        link,
        '',
        gettext('Ihr Benutzername: %(name)s') % {'name': benutzer.get_username()},
        '',
        gettext('Der Link gilt nur kurz und nur einmal. Ist er abgelaufen, bitten Sie die Verwaltung um einen neuen.'),
        '',
        gettext('Freundliche Grüsse'),
        firma,
    ]
    html = '<br>'.join(escape(z) if z != link else f'<a href="{escape(link)}">{escape(link)}</a>' for z in zeilen)
    gesendet = send_via_hoststar(benutzer.email, betreff, f"<div style='font-family:Arial,sans-serif'>{html}</div>",
                                 organisation=organisation)
    return bool(gesendet), link
