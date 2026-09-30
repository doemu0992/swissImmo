"""Unlesbare Eingaben werden zu «400 Bad Request», nicht zu «500».

WARUM ES DAS GIBT (Go-Live-Härtetest, Schritt 4)

Rund 250 Views lesen `request.POST.get(...)` und reichen den Wert an
`Model.objects.filter(id=...)` oder an einen `Decimal` weiter. Ein Formular, das
nie eine Zahl in ein Id-Feld schreibt, erzeugt damit keinen Fehler — ein
manipulierter Aufruf (`liegenschaft_id=abc`, `betrag=1e999`, eine Id mit 30
Stellen) aber schon: `ValueError`, `OverflowError`, `InvalidOperation`. Der
Anwender sah eine 500er-Seite, der Betreiber einen Eintrag im Fehlerlog, als
wäre etwas kaputt.

Die Views einzeln zu härten wäre richtig UND unvollständig — die nächste kommt
bestimmt. Diese Schicht fängt genau die drei Familien «Wert nicht lesbar / nicht
darstellbar» ab und antwortet ehrlich mit 400. Alles andere (echte Fehler,
`KeyError`, `AttributeError`, ...) läuft unverändert weiter und bleibt ein 500.
"""
import logging
import re
from decimal import InvalidOperation

from django.db import DataError
from django.http import HttpResponseBadRequest

logger = logging.getLogger(__name__)

_ZAHL = re.compile(r"Field '\w+' expected a (number|boolean)|Betrag|Python int too large|"
                   r"int too large|out of range|invalid literal|kein gültiger|zu gross", re.I)


def ist_eingabefehler(exc):
    if isinstance(exc, (InvalidOperation, DataError)):
        return True
    if isinstance(exc, (ValueError, OverflowError)):
        return bool(_ZAHL.search(str(exc)))
    return False


class UnlesbareEingabeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not ist_eingabefehler(exception):
            return None
        logger.warning('Unlesbare Eingabe abgewiesen: %s %s (%s)', request.method,
                       request.path, type(exception).__name__)
        return HttpResponseBadRequest(
            '<!doctype html><meta charset="utf-8"><title>Ungültige Eingabe</title>'
            '<h1>Ungültige Eingabe</h1><p>Ein Wert konnte nicht gelesen werden '
            '(Zahl, Betrag oder Auswahl). Bitte die Angaben prüfen und zurückgehen.</p>',
            content_type='text/html; charset=utf-8')
