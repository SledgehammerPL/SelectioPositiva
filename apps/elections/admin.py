from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    Ballot,
    Candidate,
    ElectionResultCache,
    ElectoralDistrict,
    Office,
    VoterProfile,
)


class VoterProfileInline(admin.StackedInline):
    model = VoterProfile
    can_delete = False
    fk_name = "user"
    raw_id_fields = ("polling_station",)


class UserAdmin(BaseUserAdmin):
    inlines = (VoterProfileInline,)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


class ElectoralDistrictInline(admin.TabularInline):
    model = ElectoralDistrict
    extra = 0
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("territorial_unit",)


class CandidateInline(admin.TabularInline):
    model = Candidate
    extra = 1
    fields = ("name", "committee", "is_active", "display_order")


@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_open", "display_order")
    list_filter = ("is_open",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ElectoralDistrictInline,)


@admin.register(ElectoralDistrict)
class ElectoralDistrictAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "office",
        "territorial_unit",
        "seats_count",
        "display_order",
    )
    list_filter = ("office", "territorial_unit__kind")
    search_fields = ("name", "slug", "office__name")
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("office", "territorial_unit")
    inlines = (CandidateInline,)


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("name", "committee", "district", "is_active", "display_order")
    list_filter = ("is_active", "district__office")
    search_fields = ("name", "committee")
    raw_id_fields = ("district",)


@admin.register(Ballot)
class BallotAdmin(admin.ModelAdmin):
    list_display = ("user", "district", "is_voided", "void_reason", "updated_at")
    list_filter = ("is_voided", "district__office", "void_reason")
    search_fields = ("user__username", "district__name")
    raw_id_fields = ("user", "district")
    readonly_fields = ("created_at", "updated_at", "voided_at")


@admin.register(VoterProfile)
class VoterProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "polling_station")
    raw_id_fields = ("user", "polling_station")


@admin.register(ElectionResultCache)
class ElectionResultCacheAdmin(admin.ModelAdmin):
    list_display = ("district", "ballot_count", "is_stale", "computed_at", "updated_at")
    list_filter = ("is_stale",)
    search_fields = ("district__name", "district__slug")
    readonly_fields = ("fingerprint", "computed_at", "updated_at", "payload")
