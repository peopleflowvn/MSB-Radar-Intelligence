# -*- coding: utf-8 -*-
"""Rút tiêu chí bằng cách dò chữ — đường lui khi không gọi được LLM.

Dùng ở hai chỗ và cố ý dùng CHUNG: `talent/hiring_need.py` (hỏi bằng lời) và
`hiring/jd.py` (dán JD). Hai chỗ đó gọi cùng một mô hình cho cùng một việc, nên
lúc mô hình bận thì cũng phải lùi về cùng một chỗ — hai đường lui khác nhau
nghĩa là một trong hai sẽ mục dần mà không ai biết.

Kém xa LLM: không phân biệt "bắt buộc" với "ưu tiên", không dịch "làm về dữ
liệu" thành "Data". Nhưng khoá miễn phí giới hạn ~15 lượt/phút, và ngày demo
dính giới hạn thì một bộ tiêu chí thô mà người dùng sửa được vẫn hơn hẳn một
màn hình trắng.
"""
import re

# "tối thiểu 3 năm", "3+ năm", "ít nhất 3 năm kinh nghiệm", "3 years"
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:năm|year)", re.IGNORECASE)

MAX_SKILLS = 6

# Bao nhiêu hồ sơ được quét để dựng từ vựng. Đủ để phủ hết kỹ năng thường gặp
# mà không biến mỗi lượt lùi thành một lần quét toàn bảng.
VOCAB_LIMIT = 5000


def vocabulary():
    """Kỹ năng và nơi ở **đang thật sự có trong CSDL**.

    Không dùng danh sách viết cứng: nó vừa thiếu (công nghệ mới ra), vừa thừa
    (thứ không ai trong kho có). Lấy từ chính dữ liệu thì tiêu chí rút ra luôn
    là thứ tìm được người — đúng mục đích của bước này.
    """
    from talent.models import TalentProfile

    skills, locations = set(), set()
    for row in TalentProfile.objects.values_list("skills", "location")[:VOCAB_LIMIT]:
        for skill in row[0] or []:
            if isinstance(skill, str) and len(skill) >= 2:
                skills.add(skill.strip())
        if row[1]:
            locations.add(row[1].strip())
    return skills, locations


def criteria_from_text(text, title=""):
    """Dò tiêu chí từ một đoạn chữ bất kỳ (câu hỏi hoặc cả bản JD)."""
    text = str(text or "")
    lower = text.lower()
    criteria = {}

    skills, locations = vocabulary()
    found = sorted((s for s in skills if s.lower() in lower), key=len, reverse=True)
    if found:
        criteria["skills"] = found[:MAX_SKILLS]

    for location in sorted(locations, key=len, reverse=True):
        if location.lower() in lower:
            criteria["location"] = location
            break

    years = [int(m) for m in _YEARS.findall(text) if int(m) <= 40]
    if years:
        # Lấy số NHỎ NHẤT: một câu hỏi hay nhắc nhiều mốc ("3 năm kinh nghiệm",
        # "5 năm trong ngành"), mà đòi mốc cao nhất thì loại oan.
        criteria["min_years"] = min(years)

    if title:
        criteria["title"] = title
    return criteria


def title_for_criteria(headline):
    """Rút phần dùng để TÌM KIẾM từ một dòng tiêu đề JD.

    Tiêu đề JD Việt Nam rất hay có dạng ``Chuyên viên Phân tích Dữ liệu (Data
    Analyst)``. Cả cụm là cái TÊN đẹp cho vị trí, nhưng làm tiêu chí tìm kiếm
    thì tệ: CV phần lớn ghi chức danh bằng tiếng Anh, nên phần trong ngoặc mới
    là thứ khớp được.

    Chỉ nhận phần trong ngoặc khi nó trông như một chức danh — vài từ, không có
    dấu câu lạ. Ngoặc chứa ``(2 vị trí)`` hay ``(HN & HCM)`` thì bỏ qua.
    """
    text = str(headline or "").strip()
    match = re.search(r"\(([^)]{3,60})\)", text)
    if not match:
        return text

    inside = match.group(1).strip()
    words = inside.split()
    if not 1 <= len(words) <= 4:
        return text
    # Có chữ số hoặc ký hiệu là chú thích, không phải chức danh.
    if re.search(r"[\d&/,;]", inside):
        return text
    return inside


def first_line_title(text):
    """Dòng đầu của một bản JD gần như luôn là tên vị trí.

    Không có nó thì vị trí hiện ra là "(chưa đặt tên)" — tạo ba vị trí là không
    phân biệt được cái nào với cái nào trong danh sách.
    """
    for line in str(text or "").splitlines():
        line = line.strip(" \t-–—•*#")
        if 3 <= len(line) <= 120:
            return line
    return ""
