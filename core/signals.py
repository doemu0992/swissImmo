"""Sicherheits-Ereignisse (An-/Abmeldung, fehlgeschlagene Logins) ins Logbuch.

Angebunden über Djangos Auth-Signale. Jeder Eintrag bekommt Kategorie
'sicherheit' und die Client-IP, damit im Logbuch nachvollziehbar ist,
wer wann von wo im System war."""
from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed,
)
from django.dispatch import receiver

from core.auth import log_aktion, client_ip


def _ist_portal(user):
    """Reine Mieter-/Eigentümer-Portalkonten nicht mitschreiben — nur Team-Zugänge."""
    return bool(getattr(user, 'mieter_profil', None) or getattr(user, 'mandant_profil', None))


@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    if _ist_portal(user):
        return
    log_aktion(request, "Angemeldet", user.get_full_name() or user.username,
               '', kategorie='sicherheit', ip=client_ip(request) if request else None, user=user)


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    if user is None or _ist_portal(user):
        return
    log_aktion(request, "Abgemeldet", user.get_full_name() or user.username,
               '', kategorie='sicherheit', ip=client_ip(request) if request else None, user=user)


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    versucht = (credentials or {}).get('username', '') or '—'
    log_aktion(request, "Anmeldung fehlgeschlagen", versucht,
               'Falsches Passwort oder unbekannter Benutzer',
               kategorie='sicherheit', ip=client_ip(request) if request else None)
