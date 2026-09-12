# -*- coding: utf-8 -*-
"""Từ điển cột: tiêu đề tệp Excel/CSV ↔ khoá `payload` của bàn nhận.

Khoá payload bám theo `edge/app/sync/payload.py::CANDIDATE_FIELDS` để dữ liệu
nhập tay và dữ liệu Edge chảy qua **cùng một** mapper (`talent/derive.py`) và
cùng một bộ phân giải định danh (`people/resolution.py`). Không đặt tên khoá mới
khi Edge đã có khoá cho đúng khái niệm đó.

Master Plan §4 có những trường chưa xuất hiện trong payload Edge (`university`,
`major`, `gpa`, `certifications`, …). Ta vẫn nhận và giữ nguyên trong payload —
`derive.py` chưa đọc, nhưng raw được bảo toàn (§2.2) để Phase 2 / AI-fill dùng.

Cập nhật 05/09: đối chiếu với template CSV của một nền tảng phân tích CV khác
(chủ dự án cung cấp) để hai bên **ăn khớp cột** — cùng tên khái niệm thì import
được thẳng, không phải map tay. Hầu hết cột của họ đã trùng cột ở đây qua alias
sẵn có; ba khái niệm THẬT SỰ MỚI được thêm ở cuối danh sách:

* `birth_date` — NGÀY sinh đầy đủ (dd/mm/yyyy), khác `birth_year` (chỉ năm) đã
  có từ trước. Hai cột riêng, không gộp — mất độ chính xác nếu ép ngày thành
  năm ở đây; giữ nguyên rồi để lớp đọc sau (derive/AI-fill) quyết định dùng cột
  nào cho từng việc.
* `applied_region` — khu vực/tỉnh thành NƠI ỨNG TUYỂN, khác `city` (nơi Ở HIỆN
  TẠI). Hai khái niệm khác nhau: ứng viên có thể sống Đà Nẵng, ứng tuyển vị trí
  ở Hà Nội.
* `external_assessment` — nhận xét/đánh giá đã có SẴN từ nguồn ngoài (nền tảng
  khác, hoặc người sàng lọc trước đó). LƯU Ý KHÁC BIỆT VỀ LOẠI DỮ LIỆU: đây là
  một PHÁN ĐOÁN đã thành hình, không phải một dữ kiện quan sát được như các cột
  còn lại — Radar giữ nguyên làm ghi chú tham khảo, không coi là "fact có
  nguồn" theo nghĩa `intel/field_rules.py` (không auto-accept dù dữ liệu vào
  từ đâu).
"""
import re

from people.normalize import normalize_email, normalize_phone


class Column:
    __slots__ = ("header", "aliases", "key", "kind", "sensitive")

    def __init__(self, header, key, aliases=(), kind="text", sensitive=False):
        self.header = header          # tiêu đề chuẩn, dùng khi sinh template
        self.key = key                # khoá trong SourceRecord.payload
        self.aliases = tuple(aliases)  # tiêu đề khác cùng nghĩa (VN/EN/cũ)
        self.kind = kind              # text | email | phone | url | int | date
        self.sensitive = sensitive    # trường nhạy cảm (Master Plan §14)


# Thứ tự ở đây là thứ tự cột trong file template.
COLUMNS = [
    Column("Họ tên", "fullname", ["Name", "Full Name", "Ứng viên", "Tên ứng viên"]),
    Column("Email", "email", ["E-mail", "Địa chỉ email"], kind="email"),
    Column("Số điện thoại", "phone", ["Mobile", "Phone", "SĐT", "Điện thoại"], kind="phone"),
    Column("Vị trí ứng tuyển", "position", ["Position", "Applied Position", "Vị trí"]),
    Column("Chức danh hiện tại", "current_title", ["Current Title", "Job Title"]),
    Column("Công ty gần nhất", "last_company", ["Last Company", "Current Company", "Công ty"]),
    Column("Số năm kinh nghiệm", "years_experience", ["Years of Experience", "YOE"], kind="int"),
    Column("Cấp bậc", "job_level", ["Job Level", "Seniority", "Level"]),
    Column("Học vấn", "education", ["Education", "Education Level", "Trình độ"]),
    Column("Kỹ năng", "skills", ["Skills", "Kỹ năng chính"]),
    Column("Mức lương mong muốn", "expected_salary", ["Expected Salary", "Lương mong muốn"]),
    Column("Thời gian báo trước", "notice_period", ["Notice Period"]),
    Column("Tỉnh/Thành phố", "city", ["City", "Thành phố", "Tỉnh thành"]),
    Column("Quận/Huyện", "district", ["District", "Quận huyện"]),
    Column("Địa chỉ hiện tại", "address", ["Current Address", "Address", "Địa chỉ"], sensitive=True),
    Column("Giới tính", "gender", ["Gender"], sensitive=True),
    Column("Năm sinh", "birth_year", ["Birth Year", "Year of Birth"], kind="int", sensitive=True),
    Column("LinkedIn", "linkedin", ["LinkedIn Profile URL", "LinkedIn URL"], kind="url"),
    Column("Portfolio/Website", "portfolio", ["Portfolio", "Website", "Portfolio URL"], kind="url"),
    Column("Trường/Đại học", "university", ["University", "Trường"]),
    Column("Chuyên ngành", "major", ["Major", "Ngành học"]),
    Column("GPA", "gpa", ["Điểm TB"]),
    Column("Năm tốt nghiệp", "graduation_year", ["Graduation Year"], kind="int"),
    Column("Chứng chỉ", "certifications", ["Certifications", "Chứng chỉ nghề"]),
    Column("Thành tích", "achievements", ["Achievements"]),
    Column("Ngoại ngữ", "language_proficiency", ["Language Proficiency", "Languages", "Trình độ ngoại ngữ"]),
    Column("Ngành nghề", "industry", ["Industry", "Lĩnh vực"]),
    Column("Tóm tắt kinh nghiệm", "experience_summary", ["Experience Summary", "Tóm tắt", "Kinh nghiệm"]),
    Column("Mục tiêu nghề nghiệp", "career_goals", ["Career Goals"]),
    Column("Nhãn", "labels", ["Tags", "Labels", "Nhãn phân loại"]),
    Column("Ngày ứng tuyển", "applied_at", ["Applied At", "Application Date", "Ngày nộp"], kind="date"),
    Column("Nguồn", "source", ["Acquisition Source", "Source", "Nguồn thu nhận"]),
    Column("Thông tin khác", "other_info", ["Other Information", "Ghi chú"]),
    Column("Tên file CV", "cv_file_name", ["CV File Name", "CV File", "Tên CV", "Tên file gốc"]),
    # --- ba khái niệm mới, đối chiếu với template ngoài 05/09 (xem docstring) ---
    Column("Ngày sinh", "birth_date", ["Date of Birth", "DOB", "Ngày tháng năm sinh"],
          kind="date", sensitive=True),
    Column("Khu vực ứng tuyển", "applied_region", ["Applied Region", "Region", "Khu vực"]),
    Column("Đánh giá chi tiết", "external_assessment",
          ["Detailed Assessment", "Assessment", "Nhận xét", "Đánh giá"]),
]

