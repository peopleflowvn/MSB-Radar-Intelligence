from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_login_policies(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Policy = apps.get_model("accounts", "UserLoginPolicy")
    existing = set(Policy.objects.values_list("user_id", flat=True))
    Policy.objects.bulk_create([
        Policy(user_id=user_id, login_type="local")
        for user_id in User.objects.values_list("id", flat=True)
        if user_id not in existing
    ], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0006_userloginpolicy"),
    ]

    operations = [
        migrations.RemoveConstraint("externalidentity", "uq_external_identity_subject"),
        migrations.RemoveConstraint("externalidentity", "uq_external_identity_user_tenant"),
        migrations.AddField(
            model_name="externalidentity", name="revoked_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True)),
        migrations.AddField(
            model_name="externalidentity", name="revoke_reason",
            field=models.CharField(blank=True, default="", max_length=300)),
        migrations.AddField(
            model_name="externalidentity", name="revoked_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="revoked_identities", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(
            model_name="authenticationevent", name="actor",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="auth_events_performed", to=settings.AUTH_USER_MODEL)),
        migrations.AddConstraint(
            model_name="externalidentity",
            constraint=models.UniqueConstraint(condition=models.Q(("revoked_at__isnull", True)),
                                               fields=("provider", "tenant_id", "object_id"),
                                               name="uq_active_external_identity_subject")),
        migrations.AddConstraint(
            model_name="externalidentity",
            constraint=models.UniqueConstraint(condition=models.Q(("revoked_at__isnull", True)),
                                               fields=("user", "provider", "tenant_id"),
                                               name="uq_active_external_identity_user_tenant")),
        migrations.RunPython(backfill_login_policies, migrations.RunPython.noop),
    ]
