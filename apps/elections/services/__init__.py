"""Serwisy wyborcze — eligibility, Schulze, cache wyników."""

from elections.services.eligibility import (
    DistrictVoteStatus,
    OfficeVoteStatus,
    ballot_counts_for_user,
    get_eligible_districts,
    get_eligible_offices,
    get_voter_profile,
    offices_for_user,
    user_can_vote_on,
    vote_statuses_for_user,
)
from elections.services.results import (
    compute_district_schulze,
    compute_office_schulze,
    get_cached_result,
    invalidate_district_results,
    invalidate_office_results,
    recompute_all_results,
    recompute_district_results,
    recompute_office_results,
)
from elections.services.schulze import SchulzeResult, compute_schulze

__all__ = [
    "DistrictVoteStatus",
    "OfficeVoteStatus",
    "SchulzeResult",
    "ballot_counts_for_user",
    "compute_district_schulze",
    "compute_office_schulze",
    "compute_schulze",
    "get_cached_result",
    "get_eligible_districts",
    "get_eligible_offices",
    "get_voter_profile",
    "invalidate_district_results",
    "invalidate_office_results",
    "offices_for_user",
    "recompute_all_results",
    "recompute_district_results",
    "recompute_office_results",
    "user_can_vote_on",
    "vote_statuses_for_user",
]
