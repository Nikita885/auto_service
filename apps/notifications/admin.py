from django.contrib import admin

from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "phone", "status", "sent_at")
    list_filter = ("kind", "status", "channel")
    search_fields = ("phone", "text", "booking__code")
    readonly_fields = tuple(f.name for f in Notification._meta.fields)
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
