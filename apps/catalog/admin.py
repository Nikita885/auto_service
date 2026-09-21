from django.contrib import admin

from apps.catalog.models import CarMake, CarModel, Oil, OilStock, ServicePoint


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


class CarModelInline(admin.TabularInline):
    model = CarModel
    extra = 0
    fields = ("name", "search_terms", "is_active")


@admin.register(CarMake)
class CarMakeAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "models_count", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name", "search_terms", "search_index")
    ordering = ("sort_order", "name")
    inlines = [CarModelInline]
    # Поисковую форму показываем только для чтения: её считает `save()`, и
    # руками её править нельзя — разъедется с тем, по чему идёт поиск.
    readonly_fields = ("search_index",)

    @admin.display(description="моделей")
    def models_count(self, obj) -> int:
        return obj.models.count()


@admin.register(CarModel)
class CarModelAdmin(admin.ModelAdmin):
    list_display = ("name", "make", "is_active")
    list_filter = ("make", "is_active")
    search_fields = ("name", "search_terms", "search_index", "make__name")
    autocomplete_fields = ("make",)
    readonly_fields = ("search_index",)
