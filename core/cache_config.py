"""Cache-Konfiguration: ein Zähler für ALLE Prozesse.

Ohne `CACHES` nimmt Django einen Speicher-Cache **je Prozess** (`LocMemCache`). Login-Fehlversuche, die Sperre des
Direktlinks und die Formular-Limits (`core/utils/throttle.py`) zählen dann je Worker getrennt: Bei vier Workern darf
ein Angreifer viermal so oft raten, wie das Limit sagt, und eine Sperre greift nur, wenn die Anfrage zufällig beim
selben Worker landet. (Befund Analysebericht 06.11.2026.)

Im Betrieb liegt der Cache deshalb in Dateien eines gemeinsamen Verzeichnisses (`FileBasedCache`): Alle Worker und der
Always-on-Task desselben Rechners sehen dieselben Zähler. Das braucht weder Redis noch eine Migration und fällt nicht
aus, wenn eine Tabelle fehlt. Grenzen, ehrlich: `incr` ist nicht atomar (zwei gleichzeitige Fehlversuche können als
einer zählen), und über mehrere Rechner hinweg teilen sich die Dateien nichts; dafür wäre Redis nötig. Beides ist für
eine Missbrauchsbremse ausreichend, für eine harte Sperre nicht.

In Tests bleibt der Speicher-Cache: Paralleles Testen (`--parallel`) teilte sich sonst ein Verzeichnis, und
`cache.clear()` in `setUp` räumte anderen Tests die Zähler weg.
"""
import os


def caches_fuer(testing, basis, verzeichnis=None):
    """`CACHES` für `settings.py`. `verzeichnis`: gemeinsamer Ordner (Umgebung `CACHE_VERZEICHNIS`), sonst unter `basis`."""
    if testing:
        return {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
    return {
        'default': {
            'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
            'LOCATION': verzeichnis or os.path.join(basis, 'cache_dateien'),
            'TIMEOUT': 300,
            'OPTIONS': {'MAX_ENTRIES': 20000},
        },
    }
