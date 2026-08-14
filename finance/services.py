# finance/services.py
#
# Fachlogik, die bisher in finance/api.py wohnte, dort aber kein Endpunkt
# ist und von core/views/fw.py gebraucht wird. Herausgezogen in E1a, damit
# die API-Module in E1c geloescht werden koennen, ohne die laufende
# Oberflaeche zu brechen. Unveraendert uebernommen.

# ========================================================
# HILFSFUNKTION: STORNO BUCHUNG (Revisionssicherheit)
# ========================================================
def erstelle_storno_buchung(original_buchung, benutzer=None):
    """Erstellt die revisionssichere Umkehrbuchung.

    Delegiert an die EINE kanonische Storno-Implementation
    (finance.booking.storniere_buchung): markiert das Original als storniert
    (storniert_am), verkettet Original↔Gegenbuchung (storno_von), führt die
    Beleg-Verknüpfungen mit und verhindert Doppel-Storno. Die frühere lokale
    Variante tat all das nicht — Storno-Kette war gebrochen, Kennzahlen
    zählten stornierte Originale weiter."""
    from finance.booking import storniere_buchung
    return storniere_buchung(original_buchung, user=benutzer)
