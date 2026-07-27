from django.db import migrations, models


LEVELS = [
    ("country", "Kraj", 0),
    ("voivodeship", "Województwo", 1),
    ("county", "Powiat", 2),
    ("municipality", "Gmina", 3),
    ("precinct", "Obwód wyborczy", 4),
    ("district", "Okręg wyborczy (przestarzałe)", 5),
]


def seed_levels(apps, schema_editor):
    TerritorialLevel = apps.get_model("geo", "TerritorialLevel")
    for slug, name, order in LEVELS:
        TerritorialLevel.objects.update_or_create(
            slug=slug,
            defaults={"name": name, "display_order": order},
        )


def unseed_levels(apps, schema_editor):
    TerritorialLevel = apps.get_model("geo", "TerritorialLevel")
    TerritorialLevel.objects.filter(slug__in=[s for s, _, _ in LEVELS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("geo", "0006_precinct_kind_polling_station"),
    ]

    operations = [
        migrations.CreateModel(
            name="TerritorialLevel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100, verbose_name="nazwa")),
                ("slug", models.SlugField(max_length=40, unique=True, verbose_name="slug")),
                (
                    "display_order",
                    models.PositiveSmallIntegerField(
                        db_index=True,
                        default=0,
                        help_text="Mniejsza wartość = szerszy zasięg (kraj=0, …, obwód=4).",
                        verbose_name="kolejność",
                    ),
                ),
            ],
            options={
                "verbose_name": "poziom terytorialny",
                "verbose_name_plural": "poziomy terytorialne",
                "ordering": ["display_order", "name"],
            },
        ),
        migrations.RunPython(seed_levels, unseed_levels),
    ]
