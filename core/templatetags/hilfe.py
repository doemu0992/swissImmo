"""`{% load hilfe %}{% hilfe 'akonto' %}` — ein ⓘ mit Erklärung zum Antippen (core/hilfe.py)."""
import logging

from django import template
from django.utils.html import format_html
from django.utils.translation import gettext as _

from core.hilfe import eintrag

register = template.Library()
log = logging.getLogger(__name__)


@register.simple_tag
def hilfe(schluessel):
    e = eintrag(schluessel)
    if e is None:
        # Kein Absturz in der Oberfläche; der Test `test_bausteine` findet fehlende Schlüssel.
        log.warning('Hilfe-Schlüssel fehlt: %s', schluessel)
        return ''
    titel, text = e
    return format_html(
        '<button type="button" class="fw-hilfe-knopf" aria-expanded="false" aria-label="{}">i</button>'
        '<span class="fw-hilfe-text"><b>{}</b>{}</span>',
        _('Erklärung: %(titel)s') % {'titel': titel}, titel, text)
