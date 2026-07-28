"""
Import kandydatów do Sejmu i Senatu 2023 z CSV KBW.

Jednostka terytorialna = zamieszkanie (TERYT m. z.).
Okręgi sejm-{n} / senat-{n} powinny już istnieć (import_pkw_poland).

Użycie:
  python manage.py import_pkw_sejm_senat_candidates
  python manage.py import_pkw_sejm_senat_candidates --chamber sejm
  python manage.py import_pkw_sejm_senat_candidates --chamber senat --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from elections.models import ElectoralDistrict, Office
from elections.pkw_candidate_import import (
    import_candidates_batch,
    municipality_by_teryt,
    unique_slug_for,
)
from elections.pkw_sejm_senat import (
    ELECTION_YEAR,
    PKW_CATALOG_URL,
    Chamber,
    ParliamentCandidate,
    candidate_email,
    iter_sejm_candidates,
    iter_senat_candidates,
)
from geo.models import TerritorialLevel
from geo.pkw import fetch_source


def ensure_parliament_offices() -> dict[str, Office]:
    level = TerritorialLevel.objects.filter(slug="country").first()
    specs = (
        (
            "posel-sejm",
            "Poseł na Sejm RP",
            "Okręgi sejmowe (PKW 2023).",
            10,
            21,
        ),
        (
            "senator",
            "Senator RP",
            "Okręgi senackie (PKW 2023).",
            20,
            30,
        ),
    )
    out: dict[str, Office] = {}
    for slug, name, desc, order, min_age in specs:
        office, _ = Office.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": desc,
                "is_open": True,
                "display_order": order,
                "min_age": min_age,
                "candidacy_level": level,
            },
        )
        out[slug] = office
    return out


def _email_for(cand: ParliamentCandidate, slug: str) -> str:
    return candidate_email(cand, slug)


class Command(BaseCommand):
    help = (
        "Import kandydatów do Sejmu i Senatu 2023 z CSV KBW "
        f"({PKW_CATALOG_URL})"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--chamber",
            choices=("both", "sejm", "senat"),
            default="both",
            help="Którą izbę importować (domyślnie obie)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tylko pokaż, co zostałoby utworzone",
        )
        parser.add_argument(
            "--force-fetch",
            action="store_true",
            help="Pobierz ponownie ZIP z KBW (ignoruj cache)",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Bez wypisywania każdego kandydata",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        quiet = options["quiet"]
        force = options["force_fetch"]
        chamber: str = options["chamber"]

        chambers: list[Chamber] = (
            ["sejm", "senat"] if chamber == "both" else [chamber]  # type: ignore[list-item]
        )

        if not dry:
            ensure_parliament_offices()

        units = municipality_by_teryt() if not dry else {}

        for ch in chambers:
            self._import_chamber(ch, dry=dry, quiet=quiet, force=force, units=units)

    def _import_chamber(
        self,
        chamber: Chamber,
        *,
        dry: bool,
        quiet: bool,
        force: bool,
        units: dict,
    ):
        source_key = f"kandydaci_{chamber}"
        zip_path = fetch_source(source_key, force=force)
        if chamber == "sejm":
            candidates = list(iter_sejm_candidates(zip_path))
            district_prefix = "sejm-"
            expected_districts = 41
        else:
            candidates = list(iter_senat_candidates(zip_path))
            district_prefix = "senat-"
            expected_districts = 100

        self.stdout.write(
            f"{chamber.upper()} {ELECTION_YEAR}: {len(candidates)} kandydatów "
            f"({zip_path.name})"
        )

        if dry:
            seen: set[str] = set()
            for cand in candidates[:5]:
                slug = unique_slug_for(cand, seen, email_for=_email_for)
                self.stdout.write(
                    f"  [{cand.district_nr}] {cand.last_name} {cand.first_name} "
                    f"{cand.second_name} | {candidate_email(cand, slug)} | "
                    f"TERYT {cand.residence_teryt}"
                )
            if len(candidates) > 5:
                self.stdout.write(f"  … i {len(candidates) - 5} kolejnych")
            self.stdout.write(self.style.WARNING(f"Dry-run ({chamber}) — brak zapisów."))
            return

        district_count = ElectoralDistrict.objects.filter(
            slug__startswith=district_prefix
        ).count()
        if district_count < expected_districts:
            self.stdout.write(
                self.style.WARNING(
                    f"Okręgów {district_prefix}* w DB: {district_count} "
                    f"(oczekiwano {expected_districts}). "
                    "Uruchom import_pkw_poland, jeśli brakuje mapowania."
                )
            )
        else:
            self.stdout.write(f"Okręgi {district_prefix}*: {district_count}")

        created, updated, missing_units = import_candidates_batch(
            candidates,
            email_prefix=f"{chamber}{ELECTION_YEAR}.",
            email_for=_email_for,
            units=units,
            stdout=self.stdout,
            quiet=quiet,
        )

        if missing_units:
            self.stdout.write(
                self.style.WARNING(
                    f"Bez jednostki terytorialnej ({chamber}): {missing_units}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{chamber.upper()}: utworzone {created}, zaktualizowane {updated}."
            )
        )
