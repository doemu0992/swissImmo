from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finance"

    def ready(self):
        # Zahlungseingang → laufende 257d-Frist prüfen (siehe finance/signals.py).
        from finance import signals  # noqa: F401
