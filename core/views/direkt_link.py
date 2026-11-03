# core/views/direkt_link.py
"""Chat und Terminabstimmung per signiertem Link aus der Mail — ohne Anmeldung.

ÖFFENTLICHER EINSTIEGSPUNKT (bewusst ohne ``rolle_erforderlich``), wie die Auftragsseite des Handwerkers.
Der Link steht in den Mails des Direktkanals (``tickets/direktkanal.py``); er ist signiert
(``django.core.signing``), nennt Auftrag UND Seite (Mieter oder Handwerker) und läuft nach 30 Tagen ab.
Ein Aufruf (GET) verändert nichts — Vorschau-Dienste von Mailprogrammen lösen keine Bestätigung aus; jede
Aktion ist ein POST mit CSRF-Prüfung. Rate-Limit und Sperre nach Fehlversuchen wie bei der Auftragsseite.
Jeder Fehler (Signatur, Ablauf, widerrufener Handwerker-Link, unbekannter Auftrag) ist derselbe 404.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.cache import never_cache

from .handwerker_portal import ANFRAGEN, ANFRAGEN_FENSTER, FEHLVERSUCHE, FEHLVERSUCHE_FENSTER, _koepfe, \
    _nicht_gefunden, _protokoll


@never_cache
def direkt_link(request, signiert):
    from core.tenancy import kontext_des_objekts
    from core.utils.throttle import client_ip, fehlversuch, ist_gesperrt, rate_limit
    from tickets import direkt_aktionen, direktkanal

    ip = client_ip(request)
    fehl_key = f'dk-link-fehl:{ip}'
    if ist_gesperrt(fehl_key, FEHLVERSUCHE):
        return _nicht_gefunden(request)
    if not rate_limit(f'dk-link:{ip}', ANFRAGEN, ANFRAGEN_FENSTER):
        return _koepfe(HttpResponse(gettext('Zu viele Anfragen. Bitte versuchen Sie es später erneut.'),
                                    status=429, content_type='text/plain; charset=utf-8'))
    gefunden = direktkanal.auftrag_aus_link(signiert)
    if gefunden is None:
        fehlversuch(fehl_key, FEHLVERSUCHE_FENSTER)
        return _nicht_gefunden(request)
    auftrag, seite = gefunden
    with kontext_des_objekts(auftrag):
        if request.method == 'POST':
            try:
                meldung = direkt_aktionen.ausfuehren(auftrag, seite, request.POST)
                if meldung is None:
                    raise ValidationError(gettext('Unbekannte Aktion.'))
                messages.success(request, meldung)
                _protokoll(request, auftrag, 'Direktkanal-Link: Aktion', f"{seite}: {request.POST.get('aktion', '')}")
            except ValidationError as e:
                messages.error(request, ' '.join(e.messages))
            return _koepfe(redirect(request.path))
        ticket = auftrag.ticket
        gegenseite = (direktkanal.mieter_name(ticket) if seite == 'handwerker' else auftrag.handwerker.firma)
        antwort = render(request, 'core/direkt_link.html', {
            'auftrag': auftrag, 't': ticket, 'lg': ticket.liegenschaft, 'seite': seite,
            'chat': list(direktkanal.verlauf(auftrag)), 'direkt_offen': direktkanal.ist_offen(auftrag),
            'gegenseite': gegenseite, 'vorschlag_kennung': direkt_aktionen.kennung(auftrag),
            'termin_min': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        })
        return _koepfe(antwort)