def normalize_header(name):
    """Chuẩn hoá một tiêu đề cột để tra cứu."""
    return " ".join(str(name or "").strip().lower().split())


# Tra cứu tiêu đề đã chuẩn hoá → Column.
_HEADER_INDEX = {}
for _col in COLUMNS:
    for _name in (_col.header, *_col.aliases):
        _HEADER_INDEX[normalize_header(_name)] = _col

# Khoá payload thuộc allowlist khi nhận structured output từ AI.
PAYLOAD_KEYS = tuple(c.key for c in COLUMNS if c.key != "cv_file_name")

# Định danh mạnh, theo thứ tự ưu tiên khi suy `entity_key` và khi dedupe.
IDENTITY_KEYS = ("email", "phone", "linkedin")


def column_for_header(name):
    """Column khớp với tiêu đề `name`, hoặc None nếu không nhận ra."""
    return _HEADER_INDEX.get(normalize_header(name))


def template_headers():
    return [c.header for c in COLUMNS]


_KEY_TO_HEADER = {c.key: c.header for c in COLUMNS}


def raw_from_fields(values):
    """{payload_key: value} → {tiêu_đề_chuẩn: value}.

    Dùng khi người dùng sửa ô trên lưới (gửi lên theo khoá payload) hoặc khi AI
    trả structured output — để chạy lại `normalize_row` trên cùng đường đi.
    """
    raw = {}
    for key, value in (values or {}).items():
        header = _KEY_TO_HEADER.get(key)
        if header is not None:
            raw[header] = value
    return raw


def normalize_row(raw):
    """`raw` (dict {tiêu đề gốc: giá trị ô}) → `(fields, errors)`.

    `fields`: dict {payload_key: giá trị chuỗi đã dọn}. Chỉ giữ khoá có giá trị.
    `errors`: dict {payload_key: câu lỗi} cho các ô sai định dạng.

    KHÔNG quyết định dòng hợp lệ hay không ở đây — chỉ chuẩn hoá và bắt lỗi
    định dạng từng ô. Việc xét thiếu định danh / trùng lặp thuộc về `dedupe.py`.
    """
    fields, errors = {}, {}

    for header, value in (raw or {}).items():
        col = column_for_header(header)
        if col is None:
            continue
        text = _clean_cell(value)
        if not text:
            continue

        if col.kind == "email":
            norm = normalize_email(text)
            if not norm:
                errors[col.key] = "Email sai định dạng."
                continue
            fields[col.key] = norm
        elif col.kind == "phone":
            norm = normalize_phone(text)
            if not norm:
                errors[col.key] = "Số điện thoại không hợp lệ (cần số di động VN)."
                # Giữ giá trị thô để người dùng thấy và sửa trên lưới.
                fields[col.key] = text
                continue
            fields[col.key] = norm
        elif col.kind == "url":
            fields[col.key] = text
        elif col.kind == "int":
            digits = re.sub(r"[^\d]", "", text.split(".")[0])
            fields[col.key] = digits or text
        elif col.kind == "date":
            fields[col.key] = _iso_date(text) or text
        else:
            fields[col.key] = text

    # Ngày ứng tuyển: chép sang `applied_ts` để `talent.derive._ordered_records`
    # xếp đúng thứ tự thời gian (Master Plan §7.3 — dùng mốc nguồn, không dùng
    # mốc Hub nhận).
    if fields.get("applied_at"):
        fields.setdefault("applied_ts", fields["applied_at"])

    return fields, errors


def _clean_cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split()).strip()


def _iso_date(text):
    """Cố đưa vài định dạng ngày phổ biến về `YYYY-MM-DD`. None nếu chịu."""
    text = text.strip()[:19]
    from datetime import datetime
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None
