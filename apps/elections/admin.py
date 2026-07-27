from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Ballot,
    ElectionResultCache,
    ElectoralDistrict,
    Office,
    Party,
    VoterProfile,
)

User = get_user_model()


class VoterProfileInline(admin.StackedInline):
    model = VoterProfile
    can_delete = False
    fk_name = "user"
    raw_id_fields = ("territorial_unit",)


class UserWithProfileAdmin(BaseUserAdmin):
    inlines = (VoterProfileInline,)


admin.site.unregister(User)
admin.site.register(User, UserWithProfileAdmin)


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ("name", "abbreviation", "is_active", "display_order")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "abbreviation")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "min_age",
        "candidacy_level",
        "is_open",
        "display_order",
    )
    list_filter = ("is_open", "candidacy_level")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("candidacy_level",)


@admin.register(ElectoralDistrict)
class ElectoralDistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "office", "seats_count", "display_order")
    list_filter = ("office",)
    search_fields = ("name", "slug", "office__name")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("territorial_units",)


@admin.register(Ballot)
class BallotAdmin(admin.ModelAdmin):
    list_display = ("user", "district", "is_voided", "void_reason", "updated_at")
    list_filter = ("is_voided", "district__office", "void_reason")
    search_fields = ("user__username", "district__name")
    raw_id_fields = ("user", "district")
    readonly_fields = ("created_at", "updated_at", "voided_at")


@admin.register(VoterProfile)
class VoterProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "territorial_unit", "birth_date")
    list_filter = ("territorial_unit__kind",)
    raw_id_fields = ("user", "territorial_unit")


@admin.register(ElectionResultCache)
class ElectionResultCacheAdmin(admin.ModelAdmin):
    list_display = ("district", "ballot_count", "is_stale", "computed_at", "updated_at")
    list_filter = ("is_stale",)
    search_fields = ("district__name", "district__slug")
    readonly_fields = ("fingerprint", "computed_at", "updated_at", "payload")
