"""`{% mietzinsmodell_klausel vertrag as klausel %}` — Angaben für Index-/Staffelklausel im Vertragstext.

Ein Tag statt zusätzlichem Kontext: Der Mietvertrag wird an drei Stellen gerendert
(`pdf_service`, `docuseal_service`, `views/docuseal`), jede mit eigenem Kontext. Ein Tag
liest nur den Vertrag und fehlt deshalb an keiner der Stellen.
"""
from django import template

from core.services.mietzinsmodell import klausel_kontext

register = template.Library()


@register.simple_tag
def mietzinsmodell_klausel(vertrag):
    return klausel_kontext(vertrag)
