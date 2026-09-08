from django.contrib import admin

from apps.booking.models import Booking, BookingDraft, BookingStatusLog


class BookingStatusLogInline(admin.TabularInline):
    model = BookingStatusLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "actor", "comment", "created_at")
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
        "oil_title",
        "status",
    )
    list_filter = ("status", "service_point", "start_at")
    search_fields = ("code", "client_phone", "client_name", "car_plate", "oil_title")
    date_hierarchy = "start_at"
    readonly_fields = ("id", "code", "created_at", "updated_at", "total_price")
    autocomplete_fields = ("user", "master", "service_point", "oil")
    inlines = [BookingStatusLogInline]


@admin.register(BookingDraft)
class BookingDraftAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "step", "is_open", "expires_at", "service_point", "oil")
    list_filter = ("step", "is_open", "service_point")
    search_fields = ("user__phone", "user__full_name")
    readonly_fields = ("id", "created_at", "updated_at", "expires_at")
    autocomplete_fields = ("user", "service_point", "oil", "booking")


@admin.register(BookingStatusLog)
class BookingStatusLogAdmin(admin.ModelAdmin):
    list_display = ("booking", "from_status", "to_status", "actor", "created_at")
    list_filter = ("to_status",)
    search_fields = ("booking__code",)
