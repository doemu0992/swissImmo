# core/views/fw/auftraege.py
"""«Aufträge»: was im Hintergrund wartet, läuft oder zuletzt fertig wurde oder scheiterte.

Nur lesend: Aufträge entstehen dort, wo die Arbeit ausgelöst wird (`core/services/auftraege.anlegen`), und werden von
`manage.py auftraege_abarbeiten` abgearbeitet. Die Seite zeigt Stand, Fortschritt, Ergebnis und Fehler — sonst sähe
niemand, ob eine lange Arbeit noch läuft oder woran sie scheiterte.
"""
from django.shortcuts import render

from core.auth import SCHREIB_ROLLEN, rolle_erforderlich
from core.models import Auftrag
from core.services import auftraege as dienst

from ._basis import _global_filter


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_auftraege(request):
    """Die letzten 50 Aufträge der Verwaltung, die offenen (wartend, laufend) zuerst."""
    zeilen = list(Auftrag.objects.select_related('erstellt_von')[:50])
    offene = [a for a in zeilen if a.zustand in (Auftrag.ZUSTAND_WARTET, Auftrag.ZUSTAND_LAEUFT)]
    erledigte = [a for a in zeilen if a not in offene]
    for a in zeilen:
        a.art_text = dienst.bezeichnung(a.art)
    return render(request, 'fw/auftraege.html', {
        **_global_filter(request), 'nav': 'heute', 'offene': offene, 'erledigte': erledigte,
        # Warten Aufträge und meldet sich kein Läufer, holt sie niemand ab: das soll man sehen.
        'ohne_laeufer': any(a.zustand == Auftrag.ZUSTAND_WARTET for a in offene) and not dienst.laeufer_aktiv()})
