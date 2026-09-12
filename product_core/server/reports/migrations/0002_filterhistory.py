from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="FilterHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("module", models.CharField(choices=[("talent", "Talent Radar"), ("rb", "RB Radar")], db_index=True, max_length=20)),
                ("signature", models.CharField(max_length=64)),
                ("filters", models.JSONField(default=dict)),
                ("used_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="filter_history", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Lịch sử lọc", "verbose_name_plural": "Lịch sử lọc", "ordering": ["-used_at"]},
        ),
        migrations.AddConstraint(
            model_name="filterhistory",
            constraint=models.UniqueConstraint(fields=("owner", "module", "signature"), name="uq_filterhistory_owner_module_signature"),
        ),
    ]
