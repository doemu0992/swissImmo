"""Weist übergrosse Anfragen ab, BEVOR der Body gelesen wird.

Django streamt hochgeladene Dateien ab 2.5 MB auf die Festplatte
(`FILE_UPLOAD_MAX_MEMORY_SIZE`); `DATA_UPLOAD_MAX_MEMORY_SIZE` gilt nur für
Nicht-Datei-Felder. Eine 500-MB-«PDF» füllte deshalb zuerst den temporären
Ordner und wurde erst in der View von `validiere_*` abgelehnt — zu spät, und
in Views ohne Prüfung gar nicht.

Der Client deklariert die Länge im Header `Content-Length`. Ist sie zu gross,
antwortet diese Schicht mit 413, ohne `request.POST`/`request.FILES` je
anzufassen. Ein Client, der die Länge falsch angibt, wird vom Webserver
(Grenze dort ebenfalls setzen: nginx `client_max_body_size`) und von den
Prüfungen in `core.utils.uploads` aufgefangen.

Die Grenze ist ein Rahmen (mehrere Fotos + Formularfelder), keine
Einzeldateigrenze — die setzen `MAX_BILD_BYTES` und `MAX_DOKUMENT_BYTES`.
"""
from django.conf import settings
from django.http import HttpResponse

#: Gesamtgrösse einer Anfrage. 8 Fotos à 15 MB ≈ 120 MB wären zu viel; 60 MB
#: reichen für mehrere Handyfotos oder Dokumente.
MAX_ANFRAGE_BYTES = 60 * 1024 * 1024


class UploadGrenzeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        grenze = getattr(settings, 'MAX_ANFRAGE_BYTES', MAX_ANFRAGE_BYTES)
        try:
            laenge = int(request.META.get('CONTENT_LENGTH') or 0)
        except (TypeError, ValueError):
            return HttpResponse('Ungültige Anfrage.', status=400, content_type='text/plain; charset=utf-8')
        if laenge > grenze:
            mb = grenze // (1024 * 1024)
            return HttpResponse(
                f'Die Anfrage ist zu gross (maximal {mb} MB). Bitte kleinere oder weniger Dateien wählen.',
                status=413, content_type='text/plain; charset=utf-8')
        return self.get_response(request)
