# -*- coding: utf-8 -*-
"""Chỉ mục cho nhánh field-aware FTS của CandidateSet (SEARCH-P1-03C).

Trước migration này compiler so khớp text bằng `LIKE '%…%'`: ở kho 500k đó là
quét toàn bảng, và chỉ mục GIN full-text của migration 0015 không câu nào dùng
tới vì nó nằm trên biểu thức `to_tsvector('simple', searchable_text)` còn query
lại là LIKE.

Hai thứ được thêm:

* `search_tsv` — cột `tsvector` GENERATED ALWAYS … STORED, gộp các field với
  trọng số A/B/C/D. Cột generated nên không thể lệch với dữ liệu nguồn, và
  không cần Django ghi vào (model không khai báo cột này).
* chỉ mục trigram cho bốn cột văn bản ngắn, để `__contains` còn lại dùng được
  chỉ mục thay vì quét bảng. Thiếu extension `pg_trgm` thì bỏ qua phần này —
  truy vấn vẫn đúng, chỉ chậm — và ghi lại để P0-02 xử lý.
"""
from django.db import migrations

TSV_EXPRESSION = """
    setweight(to_tsvector('simple', coalesce(title_norm, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(company_norm, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(location_norm, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(education_norm, '')), 'C') ||
    setweight(to_tsvector('simple', coalesce(searchable_text, '')), 'D')
"""
TRIGRAM_COLUMNS = ("title_norm", "company_norm", "location_norm", "education_norm")


def create(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns "
                       "WHERE table_name = 'talent_searchprojection' "
                       "AND column_name = 'search_tsv'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE talent_searchprojection ADD COLUMN search_tsv "
                           f"tsvector GENERATED ALWAYS AS ({TSV_EXPRESSION}) STORED")
        cursor.execute("CREATE INDEX IF NOT EXISTS talent_searchprojection_tsv_gin "
                       "ON talent_searchprojection USING GIN (search_tsv)")
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        except Exception:                          # noqa: BLE001 - thiếu quyền
            return
        for column in TRIGRAM_COLUMNS:
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS talent_searchprojection_{column}_trgm "
                f"ON talent_searchprojection USING GIN ({column} gin_trgm_ops)")


def drop(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS talent_searchprojection_tsv_gin")
        for column in TRIGRAM_COLUMNS:
            cursor.execute(f"DROP INDEX IF EXISTS talent_searchprojection_{column}_trgm")
        cursor.execute("ALTER TABLE talent_searchprojection DROP COLUMN IF EXISTS search_tsv")


class Migration(migrations.Migration):
    dependencies = [("talent", "0015_searchprojection_postgres_indexes")]
    operations = [migrations.RunPython(create, drop)]
