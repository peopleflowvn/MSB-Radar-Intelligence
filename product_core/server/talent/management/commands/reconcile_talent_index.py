# -*- coding: utf-8 -*-
"""Worker nền khép kín: tự phát hiện VÀ tự sửa chỉ mục Talent thiếu, bất kể
đường nhập liệu nào tạo ra khoảng trống (Master Plan §8.2, §24).

Trước đây giữ độ phủ chỉ mục đầy đủ cần ba lệnh chạy tay đúng thứ tự
(`rebuild_talent_vector_index --stale` sau nhập hàng loạt → `embed_talent_index
--loop` bù embedding → `pin_vector_dimensions --apply` chốt HNSW), và không có
gì bắt được trường hợp bước "chạy tay" bị quên. Lệnh này hợp nhất cả ba thành
MỘT vòng lặp tự rà soát liên tục, mỗi lượt:

    1. Vá lỗ hổng cấu trúc — ứng viên hợp lệ (`Person.applicants()`) nhưng
       CHƯA có `PersonSearchDocument` (nhập hàng loạt tắt
       `TALENT_INDEX_ON_SAVE`, kích hoạt lại sau gộp/bỏ cờ ứng tuyển, hay một
       đường ghi tương lai chưa lường trước). Đây là lưới an toàn không cần
       biết trước NGUYÊN NHÂN thiếu — chỉ so trực tiếp với tập phải có mặt.
    2. Bù embedding cho vector cũ/chưa có — như `embed_talent_index`.
    3. Quét sâu định kỳ (không phải mỗi lượt — đắt hơn vì phải tính lại
       fingerprint nội dung của TOÀN kho): bắt trường hợp nội dung đổi mà
       signal không nổ (vd. ghi qua model lịch sử trong data migration).
    4. Hàng đợi rỗng ⇒ tự chốt chiều vector + tạo/giữ chỉ mục HNSW, để bước
       "Tìm trong kho" không bao giờ âm thầm rơi về quét toàn bảng.

    python manage.py reconcile_talent_index --apply --loop --sleep 2
    python manage.py reconcile_talent_index --json            # chỉ báo cáo
    python manage.py reconcile_talent_index --apply --gate    # CI/ops: fail nếu còn thiếu
"""
import json as json_module
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from people.models import Person
from talent import vector_index


class DimensionMismatch(RuntimeError):
    pass


def _save_vector(row, fields):
    """Ghi vector; lệch số chiều với cột thì báo thành lỗi CÓ HƯỚNG DẪN.

    Lệch chiều nghĩa là model embedding đã đổi mà cột vẫn chốt chiều cũ. Không
    tự xoá vector cũ ở đây — đó là thao tác phá dữ liệu, người vận hành chạy
    có chủ đích bằng lệnh dưới.
    """
    from django.db import DataError, transaction
    try:
        with transaction.atomic():
            row.save(update_fields=fields)
    except DataError as exc:
        if "dimensions" not in str(exc):
            raise
        raise DimensionMismatch(
            f"Cột vector lệch số chiều với model embedding đang dùng "
            f"({row.embedding_model}, {len(row.embedding or [])} chiều): {exc}. "
            f"Sửa: xoá vector của model cũ rồi "
            f"`python manage.py pin_vector_dimensions --dimensions "
            f"{len(row.embedding or [])} --apply`.") from exc


