# -*- coding: utf-8 -*-
"""Xuất dữ liệu ứng viên THEO ĐÚNG cột của `fields.py` — chiều ngược của
`download_template` (đó là khung rỗng để NHẬP; đây là dữ liệu THẬT để XUẤT).

Cùng một bộ cột cho cả hai chiều là điểm mấu chốt: chủ dự án muốn hệ thống này
"ăn khớp" với template của một nền tảng phân tích CV khác — file xuất ra từ
đây import ngược lại chính `fields.py` (hoặc nền tảng kia, nếu họ dùng đúng tên
cột) phải chạy được, không cần map tay.

Che liên hệ THEO ĐÚNG quy ước đã có ở `talent/views.py::talent_search_export`:
xuất file là lúc dữ liệu RỜI KHỎI hệ thống, nên `email`/`phone` luôn qua
`accounts.privacy` — không có tham số nào bật lại bản thô. Ai cần liên hệ đầy
đủ thì dùng "mở khoá liên hệ" trên từng hồ sơ, đúng hạn mức đã có.
"""
import csv

from accounts import privacy
from django.http import HttpResponse

from people.models import Person

from . import fields as fields_mod


def _facts_by_field(person_id):
    """{field: [normalized_value, ...]} — CHỈ fact đã duyệt VÀ hiện hành.

    Xuất file là nơi dữ liệu rời hệ thống, không phải nơi debug — chỉ đưa dữ
    liệu đã qua gate (`ExtractedFact.STATUS_ACCEPTED`), như `current_facts()`
    dùng cho mọi chỗ hiển thị "sự thật hiện hành" khác trong hệ thống.
    """
    from intel.facts import current_facts

    out = {}
    for fact in current_facts(person_id):
        value = fact.normalized_value or fact.raw_value
        if not value:
            continue
        out.setdefault(fact.field, []).append(value)
    return out


#: Khoá cột `intake/fields.py` → cách lấy giá trị. Ưu tiên `ExtractedFact` (có
#: nguồn, đã qua gate); một số khoá không có field AI tương ứng thì đọc thẳng
#: `TalentProfile`/`Person` (dữ liệu Edge/derive) — chưa có nguồn nào thì để
#: trống, KHÔNG suy đoán hay điền giá trị ước lượng vào ô xuất.
def _resolve(person, talent, facts):
    def fact(field):
        return "; ".join(facts.get(field, []))

    t = lambda attr: (getattr(talent, attr, "") or "") if talent else ""  # noqa: E731

    return {
        "fullname": person.display_name,
        "email": privacy.mask_email(person.primary_email),
        "phone": privacy.mask_phone(person.primary_phone),
        "position": fact("applied_position"),
        "current_title": t("current_title") or fact("current_title"),
        "last_company": t("current_company") or fact("current_company"),
        "years_experience": t("years_experience") or fact("years_experience"),
        "job_level": t("seniority") or fact("seniority"),
        "education": t("education") or fact("education_level"),
        "skills": ", ".join(talent.skills) if talent and talent.skills else fact("skills"),
        "expected_salary": fact("expected_salary"),
        "notice_period": fact("notice_period"),
        "city": t("location") or fact("city"),
        "district": "",                       # chưa có nguồn nào trong hệ thống
        "address": fact("current_address"),
        "gender": fact("gender"),
        "birth_year": fact("date_of_birth")[:4] if fact("date_of_birth") else "",
        "linkedin": "",                       # chưa có nguồn nào trong hệ thống
        "portfolio": "",                      # chưa có nguồn nào trong hệ thống
        "university": fact("university"),
        "major": fact("major"),
        "gpa": fact("gpa"),
        "graduation_year": fact("graduation_year"),
        "certifications": fact("certifications"),
        "achievements": fact("achievements"),
        "language_proficiency": fact("languages"),
        "industry": ", ".join(talent.industries) if talent and talent.industries else fact("industries"),
        "experience_summary": fact("experience_summary"),
        "career_goals": "",                   # chưa có nguồn nào trong hệ thống
        "labels": "",                         # chưa có nguồn nào trong hệ thống
        "applied_at": fact("applied_date"),
        "source": fact("source"),
        "other_info": "",                     # chưa có field AI tương ứng
        "cv_file_name": "",                   # nhiều Document/người — xem hồ sơ để tải đúng bản
        # Ba khái niệm mới 05/09 — chưa có field AI tương ứng (birth_date khác
        # date_of_birth về ngữ nghĩa lưu trữ; applied_region/external_assessment
        # là khái niệm mới hoàn toàn) nên luôn trống ở export tự động; điền
        # được khi nhập tay/nhập từ nền tảng khác rồi commit vào hệ thống.
        "birth_date": "",
        "applied_region": "",
        "external_assessment": "",
    }


def export_candidates(queryset=None):
    """`HttpResponse` CSV đúng cột `fields.py`, một dòng mỗi Person.

    `queryset=None` → toàn kho (chưa gộp). Nhận `queryset` để tái dùng khi cần
    xuất một tập lọc sẵn (ví dụ kết quả tìm kiếm) mà không viết lại cột.
    """
    people = (queryset if queryset is not None else
             Person.objects.filter(merged_into__isnull=True)
             ).select_related("talent_profile").order_by("pk")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="radar_xuat_ung_vien.csv"'
    response.write("﻿")          # BOM — Excel Windows đọc đúng UTF-8

    writer = csv.writer(response)
    writer.writerow(fields_mod.template_headers())
    for person in people.iterator(chunk_size=200):
        talent = getattr(person, "talent_profile", None)
        facts = _facts_by_field(person.pk)
        row = _resolve(person, talent, facts)
        writer.writerow([row.get(col.key, "") for col in fields_mod.COLUMNS])
    return response
