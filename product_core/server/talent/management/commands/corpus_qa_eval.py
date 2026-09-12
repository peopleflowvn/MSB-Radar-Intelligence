# -*- coding: utf-8 -*-
"""Đo nhanh chất lượng hỏi đáp có dẫn chứng trên kho CV (Master Plan §24, §16.2).

Không phải benchmark đầy đủ (§15 Giai đoạn 0) — chỉ một cổng "đủ tốt để bật":
với mỗi câu hỏi, kiểm câu trả lời có nhắc tới các chuỗi mong đợi và có trích dẫn.

Định dạng tệp JSON: danh sách
  {"question": "...", "expect_any": ["chuỗi", ...], "expect_all": ["chuỗi", ...],
   "min_citations": 1}
`expect_any`/`expect_all`/`min_citations` đều tùy chọn.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from talent import corpus_qa


class Command(BaseCommand):
    help = "Chạy bộ câu hỏi mẫu qua talent.corpus_qa và báo tỉ lệ đạt."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Tệp JSON danh sách câu hỏi.")
        parser.add_argument("--verbose-answers", action="store_true")

    def handle(self, *args, **options):
        try:
            with open(options["file"], encoding="utf-8") as fh:
                cases = json.load(fh)
        except (OSError, ValueError) as exc:
            raise CommandError(f"Không đọc được tệp: {exc}")
        if not isinstance(cases, list) or not cases:
            raise CommandError("Tệp phải là danh sách câu hỏi không rỗng.")

        passed = 0
        for index, case in enumerate(cases, 1):
            question = str(case.get("question") or "").strip()
            if not question:
                continue
            result = corpus_qa.answer(question)
            answer = (result or {}).get("answer", "") or ""
            citations = (result or {}).get("citations", []) or []
            low = answer.casefold()

            ok = bool(answer)
            reasons = []
            if not answer:
                reasons.append("không có câu trả lời / không truy hồi được")
            for term in case.get("expect_all", []):
                if term.casefold() not in low:
                    ok = False
                    reasons.append(f"thiếu '{term}'")
            any_terms = case.get("expect_any", [])
            if any_terms and not any(t.casefold() in low for t in any_terms):
                ok = False
                reasons.append(f"không nhắc bất kỳ: {any_terms}")
            min_cit = int(case.get("min_citations", 1))
            if len(citations) < min_cit:
                ok = False
                reasons.append(f"chỉ {len(citations)}/{min_cit} trích dẫn")

            passed += ok
            mark = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
            self.stdout.write(f"[{index}] {mark} · {question}")
            if not ok:
                self.stdout.write("      " + "; ".join(reasons))
            if options["verbose_answers"] and answer:
                self.stdout.write("      → " + answer.replace("\n", " ")[:300])

        total = len([c for c in cases if str(c.get("question") or "").strip()])
        rate = passed / total if total else 0
        style = self.style.SUCCESS if rate >= 0.7 else self.style.WARNING
        self.stdout.write(style(f"\nĐạt {passed}/{total} ({rate:.0%})."))
