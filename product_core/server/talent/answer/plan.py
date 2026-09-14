# -*- coding: utf-8 -*-
"""① Hiểu câu hỏi → `QueryPlan`.

Khác hẳn `talent/hiring_need.py` cũ ở ba điểm quyết định:

1. **`search_queries` do LLM tự viết** — nhiều cách nói, cả tiếng Việt lẫn tiếng
   Anh. Bộ cũ dịch một lần sang tiếng Anh rồi mất nguyên văn, nên "quan hệ khách
   hàng" → "Customer Relationship" → không CV nào chứa → 0 kết quả.
2. **`sort_by` + `limit` được giữ.** Bộ cũ không có ô nào chứa "5 người ít tuổi
   nhất" nên vế đó biến mất im lặng.
3. **`extract` mở.** Trình độ, trường, ngành học, năm sinh không cần cột trong
   CSDL — chặng ③ bóc thẳng từ text CV. Hỏi gì bóc nấy.

Không có schema tiêu chí cứng: `must_have`/`should_have` là câu chữ tự nhiên, do
chặng ③ (LLM đọc bằng chứng) phán đoán, không phải do SQL `LIKE` quyết định.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace

from ai.jsonx import as_int, as_list, extract_json
from ai.router import complete
from people.normalize import normalize_name

log = logging.getLogger(__name__)

TASK = "talent_answer_plan"

SHAPES = ("find_people", "analyze", "count", "compare", "followup", "general",
          "action")
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
MAX_QUERIES = 6

SYSTEM = """Bạn là bộ lập kế hoạch truy vấn cho Radar — trợ lý tra cứu Kho con người
của MSB (hồ sơ ứng viên + CV đã bóc tách text).

Nhiệm vụ: đọc câu hỏi (kèm ngữ cảnh hội thoại nếu có) và trả về MỘT kế hoạch tìm
kiếm dạng JSON. Bạn KHÔNG trả lời câu hỏi, KHÔNG bịa dữ liệu.

Chỉ trả JSON với các khoá:

