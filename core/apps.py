from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Login-/Sicherheits-Ereignisse ins Logbuch schreiben.
        from core import signals  # noqa: F401

        # Einmal beim Start: Passt das Schema zum Code? Wenn nicht, geht die
        # Anwendung in den Wartungsmodus, statt auf jeder Seite einen
        # Traceback zu zeigen (siehe docs/WARTUNGSSEITE.md).
        #
        # Hier und nicht in der Middleware, weil das sonst eine zusaetzliche
        # Datenbankabfrage bei JEDEM Seitenaufruf waere — fuer einen Zustand,
        # der sich zwischen zwei Anfragen nicht aendert.
        from core.wartung import pruefe_migrationsstand
        pruefe_migrationsstand()

        # Startprüfungen registrieren (siehe core/checks.py). Nur der Import
        # zählt — die Funktionen tragen sich über `@register()` selbst ein.
        from core import checks  # noqa: F401
