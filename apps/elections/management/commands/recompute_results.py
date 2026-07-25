"""Przelicz wyniki Schulzego per okręg i zapisz w ElectionResultCache."""

from django.core.management.base import BaseCommand

from elections.models import ElectoralDistrict
from elections.services import recompute_all_results, recompute_district_results


class Command(BaseCommand):
    help = "Przelicza wyniki Schulzego (wszystkie okręgi lub --district=slug)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--district",
            type=str,
            default="",
            help="Slug okręgu do przeliczenia (domyślnie wszystkie).",
        )
        parser.add_argument(
            "--office",
            type=str,
            default="",
            help="Alias historyczny: przelicz wszystkie okręgi urzędu o podanym slug.",
        )

    def handle(self, *args, **options):
        district_slug = (options.get("district") or "").strip()
        office_slug = (options.get("office") or "").strip()

        if district_slug:
            district = ElectoralDistrict.objects.get(slug=district_slug)
            cache = recompute_district_results(district)
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK {district.slug}: {cache.ballot_count} głosów, "
                    f"seats={district.seats_count}"
                )
            )
            return

        if office_slug:
            qs = ElectoralDistrict.objects.filter(office__slug=office_slug)
            n = 0
            for district in qs:
                recompute_district_results(district)
                n += 1
            self.stdout.write(self.style.SUCCESS(f"Przeliczono {n} okręgów urzędu {office_slug}."))
            return

        n = recompute_all_results()
        self.stdout.write(self.style.SUCCESS(f"Przeliczono {n} okręgów."))
