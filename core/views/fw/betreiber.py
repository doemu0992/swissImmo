# core/views/fw/betreiber.py
"""Betreiber-Konsole, Etappe 1: lesende Kundenliste über alle Verwaltungen.

NUR FÜR DEN BETREIBER (Superuser, mit Zwei-Faktor wie alle). Gezeigt werden Zähler, Abostufe und Befunde (was bei einer
Verwaltung fehlt) — keine Verträge, Personen oder Buchungen, und es gibt kein «Als Kunde einloggen». Ändern kann diese
Seite noch nichts; Anlegen und Abo-Verwaltung folgen in eigenen Etappen.
"""
from django.shortcuts import render

from core.auth import BETREIBER_ROLLEN, rolle_erforderlich
from core.services import betreiber

from ._basis import _global_filter


@rolle_erforderlich(*BETREIBER_ROLLEN)
def fw_betreiber(request):
    zeilen = betreiber.kunden()
    return render(request, 'fw/betreiber.html', {
        **_global_filter(request),
        # Der Bestandsfilter der Kopfzeile listet die Liegenschaften EINER Verwaltung: Auf dieser Seite wären das
        # Kundenadressen. Der Betreiber sieht hier keine, also bleibt das Auswahlmenü leer.
        'alle_liegenschaften': [], 'aktive_lg': None, 'lg_query': '',
        'nav': 'einstellungen', 'kunden': zeilen,
        'mit_befund': sum(1 for k in zeilen if k.befunde),
    })
