"""Schlüssel für die lesende Finanz-API: erzeugen, prüfen, widerrufen, und die Anmeldung für django-ninja."""
import hashlib
import secrets

from django.utils import timezone
from ninja.security import HttpBearer

from core.models import ApiToken

#: Abfragen je Minute und Schlüssel.
LIMIT_JE_MINUTE = 120
#: `zuletzt_benutzt` höchstens so oft schreiben (Sekunden), damit nicht jede Abfrage eine Schreiblast ist.
AKTUALISIERUNG_SEKUNDEN = 300


def _hash(roh):
    return hashlib.sha256(roh.encode()).hexdigest()


def erzeugen(organisation, name):
    """Legt einen Schlüssel an und gibt `(ApiToken, Klartext)` zurück. Der Klartext ist danach nirgends mehr abrufbar."""
    roh = ApiToken.PRAEFIX + secrets.token_urlsafe(32)
    token = ApiToken.alle_organisationen.create(
        organisation=organisation, name=name.strip()[:100], schluessel_hash=_hash(roh), anfang=roh[:len(ApiToken.PRAEFIX) + 4])
    return token, roh


def widerrufen(token):
    if token.widerrufen_am is None:
        token.widerrufen_am = timezone.now()
        token.save(update_fields=['widerrufen_am'])


def finden(roh):
    """Der aktive Schlüssel zum Klartext, sonst `None`. Der Vergleich läuft über den Hash (Nachschlagen per Index)."""
    if not roh or not roh.startswith(ApiToken.PRAEFIX) or len(roh) > 200:
        return None
    return (ApiToken.alle_organisationen.select_related('organisation')
            .filter(schluessel_hash=_hash(roh), widerrufen_am__isnull=True).first())


class TokenAuth(HttpBearer):
    """`Authorization: Bearer imm_...`. Setzt `request.api_token`; ungültig oder gebremst = 401 bzw. 429 ohne Auskunft."""

    def authenticate(self, request, token):
        from core.utils.throttle import rate_limit
        gefunden = finden(token)
        if gefunden is None:
            return None
        from core.funktionen import hat_funktion
        if not hat_funktion(gefunden.organisation, 'api_zugang'):
            from ninja.errors import HttpError
            raise HttpError(403, 'Der API-Zugang gehört nicht zum Abonnement dieser Verwaltung.')
        if not rate_limit(f'api:token:{gefunden.pk}', LIMIT_JE_MINUTE, 60):
            from ninja.errors import HttpError
            raise HttpError(429, 'Zu viele Abfragen.')
        jetzt = timezone.now()
        if gefunden.zuletzt_benutzt is None or (jetzt - gefunden.zuletzt_benutzt).total_seconds() > AKTUALISIERUNG_SEKUNDEN:
            ApiToken.alle_organisationen.filter(pk=gefunden.pk).update(zuletzt_benutzt=jetzt)
        request.api_token = gefunden
        return gefunden
