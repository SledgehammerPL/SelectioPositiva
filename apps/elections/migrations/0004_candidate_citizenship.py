# Generated manually — Candidate.citizenship

import django.db.models.deletion
from django.db import migrations, models


def backfill_polish_citizenship(apps, schema_editor):
    Candidate = apps.get_model("elections", "Candidate")
    TerritorialUnit = apps.get_model("geo", "TerritorialUnit")
    poland = (
        TerritorialUnit.objects.filter(kind="country", slug="polska").first()
        or TerritorialUnit.objects.filter(kind="country").order_by("id").first()
    )
    if poland is None:
        return
    Candidate.objects.filter(citizenship__isnull=True).update(citizenship_id=poland.pk)


class Migration(migrations.Migration):

    dependencies = [
        ("elections", "0003_party_candidate_residence"),
        ("geo", "0004_teryt_county_station_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="candidate",
            name="citizenship",
            field=models.ForeignKey(
                help_text=(
                    "Kraj obywatelstwa. W wyborach w Polsce wymagane jest "
                    "obywatelstwo polskie."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="citizen_candidates",
                to="geo.territorialunit",
                verbose_name="obywatelstwo",
            ),
        ),
        migrations.RunPython(backfill_polish_citizenship, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="candidate",
            name="citizenship",
            field=models.ForeignKey(
                help_text=(
                    "Kraj obywatelstwa. W wyborach w Polsce wymagane jest "
                    "obywatelstwo polskie."
                ),
                on_delete=django.db.models.deletion.PROTECT,
                related_name="citizen_candidates",
                to="geo.territorialunit",
                verbose_name="obywatelstwo",
            ),
        ),
    ]
