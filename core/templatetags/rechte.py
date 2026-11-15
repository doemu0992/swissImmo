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

from core.auth import darf_oeffnen, rollen_der_anfrage as _rollen_der_anfrage

register = template.Library()


@register.filter
def darf(user, pfad):
    if user is None or not getattr(user, 'is_authenticated', False):
        return darf_oeffnen(user, str(pfad))
    return darf_oeffnen(user, str(pfad), _rollen_der_anfrage(user))


@register.filter
def darf_schreiben(user):
    """Gehört der Benutzer zu den Schreib-Rollen (nicht «Lesezugriff»)?

    Für Knöpfe, die Daten ablegen oder protokollieren, obwohl ihre View auch dem
    Lesezugriff offensteht (die Vorschau). Die View prüft die Rolle selbst."""
    from core.auth import SCHREIB_ROLLEN, _mit_inhaber, hat_rolle
    if user is None or not getattr(user, 'is_authenticated', False):
        return hat_rolle(user, SCHREIB_ROLLEN)
    if user.is_superuser:
        return True
    return bool(_rollen_der_anfrage(user) & set(_mit_inhaber(SCHREIB_ROLLEN)))
