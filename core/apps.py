from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Hier stand vorher der Import der Signals.
        # Da wir signals.py nicht mehr brauchen, ist das hier leer.
        pass
