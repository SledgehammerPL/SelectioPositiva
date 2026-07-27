# Generated manually for served_districts M2M

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("elections", "0003_party_candidate_residence"),
        ("geo", "0004_teryt_county_station_code"),
    ]

    operations = [
        migrations.AlterField(
            model_name="territorialunit",
            name="kind",
            field=models.CharField(
                choices=[
                    ("country", "Kraj"),
                    ("voivodeship", "Województwo"),
                    ("county", "Powiat"),
                    ("district", "Okręg wyborczy (przestarzałe)"),
                    ("municipality", "Gmina"),
                ],
                max_length=20,
                verbose_name="rodzaj",
            ),
        ),
        migrations.AlterField(
            model_name="territorialunit",
            name="teryt",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Kod TERYT (2/4/6 cyfr) dla jednostek administracyjnych.",
                max_length=7,
                verbose_name="TERYT",
            ),
        ),
        migrations.AlterField(
            model_name="pollingstation",
            name="served_units",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Jednostki administracyjne związane z komisją "
                    "(kraj, województwo, powiat, gmina)."
                ),
                related_name="serving_polling_stations",
                to="geo.territorialunit",
                verbose_name="obsługiwane jednostki terytorialne",
            ),
        ),
        migrations.AddField(
            model_name="pollingstation",
            name="served_districts",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Okręgi, w których wyborcy z tej komisji oddają głos "
                    "(np. konkretny okręg rady gminy, Sejmu, Senatu)."
                ),
                related_name="serving_polling_stations",
                to="elections.electoraldistrict",
                verbose_name="obsługiwane okręgi wyborcze",
            ),
        ),
    ]
