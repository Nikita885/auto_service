from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    verbose_name = "Каталог"

    def ready(self) -> None:
        from apps.catalog import signals  # noqa: F401  (подключает мост масел → услуги)
