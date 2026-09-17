# -*- coding: utf-8 -*-
"""Chốt số chiều vector và tạo chỉ mục HNSW khi kho đã đủ lớn (Master Plan §24).

Cột `embedding` cố ý để BIẾN CHIỀU lúc đầu để người vận hành đổi model embedding
mà không phải viết migration. Nhưng `hnsw`/`ivfflat` của pgvector **bắt buộc**
chiều cố định — không có chỉ mục thì mỗi truy vấn là một lần quét toàn bảng, và
ở kho triệu CV thì đó là cái chết của tính năng.

Chạy lệnh này SAU khi đã backfill xong embedding bằng model đã chốt:

    python manage.py pin_vector_dimensions            # chỉ xem, không đổi gì
    python manage.py pin_vector_dimensions --apply    # ALTER + CREATE INDEX

Đổi model embedding về sau ⇒ xoá vector cũ, backfill lại, rồi chạy lại lệnh này.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

TABLES = [
    ("talent_personsearchdocument", "talent_psd_embedding_hnsw"),
    ("talent_cvchunk", "talent_cvchunk_embedding_hnsw"),
    # Chỉ mục bằng chứng khách hàng của Growth — CÙNG model embedding, nên cùng
    # số chiều; chốt chung một lệnh để hai bên không thể lệch chiều nhau.
    ("rb_prospectevidencechunk", "rb_pec_embedding_hnsw"),
]


class Command(BaseCommand):
    help = "Chốt chiều cột vector + tạo chỉ mục HNSW cosine cho dense retrieval."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Thực thi; không có cờ này chỉ báo cáo.")
        parser.add_argument("--dimensions", type=int, default=0,
                            help="Ép số chiều thay vì dò từ dữ liệu.")
        parser.add_argument("--lists", type=int, default=0,
                            help="Dùng ivfflat với số lists này thay cho hnsw.")

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("Chỉ chạy được trên PostgreSQL + pgvector.")

        apply_changes = options["apply"]
        forced = options["dimensions"]
        lists = options["lists"]

        with connection.cursor() as cursor:
            for table, index_name in TABLES:
                cursor.execute(
                    f"SELECT count(*), count(embedding) FROM {table}")
                total, embedded = cursor.fetchone()

                # Chưa có vector: chỉ cho phép ĐỔI KIỂU CỘT khi có --dimensions
                # (dọn đường trước khi backfill bằng model mới). Không tạo index.
                if not embedded:
                    if not forced:
                        self.stdout.write(self.style.WARNING(
                            f"{table}: {total} hàng, 0 vector — chạy "
                            f"`embed_talent_index` / `embed_prospect_evidence` trước (hoặc thêm --dimensions N "
                            f"để đổi kiểu cột sẵn)."))
                        continue
                    cursor.execute(
                        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                        "WHERE attrelid = %s::regclass AND attname = 'embedding'", [table])
                    col_type = (cursor.fetchone() or [""])[0].strip().lower()
                    self.stdout.write(f"{table}: 0 vector · cột {col_type}")
                    if apply_changes and col_type != f"vector({forced})":
                        self.stdout.write(f"  → ALTER COLUMN embedding TYPE vector({forced})")
                        cursor.execute(f"DROP INDEX IF EXISTS {index_name}")
                        cursor.execute(
                            f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({forced})")
                    continue

                dims = forced
                if not dims:
                    cursor.execute(
                        f"SELECT vector_dims(embedding) FROM {table} "
                        f"WHERE embedding IS NOT NULL LIMIT 1")
                    dims = cursor.fetchone()[0]
                cursor.execute(
                    f"SELECT count(DISTINCT vector_dims(embedding)) FROM {table} "
                    f"WHERE embedding IS NOT NULL")
                distinct = cursor.fetchone()[0]
                if distinct > 1:
                    raise CommandError(
                        f"{table}: có {distinct} số chiều khác nhau — kho đang lẫn "
                        f"vector của nhiều model. Xoá vector cũ rồi backfill lại "
                        f"bằng MỘT model trước khi chốt chiều.")

                method = f"ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})" \
                    if lists else "hnsw (embedding vector_cosine_ops)"
                # Kiểu cột hiện tại: `vector` (không chiều) hay `vector(N)`?
                cursor.execute(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = %s::regclass AND attname = 'embedding'", [table])
                col_type = (cursor.fetchone() or [""])[0].strip().lower()
                # Cần ALTER khi kiểu cột chưa đúng `vector(dims)` — kể cả khi đang
                # là `vector(1536)` mà ta muốn 1024 (đổi model embedding).
                needs_alter = col_type != f"vector({dims})"
                self.stdout.write(
                    f"{table}: {embedded}/{total} có vector · chiều {dims} · cột {col_type} · "
                    f"chỉ mục {'ivfflat' if lists else 'hnsw'}")
                if not apply_changes:
                    continue

                if needs_alter:
                    self.stdout.write(f"  → ALTER COLUMN embedding TYPE vector({dims}) "
                                      f"(từ {col_type})")
                    cursor.execute(f"DROP INDEX IF EXISTS {index_name}")
                    cursor.execute(
                        f"ALTER TABLE {table} ALTER COLUMN embedding "
                        f"TYPE vector({dims}) USING embedding::vector({dims})")
                else:
                    self.stdout.write(f"  → cột đã là {col_type}, bỏ qua ALTER")
                self.stdout.write(f"  → CREATE INDEX {index_name}")
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} USING {method}")

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(
                "Đã chốt chiều và tạo chỉ mục. Dense retrieval giờ dùng index, "
                "không còn quét toàn bảng."))
        else:
            self.stdout.write("Chưa đổi gì. Thêm --apply để thực thi.")
