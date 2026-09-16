# -*- coding: utf-8 -*-
"""Materialize PersonSearchDocument + CVChunk cho hybrid/dense retrieval (§8.2, §24).

Chạy nền/ngoài request. `--no-embeddings` chỉ dựng projection + chunk để kiểm
coverage khi chưa chốt model embedding. Có tiến trình, bỏ qua hồ sơ không đổi
(theo fingerprint), và dừng an toàn khi gặp tệp cờ.
"""
import time

from django.core.management.base import BaseCommand

from people.models import Person
from talent import vector_index
from talent.models import PersonSearchDocument


class Command(BaseCommand):
    help = ("Dựng PersonSearchDocument/CVChunk (+ embedding). "
            "--no-embeddings để chỉ kiểm coverage; --stale để bỏ qua hồ sơ không đổi.")

    def add_arguments(self, parser):
        parser.add_argument("--person-id", type=int)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--no-embeddings", action="store_true")
        parser.add_argument("--stale", action="store_true",
                            help="Chỉ lập chỉ mục hồ sơ chưa có hoặc đã đổi nội dung.")
        parser.add_argument("--stop-file", default="",
                            help="Đường dẫn tệp cờ; tồn tại thì dừng an toàn sau batch.")

    def handle(self, *args, **options):
        import os

        # Cố ý quét CẢ người không phải ứng viên (`is_applicant=False`), dù chỉ
        # ứng viên mới được lập chỉ mục. `index_person` nay XOÁ projection +
        # chunk của người không đủ điều kiện, nên vòng quét này kiêm luôn việc
        # dọn những hàng đã lọt vào chỉ mục từ trước khi có lưới lọc. Bỏ họ ra
        # khỏi vòng lặp là bỏ luôn đường dọn duy nhất.
        rows = Person.objects.filter(merged_into__isnull=True).order_by("pk")
        if options.get("person_id"):
            rows = rows.filter(pk=options["person_id"])
        if options.get("limit"):
            rows = rows[:options["limit"]]

        stale = options["stale"]
        known = {}
        applicant_ids = set()
        if stale:
            known = dict(PersonSearchDocument.objects.values_list("person_id", "fingerprint"))
            # `--stale` bỏ qua hồ sơ có vân tay không đổi. Người KHÔNG phải ứng
            # viên thì vân tay cũng không đổi, nên nếu chỉ so vân tay, hàng chỉ
            # mục cũ của họ sẽ sống sót qua mọi lần chạy `--stale` — đúng nhóm
            # cần dọn lại là nhóm không bao giờ được dọn.
            applicant_ids = set(Person.applicants().values_list("pk", flat=True))

        with_embeddings = not options["no_embeddings"]
        batch = max(1, options["batch_size"])
        stop_file = options["stop_file"]

        done = skipped = failed = 0
        started = time.time()
        ids = list(rows.values_list("pk", flat=True))
        total = len(ids)
        self.stdout.write(f"Bắt đầu: {total} hồ sơ · embeddings={'có' if with_embeddings else 'không'}")

        for offset in range(0, total, batch):
            if stop_file and os.path.exists(stop_file):
                self.stdout.write(self.style.WARNING(f"Gặp cờ dừng {stop_file} — dừng an toàn."))
                break
            for person_id in ids[offset:offset + batch]:
                if stale and person_id in applicant_ids:
                    current = vector_index.document_text(
                        Person.objects.prefetch_related("documents", "source_records")
                        .select_related("talent_profile").get(pk=person_id))
                    import hashlib
                    fp = hashlib.sha256(current.encode("utf-8")).hexdigest()
                    if known.get(person_id) == fp:
                        skipped += 1
                        continue
                try:
                    vector_index.index_person(person_id, with_embeddings=with_embeddings)
                    done += 1
                except Exception as exc:                       # noqa: BLE001
                    failed += 1
                    self.stderr.write(f"  #{person_id}: {exc}")
            elapsed = time.time() - started
            self.stdout.write(
                f"  {min(offset + batch, total)}/{total} · dựng {done} · bỏ qua {skipped} "
                f"· lỗi {failed} · {elapsed:.0f}s")

        self.stdout.write(self.style.SUCCESS(
            f"Xong: dựng {done}, bỏ qua {skipped}, lỗi {failed} / {total} hồ sơ."))
