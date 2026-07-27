"""Pomocnicze funkcje do pobierania i parsowania danych PKW (KBW Dane Wyborcze)."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Iterable, Iterator
from urllib.request import Request, urlopen

PKW_BASE = "https://danewyborcze.kbw.gov.pl/"

SOURCES = {
    "obwody": "dane/2024/samorzad/obwody_glosowania_csv.zip",
    "okregi_sejm": "dane/2023/sejmsenat/okregi_sejm_csv.zip",
    "okregi_senat": "dane/2023/sejmsenat/okregi_senat_csv.zip",
    "okregi_sejmik": "dane/2024/samorzad/okregi_sejmiki_wojewodztw_csv.zip",
    "okregi_rada_powiatu": "dane/2024/samorzad/okregi_rady_powiatow_csv.zip",
    "okregi_rada_gminy": "dane/2024/samorzad/okregi_rady_gmin_csv.zip",
    "okregi_wbp": "dane/2024/samorzad/okregi_wojt_burmistrz_prezydent_csv.zip",
    "prot_sejm": "dane/2023/sejmsenat/protokoly_po_obwodach_sejm_csv.zip",
    "prot_senat": "dane/2023/sejmsenat/protokoly_po_obwodach_senat_csv.zip",
    "prot_sejmik": "dane/2024/samorzad/protokoly_po_obwodach_sejmik_wojewodztwa_csv.zip",
    "prot_rada_powiatu": "dane/2024/samorzad/protokoly_po_obwodach_rada_powiatu_csv.zip",
    "prot_rada_gminy_gt20": "dane/2024/samorzad/protokoly_po_obwodach_rady_gmin_powyzej_20k_csv.zip",
    "prot_rada_gminy_lt20": "dane/2024/samorzad/protokoly_po_obwodach_rady_gmin_do_20k_csv.zip",
}


def default_cache_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "pkw" / "cache"


def norm_teryt(value: str, width: int = 6) -> str:
    digits = "".join(c for c in (value or "").strip() if c.isdigit())
    if not digits:
        return ""
    return digits.zfill(width)


def fetch_source(key: str, cache_dir: Path | None = None, *, force: bool = False) -> Path:
    if key not in SOURCES:
        raise KeyError(f"Nieznane źródło PKW: {key}")
    cache_dir = cache_dir or default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    rel = SOURCES[key]
    dest = cache_dir / Path(rel).name
    if dest.exists() and dest.stat().st_size > 1000 and not force:
        return dest
    url = PKW_BASE + rel
    req = Request(url, headers={"User-Agent": "SelectioPositiva/1.0 (PKW import)"})
    with urlopen(req, timeout=300) as resp:
        dest.write_bytes(resp.read())
    return dest


def iter_csv_rows_from_zip(path: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        for name in names:
            raw = zf.read(name)
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text), delimiter=";")
            for row in reader:
                yield {
                    (k or "").strip(): (v or "").strip()
                    for k, v in row.items()
                    if k is not None
                }


def col(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row:
            return row[name]
    lower = {k.lower(): k for k in row}
    for name in names:
        key = lower.get(name.lower())
        if key is not None:
            return row[key]
    raise KeyError(f"Brak kolumn {names} w {list(row)[:12]}")
