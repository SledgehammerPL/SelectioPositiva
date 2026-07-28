"""
Kandydaci na Prezydenta RP 2025 — dane z obwieszczenia PKW.

Obwieszczenie PKW: imiona, wiek, miejsce zamieszkania.
Jednostka terytorialna profilu = gmina/powiat zamieszkania (z PKW).
Data urodzenia (opcjonalnie) z publicznych biografii — PKW podaje tylko wiek.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Oficjalne PDF obwieszczenia PKW (23.04.2025).
PKW_CANDIDATES_PDF_URL = (
    "https://prezydent2025.pkw.gov.pl/prezydent2025/statics/"
    "PKW_OBWIESZCZENIA/uploaded_files/"
    "1745431277_obwieszczenie-o-zarejestrowanych-kandydatach.pdf"
)

ELECTION_DAY = date(2025, 5, 18)


@dataclass(frozen=True)
class BirthDateHint:
    """Dokładna data urodzenia (PKW podaje tylko wiek)."""

    last_name: str
    birth_date: date


# Klucz: nazwisko UPPER jak w obwieszczeniu PKW.
BIRTH_DATES: dict[str, BirthDateHint] = {
    "BARTOSZEWICZ": BirthDateHint("BARTOSZEWICZ", date(1974, 1, 18)),
    "BIEJAT": BirthDateHint("BIEJAT", date(1982, 1, 11)),
    "BRAUN": BirthDateHint("BRAUN", date(1967, 3, 11)),
    "HOŁOWNIA": BirthDateHint("HOŁOWNIA", date(1976, 9, 3)),
    "JAKUBIAK": BirthDateHint("JAKUBIAK", date(1959, 4, 30)),
    "MACIAK": BirthDateHint("MACIAK", date(1970, 7, 30)),
    "MENTZEN": BirthDateHint("MENTZEN", date(1986, 11, 20)),
    "NAWROCKI": BirthDateHint("NAWROCKI", date(1983, 3, 3)),
    "SENYSZYN": BirthDateHint("SENYSZYN", date(1949, 2, 1)),
    "STANOWSKI": BirthDateHint("STANOWSKI", date(1982, 5, 21)),
    "TRZASKOWSKI": BirthDateHint("TRZASKOWSKI", date(1972, 1, 17)),
    "WOCH": BirthDateHint("WOCH", date(1978, 12, 17)),
    "ZANDBERG": BirthDateHint("ZANDBERG", date(1979, 12, 4)),
}

# Locativus z PDF PKW → (nazwa do wyszukania, teryt|None, kind).
# Warszawa = powiat (dzielnice jako gminy w TERYT).
RESIDENCE_MAP: dict[str, tuple[str, str | None, str]] = {
    "warszawie": ("Warszawa", "1465", "county"),
    "rzeszowie": ("Rzeszów", "186301", "municipality"),
    "otwocku": ("Otwock", "141702", "municipality"),
    "toruniu": ("Toruń", "046301", "municipality"),
    "włocławku": ("Włocławek", "046401", "municipality"),
    "gdansku": ("Gdańsk", "226101", "municipality"),
    "gdańsku": ("Gdańsk", "226101", "municipality"),
    "wilczej górze": ("Lesznowola", "141803", "municipality"),
    "kąkolewnicy": ("Kąkolewnica", "061504", "municipality"),
}


def approximate_birth_date(age: int, *, on: date = ELECTION_DAY) -> date:
    """Przybliżona data urodzenia z wieku na dzień wyborów (1 stycznia roku)."""
    return date(on.year - age, 1, 1)


def default_cache_path() -> Path:
    # apps/elections/pkw_presidential.py → project root = parents[2]
    return (
        Path(__file__).resolve().parents[2]
        / "data"
        / "pkw"
        / "cache"
        / "obwieszczenie-o-zarejestrowanych-kandydatach.pdf"
    )
