"""
Import obwodowych komisji wyborczych z danych PKW (arkusz obwodów).

Domyślnie: Katowice (TERYT 246901) z lokalnego CSV wygenerowanego
z oficjalnego XLSX wyborów prezydenckich 2025.

Użycie:
  python manage.py import_pkw_stations
  python manage.py import_pkw_stations --city Katowice
  python manage.py import_pkw_stations --file data/pkw/katowice_obwody.csv
  python manage.py import_pkw_stations --download   # pobierz pełny XLSX PKW i wyfiltruj
"""

from __future__ import annotations

import csv
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from geo.models import PollingStation, TerritorialUnit

# Oficjalny ZIP z listą obwodów (II tura prezydent 2025).
PKW_OBWODY_ZIP_URL = (
    "https://prezydent2025.pkw.gov.pl/prezydent2025/data/csv/"
    "obwody_glosowania_w_drugiej_turze_xlsx.1758650309.zip"
)

# Filtry miast: teryt gminy + nazwa w kolumnie Gmina.
CITY_FILTERS = {
    "katowice": {"teryt": "246901", "gmina": "m. Katowice"},
}

BASE_DIR = Path(__file__).resolve().parents[4]
DEFAULT_CSV = BASE_DIR / "data" / "pkw" / "katowice_obwody.csv"


def _ensure_katowice_units() -> TerritorialUnit:
    """Gmina Katowice (parent obwodów)."""
    poland, _ = TerritorialUnit.objects.get_or_create(
        slug="polska",
        defaults={
            "name": "Polska",
            "kind": TerritorialUnit.Kind.COUNTRY,
            "parent": None,
        },
    )
    slask, _ = TerritorialUnit.objects.get_or_create(
        slug="slaskie",
        defaults={
            "name": "Województwo Śląskie",
            "kind": TerritorialUnit.Kind.VOIVODESHIP,
            "parent": poland,
        },
    )
    gmina, _ = TerritorialUnit.objects.update_or_create(
        slug="gmina-katowice",
        defaults={
            "name": "Gmina Katowice",
            "kind": TerritorialUnit.Kind.MUNICIPALITY,
            "parent": slask,
            "teryt": CITY_FILTERS["katowice"]["teryt"],
        },
    )
    return gmina


def _ensure_precinct(code: str, number: int | None, gmina: TerritorialUnit, streets: str = "") -> TerritorialUnit:
    from django.utils.text import slugify

    slug = f"obwod-{slugify(code)}"
    nr = f"nr {number}" if number is not None else ""
    name = f"Obwód {nr} — {gmina.name}".strip(" —")[:200]
    precinct, _ = TerritorialUnit.objects.update_or_create(
        slug=slug,
        defaults={
            "name": name,
            "kind": TerritorialUnit.Kind.PRECINCT,
            "parent": gmina,
        },
    )
    return precinct


def _station_code(teryt: str, numer: str) -> str:
    return f"{teryt}-{numer}"


def _build_address(row: dict) -> str:
    full = (row.get("pelna_siedziba") or "").strip()
    if full:
        return full[:300]
    parts = [
        (row.get("siedziba") or "").strip(),
        (row.get("ulica") or "").strip(),
        (row.get("nr_posesji") or "").strip(),
        (row.get("kod_pocztowy") or "").strip(),
        (row.get("miejscowosc") or "").strip(),
    ]
    return ", ".join(p for p in parts if p)[:300]


def _iter_csv_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            yield {k.strip(): (v or "").strip() for k, v in row.items() if k}


