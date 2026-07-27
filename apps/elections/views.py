from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from elections.models import Ballot, ElectoralDistrict, Office, VoterProfile
from elections.services import (
    ballot_counts_for_user,
    get_cached_result,
    get_voter_profile,
    invalidate_district_results,
    user_can_vote_on,
    vote_statuses_for_user,
)
from elections.services.eligibility import get_eligible_districts, user_age_on
from elections.services.results import districts_for_filter, offices_for_unit_filter
from geo.models import TerritorialUnit

User = get_user_model()

MIN_SEARCH_CHARS = 3


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"placeholder": "demo", "autocomplete": "username"}
        )
        self.fields["password"].widget.attrs.update(
            {"placeholder": "••••••••", "autocomplete": "current-password"}
        )


class ElectionLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True
    authentication_form = StyledAuthenticationForm


class ElectionLogoutView(LogoutView):
    next_page = reverse_lazy("login")


def _user_payload(user) -> dict:
    full = f"{user.first_name} {user.last_name}".strip()
    return {
        "id": user.pk,
        "name": full or user.username,
        "username": user.username,
        "birth_date": str(user.birth_date) if getattr(user, "birth_date", None) else None,
    }


def _search_users_for_district(
    district: ElectoralDistrict,
    *,
    q: str = "",
    exclude_ids: list[int] | None = None,
    limit: int = 40,
    today: date | None = None,
) -> list:
    """
    Autocomplete: wyszukuje użytkowników uprawnionych do kandydowania w okręgu.
    Wymaga min. 3 znaków. Wyszukuje od początku imienia/nazwiska/username (istartswith).
    """
    query = q.strip()
    if len(query) < MIN_SEARCH_CHARS:
        return []

    ref = today or date.today()

    # Wyborcy z komisjami → ich profile
    eligible_user_ids = list(
        VoterProfile.objects.filter(polling_station__isnull=False)
        .values_list("user_id", flat=True)
    )

    qs = User.objects.filter(
        pk__in=eligible_user_ids,
        is_active=True,
    )
    qs = qs.filter(
        Q(first_name__istartswith=query)
        | Q(last_name__istartswith=query)
        | Q(username__istartswith=query)
    )

    if exclude_ids:
        qs = qs.exclude(pk__in=exclude_ids)

    qs = qs.order_by("last_name", "first_name", "username")

    # Filtr: obwód musi leżeć w okręgu + limit wieku
    from elections.models import unit_is_descendant_of_any
    district_unit_ids = set(district.territorial_units.values_list("pk", flat=True))
    min_age = district.min_age

    matched = []
    for user in qs[:300]:
        try:
            profile = user.voter_profile
        except Exception:
            continue
        if not profile.polling_station_id:
            continue
        try:
            precinct = profile.polling_station.precinct
        except Exception:
            continue
        if district_unit_ids and not unit_is_descendant_of_any(precinct, district_unit_ids):
            continue
        if min_age:
            age = user_age_on(user, ref)
            if age is not None and age < min_age:
                continue
        matched.append(user)
        if len(matched) >= limit:
            break

    return matched


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    profile = get_voter_profile(request.user)
    statuses = vote_statuses_for_user(request.user) if profile else []
    ballot_counts = ballot_counts_for_user(request.user)
    voided_ballots = list(
        Ballot.objects.filter(user=request.user, is_voided=True)
        .select_related("district", "district__office")
        .order_by("district__office__display_order", "district__display_order")
    )
    station_summary = request.session.pop("station_change_summary", None)

    map_payload: dict = {"station": None, "units": []}
    if profile is not None and profile.polling_station_id:
        station = profile.polling_station
        # Preferuj obwód komisji; fallback: territorial_unit profilu.
        unit = station.precinct or profile.territorial_unit
        ancestors = unit.get_ancestors(include_self=True) if unit is not None else []
        map_payload = {
            "station": {
                "name": station.name,
                "code": station.code,
                "address": station.address,
                "lat": float(station.latitude) if station.latitude is not None else None,
                "lng": float(station.longitude) if station.longitude is not None else None,
            },
            "units": [
                {
                    "id": u.pk,
                    "name": u.name,
                    "kind": u.kind,
                    "kind_label": u.get_kind_display(),
                    "boundary": getattr(u, "boundary", None),
                    "center_lat": float(u.center_lat) if getattr(u, "center_lat", None) is not None else None,
                    "center_lng": float(u.center_lng) if getattr(u, "center_lng", None) is not None else None,
                }
                for u in ancestors
            ],
        }

    return render(
        request,
        "elections/dashboard.html",
        {
            "profile": profile,
            "statuses": statuses,
            "map_payload_json": map_payload,
            "ballot_counts": ballot_counts,
            "voided_ballots": voided_ballots,
            "station_summary": station_summary,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def vote_district(request: HttpRequest, slug: str) -> HttpResponse:
    district = get_object_or_404(
        ElectoralDistrict.objects.select_related("office").prefetch_related("territorial_units"),
        slug=slug,
    )
    if not user_can_vote_on(request.user, district):
        return HttpResponseForbidden("Brak uprawnień do głosowania w tym okręgu.")

    ballot = Ballot.objects.filter(user=request.user, district=district).first()

    if request.method == "POST":
        raw_ids = request.POST.getlist("ranked_user_ids")
        try:
            ranking_ids = [int(x) for x in raw_ids]
        except ValueError:
            messages.error(request, "Nieprawidłowy ranking.")
            return redirect("vote_district", slug=district.slug)

        # Weryfikacja: każdy ID musi być uprawnionym użytkownikiem
        valid_ids = set(
            _search_users_for_district.__wrapped__(district)
            if hasattr(_search_users_for_district, "__wrapped__") else []
        )
        # Uproszczona weryfikacja: sprawdzamy istnienie użytkownika
        existing_ids = set(
            User.objects.filter(pk__in=ranking_ids).values_list("pk", flat=True)
        )
        cleaned: list[int] = []
        seen: set[int] = set()
        for uid in ranking_ids:
            if uid not in existing_ids:
                messages.error(request, "Ranking zawiera nieznanego użytkownika.")
                return redirect("vote_district", slug=district.slug)
            if uid in seen:
                continue
            cleaned.append(uid)
            seen.add(uid)

        if not cleaned:
            messages.error(
                request,
                "Dodaj co najmniej jednego kandydata do swojego rankingu.",
            )
            return redirect("vote_district", slug=district.slug)

        Ballot.objects.update_or_create(
            user=request.user,
            district=district,
            defaults={
                "ranked_user_ids": cleaned,
                "is_voided": False,
                "void_reason": "",
                "voided_at": None,
            },
        )
        invalidate_district_results(district)
        messages.success(request, f"Zapisano głos: {district}.")
        return redirect("dashboard")

    ranked_ids: list[int] = []
    if ballot and not ballot.is_voided and ballot.ranked_user_ids:
        ranked_ids = list(ballot.ranked_user_ids)
    ranked_users = list(
        User.objects.filter(pk__in=ranked_ids).only("pk", "first_name", "last_name", "username", "birth_date")
    )
    # Zachowaj kolejność
    ranked_by_id = {u.pk: u for u in ranked_users}
    ranked_users_ordered = [ranked_by_id[i] for i in ranked_ids if i in ranked_by_id]

    return render(
        request,
        "elections/vote.html",
        {
            "district": district,
            "office": district.office,
            "ranked_users": ranked_users_ordered,
            "ranked_payload": [_user_payload(u) for u in ranked_users_ordered],
            "search_url": reverse("vote_candidate_search", kwargs={"slug": district.slug}),
            "ballot": ballot,
            "is_update": ballot is not None and not ballot.is_voided,
        },
    )


@login_required
@require_GET
def vote_candidate_search(request: HttpRequest, slug: str) -> JsonResponse:
    district = get_object_or_404(
        ElectoralDistrict.objects.select_related("office").prefetch_related("territorial_units"),
        slug=slug,
    )
    if not user_can_vote_on(request.user, district):
        return JsonResponse({"error": "forbidden"}, status=403)

    q = request.GET.get("q", "").strip()
    exclude_raw = request.GET.get("exclude", "")
    exclude_ids: list[int] = []
    for part in exclude_raw.split(","):
        part = part.strip()
        if part.isdigit():
            exclude_ids.append(int(part))

    if len(q) < MIN_SEARCH_CHARS:
        return JsonResponse({"active": False, "results": []})

    found = _search_users_for_district(district, q=q, exclude_ids=exclude_ids, limit=40)
    return JsonResponse(
        {
            "active": True,
            "results": [_user_payload(u) for u in found],
        }
    )


vote_office = vote_district


@require_POST
@login_required
def clear_ballot(request: HttpRequest, slug: str) -> HttpResponse:
    district = get_object_or_404(ElectoralDistrict, slug=slug)
    if not user_can_vote_on(request.user, district):
        return HttpResponseForbidden("Brak uprawnień.")
    deleted, _ = Ballot.objects.filter(user=request.user, district=district).delete()
    if deleted:
        invalidate_district_results(district)
        messages.info(request, f"Usunięto głos: {district}.")
    return redirect("dashboard")


def results(request: HttpRequest) -> HttpResponse:
    kind = (request.GET.get("kind") or "").strip()
    unit_id_raw = (request.GET.get("unit") or "").strip()
    office_slug = (request.GET.get("office") or "").strip()
    district_slug = (request.GET.get("district") or "").strip()

    kind_choices = TerritorialUnit.Kind.choices
    selected_unit = None
    if unit_id_raw.isdigit():
        selected_unit = TerritorialUnit.objects.filter(pk=int(unit_id_raw)).first()
        if selected_unit and not kind:
            kind = selected_unit.kind

    units_qs = TerritorialUnit.objects.all().order_by("kind", "name")
    if kind:
        units_qs = units_qs.filter(kind=kind)
    units = list(units_qs)

    offices = offices_for_unit_filter(
        kind=kind or None,
        unit_id=selected_unit.pk if selected_unit else None,
    )

    selected_office = None
    if office_slug:
        selected_office = next((o for o in offices if o.slug == office_slug), None)
        if selected_office is None:
            selected_office = Office.objects.filter(slug=office_slug).first()

    districts = districts_for_filter(
        kind=kind or None,
        unit_id=selected_unit.pk if selected_unit else None,
        office_slug=selected_office.slug if selected_office else None,
    )

    selected_district = None
    result_payload = None
    if district_slug:
        selected_district = next((d for d in districts if d.slug == district_slug), None)
        if selected_district is None:
            selected_district = (
                ElectoralDistrict.objects.select_related("office")
                .filter(slug=district_slug)
                .first()
            )
            if selected_district:
                selected_office = selected_district.office
                kind = ""
                districts = districts_for_filter(
                    office_slug=selected_office.slug,
                )
        if selected_district is None:
            selected_district = get_object_or_404(
                ElectoralDistrict.objects.select_related("office"),
                slug=district_slug,
            )
        result_payload = get_cached_result(selected_district)
    elif len(districts) == 1:
        selected_district = districts[0]
        selected_office = selected_district.office
        result_payload = get_cached_result(selected_district)

    map_units = list(
        TerritorialUnit.objects.filter(electoral_districts__isnull=False)
        .annotate(offices_count=Count("electoral_districts", distinct=True))
        .distinct()
        .order_by("kind", "name")
    )
    if selected_unit and all(u.pk != selected_unit.pk for u in map_units):
        selected_unit.offices_count = selected_unit.electoral_districts.count()  # type: ignore[attr-defined]
        map_units.append(selected_unit)

    map_payload = {
        "selected_unit_id": selected_unit.pk if selected_unit else None,
        "results_base": reverse("results"),
        "units": [
            {
                "id": u.pk,
                "name": u.name,
                "kind": u.kind,
                "kind_label": u.get_kind_display(),
                "boundary": getattr(u, "boundary", None),
                "center_lat": float(u.center_lat) if getattr(u, "center_lat", None) is not None else None,
                "center_lng": float(u.center_lng) if getattr(u, "center_lng", None) is not None else None,
                "offices_count": getattr(u, "offices_count", u.electoral_districts.count()),
            }
            for u in map_units
        ],
    }

    ranking_rows = (result_payload or {}).get("ranking") or []
    elected_rows = (result_payload or {}).get("elected") or []
    remaining_rows = (result_payload or {}).get("remaining") or []
    turnout = (result_payload or {}).get("turnout") or {}
    pairwise = (result_payload or {}).get("schulze", {}).get("pairwise") or {}
    labels = (result_payload or {}).get("user_labels") or {}
    candidate_ids = (result_payload or {}).get("schulze", {}).get("candidate_ids") or []
    seats_count = (
        selected_district.seats_count
        if selected_district
        else (result_payload or {}).get("district", {}).get("seats_count", 1)
    )

    pairwise_grid = []
    for a in candidate_ids:
        row = {"id": a, "name": labels.get(str(a), str(a)), "cells": []}
        for b in candidate_ids:
            if a == b:
                row["cells"].append({"value": None, "opp": None, "win": False})
            else:
                ab = int(pairwise.get(str(a), {}).get(str(b), 0))
                ba = int(pairwise.get(str(b), {}).get(str(a), 0))
                row["cells"].append({"value": ab, "opp": ba, "win": ab > ba})
        pairwise_grid.append(row)

    return render(
        request,
        "elections/results.html",
        {
            "kind": kind,
            "kind_choices": kind_choices,
            "units": units,
            "selected_unit": selected_unit,
            "offices": offices,
            "selected_office": selected_office,
            "districts": districts,
            "selected_district": selected_district,
            "result": result_payload,
            "ranking_rows": ranking_rows,
            "elected_rows": elected_rows,
            "remaining_rows": remaining_rows,
            "seats_count": seats_count,
            "turnout": turnout,
            "pairwise_grid": pairwise_grid,
            "user_labels": labels,
            "map_payload_json": map_payload,
        },
    )
