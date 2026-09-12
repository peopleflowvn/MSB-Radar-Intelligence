from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("talent", "0002_titlesimilarity_and_more")]

    operations = [
        migrations.AddField(
            model_name="pool",
            name="domain",
            field=models.CharField(
                choices=[("talent", "Ứng viên"), ("rb", "Khách hàng")],
                db_index=True,
                default="talent",
                max_length=20,
            ),
        ),
    ]
