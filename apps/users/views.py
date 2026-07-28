from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Exists, OuterRef
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from django.conf import settings

from elections.services import ballot_counts_for_user, get_voter_profile
from geo.models import PollingStation, TerritorialUnit
from users.services.station_change import (
    change_user_polling_station,
    preview_station_change,
)


def _unit_payload(unit: TerritorialUnit, *, has_children: bool) -> dict:
    return {
        "id": unit.pk,
        "name": unit.name,
        "kind": unit.kind,
        "kind_label": unit.get_kind_display(),
        "has_children": has_children,
        "label": f"{unit.get_kind_display()}: {unit.name}",
    }


def _station_payload(station: PollingStation, *, current_id: int | None = None) -> dict:
    label = str(station)
    if current_id and station.pk == current_id:
        label = f"{label} (aktualna)"
    return {
        "id": station.pk,
        "code": station.code,
        "name": station.name,
        "address": station.address,
        "label": label,
    }


def _representative_station(precinct: TerritorialUnit | None) -> PollingStation | None:
    if precinct is None:
        return None
    return (
        PollingStation.objects.filter(precinct=precinct)
        .order_by("number", "pk")
        .first()
    )


def _current_path(profile) -> dict | None:
    """Ścieżka do aktualnego obwodu: woj → powiat → gmina → representative station."""
    if profile is None or not profile.territorial_unit_id:
        return None
    unit = profile.territorial_unit
    if unit.kind != TerritorialUnit.Kind.PRECINCT:
        return None
    ancestors = unit.get_ancestors(include_self=True)
    by_kind = {u.kind: u.pk for u in ancestors}
    station = _representative_station(unit)
    return {
        "voivodeship_id": by_kind.get(TerritorialUnit.Kind.VOIVODESHIP),
        "county_id": by_kind.get(TerritorialUnit.Kind.COUNTY),
        "municipality_id": by_kind.get(TerritorialUnit.Kind.MUNICIPALITY),
        "station_id": station.pk if station else None,
        "precinct_id": unit.pk,
    }


@login_required
@require_http_methods(["GET", "POST"])
def change_station(request: HttpRequest) -> HttpResponse:
    profile = get_voter_profile(request.user)
    current_station = _representative_station(
        profile.territorial_unit if profile else None
    )

    if request.method == "POST":
        raw_id = request.POST.get("station_id", "").strip()
        if not raw_id.isdigit():
            messages.error(request, "Wybierz komisję wyborczą.")
            return redirect("change_station")
        new_station = get_object_or_404(
            PollingStation.objects.select_related("precinct"), pk=int(raw_id)
        )
        if new_station.precinct_id is None:
            messages.error(request, "Wybrana komisja nie ma przypisanego obwodu.")
            return redirect("change_station")
        if (
            profile
            and profile.territorial_unit_id
            and profile.territorial_unit_id == new_station.precinct_id
        ):
            messages.info(request, "To już Twój aktualny obwód wyborczy.")
            return redirect("dashboard")

        result = change_user_polling_station(request.user, new_station)
        prev = result.previous_station
        request.session["station_change_summary"] = {
            "previous": str(prev) if prev else str(result.previous_precinct or "—"),
            "new": str(result.new_station),
            "active": result.active_ballots,
            "voided": result.voided_ballots,
            "voided_offices": [str(d) for d in result.voided_districts],
            "restored_offices": [str(d) for d in result.restored_districts],
        }
        messages.success(
            request,
            f"Zmieniono obwód (komisja: {result.new_station.name}). "
            f"Głosy aktywne: {result.active_ballots}. "
            f"Głosy zawieszone: {result.voided_ballots}.",
        )
        return redirect("dashboard")

    voivodeships = list(
        TerritorialUnit.objects.filter(kind=TerritorialUnit.Kind.VOIVODESHIP)
        .order_by("name")
        .only("id", "name", "kind")
    )
    counts = ballot_counts_for_user(request.user)
    return render(
        request,
        "users/change_station.html",
        {
            "profile": profile,
            "display_station": current_station,
            "voivodeships": voivodeships,
            "current_station_id": current_station.pk if current_station else None,
            "current_path_json": _current_path(profile),
            "ballot_counts": counts,
            "children_url": reverse("station_unit_children"),
            "stations_url": reverse("station_unit_stations"),
            "preview_url": reverse("preview_station_change"),
        },
    )


@login_required
@require_GET
def station_unit_children(request: HttpRequest) -> JsonResponse | HttpResponseBadRequest:
    raw = (request.GET.get("parent_id") or "").strip()
    if not raw.isdigit():
        return HttpResponseBadRequest("parent_id required")
    parent = get_object_or_404(TerritorialUnit, pk=int(raw))

    gmina_with_stations = Exists(
        PollingStation.objects.filter(
            precinct__parent_id=OuterRef("pk"),
            precinct__isnull=False,
        )
    )
    county_with_stations = Exists(
        PollingStation.objects.filter(
            precinct__parent__parent_id=OuterRef("pk"),
            precinct__isnull=False,
        )
    )

    if parent.kind == TerritorialUnit.Kind.VOIVODESHIP:
        counties = list(
            TerritorialUnit.objects.filter(
                parent=parent, kind=TerritorialUnit.Kind.COUNTY
            )
            .annotate(_has_stations=county_with_stations)
            .filter(_has_stations=True)
            .order_by("name")
            .only("id", "name", "kind")
        )
        direct_gminy = list(
            TerritorialUnit.objects.filter(
                parent=parent, kind=TerritorialUnit.Kind.MUNICIPALITY
            )
            .annotate(_has_stations=gmina_with_stations)
            .filter(_has_stations=True)
            .order_by("name")
            .only("id", "name", "kind")
        )
        children = [_unit_payload(u, has_children=True) for u in counties]
        children.extend(_unit_payload(u, has_children=False) for u in direct_gminy)
    elif parent.kind == TerritorialUnit.Kind.COUNTY:
        qs = (
            TerritorialUnit.objects.filter(
                parent=parent, kind=TerritorialUnit.Kind.MUNICIPALITY
            )
            .annotate(_has_stations=gmina_with_stations)
            .filter(_has_stations=True)
            .order_by("name")
            .only("id", "name", "kind")
        )
        children = [_unit_payload(u, has_children=False) for u in qs]
    else:
        children = []

    return JsonResponse({"parent_id": parent.pk, "children": children})


