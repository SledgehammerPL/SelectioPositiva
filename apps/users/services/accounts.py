"""Tworzenie użytkowników logujących się numerem telefonu."""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction

from elections.models import VoterProfile
from users.phone import normalize_pl_phone

User = get_user_model()


@transaction.atomic
def ensure_user_with_phone(
    *,
    phone: str,
    password: str | None = None,
    first_name: str = "",
    last_name: str = "",
    email: str = "",
    birth_date: date | None = None,
    territorial_unit=None,
    is_staff: bool = False,
) -> User:
    """
    Znajduje użytkownika po telefonie albo tworzy nowego.
    `User.username` jest wewnętrzne (`u{id}`) — logowanie tylko po telefonie.
    """
    normalized = normalize_pl_phone(phone)
    profile = (
        VoterProfile.objects.select_related("user").filter(phone=normalized).first()
    )
    if profile is not None:
        user = profile.user
        changed = False
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if last_name and user.last_name != last_name:
            user.last_name = last_name
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if changed:
            user.save()
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        updates = {}
        if birth_date is not None:
            updates["birth_date"] = birth_date
        if territorial_unit is not None:
            updates["territorial_unit"] = territorial_unit
        if updates:
            for key, value in updates.items():
                setattr(profile, key, value)
            profile.save(update_fields=list(updates.keys()))
        return user

    user = User(
        username=f"_tmp_{normalized.replace('+', '')}",
        first_name=first_name,
        last_name=last_name,
        email=email or "",
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
        phone=normalized,
        birth_date=birth_date,
        territorial_unit=territorial_unit,
    )
    return user
