"""Kleine Helfer für die Vorlagen des Nebenkosten-Wizards (fw/nk/)."""
from django import template

register = template.Library()


@register.filter
def nk_eintrag(wert, schluessel):
    """`{{ fehler|nk_eintrag:e.id }}` — Eintrag eines Wörterbuchs nach Schlüssel, sonst None.
    Die Fehler und Eingaben einer Kachel liegen je Objekt-ID; die Vorlage kann sie so lesen."""
    if not wert:
        return None
    try:
        return wert.get(schluessel)
    except AttributeError:
        return None


@register.filter
def nk_feld(wert, name):
    """`{{ eingabe|nk_feld:'personen_12' }}` — wie `nk_eintrag`, der Schlüssel als Text."""
    return nk_eintrag(wert, str(name))
