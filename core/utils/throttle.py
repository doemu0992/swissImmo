"""Einfacher cache-basierter IP-Rate-Limiter (fixed window) für öffentliche
Endpunkte (Bewerbungs-/Schadenformular). Nutzt den konfigurierten Django-Cache;
im Betrieb ist das der gemeinsame Datei-Cache (`core/cache_config.py`), in Tests der Speicher-Cache. Die Zähler tragen ihr
Fensterende selbst (siehe unten), damit beide dasselbe Fenster haben."""
import time

from django.core.cache import cache


def client_ip(request):
    """Client-IP ermitteln — hinter dem Proxy (PythonAnywhere) via X-Forwarded-For.

    Der RECHTESTE Eintrag zählt: Ihn hat der eigene Proxy angehängt. Der linke
    stammt vom Client und ist frei wählbar — wer ihn nimmt, umgeht jedes
    Limit mit einem selbst gesetzten `X-Forwarded-For`-Header.
    """
    xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if xff:
        letzter = xff.split(',')[-1].strip()
        if letzter:
            return letzter
    return request.META.get('REMOTE_ADDR') or '0.0.0.0'


# ── Zähler mit FESTEM Fensterende ───────────────────────────────────────────────────────────────────────────────
# Gespeichert wird `(anzahl, fensterende)`, nicht eine nackte Zahl. Grund (Audit 15.11.2026): Im Betrieb läuft
# `FileBasedCache`, dessen `incr` «lesen und mit dem Standard-Timeout (300 s) neu schreiben» ist. Jeder weitere Treffer
# verkürzte damit das Fenster auf fünf Minuten nach dem LETZTEN Treffer — eine Login-Sperre von 15 Minuten hielt fünf,
# «10 Meldungen je Stunde» wurden 10 je fünf Minuten, und das 60-Sekunden-Fenster des API-Schlüssels lief bei
# Dauerabfrage nie ab. In den Tests (`LocMemCache`, behält die Ablaufzeit) fiel das nicht auf.
# Das Fensterende steht jetzt im Wert und wird bei jedem Schreiben als Restlaufzeit mitgegeben: unabhängig davon, wie der
# Cache `incr` versteht. Lesen und Schreiben sind zwei Schritte; treffen zwei Prozesse im selben Augenblick, kann ein
# Treffer verloren gehen. Für eine Bremse ist das hinzunehmen (das war mit `FileBasedCache.incr` schon so).
def _lesen(key, jetzt=None):
    """`(anzahl, fensterende)` des laufenden Fensters oder `(0, None)`. Alte Einträge (nackte Zahl) zählen als abgelaufen."""
    jetzt = time.time() if jetzt is None else jetzt
    wert = cache.get(key)
    if isinstance(wert, (tuple, list)) and len(wert) == 2 and wert[1] > jetzt:
        return int(wert[0]), float(wert[1])
    return 0, None


def _hochzaehlen(key, window_seconds):
    """Zählt einen Treffer; das Fenster beginnt mit dem ersten und endet `window_seconds` später. Gibt die Anzahl zurück."""
    jetzt = time.time()
    anzahl, ende = _lesen(key, jetzt)
    if ende is None:
        ende = jetzt + window_seconds
    anzahl += 1
    cache.set(key, (anzahl, ende), max(1, int(ende - jetzt + 0.999)))
    return anzahl


def stand(key):
    """Wie viele Treffer das laufende Fenster von `key` hat (0, wenn keines läuft)."""
    return _lesen(key)[0]


def ist_gesperrt(key, limit):
    """Ohne zu zählen: ist der Zähler `key` bereits über dem Limit?"""
    return stand(key) >= limit


def fehlversuch(key, window_seconds):
    """Einen Fehlversuch zählen (Fenster startet beim ersten). Gibt die neue Anzahl zurück."""
    return _hochzaehlen(key, window_seconds)


def zuruecksetzen(key):
    cache.delete(key)


def rate_limit(key, limit, window_seconds):
    """Zählt einen Zugriff und gibt True zurück, solange das Limit im Fenster
    nicht überschritten ist (fixed window). False = blockieren."""
    return _hochzaehlen(key, window_seconds) <= limit
