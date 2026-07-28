"""Wspólna logika upsertu kandydatów PKW → User + VoterProfile."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from elections.models import VoterProfile
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


def _flush_creates(rows: list[dict], existing: dict[str, User]) -> int:
    if not rows:
        return 0
    now = timezone.now()
    users = [
        User(
            username=f"_tmp_{i}_{r['email'][:18]}",
            first_name=r["first_name"],
            last_name=r["last_name"],
            email=r["email"],
            password="!",  # unusable
            is_staff=False,
            is_active=True,
            date_joined=now,
        )
        for i, r in enumerate(rows)
    ]
    created_users = User.objects.bulk_create(users, batch_size=BATCH_SIZE)
    for user in created_users:
        user.username = f"u{user.pk}"
        existing[user.email.lower()] = user
    User.objects.bulk_update(created_users, ["username"], batch_size=BATCH_SIZE)
    VoterProfile.objects.bulk_create(
        [
            VoterProfile(
                user=existing[r["email"].lower()],
                second_name=r["second_name"] or "",
                birth_date=None,
                territorial_unit=r["unit"],
            )
            for r in rows
        ],
        batch_size=BATCH_SIZE,
    )
    return len(rows)


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
        updates = False
        second = r["second_name"] or ""
        if profile.second_name != second:
            profile.second_name = second
            updates = True
        unit = r["unit"]
        if unit is not None and profile.territorial_unit_id != unit.pk:
            profile.territorial_unit = unit
            updates = True
        if updates:
            profiles_to_save.append(profile)

    if users_to_save:
        User.objects.bulk_update(
            users_to_save, ["first_name", "last_name", "password"], batch_size=BATCH_SIZE
        )
    if profiles_to_save:
        VoterProfile.objects.bulk_update(
            profiles_to_save,
            ["second_name", "territorial_unit"],
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
) -> tuple[int, int, int]:
    """
    Importuje listę kandydatów. Zwraca (created, updated, missing_units).
    email_prefix — filtr istniejących kont, np. 'sejm2023.'.
    """
    # DEBUG SQL na Windows (cp1250) jest wolne i wywala się na ñ itd.
    settings.DEBUG = False

    existing = {
        u.email.lower(): u
        for u in User.objects.filter(email__startswith=email_prefix).iterator()
    }
    profiles_by_user_id = {
        p.user_id: p
        for p in VoterProfile.objects.filter(
            user__email__startswith=email_prefix
        ).iterator()
    }

    created = updated = missing_units = 0
    create_batch: list[dict] = []
    update_batch: list[dict] = []
    seen_emails: set[str] = set()
    candidates_list = list(candidates)
    total = len(candidates_list)

    def flush():
        nonlocal created, updated
        with transaction.atomic():
            created += _flush_creates(create_batch, existing)
            for r in create_batch:
                profiles_by_user_id[existing[r["email"].lower()].pk] = None  # type: ignore
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

        if stdout is not None and not quiet:
            unit_label = str(unit) if unit else f"(brak TERYT {code})"
            stdout.write(
                f"  [{cand.district_nr}] {cand.last_name} {cand.first_name} "
                f"{cand.second_name} | {email} | zam. {unit_label}"
            )

        user = existing.get(key)
        if user is None:
            create_batch.append(
                {
                    "email": email,
                    "first_name": cand.first_name,
                    "second_name": cand.second_name,
                    "last_name": cand.last_name,
                    "unit": unit,
                }
            )
        else:
            profile = profiles_by_user_id.get(user.pk)
            if profile is None:
                profile, _ = VoterProfile.objects.get_or_create(user=user)
                profiles_by_user_id[user.pk] = profile
            update_batch.append(
                {
                    "user": user,
                    "profile": profile,
                    "first_name": cand.first_name,
                    "second_name": cand.second_name,
                    "last_name": cand.last_name,
                    "unit": unit,
                }
            )

        if len(create_batch) + len(update_batch) >= BATCH_SIZE:
            flush()
            if stdout is not None:
                stdout.write(f"  … {created + updated}/{total}")

    flush()
    return created, updated, missing_units
