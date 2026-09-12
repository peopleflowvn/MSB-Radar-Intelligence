from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def normalize_talent_states(apps, schema_editor):
    relationship = apps.get_model("people", "Relationship")
    mapping = {
        "contacted": "attempted", "warm": "connected", "hot": "interested",
        "cool": "unavailable", "re_engagement": "nurturing",
    }
    for old, new in mapping.items():
        relationship.objects.filter(domain="talent", state=old).update(state=new)


class Migration(migrations.Migration):
    dependencies = [
        ("people", "0003_alter_document_options_document_file_size_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name="relationship", name="owner_user", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="owned_relationships", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="relationship", name="interest_level", field=models.PositiveSmallIntegerField(default=0, help_text="0 chưa rõ; 1..5 tăng dần")),
        migrations.AddField(model_name="relationship", name="last_contact_at", field=models.DateTimeField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="relationship", name="next_action", field=models.CharField(blank=True, default="", max_length=300)),
        migrations.AddField(model_name="relationship", name="next_action_at", field=models.DateTimeField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="relationship", name="preferred_channel", field=models.CharField(blank=True, default="", max_length=30)),
        migrations.AddField(model_name="relationship", name="do_not_contact", field=models.BooleanField(db_index=True, default=False)),
        migrations.AddField(model_name="relationship", name="reason", field=models.CharField(blank=True, default="", max_length=300)),
        migrations.AddField(model_name="relationship", name="notes", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="relationship", name="preferences", field=models.JSONField(blank=True, default=dict)),
        migrations.RunPython(normalize_talent_states, migrations.RunPython.noop),
    ]
