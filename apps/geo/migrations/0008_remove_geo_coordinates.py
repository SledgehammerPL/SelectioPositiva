from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("geo", "0007_territorial_level"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="territorialunit",
            name="boundary",
        ),
        migrations.RemoveField(
            model_name="territorialunit",
            name="center_lat",
        ),
        migrations.RemoveField(
            model_name="territorialunit",
            name="center_lng",
        ),
        migrations.RemoveField(
            model_name="pollingstation",
            name="latitude",
        ),
        migrations.RemoveField(
            model_name="pollingstation",
            name="longitude",
        ),
    ]
