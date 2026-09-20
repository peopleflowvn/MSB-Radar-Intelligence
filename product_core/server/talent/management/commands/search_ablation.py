# -*- coding: utf-8 -*-
"""Đo đóng góp riêng của từng nhánh retrieval (SEARCH-P0-05 tạm / mục 3.7).

Đây là bước chặn trước mọi việc tăng trọng số, thêm top-N hay gắn reranker: nếu
một nhánh không thêm Person nào mà chỉ thêm độ trễ và tiền, ablation sẽ nói ra.

    python manage.py search_ablation
    python manage.py search_ablation --dataset talent/eval_data/search_silver_v1.jsonl
    python manage.py search_ablation --out docs/benchmark/search_ablation_<ngày>.json

Bộ `search_silver_v1.jsonl` là **silver**, không phải gold: các case
`deterministic` có truth tự suy được bằng SQL nên chấm được ngay, còn case
`semantic` mang `labels.status="needs_review"` và bị **bỏ qua** cho tới khi có
người gán nhãn và người thứ hai review. Lệnh in rõ bao nhiêu case bị bỏ qua để
không ai đọc báo cáo này như đã đo recall semantic.
"""
import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from talent.search_v2 import (ABLATION_CONFIGS, RadarTurnPlan, ablation,
                              compile_projection_query)

DEFAULT_DATASET = "talent/eval_data/search_silver_v1.jsonl"


def _dataset_path(value):
    """Tìm dataset trong image trước, rồi mới tới gốc repo.

    Image của Hub chỉ copy `product_core/server`, nên dataset phải nằm trong đó
    mới chạy được trên production — đường dẫn gốc repo chỉ còn là tiện lợi khi
    làm việc trên máy.
    """
    path = Path(value)
    if path.is_absolute():
        if not path.is_file():
            raise CommandError(f"Không thấy dataset: {path}")
        return path
    base = Path(settings.BASE_DIR)
    for candidate in (base / value, base.parent.parent / value, Path.cwd() / value):
        if candidate.is_file():
            return candidate
    raise CommandError(f"Không thấy dataset {value} trong {base} hoặc gốc repo.")


def load_cases(path):
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise CommandError(f"{path.name} dòng {number}: {exc}") from exc
    return cases


def _config_required(config, branches):
    """Cấu hình này có nhánh nào thật sự được yêu cầu chạy không.

    Nếu mọi nhánh của cấu hình đều `not_required` thì recall của nó là **không
    áp dụng**, không phải 0. Báo 0 sẽ đọc thành "nhánh này chẳng tìm được ai",
    trong khi thực tế nó chưa hề được hỏi.
    """
    states = [branches.get(name) or {} for name in config.split("+")]
    states = [state for state in states if state]
    if not states:
        return True
    # `not_required`: plan không cần nhánh này. `no_hard_filter`: plan không có
    # điều kiện cứng nào để nhánh structured làm việc. Cả hai đều là "không áp
    # dụng", khác hẳn với "đã chạy và không tìm được ai".
    idle = {"not_required", "no_hard_filter"}
    return any(state.get("ran") or state.get("reason") not in idle
               for state in states)


def evaluate_case(case, *, fts_top_n):
    """Một case → recall/unique hit từng cấu hình, hoặc lý do bị bỏ qua."""
    plan = RadarTurnPlan.from_dict(case.get("plan") or {})
    truth_kind = case.get("truth")
    if truth_kind == "labels":
        labels = case.get("labels") or {}
        if labels.get("status") != "labelled" or not labels.get("person_ids"):
            return {"id": case.get("id"), "skipped": "needs_review"}
        truth = set(labels.get("person_ids") or [])
    elif case.get("truth_plan"):
        # Truth lấy từ một plan khác (thường là điều kiện cứng tương đương), để
        # đo được nhánh lexical/vector có tìm lại đúng tập đó hay không.
        truth_queryset, _explain = compile_projection_query(
            RadarTurnPlan.from_dict(case["truth_plan"]))
        truth = set(truth_queryset.values_list("person_id", flat=True))
    else:
        queryset, explain = compile_projection_query(plan)
        truth = set(queryset.values_list("person_id", flat=True))
        if truth_kind == "empty_fail_closed":
            return {"id": case.get("id"), "truth_size": len(truth),
                    "fail_closed": not truth and bool(explain.get("unresolved")),
                    "unresolved": explain.get("unresolved", [])}
    report = ablation(plan, fts_top_n=fts_top_n)
    rows = {}
    for config, data in report["configs"].items():
        found = set(data["ids"])
        applicable = _config_required(config, data["branches"])
        rows[config] = {
            "count": data["count"], "ms": data["ms"],
            "recall": (round(len(found & truth) / len(truth), 4)
                       if truth and applicable else None),
            "applicable": applicable,
            "missed": sorted(truth - found)[:20] if applicable else [],
            "extra": len(found - truth),
            "branches": data["branches"],
        }
    single = report["configs"].get("field_fts", {}).get("ids") or []
    structured = report["configs"].get("structured", {}).get("ids") or []
    return {"id": case.get("id"), "kind": case.get("kind"),
            "query": case.get("query"), "truth_size": len(truth),
            "unique_field_fts": len(set(single) - set(structured)),
            "unique_structured": len(set(structured) - set(single)),
            "configs": rows}


class Command(BaseCommand):
    help = "Ablation recall theo từng nhánh retrieval trên bộ silver/gold."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default=DEFAULT_DATASET)
        parser.add_argument("--fts-top-n", type=int, default=None)
        parser.add_argument("--out", default="")

    def handle(self, *args, **options):
        path = _dataset_path(options["dataset"])
        cases = load_cases(path)
        fts_top_n = options["fts_top_n"] or int(
            getattr(settings, "SEARCH_V2_FTS_TOP_N", 2000))
        started = time.perf_counter()
        results = [evaluate_case(case, fts_top_n=fts_top_n) for case in cases]
        skipped = [row for row in results if row.get("skipped")]
        scored = [row for row in results if not row.get("skipped")
                  and row.get("configs")]
        summary = {"dataset": path.name, "cases": len(cases),
                   "scored": len(scored), "skipped_needs_review": len(skipped),
                   "fts_top_n": fts_top_n,
                   "ms": round((time.perf_counter() - started) * 1000, 1),
                   "per_config": {}}
        for config in ABLATION_CONFIGS:
            recalls = [row["configs"][config]["recall"] for row in scored
                       if row["configs"].get(config, {}).get("recall") is not None]
            summary["per_config"][config] = {
                "cases": len(recalls),
                "mean_recall": (round(sum(recalls) / len(recalls), 4)
                                if recalls else None),
                "perfect": sum(1 for value in recalls if value == 1.0),
            }
        payload = {"summary": summary, "results": results}
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        if skipped:
            self.stdout.write(self.style.WARNING(
                f"{len(skipped)} case semantic chưa gán nhãn nên KHÔNG được tính: "
                f"{', '.join(row['id'] for row in skipped)}. "
                "Recall semantic chưa được đo."))
        if options["out"]:
            out = Path(options["out"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            self.stdout.write(f"Đã ghi {out}")
        return None
