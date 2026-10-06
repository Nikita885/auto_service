from django.contrib import admin

from apps.garage.models import Car


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = ("title", "plate", "user", "year", "mileage", "is_primary", "archived_at")
    list_filter = ("is_primary",)
    search_fields = ("title", "plate", "vin", "user__phone")
    raw_id_fields = ("user", "make", "model")
    readonly_fields = ("id", "created_at", "updated_at")
