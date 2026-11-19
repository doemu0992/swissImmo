"""Kürzel einer Person für den Avatar: «DG» für Dominic Gerber (UI-Zielbild, Phase 0, Befund 13).

Vorher stand dort der Anfang des Namens, «Do» für Dominic Gerber oder «E2» für das Konto `e2e`. Anfangsbuchstaben von Vor- und
Nachname sind das, was man auf einem Avatar erwartet. Fehlt der Name, bleiben die ersten zwei Zeichen des Benutzernamens.
"""
from django import template

register = template.Library()


def _teile(person):
    if isinstance(person, str):
        return person.split()
    voll = ''
    try:
        voll = (person.get_full_name() or '').strip()
    except Exception:                                        # noqa: BLE001 — kein Benutzerobjekt (z. B. Text)
        voll = ''
    return voll.split()


@register.filter(name='kuerzel')
def kuerzel(person):
    """Anfangsbuchstaben von Vor- und Nachname, sonst die ersten zwei Zeichen des Benutzernamens, immer gross."""
    if person is None:
        return ''
    if isinstance(person, str) and not person.strip():
        return ''
    teile = _teile(person)
    if len(teile) >= 2:
        return (teile[0][0] + teile[-1][0]).upper()
    if len(teile) == 1:
        return teile[0][:2].upper()
    return (getattr(person, 'username', '') or str(person))[:2].upper()
