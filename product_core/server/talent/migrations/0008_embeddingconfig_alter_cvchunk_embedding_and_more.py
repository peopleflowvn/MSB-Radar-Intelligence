# -*- coding: utf-8 -*-
"""Cấu hình nguồn embedding (singleton, đổi từ /settings) + cột vector biến chiều.

Số chiều vector không còn chốt ở model: người vận hành chọn Gemini API hay endpoint
tự host trên `/settings`, và `pin_vector_dimensions` chốt số chiều thật + tạo HNSW.
Migration này hạ cột `vector(1536)` → `vector` (không chiều); chỉ mục HNSW nếu có
sẽ bị xoá trước rồi `pin_vector_dimensions --apply` dựng lại theo số chiều mới.
"""
from django.db import migrations, models
import pgvector.django.vector

_HNSW = ["talent_psd_embedding_hnsw", "talent_cvchunk_embedding_hnsw"]


def drop_hnsw(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for name in _HNSW:
            cursor.execute(f"DROP INDEX IF EXISTS {name}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('talent', '0007_search_norm_and_embedding_state'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmbeddingConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mode', models.CharField(choices=[('selfhost', 'Tự host (Ollama / TEI)'), ('gemini', 'Google Gemini API'), ('off', 'Tắt — chỉ tìm full-text')], default='selfhost', max_length=20)),
                ('selfhost_base_url', models.CharField(blank=True, default='http://ollama:11434/v1', max_length=300)),
                ('selfhost_model', models.CharField(blank=True, default='nomic-embed-text', max_length=120)),
                ('gemini_model', models.CharField(blank=True, default='gemini-embedding-001', max_length=120)),
                ('dimensions', models.PositiveIntegerField(default=768)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.CharField(blank=True, default='', max_length=150)),
            ],
            options={
                'verbose_name': 'Cấu hình embedding',
                'verbose_name_plural': 'Cấu hình embedding',
            },
        ),
        migrations.RunPython(drop_hnsw, noop),
        migrations.AlterField(
            model_name='cvchunk',
            name='embedding',
            field=pgvector.django.vector.VectorField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='personsearchdocument',
            name='embedding',
            field=pgvector.django.vector.VectorField(blank=True, null=True),
        ),
    ]
