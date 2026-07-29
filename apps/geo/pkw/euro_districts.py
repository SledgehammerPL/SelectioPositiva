"""
Okręgi wyborcze do Parlamentu Europejskiego (Kodeks wyborczy / PE 2024).

13 okręgów: całe województwa, pary województw albo (Mazowsze) grupy powiatów.
Powiązanie z hierarchią: jednostkami okręgu są województwa lub powiaty —
wszystkie obwody / komisje w ich poddrzewie należą do okręgu.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from elections.models import ElectoralDistrict, Office
from geo.models import TerritorialLevel, TerritorialUnit

# Powiaty okręgu nr 4 (Warszawa + pierścień).
EURO4_POWIAT_TERYTS = frozenset(
    {
        "1465",  # m. st. Warszawa
        "1405",  # grodziski
        "1408",  # legionowski
        "1414",  # nowodworski
        "1417",  # otwocki
        "1418",  # piaseczyński
        "1421",  # pruszkowski
        "1432",  # warszawski zachodni
        "1434",  # wołomiński
    }
)


@dataclass(frozen=True)
class EuroDistrictSpec:
    nr: int
    name: str
    seat: str
    # TERYT województw (2 cyfry) — całe woj. w okręgu
    woj_teryts: tuple[str, ...] = ()
    # Jawna lista powiatów (4 cyfry); puste + mazowsze_rest → reszta woj. 14
    powiat_teryts: tuple[str, ...] | None = None
    mazowsze_rest: bool = False
    seats_count: int = 3


EURO_DISTRICT_SPECS: tuple[EuroDistrictSpec, ...] = (
    EuroDistrictSpec(1, "Okręg nr 1 — Pomorskie", "Gdańsk", woj_teryts=("22",)),
    EuroDistrictSpec(
        2, "Okręg nr 2 — Kujawsko-Pomorskie", "Bydgoszcz", woj_teryts=("04",)
    ),
    EuroDistrictSpec(
        3,
        "Okręg nr 3 — Podlaskie i Warmińsko-Mazurskie",
        "Olsztyn",
        woj_teryts=("20", "28"),
    ),
    EuroDistrictSpec(
        4,
        "Okręg nr 4 — Warszawa",
        "Warszawa",
        powiat_teryts=tuple(sorted(EURO4_POWIAT_TERYTS)),
        seats_count=5,
    ),
    EuroDistrictSpec(
        5,
        "Okręg nr 5 — Mazowsze",
        "Radom",
        mazowsze_rest=True,
        seats_count=3,
    ),
    EuroDistrictSpec(6, "Okręg nr 6 — Łódzkie", "Łódź", woj_teryts=("10",)),
    EuroDistrictSpec(
        7, "Okręg nr 7 — Wielkopolskie", "Poznań", woj_teryts=("30",), seats_count=4
    ),
    EuroDistrictSpec(8, "Okręg nr 8 — Lubelskie", "Lublin", woj_teryts=("06",)),
    EuroDistrictSpec(
        9, "Okręg nr 9 — Podkarpackie", "Rzeszów", woj_teryts=("18",)
    ),
    EuroDistrictSpec(
        10,
        "Okręg nr 10 — Małopolskie i Świętokrzyskie",
        "Kraków",
        woj_teryts=("12", "26"),
        seats_count=5,
    ),
    EuroDistrictSpec(
        11, "Okręg nr 11 — Śląskie", "Katowice", woj_teryts=("24",), seats_count=5
    ),
    EuroDistrictSpec(
        12,
        "Okręg nr 12 — Dolnośląskie i Opolskie",
        "Wrocław",
        woj_teryts=("02", "16"),
        seats_count=4,
    ),
    EuroDistrictSpec(
        13,
        "Okręg nr 13 — Lubuskie i Zachodniopomorskie",
        "Gorzów Wielkopolski",
        woj_teryts=("08", "32"),
    ),
)


def _unit_ids_for_spec(spec: EuroDistrictSpec) -> list[int]:
    ids: list[int] = []
    if spec.woj_teryts:
        ids.extend(
            TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.VOIVODESHIP,
                teryt__in=spec.woj_teryts,
            ).values_list("pk", flat=True)
        )
    if spec.powiat_teryts is not None:
        ids.extend(
            TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.COUNTY,
                teryt__in=spec.powiat_teryts,
            ).values_list("pk", flat=True)
        )
    if spec.mazowsze_rest:
        ids.extend(
            TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.COUNTY,
                teryt__startswith="14",
            )
            .exclude(teryt__in=EURO4_POWIAT_TERYTS)
            .values_list("pk", flat=True)
        )
    return ids


def ensure_euro_office() -> Office:
    levels = {lv.slug: lv for lv in TerritorialLevel.objects.all()}
    office, _ = Office.objects.update_or_create(
        slug="eurodeputowany",
        defaults={
            "name": "Poseł do Europarlamentu",
            "description": "Wybory do Parlamentu Europejskiego — 13 okręgów.",
            "is_open": True,
            "display_order": 2,
            "min_age": 21,
            "candidacy_level": levels.get("country"),
            "results_visibility_level": levels.get("voivodeship"),
        },
    )
    return office


@transaction.atomic
def ensure_euro_districts(*, office: Office | None = None) -> dict[str, int]:
    """
    Tworzy / aktualizuje 13 okręgów PE i ustawia territorial_units
    (województwa lub powiaty).
    """
    office = office or ensure_euro_office()
    created = updated = linked_units = 0

    for spec in EURO_DISTRICT_SPECS:
        slug = f"euro-{spec.nr}"
        name = f"{spec.name} (siedziba: {spec.seat})"
        district, was_created = ElectoralDistrict.objects.update_or_create(
            slug=slug,
            defaults={
                "office": office,
                "name": name[:200],
                "seats_count": spec.seats_count,
                "display_order": spec.nr,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1

        unit_ids = _unit_ids_for_spec(spec)
        district.territorial_units.set(unit_ids)
        linked_units += len(unit_ids)

    return {
        "created": created,
        "updated": updated,
        "districts": len(EURO_DISTRICT_SPECS),
        "linked_units": linked_units,
    }
