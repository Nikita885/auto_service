from django.contrib import admin

from apps.assistant.models import AssistantRequest


@admin.register(AssistantRequest)
class AssistantRequestAdmin(admin.ModelAdmin):
    """Только чтение: это счётчики, а не данные для правки."""

    list_display = (
        "created_at", "service_point", "model", "input_tokens", "output_tokens",
        "cost", "category", "service", "on_site", "error",
    )
    list_filter = ("service_point", "provider", "error")
    date_hierarchy = "created_at"
    list_select_related = ("service_point", "category", "service")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
