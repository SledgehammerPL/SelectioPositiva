"""Zgłoszenia kandydatów jako niezatwierdzone profile użytkowników."""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from elections.models import VoterProfile

User = get_user_model()


@transaction.atomic
def request_candidate_user(
    *,
    requested_by,
    first_name: str,
    last_name: str,
    birth_date: date,
    second_name: str = "",
    note: str = "",
) -> tuple[User, bool]:
    """
    Tworzy (lub znajduje) użytkownika ze zgłoszenia.

    Zwraca (user, created). Nowy profil jest niezatwierdzony;
    admin uzupełnia dane i zatwierdza.
    """
    first = (first_name or "").strip()
    second = (second_name or "").strip()
    last = (last_name or "").strip()
    note = (note or "").strip()

    qs = User.objects.filter(
        first_name__iexact=first,
        last_name__iexact=last,
        voter_profile__birth_date=birth_date,
    ).select_related("voter_profile")
    if second:
        qs = qs.filter(voter_profile__second_name__iexact=second)
    existing = qs.order_by("id").first()
    if existing is not None:
        profile = getattr(existing, "voter_profile", None)
        if profile is None:
            profile = VoterProfile.objects.create(
                user=existing,
                second_name=second,
                birth_date=birth_date,
                is_approved=False,
                requested_by=requested_by,
                request_note=note,
            )
            return existing, True
        if not profile.is_approved:
            updates: list[str] = []
            if second and not profile.second_name:
                profile.second_name = second
                updates.append("second_name")
            if note and not profile.request_note:
                profile.request_note = note
                updates.append("request_note")
            if profile.requested_by_id is None:
                profile.requested_by = requested_by
                updates.append("requested_by")
            if updates:
                profile.save(update_fields=updates)
        return existing, False

    user = User(
        username=f"_tmp_req_{requested_by.pk}_{timezone.now().timestamp():.0f}",
        first_name=first,
        last_name=last,
        email="",
        is_active=True,
    )
    user.set_unusable_password()
    user.save()
    user.username = f"u{user.pk}"
    user.save(update_fields=["username"])

    precinct = None
    try:
        precinct = requested_by.voter_profile.territorial_unit
    except VoterProfile.DoesNotExist:
        precinct = None

    VoterProfile.objects.create(
        user=user,
        second_name=second,
        birth_date=birth_date,
        territorial_unit=precinct,
        is_approved=False,
        requested_by=requested_by,
        request_note=note,
    )
    return user, True


@transaction.atomic
def approve_voter_profile(profile: VoterProfile, *, reviewer) -> VoterProfile:
    """Admin zatwierdza zgłoszony profil."""
    profile.approve(by_user=reviewer)
    return profile
