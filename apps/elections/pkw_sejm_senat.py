"""
Kandydaci do Sejmu i Senatu 2023 — dane KBW (CSV).

Źródło: https://danewyborcze.kbw.gov.pl/ (Parlament 2023 → Kandydaci).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

from elections.pkw_names import parse_pkw_full_name
from geo.pkw import col, fetch_source, iter_csv_rows_from_zip, norm_teryt

PKW_CATALOG_URL = (
    "https://danewyborcze.kbw.gov.pl/indexc6e4.html?title=Parlament_2023"
)
ELECTION_YEAR = 2023

Chamber = Literal["sejm", "senat"]


@dataclass(frozen=True)
class ParliamentCandidate:
    chamber: Chamber
    district_nr: int
    list_nr: int | None
    list_position: int
    last_name: str
    first_name: str
    second_name: str
    residence_name: str
    residence_teryt: str
    committee: str


def candidate_email(candidate: ParliamentCandidate, slug: str) -> str:
    return (
        f"{candidate.chamber}{ELECTION_YEAR}."
        f"{candidate.district_nr}.{slug}@selectio.local"
    )


def _row_to_candidate(row: dict[str, str], *, chamber: Chamber) -> ParliamentCandidate:
    full = col(row, "Nazwisko i imiona")
    first, second, last = parse_pkw_full_name(full)
    list_raw = ""
    try:
        list_raw = col(row, "Nr listy")
    except KeyError:
        list_raw = ""
    list_nr = int(list_raw) if list_raw.strip().isdigit() else None
    return ParliamentCandidate(
        chamber=chamber,
        district_nr=int(col(row, "Nr okręgu")),
        list_nr=list_nr,
        list_position=int(col(row, "Pozycja na liście")),
        last_name=last,
        first_name=first,
        second_name=second,
        residence_name=col(row, "Miejsce zamieszkania", "Gmina m. z."),
        residence_teryt=norm_teryt(col(row, "TERYT m. z."), width=6),
        committee=col(row, "Nazwa komitetu"),
    )


def iter_sejm_candidates(path: Path | None = None) -> Iterator[ParliamentCandidate]:
    zip_path = path or fetch_source("kandydaci_sejm")
    for row in iter_csv_rows_from_zip(zip_path):
        yield _row_to_candidate(row, chamber="sejm")


def iter_senat_candidates(path: Path | None = None) -> Iterator[ParliamentCandidate]:
    zip_path = path or fetch_source("kandydaci_senat")
    for row in iter_csv_rows_from_zip(zip_path):
        yield _row_to_candidate(row, chamber="senat")
