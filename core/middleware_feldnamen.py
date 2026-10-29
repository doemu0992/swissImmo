"""Verbindet Beschriftung und Feld in jeder HTML-Antwort (DESIGN-27).

Die Arbeit steht in `core.utils.feldnamen`; hier nur der Anschluss an die Antwort. Angefasst werden
nur vollständige HTML-Seiten (Status 200, `text/html`, nicht gestreamt) mit mindestens einem
`<label` oder `placeholder`. Bilder, PDF, JSON, Umleitungen und Fehlerseiten laufen unverändert durch.

Die Middleware steht UNTER `CommonMiddleware` und `GZipMiddleware` in der Liste, damit deren
Antwortseite den veränderten Inhalt sieht (Länge, Komprimierung).
"""
import re

from core.utils.feldnamen import feldnamen_ergaenzen

_MOEGLICH = re.compile(rb'<label|placeholder\s*=', re.IGNORECASE)


class FeldnamenMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        antwort = self.get_response(request)
        if (antwort.status_code != 200 or getattr(antwort, 'streaming', False)
                or not antwort.get('Content-Type', '').startswith('text/html')
                or antwort.has_header('Content-Encoding')):
            return antwort
        inhalt = antwort.content
        if not _MOEGLICH.search(inhalt):
            return antwort
        text = inhalt.decode(antwort.charset or 'utf-8', 'replace')
        neu = feldnamen_ergaenzen(text)
        if neu != text:
            antwort.content = neu.encode(antwort.charset or 'utf-8')
            if antwort.has_header('Content-Length'):
                antwort['Content-Length'] = str(len(antwort.content))
        return antwort
