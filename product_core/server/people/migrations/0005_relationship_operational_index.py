from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("people", "0004_relationship_operational_fields")]

    operations = [
        migrations.AddIndex(
            model_name="relationship",
            index=models.Index(
                fields=["domain", "owner_user", "do_not_contact", "next_action_at"],
                name="people_rel_owner_due"),
        ),
    ]
