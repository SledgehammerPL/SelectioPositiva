"""Tworzenie / aktualizacja użytkowników (login po email)."""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction

from elections.models import VoterProfile
from elections.services.identity import (
    build_identity_index,
    find_identity_match,
)

User = get_user_model()


@transaction.atomic
def ensure_user(
    *,
    email: str,
    password: str | None = None,
    first_name: str = "",
    second_name: str = "",
    last_name: str = "",
    birth_date: date | None = None,
    territorial_unit=None,
    is_staff: bool = False,
    is_approved: bool = False,
) -> User:
    """
    Znajduje użytkownika po emailu, potem po tożsamości
    (imię + spokrewniona jednostka + data ur.), albo tworzy nowego.
    `User.username` jest wewnętrzne (`u{id}`) — logowanie po email.
    """
    normalized = email.strip().lower()
    user = User.objects.filter(email__iexact=normalized).first()
    if user is None and territorial_unit is not None:
        index = build_identity_index()
        user = find_identity_match(
            index,
            first_name=first_name,
            second_name=second_name,
            last_name=last_name,
            territorial_unit_id=territorial_unit.pk,
            birth_date=birth_date,
        )
    if user is not None:
        changed = False
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if last_name and user.last_name != last_name:
            user.last_name = last_name
            changed = True
        if changed:
            user.save()
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        profile, _ = VoterProfile.objects.get_or_create(
            user=user,
            defaults={"is_approved": is_approved},
        )
        updates = {}
        if second_name and profile.second_name != second_name:
            updates["second_name"] = second_name
        if birth_date is not None:
            updates["birth_date"] = birth_date
        if territorial_unit is not None:
            updates["territorial_unit"] = territorial_unit
        if is_approved and not profile.is_approved:
            updates["is_approved"] = True
        if updates:
            for key, value in updates.items():
                setattr(profile, key, value)
            profile.save(update_fields=list(updates.keys()))
        return user

    user = User(
        username=f"_tmp_{normalized[:20]}",
        first_name=first_name,
        last_name=last_name,
        email=normalized,
        is_staff=is_staff,
    )
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    user.save()
    user.username = f"u{user.pk}"
    user.save(update_fields=["username"])

    VoterProfile.objects.create(
        user=user,
        second_name=second_name or "",
        birth_date=birth_date,
        territorial_unit=territorial_unit,
        is_approved=is_approved,
    )
    return user
