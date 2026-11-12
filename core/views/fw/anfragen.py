# core/views/fw/anfragen.py
"""«Anfragen»: Änderungswünsche aus dem Mieter- und Eigentümerportal, die die Verwaltung bestätigt oder ablehnt.

Das Portal schreibt nie selbst in die Stammdaten (`core/services/anfragen.py`). Hier entscheidet die Verwaltung: Bestätigen
führt die Änderung aus, Ablehnen nimmt sie nicht an und nennt, wenn gewünscht, den Grund. Arten, die Geld umleiten
(Bankverbindung der Eigentümerschaft), bestätigen nur Inhaber und Verwalter.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from core.auth import SCHREIB_ROLLEN, VERWALTUNGS_ROLLEN, hat_rolle, rolle_erforderlich
from core.models import Aenderungsanfrage
from core.services import anfragen as dienst

from ._basis import _global_filter

SEITE = '/neu/anfragen/'


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_anfragen(request):
    """Offene Anfragen zuerst; `?alle=1` zeigt auch die entschiedenen (die letzten 100)."""
    alle = request.GET.get('alle') == '1'
    qs = Aenderungsanfrage.objects.select_related('mieter', 'eigentuemer', 'entschieden_von')
    offene = list(qs.filter(status=Aenderungsanfrage.STATUS_OFFEN).order_by('erstellt_am'))
    entschieden = list(qs.exclude(status=Aenderungsanfrage.STATUS_OFFEN)[:100]) if alle else []
    darf_sensibel = hat_rolle(request.user, VERWALTUNGS_ROLLEN)
    for a in offene:
        a.darf_entscheiden = darf_sensibel or a.art not in Aenderungsanfrage.SENSIBEL
    return render(request, 'fw/anfragen.html', {
        **_global_filter(request), 'nav': 'heute', 'offene': offene, 'entschieden': entschieden, 'alle': alle})


def _entscheidbar(request, anfrage):
    if anfrage.art in Aenderungsanfrage.SENSIBEL and not hat_rolle(request.user, VERWALTUNGS_ROLLEN):
        raise PermissionDenied('Diese Art von Anfrage bestätigen nur Inhaber und Verwalter.')


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_anfrage_bestaetigen(request, pk):
    anfrage = get_object_or_404(Aenderungsanfrage.objects.all(), pk=pk)
    if request.method == 'POST':
        _entscheidbar(request, anfrage)
        try:
            dienst.bestaetigen(anfrage, request.user, request.POST.get('antwort', ''))
            messages.success(request, gettext('Die Anfrage ist bestätigt und die Änderung ausgeführt.'))
        except dienst.AnfrageFehler as fehler:
            messages.error(request, str(fehler))
    return redirect(SEITE)


@rolle_erforderlich(*SCHREIB_ROLLEN)
def fw_anfrage_ablehnen(request, pk):
    anfrage = get_object_or_404(Aenderungsanfrage.objects.all(), pk=pk)
    if request.method == 'POST':
        _entscheidbar(request, anfrage)
        try:
            dienst.ablehnen(anfrage, request.user, request.POST.get('antwort', ''))
            messages.success(request, gettext('Die Anfrage ist abgelehnt.'))
        except dienst.AnfrageFehler as fehler:
            messages.error(request, str(fehler))
    return redirect(SEITE)