class Command(BaseCommand):
    _pace = 0.0
    help = "Tự phát hiện + tự sửa chỉ mục Talent thiếu (projection/chunk/embedding/HNSW)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Thực thi sửa; không có cờ này chỉ báo cáo coverage.")
        parser.add_argument("--batch-size", type=int, default=100,
                            help="Số hồ sơ tối đa xử lý mỗi việc trong một lượt.")
        parser.add_argument("--loop", action="store_true",
                            help="Chạy liên tục tới khi hết hàng đợi hoặc gặp cờ dừng.")
        parser.add_argument("--sleep", type=float, default=2.0,
                            help="Giây nghỉ giữa các lượt bận khi --loop.")
        parser.add_argument("--pace", type=float, default=1.0,
                            help="Giây nghỉ giữa hai lời gọi embedding (giữ dưới hạn mức "
                                 "của provider thay vì gọi dồn rồi ăn 429).")
        parser.add_argument("--idle-sleep", type=float, default=5.0,
                            help="Giây nghỉ khi hàng đợi rỗng (mặc định 5s, tối thiểu --sleep).")
        parser.add_argument("--deep-scan-every", type=int, default=300,
                            help="Số lượt giữa các lần quét sâu toàn kho (bước 3).")
        parser.add_argument("--stop-file", default="",
                            help="Đường dẫn tệp cờ; tồn tại thì dừng an toàn sau lượt hiện tại.")
        parser.add_argument("--json", action="store_true", help="In báo cáo dạng JSON.")
        parser.add_argument("--gate", action="store_true",
                            help="Thoát mã khác 0 nếu còn hồ sơ thiếu chỉ mục sau lượt này.")

    def handle(self, *args, **options):
        import os

        apply_changes = options["apply"]
        if options["loop"] and not apply_changes:
            raise SystemExit("--loop chỉ có ý nghĩa cùng --apply (nếu không sẽ lặp vô ích).")

        batch = max(1, options["batch_size"])
        self._pace = max(0.0, float(options.get("pace") or 0.0))
        stop_file = options["stop_file"]
        as_json = options["json"]

        def stopped():
            return bool(stop_file and os.path.exists(stop_file))

        if not apply_changes:
            self._report(as_json=as_json, gate=options["gate"])
            return

        tick = 0
        deep_scan_every = max(1, options["deep_scan_every"])
        # Một hồ sơ lỗi LIÊN TỤC (nội dung không dựng chỉ mục được, provider
        # embedding từ chối đúng một đoạn…) không được phép chiếm chỗ trong
        # `batch` mãi mãi — bỏ qua trong phần còn lại của TIẾN TRÌNH này, thử
        # lại ở lượt quét sâu định kỳ (cùng nhịp dọn `rebuild_talent_vector_
        # index --stale`, không phải một cơ chế lịch riêng).
        skip_projection_ids = set()
        skip_row_keys = set()
        while True:
            if stopped():
                self.stdout.write(self.style.WARNING(f"Gặp cờ dừng {stop_file}."))
                break
            tick += 1

            fixed = self._fix_missing_projection(batch, skip_projection_ids)
            try:
                processed, failed = self._fill_embeddings(batch, skip_row_keys)
            except DimensionMismatch as exc:
                # Không crash: container sẽ khởi động lại vô hạn (production
                # 19/09: 26 lần) mà không sửa được gì. Nói rõ cách sửa rồi chờ.
                self.stderr.write(self.style.ERROR(str(exc)))
                if not options["loop"]:
                    raise SystemExit(2)
                time.sleep(max(600.0, options["idle_sleep"]))
                continue
            deep_scanned = False
            if tick % deep_scan_every == 0:
                self.stdout.write("→ quét sâu toàn kho (rebuild_talent_vector_index --stale)…")
                call_command("rebuild_talent_vector_index", "--stale", "--no-embeddings")
                deep_scanned = True
                skip_projection_ids.clear()
                skip_row_keys.clear()

            did_work = fixed or processed or failed or deep_scanned
            if not did_work:
                self.stdout.write("Hàng đợi rỗng — chốt chiều vector + HNSW.")
                try:
                    call_command("pin_vector_dimensions", "--apply")
                except Exception as exc:                    # noqa: BLE001
                    self.stderr.write(f"pin_vector_dimensions lỗi: {exc}")
                if not options["loop"]:
                    break
                time.sleep(max(options["idle_sleep"], options["sleep"]))
                continue

            self.stdout.write(
                f"lượt {tick}: +{fixed} chỉ mục mới · {processed} embedding xong "
                f"· {failed} lỗi")
            if failed and not processed:
                # Provider embedding chết hẳn (không phải một hàng lẻ): đừng
                # hot-loop chờ timeout (60s/lời gọi) liên tục cho cả `batch`.
                # Vá projection (không cần mạng) vẫn đã chạy ở lượt này rồi,
                # không bị chặn bởi nhánh này.
                if options["loop"]:
                    time.sleep(max(60.0, options["sleep"]))
                    continue
                break
            if not options["loop"]:
                break
            time.sleep(options["sleep"])

        self._report(as_json=as_json, gate=options["gate"])

    def _fix_missing_projection(self, batch, skip_ids):
        candidates = vector_index.missing_projection_ids(limit=batch + len(skip_ids))
        ids = [pid for pid in candidates if pid not in skip_ids][:batch]
        for person_id in ids:
            try:
                vector_index.index_person(person_id, with_embeddings=False)
            except Exception as exc:                    # noqa: BLE001
                self.stderr.write(f"  #{person_id}: {exc}")
                skip_ids.add(person_id)
        return len(ids)

    def _embed(self, text):
        """`embed()` có lùi dần khi provider trả 429.

        Trả `(vector, model, rate_limited)`. Bị giới hạn tốc độ KHÔNG phải lỗi của
        hàng — không được đưa hàng vào `skip_keys` (production 19/09: gần như cả
        lô bị đánh dấu bỏ qua tới lượt quét sâu, 300 lượt sau).
        """
        delay = 5.0
        for _attempt in range(6):
            vector, model = vector_index.embed(text, task_type="RETRIEVAL_DOCUMENT")
            if vector:
                if self._pace:
                    time.sleep(self._pace)
                return vector, model, False
            if vector_index.LAST_EMBED_ERROR != "rate_limited":
                return None, model, False
            time.sleep(delay)
            delay = min(120.0, delay * 2)
        return None, "", True

    def _fill_embeddings(self, batch, skip_keys):
        """Y hệt logic của `embed_talent_index` — bù vector cho hàng đã stale."""
        processed = failed = 0
        remaining = batch
        for row in vector_index.stale_documents(limit=batch + len(skip_keys)):
            if remaining <= 0:
                break
            key = ("doc", row.pk)
            if key in skip_keys:
                continue
            vector, model, limited = self._embed(
                row.content[:vector_index.PROJECTION_EMBED_CHARS])
            if limited:
                return processed, failed + 1
            if vector:
                row.embedding = vector
                row.embedding_model = model
                row.embedding_fingerprint = row.fingerprint
                _save_vector(row, ["embedding", "embedding_model",
                                   "embedding_fingerprint", "indexed_at"])
                processed += 1
            else:
                failed += 1
                skip_keys.add(key)
            remaining -= 1
        if remaining > 0:
            for row in vector_index.stale_chunks(limit=remaining + len(skip_keys)):
                if remaining <= 0:
                    break
                key = ("chunk", row.pk)
                if key in skip_keys:
                    continue
                vector, model, limited = self._embed(row.text)
                if limited:
                    return processed, failed + 1
                if vector:
                    row.embedding = vector
                    row.embedding_model = model
                    row.embedding_fingerprint = row.fingerprint
                    _save_vector(row, ["embedding", "embedding_model",
                                       "embedding_fingerprint", "updated_at"])
                    processed += 1
                else:
                    failed += 1
                    skip_keys.add(key)
                remaining -= 1
        return processed, failed

    def _coverage(self):
        from django.db.models import F
        from talent.models import CVChunk, PersonSearchDocument
        return {
            "missing_projection": Person.applicants()
            .filter(search_document__isnull=True).count(),
            "profiles": PersonSearchDocument.objects.count(),
            "profiles_embedded": PersonSearchDocument.objects.filter(
                embedding_fingerprint=F("fingerprint")).count(),
            "chunks": CVChunk.objects.count(),
            "chunks_embedded": CVChunk.objects.filter(
                embedding_fingerprint=F("fingerprint")).count(),
        }

    def _report(self, *, as_json, gate):
        report = self._coverage()
        if as_json:
            self.stdout.write(json_module.dumps(report, ensure_ascii=False))
        else:
            self.stdout.write(
                f"thiếu chỉ mục: {report['missing_projection']} · "
                f"profiles {report['profiles_embedded']}/{report['profiles']} · "
                f"chunks {report['chunks_embedded']}/{report['chunks']}")
        if gate and report["missing_projection"] > 0:
            raise CommandError(
                f"Còn {report['missing_projection']} ứng viên thiếu chỉ mục.")
        return report
