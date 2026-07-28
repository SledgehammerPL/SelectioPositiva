"""
Import kandydatów na Prezydenta RP 2025 z obwieszczenia PKW.

Pobiera PDF PKW, tworzy konta User + VoterProfile. Jednostka terytorialna =
gmina/powiat zamieszkania z obwieszczenia (nie komisja).

Użycie:
  python manage.py import_pkw_presidential_candidates
  python manage.py import_pkw_presidential_candidates --download
  python manage.py import_pkw_presidential_candidates --dry-run
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from elections.models import ElectoralDistrict, Office, VoterProfile
from elections.pkw_presidential import (
    BIRTH_DATES,
    ELECTION_DAY,
    PKW_CANDIDATES_PDF_URL,
    RESIDENCE_MAP,
    approximate_birth_date,
    default_cache_path,
)
from geo.models import TerritorialLevel, TerritorialUnit
from users.services.accounts import ensure_user


@dataclass
class ParsedCandidate:
    last_name: str
    first_name: str
    second_name: str
    age: int
    residence: str
    party: str


def _strip_diacritics(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def fetch_pdf(dest: Path, *, force: bool = False) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000 and not force:
        return dest
    req = Request(
        PKW_CANDIDATES_PDF_URL,
        headers={"User-Agent": "SelectioPositiva/1.0 (PKW presidential import)"},
    )
    with urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())
    return dest


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_candidates(text: str) -> list[ParsedCandidate]:
    """
    Parsuje punkty 1)–13) obwieszczenia PKW.
    Format: NAZWISKO Imię [Drugie], lat N, … zamieszkały/a w X, …
    """
    compact = re.sub(r"\s+", " ", text)
    pattern = re.compile(
        r"(?:^|[;\s])(\d{1,2})\)\s+"
        r"([A-ZĄĆĘŁŃÓŚŹŻ][A-ZĄĆĘŁŃÓŚŹŻ\-]+)\s+"
        r"([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż\-]+)"
        r"(?:\s+([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż\-]+))?"
        r"\s*,\s*lat\s+(\d+)\s*,"
        r"(.*?)(?=(?:^|[;\s])\d{1,2}\)\s+[A-ZĄĆĘŁŃÓŚŹŻ]|$)",
        re.DOTALL,
    )
    results: list[ParsedCandidate] = []
    seen: set[str] = set()
    for m in pattern.finditer(compact):
        last = m.group(2).strip()
        if last in seen:
            continue
        seen.add(last)
        first = m.group(3).strip()
        second = (m.group(4) or "").strip()
        age = int(m.group(5))
        rest = m.group(6)
        res_m = re.search(
            r"zamieszka[łl][ya]\s+w(?:e)?\s+([^,;]+)",
            rest,
            re.IGNORECASE,
        )
        residence = (res_m.group(1).strip() if res_m else "").rstrip(".")
        party_m = re.search(
            r"(?:członek|członkini)\s+([^;]+)|nie należy do partii",
            rest,
            re.IGNORECASE,
        )
        if party_m:
            party = (
                "bezpartyjny"
                if "nie należy" in party_m.group(0).lower()
                else party_m.group(0).strip().rstrip(".")
            )
        else:
            party = ""
        results.append(
            ParsedCandidate(
                last_name=last,
                first_name=first,
                second_name=second,
                age=age,
                residence=residence,
                party=party,
            )
        )
    return results


def resolve_residence_unit(residence_raw: str) -> TerritorialUnit | None:
    """Mapuje 'zamieszkały w X' (często locativus) na TerritorialUnit."""
    raw = (residence_raw or "").strip()
    if not raw:
        return None

    key = raw.lower()
    mapped = RESIDENCE_MAP.get(key)
    if mapped is None:
        plain = _strip_diacritics(key)
        for k, v in RESIDENCE_MAP.items():
            if _strip_diacritics(k) == plain:
                mapped = v
                break

    if mapped:
        place, teryt, kind = mapped
        if kind == "country":
            return TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.COUNTRY
            ).first()
        if teryt:
            unit = TerritorialUnit.objects.filter(kind=kind, teryt=teryt).first()
            if unit:
                return unit
        return _lookup_place(place, kind=kind)

    return _lookup_place(raw, kind="municipality")


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


def birth_date_for(last_name: str, age: int):
    key = last_name.upper()
    hint = BIRTH_DATES.get(key)
    if hint is None:
        plain = _strip_diacritics(key)
        for k, v in BIRTH_DATES.items():
            if _strip_diacritics(k) == plain:
                hint = v
                break
    if hint:
        return hint.birth_date
    return approximate_birth_date(age, on=ELECTION_DAY)


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
        "Import kandydatów na Prezydenta RP 2025 z obwieszczenia PKW "
        "(jednostka = miejsce zamieszkania)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--download",
            action="store_true",
            help="Wymuś ponowne pobranie PDF z prezydent2025.pkw.gov.pl",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tylko pokaż, co zostałoby utworzone",
        )
        parser.add_argument(
            "--pdf",
            type=str,
            default="",
            help="Ścieżka do lokalnego PDF (domyślnie cache)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry = options["dry_run"]
        pdf_path = Path(options["pdf"]) if options["pdf"] else default_cache_path()
        if not options["pdf"]:
            self.stdout.write(f"Pobieram PDF PKW -> {pdf_path}")
            fetch_pdf(pdf_path, force=options["download"])
        elif not pdf_path.exists():
            self.stderr.write(self.style.ERROR(f"Brak pliku: {pdf_path}"))
            return

        text = extract_pdf_text(pdf_path)
        parsed = parse_candidates(text)
        if not parsed:
            self.stderr.write(self.style.ERROR("Nie udało się sparsować kandydatów z PDF."))
            return

        self.stdout.write(f"Znaleziono {len(parsed)} kandydatów w obwieszczeniu PKW.")
        if not dry:
            ensure_prezydent_office()

        created = updated = 0
        for cand in parsed:
            birth_date = birth_date_for(cand.last_name, cand.age)
            unit = resolve_residence_unit(cand.residence)

            email_slug = slugify(
                f"{cand.first_name}-{cand.last_name}", allow_unicode=False
            ) or _strip_diacritics(cand.last_name).lower()
            email = f"prezydent2025.{email_slug}@selectio.local"

            desired_last = "-".join(
                p.capitalize() for p in cand.last_name.lower().split("-")
            )
            unit_label = str(unit) if unit else "(brak jednostki)"
            self.stdout.write(
                f"  {desired_last} {cand.first_name} {cand.second_name} | "
                f"ur. {birth_date} | zam. {cand.residence} -> {unit_label}"
            )

            if dry:
                continue

            existed = VoterProfile.objects.filter(user__email__iexact=email).exists()
            user = ensure_user(
                email=email,
                password=None,
                first_name=cand.first_name,
                second_name=cand.second_name,
                last_name=desired_last,
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
