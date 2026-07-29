from django.db import migrations, models
import django.db.models.deletion


# slug urzędu → poziom widoczności wyników
RESULTS_VISIBILITY_BY_SLUG = {
    "prezydent-rp": "country",
    "eurodeputowany": "voivodeship",
    "posel-sejm": "voivodeship",
    "senator": "voivodeship",
    "radny-sejmiku": "voivodeship",
    "radny-powiatu": "county",
    "radny-gminy": "municipality",
    "wojt-burmistrz-prezydent": "municipality",
}


def set_results_visibility(apps, schema_editor):
    Office = apps.get_model("elections", "Office")
    TerritorialLevel = apps.get_model("geo", "TerritorialLevel")
    levels = {lv.slug: lv for lv in TerritorialLevel.objects.all()}
    for office in Office.objects.all():
        slug = RESULTS_VISIBILITY_BY_SLUG.get(office.slug)
        if slug is None and office.candidacy_level_id:
            # fallback: skopiuj poziom kandydatury
            office.results_visibility_level_id = office.candidacy_level_id
            office.save(update_fields=["results_visibility_level"])
            continue
        level = levels.get(slug) if slug else None
        if level is not None:
            office.results_visibility_level = level
            office.save(update_fields=["results_visibility_level"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("geo", "0008_remove_geo_coordinates"),
        ("elections", "0012_remove_phone_add_second_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="office",
            name="results_visibility_level",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Na jakim poziomie filtra wyników pokazujemy ten urząd. "
                    "Kraj = wybory wspólne dla całego kraju (np. prezydent); "
                    "województwo = Sejm/Senat/PE/sejmik w wybranym województwie; "
                    "powiat = rada powiatu; gmina = rada gminy i wójt/burmistrz/prezydent."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="offices_for_results",
                to="geo.territoriallevel",
                verbose_name="poziom widoczności wyników",
            ),
        ),
        migrations.RunPython(set_results_visibility, noop_reverse),
    ]
