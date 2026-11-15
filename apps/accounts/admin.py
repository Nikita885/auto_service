from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import AccountDeletionRequest, OtpCode, User


@admin.register(AccountDeletionRequest)
class AccountDeletionRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "processed_at")
    list_filter = ("processed_at",)
    search_fields = ("user__phone", "user__full_name")
    readonly_fields = ("user", "created_at", "processed_at", "note")
    actions = ["process_requests"]

    @admin.action(description="Удалить данные по выбранным заявкам")
    def process_requests(self, request, queryset):
        from apps.accounts.deletion import process_deletion
        from apps.common.exceptions import ConflictError

        for item in queryset:
            try:
                process_deletion(item.pk)
            except ConflictError as exc:
                self.message_user(request, str(exc), level="error")
            else:
                self.message_user(request, "Данные удалены; проверьте внешние системы и бэкапы.")

    def has_add_permission(self, request):
        return False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("phone", "full_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("phone", "full_name", "cars__plate")
    readonly_fields = ("id", "date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("id", "phone", "password")}),
        ("Профиль", {"fields": ("full_name",)}),
        ("Права", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups",
                             "service_points", "allow_all_points")}),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "full_name", "role", "password1", "password2"),
            },
        ),
    )


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    list_display = ("phone", "created_at", "expires_at", "used_at", "attempts")
    list_filter = ("created_at",)
    search_fields = ("phone",)
    readonly_fields = ("id", "phone", "code_hash", "expires_at", "used_at", "attempts")

    def has_add_permission(self, request) -> bool:
        return False
