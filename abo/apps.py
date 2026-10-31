from django.apps import AppConfig


class AboConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "abo"
    verbose_name = "Abonnement und Plattform-Rechnung"

    def ready(self):
        from abo import signale  # noqa: F401  (Grenzen beim Anlegen, siehe abo/signale.py)
