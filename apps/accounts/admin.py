from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import OtpCode, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("phone", "full_name", "role", "car_model", "car_plate", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("phone", "full_name", "car_plate")
    readonly_fields = ("id", "date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("id", "phone", "password")}),
        ("Профиль", {"fields": ("full_name", "car_model", "car_plate")}),
        ("Права", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups")}),
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
