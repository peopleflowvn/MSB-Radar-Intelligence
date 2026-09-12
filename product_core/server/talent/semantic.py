# -*- coding: utf-8 -*-
"""Độ gần về nghĩa giữa các chức danh — chiều duy nhất mà LLM được góp vào điểm.

## Vì sao lại mở cửa cho LLM ở đúng chỗ này

Bộ chấm điểm cố ý tất định, và điều đó đúng cho sáu trong bảy chiều: số năm kinh
nghiệm, nơi ở, độ mới của hồ sơ — đều là dữ kiện đo được, không cần ai diễn giải.

Chức danh thì không. So khớp chuỗi cho ra những kết quả sai đến mức người dùng
nhìn là biết:

```text
"BI Developer"                    vs "Data Analyst"  →  0.00
"Chuyên viên Phân tích Tín dụng"  vs "Data Analyst"  →  0.00
"Data Engineer"                   vs "Data Analyst"  →  0.50
```

Người thứ nhất làm báo cáo và dashboard cả ngày. Recruiter thấy họ xếp bét bảng
là thôi không tin cả bảng điểm nữa — và một bảng điểm không ai tin thì phần
giải thích công phu phía trên cũng thành vô ích.

## Vì sao đây vẫn KHÔNG phải "LLM chấm điểm"

Ba ràng buộc, và cả ba đều là điều kiện để dùng được trong ngân hàng:

1. **LLM chỉ trả về một con số cho một CẶP CHỨC DANH**, không nhìn thấy con
   người nào. Nó không biết ứng viên tên gì, bao nhiêu tuổi, học ở đâu — nên
   không có đường nào để thiên lệch theo những thứ đó.
2. **Kết quả được lưu lại và tái dùng.** Cùng một tìm kiếm cho cùng một thứ tự,
   mãi mãi, cho tới khi có người sửa tay. Điểm nhảy múa giữa hai lần bấm là thứ
   giết niềm tin nhanh nhất — và làm việc hiệu chỉnh trọng số mất ý nghĩa.
3. **Điểm tổng vẫn là tổng có trọng số tất định** của bảy chiều. Chiều này chỉ
   thay chỗ cho phép so khớp chuỗi cũ, với đúng trọng số cũ.

Nói cách khác: LLM trả lời câu *"hai nghề này có gần nhau không"* — một câu về
**ngôn ngữ**, đúng thứ nó giỏi. Nó không trả lời câu *"nên gọi ai trước"* — câu
đó vẫn thuộc về code và về người tuyển dụng.

## Chi phí

Khoá theo cặp chức danh, không theo con người. Kho 20 nghìn hồ sơ chỉ có vài
trăm chức danh khác nhau, nên sau vài lượt tìm là gần như không còn lượt gọi
nào. Một lượt tìm kiếm giải quyết **tất cả** cặp còn thiếu trong đúng một lời
gọi.
"""
import json
import logging
import re

from ai.router import complete

from .hiring_need import _extract_json
from .models import TitleSimilarity

log = logging.getLogger(__name__)

TASK = "title_similarity"

#: Nhiều hơn mức này thì chia thành nhiều lượt gọi. Chức danh ngắn nên một lượt
#: chứa được nhiều, nhưng prompt quá dài làm mô hình bắt đầu trả lời cẩu thả.
BATCH_SIZE = 40

SYSTEM_PROMPT = """Bạn chấm độ gần về CÔNG VIỆC THỰC TẾ giữa một chức danh cần tuyển và danh sách chức danh của ứng viên.

Chỉ trả về JSON:
{"results": [{"title": "<nguyên văn chức danh ứng viên>", "score": <0..1>, "reason": "<một câu ngắn tiếng Việt>"}]}

Thang điểm:
- 1.0  cùng một công việc, chỉ khác cách gọi hoặc khác cấp bậc
       ("Senior Data Analyst" ↔ "Data Analyst", "Chuyên viên Phân tích Dữ liệu")
- 0.7–0.9  công việc hằng ngày trùng nhau phần lớn, chuyển sang làm được ngay
       ("BI Developer" ↔ "Data Analyst")
- 0.4–0.6  cùng lĩnh vực, kỹ năng nền giống nhau, nhưng đầu việc khác
       ("Data Engineer" ↔ "Data Analyst")
- 0.1–0.3  chỉ chung một ngành hoặc một vài kỹ năng rời rạc
- 0.0  không liên quan

Quy tắc:
- Chấm theo VIỆC PHẢI LÀM, không theo mức độ giống nhau của chuỗi ký tự.
- Cấp bậc (Junior/Senior/Lead) KHÔNG làm giảm điểm — số năm kinh nghiệm đã được
  chấm riêng ở chỗ khác, trừ hai lần là phạt oan.
- Chức danh tiếng Việt và tiếng Anh cùng nghĩa thì điểm cao.
- "reason" nói VIỆC, không nói chữ: "cùng làm báo cáo và dashboard", không phải
  "hai chức danh đều có chữ Data".
- Trả về ĐỦ mọi chức danh được đưa vào, giữ nguyên văn."""