@login_required
@require_GET
def station_unit_stations(request: HttpRequest) -> JsonResponse | HttpResponseBadRequest:
    raw = (request.GET.get("unit_id") or "").strip()
    if not raw.isdigit():
        return HttpResponseBadRequest("unit_id required")
    unit = get_object_or_404(TerritorialUnit, pk=int(raw))

    if unit.kind == TerritorialUnit.Kind.MUNICIPALITY:
        qs = PollingStation.objects.filter(precinct__parent=unit)
    elif unit.kind == TerritorialUnit.Kind.PRECINCT:
        qs = PollingStation.objects.filter(precinct=unit)
    else:
        qs = PollingStation.objects.none()

    qs = qs.order_by("number", "name").only("id", "code", "name", "address", "number")
    profile = get_voter_profile(request.user)
    current_station = _representative_station(
        profile.territorial_unit if profile else None
    )
    current_id = current_station.pk if current_station else None
    stations = [_station_payload(s, current_id=current_id) for s in qs]
    return JsonResponse({"unit_id": unit.pk, "stations": stations})


@login_required
@require_GET
def preview_station_change_api(
    request: HttpRequest,
) -> JsonResponse | HttpResponseBadRequest:
    raw_id = (request.GET.get("station_id") or "").strip()
    if not raw_id.isdigit():
        return HttpResponseBadRequest("station_id required")
    station = get_object_or_404(
        PollingStation.objects.select_related("precinct"), pk=int(raw_id)
    )
    preview = preview_station_change(request.user, station)
    same = bool(
        preview.current_precinct
        and preview.current_precinct.pk == preview.new_precinct.pk
    )
    return JsonResponse(
        {
            "station": {
                "id": station.pk,
                "name": station.name,
                "code": station.code,
                "address": station.address,
            },
            "offices_to_void": [
                {"id": o.pk, "name": str(o)} for o in preview.offices_to_void
            ],
            "offices_to_restore": [
                {"id": o.pk, "name": str(o)} for o in preview.offices_to_restore
            ],
            "same_station": same,
        }
    )


@require_http_methods(["GET", "POST"])
def register(request: HttpRequest) -> HttpResponse:
    from users.forms import RegistrationForm
    from users.services.registration import (
        email_verification_token,
        make_email_uid,
        register_user,
    )

    if request.user.is_authenticated:
        return redirect("dashboard")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = register_user(
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password1"],
        )
        uid = make_email_uid(user)
        token = email_verification_token.make_token(user)
        verify_url = request.build_absolute_uri(
            reverse("verify_email", kwargs={"uidb64": uid, "token": token})
        )
        try:
            send_mail(
                subject="Selectio Positiva — potwierdź rejestrację",
                message=(
                    "Witaj!\n\n"
                    "Kliknij link, aby aktywować konto:\n"
                    f"{verify_url}\n\n"
                    "Jeśli nie zakładałeś konta, zignoruj tę wiadomość.\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception as exc:
            logging.getLogger("apps").exception(
                "Registration email failed (from=%s to=%s): %s",
                settings.DEFAULT_FROM_EMAIL,
                user.email,
                exc,
            )
            user.delete()
            detail = f" ({exc})" if settings.DEBUG else ""
            messages.error(
                request,
                "Nie udało się wysłać emaila aktywacyjnego."
                f"{detail} Sprawdź DEFAULT_FROM_EMAIL / Postfix.",
            )
            return render(request, "registration/register.html", {"form": form})
        messages.success(
            request,
            "Konto utworzone. Sprawdź email i kliknij link aktywacyjny.",
        )
        return redirect("login")

    return render(request, "registration/register.html", {"form": form})


@require_GET
def verify_email(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    from users.services.registration import activate_user_from_token

    user = activate_user_from_token(uidb64=uidb64, token=token)
    if user is None:
        messages.error(request, "Link aktywacyjny jest nieprawidłowy lub wygasł.")
        return redirect("login")
    messages.success(request, "Email potwierdzony. Możesz się zalogować.")
    return redirect("login")


@login_required
@require_http_methods(["GET", "POST"])
def profile(request: HttpRequest) -> HttpResponse:
    from django.contrib.auth import update_session_auth_hash

    from users.forms import ProfileDataForm, ProfilePasswordChangeForm

    profile_obj = get_voter_profile(request.user)
    data_form = ProfileDataForm(request.user)
    password_form = ProfilePasswordChangeForm(user=request.user)

    if request.method == "POST":
        action = request.POST.get("action", "profile")
        if action == "password":
            password_form = ProfilePasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Hasło zostało zmienione.")
                return redirect("profile")
        else:
            data_form = ProfileDataForm(request.user, request.POST)
            if data_form.is_valid():
                data_form.save()
                messages.success(request, "Zapisano dane profilu.")
                return redirect("profile")

    return render(
        request,
        "users/profile.html",
        {
            "profile": profile_obj,
            "data_form": data_form,
            "password_form": password_form,
        },
    )
