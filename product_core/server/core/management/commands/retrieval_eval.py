# -*- coding: utf-8 -*-
"""Đo truy hồi của Talent / Growth bằng nhãn người duyệt — ba bước.

    # 1. Xuất phiếu gán nhãn (pooling, thứ tự đã xáo)
    python manage.py retrieval_eval export --domain rb \\
        --dataset ../../evaluation/datasets/growth_prospect_queries_v1.jsonl \\
        --out ../../evaluation/labels/growth-2026-09

    # 2. Nghiệp vụ điền cột `relevant` trong worksheet.csv, rồi nhập vào
    python manage.py retrieval_eval import --domain rb \\
        --dataset ../../evaluation/datasets/growth_prospect_queries_v1.jsonl \\
        --worksheet ../../evaluation/labels/growth-2026-09/worksheet.csv \\
        --out ../../evaluation/datasets/growth_prospect_gold_v1.jsonl

    # 3. Chấm
    python manage.py retrieval_eval score --domain rb \\
        --dataset ../../evaluation/datasets/growth_prospect_gold_v1.jsonl \\
        --manifest ../../evaluation/labels/growth-2026-09/manifest.json \\
        --mode literal --k 10 --out ../../evaluation/results/growth_literal.json

Xem `core/answer/evaluation.py` cho lý do của từng bước. Lệnh này không bao giờ
tự sinh nhãn và không bao giờ báo một con số cho câu chưa có nhãn.
"""
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.answer import evaluation

DOMAINS = ("talent", "rb")


def _talent_adapter():
    from talent.answer import cache, plan as plan_stage, retrieve as retrieve_stage

    def run(query, mode, user, pool):
        if mode == "planned":
            query_plan = plan_stage.plan(query)
        else:
            query_plan = plan_stage.QueryPlan(information_need=query, search_queries=[query])
        rows = retrieve_stage.retrieve(query_plan, pool=pool)
        return [(c.person_id, c.name, [p.text for p in c.passages[:3]]) for c in rows]

    return evaluation.Adapter("talent", run, cache.corpus_fingerprint)


def _rb_adapter():
    from rb.answer import cache, plan as plan_stage, retrieve as retrieve_stage

    def run(query, mode, user, pool):
        if mode == "planned":
            query_plan = plan_stage.plan(query, user=user)
        else:
            query_plan = plan_stage.ProspectPlan(information_need=query, search_queries=[query])
        rows = retrieve_stage.retrieve(query_plan, user=user, pool=pool)
        return [(c.person_id, c.name, [p.text for p in c.passages[:3]]) for c in rows]

    return evaluation.Adapter("rb", run, cache.corpus_fingerprint)


def adapter_for(domain):
    if domain == "talent":
        return _talent_adapter()
    if domain == "rb":
        return _rb_adapter()
    raise CommandError(f"--domain phải là một trong {DOMAINS}")


class Command(BaseCommand):
    help = "Xuất phiếu gán nhãn / nhập nhãn / chấm Recall@K-MRR-nDCG cho truy hồi."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("export", "import", "score"))
        parser.add_argument("--domain", required=True, choices=DOMAINS)
        parser.add_argument("--dataset", required=True)
        parser.add_argument("--out", default="")
        parser.add_argument("--worksheet", default="")
        parser.add_argument("--manifest", default="")
        parser.add_argument("--depth", type=int, default=20)
        parser.add_argument("--k", type=int, default=10)
        parser.add_argument("--mode", choices=evaluation.PLAN_MODES, default="literal")
        parser.add_argument("--modes", default="literal",
                            help="Chế độ gom pool khi export, phân tách bằng dấu phẩy. "
                                 "'literal,planned' gọi LLM cho mỗi câu.")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--as-user", default="",
                            help="Username để chạy các câu phụ thuộc người hỏi "
                                 "(portfolio của Growth). Bỏ trống = không có người hỏi.")

    def handle(self, *args, **options):
        try:
            cases, sha = evaluation.load_cases(options["dataset"])
        except (OSError, ValueError) as exc:
            raise CommandError(f"Không đọc được bộ dữ liệu: {exc}") from exc
        user = None
        if options["as_user"]:
            user = get_user_model().objects.filter(username=options["as_user"]).first()
            if user is None:
                raise CommandError(f"Không có user '{options['as_user']}'.")
        action = options["action"]
        if action == "export":
            return self._export(cases, sha, user, options)
        if action == "import":
            return self._import(cases, options)
        return self._score(cases, user, options)

    def _export(self, cases, sha, user, options):
        if not options["out"]:
            raise CommandError("export cần --out (thư mục).")
        modes = tuple(m.strip() for m in options["modes"].split(",") if m.strip())
        if any(m not in evaluation.PLAN_MODES for m in modes):
            raise CommandError(f"--modes chỉ nhận {evaluation.PLAN_MODES}")
        adapter = adapter_for(options["domain"])
        rows = evaluation.build_pool(adapter, cases, depth=options["depth"], modes=modes,
                                     user=user, seed=options["seed"])
        out = evaluation.write_worksheet(
            rows, options["out"], domain=adapter.domain, dataset_sha=sha,
            corpus=adapter.corpus_fingerprint(), depth=options["depth"], modes=modes,
            seed=options["seed"])
        self.stdout.write(self.style.SUCCESS(
            f"{len(rows)} dòng cho {len(cases)} câu → {out / 'worksheet.csv'}. "
            "Điền cột 'relevant' (1/0) cho MỌI dòng rồi chạy `import`."))

    def _import(self, cases, options):
        if not options["worksheet"] or not options["out"]:
            raise CommandError("import cần --worksheet và --out (file .jsonl).")
        labelled, incomplete = evaluation.labels_from_worksheet(options["worksheet"])
        rows = evaluation.apply_labels(cases, labelled)
        path = Path(options["out"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                        encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"{len(labelled)} câu có nhãn đầy đủ → {path}."))
        if incomplete:
            self.stdout.write(self.style.WARNING(
                f"{len(incomplete)} câu còn dòng chưa điền, KHÔNG được dùng: "
                + ", ".join(incomplete)))

    def _score(self, cases, user, options):
        manifest = None
        if options["manifest"]:
            manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8"))
        result = evaluation.run_scoring(adapter_for(options["domain"]), cases, k=options["k"],
                                        mode=options["mode"], user=user,
                                        label_manifest=manifest)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if options["out"]:
            Path(options["out"]).parent.mkdir(parents=True, exist_ok=True)
            Path(options["out"]).write_text(text, encoding="utf-8")
        summary = {k: result[k] for k in ("domain", "plan_mode", "cases_scored",
                                          "cases_not_measured", "metrics", "warnings")}
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
