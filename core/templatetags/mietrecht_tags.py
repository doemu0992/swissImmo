"""Template-Tags für konsistente Gesetzeszitate ({% load mietrecht_tags %}).

Funktioniert auch in PDF-Templates (kein Request/Context-Processor nötig).
Backing-Store ist core.services.mietrecht.ARTIKEL (Single Source of Truth).
"""
from django import template
from core.services import mietrecht

register = template.Library()


@register.simple_tag
def art(key):
    """{% art 'kaution' %} → 'Art. 257e OR'."""
    return mietrecht.ref(key)


@register.filter
def artikel(key):
    """{{ 'kaution'|artikel }} → 'Art. 257e OR'."""
    return mietrecht.ref(key)


@register.simple_tag
def art_label(key):
    """{% art_label 'kaution' %} → 'Sicherheitsleistung (Mietzinsdepot)'."""
    return mietrecht.label(key)
