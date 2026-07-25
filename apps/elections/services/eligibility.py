from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Prefetch, QuerySet

from elections.models import Ballot, Candidate, ElectoralDistrict, VoterProfile
from geo.models import PollingStation, TerritorialUnit


@dataclass(frozen=True)
class DistrictVoteStatus:
    district: ElectoralDistrict
    has_voted: bool
    ballot: Ballot | None


# Alias historyczny dla czytelności w starszym kodzie.
OfficeVoteStatus = DistrictVoteStatus


def get_voter_profile(user: AbstractBaseUser) -> VoterProfile | None:
    if not user.is_authenticated:
        return None
    try:
        return user.voter_profile  # type: ignore[attr-defined]
    except VoterProfile.DoesNotExist:
        return None


def eligible_territorial_unit_ids(unit: TerritorialUnit) -> list[int]:
    """ID jednostek w łańcuchu hierarchii (od liścia w górę do kraju)."""
    return [u.pk for u in unit.get_ancestors(include_self=True)]


def get_eligible_districts(
    user: AbstractBaseUser | None = None,
    *,
    polling_station: PollingStation | None = None,
    only_open: bool = True,
) -> QuerySet[ElectoralDistrict]:
    """
    Okręgi dostępne dla użytkownika / komisji.

    Okręg jest uprawniony, gdy jego `territorial_unit` leży w drzewie
    przodków jednostki terytorialnej komisji (włącznie z nią samą).
    """
    station = polling_station
    if station is None:
        if user is None:
            return ElectoralDistrict.objects.none()
        profile = get_voter_profile(user)
        if profile is None:
            return ElectoralDistrict.objects.none()
        station = profile.polling_station

    unit_ids = eligible_territorial_unit_ids(station.territorial_unit)
    qs = ElectoralDistrict.objects.filter(territorial_unit_id__in=unit_ids)
    if only_open:
        qs = qs.filter(office__is_open=True)
    return qs.select_related("office", "territorial_unit").prefetch_related(
        Prefetch(
            "candidates",
            queryset=Candidate.objects.filter(is_active=True),
        )
    )


def get_eligible_offices(
    user: AbstractBaseUser | None = None,
    *,
    polling_station: PollingStation | None = None,
    only_open: bool = True,
) -> QuerySet[ElectoralDistrict]:
    """Alias: uprawnione jednostki głosowania = okręgi wyborcze."""
    return get_eligible_districts(
        user, polling_station=polling_station, only_open=only_open
    )


def offices_for_user(user: AbstractBaseUser) -> QuerySet[ElectoralDistrict]:
    return get_eligible_districts(user, only_open=True)


def vote_statuses_for_user(user: AbstractBaseUser) -> list[DistrictVoteStatus]:
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


def user_can_vote_on(user: AbstractBaseUser, district: ElectoralDistrict) -> bool:
    if not district.is_open:
        return False
    return get_eligible_districts(user).filter(pk=district.pk).exists()


def ballot_counts_for_user(user: AbstractBaseUser) -> dict[str, int]:
    qs = Ballot.objects.filter(user=user)
    return {
        "active": qs.filter(is_voided=False).count(),
        "voided": qs.filter(is_voided=True).count(),
    }
