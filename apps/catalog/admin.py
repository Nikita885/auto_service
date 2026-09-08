from django.contrib import admin

from apps.catalog.models import Oil, OilStock, ServicePoint


class OilStockInline(admin.TabularInline):
    model = OilStock
    extra = 0
    autocomplete_fields = ("oil",)


@admin.register(ServicePoint)
class ServicePointAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "opens_at", "closes_at", "slot_minutes",
                    "posts_count", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "address")
    inlines = [OilStockInline]


@admin.register(Oil)
class OilAdmin(admin.ModelAdmin):
    list_display = ("brand", "name", "viscosity", "oil_type", "volume_liters",
                    "price", "work_price", "is_active")
    list_filter = ("oil_type", "brand", "is_active")
    search_fields = ("brand", "name", "viscosity")


@admin.register(OilStock)
class OilStockAdmin(admin.ModelAdmin):
    list_display = ("oil", "service_point", "quantity")
    list_filter = ("service_point",)
    search_fields = ("oil__brand", "oil__name")
    autocomplete_fields = ("oil", "service_point")
