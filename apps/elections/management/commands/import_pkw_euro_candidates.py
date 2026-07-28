"""
Import kandydatów do PE 2024 z CSV KBW (danewyborcze.kbw.gov.pl).

Jednostka terytorialna = zamieszkanie (TERYT m. z.).
Zapewnia urząd eurodeputowany + 13 okręgów (euro-1…euro-13).

Użycie:
  python manage.py import_pkw_euro_candidates
  python manage.py import_pkw_euro_candidates --dry-run
  python manage.py import_pkw_euro_candidates --force-fetch
"""

from __future__ import annotations

import unicodedata

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from elections.models import VoterProfile
from elections.pkw_euro import (
    PKW_CATALOG_URL,
    candidate_email,
    iter_euro_candidates,
)
from geo.models import TerritorialUnit
from geo.pkw import fetch_source, norm_teryt
from geo.pkw.euro_districts import ensure_euro_districts

User = get_user_model()
BATCH_SIZE = 100


def _strip_diacritics(value: str) -> str:
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
        base = _strip_diacritics(last_name or first_name or "kandydat").lower().replace(
            " ", "-"
        )
    if second_name:
        extra = slugify(second_name, allow_unicode=False)
        if extra:
            base = f"{base}-{extra}"
    if list_nr is not None and list_position is not None:
        base = f"{base}-l{list_nr}-p{list_position}"
    return base


def _unique_slug(cand, seen_emails: set[str]) -> str:
    """Preferuj first-last (jak istniejące konta); przy kolizji dodaj 2. imię / listę."""
    attempts = (
        email_slug_for(cand.first_name, cand.last_name),
        email_slug_for(
            cand.first_name, cand.last_name, second_name=cand.second_name
        ),
        email_slug_for(
            cand.first_name,
            cand.last_name,
            second_name=cand.second_name,
            list_nr=cand.list_nr,
            list_position=cand.list_position,
        ),
    )
    for slug in attempts:
        email = candidate_email(cand, slug=slug).lower()
        if email not in seen_emails:
            seen_emails.add(email)
            return slug
    # nie powinno się zdarzyć
    slug = attempts[-1]
    seen_emails.add(candidate_email(cand, slug=slug).lower())
    return slug


def _municipality_by_teryt() -> dict[str, TerritorialUnit]:
    return {
        u.teryt: u
        for u in TerritorialUnit.objects.filter(
            kind=TerritorialUnit.Kind.MUNICIPALITY
        ).exclude(teryt="")
        if u.teryt
    }


def _upsert_candidate(
    *,
    email: str,
    first_name: str,
    second_name: str,
    last_name: str,
    unit: TerritorialUnit | None,
    existing: dict[str, User],
) -> str:
    """Zwraca 'created' albo 'updated'."""
    user = existing.get(email.lower())
    if user is None:
        user = User(
            username=f"_tmp_{email[:24]}",
            first_name=first_name,
            last_name=last_name,
            email=email,
        )
        user.set_unusable_password()
        user.save()
        user.username = f"u{user.pk}"
        user.save(update_fields=["username"])
        VoterProfile.objects.create(
            user=user,
            second_name=second_name or "",
            birth_date=None,
            territorial_unit=unit,
        )
        existing[email.lower()] = user
        return "created"

    changed_user = False
    if first_name and user.first_name != first_name:
        user.first_name = first_name
        changed_user = True
    if last_name and user.last_name != last_name:
        user.last_name = last_name
        changed_user = True
    if user.has_usable_password():
        user.set_unusable_password()
        changed_user = True
    if changed_user:
        user.save()

    profile, _ = VoterProfile.objects.get_or_create(user=user)
    updates = {}
    if profile.second_name != (second_name or ""):
        updates["second_name"] = second_name or ""
    if unit is not None and profile.territorial_unit_id != getattr(unit, "pk", None):
        updates["territorial_unit"] = unit
    if updates:
        for key, value in updates.items():
            setattr(profile, key, value)
        profile.save(update_fields=list(updates.keys()))
    return "updated"


class Command(BaseCommand):
    help = (
        "Import kandydatów do Parlamentu Europejskiego 2024 z CSV KBW "
        f"({PKW_CATALOG_URL})"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tylko pokaż, co zostałoby utworzone",
        )
        parser.add_argument(
            "--force-fetch",
            action="store_true",
            help="Pobierz ponownie ZIP z KBW (ignoruj cache)",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Bez wypisywania każdego kandydata",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        quiet = options["quiet"]

        zip_path = fetch_source("kandydaci_euro", force=options["force_fetch"])
        candidates = list(iter_euro_candidates(zip_path))
        self.stdout.write(f"Kandydatów w CSV: {len(candidates)} ({zip_path.name})")

        if dry:
            seen: set[str] = set()
            for cand in candidates[:5]:
                slug = _unique_slug(cand, seen)
                self.stdout.write(
                    f"  [{cand.district_nr}] {cand.last_name} {cand.first_name} "
                    f"{cand.second_name} | {candidate_email(cand, slug=slug)} | "
                    f"TERYT {cand.residence_teryt}"
                )
            if len(candidates) > 5:
                self.stdout.write(f"  … i {len(candidates) - 5} kolejnych")
            self.stdout.write(self.style.WARNING("Dry-run — brak zapisów."))
            return

        stats = ensure_euro_districts()
        self.stdout.write(
            f"Okręgi PE: {stats['districts']} "
            f"(utworzone={stats['created']}, zaktualizowane={stats['updated']})"
        )

        units = _municipality_by_teryt()
        existing = {
            u.email.lower(): u
            for u in User.objects.filter(email__startswith=f"euro2024.").iterator()
        }

        created = updated = missing_units = 0
        batch: list = []
        seen_emails: set[str] = set()

        def flush():
            nonlocal created, updated
            if not batch:
                return
            with transaction.atomic():
                for item in batch:
                    result = _upsert_candidate(**item, existing=existing)
                    if result == "created":
                        created += 1
                    else:
                        updated += 1
            batch.clear()

        for cand in candidates:
            code = norm_teryt(cand.residence_teryt, width=6)
            unit = units.get(code)
            if unit is None:
                missing_units += 1

            slug = _unique_slug(cand, seen_emails)
            email = candidate_email(cand, slug=slug)

            if not quiet:
                unit_label = str(unit) if unit else f"(brak TERYT {code})"
                self.stdout.write(
                    f"  [{cand.district_nr}] {cand.last_name} {cand.first_name} "
                    f"{cand.second_name} | {email} | zam. {unit_label}"
                )

            batch.append(
                {
                    "email": email,
                    "first_name": cand.first_name,
                    "second_name": cand.second_name,
                    "last_name": cand.last_name,
                    "unit": unit,
                }
            )
            if len(batch) >= BATCH_SIZE:
                flush()
                self.stdout.write(f"  … {created + updated}/{len(candidates)}")

        flush()

        if missing_units:
            self.stdout.write(
                self.style.WARNING(
                    f"Bez jednostki terytorialnej: {missing_units} kandydatów "
                    "(zaimportuj TERYT / import_pkw_poland)."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Gotowe. Utworzone: {created}, zaktualizowane: {updated}."
            )
        )
