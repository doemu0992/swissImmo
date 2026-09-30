# core/templatetags/chf.py
"""
Schweizer Betragsformatierung: 2'480.00 (Apostroph-Tausender, Punkt-Dezimal).
Django's de-Locale rendert floatformat mit Komma — das ist in der Schweiz falsch.

Verwendung: {% load chf %} … CHF {{ betrag|chf }} bzw. {{ betrag|chf:0 }}

Die Formatierung selbst steht in core/services/pdf_text.py (`format_chf`) —
eine Quelle für Vorlagen, PDF-Generatoren und Briefe. Ein fehlender Betrag
(None/leer) ergibt eine leere Zeichenkette, nicht «None».
"""
from django import template
from django.utils.safestring import mark_safe

from core.services.pdf_text import format_chf

register = template.Library()


@register.filter
def chf(value, dezimalstellen=2):
    if value is None or value == '':
        return ''
    formatiert = format_chf(value, dezimalstellen, leer=None)
    if formatiert is None:
        return value            # nicht numerisch: unverändert (wie bisher)
    # mark_safe: rein numerisch generiert (kein User-Input), sonst würde
    # Djangos Autoescape den Apostroph zu &#x27; entstellen.
    return mark_safe(formatiert)
