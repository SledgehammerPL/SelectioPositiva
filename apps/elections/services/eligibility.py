from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from elections.models import (
    Ballot,
    ElectoralDistrict,
    VoterProfile,
    _ancestor_of_kind,
    unit_is_descendant_of_any,
)
from geo.models import TerritorialUnit

User = get_user_model()


def district_units_at_level(
    district: ElectoralDistrict, level_slug: str
) -> set[int]:
    """
    ID jednostek na danym poziomie pokrywających okręg
    (sama jednostka okręgu lub jej przodek tego rodzaju).
    """
    ids: set[int] = set()
    for unit in district.territorial_units.all():
        if unit.kind == level_slug:
            ids.add(unit.pk)
            continue
        ancestor = _ancestor_of_kind(unit, level_slug)
        if ancestor is not None:
            ids.add(ancestor.pk)
    return ids


def user_may_run_in_district(
    precinct: TerritorialUnit | None,
    district: ElectoralDistrict,
) -> bool:
    """
    Czy osoba z danego obwodu może kandydować / być w rankingu w okręgu.

    Poziom zgodności bierze się z `office.candidacy_level`
    (np. kraj → każdy z kraju; gmina → ta sama gmina).
    Bez ustawionego poziomu — jak przy głosowaniu (obwód ∈ okręgu).
    """
    if precinct is None or precinct.kind != TerritorialUnit.Kind.PRECINCT:
        return False

    office = district.office
    level = office.candidacy_level if office is not None else None
    if level is None:
        district_unit_ids = set(district.territorial_units.values_list("pk", flat=True))
        if not district_unit_ids:
            return False
        return unit_is_descendant_of_any(precinct, district_unit_ids)

    candidate_unit = _ancestor_of_kind(precinct, level.slug)
    if candidate_unit is None:
        return False
    return candidate_unit.pk in district_units_at_level(district, level.slug)


@dataclass(frozen=True)
class DistrictVoteStatus:
    district: ElectoralDistrict
    has_voted: bool
    ballot: Ballot | None


OfficeVoteStatus = DistrictVoteStatus


def get_voter_profile(user) -> VoterProfile | None:
    if not user.is_authenticated:
        return None
    try:
        return user.voter_profile  # type: ignore[attr-defined]
    except VoterProfile.DoesNotExist:
        return None


def user_age_on(user, reference: date) -> int | None:
    """Wiek użytkownika na podany dzień. Pobiera birth_date z profilu."""
    profile = get_voter_profile(user)
    bd = profile.birth_date if profile else None
    if bd is None:
        return None
    years = reference.year - bd.year
    if (reference.month, reference.day) < (bd.month, bd.day):
        years -= 1
    return years


def user_eligible_for_district(
    user, district: ElectoralDistrict, *, today: date | None = None
) -> bool:
    """
    Czy użytkownik jest uprawniony do głosowania w okręgu.

    Warunki:
    1. Musi mieć territorial_unit = obwód (kind=precinct).
    2. Jego obwód musi być potomkiem (lub równy) jednej z jednostek okręgu.
    3. Musi spełniać limit wieku office.min_age (jeśli znana data urodzenia).
    """
    profile = get_voter_profile(user)
    if profile is None or not profile.can_vote():
        return False

    effective = profile.effective_unit()
    if effective is None:
        return False

    district_unit_ids = set(district.territorial_units.values_list("pk", flat=True))
    if not district_unit_ids:
        return False

    if not unit_is_descendant_of_any(effective, district_unit_ids):
        return False

    min_age = district.office.min_age if district.office_id else 0
    if min_age:
        ref = today or date.today()
        age = user_age_on(user, ref)
        if age is not None and age < min_age:
            return False

    return True


def get_eligible_districts(
    user=None,
    *,
    precinct: TerritorialUnit | None = None,
    only_open: bool = True,
    today: date | None = None,
) -> QuerySet[ElectoralDistrict]:
    """
    Okręgi dostępne dla użytkownika / obwodu.

    Filtr po hierarchii: obwód ∈ poddrzewu territorial_units okręgu.
    """
    if user is None and precinct is None:
        return ElectoralDistrict.objects.none()

    if precinct is not None:
        effective = precinct
    else:
        profile = get_voter_profile(user)
        if profile is None or not profile.can_vote():
            return ElectoralDistrict.objects.none()
        effective = profile.effective_unit()
        if effective is None:
            return ElectoralDistrict.objects.none()

    ancestor_ids = [u.pk for u in effective.get_ancestors(include_self=True)]
    if not ancestor_ids:
        return ElectoralDistrict.objects.none()

    qs = ElectoralDistrict.objects.filter(
        territorial_units__pk__in=ancestor_ids
    ).distinct()

    if only_open:
        qs = qs.filter(office__is_open=True)

    if user is not None:
        ref = today or date.today()
        age = user_age_on(user, ref)
        if age is not None:
            qs = qs.filter(office__min_age__lte=age)

    return qs.select_related("office", "office__candidacy_level")


def get_eligible_offices(user=None, *, precinct=None, only_open=True):
    """Alias."""
    return get_eligible_districts(user, precinct=precinct, only_open=only_open)


def offices_for_user(user) -> QuerySet[ElectoralDistrict]:
    return get_eligible_districts(user, only_open=True)


def vote_statuses_for_user(user) -> list[DistrictVoteStatus]:
    districts = list(get_eligible_districts(user))
    ballots = {
        b.district_id: b
        for b in Ballot.objects.filter(
            user=user, district__in=districts, is_voided=False
        )
    }
    return [
        DistrictVoteStatus(
            district=district,
            has_voted=district.pk in ballots,
            ballot=ballots.get(district.pk),
        )
        for district in districts
    ]


def user_can_vote_on(user, district: ElectoralDistrict) -> bool:
    if not district.is_open:
        return False
    return get_eligible_districts(user).filter(pk=district.pk).exists()


def ballot_counts_for_user(user) -> dict[str, int]:
    qs = Ballot.objects.filter(user=user)
    return {
        "active": qs.filter(is_voided=False).count(),
        "voided": qs.filter(is_voided=True).count(),
    }
