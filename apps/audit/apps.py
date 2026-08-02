from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    verbose_name = "Audit"

    def ready(self) -> None:
        from apps.audit import signals  # noqa: F401 - signal handlerlarni ulash
