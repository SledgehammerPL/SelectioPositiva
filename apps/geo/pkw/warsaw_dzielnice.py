"""
Okręgi rad dzielnic m.st. Warszawy — traktowane jak rady powiatów
(urząd `radny-powiatu`, slug `rada-powiat-{teryt6}-{nr}`).
"""

from __future__ import annotations

from django.db import transaction

from elections.models import ElectoralDistrict, Office
from geo.models import TerritorialLevel, TerritorialUnit
from geo.pkw import col, fetch_source, iter_csv_rows_from_zip, norm_teryt


def ensure_radny_powiatu_office() -> Office:
    level = TerritorialLevel.objects.filter(slug="county").first()
    office, _ = Office.objects.update_or_create(
        slug="radny-powiatu",
        defaults={
            "name": "Radny rady powiatu / dzielnicy",
            "description": (
                "Okręgi do rad powiatów i rad dzielnic m.st. Warszawy "
                "(PKW samorząd 2024)."
            ),
            "is_open": True,
            "display_order": 40,
            "min_age": 18,
            "candidacy_level": level,
        },
    )
    return office


@transaction.atomic
def ensure_warsaw_dzielnica_districts(*, office: Office | None = None) -> dict[str, int]:
    office = office or ensure_radny_powiatu_office()
    gminy = {
        u.teryt: u
        for u in TerritorialUnit.objects.filter(
            kind=TerritorialUnit.Kind.MUNICIPALITY,
            teryt__startswith="1465",
        ).exclude(teryt="")
        if u.teryt
    }
    path = fetch_source("okregi_rada_dzielnic")
    created = updated = skipped = 0

    for row in iter_csv_rows_from_zip(path):
        key = norm_teryt(col(row, "TERYT Dzielnicy"), width=6)
        nr = col(row, "Numer okręgu")
        if not key or not nr:
            continue
        parent = gminy.get(key)
        if parent is None:
            skipped += 1
            continue
        seats = int(col(row, "Liczba mandatów") or "1")
        organ = col(row, "Wybierany organ")
        slug = f"rada-powiat-{key}-{nr}"
        district, was_created = ElectoralDistrict.objects.update_or_create(
            slug=slug,
            defaults={
                "office": office,
                "name": f"{organ} — okręg {nr}"[:200],
                "seats_count": seats,
                "display_order": int(nr) if str(nr).isdigit() else 0,
            },
        )
        district.territorial_units.set([parent.pk])
        if was_created:
            created += 1
        else:
            updated += 1

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "districts": created + updated,
    }
