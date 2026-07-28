"""
Import kandydatów na Prezydenta RP 2025 z obwieszczenia PKW.

Dane kandydatów są w elections.pkw_presidential (bez PDF / pypdf).
Jednostka terytorialna = zamieszkanie z PKW.

Użycie:
  python manage.py import_pkw_presidential_candidates
  python manage.py import_pkw_presidential_candidates --dry-run
"""

from __future__ import annotations

import unicodedata

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from elections.models import ElectoralDistrict, Office, VoterProfile
from elections.pkw_presidential import (
    CANDIDATES,
    PKW_OBWIESZCZENIE_URL,
    RESIDENCE_MAP,
    birth_date_for,
)
from geo.models import TerritorialLevel, TerritorialUnit
from users.services.accounts import ensure_user


def _strip_diacritics(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def resolve_residence_unit(residence_key: str) -> TerritorialUnit | None:
    key = (residence_key or "").strip().lower()
    mapped = RESIDENCE_MAP.get(key)
    if mapped is None:
        plain = _strip_diacritics(key)
        for k, v in RESIDENCE_MAP.items():
            if _strip_diacritics(k) == plain:
                mapped = v
                break
    if not mapped:
        return None

    place, teryt, kind = mapped
    if kind == "country":
        return TerritorialUnit.objects.filter(kind=TerritorialUnit.Kind.COUNTRY).first()
    if teryt:
        unit = TerritorialUnit.objects.filter(kind=kind, teryt=teryt).first()
        if unit:
            return unit
    return _lookup_place(place, kind=kind)


def _lookup_place(place: str, *, kind: str) -> TerritorialUnit | None:
    kind_enum = {
        "county": TerritorialUnit.Kind.COUNTY,
        "municipality": TerritorialUnit.Kind.MUNICIPALITY,
        "country": TerritorialUnit.Kind.COUNTRY,
    }.get(kind, TerritorialUnit.Kind.MUNICIPALITY)

    if kind_enum == TerritorialUnit.Kind.COUNTRY:
        return TerritorialUnit.objects.filter(kind=kind_enum).first()

    place = place.strip()
    for name in (f"m. {place}", f"gm. {place}", place, f"m.st. {place}"):
        unit = TerritorialUnit.objects.filter(kind=kind_enum, name__iexact=name).first()
        if unit:
            return unit

    qs = TerritorialUnit.objects.filter(kind=kind_enum, name__icontains=place)
    city = qs.filter(name__istartswith="m.").first()
    return city or qs.first()


def ensure_prezydent_office() -> Office:
    country_level = TerritorialLevel.objects.filter(slug="country").first()
    office, _ = Office.objects.update_or_create(
        slug="prezydent-rp",
        defaults={
            "name": "Prezydent RP",
            "description": "Wybory Prezydenta Rzeczypospolitej Polskiej",
            "is_open": True,
            "min_age": 35,
            "candidacy_level": country_level,
            "display_order": 1,
        },
    )
    poland = TerritorialUnit.objects.filter(kind=TerritorialUnit.Kind.COUNTRY).first()
    district, _ = ElectoralDistrict.objects.update_or_create(
        slug="prezydent-rp-kraj",
        defaults={
            "office": office,
            "name": "Okręg ogólnopolski",
            "seats_count": 1,
            "display_order": 1,
        },
    )
    if poland:
        district.territorial_units.set([poland])
    return office


class Command(BaseCommand):
    help = (
        "Import kandydatów na Prezydenta RP 2025 (lista z obwieszczenia PKW w kodzie; "
        f"źródło: {PKW_OBWIESZCZENIE_URL})"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tylko pokaż, co zostałoby utworzone",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry = options["dry_run"]
        self.stdout.write(f"Kandydatów w liście: {len(CANDIDATES)}")
        if not dry:
            ensure_prezydent_office()

        created = updated = 0
        for cand in CANDIDATES:
            birth_date = birth_date_for(cand)
            unit = resolve_residence_unit(cand.residence_key)

            email_slug = slugify(
                f"{cand.first_name}-{cand.last_name}", allow_unicode=False
            ) or _strip_diacritics(cand.last_name).lower()
            email = f"prezydent2025.{email_slug}@selectio.local"

            unit_label = str(unit) if unit else "(brak jednostki)"
            self.stdout.write(
                f"  {cand.last_name} {cand.first_name} {cand.second_name} | "
                f"ur. {birth_date} | zam. {cand.residence_key} -> {unit_label}"
            )

            if dry:
                continue

            existed = VoterProfile.objects.filter(user__email__iexact=email).exists()
            user = ensure_user(
                email=email,
                password=None,
                first_name=cand.first_name,
                second_name=cand.second_name,
                last_name=cand.last_name,
                birth_date=birth_date,
                territorial_unit=unit,
            )
            if user.has_usable_password():
                user.set_unusable_password()
                user.save(update_fields=["password"])

            if existed:
                updated += 1
            else:
                created += 1

        if dry:
            self.stdout.write(self.style.WARNING("Dry-run — brak zapisów."))
            transaction.set_rollback(True)
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Gotowe. Profili zaktualizowanych/utworzonych: {updated + created}."
                )
            )
