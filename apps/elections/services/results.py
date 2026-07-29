"""Cache wyników Schulzego per okręg + frekwencja."""

from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from elections.models import (
    Ballot,
    ElectionResultCache,
    ElectoralDistrict,
    Office,
    VoterProfile,
)
from elections.services.schulze import SchulzeResult, compute_schulze
from geo.models import TerritorialUnit

User = get_user_model()


def eligible_voter_count(district: ElectoralDistrict) -> int:
    """
    Liczba wyborców uprawnionych do głosowania w okręgu.

    Iteruje profile z obwodem (jest ich mało względem drzewa PKW) i sprawdza,
    czy obwód leży w poddrzewie jednostek okręgu — zamiast BFS po wszystkich
    obwodach województwa.
    """
    from elections.models import unit_is_descendant_of_any

    district_unit_ids = set(
        district.territorial_units.values_list("pk", flat=True)
    )
    if not district_unit_ids:
        return 0

    profiles = VoterProfile.objects.filter(
        territorial_unit__kind=TerritorialUnit.Kind.PRECINCT,
    ).select_related(
        "territorial_unit",
        "territorial_unit__parent",
        "territorial_unit__parent__parent",
        "territorial_unit__parent__parent__parent",
        "territorial_unit__parent__parent__parent__parent",
    )
    return sum(
        1
        for profile in profiles
        if profile.territorial_unit_id
        and unit_is_descendant_of_any(profile.territorial_unit, district_unit_ids)
    )


def _eligible_user_ids_for_district(district: ElectoralDistrict) -> list[int]:
    """
    Pula kandydatów Schulzego dla okręgu.

    Bierzemy wyłącznie użytkowników obecnych na kartach do głosowania
    (rankingach) — nie skanujemy wszystkich wyborców w kraju.
    Osoby nigdy nieumieszczone w rankingu nie wchodzą do macierzy pairwise.
    """
    ids: set[int] = set()
    for ranked in Ballot.objects.filter(
        district=district, is_voided=False
    ).values_list("ranked_user_ids", flat=True):
        if ranked:
            ids.update(int(x) for x in ranked)
    return sorted(ids)

def ballot_fingerprint(district: ElectoralDistrict) -> str:
    rows = (
        Ballot.objects.filter(district=district, is_voided=False)
        .order_by("id")
        .values_list("id", "updated_at", "ranked_user_ids", "is_voided")
    )
    h = hashlib.sha256()
    for pk, updated, ranked, is_voided in rows:
        h.update(f"{pk}:{updated.isoformat()}:{ranked}:{is_voided}".encode())
    h.update(f"|seats:{district.seats_count}|district:{district.pk}".encode())
    return h.hexdigest()


def compute_district_schulze(district: ElectoralDistrict) -> SchulzeResult:
    user_ids = _eligible_user_ids_for_district(district)
    rankings = list(
        Ballot.objects.filter(district=district, is_voided=False).values_list(
            "ranked_user_ids", flat=True
        )
    )
    active = set(user_ids)
    cleaned = [[uid for uid in ranking if uid in active] for ranking in rankings]
    return compute_schulze(user_ids, cleaned, seats_count=district.seats_count)


compute_office_schulze = compute_district_schulze


