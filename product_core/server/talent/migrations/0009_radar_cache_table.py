# -*- coding: utf-8 -*-
"""Tạo bảng cho `DatabaseCache` (settings.CACHES → LOCATION "radar_cache").

Django có lệnh `createcachetable`, nhưng để nó ngoài migration nghĩa là mỗi lần
dựng môi trường mới lại phải nhớ chạy tay — quên một lần là mọi lượt hỏi ném lỗi
"relation radar_cache does not exist". Đưa vào migration thì `manage.py migrate`
trong CMD của container lo trọn.

Chỉ `RunSQL`, không khai model: đây là bảng của Django cache framework, không
phải của nghiệp vụ. Khai thành model `managed=False` chỉ làm `makemigrations`
sau này phải bận tâm tới một thứ không ai đọc bằng ORM.

Khuôn bảng lấy đúng theo `django.core.management.commands.createcachetable`.
`timestamp with time zone` là kiểu của PostgreSQL; SQLite (máy dev) chấp nhận
nhờ type affinity lỏng, nên không cần rẽ nhánh theo vendor.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("talent", "0008_embeddingconfig_alter_cvchunk_embedding_and_more")]

    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE TABLE IF NOT EXISTS radar_cache ("
                "  cache_key varchar(255) NOT NULL PRIMARY KEY,"
                "  value text NOT NULL,"
                "  expires timestamp with time zone NOT NULL)",
                "CREATE INDEX IF NOT EXISTS radar_cache_expires "
                "  ON radar_cache (expires)",
            ],
            reverse_sql=["DROP TABLE IF EXISTS radar_cache"],
        ),
    ]
