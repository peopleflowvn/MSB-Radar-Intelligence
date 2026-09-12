# Generated manually for the Microsoft SSO integration.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0004_contactunlockpolicy_contactunlocklog"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(default="microsoft", max_length=30)),
                ("realm", models.CharField(choices=[("tntalent", "TNTalent"), ("msb", "MSB")], max_length=20)),
                ("tenant_id", models.CharField(max_length=36)),
                ("object_id", models.CharField(max_length=36)),
                ("username_snapshot", models.CharField(blank=True, default="", max_length=254)),
                ("display_name_snapshot", models.CharField(blank=True, default="", max_length=200)),
                ("linked_at", models.DateTimeField(auto_now_add=True)),
                ("last_login_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="external_identities", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="AuthenticationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(db_index=True, default="microsoft", max_length=30)),
                ("realm", models.CharField(blank=True, db_index=True, default="", max_length=20)),
                ("result", models.CharField(db_index=True, max_length=40)),
                ("tenant_id", models.CharField(blank=True, default="", max_length=36)),
                ("object_id_hash", models.CharField(blank=True, default="", max_length=64)),
                ("username_masked", models.CharField(blank=True, default="", max_length=254)),
                ("ip", models.CharField(blank=True, default="", max_length=64)),
                ("user_agent", models.CharField(blank=True, default="", max_length=300)),
                ("correlation_id", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("detail", models.CharField(blank=True, default="", max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="authentication_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="externalidentity",
            constraint=models.UniqueConstraint(fields=("provider", "tenant_id", "object_id"), name="uq_external_identity_subject"),
        ),
        migrations.AddConstraint(
            model_name="externalidentity",
            constraint=models.UniqueConstraint(fields=("user", "provider", "tenant_id"), name="uq_external_identity_user_tenant"),
        ),
        migrations.AddIndex(
            model_name="externalidentity",
            index=models.Index(fields=["provider", "tenant_id", "object_id"], name="accounts_ex_provide_8db87a_idx"),
        ),
        migrations.AddIndex(
            model_name="authenticationevent",
            index=models.Index(fields=["result", "-created_at"], name="accounts_au_result_09355f_idx"),
        ),
    ]
