# -*- coding: utf-8 -*-
"""Quy tắc theo từng field — bám docs/DATA_DICTIONARY.md và Master Plan §7.3, §21.1.

`mode`:
    latest  — bản có evidence mới nhất là hiện hành; bản cũ `is_current=False`.
    merge   — mọi giá trị accepted đều hiện hành (kỹ năng cũ không tự mất).
`namespace` — danh mục Canonical Registry để chuẩn hoá (rỗng = không chuẩn hoá).
`sensitive` — luôn vào review, không auto-accept (S2/S3).
`auto_accept` — được nhận tự động khi confidence ≥ `gate` và không curated.
"""

FIELD_RULES = {
    # --- định danh ---
    "full_name":       {"mode": "latest", "namespace": "", "sensitive": False, "auto_accept": True,  "gate": 0.80},
    "email":           {"mode": "merge",  "namespace": "", "sensitive": True,  "auto_accept": False, "gate": 0.99},
    "phone":           {"mode": "merge",  "namespace": "", "sensitive": True,  "auto_accept": False, "gate": 0.99},
    "gender":          {"mode": "latest", "namespace": "", "sensitive": True,  "auto_accept": False, "gate": 1.01},
    "date_of_birth":   {"mode": "latest", "namespace": "", "sensitive": True,  "auto_accept": False, "gate": 1.01},
    # --- địa lý ---
    "city":            {"mode": "latest", "namespace": "location", "sensitive": False, "auto_accept": True, "gate": 0.75},
    "current_address": {"mode": "latest", "namespace": "", "sensitive": True,  "auto_accept": False, "gate": 1.01},
    "location_interest": {"mode": "merge", "namespace": "location", "sensitive": False, "auto_accept": True, "gate": 0.75},
    # --- kinh nghiệm ---
    "current_title":   {"mode": "latest", "namespace": "job_title", "sensitive": False, "auto_accept": True, "gate": 0.75},
    "current_company": {"mode": "latest", "namespace": "company",   "sensitive": False, "auto_accept": True, "gate": 0.75},
    "seniority":       {"mode": "latest", "namespace": "seniority", "sensitive": False, "auto_accept": True, "gate": 0.75},
    "years_experience": {"mode": "latest", "namespace": "", "sensitive": False, "auto_accept": True, "gate": 0.70},
    # Tóm tắt năng lực: AI diễn giải lại nội dung CV vốn đã lưu, evidence bắt
    # buộc, không nhạy cảm. Trước đây gate 1.01 (không thể đạt) khiến nó kẹt ở
    # `proposed` mãi -> `current_facts` bỏ qua -> cột `TalentProfile.summary`
    # rỗng trên toàn kho (chỉ mục ngữ nghĩa có đọc cột này). Gate 0.85 cao nhưng
    # đạt được: nhận khi AI tự tin, còn lại vẫn vào review.
    "experience_summary": {"mode": "latest", "namespace": "", "sensitive": False, "auto_accept": True, "gate": 0.85},
    # --- học vấn ---
    "education_level": {"mode": "latest", "namespace": "education_level", "sensitive": False, "auto_accept": True, "gate": 0.75},
    "university":      {"mode": "latest", "namespace": "university", "sensitive": False, "auto_accept": True, "gate": 0.80},
    "major":           {"mode": "latest", "namespace": "", "sensitive": False, "auto_accept": True, "gate": 0.80},
    "graduation_year": {"mode": "latest", "namespace": "", "sensitive": False, "auto_accept": True, "gate": 0.80},
    "gpa":             {"mode": "latest", "namespace": "", "sensitive": False, "auto_accept": True, "gate": 0.80},
    # --- năng lực (merge) ---
    "skills":          {"mode": "merge", "namespace": "skill", "sensitive": False, "auto_accept": True, "gate": 0.70},
    "industries":      {"mode": "merge", "namespace": "industry", "sensitive": False, "auto_accept": True, "gate": 0.70},
    "languages":       {"mode": "merge", "namespace": "language", "sensitive": False, "auto_accept": True, "gate": 0.75},
    "certifications":  {"mode": "merge", "namespace": "certification", "sensitive": False, "auto_accept": True, "gate": 0.80},
    # "achievements" là mảng câu tự do (giải thưởng, dự án nổi bật, KPI đạt
    # được) — merge như skills: thành tích cũ không tự mất khi có CV mới.
    # KHÔNG có namespace chuẩn hoá (không như "công ty"/"kỹ năng", một câu
    # thành tích không quy về một mã canonical hữu ích).
    "achievements":    {"mode": "merge", "namespace": "", "sensitive": False, "auto_accept": True, "gate": 0.70},
    # --- nhu cầu nghề nghiệp ---
    "expected_salary": {"mode": "latest", "namespace": "", "sensitive": True,  "auto_accept": False, "gate": 1.01},
    "notice_period":   {"mode": "latest", "namespace": "", "sensitive": False, "auto_accept": True, "gate": 0.75},
    # Các trường Edge bóc từ TRANG CHI TIẾT của nhà tuyển dụng (không phải suy
    # từ CV): ứng viên tự khai nên đáng tin, gate thấp. Trước đây chúng chỉ tới
    # được `TalentProfile` nên query được bằng ORM nhưng KHÔNG có provenance,
    # không vào review/canonical và không so khớp được ở tầng fact.
    "desired_location": {"mode": "merge",  "namespace": "location", "sensitive": False, "auto_accept": True, "gate": 0.70},
    "desired_level":   {"mode": "latest", "namespace": "seniority", "sensitive": False, "auto_accept": True, "gate": 0.75},
    "desired_position": {"mode": "latest", "namespace": "job_title", "sensitive": False, "auto_accept": True, "gate": 0.75},
    "job_type":        {"mode": "latest", "namespace": "", "sensitive": False, "auto_accept": True, "gate": 0.75},
    # Lương hiện tại nhạy cảm y như lương mong muốn — luôn qua người duyệt.
    "current_salary":  {"mode": "latest", "namespace": "", "sensitive": True,  "auto_accept": False, "gate": 1.01},
    # Tình trạng hôn nhân là dữ liệu nhân thân: không auto-accept (như gender).
    "marital_status":  {"mode": "latest", "namespace": "", "sensitive": True,  "auto_accept": False, "gate": 1.01},
    # Ngoại ngữ Edge gửi dạng "German - Native | English - Intermediate" — nhiều
    # giá trị trong một chuỗi nên merge, cùng namespace với `languages`.
    "foreign_language": {"mode": "merge", "namespace": "language", "sensitive": False, "auto_accept": True, "gate": 0.75},
    # --- tuyển dụng (thuộc lần ứng tuyển) ---
    "applied_position": {"mode": "latest", "namespace": "job_title", "sensitive": False, "auto_accept": True, "gate": 0.80},
    "applied_date":    {"mode": "latest", "namespace": "", "sensitive": False, "auto_accept": True, "gate": 0.90},
    "source":          {"mode": "latest", "namespace": "source", "sensitive": False, "auto_accept": True, "gate": 0.90},
}

MERGE_FIELDS = {name for name, rule in FIELD_RULES.items() if rule["mode"] == "merge"}
KNOWN_FIELDS = set(FIELD_RULES)


def rule_for(field):
    return FIELD_RULES.get(field, {"mode": "latest", "namespace": "", "sensitive": True,
                                   "auto_accept": False, "gate": 1.01})
