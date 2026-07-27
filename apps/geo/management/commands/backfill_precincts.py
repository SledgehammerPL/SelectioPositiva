"""
Tworzy TerritorialUnit(kind=precinct) dla każdej komisji bez obwodu
i ustawia PollingStation.precinct.

Kod komisji PKW: ``{TERYT_gminy}-{numer}`` → parent = gmina o tym TERYT.

Użycie:
  python manage.py backfill_precincts
  python manage.py backfill_precincts --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from geo.models import PollingStation, TerritorialUnit

BATCH = 2000


def precinct_slug(station_code: str) -> str:
    return f"obwod-{slugify(station_code)}"


def precinct_name(number: int | None, gmina_name: str, streets: str = "") -> str:
    nr = f"nr {number}" if number is not None else ""
    base = f"Obwód {nr} — {gmina_name}".strip(" —")
    if streets:
        short = streets.strip().replace("\n", " ")[:80]
        if short:
            return f"{base} ({short})"[:200]
    return base[:200]


class Command(BaseCommand):
    help = "Tworzy obwody (TerritorialUnit.PRECINCT) na podstawie PollingStation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tylko policz, bez zapisu.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        gminy = {
            u.teryt: u
            for u in TerritorialUnit.objects.filter(
                kind=TerritorialUnit.Kind.MUNICIPALITY
            ).exclude(teryt="")
            if u.teryt
        }
        self.stdout.write(f"Gminy z TERYT: {len(gminy)}")

        qs = (
            PollingStation.objects.filter(precinct__isnull=True)
            .only("id", "code", "number", "name", "streets_served")
            .order_by("id")
        )
        total = qs.count()
        self.stdout.write(f"Komisje bez obwodu: {total}")
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nic do zrobienia."))
            return

        existing_slugs = set(
            TerritorialUnit.objects.filter(kind=TerritorialUnit.Kind.PRECINCT)
            .values_list("slug", flat=True)
        )

        created = linked = skipped = 0
        to_create_units: list[TerritorialUnit] = []
        pending_links: list[tuple[int, str]] = []  # (station_id, precinct_slug)

        def flush():
            nonlocal created, linked
            if not to_create_units:
                return
            if dry:
                created += len(to_create_units)
                linked += len(pending_links)
                to_create_units.clear()
                pending_links.clear()
                return

            TerritorialUnit.objects.bulk_create(to_create_units, batch_size=BATCH)
            slug_to_id = dict(
                TerritorialUnit.objects.filter(
                    slug__in=[u.slug for u in to_create_units]
                ).values_list("slug", "id")
            )
            created += len(to_create_units)
            updates = []
            for station_id, slug in pending_links:
                pid = slug_to_id.get(slug)
                if pid:
                    updates.append(
                        PollingStation(pk=station_id, precinct_id=pid)
                    )
            if updates:
                PollingStation.objects.bulk_update(
                    updates, ["precinct_id"], batch_size=BATCH
                )
                linked += len(updates)
            to_create_units.clear()
            pending_links.clear()

        with transaction.atomic():
            for station in qs.iterator(chunk_size=BATCH):
                code = station.code or ""
                teryt = code.split("-", 1)[0] if "-" in code else ""
                gmina = gminy.get(teryt)
                if gmina is None:
                    skipped += 1
                    continue

                slug = precinct_slug(code)
                if slug in existing_slugs:
                    # Obwód już istnieje — tylko podepnij komisję.
                    if not dry:
                        existing = TerritorialUnit.objects.filter(slug=slug).only("id").first()
                        if existing:
                            PollingStation.objects.filter(pk=station.pk).update(
                                precinct_id=existing.pk
                            )
                            linked += 1
                    else:
                        linked += 1
                    continue

                existing_slugs.add(slug)
                to_create_units.append(
                    TerritorialUnit(
                        name=precinct_name(
                            station.number, gmina.name, station.streets_served or ""
                        ),
                        slug=slug,
                        kind=TerritorialUnit.Kind.PRECINCT,
                        parent=gmina,
                        teryt="",
                    )
                )
                pending_links.append((station.pk, slug))

                if len(to_create_units) >= BATCH:
                    flush()
                    self.stdout.write(f"  … utworzono {created}, podpięto {linked}")

            flush()

            if dry:
                transaction.set_rollback(True)

        style = self.style.WARNING if dry else self.style.SUCCESS
        self.stdout.write(
            style(
                f"{'[DRY-RUN] ' if dry else ''}"
                f"Obwody utworzone: {created}, komisje podpięte: {linked}, "
                f"pominięte (brak gminy): {skipped}."
            )
        )
