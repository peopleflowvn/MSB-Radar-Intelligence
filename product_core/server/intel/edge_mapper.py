# -*- coding: utf-8 -*-
"""Ánh xạ payload Edge → field nghiệp vụ (Master Plan §2.1, §7.1 bước 2).

Bảng khoá bám `docs/DATA_DICTIONARY.md §4`. Đã đối chiếu payload **thật** của
TopCV (Edge `topcv`, xem DATA_DICTIONARY §4): provider này gửi `position` = vị trí
**ứng tuyển** (không phải chức danh hiện tại — khoá `current_title` riêng, thường
rỗng), có `district`/`birth_year`, ngày ở `applied_ts` (ISO) và `applied_at` (dd/mm/yyyy).

Nguyên tắc: đọc thẳng, KHÔNG gọi AI để "đoán lại" trường Edge đã gửi (§7.2).
"""
from datetime import datetime

from django.utils import timezone

# field nghiệp vụ  ←  (các khoá payload, theo thứ tự ưu tiên)
PAYLOAD_KEYS = {
    "full_name": ("fullname", "full_name", "name"),
    "email": ("email",),
    "phone": ("phone", "mobile"),
    "gender": ("gender",),
    "date_of_birth": ("date_of_birth", "birth_year", "dob"),
    # `position` KHÔNG map vào current_title: với TopCV đó là vị trí ứng tuyển.
    "current_title": ("current_title",),
    "current_company": ("last_company", "current_company", "company"),
    "seniority": ("job_level", "seniority"),
    "education_level": ("education", "education_level"),
    "expected_salary": ("expected_salary", "salary_expectation"),
    "city": ("city", "address", "district", "location"),
    "years_experience": ("years_experience", "experience"),
    "skills": ("skills",),
    "applied_position": ("position", "applied_position"),
    "applied_date": ("applied_ts", "applied_date", "applied_at"),
    "source": ("source",),
    "notice_period": ("notice_period",),
    # Trường Edge bóc từ trang chi tiết nhà tuyển dụng (ứng viên tự khai).
    # Trước đây chỉ tới `TalentProfile`, không thành fact nên không có provenance.
    "desired_location": ("desired_location",),
    "desired_level": ("desired_level",),
    "desired_position": ("desired_position",),
    "job_type": ("job_type",),
    "current_salary": ("current_salary",),
    "marital_status": ("marital_status",),
    "foreign_language": ("foreign_language",),
}

# Trường lấy nguyên list, không tách chuỗi.
_LIST_FIELDS = {"skills"}


def _parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    # birth_year: chỉ có năm.
    if text.isdigit() and len(text) == 4 and 1940 <= int(text) <= 2015:
        text = f"{text}-01-01"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
                "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
        except (ValueError, TypeError):
            continue
    return None


def map_record(source_record):
    """Trả list dict: {field, raw_value, observed_at}. Bỏ khoá rỗng."""
    payload = source_record.payload or {}
    observed = _parse_dt(payload.get("applied_ts")) or source_record.last_seen_at
    rows = []
    for field, keys in PAYLOAD_KEYS.items():
        value = None
        for key in keys:
            candidate = payload.get(key)
            if candidate not in (None, "", [], {}):
                value = candidate
                break
        if value is None:
            continue
        if field in ("applied_date", "date_of_birth"):
            dt = _parse_dt(value)
            if dt is None:
                continue
            rows.append({"field": field, "raw_value": dt.date().isoformat(),
                         "observed_at": observed, "value_dt": dt})
            continue
        if field in _LIST_FIELDS and isinstance(value, str):
            for part in _split_list(value):
                rows.append({"field": field, "raw_value": part, "observed_at": observed})
            continue
        if field in _LIST_FIELDS and isinstance(value, (list, tuple)):
            for part in value:
                if str(part).strip():
                    rows.append({"field": field, "raw_value": str(part).strip(),
                                 "observed_at": observed})
            continue
        rows.append({"field": field, "raw_value": str(value).strip(),
                     "observed_at": observed})
    return rows


def _split_list(text):
    seen, out = set(), []
    for chunk in str(text or "").replace("\n", ",").replace(";", ",").replace("|", ",").split(","):
        name = " ".join(chunk.split())
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out
