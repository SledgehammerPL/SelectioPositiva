"""
Kandydaci samorządowi 2024 — dane KBW (CSV / XLSX).

Źródło: https://danewyborcze.kbw.gov.pl/ (Samorząd 2024 → Kandydaci).
Format nazwiska: NAZWISKO Imię … (odwrotnie niż sejm/PE).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

from elections.pkw_names import parse_pkw_full_name_surname_first
from geo.pkw import (
    col,
    fetch_source,
    iter_csv_rows_from_zip,
    iter_xlsx_rows_from_zip,
    norm_teryt,
)

PKW_CATALOG_URL = (
    "https://danewyborcze.kbw.gov.pl/indexbea2.html?title=Samorz%C4%85d_2024"
)
ELECTION_YEAR = 2024

Kind = Literal["sejmik", "powiat", "gmina", "wbp"]


@dataclass(frozen=True)
class SamorzadCandidate:
    kind: Kind
    district_nr: int
    list_nr: int | None
    list_position: int
    last_name: str
    first_name: str
    second_name: str
    residence_name: str
    residence_teryt: str
    committee: str
    """Klucz do emaila / okręgu, np. '02-1', '0201-1', '020101-1', '020101'."""
    area_key: str
    district_slug: str


def candidate_email(candidate: SamorzadCandidate, slug: str) -> str:
    prefix = {
        "sejmik": "sejmik",
        "powiat": "radapowiat",
        "gmina": "radagminy",
        "wbp": "wbp",
    }[candidate.kind]
    return (
        f"{prefix}{ELECTION_YEAR}.{candidate.area_key}.{slug}@selectio.local"
    )


def _parse_int(value: str) -> int | None:
    digits = "".join(c for c in (value or "").strip() if c.isdigit())
    return int(digits) if digits else None


def _row_name_residence(row: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    full = col(row, "Nazwisko i imiona")
    first, second, last = parse_pkw_full_name_surname_first(full)
    return (
        first,
        second,
        last,
        col(row, "Miejsce zamieszkania", "Gmina m. z."),
        norm_teryt(col(row, "TERYT m. z."), width=6),
        col(row, "Nazwa komitetu", "Skrót nazwy komitetu"),
    )


def iter_sejmik_candidates(path: Path | None = None) -> Iterator[SamorzadCandidate]:
    zip_path = path or fetch_source("kandydaci_sejmik")
    for row in iter_csv_rows_from_zip(zip_path):
        first, second, last, place, teryt, committee = _row_name_residence(row)
        nr = int(col(row, "Nr okręgu"))
        woj = norm_teryt(col(row, "TERYT Województwa"), width=6)[:2]
        area = f"{woj}-{nr}"
        yield SamorzadCandidate(
            kind="sejmik",
            district_nr=nr,
            list_nr=_parse_int(col(row, "Nr listy")),
            list_position=int(col(row, "Pozycja na liście")),
            last_name=last,
            first_name=first,
            second_name=second,
            residence_name=place,
            residence_teryt=teryt,
            committee=committee,
            area_key=area,
            district_slug=f"sejmik-{area}",
        )


def iter_powiat_candidates(path: Path | None = None) -> Iterator[SamorzadCandidate]:
    zip_path = path or fetch_source("kandydaci_rada_powiatu")
    for row in iter_csv_rows_from_zip(zip_path):
        first, second, last, place, teryt, committee = _row_name_residence(row)
        nr = int(col(row, "Nr okręgu"))
        powiat = norm_teryt(col(row, "TERYT Powiatu"), width=6)[:4]
        area = f"{powiat}-{nr}"
        yield SamorzadCandidate(
            kind="powiat",
            district_nr=nr,
            list_nr=_parse_int(col(row, "Nr listy")),
            list_position=int(col(row, "Pozycja na liście")),
            last_name=last,
            first_name=first,
            second_name=second,
            residence_name=place,
            residence_teryt=teryt,
            committee=committee,
            area_key=area,
            district_slug=f"rada-powiat-{area}",
        )


def iter_dzielnica_candidates(path: Path | None = None) -> Iterator[SamorzadCandidate]:
    """Rady dzielnic m.st. Warszawy — jak powiaty (urząd radny-powiatu)."""
    zip_path = path or fetch_source("kandydaci_rada_dzielnic")
    for row in iter_csv_rows_from_zip(zip_path):
        first, second, last, place, teryt, committee = _row_name_residence(row)
        nr = int(col(row, "Nr okręgu"))
        dzielnica = norm_teryt(col(row, "TERYT Dzielnicy"), width=6)
        area = f"{dzielnica}-{nr}"
        yield SamorzadCandidate(
            kind="powiat",
            district_nr=nr,
            list_nr=_parse_int(col(row, "Nr listy")),
            list_position=int(col(row, "Pozycja na liście")),
            last_name=last,
            first_name=first,
            second_name=second,
            residence_name=place,
            residence_teryt=teryt,
            committee=committee,
            area_key=area,
            district_slug=f"rada-powiat-{area}",
        )


def iter_powiat_and_dzielnica_candidates() -> Iterator[SamorzadCandidate]:
    yield from iter_powiat_candidates()
    yield from iter_dzielnica_candidates()


def iter_gmina_gt20_candidates(path: Path | None = None) -> Iterator[SamorzadCandidate]:
    zip_path = path or fetch_source("kandydaci_rada_gminy_gt20")
    for row in iter_csv_rows_from_zip(zip_path):
        first, second, last, place, teryt, committee = _row_name_residence(row)
        nr = int(col(row, "Nr okręgu"))
        gmina = norm_teryt(col(row, "TERYT Gminy"), width=6)
        area = f"{gmina}-{nr}"
        yield SamorzadCandidate(
            kind="gmina",
            district_nr=nr,
            list_nr=_parse_int(col(row, "Nr listy")),
            list_position=int(col(row, "Pozycja na liście")),
            last_name=last,
            first_name=first,
            second_name=second,
            residence_name=place,
            residence_teryt=teryt,
            committee=committee,
            area_key=area,
            district_slug=f"rada-gminy-{area}",
        )


def iter_gmina_lt20_candidates(path: Path | None = None) -> Iterator[SamorzadCandidate]:
    """Gminy do 20k — XLSX, jednomandatowe (Numer na karcie, bez Nr listy)."""
    zip_path = path or fetch_source("kandydaci_rada_gminy_lt20")
    for row in iter_xlsx_rows_from_zip(zip_path):
        first, second, last, place, teryt, committee = _row_name_residence(row)
        nr = int(col(row, "Nr okręgu"))
        gmina = norm_teryt(col(row, "TERYT Gminy"), width=6)
        pos = _parse_int(col(row, "Numer na karcie do głosowania", "Pozycja na liście"))
        area = f"{gmina}-{nr}"
        yield SamorzadCandidate(
            kind="gmina",
            district_nr=nr,
            list_nr=None,
            list_position=pos or 0,
            last_name=last,
            first_name=first,
            second_name=second,
            residence_name=place,
            residence_teryt=teryt,
            committee=committee,
            area_key=area,
            district_slug=f"rada-gminy-{area}",
        )


def iter_wbp_candidates(path: Path | None = None) -> Iterator[SamorzadCandidate]:
    zip_path = path or fetch_source("kandydaci_wbp")
    for row in iter_csv_rows_from_zip(zip_path):
        first, second, last, place, teryt, committee = _row_name_residence(row)
        area_teryt = norm_teryt(col(row, "TERYT"), width=6)
        pos = _parse_int(col(row, "Numer na karcie do głosowania")) or 0
        yield SamorzadCandidate(
            kind="wbp",
            district_nr=1,
            list_nr=None,
            list_position=pos,
            last_name=last,
            first_name=first,
            second_name=second,
            residence_name=place,
            residence_teryt=teryt,
            committee=committee,
            area_key=area_teryt,
            district_slug=f"wbp-{area_teryt}",
        )


def iter_gmina_candidates() -> Iterator[SamorzadCandidate]:
    yield from iter_gmina_gt20_candidates()
    yield from iter_gmina_lt20_candidates()
