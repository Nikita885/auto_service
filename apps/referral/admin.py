from django.contrib import admin

from apps.referral.models import BinarySettlement, LegCredit, PointsEntry, ReferralNode


@admin.register(ReferralNode)
class ReferralNodeAdmin(admin.ModelAdmin):
    list_display = (
        "code", "user", "depth", "position", "parent", "sponsor", "balance",
        "carry_left", "carry_right",
    )
    list_filter = ("depth", "position")
    search_fields = ("code", "user__phone", "user__full_name")
    # Дерево правится только кодом: перевесить узел мышкой значит отобрать
    # у кого-то уже начисленные баллы.
    readonly_fields = (
        "parent", "position", "depth", "sponsor", "balance", "code", "carry_left", "carry_right",
    )
    raw_id_fields = ("user",)
    ordering = ("depth", "created_at")


@admin.register(PointsEntry)
class PointsEntryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "node", "kind", "amount", "level", "percent", "booking")
    list_filter = ("kind", "level")
    search_fields = ("node__code", "node__user__phone", "booking__code", "comment")
    # Журнал — источник правды по балансу. Правка задним числом разошлась бы
    # с денормализованным ReferralNode.balance, поэтому только чтение.
    readonly_fields = tuple(
        f.name for f in PointsEntry._meta.fields if f.name != "comment"
    )
    raw_id_fields = ("node", "booking", "source_node")
    date_hierarchy = "created_at"


@admin.register(LegCredit)
class LegCreditAdmin(admin.ModelAdmin):
    list_display = (
        "created_at", "node", "side", "amount", "level", "percent", "booking", "settlement",
    )
    list_filter = ("side", "level")
    search_fields = ("node__code", "node__user__phone", "booking__code")
    # Поступления и сведения — финансовая история, правится только кодом.
    readonly_fields = tuple(f.name for f in LegCredit._meta.fields)
    raw_id_fields = ("node", "booking", "source_node", "settlement")
    date_hierarchy = "created_at"


@admin.register(BinarySettlement)
class BinarySettlementAdmin(admin.ModelAdmin):
    list_display = (
        "day", "node", "left_before", "left_added", "right_before", "right_added",
        "paid", "left_after", "right_after",
    )
    search_fields = ("node__code", "node__user__phone")
    readonly_fields = tuple(f.name for f in BinarySettlement._meta.fields)
    raw_id_fields = ("node", "entry")
    date_hierarchy = "day"
