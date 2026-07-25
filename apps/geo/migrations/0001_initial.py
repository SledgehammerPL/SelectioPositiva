import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="TerritorialUnit",
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
                ("name", models.CharField(max_length=200, verbose_name="nazwa")),
                ("slug", models.SlugField(max_length=200, unique=True, verbose_name="slug")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("country", "Kraj"),
                            ("voivodeship", "Województwo"),
                            ("district", "Okręg"),
                            ("municipality", "Gmina"),
                        ],
                        max_length=20,
                        verbose_name="rodzaj",
                    ),
                ),
                (
                    "boundary",
                    models.JSONField(
                        blank=True,
                        null=True,
                        verbose_name="granica (GeoJSON)",
                    ),
                ),
                (
                    "center_lat",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=9,
                        null=True,
                        verbose_name="środek (szerokość)",
                    ),
                ),
                (
                    "center_lng",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=9,
                        null=True,
                        verbose_name="środek (długość)",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="geo.territorialunit",
                        verbose_name="jednostka nadrzędna",
                    ),
                ),
            ],
            options={
                "verbose_name": "jednostka terytorialna",
                "verbose_name_plural": "jednostki terytorialne",
                "ordering": ["kind", "name"],
            },
        ),
        migrations.CreateModel(
            name="PollingStation",
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
                ("name", models.CharField(max_length=200, verbose_name="nazwa")),
                ("code", models.CharField(max_length=32, unique=True, verbose_name="kod")),
                ("address", models.CharField(max_length=300, verbose_name="adres")),
                (
                    "latitude",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=9,
                        null=True,
                        verbose_name="szerokość geograficzna",
                    ),
                ),
                (
                    "longitude",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=9,
                        null=True,
                        verbose_name="długość geograficzna",
                    ),
                ),
                (
                    "territorial_unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="polling_stations",
                        to="geo.territorialunit",
                        verbose_name="jednostka terytorialna",
                    ),
                ),
            ],
            options={
                "verbose_name": "komisja wyborcza",
                "verbose_name_plural": "komisje wyborcze",
                "ordering": ["name"],
            },
        ),
    ]
