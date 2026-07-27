from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

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
    fields = ("phone", "birth_date", "territorial_unit")


class UserWithProfileAdmin(BaseUserAdmin):
    inlines = (VoterProfileInline,)
    list_display = ("phone_display", "first_name", "last_name", "is_staff", "is_active")
    search_fields = ("first_name", "last_name", "email", "voter_profile__phone")
    ordering = ("pk",)
    # Username jest tylko wewnętrzne (u{id}) — logowanie po telefonie.
    fieldsets = (
        (None, {"fields": ("password",)}),
        (_("Dane osobowe"), {"fields": ("first_name", "last_name", "email")}),
        (
            _("Uprawnienia"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Ważne daty"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("password1", "password2"),
                "description": (
                    "Po utworzeniu uzupełnij telefon (+48…) w profilu wyborcy — "
                    "to login użytkownika."
                ),
            },
        ),
    )

    @admin.display(description="Telefon")
    def phone_display(self, obj):
        try:
            return obj.voter_profile.phone
        except VoterProfile.DoesNotExist:
            return "—"

    def save_model(self, request, obj, form, change):
        import uuid

        creating = obj.pk is None
        if creating and not obj.username:
            obj.username = f"_tmp_{uuid.uuid4().hex[:12]}"
        super().save_model(request, obj, form, change)
        desired = f"u{obj.pk}"
        if obj.username != desired:
            obj.username = desired
            obj.save(update_fields=["username"])


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
    search_fields = (
        "user__first_name",
        "user__last_name",
        "user__voter_profile__phone",
        "district__name",
    )
    raw_id_fields = ("user", "district")
    readonly_fields = ("created_at", "updated_at", "voided_at")


@admin.register(VoterProfile)
class VoterProfileAdmin(admin.ModelAdmin):
    list_display = ("phone", "user", "territorial_unit", "birth_date")
    list_filter = ("territorial_unit__kind",)
    search_fields = ("phone", "user__first_name", "user__last_name")
    raw_id_fields = ("user", "territorial_unit")


@admin.register(ElectionResultCache)
class ElectionResultCacheAdmin(admin.ModelAdmin):
    list_display = ("district", "ballot_count", "is_stale", "computed_at", "updated_at")
    list_filter = ("is_stale",)
    search_fields = ("district__name", "district__slug")
    readonly_fields = ("fingerprint", "computed_at", "updated_at", "payload")
