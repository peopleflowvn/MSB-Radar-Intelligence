from django.db import migrations, models
from django.db.models import F
import django.utils.timezone


def preserve_existing_stage_time(apps, schema_editor):
    candidate = apps.get_model("hiring", "HuntCandidate")
    candidate.objects.filter(stage_entered_at__isnull=True).update(
        stage_entered_at=F("updated_at"))


class Migration(migrations.Migration):
    dependencies = [("hiring", "0005_alter_huntcandidate_state")]

    operations = [
        migrations.AddField(
            model_name="huntcandidate",
            name="stage_entered_at",
            field=models.DateTimeField(null=True, db_index=True),
        ),
        migrations.RunPython(preserve_existing_stage_time, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="huntcandidate",
            name="stage_entered_at",
            field=models.DateTimeField(default=django.utils.timezone.now, db_index=True),
        ),
    ]
