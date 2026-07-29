from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from elections.forms import CandidateRequestForm
from elections.models import (
    Ballot,
    CandidateRequest,
    ElectoralDistrict,
    _ancestor_of_kind,
    unit_is_descendant_of_any,
)
from elections.services import (
    ballot_counts_for_user,
    get_cached_result,
    get_voter_profile,
    invalidate_district_results,
    user_can_vote_on,
    vote_statuses_for_user,
)
from elections.services.eligibility import (
    district_units_at_level,
    get_eligible_districts,
    user_age_on,
    user_may_run_in_district,
)
from geo.models import TerritorialUnit
from users.forms import EmailAuthenticationForm

User = get_user_model()

MIN_SEARCH_CHARS = 3


@method_decorator(never_cache, name="dispatch")
@method_decorator(ensure_csrf_cookie, name="dispatch")
class ElectionLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True
    authentication_form = EmailAuthenticationForm


class ElectionLogoutView(LogoutView):
    next_page = reverse_lazy("login")


def _user_payload(user) -> dict:
    birth = None
    second = ""
    municipality = None
    try:
        profile = user.voter_profile
        if profile:
            if profile.birth_date:
                birth = str(profile.birth_date)
            second = profile.second_name or ""
            name = profile.full_name()
            municipality = profile.residence_municipality_name()
        else:
            name = f"{user.first_name} {user.last_name}".strip()
    except Exception:
        name = f"{user.first_name} {user.last_name}".strip()
    return {
        "id": user.pk,
        "name": name or user.email or f"#{user.pk}",
        "birth_date": birth,
        "second_name": second,
        "municipality": municipality,
    }


def _search_users_for_district(
    district: ElectoralDistrict,
    *,
    first_name: str = "",
    second_name: str = "",
    last_name: str = "",
    birth_date: str = "",
    exclude_ids: list[int] | None = None,
    limit: int = 40,
    today: date | None = None,
) -> list:
    """
    Autocomplete: wyszukuje użytkowników uprawnionych do kandydowania w okręgu.

    Wystarczy JEDNO wypełnione pole (min. 3 znaki) albo data urodzenia.
    Kolejne pola zawężają wynik (AND).
    """
    first = first_name.strip()
    second = second_name.strip()
    last = last_name.strip()
    birth = birth_date.strip()
    has_name_filter = (
        len(first) >= MIN_SEARCH_CHARS
        or len(second) >= MIN_SEARCH_CHARS
        or len(last) >= MIN_SEARCH_CHARS
    )
    if not has_name_filter and not birth:
        return []

    ref = today or date.today()
    office = district.office
    level = office.candidacy_level if office is not None else None
    min_age = office.min_age if office is not None else 0
    # Poziom krajowy: każdy z jednostką może kandydować — bez per-user tree walk.
    country_wide = bool(level and level.slug == "country")
    allowed_at_level: set[int] | None = None
    if not country_wide:
        if level is not None:
            allowed_at_level = district_units_at_level(district, level.slug)
        else:
            allowed_at_level = set(
                district.territorial_units.values_list("pk", flat=True)
            )
        if not allowed_at_level:
            return []

    qs = (
        User.objects.filter(
            is_active=True,
            voter_profile__territorial_unit__isnull=False,
        )
        .select_related(
            "voter_profile",
            "voter_profile__territorial_unit",
            "voter_profile__territorial_unit__parent",
            "voter_profile__territorial_unit__parent__parent",
            "voter_profile__territorial_unit__parent__parent__parent",
            "voter_profile__territorial_unit__parent__parent__parent__parent",
        )
    )

    if birth:
        try:
            qs = qs.filter(voter_profile__birth_date=date.fromisoformat(birth))
        except ValueError:
            return []

    if len(first) >= MIN_SEARCH_CHARS:
        qs = qs.filter(first_name__istartswith=first)
    if len(second) >= MIN_SEARCH_CHARS:
        qs = qs.filter(voter_profile__second_name__istartswith=second)
    if len(last) >= MIN_SEARCH_CHARS:
        qs = qs.filter(last_name__istartswith=last)

    if exclude_ids:
        qs = qs.exclude(pk__in=exclude_ids)

    qs = qs.order_by("last_name", "first_name", "pk")

    matched = []
    # Nadmiarowy bufor gdy część odpadnie na wieku / terytorium.
    scan_cap = limit if country_wide else max(limit * 25, 200)
    for user in qs[:scan_cap]:
        try:
            profile = user.voter_profile
        except Exception:
            continue
        unit = profile.territorial_unit
        if unit is None:
            continue

        if not country_wide:
            assert allowed_at_level is not None
            if level is not None:
                candidate_unit = _ancestor_of_kind(unit, level.slug)
                if candidate_unit is None or candidate_unit.pk not in allowed_at_level:
                    continue
            elif not unit_is_descendant_of_any(unit, allowed_at_level):
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

    display_station = None
    if profile is not None and profile.territorial_unit_id:
        unit = profile.territorial_unit
        if unit.kind == TerritorialUnit.Kind.PRECINCT:
            from geo.models import PollingStation

            display_station = (
                PollingStation.objects.filter(precinct=unit)
                .order_by("number", "pk")
                .first()
            )

    return render(
        request,
        "elections/dashboard.html",
        {
            "profile": profile,
            "display_station": display_station,
            "statuses": statuses,
            "ballot_counts": ballot_counts,
            "voided_ballots": voided_ballots,
            "station_summary": station_summary,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def vote_district(request: HttpRequest, slug: str) -> HttpResponse:
    district = get_object_or_404(
        ElectoralDistrict.objects.select_related("office", "office__candidacy_level").prefetch_related("territorial_units"),
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
        User.objects.filter(pk__in=ranked_ids).select_related("voter_profile")
    )
    # Zachowaj kolejność
    ranked_by_id = {u.pk: u for u in ranked_users}
    ranked_users_ordered = [ranked_by_id[i] for i in ranked_ids if i in ranked_by_id]

    profile = get_voter_profile(request.user)
    can_self_nominate = False
    if profile and profile.territorial_unit_id:
        can_self_nominate = user_may_run_in_district(
            profile.territorial_unit, district
        )
        min_age = district.office.min_age if district.office_id else 0
        if can_self_nominate and min_age:
            age = user_age_on(request.user, date.today())
            if age is not None and age < min_age:
                can_self_nominate = False

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
            "candidate_request_form": CandidateRequestForm(),
            "can_self_nominate": can_self_nominate,
            "self_payload": _user_payload(request.user),
        },
    )


