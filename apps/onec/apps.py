from django.apps import AppConfig


class OneCConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.onec"
    verbose_name = "Обмен с 1С"

    def ready(self):
        from apps.onec import schema  # noqa: F401
