"""
Kandydaci na Prezydenta RP 2025 — dane z obwieszczenia PKW (23.04.2025).

Źródło: https://prezydent2025.pkw.gov.pl/ (obwieszczenie o zarejestrowanych
kandydatach). Lista jest stała w kodzie — bez pobierania PDF / pypdf.

Jednostka terytorialna profilu = zamieszkanie z PKW (mapowane na TerritorialUnit).
Data urodzenia: dokładna z biografii publicznych albo przybliżenie z wieku PKW.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

ELECTION_DAY = date(2025, 5, 18)

PKW_OBWIESZCZENIE_URL = (
    "https://prezydent2025.pkw.gov.pl/prezydent2025/pl/pkw_obwieszczenia/69029"
)


@dataclass(frozen=True)
class PresidentialCandidate:
    last_name: str
    first_name: str
    second_name: str
    age: int
    """Wiek wg obwieszczenia PKW (na wybory 18.05.2025)."""
    residence_key: str
    """Klucz do RESIDENCE_MAP (locativus z PKW, lower)."""
    birth_date: date | None = None
    """Dokładna data urodzenia, jeśli znana; inaczej z age."""


# Kolejność jak w obwieszczeniu PKW.
CANDIDATES: tuple[PresidentialCandidate, ...] = (
    PresidentialCandidate("Bartoszewicz", "Artur", "", 51, "warszawie", date(1974, 1, 18)),
    PresidentialCandidate("Biejat", "Magdalena", "Agnieszka", 43, "warszawie", date(1982, 1, 11)),
    PresidentialCandidate("Braun", "Grzegorz", "Michał", 58, "rzeszowie", date(1967, 3, 11)),
    PresidentialCandidate("Hołownia", "Szymon", "Franciszek", 48, "otwocku", date(1976, 9, 3)),
    PresidentialCandidate("Jakubiak", "Marek", "", 66, "warszawie", date(1959, 4, 30)),
    PresidentialCandidate("Maciak", "Maciej", "", 54, "włocławku", date(1970, 7, 30)),
    PresidentialCandidate("Mentzen", "Sławomir", "Jerzy", 38, "toruniu", date(1986, 11, 20)),
    PresidentialCandidate("Nawrocki", "Karol", "Tadeusz", 42, "gdańsku", date(1983, 3, 3)),
    PresidentialCandidate("Senyszyn", "Joanna", "", 76, "warszawie", date(1949, 2, 1)),
    PresidentialCandidate("Stanowski", "Krzysztof", "Jakub", 42, "wilczej górze", date(1982, 5, 21)),
    PresidentialCandidate("Trzaskowski", "Rafał", "Kazimierz", 53, "warszawie", date(1972, 1, 17)),
    PresidentialCandidate("Woch", "Marek", "Marian", 46, "kąkolewnicy", date(1978, 12, 17)),
    PresidentialCandidate("Zandberg", "Adrian", "Tadeusz", 45, "warszawie", date(1979, 12, 4)),
)

# Locativus z PKW → (nazwa, teryt|None, kind). Warszawa = powiat (dzielnice).
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
    return date(on.year - age, 1, 1)


def birth_date_for(candidate: PresidentialCandidate) -> date:
    if candidate.birth_date is not None:
        return candidate.birth_date
    return approximate_birth_date(candidate.age, on=ELECTION_DAY)
