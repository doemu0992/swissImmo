# core/templatetags/rechte.py
"""
Knöpfe nur zeigen, wenn die Rolle sie auch bedienen darf.

Verwendung: {% load rechte %} … {% if request.user|darf:"/neu/benutzer/neu/" %}…{% endif %}

Liest die Rollen über `core.auth.darf_oeffnen` direkt am Dekorator der View ab —
eine zweite, von Hand gepflegte Rollenliste in den Vorlagen gibt es damit nicht.
Ersetzt die Prüfung in der View nicht; blendet nur aus, was dort ohnehin mit
403 endete.
"""
from django import template

from core.auth import darf_oeffnen

register = template.Library()


@register.filter
def darf(user, pfad):
    return darf_oeffnen(user, str(pfad))


@register.filter
def darf_schreiben(user):
    """Gehört der Benutzer zu den Schreib-Rollen (nicht «Lesezugriff»)?

    Für Knöpfe, die Daten ablegen oder protokollieren, obwohl ihre View auch dem
    Lesezugriff offensteht (die Vorschau). Die View prüft die Rolle selbst."""
    from core.auth import SCHREIB_ROLLEN, hat_rolle
    return hat_rolle(user, SCHREIB_ROLLEN)
