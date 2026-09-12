# -*- coding: utf-8 -*-
"""Bóc JSON ra khỏi câu trả lời của model — dùng chung, không thuộc nghiệp vụ nào.

Tách khỏi `talent/hiring_need.py` vì ba nơi cần nó (`hiring/jd.py`,
`talent/answer/*`, và bộ bóc tiêu chí cũ trong thời gian chuyển đổi), và vì tầng
sinh phản hồi cũ sẽ bị gỡ bỏ.

Có `response_format=json_object` thì phần lớn model trả JSON trần, nhưng không
phải model nào cũng tôn trọng nó — đo thực tế: gemini/qwen vẫn bọc trong hàng rào
markdown, một số model chèn câu dẫn trước JSON. Bóc cả ba dạng.
"""
import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def extract_json(text, default=None):
    """Trả về dict/list đầu tiên đọc được trong `text`; `default` nếu không có."""
    raw = str(text or "").strip()
    if not raw:
        return {} if default is None else default

    fenced = _FENCE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()

    for candidate in _candidates(raw):
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            continue
    return {} if default is None else default


def _candidates(raw):
    """Các lát cắt đáng thử, từ nguyên văn tới khối {...} / [...] đầu tiên."""
    yield raw
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = raw.find(opener), raw.rfind(closer)
        if start != -1 and end > start:
            yield raw[start:end + 1]


def as_list(value, limit=None):
    """Chuẩn hoá một trường "đáng lẽ là mảng" — model hay trả chuỗi đơn."""
    if value in (None, "", {}):
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for item in items:
        text = " ".join(str(item or "").split())
        if text and text not in out:
            out.append(text)
    return out[:limit] if limit else out


def as_int(value, default=None, low=None, high=None):
    """Số nguyên khoan dung: nhận 5, "5", "5 người", "top 5"."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        number = int(value)
    else:
        match = re.search(r"-?\d+", str(value or ""))
        if not match:
            return default
        number = int(match.group(0))
    if low is not None and number < low:
        return default
    if high is not None and number > high:
        return high
    return number
