import django.db.models.deletion
from django.db import migrations, models


# slug urzędu → (min_age, candidacy_level_slug)
OFFICE_DEFAULTS = {
    "prezydent-rp": (35, "country"),
    "eurodeputowany": (21, "country"),
    "posel-sejm": (21, "country"),
    "senator": (30, "country"),
    "prezydent-miasta": (18, "country"),
    "wojt-burmistrz-prezydent": (18, "country"),
    "radny-sejmiku": (18, "voivodeship"),
    "radny-powiatu": (18, "county"),
    "radny-gminy": (18, "municipality"),
    "radny": (18, "municipality"),
}


def forwards(apps, schema_editor):
    Office = apps.get_model("elections", "Office")
    ElectoralDistrict = apps.get_model("elections", "ElectoralDistrict")
    TerritorialLevel = apps.get_model("geo", "TerritorialLevel")

    levels = {lvl.slug: lvl for lvl in TerritorialLevel.objects.all()}

    for office in Office.objects.all():
        # Weź najwyższy min_age z okręgów (np. prezydent RP = 35).
        max_age = (
            ElectoralDistrict.objects.filter(office_id=office.pk)
            .order_by("-min_age")
            .values_list("min_age", flat=True)
            .first()
        )
        defaults = OFFICE_DEFAULTS.get(office.slug)
        if defaults:
            age, level_slug = defaults
            office.min_age = max(age, max_age or 0) if max_age else age
            office.candidacy_level = levels.get(level_slug)
        else:
            office.min_age = max_age or 18
            office.candidacy_level = levels.get("municipality")
        office.save(update_fields=["min_age", "candidacy_level"])


def backwards(apps, schema_editor):
    Office = apps.get_model("elections", "Office")
    ElectoralDistrict = apps.get_model("elections", "ElectoralDistrict")
    for office in Office.objects.all():
        ElectoralDistrict.objects.filter(office_id=office.pk).update(
            min_age=office.min_age
        )


class Migration(migrations.Migration):

    dependencies = [
        ("geo", "0007_territorial_level"),
        ("elections", "0007_remove_voterprofile_polling_station"),
    ]

    operations = [
        migrations.AddField(
            model_name="office",
            name="min_age",
            field=models.PositiveSmallIntegerField(
                default=18,
                help_text="Minimalny wiek (w latach) wymagany do głosowania i kandydowania.",
                verbose_name="minimalny wiek",
            ),
        ),
        migrations.AddField(
            model_name="office",
            name="candidacy_level",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Na jakim poziomie hierarchii kandydat musi pokrywać się z okręgiem. "
                    "Np. kraj = każdy z kraju; gmina = ta sama gmina; "
                    "województwo = to samo województwo."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="offices",
                to="geo.territoriallevel",
                verbose_name="poziom kandydatury",
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name="electoraldistrict",
            name="min_age",
        ),
    ]
