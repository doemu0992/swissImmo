"""Einfacher cache-basierter IP-Rate-Limiter (fixed window) für öffentliche
Endpunkte (Bewerbungs-/Schadenformular). Nutzt den konfigurierten Django-Cache;
mit dem Default-LocMemCache greift er pro Prozess — als Spam-/Missbrauchsbremse
ausreichend, für harte Limits einen geteilten Cache (DB/Redis) konfigurieren."""
from django.core.cache import cache


def client_ip(request):
    """Client-IP ermitteln — hinter dem Proxy (PythonAnywhere) via X-Forwarded-For."""
    xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or '0.0.0.0'


def rate_limit(key, limit, window_seconds):
    """Zählt einen Zugriff und gibt True zurück, solange das Limit im Fenster
    nicht überschritten ist (fixed window). False = blockieren."""
    # add() legt den Zähler nur an, wenn er fehlt → startet das Fenster mit TTL.
    if cache.add(key, 1, window_seconds):
        return True
    try:
        n = cache.incr(key)
    except ValueError:
        # Schlüssel ist zwischenzeitlich abgelaufen → Fenster neu starten.
        cache.set(key, 1, window_seconds)
        return True
    return n <= limit
