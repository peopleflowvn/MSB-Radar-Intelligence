# -*- coding: utf-8 -*-
"""Xuất một lô CV để nghiệp vụ gán nhãn vàng (Master Plan §15, Giai đoạn 0).

Dựng bộ nhãn *extraction theo field*: mỗi CV kèm text đã parsing và các trường
Hub đang suy ra hiện tại, cộng một khung `gold` trống để người gán nhãn điền tay.
So sánh `gold` với đầu ra AI ở Giai đoạn 3 cho ra precision/recall theo từng
field (Master Plan §16.1).

    python manage.py export_label_batch --count 150 --seed 42

Sinh ra, trong `docs/benchmark/label_batch/<UTC>/`:
    manifest.json   — metadata lô (seed, bộ lọc, danh sách person_id)
    worksheet.jsonl — một dòng/CV: text + trường hiện tại + khung gold trống
    worksheet.csv   — bản phẳng cho người quen dùng bảng tính

Chọn mẫu tất định theo `--seed`: cùng seed + cùng dữ liệu ⇒ cùng lô.
"""
import csv
import json
import random
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from people.models import Document, Person

# Khung trường gold. Bám theo Master Plan §4 và các test case bắt buộc §16.4.
# Người gán nhãn để trống nếu CV không có; ghi "" nghĩa là "đã xem, không có".
GOLD_FIELDS = [
    "full_name", "email", "phone", "gender", "date_of_birth",
    "city", "current_address",
    "current_title", "current_company", "years_experience", "seniority",
    "education_level", "university", "major", "graduation_year", "gpa",
    "skills",                    # danh sách, phân tách bằng dấu ';'
    "languages", "certifications",
    "expected_salary", "notice_period", "location_interest", "job_title_interest",
    "applied_position", "applied_date", "requisition_id", "source",
]


class Command(BaseCommand):
    help = "Xuất một lô CV (text + trường hiện tại + khung gold) để gán nhãn."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=150)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--min-chars", type=int, default=400,
                            help="Bỏ qua CV có text ngắn hơn ngưỡng này")
        parser.add_argument("--out", default="",
                            help="Thư mục ra; mặc định docs/benchmark/label_batch/<UTC>/")

    def handle(self, *args, **opts):
        count, seed, min_chars = opts["count"], opts["seed"], opts["min_chars"]

        # Ứng viên: Person còn hiệu lực, có ít nhất một CV parsing xong đủ dài.
        doc_qs = (Document.objects
                  .filter(document_type="cv", parse_status=Document.PARSE_DONE,
                          person__merged_into__isnull=True)
                  .select_related("person", "person__talent_profile",
                                  "primary_text_version")
                  .order_by("person_id", "-observed_at", "-created_at"))

        best_by_person = {}
        for doc in doc_qs.iterator():
            if doc.person_id in best_by_person:
                continue
            text = doc.best_text or ""
            if len(text) < min_chars:
                continue
            best_by_person[doc.person_id] = doc

        person_ids = sorted(best_by_person)
        rng = random.Random(seed)
        rng.shuffle(person_ids)
        picked = person_ids[:count]

        if not picked:
            self.stdout.write(self.style.WARNING(
                "Không có CV nào đạt điều kiện. Kho có thể chưa parsing xong."))
            return

        stamp = f"{datetime.now(dt_timezone.utc):%Y%m%dT%H%M%SZ}"
        out_dir = Path(opts["out"]) if opts["out"] else (
            Path(settings.BASE_DIR).parent / "docs" / "benchmark" / "label_batch" / stamp)
        out_dir.mkdir(parents=True, exist_ok=True)

        gold_blank = {field: None for field in GOLD_FIELDS}
        worksheet_path = out_dir / "worksheet.jsonl"
        csv_path = out_dir / "worksheet.csv"

        with worksheet_path.open("w", encoding="utf-8") as wf, \
                csv_path.open("w", encoding="utf-8-sig", newline="") as cf:
            writer = csv.writer(cf)
            writer.writerow(["person_id", "document_id", "filename", "observed_at",
                             "cv_text"] + [f"gold.{f}" for f in GOLD_FIELDS])
            for person_id in picked:
                doc = best_by_person[person_id]
                person = doc.person
                talent = getattr(person, "talent_profile", None)
                row = {
                    "person_id": person_id,
                    "document_id": doc.pk,
                    "filename": doc.filename,
                    "observed_at": doc.observed_at.isoformat() if doc.observed_at else None,
                    "current_derived": {
                        "display_name": person.display_name,
                        "primary_email": person.primary_email,
                        "primary_phone": person.primary_phone,
                        "location": person.location,
                        "current_title": getattr(talent, "current_title", ""),
                        "current_company": getattr(talent, "current_company", ""),
                        "years_experience": getattr(talent, "years_experience", None),
                        "seniority": getattr(talent, "seniority", ""),
                        "education": getattr(talent, "education", ""),
                        "expected_salary": getattr(talent, "expected_salary", ""),
                        "skills": list(getattr(talent, "skills", []) or []),
                        "industries": list(getattr(talent, "industries", []) or []),
                        "curated_fields": list(getattr(talent, "curated_fields", []) or []),
                    },
                    "cv_text": doc.best_text or "",
                    "gold": dict(gold_blank),
                }
                wf.write(json.dumps(row, ensure_ascii=False) + "\n")
                writer.writerow(
                    [person_id, doc.pk, doc.filename,
                     row["observed_at"], (doc.best_text or "").replace("\r", " ")]
                    + ["" for _ in GOLD_FIELDS])

        manifest = {
            "kind": "talent_extraction_label_batch",
            "generated_at": datetime.now(dt_timezone.utc).isoformat(),
            "seed": seed,
            "requested_count": count,
            "actual_count": len(picked),
            "min_chars": min_chars,
            "eligible_pool": len(person_ids),
            "total_people": Person.objects.filter(merged_into__isnull=True).count(),
            "gold_fields": GOLD_FIELDS,
            "person_ids": picked,
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(
            f"Đã xuất {len(picked)} CV (trên {len(person_ids)} đạt điều kiện) → {out_dir}"))
