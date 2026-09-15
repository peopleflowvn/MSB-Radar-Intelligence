# -*- coding: utf-8 -*-
"""Tự động nối alias `proposed` vào CanonicalEntry đã có (Master Plan §6, §21.2).

    python manage.py auto_resolve_aliases                    # chỉ báo cáo, không đổi gì
    python manage.py auto_resolve_aliases --apply            # nối các khớp đủ tin cậy
    python manage.py auto_resolve_aliases --apply --loop     # chạy liên tục (service)
    python manage.py auto_resolve_aliases --namespace location --threshold 0.93

KHÔNG BAO GIỜ tạo `CanonicalEntry` mới — chỉ nối alias vào entry đã tồn tại,
xem `intel/aliasing.py` và nguyên tắc ở `intel/registry.py`. Alias không đủ
tin cậy để nối vẫn nằm nguyên ở hàng chờ cho người quản trị (`/intel/aliases/`).
"""
import time

from django.core.management.base import BaseCommand

from intel.aliasing import DEFAULT_THRESHOLD, auto_resolve


class Command(BaseCommand):
    help = "Tự động nối alias 'proposed' vào canonical entry đã có khi đủ tin cậy."

    def add_arguments(self, parser):
        parser.add_argument("--namespace", default="", help="Chỉ xử lý một namespace.")
        parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                            help="Điểm khớp tối thiểu (0..1) để tự nối. Mặc định 0.90.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Giới hạn số alias xử lý mỗi lượt (0 = không giới hạn).")
        parser.add_argument("--apply", action="store_true",
                            help="Thực sự ghi CSDL; không có cờ này chỉ báo cáo.")
        parser.add_argument("--loop", action="store_true",
                            help="Chạy liên tục thay vì một lượt rồi thoát (dùng cho service).")
        parser.add_argument("--sleep", type=int, default=300,
                            help="Giây nghỉ giữa các lượt khi --loop (mặc định 300).")
        parser.add_argument("--json", action="store_true", help="In báo cáo dạng JSON.")

    def _run_once(self, options):
        report = auto_resolve(
            namespace_key=options["namespace"], threshold=options["threshold"],
            limit=options["limit"] or None, apply=options["apply"])
        if options["json"]:
            import json
            self.stdout.write(json.dumps(report.summary(), sort_keys=True))
        else:
            mode = "ĐÃ GHI" if options["apply"] else "chỉ báo cáo (thêm --apply để ghi)"
            self.stdout.write(f"[{mode}] {report.summary()}")
            for d in report.needs_human[:20]:
                hint = f" gợi ý={d.suggested_entry_code}(score={d.score})" if d.suggested_entry_code else ""
                self.stdout.write(f"  cần người xem: {d.namespace}:{d.alias_norm}{hint}")
        return report

    def handle(self, *args, **options):
        if not options["loop"]:
            self._run_once(options)
            return
        if not options["apply"]:
            raise SystemExit("--loop chỉ có ý nghĩa cùng --apply (nếu không sẽ lặp vô ích).")
        self.stdout.write(self.style.SUCCESS(
            f"auto_resolve_aliases: chạy liên tục, nghỉ {options['sleep']}s mỗi lượt."))
        while True:
            self._run_once(options)
            time.sleep(options["sleep"])
