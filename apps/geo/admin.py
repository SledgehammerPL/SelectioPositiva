from django.contrib import admin

from .models import PollingStation, TerritorialLevel, TerritorialUnit


@admin.register(TerritorialLevel)
class TerritorialLevelAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "display_order")
    search_fields = ("name", "slug")
    ordering = ("display_order", "name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(TerritorialUnit)
class TerritorialUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "teryt", "parent")
    list_filter = ("kind",)
    search_fields = ("name", "slug", "teryt")
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("parent",)


@admin.register(PollingStation)
class PollingStationAdmin(admin.ModelAdmin):
    list_display = ("number", "code", "name", "precinct", "address")
    list_filter = ("precinct__kind",)
    search_fields = ("name", "code", "address", "streets_served", "number")
    raw_id_fields = ("precinct",)
    fields = (
        "number",
        "code",
        "name",
        "precinct",
        "address",
        "streets_served",
    )
