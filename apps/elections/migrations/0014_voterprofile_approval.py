from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def approve_existing_profiles(apps, schema_editor):
    VoterProfile = apps.get_model("elections", "VoterProfile")
    VoterProfile.objects.all().update(is_approved=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("elections", "0013_office_results_visibility_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="voterprofile",
            name="is_approved",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "Czy profil jest zatwierdzony do rankingów. "
                    "Użytkownik zatwierdza siebie w profilu; "
                    "admin zatwierdza osoby zgłoszone przez innych."
                ),
                verbose_name="zatwierdzony",
            ),
        ),
        migrations.AddField(
            model_name="voterprofile",
            name="request_note",
            field=models.TextField(
                blank=True, default="", verbose_name="uwaga ze zgłoszenia"
            ),
        ),
        migrations.AddField(
            model_name="voterprofile",
            name="approved_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="zatwierdzono"
            ),
        ),
        migrations.AddField(
            model_name="voterprofile",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="approved_voter_profiles",
                to=settings.AUTH_USER_MODEL,
                verbose_name="zatwierdził",
            ),
        ),
        migrations.AddField(
            model_name="voterprofile",
            name="requested_by",
            field=models.ForeignKey(
                blank=True,
                help_text="Ustawiane, gdy ktoś inny poprosił o dodanie tej osoby.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="requested_candidate_profiles",
                to=settings.AUTH_USER_MODEL,
                verbose_name="zgłoszony przez",
            ),
        ),
        migrations.RunPython(approve_existing_profiles, noop_reverse),
        migrations.DeleteModel(name="CandidateRequest"),
    ]
