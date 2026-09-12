# -*- coding: utf-8 -*-
"""Seed dữ liệu Canonical Registry cho các namespace ưu tiên (Master Plan §6.2).

Ưu tiên: location → skill (song ngữ) → job_title → seniority → education → industry.
Đây là **hạt giống** để có gì mà chuẩn hoá ngay; alias chưa biết vẫn vào hàng chờ
và người quản trị mở rộng dần.
"""
from core.vn_locations import ALIASES as VN_PROVINCE_ALIASES

from .registry import add_alias, ensure_namespace, upsert_entry

# Địa chỉ cấp quận vẫn mang thông tin cấp tỉnh (Master Plan §16.4: "Quận 1" → HCM).
_DISTRICT_ALIASES = {
    "Hồ Chí Minh": [f"Quận {i}" for i in range(1, 13)] + [
        "Quận Bình Thạnh", "Quận Bình Tân", "Quận Gò Vấp", "Quận Tân Bình",
        "Quận Tân Phú", "Quận Phú Nhuận", "Quận Thủ Đức", "Thành phố Thủ Đức",
        "District 1", "District 7"],
    "Hà Nội": ["Quận Ba Đình", "Quận Hoàn Kiếm", "Quận Hai Bà Trưng", "Quận Đống Đa",
               "Quận Cầu Giấy", "Quận Thanh Xuân", "Quận Hoàng Mai", "Quận Long Biên",
               "Quận Hà Đông", "Quận Tây Hồ", "Quận Nam Từ Liêm", "Quận Bắc Từ Liêm"],
}

# --- location: 63 tỉnh/thành + alias phổ biến từ core.vn_locations ----------- #
_PROVINCE_CODES = {
    "Hà Nội": "VN-HN", "Hồ Chí Minh": "VN-SG", "Đà Nẵng": "VN-DN",
    "Hải Phòng": "VN-HP", "Cần Thơ": "VN-CT", "Bình Dương": "VN-BD",
    "Đồng Nai": "VN-DNA", "Bắc Ninh": "VN-BN", "Quảng Ninh": "VN-QN",
    "Khánh Hoà": "VN-KH", "Huế": "VN-TTH", "Vũng Tàu": "VN-BRVT",
    "Long An": "VN-LA", "Hưng Yên": "VN-HY", "Hải Dương": "VN-HD",
    "Thái Nguyên": "VN-TN", "Nghệ An": "VN-NA", "Thanh Hoá": "VN-TH",
    "Bắc Giang": "VN-BG", "Vĩnh Phúc": "VN-VP", "Nam Định": "VN-ND",
    "Quảng Nam": "VN-QNM", "Bình Định": "VN-BDH", "Lâm Đồng": "VN-LD",
    "Tiền Giang": "VN-TG", "Kiên Giang": "VN-KG", "An Giang": "VN-AG",
}

_SKILLS = [
    # code, label, [aliases song ngữ]
    ("sql", "SQL", ["sql", "ngon ngu truy van sql", "t-sql", "pl/sql"]),
    ("python", "Python", ["python", "py"]),
    ("java", "Java", ["java", "core java", "java se"]),
    ("javascript", "JavaScript", ["javascript", "js", "ecmascript"]),
    ("power-bi", "Power BI", ["power bi", "powerbi", "microsoft power bi", "pbi"]),
    ("excel", "Excel", ["excel", "microsoft excel", "ms excel"]),
    ("data", "Dữ liệu", ["data", "du lieu"]),  # lĩnh vực — cha, phải seed trước con
    ("data-analysis", "Phân tích dữ liệu", ["data analysis", "phan tich du lieu",
                                            "data analytics", "phan tich so lieu"]),
    ("react", "React", ["react", "reactjs", "react.js"]),
    ("nodejs", "Node.js", ["node js", "nodejs", "node.js"]),
    ("aws", "AWS", ["aws", "amazon web services"]),
    ("docker", "Docker", ["docker"]),
    ("kubernetes", "Kubernetes", ["kubernetes", "k8s"]),
    ("machine-learning", "Machine Learning", ["machine learning", "hoc may", "ml"]),
    ("communication", "Giao tiếp", ["communication", "ky nang giao tiep", "giao tiep"]),
    ("english", "Tiếng Anh", ["english", "tieng anh", "anh van"]),
    ("credit-appraisal", "Thẩm định tín dụng", ["credit appraisal", "tham dinh tin dung",
                                                "thẩm định tín dụng"]),
    ("sales", "Bán hàng", ["sales", "ban hang", "kinh doanh"]),
    ("selenium", "Selenium", ["selenium", "selenium webdriver"]),
]
_SKILL_PARENTS = {"data-analysis": "data"}

_JOB_TITLES = [
    ("data-analyst", "Data Analyst", ["data analyst", "chuyen vien phan tich du lieu",
                                      "nhan vien phan tich du lieu"]),
    ("business-analyst", "Business Analyst", ["business analyst", "ba",
                                             "chuyen vien phan tich nghiep vu"]),
    ("backend-engineer", "Backend Engineer", ["backend engineer", "backend developer",
                                              "lap trinh vien backend", "ky su backend"]),
    ("frontend-engineer", "Frontend Engineer", ["frontend engineer", "frontend developer",
                                                "lap trinh vien frontend"]),
    ("devops-engineer", "DevOps Engineer", ["devops engineer", "devops", "sre"]),
    ("qa-engineer", "QA Engineer", ["qa engineer", "kiem thu phan mem", "tester",
                                    "qa automation"]),
    ("product-manager", "Product Manager", ["product manager", "pm", "quan ly san pham"]),
    ("recruiter", "Chuyên viên Tuyển dụng", ["recruiter", "chuyen vien tuyen dung",
                                             "sourcing specialist", "talent acquisition"]),
    ("relationship-manager", "Quan hệ Khách hàng", ["relationship manager", "rm",
                                                    "chuyen vien quan he khach hang",
                                                    "chuyen vien khach hang"]),
    ("credit-officer", "Chuyên viên Tín dụng", ["credit officer", "chuyen vien tin dung",
                                                "nhan vien tin dung"]),
    ("branch-manager", "Giám đốc Chi nhánh", ["branch manager", "giam doc chi nhanh"]),
    ("chief-accountant", "Kế toán trưởng", ["chief accountant", "ke toan truong"]),
]

