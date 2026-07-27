# Generated manually — Party, Candidate refactor, Office.requires_local_residence

import django.db.models.deletion
from django.db import migrations, models


def set_residence_flags(apps, schema_editor):
    Office = apps.get_model("elections", "Office")
    for slug in ("radny-gminy", "radny-powiatu", "radny-sejmiku"):
        Office.objects.filter(slug=slug).update(requires_local_residence=True)


def wipe_ballots_and_candidates(apps, schema_editor):
    apps.get_model("elections", "Ballot").objects.all().delete()
    apps.get_model("elections", "Candidate").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("elections", "0002_ballot_ranked_ids_and_committee"),
        ("geo", "0004_teryt_county_station_code"),
    ]

    operations = [
        migrations.CreateModel(
            name="Party",
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
                (
                    "slug",
                    models.SlugField(max_length=200, unique=True, verbose_name="slug"),
                ),
                (
                    "abbreviation",
                    models.CharField(blank=True, max_length=32, verbose_name="skrót"),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="aktywna")),
                (
                    "display_order",
                    models.PositiveIntegerField(default=0, verbose_name="kolejność"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "partia",
                "verbose_name_plural": "partie",
                "ordering": ["display_order", "name"],
            },
        ),
        migrations.AddField(
            model_name="office",
            name="requires_local_residence",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Jeśli włączone, kandydat musi mieszkać na terenie właściwym dla rady: "
                    "rada gminy → gmina, rada powiatu → powiat gminy zamieszkania, "
                    "sejmik → województwo, pozostałe urzędy → kraj."
                ),
                verbose_name="wymaga zamieszkania na terenie",
            ),
        ),
        migrations.RunPython(set_residence_flags, migrations.RunPython.noop),
        migrations.RunPython(wipe_ballots_and_candidates, migrations.RunPython.noop),
        migrations.RemoveField(model_name="candidate", name="district"),
        migrations.RemoveField(model_name="candidate", name="name"),
        migrations.AddField(
            model_name="candidate",
            name="office",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="candidates",
                to="elections.office",
                verbose_name="urząd",
            ),
        ),
        migrations.AddField(
            model_name="candidate",
            name="first_name",
            field=models.CharField(max_length=100, verbose_name="imię"),
        ),
        migrations.AddField(
            model_name="candidate",
            name="middle_name",
            field=models.CharField(
                blank=True, max_length=100, verbose_name="drugie imię"
            ),
        ),
        migrations.AddField(
            model_name="candidate",
            name="last_name",
            field=models.CharField(max_length=100, verbose_name="nazwisko"),
        ),
        migrations.AddField(
            model_name="candidate",
            name="birth_date",
            field=models.DateField(
                blank=True, null=True, verbose_name="data urodzenia"
            ),
        ),
        migrations.AddField(
            model_name="candidate",
            name="residence_municipality",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="resident_candidates",
                to="geo.territorialunit",
                verbose_name="gmina zamieszkania",
            ),
        ),
        migrations.AddField(
            model_name="candidate",
            name="parties",
            field=models.ManyToManyField(
                blank=True,
                related_name="candidates",
                to="elections.party",
                verbose_name="partie",
            ),
        ),
        migrations.AlterModelOptions(
            name="candidate",
            options={
                "ordering": ["last_name", "first_name", "display_order"],
                "verbose_name": "kandydat",
                "verbose_name_plural": "kandydaci",
            },
        ),
    ]
