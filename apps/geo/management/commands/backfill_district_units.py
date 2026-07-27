"""
Odbudowuje ElectoralDistrict.territorial_units z protokołów PKW.

Użycie:
  python manage.py backfill_district_units
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from geo.pkw import SOURCES, fetch_source
from geo.pkw.district_units import rebuild_district_units


class Command(BaseCommand):
    help = "Odbudowuje M2M okręg ↔ jednostki terytorialne z protokołów PKW."

    def add_arguments(self, parser):
        parser.add_argument(
            "--download",
            action="store_true",
            help="Wymuś ponowne pobranie ZIP-ów PKW.",
        )

    def handle(self, *args, **options):
        self.stdout.write("Pobieranie / weryfikacja źródeł PKW…")
        paths = {
            key: fetch_source(key, force=options["download"])
            for key in SOURCES
            if key.startswith("prot_")
            or key in ("okregi_sejm",)  # ensure cache dir ok
        }
        # Potrzebujemy wszystkich protokołów
        paths = {key: fetch_source(key, force=options["download"]) for key in SOURCES}
        for key, path in paths.items():
            if key.startswith("prot_"):
                self.stdout.write(f"  {key}: {path.name}")

        stats = rebuild_district_units(
            paths, log=lambda msg: self.stdout.write(f"  {msg}")
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"OK: powiązań={stats['links']}, "
                f"okręgi z jednostkami={stats['districts_with_units']}/{stats['districts_pkw']}, "
                f"fallback={stats['fallback']}\n"
                f"  sejm={stats['sejm_linked']} senat={stats['senat_linked']} "
                f"sejmik={stats['sejmik_linked']} "
                f"rada_powiat={stats['rada_powiat_linked']} "
                f"rada_gminy={stats['rada_gminy_linked']} "
                f"wbp={stats['wbp_linked']}"
            )
        )
