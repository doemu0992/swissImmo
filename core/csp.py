"""Content-Security-Policy (Roadmap Nr. 23, Etappe 1): Nonce je Anfrage, Richtlinie, Berichtsstelle.

WARUM
    Ohne CSP läuft jedes eingeschleuste `<script>` und jeder `onclick="…"`, den ein ungeschützter Wert in eine
    Seite bringt. Die Richtlinie sagt dem Browser: Skripte nur von uns oder mit dem Nonce dieser Antwort.

WIE ES EINGEFÜHRT WIRD (Etappen)
    1. (jetzt) Nonce an allen Inline-Skripten, Richtlinie im Modus «report-only»: Der Browser meldet, was er
       sperren WÜRDE (`/csp-bericht/`, Warnung im Log), sperrt aber nichts. Eine Ratsche (`test_csp`) lässt
       Inline-Handler (`onclick=` …) nicht mehr zunehmen.
    2. Die Inline-Handler wandern nach und nach in `static/js/` (Datenattribute und ein zentraler Verteiler).
    3. Sind es null, wird `CSP_MODUS=enforce` gesetzt.

    `CSP_MODUS`: `report-only` (Vorgabe), `enforce` oder `aus` (Umgebungsvariable; `aus` nur als Notausstieg).

STIL
    Seit 12.11.2026 ohne `'unsafe-inline'`: Die Browser-Vorlagen haben kein `style="…"` mehr (`core/tests/test_stilschuld.py`),
    `<style>`-Blöcke tragen den Nonce, dynamische Masse (Balken, Kurven) setzt `static/js/fw-aktionen.js` über das Stilobjekt.
    Ausnahme: Antworten, die ein fertiges Dokument zeigen (Vertragsvorschau), setzen `request.csp_stil_inline = True`.
"""
import json
import logging
import secrets

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, RawPostDataException
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger('csp')

HEADER_ENFORCE = 'Content-Security-Policy'
HEADER_REPORT = 'Content-Security-Policy-Report-Only'
BERICHT_PFAD = '/csp-bericht/'
MODI = ('report-only', 'enforce', 'aus')


def modus():
    wert = str(getattr(settings, 'CSP_MODUS', 'report-only') or 'report-only').strip().lower()
    return wert if wert in MODI else 'report-only'


def richtlinie(nonce, stil_inline=False):
    """Die Richtlinie dieser Antwort.

    Stile: nur eigene Dateien und `<style nonce>` — kein `style="…"`-Attribut im Quelltext (Masse setzt `fw-aktionen.js`
    über das Stilobjekt). `stil_inline=True` erlaubt Inline-Stile für Antworten, die ein fertiges Dokument zeigen (die
    Vertragsvorschau, gerendert aus der PDF-Vorlage mit eigenen Stilen). Skripte bleiben auch dort auf den Nonce beschränkt."""
    return '; '.join([
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        "style-src 'self' 'unsafe-inline'" if stil_inline else f"style-src 'self' 'nonce-{nonce}'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "frame-src 'self'",
        "frame-ancestors 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        f"report-uri {BERICHT_PFAD}",
    ])


class CspMiddleware:
    """Legt `request.csp_nonce` an und setzt den Richtlinien-Kopf (je nach `CSP_MODUS`)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        antwort = self.get_response(request)
        art = modus()
        if art != 'aus' and HEADER_ENFORCE not in antwort and HEADER_REPORT not in antwort:
            antwort[HEADER_ENFORCE if art == 'enforce' else HEADER_REPORT] = richtlinie(
                request.csp_nonce, stil_inline=getattr(request, 'csp_stil_inline', False))
        return antwort


def kontext(request):
    """Context-Processor: `{{ csp_nonce }}` für `<script nonce="{{ csp_nonce }}">`."""
    return {'csp_nonce': getattr(request, 'csp_nonce', '')}


def _kurz(wert, n=200):
    return str(wert or '')[:n].replace('\n', ' ')


@csrf_exempt
@require_POST
def csp_bericht(request):
    """Nimmt Verstossmeldungen des Browsers entgegen und schreibt eine Warnung ins Log.

    Offen (ohne Anmeldung): Auch die Anmeldeseite meldet. Gedeckelt: höchstens 8 kB je Meldung und 60 Meldungen
    je Minute und Absender — sonst wäre die Stelle ein Weg, das Log zu fluten.
    """
    try:
        koerper = request.body or b''
    except RawPostDataException:        # ein Formular-Body wurde schon gelesen: kein Bericht des Browsers
        return HttpResponse(status=400)
    if len(koerper) > 8192:
        return HttpResponse(status=413)
    absender = request.META.get('REMOTE_ADDR', '?')
    schluessel = f'csp-bericht:{absender}'
    try:
        n = cache.incr(schluessel)
    except ValueError:
        cache.set(schluessel, 1, 60)
        n = 1
    if n > 60:
        return HttpResponse(status=429)
    try:
        roh = json.loads(koerper.decode('utf-8') or '{}')
    except ValueError:
        return HttpResponse(status=400)
    eintraege = roh if isinstance(roh, list) else [roh]
    for e in eintraege[:5]:
        b = e.get('csp-report', e.get('body', e)) if isinstance(e, dict) else {}
        if not isinstance(b, dict):
            continue
        logger.warning(
            'CSP-Verstoss: %s | blockiert=%s | Seite=%s | Zeile=%s',
            _kurz(b.get('violated-directive') or b.get('effectiveDirective')),
            _kurz(b.get('blocked-uri') or b.get('blockedURL') or b.get('blocked-url')),
            _kurz(b.get('document-uri') or b.get('documentURL')),
            _kurz(b.get('line-number') or b.get('lineNumber')))
    return HttpResponse(status=204)
