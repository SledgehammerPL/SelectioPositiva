from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from elections.services import ballot_counts_for_user, get_voter_profile
from geo.models import PollingStation, TerritorialUnit
from users.services.station_change import (
    change_user_polling_station,
    preview_station_change,
)


def _station_tree_payload() -> list[dict]:
    """Drzewo województwo → jednostki z komisjami → komisje (pod kaskadowe selecty)."""
    voivodeships = TerritorialUnit.objects.filter(
        kind=TerritorialUnit.Kind.VOIVODESHIP
    ).order_by("name")
    stations = PollingStation.objects.select_related("territorial_unit").order_by("name")

    tree: dict[int, dict] = {}
    for v in voivodeships:
        tree[v.pk] = {
            "id": v.pk,
            "name": v.name,
            "units": {},
        }

    for station in stations:
        unit = station.territorial_unit
        ancestors = unit.get_ancestors(include_self=True)
        voiv = next(
            (a for a in ancestors if a.kind == TerritorialUnit.Kind.VOIVODESHIP),
            None,
        )
        if voiv is None or voiv.pk not in tree:
            continue
        units = tree[voiv.pk]["units"]
        if unit.pk not in units:
            units[unit.pk] = {
                "id": unit.pk,
                "name": f"{unit.get_kind_display()}: {unit.name}",
                "stations": [],
            }
        units[unit.pk]["stations"].append(
            {
                "id": station.pk,
                "code": station.code,
                "name": station.name,
                "address": station.address,
                "label": f"{station.code} — {station.name}",
            }
        )

    result = []
    for v in tree.values():
        units_list = sorted(v["units"].values(), key=lambda u: u["name"])
        if not units_list:
            continue
        result.append(
            {
                "id": v["id"],
                "name": v["name"],
                "units": units_list,
            }
        )
    return result


@login_required
@require_http_methods(["GET", "POST"])
def change_station(request: HttpRequest) -> HttpResponse:
    profile = get_voter_profile(request.user)
    tree = _station_tree_payload()

    if request.method == "POST":
        raw_id = request.POST.get("station_id", "").strip()
        if not raw_id.isdigit():
            messages.error(request, "Wybierz komisję wyborczą.")
            return redirect("change_station")
        new_station = get_object_or_404(PollingStation, pk=int(raw_id))
        if profile and profile.polling_station_id == new_station.pk:
            messages.info(request, "To już Twoja aktualna komisja.")
            return redirect("dashboard")

        result = change_user_polling_station(request.user, new_station)
        request.session["station_change_summary"] = {
            "previous": str(result.previous_station),
            "new": str(result.new_station),
            "active": result.active_ballots,
            "voided": result.voided_ballots,
            "voided_offices": [str(d) for d in result.voided_districts],
            "restored_offices": [str(d) for d in result.restored_districts],
        }
        messages.success(
            request,
            f"Zmieniono komisję na {result.new_station.name}. "
            f"Głosy aktywne: {result.active_ballots}. "
            f"Głosy zawieszone: {result.voided_ballots}.",
        )
        return redirect("dashboard")

    counts = ballot_counts_for_user(request.user)
    return render(
        request,
        "users/change_station.html",
        {
            "profile": profile,
            "station_tree_json": tree,
            "current_station_id": profile.polling_station_id if profile else None,
            "ballot_counts": counts,
        },
    )


@login_required
@require_GET
def preview_station_change_api(request: HttpRequest) -> JsonResponse | HttpResponseBadRequest:
    raw_id = (request.GET.get("station_id") or "").strip()
    if not raw_id.isdigit():
        return HttpResponseBadRequest("station_id required")
    station = get_object_or_404(PollingStation, pk=int(raw_id))
    preview = preview_station_change(request.user, station)
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
            "same_station": bool(
                preview.current_station and preview.current_station.pk == station.pk
            ),
        }
    )
