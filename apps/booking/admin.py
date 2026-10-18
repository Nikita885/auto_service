from django.contrib import admin

from apps.booking.models import (
    Booking,
    BookingDraft,
    BookingItem,
    BookingPriceChange,
    BookingStatusLog,
)


class BookingItemInline(admin.TabularInline):
    """Услуги записи. Цены — снимок на момент брони, поэтому правятся
    руками только здесь и только если расчёт разошёлся с реальностью."""

    model = BookingItem
    extra = 0
    fields = ("service", "title", "category_title", "price", "material_price", "quantity")
    autocomplete_fields = ("service",)


class BookingStatusLogInline(admin.TabularInline):
    model = BookingStatusLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "actor", "comment", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


class BookingPriceChangeInline(admin.TabularInline):
    model = BookingPriceChange
    extra = 0
    readonly_fields = ("old_price", "new_price", "reason", "actor", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "start_at",
        "service_point",
        "client_name",
        "client_phone",
        "service_title",
        "status",
    )
    list_filter = ("status", "service_point", "start_at")
    search_fields = (
        "code", "client_phone", "client_name", "car_plate", "service_title", "oil_title",
    )
    date_hierarchy = "start_at"
    readonly_fields = (
        "id", "code", "created_at", "updated_at", "total_price", "final_price",
    )
    autocomplete_fields = ("user", "master", "service_point", "service_category", "oil")
    inlines = [BookingItemInline, BookingStatusLogInline, BookingPriceChangeInline]


@admin.register(BookingDraft)
class BookingDraftAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "step", "is_open", "expires_at", "service_point", "service",
    )
    list_filter = ("step", "is_open", "service_point")
    search_fields = ("user__phone", "user__full_name")
    readonly_fields = ("id", "created_at", "updated_at", "expires_at")
    autocomplete_fields = (
        "user", "service_point", "service_category", "service", "oil", "booking",
    )


@admin.register(BookingStatusLog)
class BookingStatusLogAdmin(admin.ModelAdmin):
    list_display = ("booking", "from_status", "to_status", "actor", "created_at")
    list_filter = ("to_status",)
    search_fields = ("booking__code",)
