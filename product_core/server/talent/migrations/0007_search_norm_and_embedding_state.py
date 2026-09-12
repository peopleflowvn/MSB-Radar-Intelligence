# -*- coding: utf-8 -*-
"""Cột text đã bỏ dấu + trạng thái embedding, và chỉ mục full-text cho quy mô lớn.

`content_norm`/`text_norm` là bản bỏ dấu, hạ chữ thường của text gốc. PostgreSQL
đánh **chỉ mục biểu thức GIN** trên `to_tsvector('simple', <cột>)` — nhờ vậy tìm
theo từ khoá trên kho triệu CV là index scan, không còn `LIKE '%...%'` quét bảng.
Dùng cấu hình `simple` + text đã bỏ dấu để khớp không phụ thuộc dấu tiếng Việt mà
không cần extension `unaccent`.

`embedding_fingerprint` = fingerprint của nội dung đã được embed. Khác với
`fingerprint` nghĩa là vector đã cũ ⇒ chính bảng projection đóng vai hàng đợi
embedding, không cần bảng job riêng.

Chỉ mục chỉ tạo trên PostgreSQL; SQLite (máy dev) bỏ qua an toàn.
"""
from django.db import migrations, models

_INDEXES = [
    ("talent_cvchunk_text_norm_fts",
     "talent_cvchunk", "text_norm"),
    ("talent_psd_content_norm_fts",
     "talent_personsearchdocument", "content_norm"),
    ("talent_semantic_normtext_fts",
     "talent_talentsemanticindex", "normalized_text"),
]


def create_fts_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for name, table, column in _INDEXES:
            cursor.execute(
                f'CREATE INDEX IF NOT EXISTS {name} ON {table} '
                f"USING GIN (to_tsvector('simple', {column}))")


def drop_fts_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for name, _table, _column in _INDEXES:
            cursor.execute(f"DROP INDEX IF EXISTS {name}")


class Migration(migrations.Migration):

    dependencies = [
        ('talent', '0006_personsearchdocument_cvchunk'),
    ]

    operations = [
        migrations.AddField(
            model_name='cvchunk',
            name='embedding_fingerprint',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='cvchunk',
            name='text_norm',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='personsearchdocument',
            name='content_norm',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='personsearchdocument',
            name='embedding_fingerprint',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.RunPython(create_fts_indexes, drop_fts_indexes),
    ]
