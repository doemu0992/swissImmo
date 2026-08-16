from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # ADMIN = NOTFALL-MODUS: Der Unfold-Admin ist nur noch für Superuser
        # zugänglich. Alle Alltags-Workflows laufen über das SPA (/app/) mit
        # dem Rollenkonzept aus core/auth.py. Sachbearbeiter/Lesende brauchen
        # den Admin nicht — und sollen dort auch nichts kaputt machen können.
        from django.contrib import admin

        def superuser_only(request):
            return bool(
                request.user
                and request.user.is_active
                and request.user.is_superuser
            )

        admin.site.has_permission = superuser_only

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
