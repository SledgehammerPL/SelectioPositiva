# Generated manually — drop Candidate.office

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("elections", "0004_candidate_citizenship"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="candidate",
            name="office",
        ),
    ]
