# core/views/fw/api_zugang.py
"""Einstellungen «API-Zugang»: Schlüssel für die lesende Finanz-API (`/api/v1/`) selbst anlegen und widerrufen.

Nur der Inhaber; die Views hängen über `funktion_erforderlich` (innerhalb der Rollenprüfung) am Merkmal `api_zugang` (Stufe Enterprise), und die API selbst prüft
dasselbe Merkmal bei jeder Abfrage. Der Klartext des Schlüssels erscheint genau einmal, in der Antwort auf das Anlegen: Er
wird weder gespeichert noch in einer Sitzung oder im Logbuch festgehalten (dort steht nur der Anfang). Anlegen und Widerruf
stehen im Logbuch.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from abo.zugang import funktion_erforderlich
from core import api_token
from core.auth import INHABER_ROLLEN, client_ip, rolle_erforderlich
from core.models import ApiToken
from core.tenancy import OrganisationsFehler, organisation_der_anfrage

from ._basis import _global_filter

SEITE = '/neu/einstellungen/api/'
#: So viele aktive Schlüssel je Verwaltung; wer mehr braucht, widerruft alte.
MAX_AKTIV = 10


def _organisation(request):
    try:
        return organisation_der_anfrage(request)
    except OrganisationsFehler:
        raise PermissionDenied('Keine aktive Organisation.')


def _protokollieren(request, aktion, token):
    """Logbuch-Eintrag; wirft, wenn er nicht geschrieben werden kann: ein Schlüssel ohne Spur soll es nicht geben."""
    from core.models import AktivitaetsLog
    AktivitaetsLog.objects.create(
        organisation=_organisation(request), benutzer=request.user, aktion=aktion, objekt=token.name[:200],
        details=f'{token.anfang}…', kategorie='sicherheit', ip_adresse=client_ip(request))


def _seite(request, **extra):
    return render(request, 'fw/api_zugang.html', {
        **_global_filter(request), 'nav': 'einstellungen', 'max_aktiv': MAX_AKTIV,
        'schluessel': list(ApiToken.objects.all()), **extra})


@rolle_erforderlich(*INHABER_ROLLEN)
@funktion_erforderlich('api_zugang')
def fw_api_zugang(request):
    """GET: Liste. POST: neuen Schlüssel anlegen und ihn einmalig anzeigen."""
    if request.method != 'POST':
        return _seite(request)
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, gettext('Bitte eine Bezeichnung angeben, z. B. den Namen der Treuhandfirma.'))
        return redirect(SEITE)
    if ApiToken.objects.filter(widerrufen_am__isnull=True).count() >= MAX_AKTIV:
        messages.error(request, gettext('Es sind bereits %(n)s Schlüssel aktiv. Bitte zuerst einen widerrufen.') % {'n': MAX_AKTIV})
        return redirect(SEITE)
    token, klartext = api_token.erzeugen(_organisation(request), name)
    _protokollieren(request, 'API-Schlüssel angelegt', token)
    return _seite(request, neuer_schluessel=klartext, neuer_name=token.name)


@rolle_erforderlich(*INHABER_ROLLEN)
@funktion_erforderlich('api_zugang')
def fw_api_zugang_widerrufen(request, pk):
    if request.method != 'POST':
        return redirect(SEITE)
    token = get_object_or_404(ApiToken.objects.all(), pk=pk)
    if token.aktiv:
        api_token.widerrufen(token)
        _protokollieren(request, 'API-Schlüssel widerrufen', token)
        messages.success(request, gettext('Der Schlüssel «%(n)s» ist widerrufen.') % {'n': token.name})
    return redirect(SEITE)
