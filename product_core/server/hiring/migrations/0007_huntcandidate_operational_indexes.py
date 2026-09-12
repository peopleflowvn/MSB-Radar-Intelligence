from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hiring", "0006_huntcandidate_stage_entered_at")]

    operations = [
        migrations.AddIndex(
            model_name="huntcandidate",
            index=models.Index(
                fields=["assigned_to", "state", "next_action_at"],
                name="hiring_hc_owner_state_due"),
        ),
        migrations.AddIndex(
            model_name="huntcandidate",
            index=models.Index(fields=["person", "state"],
                               name="hiring_hc_person_state"),
        ),
    ]
