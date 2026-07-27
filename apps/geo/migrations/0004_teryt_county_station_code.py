# Generated manually — TERYT + powiat + dłuższy kod komisji

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("geo", "0003_polling_station_served_units"),
    ]

    operations = [
        migrations.AddField(
            model_name="territorialunit",
            name="teryt",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "Kod TERYT (2/4/6 cyfr) dla jednostek administracyjnych; "
                    "puste dla okręgów wyborczych."
                ),
                max_length=7,
                verbose_name="TERYT",
            ),
        ),
        migrations.AlterField(
            model_name="territorialunit",
            name="kind",
            field=models.CharField(
                choices=[
                    ("country", "Kraj"),
                    ("voivodeship", "Województwo"),
                    ("county", "Powiat"),
                    ("district", "Okręg wyborczy"),
                    ("municipality", "Gmina"),
                ],
                max_length=20,
                verbose_name="rodzaj",
            ),
        ),
        migrations.AlterField(
            model_name="pollingstation",
            name="code",
            field=models.CharField(max_length=64, unique=True, verbose_name="kod"),
        ),
    ]
