from django.contrib import admin

from .models import PollingStation, TerritorialUnit


@admin.register(TerritorialUnit)
class TerritorialUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "parent", "center_lat", "center_lng")
    list_filter = ("kind",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("parent",)


@admin.register(PollingStation)
class PollingStationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "territorial_unit", "address", "latitude", "longitude")
    list_filter = ("territorial_unit__kind",)
    search_fields = ("name", "code", "address")
    raw_id_fields = ("territorial_unit",)
