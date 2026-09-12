from django.db import migrations


def refresh_labels(apps, schema_editor):
    stage = apps.get_model("core", "WorkflowStage")
    labels = {
        "pending": (["Chưa xử lý", "Chưa liên hệ"], "Mới trong danh sách"),
        "interested": (["Tiềm năng", "Quan tâm"], "Có quan tâm"),
        "not_interested": (["Không phù hợp", "Không quan tâm"], "Chưa quan tâm"),
        "unreachable": (["Chưa liên hệ được"], "Không liên hệ được"),
        "submitted": (["Hoàn tất", "Đã hoàn tất xử lý"], "Hoàn tất mục tiêu"),
        "returned": (["Loại khỏi danh sách", "Trả về kho talent"],
                     "Đưa về chăm sóc dài hạn"),
    }
    for code, (old_labels, new_label) in labels.items():
        stage.objects.filter(domain="talent", code=code,
                             label__in=old_labels).update(label=new_label)


class Migration(migrations.Migration):
    dependencies = [("core", "0004_workflowstage_allowed_next")]
    operations = [migrations.RunPython(refresh_labels, migrations.RunPython.noop)]
