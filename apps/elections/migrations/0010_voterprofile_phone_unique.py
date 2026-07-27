from django.db import migrations, models


class Migration(migrations.Migration):
    """Unikalność telefonu — osobna transakcja po wypełnieniu danych."""

    dependencies = [
        ("elections", "0009_voterprofile_phone"),
    ]

    operations = [
        migrations.AlterField(
            model_name="voterprofile",
            name="phone",
            field=models.CharField(
                help_text="Pełny numer w formacie +48XXXXXXXXX — używany do logowania.",
                max_length=16,
                unique=True,
                verbose_name="telefon",
            ),
        ),
    ]
