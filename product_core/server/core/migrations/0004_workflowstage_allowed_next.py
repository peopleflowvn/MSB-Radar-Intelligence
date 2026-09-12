from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0003_workflowstage_and_more")]
    operations = [migrations.AddField(
        model_name="workflowstage", name="allowed_next",
        field=models.JSONField(blank=True, default=list,
                               help_text="Mã bước được phép chuyển tới; rỗng là không giới hạn"))]
