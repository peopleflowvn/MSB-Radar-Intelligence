from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("people", "0008_contactmention_personlink_person_is_applicant_and_more")]

    operations = [
        migrations.AddIndex(
            model_name="document",
            index=models.Index(
                fields=["parse_status", "updated_at", "id"],
                name="people_docu_parse_s_4c2301_idx",
            ),
        ),
    ]
