"""Angemeldete HTML-Seiten werden nicht zwischengespeichert.

Ohne diese Kopfzeile zeigt der Browser nach dem Abmelden mit «Zurück» die zuletzt besuchte Seite aus seinem Zwischenspeicher:
Es sieht aus, als wäre man noch angemeldet. Die Sitzung ist zwar beendet, aber die Seite mit den Daten steht noch auf dem Schirm.
`no-store` verbietet das Ablegen; die Seite wird beim Zurückgehen neu angefragt und führt zur Anmeldung.
"""
from django.utils.cache import patch_cache_control


class AngemeldetNichtZwischenspeichern:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        antwort = self.get_response(request)
        benutzer = getattr(request, 'user', None)
        if (benutzer is not None and benutzer.is_authenticated and not antwort.has_header('Cache-Control')
                and antwort.get('Content-Type', '').startswith('text/html')):
            patch_cache_control(antwort, no_store=True, private=True)
        return antwort
