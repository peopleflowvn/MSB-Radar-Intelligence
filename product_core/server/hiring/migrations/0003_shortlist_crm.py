# Generated manually for the recruiter-owned shortlist CRM.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("hiring", "0002_huntcandidate_alter_huntrequest_people_and_more")]

    operations = [
        migrations.AlterModelOptions(
            name="huntrequest",
            options={"ordering": ["-created_at"],
                     "verbose_name": "Shortlist xử lý ứng viên",
                     "verbose_name_plural": "Shortlist xử lý ứng viên"},
        ),
        migrations.AddField(
            model_name="huntrequest", name="title",
            field=models.CharField(blank=True, default="", max_length=200,
                                   verbose_name="Tên shortlist")),
        migrations.AlterField(
            model_name="huntrequest", name="hiring_need",
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="hunt_requests", to="hiring.hiringneed")),
        migrations.AddField(
            model_name="huntrequest", name="priority",
            field=models.CharField(choices=[("low", "Thấp"), ("normal", "Bình thường"),
                                            ("high", "Cao"), ("urgent", "Khẩn cấp")],
                                   db_index=True, default="normal", max_length=10)),
        migrations.AddField(
            model_name="huntcandidate", name="next_action_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True)),
        migrations.AddField(
            model_name="huntcandidate", name="priority",
            field=models.CharField(choices=[("low", "Thấp"), ("normal", "Bình thường"),
                                            ("high", "Cao"), ("urgent", "Khẩn cấp")],
                                   db_index=True, default="normal", max_length=10)),
        migrations.AlterField(
            model_name="huntcandidate", name="state",
            field=models.CharField(choices=[
                ("pending", "Chưa liên hệ"), ("contacting", "Đang liên hệ"),
                ("responded", "Đã phản hồi"), ("interested", "Quan tâm"),
                ("not_interested", "Không quan tâm"),
                ("unreachable", "Không liên hệ được"),
                ("submitted", "Đã hoàn tất xử lý"),
                ("returned", "Trả về kho talent")],
                db_index=True, default="pending", max_length=20),
        ),
        migrations.AlterField(
            model_name="huntrequest", name="people",
            field=models.ManyToManyField(blank=True, help_text="Ứng viên trong shortlist",
                                         related_name="hunt_requests",
                                         through="hiring.HuntCandidate", to="people.person"),
        ),
    ]
