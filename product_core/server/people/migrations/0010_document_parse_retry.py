from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("people", "0009_document_intelligence_feed_index")]

    operations = [
        migrations.AddField(
            model_name="document",
            name="parse_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="document",
            name="next_parse_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
