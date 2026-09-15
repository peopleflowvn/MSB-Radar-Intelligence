# -*- coding: utf-8 -*-
"""So khớp gần đúng cho alias `proposed` — KHÔNG quyết định canonical code.

Chỉ trả ứng viên + điểm tin cậy trong số các `CanonicalEntry`/alias `accepted`
ĐÃ CÓ. Không tự nghĩ ra giá trị mới, không gọi model — tất định, để kết quả
lặp lại được và audit được (Master Plan §6, xem intel/registry.py cho nguyên
tắc "AI không tự tạo canonical code mới").

Alias còn ở hàng chờ sau `intel.registry.resolve()` là alias có `alias_norm`
KHÔNG trùng tuyệt đối với alias nào đã có (trùng tuyệt đối đã tự nối ở đó rồi).
Việc còn lại ở đây là bắt lỗi chính tả / thiếu từ / thừa từ — dùng 3 tín hiệu
độc lập, không cần thư viện fuzzy-matching ngoài:

* `containment` — chuỗi ngắn nằm trọn trong chuỗi dài (vd "ke toan" trong
  "chuyen vien ke toan tong hop").
* `token_jaccard` — tỷ lệ từ chung/tổng, không quan tâm thứ tự.
* `sequence_ratio` — `difflib.SequenceMatcher`, bắt lỗi gõ nhầm ký tự.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class Candidate:
    """Một chuỗi đã biết trỏ tới một canonical entry, dùng để so khớp."""

    text: str
    entry_id: int
    entry_code: str
    origin: str  # "code" | "label" | "alias"


@dataclass(frozen=True)
class Match:
    candidate: Candidate
    score: float
    containment: bool


def _token_jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _containment(short: str, long: str) -> bool:
    if not short or short == long:
        return False
    return short in long and len(short) >= 3


def score_pair(query: str, candidate_text: str) -> tuple[float, bool]:
    """Điểm khớp [0..1] giữa hai chuỗi đã chuẩn hoá (đã qua `normalize_value`)."""
    if not query or not candidate_text:
        return 0.0, False
    if query == candidate_text:
        return 1.0, False

    query_tokens = frozenset(query.split())
    cand_tokens = frozenset(candidate_text.split())
    jaccard = _token_jaccard(query_tokens, cand_tokens)
    ratio = SequenceMatcher(None, query, candidate_text).ratio()

    shorter, longer = (query, candidate_text) if len(query) <= len(candidate_text) \
        else (candidate_text, query)
    contained = _containment(shorter, longer)
    # Containment tự nó là tín hiệu mạnh (một cụm là con của cụm kia) nhưng
    # không được thắng jaccard/ratio quá thấp — "ha noi" không nên "chứa
    # trong" một câu dài bất kỳ có chữ đó lẫn vào một cụm không liên quan.
    length_ratio = len(shorter) / len(longer) if longer else 0.0
    containment_score = 0.9 * length_ratio + 0.1 if contained else 0.0

    return max(jaccard, ratio, containment_score), contained


def best_match(query: str, candidates: Sequence[Candidate]) -> Optional[Match]:
    """Ứng viên khớp tốt nhất, hoặc `None` nếu không có ứng viên nào."""
    best: Optional[Match] = None
    for candidate in candidates:
        score, contained = score_pair(query, candidate.text)
        if best is None or score > best.score:
            best = Match(candidate=candidate, score=score, containment=contained)
    return best


def build_candidates(entries_and_aliases: Iterable[tuple]) -> list:
    """Tiện ích gộp: nhận (text, entry_id, entry_code, origin) → list[Candidate]."""
    return [Candidate(text=text, entry_id=entry_id, entry_code=entry_code, origin=origin)
            for text, entry_id, entry_code, origin in entries_and_aliases if text]