_SENIORITY = [
    ("intern", "Thực tập sinh", ["intern", "thuc tap sinh", "internship", "ttS"]),
    ("fresher", "Mới ra trường", ["fresher", "fresh graduate", "moi ra truong",
                                  "moi tot nghiep"]),
    ("junior", "Junior", ["junior", "jr", "nhan vien"]),
    ("mid", "Middle", ["middle", "mid", "mid-level", "trung cap"]),
    ("senior", "Senior", ["senior", "sr", "chuyen vien chinh", "chuyen gia"]),
    ("lead", "Lead", ["lead", "team lead", "truong nhom", "tech lead"]),
    ("manager", "Manager", ["manager", "quan ly", "truong phong", "truong bo phan"]),
    ("director", "Director", ["director", "giam doc", "pho giam doc"]),
    ("executive", "Executive", ["executive", "ceo", "cfo", "cto", "tong giam doc"]),
]

_EDUCATION = [
    ("highschool", "Trung học phổ thông", ["thpt", "trung hoc pho thong", "high school",
                                           "tot nghiep cap 3", "12/12"]),
    ("intermediate", "Trung cấp", ["trung cap", "intermediate"]),
    ("college", "Cao đẳng", ["cao dang", "college", "associate"]),
    ("bachelor", "Cử nhân / Đại học", ["cu nhan", "dai hoc", "bachelor", "bachelor's",
                                       "ky su", "engineer degree", "b.sc", "bsc", "ba", "be"]),
    ("master", "Thạc sĩ", ["thac si", "master", "master's", "m.sc", "msc", "mba"]),
    ("phd", "Tiến sĩ", ["tien si", "phd", "doctor", "doctorate", "ph.d"]),
]

_INDUSTRIES = [
    ("banking", "Ngân hàng", ["ngan hang", "banking", "bank"]),
    ("fintech", "Fintech", ["fintech", "cong nghe tai chinh"]),
    ("insurance", "Bảo hiểm", ["bao hiem", "insurance", "bao hiem nhan tho"]),
    ("it-software", "CNTT / Phần mềm", ["cntt", "phan mem", "software", "it",
                                       "cong nghe thong tin"]),
    ("ecommerce", "Thương mại điện tử", ["thuong mai dien tu", "ecommerce", "e-commerce"]),
    ("logistics", "Logistics", ["logistics", "van tai", "chuoi cung ung", "supply chain"]),
    ("manufacturing", "Sản xuất", ["san xuat", "manufacturing", "nha may"]),
    ("retail", "Bán lẻ", ["ban le", "retail"]),
    ("marketing", "Marketing", ["marketing", "truyen thong", "quang cao"]),
]


def seed_all(*, stdout=None):
    def say(msg):
        if stdout:
            stdout.write(msg)

    # location
    ns_loc = ensure_namespace("location", "Địa lý", fold_diacritics=True)
    for label, code in _PROVINCE_CODES.items():
        entry = upsert_entry(ns_loc, code, label, attrs={"level": "province", "country": "VN"})
        add_alias(ns_loc, label, entry, source="seed")
        for alias in VN_PROVINCE_ALIASES.get(label, []):
            add_alias(ns_loc, alias, entry, source="seed")
        for alias in _DISTRICT_ALIASES.get(label, []):
            add_alias(ns_loc, alias, entry, source="seed")
    say(f"location: {len(_PROVINCE_CODES)} tỉnh/thành")

    _seed_list("skill", "Kỹ năng & công nghệ", _SKILLS, parents=_SKILL_PARENTS, say=say)
    _seed_list("job_title", "Chức danh", _JOB_TITLES, say=say)
    _seed_list("seniority", "Cấp bậc", _SENIORITY, say=say)
    _seed_list("education_level", "Trình độ học vấn", _EDUCATION, say=say)
    _seed_list("industry", "Ngành nghề", _INDUSTRIES, say=say)
    # Các namespace còn lại tạo trống để resolve() gom alias vào hàng chờ.
    for key, label in (("company", "Công ty"), ("university", "Trường"),
                       ("language", "Ngôn ngữ"), ("certification", "Chứng chỉ"),
                       ("source", "Nguồn thu nhận")):
        ensure_namespace(key, label, fold_diacritics=True)
    say("company/university/language/certification/source: namespace trống (hàng chờ alias)")


def _seed_list(key, label, rows, *, parents=None, say=None):
    ns = ensure_namespace(key, label, fold_diacritics=True)
    parents = parents or {}
    for code, entry_label, aliases in rows:
        entry = upsert_entry(ns, code, entry_label, parent_code=parents.get(code, ""))
        add_alias(ns, entry_label, entry, source="seed")
        for alias in aliases:
            add_alias(ns, alias, entry, source="seed")
    if say:
        say(f"{key}: {len(rows)} mã")
