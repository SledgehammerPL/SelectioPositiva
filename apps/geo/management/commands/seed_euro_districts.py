"""Utwórz / odśwież 13 okręgów do Parlamentu Europejskiego."""

from django.core.management.base import BaseCommand

from geo.pkw.euro_districts import ensure_euro_districts


class Command(BaseCommand):
    help = (
        "Tworzy 13 okręgów PE (województwa / pary / powiaty Mazowsza) "
        "i wiąże je z jednostkami terytorialnymi."
    )

    def handle(self, *args, **options):
        stats = ensure_euro_districts()
        self.stdout.write(
            self.style.SUCCESS(
                f"PE: districts={stats['districts']} "
                f"created={stats['created']} updated={stats['updated']} "
                f"linked_units={stats['linked_units']}"
            )
        )
