"""Cache wyników Schulzego per okręg + frekwencja."""

from __future__ import annotations

import hashlib
from typing import Any

from django.db.models import Count
from django.utils import timezone

from elections.models import (
    Ballot,
    Candidate,
    ElectionResultCache,
    ElectoralDistrict,
    Office,
    VoterProfile,
)
from elections.services.schulze import SchulzeResult, compute_schulze
from geo.models import TerritorialUnit


def _descendant_unit_ids(unit: TerritorialUnit) -> set[int]:
    ids: set[int] = {unit.pk}
    stack = list(unit.children.all())
    while stack:
        node = stack.pop()
        if node.pk in ids:
            continue
        ids.add(node.pk)
        stack.extend(node.children.all())
    return ids


def eligible_voter_count(district: ElectoralDistrict) -> int:
    unit_ids = _descendant_unit_ids(district.territorial_unit)
    return VoterProfile.objects.filter(
        polling_station__territorial_unit_id__in=unit_ids
    ).count()


def ballot_fingerprint(district: ElectoralDistrict) -> str:
    rows = (
        Ballot.objects.filter(district=district, is_voided=False)
        .order_by("id")
        .values_list("id", "updated_at", "ranked_candidate_ids", "is_voided")
    )
    h = hashlib.sha256()
    for pk, updated, ranked, is_voided in rows:
        h.update(f"{pk}:{updated.isoformat()}:{ranked}:{is_voided}".encode())
    h.update(f"|seats:{district.seats_count}|candidates:{district.pk}".encode())
    cand = Candidate.objects.filter(district=district, is_active=True).order_by("id")
    for c in cand:
        h.update(f",{c.pk}".encode())
    return h.hexdigest()


def compute_district_schulze(district: ElectoralDistrict) -> SchulzeResult:
    candidates = list(
        Candidate.objects.filter(district=district, is_active=True).order_by(
            "display_order", "name"
        )
    )
    candidate_ids = [c.pk for c in candidates]
    rankings = list(
        Ballot.objects.filter(district=district, is_voided=False).values_list(
            "ranked_candidate_ids", flat=True
        )
    )
    active = set(candidate_ids)
    cleaned = [[cid for cid in ranking if cid in active] for ranking in rankings]
    return compute_schulze(
        candidate_ids, cleaned, seats_count=district.seats_count
    )


# Alias kompatybilności
compute_office_schulze = compute_district_schulze


def build_result_payload(
    district: ElectoralDistrict, result: SchulzeResult
) -> dict[str, Any]:
    candidates = {
        c.pk: c
        for c in Candidate.objects.filter(district=district, is_active=True)
    }
    eligible = eligible_voter_count(district)
    ballots = result.ballot_count
    turnout_pct = round((ballots / eligible) * 100, 1) if eligible else 0.0

    ranking_rows = []
    for row in result.ranking:
        cand = candidates.get(row.candidate_id)
        if cand is None:
            continue
        if row.is_tied_at_threshold:
            status = "Remis na progu mandatowym"
        elif row.is_elected:
            status = "Wybrany"
        else:
            status = "Nieobsadzony"
        ranking_rows.append(
            {
                "candidate_id": row.candidate_id,
                "name": cand.name,
                "place": row.place,
                "schulze_wins": row.schulze_wins,
                "first_preferences": row.first_preferences,
                "is_winner": row.is_elected,
                "is_elected": row.is_elected,
                "is_tied_winner": row.is_tied_winner,
                "is_tied_at_threshold": row.is_tied_at_threshold,
                "status": status,
            }
        )

    labels = {
        str(cid): candidates[cid].name
        for cid in result.candidate_ids
        if cid in candidates
    }
    elected_rows = [r for r in ranking_rows if r["is_elected"]]
    remaining_rows = [r for r in ranking_rows if not r["is_elected"]]

    return {
        "district": {
            "id": district.pk,
            "slug": district.slug,
            "name": district.name,
            "seats_count": district.seats_count,
            "territorial_unit_id": district.territorial_unit_id,
        },
        "office": {
            "id": district.office_id,
            "slug": district.office.slug,
            "name": district.office.name,
        },
        "schulze": result.to_payload(),
        "ranking": ranking_rows,
        "elected": elected_rows,
        "remaining": remaining_rows,
        "candidate_labels": labels,
        "turnout": {
            "ballots": ballots,
            "eligible_voters": eligible,
            "percent": turnout_pct,
        },
        "computed_at": timezone.now().isoformat(),
    }


def invalidate_district_results(district: ElectoralDistrict | int) -> None:
    district_id = district.pk if isinstance(district, ElectoralDistrict) else district
    ElectionResultCache.objects.filter(district_id=district_id).update(is_stale=True)


invalidate_office_results = invalidate_district_results


def recompute_district_results(district: ElectoralDistrict) -> ElectionResultCache:
    result = compute_district_schulze(district)
    payload = build_result_payload(district, result)
    fingerprint = ballot_fingerprint(district)
    cache, _ = ElectionResultCache.objects.update_or_create(
        district=district,
        defaults={
            "payload": payload,
            "ballot_count": result.ballot_count,
            "fingerprint": fingerprint,
            "is_stale": False,
            "computed_at": timezone.now(),
        },
    )
    return cache


recompute_office_results = recompute_district_results


def get_cached_result(
    district: ElectoralDistrict, *, recompute_if_stale: bool = True
) -> dict[str, Any]:
    cache = (
        ElectionResultCache.objects.filter(district=district)
        .only("payload", "is_stale", "fingerprint", "computed_at")
        .first()
    )
    current_fp = ballot_fingerprint(district)
    needs = cache is None or cache.is_stale or cache.fingerprint != current_fp
    if needs and recompute_if_stale:
        cache = recompute_district_results(district)
    elif cache is None:
        return build_result_payload(district, compute_district_schulze(district))
    return cache.payload


def recompute_all_results() -> int:
    count = 0
    for district in ElectoralDistrict.objects.select_related(
        "office", "territorial_unit"
    ).iterator():
        recompute_district_results(district)
        count += 1
    return count


def districts_for_filter(
    *,
    kind: str | None = None,
    unit_id: int | None = None,
    office_id: int | None = None,
    office_slug: str | None = None,
) -> list[ElectoralDistrict]:
    qs = ElectoralDistrict.objects.select_related("office", "territorial_unit").annotate(
        _ballot_count=Count("ballots")
    )
    if kind:
        qs = qs.filter(territorial_unit__kind=kind)
    if unit_id:
        qs = qs.filter(territorial_unit_id=unit_id)
    if office_id:
        qs = qs.filter(office_id=office_id)
    if office_slug:
        qs = qs.filter(office__slug=office_slug)
    return list(qs.order_by("office__display_order", "display_order", "name"))


def offices_for_unit_filter(
    *,
    kind: str | None = None,
    unit_id: int | None = None,
) -> list[Office]:
    """Urzędy mające okręgi w danym filtrze terytorialnym."""
    district_qs = ElectoralDistrict.objects.all()
    if kind:
        district_qs = district_qs.filter(territorial_unit__kind=kind)
    if unit_id:
        district_qs = district_qs.filter(territorial_unit_id=unit_id)
    office_ids = district_qs.values_list("office_id", flat=True).distinct()
    return list(
        Office.objects.filter(pk__in=office_ids).order_by("display_order", "name")
    )
