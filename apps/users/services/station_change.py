"""
Zmiana komisji wyborczej użytkownika z zamrażaniem / przywracaniem głosów.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from elections.models import Ballot, ElectoralDistrict, VoterProfile
from elections.services.eligibility import get_eligible_districts, get_voter_profile
from elections.services.results import invalidate_district_results
from geo.models import PollingStation


VOID_REASON_STATION_CHANGE = Ballot.VoidReason.CHANGE_OF_POLLING_STATION


@dataclass
class StationChangePreview:
    current_station: PollingStation | None
    new_station: PollingStation
    districts_to_void: list[ElectoralDistrict] = field(default_factory=list)
    districts_to_restore: list[ElectoralDistrict] = field(default_factory=list)
    districts_unchanged_active: list[ElectoralDistrict] = field(default_factory=list)

    # Aliasy pod UI (nazwy „urzędy” w komunikatach = okręgi głosowania)
    @property
    def offices_to_void(self) -> list[ElectoralDistrict]:
        return self.districts_to_void

    @property
    def offices_to_restore(self) -> list[ElectoralDistrict]:
        return self.districts_to_restore


@dataclass
class StationChangeResult:
    previous_station: PollingStation
    new_station: PollingStation
    voided_districts: list[ElectoralDistrict]
    restored_districts: list[ElectoralDistrict]
    active_ballots: int
    voided_ballots: int

    @property
    def voided_offices(self) -> list[ElectoralDistrict]:
        return self.voided_districts

    @property
    def restored_offices(self) -> list[ElectoralDistrict]:
        return self.restored_districts


def preview_station_change(
    user: AbstractBaseUser,
    new_station: PollingStation,
) -> StationChangePreview:
    profile = get_voter_profile(user)
    current = profile.polling_station if profile else None

    new_eligible_ids = set(
        get_eligible_districts(
            polling_station=new_station, only_open=False
        ).values_list("pk", flat=True)
    )
    ballots = list(
        Ballot.objects.filter(user=user).select_related(
            "district", "district__office"
        )
    )

    to_void: list[ElectoralDistrict] = []
    to_restore: list[ElectoralDistrict] = []
    unchanged: list[ElectoralDistrict] = []

    for ballot in ballots:
        district = ballot.district
        eligible = district.pk in new_eligible_ids
        if eligible:
            if ballot.is_voided:
                to_restore.append(district)
            else:
                unchanged.append(district)
        elif not ballot.is_voided:
            to_void.append(district)

    return StationChangePreview(
        current_station=current,
        new_station=new_station,
        districts_to_void=to_void,
        districts_to_restore=to_restore,
        districts_unchanged_active=unchanged,
    )


@transaction.atomic
def change_user_polling_station(
    user: AbstractBaseUser,
    new_station: PollingStation,
) -> StationChangeResult:
    profile = get_voter_profile(user)
    if profile is None:
        profile = VoterProfile.objects.create(
            user=user,
            polling_station=new_station,
            territorial_unit=new_station.precinct,
        )
        previous = new_station
    else:
        previous = profile.polling_station
        if previous.pk == new_station.pk:
            active = Ballot.objects.filter(user=user, is_voided=False).count()
            voided = Ballot.objects.filter(user=user, is_voided=True).count()
            return StationChangeResult(
                previous_station=previous,
                new_station=new_station,
                voided_districts=[],
                restored_districts=[],
                active_ballots=active,
                voided_ballots=voided,
            )
        profile.polling_station = new_station
        profile.territorial_unit = new_station.precinct
        profile.save(update_fields=["polling_station", "territorial_unit"])

    new_eligible_ids = set(
        get_eligible_districts(
            polling_station=new_station, only_open=False
        ).values_list("pk", flat=True)
    )

    ballots = list(Ballot.objects.filter(user=user).select_related("district"))
    now = timezone.now()
    voided_districts: list[ElectoralDistrict] = []
    restored_districts: list[ElectoralDistrict] = []
    touched_ids: set[int] = set()

    for ballot in ballots:
        district = ballot.district
        eligible = district.pk in new_eligible_ids
        touched_ids.add(district.pk)

        if eligible:
            if ballot.is_voided:
                ballot.is_voided = False
                ballot.void_reason = ""
                ballot.voided_at = None
                ballot.save(
                    update_fields=["is_voided", "void_reason", "voided_at", "updated_at"]
                )
                restored_districts.append(district)
        else:
            if not ballot.is_voided:
                ballot.is_voided = True
                ballot.void_reason = VOID_REASON_STATION_CHANGE
                ballot.voided_at = now
                ballot.save(
                    update_fields=["is_voided", "void_reason", "voided_at", "updated_at"]
                )
                voided_districts.append(district)

    for district_id in touched_ids:
        invalidate_district_results(district_id)

    active = Ballot.objects.filter(user=user, is_voided=False).count()
    voided = Ballot.objects.filter(user=user, is_voided=True).count()

    return StationChangeResult(
        previous_station=previous,
        new_station=new_station,
        voided_districts=voided_districts,
        restored_districts=restored_districts,
        active_ballots=active,
        voided_ballots=voided,
    )
