"""
Import kandydatów do PE 2024 z CSV KBW (danewyborcze.kbw.gov.pl).

Jednostka terytorialna = zamieszkanie (TERYT m. z.).
Zapewnia urząd eurodeputowany + 13 okręgów (euro-1…euro-13).

Użycie:
  python manage.py import_pkw_euro_candidates
  python manage.py import_pkw_euro_candidates --dry-run
  python manage.py import_pkw_euro_candidates --force-fetch
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from elections.pkw_candidate_import import (
    import_candidates_batch,
    municipality_by_teryt,
    unique_slug_for,
)
from elections.pkw_euro import (
    ELECTION_YEAR,
    PKW_CATALOG_URL,
    candidate_email,
    iter_euro_candidates,
)
from geo.pkw import fetch_source
from geo.pkw.euro_districts import ensure_euro_districts


def _email_for(cand, slug: str) -> str:
    return candidate_email(cand, slug=slug)


class Command(BaseCommand):
    help = (
        "Import kandydatów do Parlamentu Europejskiego 2024 z CSV KBW "
        f"({PKW_CATALOG_URL})"
    )

    def add_arguments(self, parser):
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

        zip_path = fetch_source("kandydaci_euro", force=options["force_fetch"])
        candidates = list(iter_euro_candidates(zip_path))
        self.stdout.write(f"Kandydatów w CSV: {len(candidates)} ({zip_path.name})")

        if dry:
            seen: set[str] = set()
            for cand in candidates[:5]:
                slug = unique_slug_for(cand, seen, email_for=_email_for)
                self.stdout.write(
                    f"  [{cand.district_nr}] {cand.last_name} {cand.first_name} "
                    f"{cand.second_name} | {candidate_email(cand, slug=slug)} | "
                    f"TERYT {cand.residence_teryt}"
                )
            if len(candidates) > 5:
                self.stdout.write(f"  … i {len(candidates) - 5} kolejnych")
            self.stdout.write(self.style.WARNING("Dry-run — brak zapisów."))
            return

        stats = ensure_euro_districts()
        self.stdout.write(
            f"Okręgi PE: {stats['districts']} "
            f"(utworzone={stats['created']}, zaktualizowane={stats['updated']})"
        )

        created, updated, reused, missing_units = import_candidates_batch(
            candidates,
            email_prefix=f"euro{ELECTION_YEAR}.",
            email_for=_email_for,
            units=municipality_by_teryt(),
            stdout=self.stdout,
            quiet=quiet,
        )

        if missing_units:
            self.stdout.write(
                self.style.WARNING(
                    f"Bez jednostki terytorialnej: {missing_units} kandydatów "
                    "(zaimportuj TERYT / import_pkw_poland)."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Gotowe. Utworzone: {created}, zaktualizowane: {updated}, "
                f"po tożsamości: {reused}."
            )
        )
