"""Bausteine für die PDF-Dokumente (Grundlayout, Welle 1).

`{% briefkopf_von organisation as briefkopf %}` liefert die Briefkopf-Werte
einer Organisation (Logo, Farbe, Fusszeile, Absender) — dieselben wie
`core.services.briefkopf.briefkopf_kontext`. `dok_base.html` ruft es selbst auf,
wenn der aufrufende Code keinen `briefkopf` in den Kontext gelegt hat (die
DocuSeal-Wege bauen ihren Kontext von Hand und kennen ihn nicht).
"""
from django import template

from core.services.briefkopf import briefkopf_kontext

register = template.Library()


@register.simple_tag
def briefkopf_von(organisation):
    """Briefkopf der Organisation DES DATENSATZES; leeres Dict ohne Organisation.

    Fehlt `verwaltung` im Kontext, übergibt Django dem Tag einen leeren String statt None
    (so rief ein Vertrag mit Minimalkontext, wie ihn ein Test baut, den Briefkopf mit '' auf)."""
    if not hasattr(organisation, 'firma'):
        return {}
    return briefkopf_kontext(organisation)
