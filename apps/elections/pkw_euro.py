"""
Kandydaci do Parlamentu Europejskiego 2024 — dane KBW (CSV).

Źródło: https://danewyborcze.kbw.gov.pl/ (Parlament Europejski 2024 → Kandydaci).
Nazwisko w pliku PKW jest CAPS; imiona — Title Case.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from geo.pkw import col, fetch_source, iter_csv_rows_from_zip, norm_teryt

PKW_CATALOG_URL = (
    "https://danewyborcze.kbw.gov.pl/indexb609.html?title=Parlament_Europejski_2024"
)
ELECTION_YEAR = 2024


@dataclass(frozen=True)
class EuroCandidate:
    district_nr: int
    list_nr: int
    list_position: int
    last_name: str
    first_name: str
    second_name: str
    residence_name: str
    residence_teryt: str
    committee: str


def parse_pkw_full_name(full: str) -> tuple[str, str, str]:
    """
    'Wioleta Barbara TOMCZAK' → (Wioleta, Barbara, Tomczak)
    'Łukasz KOPEĆ' → (Łukasz, '', Kopeć)
    'Róża Maria GRÄFIN VON THUN UND HOHENSTEIN' → (... , Gräfin Von Thun Und Hohenstein)
    """
    parts = (full or "").split()
    if not parts:
        return "", "", ""

    i = 0
    while i < len(parts) and not parts[i].isupper():
        i += 1
    given = parts[:i]
    surname_parts = parts[i:]
    if not surname_parts:
        surname_parts = [parts[-1]]
        given = parts[:-1]

    first = given[0] if given else ""
    second = " ".join(given[1:]) if len(given) > 1 else ""
    last = " ".join(_title_token(t) for t in surname_parts)
    return first, second, last


def _title_token(token: str) -> str:
    if not token:
        return token
    if token.isupper() or token.islower():
        return token[:1].upper() + token[1:].lower()
    return token


def iter_euro_candidates(path: Path | None = None) -> Iterator[EuroCandidate]:
    zip_path = path or fetch_source("kandydaci_euro")
    for row in iter_csv_rows_from_zip(zip_path):
        full = col(row, "Nazwisko i imiona")
        first, second, last = parse_pkw_full_name(full)
        teryt = norm_teryt(col(row, "TERYT m. z."), width=6)
        yield EuroCandidate(
            district_nr=int(col(row, "Nr okręgu")),
            list_nr=int(col(row, "Nr listy")),
            list_position=int(col(row, "Pozycja na liście")),
            last_name=last,
            first_name=first,
            second_name=second,
            residence_name=col(row, "Miejsce zamieszkania", "Gmina m. z."),
            residence_teryt=teryt,
            committee=col(row, "Nazwa komitetu"),
        )


def candidate_email(candidate: EuroCandidate, *, slug: str) -> str:
    """Unikalny email: okręg + slug (ten sam człowiek mógł startować w 2 okręgach)."""
    return f"euro{ELECTION_YEAR}.{candidate.district_nr}.{slug}@selectio.local"
