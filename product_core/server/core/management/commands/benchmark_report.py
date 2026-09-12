# -*- coding: utf-8 -*-
"""In số liệu Loại A + Loại B tự động hoá được, đúng khuôn docs/HACKATHON_METRICS.md.

Mục 23-26 Master Plan (docs/HACKATHON_METRICS.md) cấm bịa số: mọi số Loại B
phải do người thật đo bằng tay (thời gian tới shortlist, Acceptance@10, RM
nhận đề xuất...) — lệnh này KHÔNG thay thế việc đó.

Nó chỉ in ra hai thứ đếm được thật, không cần recruiter/RM ngồi bấm giờ:

    Loại A   toàn bộ bảng ở mục 2 tài liệu, lấy thẳng từ capture.collect() +
             ai/usage_summary — sao chép thẳng vào bảng, không phải gõ tay.
    Mục 3.3  tỷ lệ hồ sơ >12 tháng trong số Person đã hợp nhất — mục 3.3 nói
             rõ đây là "đếm được từ hệ thống" nhưng thuộc Loại B vì cần một
             truy vấn có chủ đích, không phải một số sẵn trên dashboard.

Chạy: python manage.py benchmark_report
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "In số liệu Loại A (đếm được) + mục 3.3 (Loại B tự động hoá) cho docs/HACKATHON_METRICS.md"

    def handle(self, *args, **options):
        from ai.models import LLMCall
        from core import capture
        from people.models import Person

        data = capture.collect()
        consolidation = data["consolidation"]
        parsing = data["parsing"]

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n== Loại A — số đếm được ngay hôm nay (mục 2 HACKATHON_METRICS.md) =="))
        rows = [
            ("Bản ghi nguồn đã nhận", consolidation["source_records"]),
            ("Hợp nhất thành người", consolidation["unique_people"]),
            ("Người đến từ nhiều nền tảng", consolidation["multi_source_people"]),
            ("Nhiều nguồn nhất cho một người", consolidation["max_sources_for_one_person"]),
            ("Lượt hồ sơ / người", consolidation["records_per_person"]),
            ("Bóc tách CV thành công", _pct(parsing["success_rate"])),
        ]

        primary = LLMCall.objects.filter(provider="greennode")
        gn_calls = primary.count()
        if gn_calls:
            gn_ok = primary.filter(ok=True).count()
            gn_latency = primary.filter(ok=True).aggregate(
                avg=_avg("latency_ms"))["avg"]
            rows += [
                ("Lượt gọi GreenNode", gn_calls),
                ("Tỷ lệ thành công GreenNode", _pct(round(gn_ok / gn_calls, 3))),
                ("Độ trễ trung bình GreenNode",
                 f"{round(gn_latency)} ms" if gn_latency else "—"),
            ]
        else:
            rows.append(("Lượt gọi GreenNode", 0))
        fallback_calls = LLMCall.objects.exclude(provider="greennode").count()
        rows.append(("Lượt phải dùng dự phòng", fallback_calls))

        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            self.stdout.write(f"  {label.ljust(width)} : {value}")

        self.stdout.write(self.style.WARNING(
            "\n  Nếu dữ liệu đến từ seed_demo: đây là DỮ LIỆU GIẢ LẬP — "
            "chứng minh cơ chế, không phải quy mô thật."))

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n== Mục 3.3 — tỷ lệ hồ sơ >12 tháng (Loại B, tự động hoá) =="))
        resolved = Person.objects.filter(source_records__isnull=False).distinct()
        total_resolved = resolved.count()
        if total_resolved == 0:
            self.stdout.write("  Chưa có Person nào đã hợp nhất — chưa tính được.")
            return

        cutoff = timezone.now() - timedelta(days=365)
        old = resolved.filter(created_at__lt=cutoff).count()
        self.stdout.write(
            f"  Person đã hợp nhất: {total_resolved}, cũ hơn 12 tháng: {old} "
            f"({_pct(round(old / total_resolved, 3))})")
        self.stdout.write(self.style.WARNING(
            "  Đây là tỷ lệ trên TOÀN KHO, không phải trên một lần tìm kiếm cụ "
            "thể — mục 3.3 tài liệu đòi tỷ lệ trong KẾT QUẢ TÌM KIẾM của một "
            "JD thật. Dùng số này làm tham chiếu nền, không thay thế bài đo."))
        self.stdout.write(self.style.NOTICE(
            "\nNhãn bắt buộc khi trình bày (mục 7): "
            "\"Controlled Hackathon Benchmark — n=…, đo ngày …/09/2026\"\n"))


def _pct(ratio):
    return f"{round(ratio * 100, 1)}%" if ratio is not None else "—"


def _avg(field):
    from django.db.models import Avg
    return Avg(field)
