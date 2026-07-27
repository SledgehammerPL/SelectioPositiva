from django.contrib import admin

from .models import PollingStation, TerritorialUnit


@admin.register(TerritorialUnit)
class TerritorialUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "teryt", "parent", "center_lat", "center_lng")
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
        "latitude",
        "longitude",
    )