def _download_and_filter_katowice(dest_csv: Path) -> int:
    """Pobiera XLSX PKW i zapisuje CSV tylko dla Katowic."""
    try:
        import openpyxl
    except ImportError as exc:
        raise CommandError("Zainstaluj openpyxl: pip install openpyxl") from exc

    dest_csv.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(PKW_OBWODY_ZIP_URL, timeout=120) as resp:
        raw = resp.read()
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
        if not names:
            raise CommandError("Brak pliku XLSX w archiwum PKW.")
        xlsx_bytes = zf.read(names[0])

    tmp = dest_csv.parent / "_tmp_obwody.xlsx"
    tmp.write_bytes(xlsx_bytes)
    wb = openpyxl.load_workbook(tmp, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    next(rows)  # header
    canon = [
        "teryt",
        "gmina",
        "powiat",
        "wojewodztwo",
        "numer",
        "mieszkancy",
        "wyborcy",
        "pakiety",
        "siedziba",
        "miejscowosc",
        "ulica",
        "nr_posesji",
        "nr_lokalu",
        "kod_pocztowy",
        "poczta",
        "typ_obwodu",
        "dla_niepelnosprawnych",
        "typ_obszaru",
        "pelna_siedziba",
        "opis_granic",
    ]
    filt = CITY_FILTERS["katowice"]
    count = 0
    with dest_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(canon)
        for row in rows:
            teryt = str(row[0] or "").strip()
            gmina = str(row[1] or "").strip()
            if teryt != filt["teryt"] and gmina != filt["gmina"]:
                continue
            vals = ["" if x is None else str(x).strip() for x in row[:20]]
            w.writerow(vals)
            count += 1
    wb.close()
    tmp.unlink(missing_ok=True)
    return count


class Command(BaseCommand):
    help = "Importuje komisje wyborcze PKW (domyślnie Katowice) do PollingStation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--city",
            default="katowice",
            help="Miasto do importu (na razie: katowice).",
        )
        parser.add_argument(
            "--file",
            type=str,
            default="",
            help="Ścieżka do CSV (;, UTF-8) z obwodami.",
        )
        parser.add_argument(
            "--download",
            action="store_true",
            help="Pobierz pełny XLSX z PKW i wygeneruj CSV dla miasta.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tylko pokaż liczbę rekordów, bez zapisu.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        city = (options["city"] or "katowice").strip().lower()
        if city not in CITY_FILTERS:
            raise CommandError(
                f"Nieobsługiwane miasto: {city}. Dostępne: {', '.join(CITY_FILTERS)}"
            )
        filt = CITY_FILTERS[city]

        csv_path = Path(options["file"]) if options["file"] else DEFAULT_CSV
        if options["download"] or not csv_path.exists():
            self.stdout.write(f"Pobieranie danych PKW → {csv_path} …")
            n = _download_and_filter_katowice(csv_path)
            self.stdout.write(self.style.SUCCESS(f"Zapisano {n} obwodów do CSV."))

        if not csv_path.exists():
            raise CommandError(f"Brak pliku: {csv_path}")

        rows = [
            r
            for r in _iter_csv_rows(csv_path)
            if r.get("teryt") == filt["teryt"] or r.get("gmina") == filt["gmina"]
        ]
        if not rows:
            raise CommandError("Brak wierszy po filtrze miasta.")

        self.stdout.write(f"Do importu: {len(rows)} komisji ({filt['gmina']}).")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run — bez zapisu."))
            return

        gmina = _ensure_katowice_units()
        created = updated = 0
        for row in rows:
            teryt = row.get("teryt") or filt["teryt"]
            numer = row.get("numer") or ""
            if not numer:
                continue
            code = _station_code(teryt, numer)
            name = (row.get("siedziba") or f"Obwód nr {numer}")[:200]
            address = _build_address(row)
            try:
                number = int(str(numer).strip())
            except ValueError:
                number = None
            streets = (row.get("opis_granic") or "").strip()
            precinct = _ensure_precinct(code, number, gmina, streets)
            station, was_created = PollingStation.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "number": number,
                    "precinct": precinct,
                    "address": address or f"Katowice, obwód {numer}",
                    "streets_served": streets,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"OK: utworzono {created}, zaktualizowano {updated}. "
                f"Gmina: {gmina}."
            )
        )