- "shape": một trong "find_people" (tìm/liệt kê người), "analyze" (tổng hợp,
  nhận xét về kho), "count" (đếm/thống kê), "compare" (so sánh), "followup"
  (hỏi tiếp về kết quả vừa rồi), "action" (người dùng bảo LÀM một việc trên
  người đã nhắc tới: soạn thư tiếp cận, ghi nhớ điều gì đó, truy nguồn gốc một
  dữ kiện), "general" (không liên quan dữ liệu người).
  Phân biệt "action" với phần còn lại: "action" là câu MỆNH LỆNH làm việc gì
  ("soạn thư cho 3 người đầu", "nhớ giúp tôi là chỉ tuyển ở Hà Nội", "dữ kiện
  này lấy từ đâu ra"), không phải câu hỏi tra cứu.

  CẢNH BÁO về "general" — đây là chỗ hay bị chọn nhầm nhất:
  "general" CHỈ dành cho câu KHÔNG dính gì tới kho hồ sơ — chào hỏi, hỏi Radar
  là gì, kiến thức chung, tin tức, thời tiết, lãi suất.
  Câu hỏi có nhắc tới CV / hồ sơ / ứng viên / kho / dữ liệu thì KHÔNG BAO GIỜ là
  "general", kể cả khi nó hỏi theo lối "bạn có…". Những câu sau đều nói về kho:
    "thế bạn có cv những ngành nào"        → analyze
    "bạn đánh giá tổng quan về kho ứng viên" → analyze
    "kho mình có dữ liệu gì"                → analyze
    "bạn có bao nhiêu hồ sơ"                → count
  Chọn nhầm những câu này thành "general" khiến Radar trả lời "tôi không có dữ
  liệu" trong khi kho có hàng trăm hồ sơ — sai nghiêm trọng nhất có thể mắc.
- "information_need": viết lại câu hỏi thành MỘT câu độc lập, đã ghép ngữ cảnh
  hội thoại, đủ nghĩa khi đọc riêng.
- "must_have": mảng câu chữ — điều kiện BẮT BUỘC, không thoả thì loại. Rất ít.
  Chỉ đưa vào khi người hỏi nói rõ là bắt buộc hoặc là bản chất câu hỏi
  (ví dụ "của NEU" → "tốt nghiệp Đại học Kinh tế Quốc dân (NEU)").
- "should_have": mảng câu chữ — tiêu chí mong muốn, dùng để xếp hạng, thiếu vẫn
  có thể lọt vào danh sách.
  Riêng câu ĐẾM: mọi điều kiện xác định nhóm cần đếm, kể cả phủ định, đều là
  must_have; chỉ tiêu chí người dùng nói rõ là ưu tiên mới là should_have.
  Tách từng điều kiện: "bao nhiêu người biết SQL và không biết Python" →
  shape="count", must_have=["biết SQL", "không biết Python"]. Không suy phủ
  định từ việc CV không nhắc kỹ năng. Câu đếm trong nhóm lượt trước vẫn là
  count; tên của nhóm là phạm vi, không phải điều kiện must_have.
- "extract": mảng tên thuộc tính cần BÓC RA TỪ CV để trả lời được câu hỏi
  (ví dụ "năm sinh", "trường tốt nghiệp", "trình độ", "số năm kinh nghiệm").
  Chỉ liệt kê thứ câu hỏi thực sự cần; rỗng nếu không cần.
- "sort_by": {"key": "<tên thuộc tính trong extract>", "dir": "asc"|"desc"}
  hoặc null. "ít tuổi nhất" = sinh sau = năm sinh "desc".
  "lớn tuổi nhất" = sinh sớm = năm sinh "asc". "nhiều kinh nghiệm
  nhất" = số năm kinh nghiệm "desc".
- "limit": số hồ sơ người hỏi muốn. Không nói rõ thì 10.
- "search_queries": 3–6 truy vấn ngữ nghĩa để tìm trong kho CV. ĐÂY LÀ PHẦN
  QUAN TRỌNG NHẤT.
- "next_steps": mảng các việc CÒN LẠI, khi một câu chứa NHIỀU VIỆC nối nhau.
  Mỗi phần tử: {"shape": "...", "yeu_cau": "câu mô tả việc của bước đó"}.
  Các khoá ở trên mô tả việc THỨ NHẤT; "next_steps" mô tả việc thứ hai trở đi.
  Tối đa 2 bước tiếp theo. Câu chỉ có một việc thì để mảng rỗng.
  Ví dụ "tìm ứng viên Java rồi soạn thư cho người đầu":
    shape = "find_people", search_queries = [...Java...],
    next_steps = [{"shape": "action", "yeu_cau": "soạn thư tiếp cận cho người đầu tiên"}]
  Ví dụ "tìm 5 người quan hệ khách hàng, so sánh 2 người đầu":
    shape = "find_people", limit = 5,
    next_steps = [{"shape": "action", "yeu_cau": "so sánh hai người đầu danh sách"}]
  KHÔNG tách một việc thành nhiều bước. "Tìm ứng viên Java biết Spring" là MỘT
  việc với hai điều kiện, không phải hai bước.

Quy tắc cho "search_queries":
- Viết ĐỦ MỌI CÁCH NÓI của cùng một khái niệm: nguyên văn tiếng Việt người hỏi
  dùng, cách viết nghiệp vụ khác, viết tắt, và bản tiếng Anh.
- CV ứng viên Việt Nam trộn cả tiếng Việt lẫn tiếng Anh — phải phủ cả hai.
- Ví dụ "quan hệ khách hàng" → ["quan hệ khách hàng cá nhân",
  "chuyên viên khách hàng ưu tiên priority banking", "customer relationship
  manager RM", "chăm sóc tư vấn khách hàng ngân hàng"].
- Ví dụ "học cao đẳng" → ["tốt nghiệp cao đẳng", "trình độ cao đẳng college",
  "bằng cao đẳng chính quy"].
- KHÔNG viết cả câu hỏi thành một truy vấn. Tách theo khái niệm.
- KHÔNG thêm điều kiện người hỏi không nêu.

Nếu ngữ cảnh có mục "NGƯỜI DÙNG ĐÃ DẶN": đó là điều họ đã chủ động bảo bạn nhớ.
Áp dụng vào kế hoạch khi có liên quan (thường thành "should_have"). Chỉ đưa lên
"must_have" nếu lời dặn nói rõ là bắt buộc. Câu hỏi lần này mâu thuẫn với lời
dặn thì CÂU HỎI THẮNG — người ta có quyền đổi ý.

Nếu câu hỏi không liên quan tới dữ liệu con người (chào hỏi, hỏi về Radar, kiến
thức chung) thì shape="general" và search_queries=[]."""


@dataclass
class QueryPlan:
    shape: str = "find_people"
    information_need: str = ""
    must_have: list = field(default_factory=list)
    should_have: list = field(default_factory=list)
    extract: list = field(default_factory=list)
    sort_by: dict | None = None
    limit: int = DEFAULT_LIMIT
    search_queries: list = field(default_factory=list)
    #: Các việc CÒN LẠI sau bước này, khi một câu chứa nhiều việc.
    #:
    #: "Tìm ứng viên Java rồi soạn thư cho người đầu" là MỘT câu, HAI việc. Một
    #: `shape` không diễn tả được điều đó: nếu chọn `find_people` thì thư không
    #: bao giờ được soạn, nếu chọn `action` thì không có ai để soạn cho.
    #:
    #: Mỗi phần tử: {"shape": "...", "yeu_cau": "câu mô tả việc của bước đó"}.
    #: Bước sau nhận danh sách người của bước trước qua `last_result` — đúng cơ
    #: chế câu hỏi tiếp vẫn dùng, không phải đường dây riêng.
    next_steps: list = field(default_factory=list)
    provider: str = ""
    model: str = ""
    fallback: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def needs_people(self) -> bool:
        """Có phải đi truy hồi kho người không (①→⑤)?

        `action` KHÔNG: người dùng bảo làm việc gì đó trên người đã nhắc ở lượt
        trước, nên đối tượng đã có sẵn trong ngữ cảnh — đi tìm lại từ đầu vừa
        tốn tiền vừa dễ ra một danh sách khác với danh sách họ đang nói tới.
        """
        return self.shape not in ("general", "action") and bool(self.search_queries)

    @property
    def wants_action(self) -> bool:
        return self.shape == "action"

    def as_dict(self):
        return {"shape": self.shape, "information_need": self.information_need,
                "must_have": self.must_have, "should_have": self.should_have,
                "extract": self.extract, "sort_by": self.sort_by,
                "limit": self.limit, "search_queries": self.search_queries,
                "next_steps": self.next_steps,
                "provider": self.provider, "model": self.model,
                "fallback": self.fallback}


#: Từ khoá cho thấy câu hỏi nói về KHO của Radar, không phải kiến thức chung.
#: Cả bản có dấu lẫn không dấu — người dùng thật gõ cả hai kiểu.
_STORE_WORDS = ("cv", "hồ sơ", "ho so", "ứng viên", "ung vien", "kho ",
                "trong kho", "dữ liệu", "du lieu", "hồ sơ nào", "ho so nao")


def mentions_store(question):
    """Câu hỏi có nhắc tới kho hồ sơ không (dù hỏi theo lối "bạn có…")."""
    low = " ".join(str(question or "").casefold().split())
    return any(word in low for word in _STORE_WORDS)


def _context_block(envelope):
    """Vài lượt gần nhất + kết quả lượt trước + điều người dùng đã dặn.

    `memories` là những điều người dùng chủ động bảo Radar nhớ ("tôi chỉ tuyển ở
    Hà Nội"). Không đưa vào đây thì panel "Radar nhớ" chỉ là một cuốn sổ không
    ai đọc: người dùng dạy một điều, Radar ghi lại, rồi trả lời như chưa từng
    biết. Chúng đã được `projection` lọc prompt-injection trước khi tới đây.
    """
    projection = getattr(envelope, "projection", None)
    if projection is None:
        return ""
    parts = []

    memories = list(getattr(projection, "memories", []) or [])[:8]
    if memories:
        parts.append("NGƯỜI DÙNG ĐÃ DẶN:\n"
                     + "\n".join(f"- {m}" for m in memories))

    summary = str(getattr(projection, "summary", "") or "").strip()
    if summary:
        parts.append("TÓM TẮT PHẦN HỘI THOẠI CŨ:\n" + summary[:1800])

    criteria = getattr(projection, "active_criteria", None) or {}
    if criteria:
        parts.append("TIÊU CHÍ ĐANG CÓ HIỆU LỰC:\n" + str(criteria)[:1200])

    turns = list(getattr(projection, "recent_turns", []) or [])[-12:]
    for turn in turns:
        question = str(turn.get("question") or "").strip()[:500]
        answer = str(turn.get("answer") or "").strip()[:700]
        if question:
            parts.append(f"H: {question}")
        if answer:
            parts.append(f"Đ: {answer}")
    last = projection.last_result_lines() if hasattr(projection, "last_result_lines") else ""
    if last:
        parts.append(last[:600])
    return "\n\n".join(parts)


def plan(question, *, envelope=None, complete_fn=None) -> QueryPlan:
    """Câu hỏi → `QueryPlan`. LLM lỗi thì lùi về kế hoạch tối thiểu, không ném lỗi."""
    question = " ".join(str(question or "").split())
    if not question:
        return QueryPlan(shape="general", fallback=True)

    context = _context_block(envelope)
    user = (f"NGỮ CẢNH HỘI THOẠI:\n{context}\n\n" if context else "") + f"CÂU HỎI: {question}"

    caller = complete_fn or complete
    try:
        result = caller(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            task=TASK, temperature=0, max_tokens=900, reasoning_effort="none",
            budget_seconds=25, response_format={"type": "json_object"})
    except Exception as exc:                       # noqa: BLE001
        log.warning("answer.plan: LLM lỗi, dùng kế hoạch tối thiểu: %s", exc)
        return _fallback(question)

    payload = extract_json(result.text)
    if not isinstance(payload, dict) or not payload:
        return _fallback(question, provider=getattr(result, "provider", ""),
                         model=getattr(result, "model", ""))

    queries = as_list(payload.get("search_queries"), limit=MAX_QUERIES)
    shape = str(payload.get("shape") or "").strip().lower()
    if shape not in SHAPES:
        shape = "general" if not queries else "find_people"
    # Chốt chặn: câu có nhắc CV/hồ sơ/ứng viên/kho mà bị xếp "general" thì Radar
    # sẽ đi nhánh hội thoại và trả lời "tôi không có dữ liệu" — trong khi kho có
    # hàng trăm hồ sơ. Đã xảy ra thật trên production ("thế bạn có cv những ngành
    # nào"). Prompt đã dặn kỹ, nhưng đây là lỗi tệ nhất có thể mắc nên không để
    # nó phụ thuộc một mình vào việc model có nghe lời hay không.
    if shape == "general" and mentions_store(question):
        log.info("answer.plan: ép 'general' → 'analyze' vì câu hỏi nhắc tới kho: %r",
                 question[:80])
        shape = "analyze"
    # "Lấy/mở hồ sơ X và phân tích" là yêu cầu ĐỌC hồ sơ, không phải action
    # qua tool. Model đôi khi xếp nó thành action khiến nhánh tool đã biết tên
    # ở preamble nhưng cuối cùng lại hỏi "làm gì với ai".
    normalized = normalize_name(question)
    # Đếm theo tên là phép thống kê xác định trên chỉ mục toàn kho. Không để
    # model phân loại nhầm thành tìm kiếm hồ sơ rồi chỉ đọc top-N.
    if re.fullmatch(
            r"(?:(?:trong kho )?(?:co )?bao nhieu|dem|tim tat ca) "
            r"(?:ung vien|ho so|nguoi|cv) (?:co )?ten .+", normalized):
        shape = "count"
    asks_profile_analysis = (
        any(mark in normalized for mark in ("ho so", "cv"))
        and any(mark in normalized for mark in (
            "phan tich", "danh gia", "xem chi tiet", "doc chi tiet", "lay ho so", "mo ho so"))
    )
    if shape == "action" and asks_profile_analysis:
        shape = "analyze"
        if not queries:
            queries = [question]
    # Không có truy vấn nào mà lại đòi tìm người ⇒ ít nhất dùng chính câu hỏi.
    if shape != "general" and not queries:
        queries = [question]

    sort_by = _sort_by(payload.get("sort_by"))
    # Scalar count has no person ordering. Preserve the richer ranking
    # contract when a model emits the contradictory count + sort combination.
    if shape == "count" and sort_by:
        shape = "find_people"

    return QueryPlan(
        shape=shape,
        information_need=" ".join(str(payload.get("information_need") or question).split())[:500],
        must_have=as_list(payload.get("must_have"), limit=6),
        should_have=as_list(payload.get("should_have"), limit=10),
        extract=as_list(payload.get("extract"), limit=8),
        sort_by=sort_by,
        limit=as_int(payload.get("limit"), default=DEFAULT_LIMIT, low=1, high=MAX_LIMIT),
        search_queries=queries,
        next_steps=_next_steps(payload.get("next_steps")),
        provider=getattr(result, "provider", ""), model=getattr(result, "model", ""),
        raw=payload)


#: Trần số bước tiếp theo. Mỗi bước là một lượt gọi model nữa, nên chuỗi dài
#: vừa chậm vừa khó nói cho người dùng biết Radar đang làm gì.
MAX_NEXT_STEPS = 2


def _next_steps(value):
    """Chuẩn hoá `next_steps` do ① sinh ra. Sai khuôn thì bỏ, không đoán."""
    out = []
    for item in (value if isinstance(value, list) else [])[:MAX_NEXT_STEPS]:
        if not isinstance(item, dict):
            continue
        shape = str(item.get("shape") or "").strip().lower()
        need = " ".join(str(item.get("yeu_cau") or "").split())[:300]
        if shape not in SHAPES or not need:
            continue
        out.append({"shape": shape, "yeu_cau": need})
    return out


def _sort_by(value):
    if not isinstance(value, dict):
        return None
    key = " ".join(str(value.get("key") or "").split())
    if not key:
        return None
    direction = str(value.get("dir") or "desc").strip().lower()
    return {"key": key, "dir": "asc" if direction == "asc" else "desc"}


def _fallback(question, provider="", model=""):
    """Không hiểu được thì vẫn phải tìm — dùng chính câu hỏi làm truy vấn."""
    return QueryPlan(shape="find_people", information_need=question,
                     search_queries=[question], provider=provider, model=model,
                     fallback=True)


def widen(previous: QueryPlan) -> QueryPlan:
    """Expand retrieval vocabulary without changing the user's constraints.

    A wider candidate pool still has to satisfy the original requirements,
    including exclusions. Keep follow-on actions and all planning metadata.
    """
    queries = list(previous.search_queries)
    if previous.information_need and previous.information_need not in queries:
        queries.append(previous.information_need)
    for item in previous.must_have:
        if item not in queries:
            queries.append(item)
    return replace(previous, search_queries=queries[:MAX_QUERIES + 2])
