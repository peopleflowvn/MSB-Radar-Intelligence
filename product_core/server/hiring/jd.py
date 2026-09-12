# -*- coding: utf-8 -*-
"""Rút tiêu chí tìm kiếm từ JD dán vào (Master Plan mục 20).

Khác `talent/hiring_need.py` ở chỗ đầu vào là **cả một bản mô tả công việc** chứ
không phải một câu hỏi. JD dài, có phần thừa (phúc lợi, giới thiệu công ty), và
thường trộn "bắt buộc" với "ưu tiên".

Đầu ra vẫn là **đúng bộ tiêu chí mà `talent.search()` nhận** — không có định dạng
thứ ba. Nhờ vậy nhu cầu tuyển dụng, tìm bằng AI và bộ lọc thủ công dùng chung một
ngôn ngữ, và HM sửa được tiêu chí mà AI rút ra.
"""
import logging

from ai.router import complete
from talent import keywords
from talent.hiring_need import _extract_json, _validate

log = logging.getLogger(__name__)

TASK = "jd_parse"

# JD dài hơn mức này thì phần sau gần như luôn là phúc lợi và giới thiệu công ty.
MAX_JD_CHARS = 8000

SYSTEM_PROMPT = """Bạn đọc bản mô tả công việc (JD) tiếng Việt hoặc tiếng Anh và rút ra tiêu chí tìm ứng viên.

Chỉ trả về JSON, không giải thích. Các khoá được phép:
- title: chuỗi, chức danh cần tuyển
- skills: mảng chuỗi, kỹ năng/công nghệ BẮT BUỘC (không lấy phần "ưu tiên", "là một lợi thế")
- location: chuỗi, tỉnh/thành phố làm việc
- company: chuỗi, lĩnh vực kinh nghiệm yêu cầu (ví dụ "ngân hàng")
- min_years: số, số năm kinh nghiệm tối thiểu
- max_years: số, số năm kinh nghiệm tối đa

Quy tắc:
- BỎ QUA khoá không suy ra được. Đừng đoán.
- CHỈ lấy yêu cầu BẮT BUỘC vào "skills". Phần "ưu tiên/nice to have" bỏ qua —
  đưa vào sẽ khiến hệ thống loại mất những ứng viên vốn đạt yêu cầu bắt buộc.
- Bỏ qua hoàn toàn: phúc lợi, lương thưởng, giới thiệu công ty, quy trình ứng tuyển.
- Lấy tối đa 8 kỹ năng quan trọng nhất. JD thường liệt kê rất nhiều; đòi đủ hết
  thì không còn ai khớp.

"title" và "skills" viết bằng thuật ngữ như CV thường dùng (phần lớn là tiếng Anh):
"Data Analyst", "SQL", "Power BI". "location" và "company" giữ tiếng Việt.
Với "title" dùng phần LÕI ngắn gọn để khớp được nhiều biến thể."""


class ParsedJD:
    def __init__(self, criteria, title="", raw="", error="", fallback=False):
        self.criteria = criteria
        self.title = title
        self.raw = raw
        self.error = error
        #: True = tiêu chí do dò chữ, không phải LLM. Giao diện phải nói rõ để
        #: HM biết mà xem lại — im lặng ở đây là để họ tin nhầm vào AI.
        self.fallback = fallback


def _keyword_fallback(text, title, raw="", error=""):
    """Dò chữ thay cho LLM, và **đưa chức danh vào cả tiêu chí**.

    Chỗ này từng hụt một bước: dòng đầu JD được lấy làm TÊN vị trí, nhưng không
    được đưa vào `criteria`. Hậu quả là vị trí có tên đàng hoàng mà chiều "chức
    danh" không được chấm chút nào — danh sách đề xuất chỉ còn xét kỹ năng, số
    năm và nơi ở, và Data Engineer xếp ngang Data Analyst.

    Chức danh lấy được thường là tiếng Việt ("Chuyên viên Phân tích Dữ liệu")
    còn CV lại ghi tiếng Anh. Trước đây đưa vào cũng vô ích vì so khớp chuỗi cho
    0 điểm; giờ `talent/semantic.py` bắc được cầu đó nên đưa vào mới có nghĩa.
    """
    ten = title or keywords.first_line_title(text)
    # Tên vị trí và tiêu chí tìm kiếm không nhất thiết là một chuỗi: xem
    # `keywords.title_for_criteria`.
    criteria = keywords.criteria_from_text(text, keywords.title_for_criteria(ten))
    return ParsedJD(criteria, title=ten, raw=raw, error=error, fallback=True)


def parse_jd(jd_text, title=""):
    """JD -> tiêu chí. Không gọi được LLM thì dò chữ, không ném lỗi."""
    text = str(jd_text or "").strip()[:MAX_JD_CHARS]
    if not text:
        return ParsedJD({}, title=title)

    prompt = text
    if title:
        prompt = f"Vị trí: {title}\n\n{text}"

    try:
        result = complete(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            task=TASK, temperature=0, max_tokens=2000,
            response_format={"type": "json_object"})
    except Exception as exc:                   # noqa: BLE001 — xem docstring
        log.warning("Không gọi được LLM, dò chữ thay thế: %s", exc)
        return _keyword_fallback(text, title, error=str(exc)[:200])

    payload = _extract_json(result.text)
    criteria, _dropped = _validate(payload)
    if not criteria:
        # LLM trả về nhưng không rút được gì (JD quá ngắn, hoặc trả JSON rỗng).
        return _keyword_fallback(text, title, raw=result.text)
    return ParsedJD(criteria, title=criteria.get("title", "") or title,
                    raw=result.text)
