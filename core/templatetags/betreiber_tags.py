"""Leiste des Betreiber-Portals: die Zahl der neuen Fehler im Protokoll (rote Pille)."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def betreiber_fehlerzahl(context):
    """Zahl der neuen Fehler für den angemeldeten Betreiber; 0 für alle anderen und wenn nichts ansteht."""
    anfrage = context.get('request')
    benutzer = getattr(anfrage, 'user', None)
    if benutzer is None or not benutzer.is_authenticated or not benutzer.is_superuser:
        return 0
    from core.services import betreiber_protokoll
    return betreiber_protokoll.fehlerzahl(benutzer)
