"""Entfernt NUL-Bytes (0x00) aus Formular- und Suchparametern.

PostgreSQL lehnt sie in Textfeldern und Suchwerten mit einem `DataError` ab,
SQLite nimmt sie klaglos. Ein `?q=%00` auf einer Liste war deshalb auf SQLite
harmlos und auf PostgreSQL ein Serverfehler (500) — der Pentest-Test
`test_listen_mit_suchparameter` fand es erst in der CI auf PostgreSQL.

Ein NUL-Byte hat in Eingaben nie eine Bedeutung. Es hier einmal zu entfernen
ist verlässlicher, als jede Liste und jedes Formular einzeln daran erinnern zu
müssen.

Nur Formularinhalte (`GET`, `application/x-www-form-urlencoded`,
`multipart/form-data`) werden angefasst. Ein anderer Inhaltstyp (JSON der
Webhooks) bleibt unberührt: `request.body` darf dort nicht vorab gelesen
werden.
"""


def _bereinigt(querydict):
    if not any('\x00' in k or any('\x00' in v for v in querydict.getlist(k))
               for k in querydict):
        return querydict
    sauber = querydict.copy()          # veränderbare Kopie
    for k in list(sauber):
        werte = [v.replace('\x00', '') for v in sauber.getlist(k)]
        sauber.setlist(k.replace('\x00', ''), werte)
        if '\x00' in k:
            del sauber[k]
    sauber._mutable = False
    return sauber


class NulBytesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.GET = _bereinigt(request.GET)
        if request.method == 'POST' and (request.content_type or '') in (
                'application/x-www-form-urlencoded', 'multipart/form-data'):
            request.POST = _bereinigt(request.POST)
        return self.get_response(request)
