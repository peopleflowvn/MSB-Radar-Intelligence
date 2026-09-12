# -*- coding: utf-8 -*-
"""R0-01 — in/ghi manifest baseline (xem `ai/baseline.py` để biết manifest có gì).

    python manage.py baseline_manifest                    # in ra stdout
    python manage.py baseline_manifest --out manifest.json
    python manage.py baseline_manifest --compare cu.json   # so với manifest cũ
"""
import json

from django.core.management.base import BaseCommand

from ai.baseline import manifest as build_manifest


def _diff(old, new):
    """Những gì đổi giữa hai manifest, gọn cho người đọc — không phải deep-diff
    đầy đủ, chỉ đủ để trả lời "tại sao số liệu lần này khác lần trước"."""
    changes = []
    if old.get("git_commit") != new.get("git_commit"):
        changes.append(f"git_commit: {old.get('git_commit')!r} → {new.get('git_commit')!r}")
    if old.get("corpus", {}).get("fingerprint") != new.get("corpus", {}).get("fingerprint"):
        changes.append("corpus: kho đã đổi (vân tay khác)")
    for name, old_hash in (old.get("prompt_versions") or {}).items():
        new_hash = (new.get("prompt_versions") or {}).get(name)
        if old_hash != new_hash:
            changes.append(f"prompt[{name}]: {old_hash} → {new_hash}")
    old_routes = {r["task"]: (r["provider"], r["model"])
                  for r in (old.get("effective_routes") or [])}
    for row in new.get("effective_routes") or []:
        prev = old_routes.get(row["task"])
        cur = (row["provider"], row["model"])
        if prev is not None and prev != cur:
            changes.append(f"route[{row['task']}]: {prev} → {cur}")
    for name, info in (old.get("eval_datasets") or {}).items():
        new_info = (new.get("eval_datasets") or {}).get(name) or {}
        if info.get("hash") != new_info.get("hash"):
            changes.append(f"eval_dataset[{name}]: bộ câu hỏi đã đổi "
                           f"({info.get('count')} → {new_info.get('count')} câu)")
    return changes


class Command(BaseCommand):
    help = "In/ghi manifest baseline (kho, model route, prompt, bộ eval) — R0-01."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="", help="Ghi manifest ra tệp JSON.")
        parser.add_argument("--compare", default="",
                            help="Đường dẫn một manifest JSON cũ để so sánh.")

    def handle(self, *args, **options):
        data = build_manifest()
        text = json.dumps(data, ensure_ascii=False, indent=1)

        if options["compare"]:
            try:
                with open(options["compare"], "r", encoding="utf-8") as handle:
                    old = json.load(handle)
            except OSError as exc:
                self.stderr.write(self.style.ERROR(f"Không đọc được {options['compare']}: {exc}"))
                raise SystemExit(1)
            changes = _diff(old, data)
            if changes:
                self.stdout.write(self.style.WARNING(f"{len(changes)} thay đổi so với manifest cũ:"))
                for line in changes:
                    self.stdout.write(f"  - {line}")
            else:
                self.stdout.write(self.style.SUCCESS("Không có thay đổi so với manifest cũ."))

        if options["out"]:
            with open(options["out"], "w", encoding="utf-8") as handle:
                handle.write(text)
            self.stdout.write(f"Đã ghi {options['out']}")
        else:
            self.stdout.write(text)
