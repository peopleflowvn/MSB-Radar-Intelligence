from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("talent", "0011_embeddingconfig_greennode_model_and_more")]

    operations = [
        migrations.CreateModel(
            name="IntelligenceDocumentTombstone",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_id", models.BigIntegerField(db_index=True)),
                ("person_id", models.BigIntegerField()),
                ("version", models.CharField(max_length=64)),
                ("content_hash", models.CharField(max_length=64)),
                ("source", models.CharField(default="radar", max_length=40)),
                ("document_type", models.CharField(default="cv", max_length=40)),
                ("deleted_at", models.DateTimeField(db_index=True)),
            ],
            options={"ordering": ["deleted_at", "pk"]},
        ),
        migrations.AddIndex(
            model_name="intelligencedocumenttombstone",
            index=models.Index(fields=["deleted_at", "id"], name="talent_inte_deleted_3f6637_idx"),
        ),
    ]
