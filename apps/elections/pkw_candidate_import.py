"""Wspólna logika upsertu kandydatów PKW → User + VoterProfile."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from elections.models import VoterProfile
from elections.services.identity import (
    build_identity_index,
    find_identity_match,
    register_identity,
)
from geo.models import TerritorialUnit
from geo.pkw import norm_teryt

User = get_user_model()
BATCH_SIZE = 200


def strip_diacritics(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def email_slug_for(
    first_name: str,
    last_name: str,
    *,
    second_name: str = "",
    list_nr: int | None = None,
    list_position: int | None = None,
) -> str:
    base = slugify(f"{first_name}-{last_name}", allow_unicode=False)
    if not base:
        base = strip_diacritics(last_name or first_name or "kandydat").lower().replace(
            " ", "-"
        )
    if second_name:
        extra = slugify(second_name, allow_unicode=False)
        if extra:
            base = f"{base}-{extra}"
    if list_nr is not None and list_position is not None:
        base = f"{base}-l{list_nr}-p{list_position}"
    elif list_position is not None and list_nr is None:
        base = f"{base}-p{list_position}"
    return base


def unique_slug_for(
    cand: Any,
    seen_emails: set[str],
    *,
    email_for: Callable[[Any, str], str],
) -> str:
    """Preferuj first-last; przy kolizji dodaj 2. imię / listę."""
    list_nr = getattr(cand, "list_nr", None)
    attempts = (
        email_slug_for(cand.first_name, cand.last_name),
        email_slug_for(
            cand.first_name, cand.last_name, second_name=cand.second_name
        ),
        email_slug_for(
            cand.first_name,
            cand.last_name,
            second_name=cand.second_name,
            list_nr=list_nr,
            list_position=cand.list_position,
        ),
    )
    for slug in attempts:
        email = email_for(cand, slug).lower()
        if email not in seen_emails:
            seen_emails.add(email)
            return slug
    slug = attempts[-1]
    seen_emails.add(email_for(cand, slug).lower())
    return slug


def municipality_by_teryt() -> dict[str, TerritorialUnit]:
    return {
        u.teryt: u
        for u in TerritorialUnit.objects.filter(
            kind=TerritorialUnit.Kind.MUNICIPALITY
        ).exclude(teryt="")
        if u.teryt
    }


def _apply_profile_updates(
    profile: VoterProfile,
    *,
    second_name: str,
    unit: TerritorialUnit | None,
    birth_date: date | None,
) -> bool:
    updates = False
    second = second_name or ""
    if profile.second_name != second:
        profile.second_name = second
        updates = True
    if unit is not None and profile.territorial_unit_id != unit.pk:
        profile.territorial_unit = unit
        updates = True
    if birth_date is not None and profile.birth_date != birth_date:
        profile.birth_date = birth_date
        updates = True
    return updates


def _flush_creates(
    rows: list[dict],
    existing: dict[str, User],
    identity_index: dict,
    profiles_by_user_id: dict[int, VoterProfile],
) -> tuple[int, int]:
    """Zwraca (created, reused_as_update_rows)."""
    if not rows:
        return 0, 0

    emails = [r["email"] for r in rows]
    for u in User.objects.filter(email__in=emails).select_related("voter_profile"):
        existing[u.email.lower()] = u
        register_identity(identity_index, u)
        if hasattr(u, "voter_profile"):
            profiles_by_user_id[u.pk] = u.voter_profile

    to_create: list[dict] = []
    to_reuse: list[dict] = []
    for r in rows:
        key = r["email"].lower()
        if key in existing:
            user = existing[key]
            profile = profiles_by_user_id.get(user.pk)
            if profile is None:
                profile, _ = VoterProfile.objects.get_or_create(user=user)
                profiles_by_user_id[user.pk] = profile
            to_reuse.append({**r, "user": user, "profile": profile})
            continue

        unit = r["unit"]
        unit_id = unit.pk if unit is not None else None
        match = find_identity_match(
            identity_index,
            first_name=r["first_name"],
            second_name=r["second_name"],
            last_name=r["last_name"],
            territorial_unit_id=unit_id,
            birth_date=r.get("birth_date"),
        )
        if match is not None:
            existing[key] = match
            existing[match.email.lower()] = match
            profile = profiles_by_user_id.get(match.pk)
            if profile is None:
                profile, _ = VoterProfile.objects.get_or_create(user=match)
                profiles_by_user_id[match.pk] = profile
            to_reuse.append({**r, "user": match, "profile": profile})
            continue

        to_create.append(r)

    reused = 0
    if to_reuse:
        reused = _flush_updates(to_reuse)

    if not to_create:
        return 0, reused

    now = timezone.now()
    users = [
        User(
            username=f"_tmp_{i}_{r['email'][:18]}",
            first_name=r["first_name"],
            last_name=r["last_name"],
            email=r["email"],
            password="!",
            is_staff=False,
            is_active=True,
            date_joined=now,
        )
        for i, r in enumerate(to_create)
    ]
    created_users = User.objects.bulk_create(users, batch_size=BATCH_SIZE)
    for user in created_users:
        user.username = f"u{user.pk}"
        existing[user.email.lower()] = user
    User.objects.bulk_update(created_users, ["username"], batch_size=BATCH_SIZE)

    profiles = []
    for r, user in zip(to_create, created_users, strict=True):
        profile = VoterProfile(
            user=user,
            second_name=r["second_name"] or "",
            birth_date=r.get("birth_date"),
            territorial_unit=r["unit"],
        )
        profiles.append(profile)
        profiles_by_user_id[user.pk] = profile
        user.voter_profile = profile
        register_identity(identity_index, user)

    VoterProfile.objects.bulk_create(profiles, batch_size=BATCH_SIZE)
    return len(to_create), reused


def _flush_updates(rows: list[dict]) -> int:
    if not rows:
        return 0
    users_to_save: list[User] = []
    profiles_to_save: list[VoterProfile] = []
    for r in rows:
        user: User = r["user"]
        changed = False
        if r["first_name"] and user.first_name != r["first_name"]:
            user.first_name = r["first_name"]
            changed = True
        if r["last_name"] and user.last_name != r["last_name"]:
            user.last_name = r["last_name"]
            changed = True
        if user.has_usable_password():
            user.set_unusable_password()
            changed = True
        if changed:
            users_to_save.append(user)

        profile = r["profile"]
        if _apply_profile_updates(
            profile,
            second_name=r["second_name"],
            unit=r["unit"],
            birth_date=r.get("birth_date"),
        ):
            profiles_to_save.append(profile)

    if users_to_save:
        User.objects.bulk_update(
            users_to_save, ["first_name", "last_name", "password"], batch_size=BATCH_SIZE
        )
    if profiles_to_save:
        VoterProfile.objects.bulk_update(
            profiles_to_save,
            ["second_name", "territorial_unit", "birth_date"],
            batch_size=BATCH_SIZE,
        )
    return len(rows)


def import_candidates_batch(
    candidates: Iterable[Any],
    *,
    email_prefix: str,
    email_for: Callable[[Any, str], str],
    units: dict[str, TerritorialUnit],
    stdout=None,
    quiet: bool = True,
    identity_index: dict | None = None,
) -> tuple[int, int, int, int]:
    """
    Importuje listę kandydatów.
    Zwraca (created, updated, reused_identity, missing_units).
    """
    settings.DEBUG = False

    if identity_index is None:
        identity_index = build_identity_index()
    existing = {
        u.email.lower(): u
        for u in User.objects.filter(email__startswith=email_prefix)
        .select_related("voter_profile")
        .iterator()
    }
    for u in existing.values():
        register_identity(identity_index, u)

    profiles_by_user_id = {
        p.user_id: p
        for p in VoterProfile.objects.filter(
            user__email__startswith=email_prefix
        ).iterator()
    }

    created = updated = reused = missing_units = 0
    create_batch: list[dict] = []
    update_batch: list[dict] = []
    seen_emails: set[str] = set()
    candidates_list = list(candidates)
    total = len(candidates_list)

    def flush():
        nonlocal created, updated, reused
        with transaction.atomic():
            c, r = _flush_creates(
                create_batch, existing, identity_index, profiles_by_user_id
            )
            created += c
            reused += r
            updated += _flush_updates(update_batch)
        create_batch.clear()
        update_batch.clear()

    for cand in candidates_list:
        code = norm_teryt(cand.residence_teryt, width=6)
        unit = units.get(code)
        if unit is None:
            missing_units += 1

        slug = unique_slug_for(cand, seen_emails, email_for=email_for)
        email = email_for(cand, slug)
        key = email.lower()
        birth_date = getattr(cand, "birth_date", None)

        if stdout is not None and not quiet:
            unit_label = str(unit) if unit else f"(brak TERYT {code})"
            stdout.write(
                f"  [{cand.district_nr}] {cand.last_name} {cand.first_name} "
                f"{cand.second_name} | {email} | zam. {unit_label}"
            )

        user = existing.get(key)
        unit_id = unit.pk if unit is not None else None
        via_identity = False
        if user is None:
            user = find_identity_match(
                identity_index,
                first_name=cand.first_name,
                second_name=cand.second_name,
                last_name=cand.last_name,
                territorial_unit_id=unit_id,
                birth_date=birth_date,
            )
            if user is not None:
                via_identity = True
                existing[key] = user
                existing[user.email.lower()] = user

        row = {
            "email": email,
            "first_name": cand.first_name,
            "second_name": cand.second_name,
            "last_name": cand.last_name,
            "unit": unit,
            "birth_date": birth_date,
        }

        if user is None:
            create_batch.append(row)
        else:
            profile = profiles_by_user_id.get(user.pk)
            if profile is None:
                profile, _ = VoterProfile.objects.get_or_create(user=user)
                profiles_by_user_id[user.pk] = profile
            update_batch.append({**row, "user": user, "profile": profile})
            if via_identity:
                reused += 1

        if len(create_batch) + len(update_batch) >= BATCH_SIZE:
            flush()
            if stdout is not None:
                stdout.write(f"  … {created + updated}/{total}")

    flush()
    return created, updated, reused, missing_units
