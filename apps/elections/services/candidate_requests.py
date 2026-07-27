"""Zatwierdzanie próśb o kandydatów."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from elections.models import CandidateRequest, VoterProfile

User = get_user_model()


@transaction.atomic
def approve_candidate_request(
    request_obj: CandidateRequest,
    *,
    reviewer,
) -> User:
    """
    Tworzy konto kandydata (User + VoterProfile) i oznacza prośbę jako zatwierdzoną.
    Obwód bierze z profilu zgłaszającego — admin może potem poprawić.
    """
    if request_obj.status == CandidateRequest.Status.APPROVED and request_obj.created_user_id:
        return request_obj.created_user

    precinct = None
    try:
        precinct = request_obj.requested_by.voter_profile.territorial_unit
    except VoterProfile.DoesNotExist:
        precinct = None

    user = User(
        username=f"_tmp_req_{request_obj.pk}",
        first_name=request_obj.first_name.strip(),
        last_name=request_obj.last_name.strip(),
        email="",
        is_active=True,
    )
    user.set_unusable_password()
    user.save()
    user.username = f"u{user.pk}"
    user.save(update_fields=["username"])

    VoterProfile.objects.create(
        user=user,
        phone=None,
        birth_date=request_obj.birth_date,
        territorial_unit=precinct,
    )

    request_obj.status = CandidateRequest.Status.APPROVED
    request_obj.created_user = user
    request_obj.reviewed_by = reviewer
    request_obj.reviewed_at = timezone.now()
    request_obj.save(
        update_fields=[
            "status",
            "created_user",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )
    return user


@transaction.atomic
def reject_candidate_request(
    request_obj: CandidateRequest,
    *,
    reviewer,
    admin_note: str = "",
) -> None:
    request_obj.status = CandidateRequest.Status.REJECTED
    request_obj.reviewed_by = reviewer
    request_obj.reviewed_at = timezone.now()
    if admin_note:
        request_obj.admin_note = admin_note
    request_obj.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "admin_note",
            "updated_at",
        ]
    )
