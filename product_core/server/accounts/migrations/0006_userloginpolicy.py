from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0005_externalidentity_authenticationevent"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserLoginPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("login_type", models.CharField(choices=[("local", "Tài khoản thường"), ("tntalent", "Microsoft — TNTalent"), ("msb", "Microsoft — MSB")], db_index=True, default="local", max_length=20)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="login_policy", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
