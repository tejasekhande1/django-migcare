from django.apps import AppConfig


class MigcareConfig(AppConfig):
    name = "migcare"
    verbose_name = "Migration Care"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401 — registers signal handlers