def normalize(title):
    """Gộp các biến thể gõ khác nhau về một khoá tra cứu."""
    text = re.sub(r"\s+", " ", str(title or "")).strip().lower()
    return text[:200]


def lookup(needed, candidate):
    """Đọc từ bộ nhớ. Trả `TitleSimilarity` hoặc None."""
    a, b = normalize(needed), normalize(candidate)
    if not a or not b:
        return None
    return TitleSimilarity.objects.filter(needed=a, candidate=b).first()


def warm(needed, candidates):
    """Chấm trước mọi cặp còn thiếu, trong ĐÚNG MỘT lượt gọi cho mỗi lô.

    Gọi hàm này một lần trước khi chấm cả danh sách; sau đó `lookup()` chỉ đọc
    bộ nhớ. Không gọi được LLM thì lặng lẽ bỏ qua — `scoring` tự lùi về so khớp
    chuỗi như trước, và đánh dấu rõ là đã lùi.
    """
    a = normalize(needed)
    if not a:
        return {}

    wanted = {normalize(c): str(c).strip() for c in candidates if normalize(c)}
    if not wanted:
        return {}

    known = set(TitleSimilarity.objects
                .filter(needed=a, candidate__in=list(wanted))
                .values_list("candidate", flat=True))
    missing = {k: v for k, v in wanted.items() if k not in known}

    keys = list(missing)
    for start in range(0, len(keys), BATCH_SIZE):
        chunk = keys[start:start + BATCH_SIZE]
        _resolve_batch(a, needed, {k: missing[k] for k in chunk})

    rows = TitleSimilarity.objects.filter(needed=a, candidate__in=list(wanted))
    return {row.candidate: row for row in rows}


def _resolve_batch(needed_key, needed_raw, missing):
    """Một lượt gọi cho một lô cặp. Ghi kết quả vào bộ nhớ."""
    prompt = (f"Chức danh cần tuyển: {needed_raw}\n\n"
              "Chức danh của ứng viên:\n"
              + "\n".join(f"- {raw}" for raw in missing.values()))
    try:
        result = complete(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            task=TASK, temperature=0, max_tokens=2000,
            response_format={"type": "json_object"})
    except Exception as exc:                   # noqa: BLE001 — xem docstring
        log.warning("Không chấm được độ gần chức danh: %s", exc)
        return

    payload = _extract_json(result.text)
    rows = (payload or {}).get("results")
    if not isinstance(rows, list):
        log.warning("Kết quả độ gần chức danh không đúng khuôn: %r",
                    str(result.text)[:200])
        return

    for row in rows:
        if not isinstance(row, dict):
            continue
        key = normalize(row.get("title"))
        # Chỉ nhận chức danh CÓ TRONG lô đã hỏi. Mô hình đôi khi tự thêm dòng,
        # và nhận bừa nghĩa là để nó tự bịa ra ứng viên trong bộ nhớ.
        if key not in missing:
            continue
        score = _clamp(row.get("score"))
        if score is None:
            continue
        TitleSimilarity.objects.update_or_create(
            needed=needed_key, candidate=key,
            defaults={"score": score,
                      "reason": str(row.get("reason") or "")[:300],
                      "source": TitleSimilarity.SOURCE_LLM})


def _clamp(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1.0:
        # Mô hình thỉnh thoảng trả thang 0..100.
        number = number / 100.0 if number <= 100 else 1.0
    return round(max(0.0, min(1.0, number)), 3)


def to_json(rows):
    return json.dumps({k: {"score": v.score, "reason": v.reason}
                       for k, v in rows.items()}, ensure_ascii=False)
