# -*- coding: utf-8 -*-
"""Ước tính field còn thiếu từ mốc thời gian khác đã biết — KHÔNG phải fact.

`intel/extraction.py` cấm tuyệt đối việc AI suy diễn khi bóc CV ("CHỈ điền field
khi CV nêu rõ... TUYỆT ĐỐI không suy diễn hay bịa") — mỗi field ở tầng
`ExtractedFact` phải có bằng chứng trích dẫn được. Module này đứng NGOÀI ranh
giới đó: nó không ghi field mới vào `ExtractedFact`/`TalentProfile`, chỉ tính
toán số học tất định để TRẢ LỜI khi người dùng hỏi ("khoảng bao nhiêu năm kinh
nghiệm", "đoán năm sinh giúp") mà CV không ghi trực tiếp field đó.

Ba suy luận, đều một chiều toán học từ MỘT mốc năm đã biết:

    kinh nghiệm  ước tính = năm hiện tại  - năm tốt nghiệp
    năm tốt nghiệp ước tính = năm sinh     + tuổi tốt nghiệp trung bình
    năm sinh     ước tính = năm tốt nghiệp - tuổi tốt nghiệp trung bình

Mọi kết quả PHẢI được người gọi (tool handler, câu trả lời) gắn nhãn "ước tính,
suy luận — không phải dữ liệu CV đã xác nhận". Đây là quyết định sản phẩm có
đánh đổi (độ phủ cao hơn, đổi lấy rủi ro lệch vài năm so với thực tế), khác hẳn
phần fact có bằng chứng.
"""
import re

from django.utils import timezone

#: Tuổi tốt nghiệp đại học trung bình ở VN — dùng để suy hai chiều năm sinh
#: <-> năm tốt nghiệp. Một hằng số thô: không tính cao đẳng/sau đại học riêng,
#: vì CV hiếm khi cho đủ dữ kiện để tinh chỉnh hơn mà không suy diễn thêm.
TYPICAL_GRADUATION_AGE = 22

#: Cùng trần 60 năm như `talent/derive.py::parse_years` — chặn giá trị vô lý
#: khi năm tốt nghiệp bị gõ nhầm hoặc bị hiểu nhầm là năm sinh.
MAX_EXPERIENCE_YEARS = 60

_YEAR = re.compile(r"(?:19|20)\d{2}")


def extract_year(value):
    """Chuỗi bất kỳ ("12/05/1995", "sinh năm 1995", "2015", 2015) -> năm 4 chữ
    số hợp lý, hoặc `None` nếu không đọc được hoặc năm phi lý (tương lai, quá
    xa quá khứ)."""
    if value is None or value == "":
        return None
    match = _YEAR.search(str(value))
    if not match:
        return None
    year = int(match.group(0))
    current_year = timezone.now().year
    return year if 1940 <= year <= current_year else None


def estimate_years_experience(graduation_year):
    """Số năm kinh nghiệm ƯỚC TÍNH = năm hiện tại - năm tốt nghiệp.

    Cận thô: giả định đi làm ngay sau tốt nghiệp, không trừ thời gian học
    lên/gián đoạn — nói rõ đây là ước tính khi dùng, không phải số đã xác nhận.
    """
    year = extract_year(graduation_year)
    if year is None:
        return None
    years = timezone.now().year - year
    return years if 0 <= years <= MAX_EXPERIENCE_YEARS else None


def estimate_graduation_year(birth_year):
    """Năm tốt nghiệp ƯỚC TÍNH = năm sinh + tuổi tốt nghiệp trung bình."""
    year = extract_year(birth_year)
    return year + TYPICAL_GRADUATION_AGE if year is not None else None


def estimate_birth_year(graduation_year):
    """Năm sinh ƯỚC TÍNH = năm tốt nghiệp - tuổi tốt nghiệp trung bình."""
    year = extract_year(graduation_year)
    return year - TYPICAL_GRADUATION_AGE if year is not None else None
