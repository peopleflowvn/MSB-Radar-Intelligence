from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("talent", "0003_pool_domain"),
    ]

    operations = [
        migrations.CreateModel(
            name="TalentAIAnalysis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("cache_key", models.CharField(max_length=64, unique=True)),
                ("question", models.TextField()),
                ("normalized_question", models.TextField(db_index=True)),
                ("limit", models.PositiveSmallIntegerField(default=20)),
                ("version", models.PositiveSmallIntegerField(default=1)),
                ("status", models.CharField(
                    choices=[("processing", "Đang phân tích"), ("ready", "Sẵn sàng"),
                             ("failed", "Thất bại")], db_index=True,
                    default="processing", max_length=20)),
                ("criteria", models.JSONField(blank=True, default=dict)),
                ("trace", models.JSONField(blank=True, default=list)),
                ("results", models.JSONField(blank=True, default=list)),
                ("provider", models.CharField(blank=True, default="", max_length=40)),
                ("model", models.CharField(blank=True, default="", max_length=100)),
                ("error", models.CharField(blank=True, default="", max_length=500)),
                ("analyzed_at", models.DateTimeField(default=django.utils.timezone.now,
                                                      db_index=True)),
                ("last_used_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("hit_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL, related_name="+",
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-analyzed_at"],
                "indexes": [models.Index(fields=["status", "-analyzed_at"],
                                         name="talent_ai_status_time_idx")],
            },
        ),
    ]
