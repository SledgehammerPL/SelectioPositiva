"""
Import kandydatów samorządowych 2024 z CSV/XLSX KBW.

Jednostka terytorialna = zamieszkanie (TERYT m. z.).
Okręgi powinny istnieć (import_pkw_poland).

Użycie:
  python manage.py import_pkw_samorzad_candidates
  python manage.py import_pkw_samorzad_candidates --kind sejmik
  python manage.py import_pkw_samorzad_candidates --kind gmina,wbp --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from elections.models import ElectoralDistrict, Office
from elections.pkw_candidate_import import (
    import_candidates_batch,
    municipality_by_teryt,
    unique_slug_for,
)
from elections.pkw_samorzad import (
    ELECTION_YEAR,
    PKW_CATALOG_URL,
    Kind,
    SamorzadCandidate,
    candidate_email,
    iter_gmina_candidates,
    iter_powiat_and_dzielnica_candidates,
    iter_sejmik_candidates,
    iter_wbp_candidates,
)
from elections.services.identity import build_identity_index
from geo.models import TerritorialLevel
from geo.pkw import fetch_source
from geo.pkw.warsaw_dzielnice import ensure_warsaw_dzielnica_districts

KIND_SPECS: dict[Kind, dict] = {
    "sejmik": {
        "label": "Sejmiki wojewodztw",
        "email_prefix": f"sejmik{ELECTION_YEAR}.",
        "office_slug": "radny-sejmiku",
        "district_prefix": "sejmik-",
        "sources": ("kandydaci_sejmik",),
        "iterator": iter_sejmik_candidates,
    },
    "powiat": {
        "label": "Rady powiatow + dzielnice Warszawy",
        "email_prefix": f"radapowiat{ELECTION_YEAR}.",
        "office_slug": "radny-powiatu",
        "district_prefix": "rada-powiat-",
        "sources": ("kandydaci_rada_powiatu", "kandydaci_rada_dzielnic"),
        "iterator": iter_powiat_and_dzielnica_candidates,
    },
    "gmina": {
        "label": "Rady gmin (do 20k + powyzej 20k)",
        "email_prefix": f"radagminy{ELECTION_YEAR}.",
        "office_slug": "radny-gminy",
        "district_prefix": "rada-gminy-",
        "sources": ("kandydaci_rada_gminy_gt20", "kandydaci_rada_gminy_lt20"),
        "iterator": iter_gmina_candidates,
    },
    "wbp": {
        "label": "Wojt / Burmistrz / Prezydent",
        "email_prefix": f"wbp{ELECTION_YEAR}.",
        "office_slug": "wojt-burmistrz-prezydent",
        "district_prefix": "wbp-",
        "sources": ("kandydaci_wbp",),
        "iterator": iter_wbp_candidates,
    },
}

OFFICE_DEFAULTS = {
    # slug → name, desc, order, min_age, candidacy_level, results_visibility
    "radny-sejmiku": (
        "Radny sejmiku wojewodztwa",
        "Okregi sejmikow (PKW 2024).",
        30,
        18,
        "voivodeship",
        "voivodeship",
    ),
    "radny-powiatu": (
        "Radny rady powiatu / dzielnicy",
        "Okregi rad powiatow i dzielnic m.st. Warszawy (PKW 2024).",
        40,
        18,
        "county",
        "county",
    ),
    "radny-gminy": (
        "Radny rady gminy / miasta",
        "Okregi rad gmin (PKW 2024).",
        50,
        18,
        "municipality",
        "municipality",
    ),
    "wojt-burmistrz-prezydent": (
        "Wojt / Burmistrz / Prezydent",
        "Wybory wojtow, burmistrzow i prezydentow (PKW 2024).",
        60,
        25,
        "country",
        "municipality",
    ),
}


def _email_for(cand: SamorzadCandidate, slug: str) -> str:
    return candidate_email(cand, slug)


def ensure_samorzad_offices() -> None:
    levels = {lv.slug: lv for lv in TerritorialLevel.objects.all()}
    for slug, (name, desc, order, min_age, cand_slug, results_slug) in OFFICE_DEFAULTS.items():
        Office.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": desc,
                "is_open": True,
                "display_order": order,
                "min_age": min_age,
                "candidacy_level": levels.get(cand_slug),
                "results_visibility_level": levels.get(results_slug),
            },
        )


class Command(BaseCommand):
    help = (
        "Import kandydatów samorządowych 2024 z KBW "
        f"({PKW_CATALOG_URL})"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--kind",
            default="all",
            help="sejmik,powiat,gmina,wbp albo all (domyślnie)",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force-fetch", action="store_true")
        parser.add_argument("--quiet", action="store_true")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        quiet = options["quiet"]
        force = options["force_fetch"]
        kind_arg = (options["kind"] or "all").strip().lower()
        if kind_arg == "all":
            kinds: list[Kind] = ["sejmik", "powiat", "gmina", "wbp"]
        else:
            kinds = []
            for part in kind_arg.split(","):
                part = part.strip()
                if part not in KIND_SPECS:
                    raise SystemExit(f"Nieznany kind={part!r}. Dozwolone: {', '.join(KIND_SPECS)}")
                kinds.append(part)  # type: ignore[arg-type]

        if not dry:
            ensure_samorzad_offices()

        units = municipality_by_teryt() if not dry else {}
        identity_index = None if dry else build_identity_index()

        for kind in kinds:
            self._import_kind(
                kind,
                dry=dry,
                quiet=quiet,
                force=force,
                units=units,
                identity_index=identity_index,
            )

    def _import_kind(
        self,
        kind: Kind,
        *,
        dry: bool,
        quiet: bool,
        force: bool,
        units: dict,
        identity_index,
    ):
        spec = KIND_SPECS[kind]
        for source_key in spec["sources"]:
            path = fetch_source(source_key, force=force)
            self.stdout.write(f"Źródło {source_key}: {path.name}")

        if kind == "gmina":
            candidates = list(iter_gmina_candidates())
        elif kind == "powiat":
            if not dry:
                dstats = ensure_warsaw_dzielnica_districts()
                self.stdout.write(
                    f"Dzielnice Warszawy: okręgi={dstats['districts']} "
                    f"(new={dstats['created']}, upd={dstats['updated']})"
                )
            candidates = list(iter_powiat_and_dzielnica_candidates())
        else:
            # pojedyncze źródło — przekaż path z cache
            path = fetch_source(spec["sources"][0], force=force)
            candidates = list(spec["iterator"](path))

        self.stdout.write(
            f"{spec['label']}: {len(candidates)} kandydatów ({kind})"
        )

        if dry:
            seen: set[str] = set()
            for cand in candidates[:5]:
                slug = unique_slug_for(cand, seen, email_for=_email_for)
                self.stdout.write(
                    f"  [{cand.district_slug}] {cand.last_name} {cand.first_name} "
                    f"{cand.second_name} | {candidate_email(cand, slug)} | "
                    f"TERYT {cand.residence_teryt}"
                )
            if len(candidates) > 5:
                self.stdout.write(f"  … i {len(candidates) - 5} kolejnych")
            self.stdout.write(self.style.WARNING(f"Dry-run ({kind}) — brak zapisów."))
            return

        n_dist = ElectoralDistrict.objects.filter(
            slug__startswith=spec["district_prefix"]
        ).count()
        self.stdout.write(f"Okręgi {spec['district_prefix']}*: {n_dist}")

        created, updated, reused, missing_units = import_candidates_batch(
            candidates,
            email_prefix=spec["email_prefix"],
            email_for=_email_for,
            units=units,
            stdout=self.stdout,
            quiet=quiet,
            identity_index=identity_index,
        )

        if missing_units:
            self.stdout.write(
                self.style.WARNING(
                    f"Bez jednostki terytorialnej ({kind}): {missing_units}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{kind.upper()}: utworzone {created}, "
                f"zaktualizowane {updated}, po tożsamości {reused}."
            )
        )