@login_required
@require_POST
def request_candidate(request: HttpRequest, slug: str) -> HttpResponse:
    district = get_object_or_404(
        ElectoralDistrict.objects.select_related("office"),
        slug=slug,
    )
    if not user_can_vote_on(request.user, district):
        return HttpResponseForbidden("Brak uprawnień.")

    form = CandidateRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Sprawdź dane prośby o kandydata.")
        return redirect("vote_district", slug=district.slug)

    pending = CandidateRequest.objects.filter(
        district=district,
        requested_by=request.user,
        first_name__iexact=form.cleaned_data["first_name"].strip(),
        last_name__iexact=form.cleaned_data["last_name"].strip(),
        birth_date=form.cleaned_data["birth_date"],
        status=CandidateRequest.Status.PENDING,
    ).exists()
    if pending:
        messages.info(
            request,
            "Taka prośba już oczekuje na rozpatrzenie przez administratora.",
        )
        return redirect("vote_district", slug=district.slug)

    CandidateRequest.objects.create(
        district=district,
        requested_by=request.user,
        first_name=form.cleaned_data["first_name"].strip(),
        last_name=form.cleaned_data["last_name"].strip(),
        birth_date=form.cleaned_data["birth_date"],
        note=form.cleaned_data.get("note") or "",
    )
    messages.success(
        request,
        "Wysłano prośbę o dodanie kandydata. Administrator rozpatrzy zgłoszenie.",
    )
    return redirect("vote_district", slug=district.slug)


@login_required
@require_GET
def vote_candidate_search(request: HttpRequest, slug: str) -> JsonResponse:
    district = get_object_or_404(
        ElectoralDistrict.objects.select_related("office", "office__candidacy_level").prefetch_related("territorial_units"),
        slug=slug,
    )
    if not user_can_vote_on(request.user, district):
        return JsonResponse({"error": "forbidden"}, status=403)

    first = request.GET.get("first_name", "").strip()
    second = request.GET.get("second_name", "").strip()
    last = request.GET.get("last_name", "").strip()
    birth = request.GET.get("birth_date", "").strip()
    exclude_raw = request.GET.get("exclude", "")
    exclude_ids: list[int] = []
    for part in exclude_raw.split(","):
        part = part.strip()
        if part.isdigit():
            exclude_ids.append(int(part))

    has_name = (
        len(first) >= MIN_SEARCH_CHARS
        or len(second) >= MIN_SEARCH_CHARS
        or len(last) >= MIN_SEARCH_CHARS
    )
    if not has_name and not birth:
        return JsonResponse({"active": False, "results": []})

    found = _search_users_for_district(
        district,
        first_name=first,
        second_name=second,
        last_name=last,
        birth_date=birth,
        exclude_ids=exclude_ids,
        limit=40,
    )
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


@login_required
def results(request: HttpRequest) -> HttpResponse:
    """Wyniki Schulzego wyłącznie dla okręgów dostępnych zalogowanemu użytkownikowi."""
    profile = get_voter_profile(request.user)
    districts = list(get_eligible_districts(request.user))
    district_by_slug = {d.slug: d for d in districts}

    district_slug = (request.GET.get("district") or "").strip()
    selected_district = district_by_slug.get(district_slug)
    if selected_district is None and len(districts) == 1:
        selected_district = districts[0]

    result_payload = None
    if selected_district is not None:
        result_payload = get_cached_result(selected_district)

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
            "profile": profile,
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
        },
    )
