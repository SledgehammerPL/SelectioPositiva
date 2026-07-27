# Generated manually for served_units M2M

import django.db.models.deletion
from django.db import migrations, models


def populate_served_units(apps, schema_editor):
    """
    Startowy zbiór: lokalizacja siedziby.
    Dla znanych komisji Katowice/Warszawa — pełny zestaw jednostek (nie drzewo).
    """
    PollingStation = apps.get_model("geo", "PollingStation")
    TerritorialUnit = apps.get_model("geo", "TerritorialUnit")
    Through = PollingStation.served_units.through

    by_slug = {u.slug: u for u in TerritorialUnit.objects.all()}

    katowice_slugs = (
        "polska",
        "slaskie",
        "okreg-katowice",
        "gmina-katowice",
        "okreg-miejski-katowice",
    )
    warsaw_slugs = (
        "polska",
        "mazowieckie",
        "okreg-warszawa",
        "gmina-warszawa",
    )
    katowice_ids = [by_slug[s].pk for s in katowice_slugs if s in by_slug]
    warsaw_ids = [by_slug[s].pk for s in warsaw_slugs if s in by_slug]

    location_gmina_ktw = by_slug.get("gmina-katowice")
    location_okreg_miejski = by_slug.get("okreg-miejski-katowice")
    location_gmina_waw = by_slug.get("gmina-warszawa")

    rows = []
    for station in PollingStation.objects.all().iterator():
        unit_ids: list[int] = []
        loc_id = station.territorial_unit_id
        if location_gmina_ktw and loc_id in {
            location_gmina_ktw.pk,
            *( [location_okreg_miejski.pk] if location_okreg_miejski else [] ),
        }:
            unit_ids = katowice_ids or ([loc_id] if loc_id else [])
        elif location_gmina_waw and loc_id == location_gmina_waw.pk:
            unit_ids = warsaw_ids or ([loc_id] if loc_id else [])
        elif loc_id:
            unit_ids = [loc_id]

        for uid in unit_ids:
            rows.append(
                Through(
                    pollingstation_id=station.pk,
                    territorialunit_id=uid,
                )
            )

    if rows:
        Through.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ("geo", "0002_polling_station_number_streets"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pollingstation",
            name="territorial_unit",
            field=models.ForeignKey(
                help_text="Jednostka, w której fizycznie znajduje się komisja.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="located_polling_stations",
                to="geo.territorialunit",
                verbose_name="lokalizacja (siedziba)",
            ),
        ),
        migrations.AddField(
            model_name="pollingstation",
            name="served_units",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Zbiór jednostek, na które wyborcy z tej komisji mogą głosować "
                    "(kraj, województwo, okręgi Sejmu/Senatu/sejmiku, gmina itd.)."
                ),
                related_name="serving_polling_stations",
                to="geo.territorialunit",
                verbose_name="obsługiwane jednostki terytorialne",
            ),
        ),
        migrations.RunPython(populate_served_units, migrations.RunPython.noop),
    ]
