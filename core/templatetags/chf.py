# core/templatetags/chf.py
"""
Schweizer Betragsformatierung: 2'480.00 (Apostroph-Tausender, Punkt-Dezimal).
Django's de-Locale rendert floatformat mit Komma — das ist in der Schweiz falsch.

Verwendung: {% load chf %} … CHF {{ betrag|chf }} bzw. {{ betrag|chf:0 }}
"""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def chf(value, dezimalstellen=2):
    try:
        zahl = float(value)
    except (TypeError, ValueError):
        return value
    formatiert = f"{zahl:,.{int(dezimalstellen)}f}"
    # Python: 2,480.00 → Schweiz: 2'480.00
    # mark_safe: rein numerisch generiert (kein User-Input), sonst würde
    # Djangos Autoescape den Apostroph zu &#x27; entstellen.
    return mark_safe(formatiert.replace(",", "'"))
