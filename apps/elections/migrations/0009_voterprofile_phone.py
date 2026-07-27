import random

from django.conf import settings
from django.db import migrations, models


def assign_phones(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    VoterProfile = apps.get_model("elections", "VoterProfile")

    known_phones = {
        "demo": "+48500100100",
        "anna": "+48500100101",
        "jan": "+48500100102",
        "piotr": "+48500100103",
        "maria": "+48500100104",
        "ewa": "+48500100105",
        "tomasz": "+48500100106",
        "barbara": "+48500100107",
        "hanna": "+48500100108",
        "stefan": "+48500100109",
        "julia": "+48500100110",
        "adam": "+48500100111",
    }

    used: set[str] = set(
        VoterProfile.objects.exclude(phone="")
        .exclude(phone__isnull=True)
        .values_list("phone", flat=True)
    )
    used.update(known_phones.values())

    def next_phone() -> str:
        while True:
            candidate = f"+48{random.randint(500_000_000, 799_999_999)}"
            if candidate not in used:
                used.add(candidate)
                return candidate

    for user in User.objects.all().order_by("pk"):
        # Po ewentualnej wcześniejszej częściowej migracji username może być już u{id}.
        phone = known_phones.get(user.username)
        if phone is None:
            # Spróbuj zmapować po starym loginie zapisanym w emailu demo@…
            phone = next_phone()

        profile = VoterProfile.objects.filter(user_id=user.pk).first()
        if profile is None:
            VoterProfile.objects.create(user_id=user.pk, phone=phone)
        elif not profile.phone:
            profile.phone = phone
            profile.save(update_fields=["phone"])
        else:
            used.add(profile.phone)

        desired = f"u{user.pk}"
        if user.username != desired:
            clash = User.objects.filter(username=desired).exclude(pk=user.pk).exists()
            if not clash:
                user.username = desired
                user.save(update_fields=["username"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    """Dodaje telefon i wypełnia dane (bez unique — osobna migracja)."""

    dependencies = [
        ("elections", "0008_office_min_age_candidacy_level"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="voterprofile",
            name="phone",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Pełny numer w formacie +48XXXXXXXXX — używany do logowania.",
                max_length=16,
                verbose_name="telefon",
            ),
        ),
        migrations.RunPython(assign_phones, noop_reverse),
    ]
