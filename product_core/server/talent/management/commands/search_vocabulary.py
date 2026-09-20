# -*- coding: utf-8 -*-
"""Quản trị từ điển canonical/alias của query compiler (SEARCH-P1-02B).

Từ điển là nội dung nghiệp vụ, không phải code: thêm một cách gọi chức danh
không được đòi một lần deploy. Lệnh này để Product-Ops xuất ra soát, sửa file,
rồi nạp lại — mỗi lần nạp tăng `version` nên `explain` của truy vấn nói được nó
đã dùng bản nào.

    python manage.py search_vocabulary list
    python manage.py search_vocabulary list --kind title
    python manage.py search_vocabulary export --out vocab.json
    python manage.py search_vocabulary import --file vocab.json --by "tên người"

Định dạng file: `{"<kind>": {"<canonical>": ["alias", …]}}`. `import` là
update-or-create theo (kind, canonical); không xoá dòng nào không có trong file
— muốn tắt thì đặt `enabled=false` qua `--disable kind:canonical`.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from talent.models import SearchVocabulary
from talent.search_v2 import canonical


class Command(BaseCommand):
    help = "Xem, xuất và nạp từ điển canonical/alias cho tìm kiếm."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("list", "export", "import", "disable"))
        parser.add_argument("--kind", default="")
        parser.add_argument("--file", default="")
        parser.add_argument("--out", default="")
        parser.add_argument("--by", default="")
        parser.add_argument("--target", default="", help="disable: kind:canonical")

    def handle(self, *args, **options):
        action = options["action"]
        if action == "list":
            return self._list(options["kind"])
        if action == "export":
            return self._export(options["out"], options["kind"])
        if action == "disable":
            return self._disable(options["target"], options["by"])
        return self._import(options["file"], options["by"])

    def _rows(self, kind=""):
        rows = SearchVocabulary.objects.all().order_by("kind", "canonical")
        return rows.filter(kind=kind) if kind else rows

    def _list(self, kind):
        for row in self._rows(kind):
            state = "" if row.enabled else " [tắt]"
            self.stdout.write(
                f"{row.kind}: {row.canonical}{state} v{row.version} "
                f"← {', '.join(row.aliases or [])}")
        self.stdout.write(f"tổng {self._rows(kind).count()} dòng")

    def _export(self, out, kind):
        data = {}
        for row in self._rows(kind).filter(enabled=True):
            data.setdefault(row.kind, {})[row.canonical] = list(row.aliases or [])
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        if out:
            Path(out).write_text(text, encoding="utf-8")
            self.stdout.write(f"Đã ghi {out}")
        else:
            self.stdout.write(text)

    @transaction.atomic
    def _import(self, file_path, by):
        if not file_path:
            raise CommandError("import cần --file")
        path = Path(file_path)
        if not path.is_file():
            raise CommandError(f"Không thấy file: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"File không phải JSON hợp lệ: {exc}") from exc
        if not isinstance(data, dict):
            raise CommandError('File phải có dạng {"kind": {"canonical": ["alias"]}}')
        created, updated = 0, 0
        for kind, rows in data.items():
            if kind not in SearchVocabulary.KINDS:
                raise CommandError(
                    f"kind không hỗ trợ: {kind} (chọn trong {', '.join(SearchVocabulary.KINDS)})")
            if not isinstance(rows, dict):
                raise CommandError(f"{kind}: phải là object canonical → danh sách alias")
            for raw_canonical, aliases in rows.items():
                if not isinstance(aliases, list):
                    raise CommandError(f"{kind}/{raw_canonical}: alias phải là danh sách")
                key = canonical(raw_canonical)
                if not key:
                    raise CommandError(f"{kind}: canonical rỗng")
                clean = [alias for alias in
                         dict.fromkeys([key, *[canonical(x) for x in aliases]]) if alias]
                row = SearchVocabulary.objects.filter(kind=kind, canonical=key).first()
                if row is None:
                    SearchVocabulary.objects.create(
                        kind=kind, canonical=key, aliases=clean, version=1,
                        updated_by=by or "search_vocabulary.import")
                    created += 1
                    continue
                if list(row.aliases or []) != clean or not row.enabled:
                    row.aliases = clean
                    row.enabled = True
                    row.version = int(row.version or 0) + 1
                    row.updated_by = by or "search_vocabulary.import"
                    row.save(update_fields=["aliases", "enabled", "version",
                                            "updated_by", "updated_at"])
                    updated += 1
        self.stdout.write(self.style.SUCCESS(
            f"thêm={created} sửa={updated} tổng={SearchVocabulary.objects.count()}"))

    def _disable(self, target, by):
        if ":" not in str(target):
            raise CommandError("disable cần --target kind:canonical")
        kind, _, raw = str(target).partition(":")
        row = SearchVocabulary.objects.filter(kind=kind, canonical=canonical(raw)).first()
        if row is None:
            raise CommandError(f"Không thấy {target}")
        row.enabled = False
        row.version = int(row.version or 0) + 1
        row.updated_by = by or "search_vocabulary.disable"
        row.save(update_fields=["enabled", "version", "updated_by", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"đã tắt {kind}:{row.canonical}"))
