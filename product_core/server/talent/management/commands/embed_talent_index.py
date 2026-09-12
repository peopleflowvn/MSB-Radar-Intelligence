# -*- coding: utf-8 -*-
"""Worker nền tính embedding cho projection + đoạn CV (Master Plan §8.2, §24).

Hàng đợi chính là bảng projection: hàng nào `embedding_fingerprint != fingerprint`
là vector đã cũ hoặc chưa có. Nhờ vậy kho triệu CV backfill tăng dần được, chạy
lại an toàn, và ingest không bao giờ phải chờ provider embedding.

    python manage.py embed_talent_index --limit 5000
    python manage.py embed_talent_index --loop --stop-file /tmp/stop-embed
"""
import time

from django.core.management.base import BaseCommand

from talent import vector_index


class Command(BaseCommand):
    help = "Tính embedding cho các PersonSearchDocument/CVChunk có vector đã cũ."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000,
                            help="Số bản ghi tối đa xử lý trong lượt chạy này (0 = không giới hạn).")
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--chunks-only", action="store_true")
        parser.add_argument("--documents-only", action="store_true")
        parser.add_argument("--loop", action="store_true",
                            help="Chạy liên tục tới khi hết hàng đợi hoặc gặp cờ dừng.")
        parser.add_argument("--sleep", type=float, default=1.0)
        parser.add_argument("--stop-file", default="")
        parser.add_argument("--then-pin", action="store_true",
                            help="Hàng đợi rỗng ⇒ tự chốt chiều + tạo HNSW (pin_vector_dimensions --apply).")

    def handle(self, *args, **options):
        import os

        limit = options["limit"]
        batch = max(1, options["batch_size"])
        stop_file = options["stop_file"]
        do_docs = not options["chunks_only"]
        do_chunks = not options["documents_only"]

        processed = failed = 0
        started = time.time()

        def stopped():
            return bool(stop_file and os.path.exists(stop_file))

        while True:
            if stopped():
                self.stdout.write(self.style.WARNING(f"Gặp cờ dừng {stop_file}."))
                break
            budget = batch if limit <= 0 else min(batch, limit - processed)
            if budget <= 0:
                break

            did = 0
            if do_docs:
                for row in vector_index.stale_documents(limit=budget):
                    vector, model = vector_index.embed(
                        row.content[:vector_index.PROJECTION_EMBED_CHARS],
                        task_type="RETRIEVAL_DOCUMENT")
                    if vector:
                        row.embedding = vector
                        row.embedding_model = model
                        row.embedding_fingerprint = row.fingerprint
                        row.save(update_fields=["embedding", "embedding_model",
                                                "embedding_fingerprint", "indexed_at"])
                        processed += 1
                    else:
                        failed += 1
                    did += 1
            if do_chunks and did < budget:
                for row in vector_index.stale_chunks(limit=budget - did):
                    vector, model = vector_index.embed(
                        row.text, task_type="RETRIEVAL_DOCUMENT")
                    if vector:
                        row.embedding = vector
                        row.embedding_model = model
                        row.embedding_fingerprint = row.fingerprint
                        row.save(update_fields=["embedding", "embedding_model",
                                                "embedding_fingerprint", "updated_at"])
                        processed += 1
                    else:
                        failed += 1
                    did += 1

            if did == 0:
                self.stdout.write("Hàng đợi rỗng.")
                if options["then_pin"] and processed:
                    self.stdout.write("→ chốt chiều + tạo HNSW…")
                    from django.core.management import call_command
                    try:
                        call_command("pin_vector_dimensions", "--apply")
                    except Exception as exc:                    # noqa: BLE001
                        self.stderr.write(f"pin_vector_dimensions lỗi: {exc}")
                if options["loop"]:
                    time.sleep(max(5.0, options["sleep"]))
                    continue
                break
            self.stdout.write(f"  +{did} · xong {processed} · lỗi {failed} "
                              f"· {time.time() - started:.0f}s")
            if failed and processed == 0:
                self.stderr.write(self.style.ERROR(
                    "Không embed được bản ghi nào — kiểm tra route `talent_embedding` "
                    "trong /settings (provider bật, có khoá, có mã model)."))
                if options["loop"]:
                    time.sleep(max(60.0, options["sleep"]))
                    failed = 0
                    continue
                break
            if not options["loop"]:
                if limit > 0 and processed + failed >= limit:
                    break
                continue
            time.sleep(max(0.0, options["sleep"]))

        self.stdout.write(self.style.SUCCESS(
            f"Xong: {processed} vector mới, {failed} lỗi, {time.time() - started:.0f}s."))
