"""Unmögliche Eingaben ergeben eine Meldung, keine 500-Seite (ROUTE-06, SICH-14).

BEFUND (Audit 28.10.2026)
35 Endpunkte antworteten auf PostgreSQL mit HTTP 500, sobald eine Eingabe nicht in ihr
Feld passte: ein Text über der Feldlänge (`DataError: value too long for type
character varying(200)`), ein Betrag über der Grenze (`BetragFehler`, früher
`ValueError`), eine Zahl ausserhalb von `smallint`/`integer`/`bigint`
(`DataError`, `OverflowError`) oder eine Nicht-Zahl als Kennung (`ValueError: Field
'id' expected a number`). SQLite nimmt zu lange Texte klaglos an und verschweigt das.
Die Verwaltung sah eine Fehlerseite und verlor die Eingabe; anonym liessen sich die
Formulare mit einer einzigen Anfrage zum Absturz bringen.

WARUM HIER UND NICHT IN JEDER VIEW
Es sind über 40 Stellen, von Hand gebaute Formulare ohne `ModelForm` (die Werte
gehen aus `request.POST` direkt ins Modell). Jede einzeln zu begrenzen vergisst
die 41. Diese Schicht fängt genau diese Ausnahme-Arten ab — und nur diese: ein
`ValueError` oder `DataError` allgemein bleibt ein Fehler, den man sehen will.

WAS DER NUTZER SIEHT
- Formular (POST): Die Meldung steht oben, die Seite davor wird wieder angezeigt
  (Rückkehr auf die Seite, von der abgeschickt wurde).
- Ohne Rückkehrseite oder bei GET: eine gestaltete Seite mit der Meldung (400).
- JSON/Fetch: `{"fehler": "..."}` mit Status 400.
Im Protokoll steht der Vorfall als Warnung mit der ursprünglichen Ausnahme.

Die Datenbank ist heil: Eine Ausnahme dieser Art bricht die Schreibaktion ab,
bevor etwas festgeschrieben wird (jede View mit mehreren Schreibvorgängen
arbeitet in `transaction.atomic`).
"""
import logging
import re

from django.contrib import messages
from django.db.utils import DataError, IntegrityError
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext

from finance.models import BetragFehler

logger = logging.getLogger(__name__)

_ZU_LANG = re.compile(r'value too long for type character varying\((\d+)\)')
_KEINE_ZAHL = re.compile(r"Field '[^']+' expected a number but got")
_AUSSERHALB = re.compile(r'out of range|numeric field overflow|integer too large')
_WERTEBEREICH = re.compile(r'CHECK constraint failed|violates check constraint')


def _meldung(exc):
    """Die Meldung für eine abfangbare Ausnahme — oder None, wenn sie ein echter Fehler ist."""
    if isinstance(exc, BetragFehler):
        return ' '.join(exc.messages)
    if isinstance(exc, DataError):
        text = str(exc)
        treffer = _ZU_LANG.search(text)
        if treffer:
            return gettext('Die Eingabe ist zu lang: Ein Feld darf höchstens %(n)s Zeichen enthalten.') % {
                'n': treffer.group(1)}
        if _AUSSERHALB.search(text):
            return gettext('Eine Zahl in der Eingabe ist zu gross oder zu klein.')
        return None
    if isinstance(exc, IntegrityError) and _WERTEBEREICH.search(str(exc)):
        # Eine Bereichsregel der Datenbank (z. B. Menge nicht negativ). Eindeutigkeit und
        # Fremdschlüssel sind etwas anderes und bleiben Sache der jeweiligen View.
        return gettext('Ein Wert liegt ausserhalb des zulässigen Bereichs (zum Beispiel eine negative Menge).')
    if isinstance(exc, OverflowError):
        return gettext('Eine Zahl in der Eingabe ist zu gross oder zu klein.')
    if isinstance(exc, ValueError) and _KEINE_ZAHL.search(str(exc)):
        return gettext('Die Eingabe enthält eine ungültige Kennung oder Zahl.')
    return None


class EingabeFehlerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        text = _meldung(exception)
        if text is None:
            return None            # ein echter Fehler: weiter zur 500-Seite und ins Protokoll
        logger.warning('Eingabe abgewiesen (%s %s): %s [%s: %s]', request.method, request.path,
                       text, type(exception).__name__, str(exception)[:200])
        text = gettext('Die Eingabe wurde nicht gespeichert.') + ' ' + text \
            if request.method not in ('GET', 'HEAD') else text

        akzeptiert = request.headers.get('Accept', '')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in akzeptiert:
            return JsonResponse({'fehler': text}, status=400)

        if request.method == 'POST':
            zurueck = request.META.get('HTTP_REFERER', '')
            if zurueck and url_has_allowed_host_and_scheme(
                    zurueck, allowed_hosts={request.get_host()},
                    require_https=request.is_secure()):
                messages.error(request, text)
                return HttpResponseRedirect(zurueck)

        return render(request, '400.html', {'meldung': text}, status=400)
