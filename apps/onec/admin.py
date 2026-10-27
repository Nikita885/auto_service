from django.contrib import admin

from apps.onec.models import BookingSync


@admin.register(BookingSync)
class BookingSyncAdmin(admin.ModelAdmin):
    list_display = (
        "booking",
        "request_number",
        "order_number",
        "order_state",
        "receipt_number",
        "exported_at",
        "last_error",
    )
    list_filter = ("order_state",)
    search_fields = ("booking__code", "request_number", "order_number", "receipt_number")
    raw_id_fields = ("booking",)
    readonly_fields = [field.name for field in BookingSync._meta.fields if field.name != "booking"]
