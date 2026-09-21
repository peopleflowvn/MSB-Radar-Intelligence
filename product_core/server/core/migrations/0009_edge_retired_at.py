from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0008_edge_data_report_edge_data_reported_at")]

    operations = [
        migrations.AddField(
            model_name="edge",
            name="retired_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Đã gỡ kết nối lúc"
            ),
        ),
    ]