def build_result_payload(
    district: ElectoralDistrict, result: SchulzeResult
) -> dict[str, Any]:
    user_ids = result.candidate_ids
    users = {
        u.pk: u
        for u in User.objects.filter(pk__in=user_ids).select_related("voter_profile")
    }

    def user_label(uid: int) -> str:
        u = users.get(uid)
        if u is None:
            return str(uid)
        try:
            return u.voter_profile.full_name()
        except Exception:
            full = f"{u.first_name} {u.last_name}".strip()
            return full or u.email or str(uid)

    eligible = eligible_voter_count(district)
    ballots = result.ballot_count
    turnout_pct = round((ballots / eligible) * 100, 1) if eligible else 0.0

    ranking_rows = []
    for row in result.ranking:
        uid = row.candidate_id
        if row.is_tied_at_threshold:
            status = "Remis na progu mandatowym"
        elif row.is_elected:
            status = "Wybrany"
        else:
            status = "Nieobsadzony"
        ranking_rows.append(
            {
                "user_id": uid,
                "name": user_label(uid),
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

    labels = {str(uid): user_label(uid) for uid in user_ids}
    elected_rows = [r for r in ranking_rows if r["is_elected"]]
    remaining_rows = [r for r in ranking_rows if not r["is_elected"]]

    return {
        "district": {
            "id": district.pk,
            "slug": district.slug,
            "name": district.name,
            "seats_count": district.seats_count,
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
        "user_labels": labels,
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
    for district in ElectoralDistrict.objects.select_related("office").iterator():
        recompute_district_results(district)
        count += 1
    return count


# Poziom wyników ≠ zawsze candidacy_level (WBP ma candidacy=country, a wybory są gminne).
_RESULT_LEVEL_BY_OFFICE_SLUG: dict[str, str] = {
    "prezydent-rp": TerritorialUnit.Kind.COUNTRY,
    "eurodeputowany": TerritorialUnit.Kind.COUNTRY,
    "posel-sejm": TerritorialUnit.Kind.COUNTRY,
    "senator": TerritorialUnit.Kind.COUNTRY,
    "radny-sejmiku": TerritorialUnit.Kind.VOIVODESHIP,
    "radny-powiatu": TerritorialUnit.Kind.COUNTY,
    "radny-gminy": TerritorialUnit.Kind.MUNICIPALITY,
    "wojt-burmistrz-prezydent": TerritorialUnit.Kind.MUNICIPALITY,
}

_RESULTS_FILTER_KINDS = (
    TerritorialUnit.Kind.COUNTRY,
    TerritorialUnit.Kind.VOIVODESHIP,
    TerritorialUnit.Kind.COUNTY,
    TerritorialUnit.Kind.MUNICIPALITY,
)


def result_level_for_office(office: Office) -> str | None:
    if office.slug in _RESULT_LEVEL_BY_OFFICE_SLUG:
        return _RESULT_LEVEL_BY_OFFICE_SLUG[office.slug]
    if office.candidacy_level_id:
        return office.candidacy_level.slug
    return None


def offices_for_results_level(kind: str) -> list[Office]:
    """Urzędy, których wyniki pokazujemy na danym poziomie hierarchii."""
    slugs = [
        slug for slug, level in _RESULT_LEVEL_BY_OFFICE_SLUG.items() if level == kind
    ]
    if not slugs:
        return list(
            Office.objects.filter(candidacy_level__slug=kind).order_by(
                "display_order", "name"
            )
        )
    return list(
        Office.objects.filter(slug__in=slugs).order_by("display_order", "name")
    )


def _district_covers_unit_q(unit: TerritorialUnit):
    """
    Okręg „należy” do jednostki, gdy ma powiązanie z nią, jej potomkiem
    albo jej przodkiem (do 3 poziomów w dół — kraj→…→obwód).
    """
    from django.db.models import Q

    ancestor_ids = [u.pk for u in unit.get_ancestors(include_self=True)]
    q = Q(territorial_units__pk__in=ancestor_ids)
    q |= Q(territorial_units=unit)
    q |= Q(territorial_units__parent=unit)
    q |= Q(territorial_units__parent__parent=unit)
    q |= Q(territorial_units__parent__parent__parent=unit)
    return q


def districts_for_results_unit(unit: TerritorialUnit) -> list[ElectoralDistrict]:
    """
    Okręgi wyborów na poziomie `unit.kind`, w zasięgu wybranej jednostki.

    Kraj → wybory krajowe (prezydent, Sejm, Senat, PE).
    Województwo → sejmik (okręgi w tym województwie).
    Powiat → rada powiatu / dzielnicy.
    Gmina → rada gminy + wójt/burmistrz/prezydent.
    """
    if unit.kind not in _RESULTS_FILTER_KINDS:
        return []

    offices = offices_for_results_level(unit.kind)
    if not offices:
        return []

    office_ids = [o.pk for o in offices]
    qs = (
        ElectoralDistrict.objects.filter(office_id__in=office_ids)
        .select_related("office", "office__candidacy_level")
        .order_by("office__display_order", "display_order", "name")
    )

    if unit.kind == TerritorialUnit.Kind.COUNTRY:
        # Wszystkie okręgi wyborów krajowych (np. 41 sejmowych).
        return list(qs.distinct())

    return list(qs.filter(_district_covers_unit_q(unit)).distinct())


def group_districts_by_office(
    districts: list[ElectoralDistrict],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    by_office: dict[int, dict[str, Any]] = {}
    for district in districts:
        office = district.office
        bucket = by_office.get(office.pk)
        if bucket is None:
            bucket = {"office": office, "districts": []}
            by_office[office.pk] = bucket
            groups.append(bucket)
        bucket["districts"].append(district)
    return groups


def child_units_for_results(parent: TerritorialUnit) -> list[TerritorialUnit]:
    """Dzieci do selectów wyników (woj. → powiaty + gminy na prawach powiatu)."""
    if parent.kind == TerritorialUnit.Kind.COUNTRY:
        return list(
            TerritorialUnit.objects.filter(
                parent=parent, kind=TerritorialUnit.Kind.VOIVODESHIP
            ).order_by("name")
        )
    if parent.kind == TerritorialUnit.Kind.VOIVODESHIP:
        counties = list(
            TerritorialUnit.objects.filter(
                parent=parent, kind=TerritorialUnit.Kind.COUNTY
            ).order_by("name")
        )
        cities = list(
            TerritorialUnit.objects.filter(
                parent=parent, kind=TerritorialUnit.Kind.MUNICIPALITY
            ).order_by("name")
        )
        return counties + cities
    if parent.kind == TerritorialUnit.Kind.COUNTY:
        return list(
            TerritorialUnit.objects.filter(
                parent=parent, kind=TerritorialUnit.Kind.MUNICIPALITY
            ).order_by("name")
        )
    return []

