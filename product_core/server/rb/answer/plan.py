# -*- coding: utf-8 -*-
"""① Hiểu câu hỏi của RM → `ProspectPlan`.

Khác `rb/prospects.py::parse` ở đúng chỗ quan trọng nhất: **không còn tám khoá
cố định**. Bộ cũ cho phép LLM điền `location`, `seniority`, `products`,
`segment`, `require_contact`, `exclude_open_opportunity`, `limit`,
`signal_recency_days` — và mọi thứ ngoài tám ô đó rơi mất trong im lặng. Đo được
trên câu thật:

    "khách nào có dấu hiệu chuẩn bị mua nhà"
        → không ô nào chứa "dấu hiệu chuẩn bị mua nhà"
        → RM nhận về danh sách lọc theo… không gì cả

Ở đây `must_have`/`should_have` là **câu chữ tự nhiên**, do ③ đọc bằng chứng mà
phán đoán. Những gì khớp được cột CSDL thì `structured.py` vẫn dùng làm bộ lọc
cứng — nhưng đó là để tăng recall, không phải để định nghĩa câu hỏi.

## Hai shape không có bên Talent

`portfolio`  câu về chính danh mục của RM đang hỏi: "khách của tôi ai sắp rời
             bỏ", "tháng này tôi nên ưu tiên ai". Phạm vi là
             `rb_profile.sales_owner = người hỏi`, và đây là lần đầu trong hệ
             thống mà **danh tính người hỏi đổi tập kết quả** — bên Talent thì
             không, ai vào được đều thấy cùng một kho.

`whitespace` khách chưa ai chăm: không `sales_owner`, không cơ hội đang mở.
             Đây là câu hỏi sinh ra tiền mà bộ lọc tay không hỏi được, vì nó
             định nghĩa bằng cái KHÔNG có.

## Vì sao `sort_by` mặc định KHÔNG phải độ liên quan

Talent hỏi "ai thoả tiêu chí"; Growth hỏi "ai đáng gọi". Không ai mở Growth
Radar để đọc một danh sách xếp theo độ khớp chữ. Nên khi RM không nói rõ thứ tự,
④ xếp theo `priority_score` — xem `aggregate.py`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace

from ai.jsonx import as_int, as_list, extract_json
from ai.router import complete

log = logging.getLogger(__name__)

TASK = "rb_prospect_search"

SHAPES = ("find_prospects", "portfolio", "whitespace", "analyze", "count",
          "compare", "followup", "action", "general")
#: Shape cần đi qua ②③④ — tức cần truy hồi người thật.
NEEDS_PEOPLE = ("find_prospects", "portfolio", "whitespace", "analyze", "count",
                "compare", "followup")
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_QUERIES = 6

#: Trên mức này thì tin phán đoán shape của ① và bỏ chốt chặn từ khoá.
TRUST_SHAPE_ABOVE = 0.85
#: Dưới mức này, có câu hỏi làm rõ thì HỎI LẠI thay vì đoán rồi chạy ①→⑤.
CLARIFY_BELOW = 0.4

SYSTEM = """Bạn là bộ lập kế hoạch truy vấn cho Growth Radar — trợ lý của chuyên viên
quan hệ khách hàng (RM) ngân hàng MSB, làm việc trên kho khách hàng cá nhân
(hồ sơ bán lẻ + tín hiệu quan sát được + lịch sử tiếp cận).

Nhiệm vụ: đọc câu hỏi (kèm ngữ cảnh hội thoại nếu có) và trả về MỘT kế hoạch tìm
kiếm dạng JSON. Bạn KHÔNG trả lời câu hỏi, KHÔNG bịa khách hàng, KHÔNG bịa tín hiệu.

Chỉ trả JSON, các khoá viết THEO ĐÚNG THỨ TỰ dưới đây:

- "suy_luan": 2–4 câu NGẮN, và phải là khoá ĐẦU TIÊN bạn viết ra. Đây là chỗ bạn
  NGHĨ để chọn nhánh, không phải chỗ giải thích sau khi đã chọn. Lần lượt:
  (a) RM thực sự đang muốn gì? Nói lại bằng lời của bạn.
  (b) Câu này hỏi về khách hàng NÀO: toàn kho, danh mục của riêng RM này, hay
      nhóm chưa ai phụ trách?
  (c) Họ muốn TRA CỨU, hay đang BẢO LÀM một việc trên nhóm đã nhắc ở lượt trước?
  (d) Nếu chỉ là chào hỏi / kiến thức chung ngoài kho → "general".
  Viết "shape" TRƯỚC rồi bịa "suy_luan" cho khớp là hỏng đúng cơ chế này.

- "shape": một trong
  "find_prospects" — tìm/liệt kê khách hàng tiềm năng trong TOÀN kho.
  "portfolio"      — câu về danh mục của CHÍNH RM đang hỏi. Dấu hiệu: "khách
                     của tôi", "tôi đang phụ trách", "danh mục của tôi", "tôi
                     nên gọi ai". Chọn đúng shape này rất quan trọng: nó đổi
                     phạm vi dữ liệu, không chỉ đổi cách trình bày.
  "whitespace"     — khách CHƯA ai phụ trách hoặc chưa ai tiếp cận. Dấu hiệu:
                     "chưa ai chăm", "còn bỏ trống", "chưa được phân công",
                     "chưa ai gọi".
  "analyze"        — tổng hợp, nhận xét về kho khách hàng.
  "count"          — đếm/thống kê.
  "compare"        — so sánh vài khách hàng cụ thể.
  "followup"       — hỏi tiếp về kết quả vừa rồi.
  "action"         — MỆNH LỆNH làm một việc trên người đã nhắc tới: soạn thư
                     tiếp cận, tạo cơ hội, ghi nhớ một điều kiện. Không phải câu
                     tra cứu.
                     CŨNG LÀ "action": nhờ gợi ý sản phẩm từ một câu mô tả nhu
                     cầu khách vừa nói ("khách bảo đang tính mua ô tô trả góp
                     thì gợi ý sản phẩm gì", "nên chào sản phẩm gì") — dù không
                     nhắc tới người cụ thể nào, đây vẫn là MỘT VIỆC cần làm
                     ngay bằng công cụ, không phải tìm kiếm trong kho.
  "general"        — không liên quan dữ liệu khách hàng.

  CẢNH BÁO về "general" — chỗ hay chọn nhầm nhất:
  "general" CHỈ dành cho câu KHÔNG dính gì tới kho khách hàng. Câu có nhắc tới
  khách hàng / kho / dữ liệu / tín hiệu thì KHÔNG BAO GIỜ là "general", kể cả
  khi hỏi theo lối "bạn có…":
    "kho mình có bao nhiêu khách"            → count
    "bạn có dữ liệu khách hàng ngành nào"    → analyze
    "thế bạn thấy khách của tôi thế nào"     → portfolio

  NGƯỢC LẠI — câu về CHÍNH NGÂN HÀNG MSB (lãi suất, sản phẩm, chi nhánh, lãnh
  đạo, tin tức) là kiến thức thế giới thực, KHÔNG phải phép tổng hợp trên kho
  khách hàng, dù câu có chữ "MSB":
    "lãi suất vay mua nhà của msb"      → general
    "msb có bao nhiêu chi nhánh"        → general
  Phân biệt bằng: đang hỏi về NGƯỜI trong kho, hay về ngân hàng như một tổ chức?

- "do_tin_cay": 0.0–1.0 — bạn CHẮC tới đâu về "shape" vừa chọn. Chấm thật thà:
    ≥ 0.8  câu hỏi rõ ràng, chỉ một cách hiểu.
    0.4–0.8 hiểu được nhưng còn mập mờ, vẫn đoán được ý chính.
    < 0.4  thật sự không biết — hai cách hiểu trở lên, khác hẳn nhau.

- "cau_hoi_lam_ro": CHỈ điền khi "do_tin_cay" < 0.4 — MỘT câu ngắn hỏi lại RM,
  xưng "anh/chị". Không mập mờ thì để "".
  Ví dụ: "Anh/chị muốn tìm khách đang có nhu cầu vay, hay khách đã từng vay ạ?"
  ĐỪNG hỏi lại chỉ vì câu hỏi khó — hỏi lại khi nó ĐA NGHĨA.

  CẢNH BÁO về CÂU XÁC NHẬN / ĐỒNG Ý NGẮN ("có", "vâng", "ừ", "ok", "đồng ý", "làm đi", "tiếp tục", "lọc đi"...):
  - Khi lượt trước Radar vừa hỏi hoặc đề xuất một hướng tiếp theo:
    + Câu trả lời "có", "vâng", "ok", "đồng ý", "làm đi", "tiếp tục", "lọc đi" là sự XÁC NHẬN ĐỒNG Ý thực hiện đề xuất đó.
    + Đây là câu có mục tiêu rõ ràng từ ngữ cảnh, TUYỆT ĐỐI KHÔNG coi là mơ hồ hay không hiểu được (do_tin_cay >= 0.85, TUYỆT ĐỐI KHÔNG sinh "cau_hoi_lam_ro").
    + "information_need": viết lại thành câu thực thi đầy đủ đề xuất đó.
    + "shape": chọn "followup", "find_prospects" hoặc "action" phù hợp.

- "information_need": viết lại câu hỏi thành MỘT câu độc lập, đã ghép ngữ cảnh
  hội thoại, đủ nghĩa khi đọc riêng.

- "must_have": mảng câu chữ — điều kiện BẮT BUỘC, không thoả thì loại. Rất ít.
  LƯU Ý QUAN TRỌNG: Dữ liệu thực tế gồm CV xin việc (kinh nghiệm, vị trí, công ty...)
  kèm bài đăng và tín hiệu. Ứng viên KHÔNG BAO GIỜ ghi trong CV là "tôi muốn vay mua nhà".
  Do đó, TUYỆT ĐỐI KHÔNG đưa điều kiện "phải nói rõ cần vay" vào must_have vì sẽ loại
  sạch mọi khách tiềm năng. Chỉ dùng must_have cho ràng buộc cứng như địa bàn nếu RM yêu cầu.
  Riêng câu ĐẾM: mọi điều kiện xác định nhóm cần đếm, kể cả phủ định, đều là must_have.

- "should_have": mảng câu chữ — tiêu chí mong muốn, dùng để xếp hạng và định hướng
  tìm kiếm (ví dụ "cấp quản lý hoặc chuyên môn cao", "thâm niên trên 5 năm", "đã kết hôn",
  "làm việc tại công ty uy tín").

- "extract": mảng tên thuộc tính cần BÓC RA TỪ BẰNG CHỨNG để trả lời được câu
  hỏi (ví dụ "sản phẩm đang quan tâm", "thời điểm phát sinh nhu cầu", "nghề
  nghiệp", "chức danh", "kết quả tiếp cận gần nhất").

- "search_queries": 3–6 cách diễn đạt và TỪ KHOÁ TƯ DUY KINH DOANH để tìm trong bằng chứng.
  BẢN CHẤT DỮ LIỆU: Kho dữ liệu là hồ sơ nghề nghiệp / CV ứng viên kèm bài đăng và tín hiệu.
  TƯ DUY KINH DOANH: Hãy dịch nhu cầu sản phẩm tài chính sang CHÂN DUNG NGHỀ NGHIỆP & TỪ KHOÁ CV:
  * Vay mua nhà (mortgage): tìm quản lý, trưởng phòng, manager, kỹ sư, senior, thâm niên >5 năm, đã kết hôn...
    ["trưởng phòng", "manager", "kỹ sư", "senior", "vay mua nhà", "mua chung cư"]
  * Thẻ tín dụng VIP / chi tiêu (credit_card): tìm quản lý, giám đốc, tech lead, sales, marketing...
    ["quản lý", "giám đốc", "tech lead", "thẻ tín dụng", "credit card"]
  * Vay kinh doanh / Vốn SME (business): tìm chủ doanh nghiệp, founder, ceo, giám đốc, kế toán trưởng...
    ["founder", "giám đốc", "ceo", "chủ doanh nghiệp", "vốn kinh doanh", "kế toán trưởng"]
  * Gửi tiết kiệm / Đầu tư / Khách ưu tiên (savings, investment): tìm giám đốc, bác sĩ, luật sư, chuyên gia >10 năm...
    ["giám đốc", "bác sĩ", "chuyên gia", "tiết kiệm", "đầu tư", "quản lý tài sản"]
  * Tài khoản chi lương (payroll): tìm nhân sự, hr manager, kế toán trưởng, giám đốc...
    ["hr manager", "trưởng phòng nhân sự", "kế toán trưởng", "chi lương", "payroll"]
  * Ngoại tệ (fx): tìm xuất nhập khẩu, logistics quốc tế, công ty đa quốc gia, remote...
    ["xuất nhập khẩu", "logistics", "ngoại tệ", "chuyển tiền quốc tế"]

- "san_pham": mảng mã sản phẩm, CHỈ chọn trong credit_card, mortgage, auto_loan,
  consumer_loan, savings, investment, insurance, fx, payroll. Chọn sản phẩm mà câu hỏi
  hướng tới hoặc sản phẩm phù hợp nhất với chân dung khách RM đang tìm.

- "bo_loc": object các bộ lọc khớp thẳng cột dữ liệu. Chỉ điền khoá nào suy ra
  CHẮC CHẮN được, bỏ qua phần còn lại:
    "tinh_thanh": tên tỉnh/thành
    "phan_khuc": "mass" | "affluent" | "priority"
    "cap_bac": "manager" | "executive"
    "phai_co_lien_he": true nếu RM yêu cầu phải gọi được ngay
    "loai_co_hoi_dang_mo": true nếu muốn bỏ người đã có cơ hội đang mở
    "tin_hieu_trong_ngay": số ngày, khi RM nói "gần đây"/"tuần này"…
                           "gần đây" không kèm số → 90

- "sap_xep": {"key": "...", "dir": "desc"|"asc"} khi RM nói rõ thứ tự ("mới nhất
  trước", "giá trị cao nhất"). KHÔNG nói rõ thì để null — mặc định của hệ thống
  là xếp theo mức độ đáng ưu tiên, và đó gần như luôn là thứ RM muốn.

- "so_luong": số khách cần lấy. Không nói thì bỏ qua.
"""

#: Từ khoá cho chốt chặn khi ① không chắc. Cùng vai trò `mentions_store` bên
#: Talent: chặn đúng lỗi tệ nhất — trả lời "tôi không có dữ liệu" trong khi kho
#: có hàng nghìn khách hàng.
_STORE_WORDS = ("khach hang", "khach", "kho", "du lieu", "ho so", "prospect",
                "lead", "tin hieu", "co hoi", "danh muc", "phu trach")
#: Dấu hiệu câu hỏi về danh mục của chính RM.
_PORTFOLIO_WORDS = ("cua toi", "toi dang phu trach", "toi phu trach",
                    "danh muc cua toi", "toi nen goi", "khach toi")
#: Dấu hiệu câu hỏi về khoảng trống thị trường.
_WHITESPACE_WORDS = ("chua ai cham", "chua ai phu trach", "chua duoc phan cong",
                     "con bo trong", "chua ai goi", "chua tiep can")

VALID_SEGMENTS = ("mass", "affluent", "priority")
VALID_SENIORITY = ("manager", "executive")


def _fold(text):
    """Bỏ dấu + hạ chữ thường, để chốt chặn không phụ thuộc cách gõ dấu."""
    from people.normalize import normalize_name
    return normalize_name(text or "")


def mentions_store(question):
    folded = _fold(question)
    return any(word in folded for word in _STORE_WORDS)


def looks_like_portfolio(question):
    folded = _fold(question)
    return any(word in folded for word in _PORTFOLIO_WORDS)


def looks_like_whitespace(question):
    folded = _fold(question)
    return any(word in folded for word in _WHITESPACE_WORDS)


@dataclass
class ProspectPlan:
    """Kế hoạch một lượt. Mọi trường đều có mặc định dùng được ngay."""

    shape: str = "find_prospects"
    information_need: str = ""
    must_have: list = field(default_factory=list)
    should_have: list = field(default_factory=list)
    extract: list = field(default_factory=list)
    search_queries: list = field(default_factory=list)
    products: list = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    sort_by: dict = field(default_factory=dict)
    limit: int = DEFAULT_LIMIT
    reasoning: str = ""
    confidence: float = 0.0
    clarifying_question: str = ""
    #: True khi ① KHÔNG hiểu được câu hỏi (model lỗi, hết hạn mức) và đang đoán.
    #: Người gọi dùng nó để dè dặt ở những cổng mà đoán sai thì tốn kém.
    fallback: bool = False
    provider: str = ""
    model: str = ""

    @property
    def needs_people(self):
        return self.shape in NEEDS_PEOPLE

    @property
    def wants_clarification(self):
        return bool(self.clarifying_question) and self.confidence < CLARIFY_BELOW

    def as_dict(self):
        return {"shape": self.shape, "information_need": self.information_need,
                "must_have": list(self.must_have), "should_have": list(self.should_have),
                "extract": list(self.extract), "search_queries": list(self.search_queries),
                "products": list(self.products), "filters": dict(self.filters),
                "sort_by": dict(self.sort_by), "limit": self.limit,
                "confidence": self.confidence,
                "clarifying_question": self.clarifying_question,
                "fallback": self.fallback,
                "provider": self.provider, "model": self.model}


def _filters(value):
    """Chỉ giữ khoá hợp lệ và giá trị thuộc tập cho phép.

    Bỏ im lặng thứ không hợp lệ chứ không ném lỗi: một `phan_khuc: "VIP"` do
    model bịa ra không được làm hỏng cả lượt, nhưng cũng tuyệt đối không được
    trở thành bộ lọc — lọc theo một giá trị không tồn tại thì kết quả luôn rỗng
    và RM không biết vì sao.
    """
    if not isinstance(value, dict):
        return {}
    out = {}
    if isinstance(value.get("tinh_thanh"), str) and value["tinh_thanh"].strip():
        out["tinh_thanh"] = value["tinh_thanh"].strip()[:100]
    if value.get("phan_khuc") in VALID_SEGMENTS:
        out["phan_khuc"] = value["phan_khuc"]
    if value.get("cap_bac") in VALID_SENIORITY:
        out["cap_bac"] = value["cap_bac"]
    for flag in ("phai_co_lien_he", "loai_co_hoi_dang_mo"):
        if isinstance(value.get(flag), bool) and value[flag]:
            out[flag] = True
    days = as_int(value.get("tin_hieu_trong_ngay"), 0)
    if days and 0 < days <= 3650:
        out["tin_hieu_trong_ngay"] = days
    return out


def _products(value):
    from ..models import PRODUCT_CHOICES
    valid = {code for code, _label in PRODUCT_CHOICES}
    return [p for p in as_list(value) if isinstance(p, str) and p in valid][:5]


def _sort_by(value):
    if not isinstance(value, dict):
        return {}
    key = str(value.get("key") or "").strip()[:60]
    if not key:
        return {}
    direction = "asc" if str(value.get("dir") or "").lower() == "asc" else "desc"
    return {"key": key, "dir": direction}


def _confidence(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _context_block(envelope):
    """Ngữ cảnh hội thoại cho ①: nhóm người lượt trước + điều RM đã dặn."""
    projection = getattr(envelope, "projection", None)
    if projection is None:
        return ""
    parts = []
    last = dict(getattr(projection, "last_result", None) or {})
    items = last.get("items") or []
    if items:
        names = ", ".join(str(i.get("name") or "") for i in items[:8] if i.get("name"))
        if names:
            parts.append(f"NHÓM KHÁCH HÀNG Ở LƯỢT TRƯỚC: {names}")
    summary = getattr(projection, "summary", "") or ""
    if summary:
        parts.append(f"TÓM TẮT HỘI THOẠI: {summary[:600]}")
    memories = getattr(projection, "memories", []) or []
    if memories:
        parts.append("RM ĐÃ DẶN: " + "; ".join(str(m)[:160] for m in memories[:5]))
    recent = getattr(projection, "recent_turns", []) or []
    if recent:
        lines = []
        for index, turn in enumerate(recent[-6:]):
            is_last = (index == len(recent[-6:]) - 1)
            q = str((turn or {}).get("question") or "")[:200]
            raw_a = str((turn or {}).get("answer") or "").strip()
            if is_last:
                a = raw_a if len(raw_a) <= 2500 else (raw_a[:1600] + "\n...\n" + raw_a[-800:])
            else:
                a = raw_a[:500]
            if q:
                lines.append(f"H: {q}")
            if a:
                lines.append(f"Đ: {a}")
        if lines:
            parts.append("CÁC LƯỢT GẦN ĐÂY:\n" + "\n".join(lines))
    return "\n\n".join(parts)



def _fallback(question, provider="", model=""):
    """Kế hoạch tối thiểu khi ① không chạy được. KHÔNG được biến ô hỏi thành ô hỏng.

    Đoán `find_prospects` chứ không `general`: RM mở Growth Radar để tìm khách,
    nên đoán sai theo chiều "có tìm" chỉ tốn một lượt truy hồi, còn đoán sai
    theo chiều "không liên quan" thì trả lời "tôi không có dữ liệu" trên một kho
    đầy dữ liệu — sai nghiêm trọng hơn hẳn.
    """
    text = " ".join(str(question or "").split())[:400]
    shape = "find_prospects"
    from .act import detect_verb
    if detect_verb(text):
        shape = "action"
    elif looks_like_portfolio(text):
        shape = "portfolio"
    elif looks_like_whitespace(text):
        shape = "whitespace"
    return ProspectPlan(shape=shape, information_need=text,
                        search_queries=[text] if text else [],
                        fallback=True, provider=provider, model=model)


def plan(question, *, envelope=None, user=None, complete_fn=None) -> ProspectPlan:
    """Câu hỏi → `ProspectPlan`. Không bao giờ ném lỗi lên trên."""
    question = " ".join(str(question or "").split())
    if not question:
        return ProspectPlan(shape="general", confidence=1.0)

    messages = [{"role": "system", "content": SYSTEM}]
    context = _context_block(envelope)
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": question})

    caller = complete_fn or complete
    try:
        # `reasoning_effort="none"` + `max_tokens=1300`: cùng bài học đã vá bên
        # `talent/answer/plan.py` (comment ở đó, và `ai/tasks.py` mục DEFAULT_ROUTE)
        # — schema ở đây CÒN NHIỀU khoá hơn Talent (13 khoá + object `bo_loc` lồng
        # 6 khoá con so với 12 khoá phẳng), lại có "suy_luan" là khoá ĐẦU TIÊN, nên
        # rủi ro model "nghĩ" ngốn hết token trước khi ra JSON còn cao hơn. Thiếu
        # `reasoning_effort` (bản trước) để model tự quyết định có nghĩ hay không,
        # và `max_tokens=900` (thấp hơn cả mức 1100 Talent cần) — kết quả nhiều khả
        # năng là JSON bị cắt giữa chừng, `extract_json` trượt, rơi thẳng xuống
        # nhánh dự phòng "đoán theo từ khoá" (UI: badge "Dự phòng").
        result = caller(messages, task=TASK, temperature=0, max_tokens=1300,
                        reasoning_effort="none", budget_seconds=25,
                        response_format={"type": "json_object"})
    except Exception as exc:                       # noqa: BLE001 - xem docstring
        log.warning("rb.answer.plan: LLM lỗi, dùng kế hoạch tối thiểu: %s", exc)
        return _fallback(question)

    raw = extract_json(getattr(result, "text", "")) or {}
    provider = getattr(result, "provider", "")
    model = getattr(result, "model", "")
    if not isinstance(raw, dict) or not raw:
        # Nhánh này TRƯỚC ĐÂY im lặng — không có exception nên không đi qua log ở
        # trên, và người vận hành không có cách nào biết ① vừa rơi vào dự phòng vì
        # sao. Ghi log để `docker logs | grep "rb.answer.plan"` bắt được CẢ hai
        # kiểu lỗi, không chỉ kiểu ném exception.
        log.warning("rb.answer.plan: JSON rỗng/không đọc được (provider=%s model=%s), "
                   "dùng kế hoạch tối thiểu. Raw text: %r",
                   provider, model, str(getattr(result, "text", ""))[:300])
        return _fallback(question, provider, model)

    shape = raw.get("shape") if raw.get("shape") in SHAPES else "find_prospects"
    confidence = _confidence(raw.get("do_tin_cay"))
    reasoning = str(raw.get("suy_luan") or "")[:800]

    # --- Chốt chặn, theo đúng thứ tự ưu tiên -------------------------------
    #
    # ① chọn "general" cho một câu rõ ràng nói về kho là lỗi tệ nhất hệ thống
    # này mắc được: Radar trả lời "tôi không có dữ liệu" trong khi kho có hàng
    # nghìn khách hàng. Chỉ nhường đường khi ① vừa rất chắc vừa đã thật sự suy
    # luận — `do_tin_cay` cao mà `suy_luan` rỗng là dấu hiệu model điền bừa.
    if (shape == "general" and mentions_store(question)
            and not (confidence > TRUST_SHAPE_ABOVE and reasoning)):
        log.info("rb.answer.plan: ép 'general' → 'analyze' vì câu hỏi nhắc tới kho: "
                 "%r (① chắc %.2f)", question[:80], confidence)
        shape = "analyze"

    # Phạm vi dữ liệu quan trọng hơn cách trình bày: chọn nhầm `find_prospects`
    # cho câu "khách của tôi" trả về khách của người khác — RM gọi nhầm người
    # đồng nghiệp đang chăm. Chốt chặn này chỉ áp khi ① không chắc.
    if shape in ("find_prospects", "analyze") and confidence <= TRUST_SHAPE_ABOVE:
        if looks_like_portfolio(question):
            log.info("rb.answer.plan: ép '%s' → 'portfolio' theo từ khoá", shape)
            shape = "portfolio"
        elif looks_like_whitespace(question):
            log.info("rb.answer.plan: ép '%s' → 'whitespace' theo từ khoá", shape)
            shape = "whitespace"

    # Câu lệnh bị xếp nhầm thành tìm kiếm thì ② đi tìm lại từ đầu và có thể ra
    # một danh sách KHÁC với danh sách RM đang trỏ tới. Động từ nhận bằng cùng
    # quy tắc mà `act.py` sẽ thực thi, nên hai nơi không thể hiểu khác nhau.
    if shape not in ("action", "general") and confidence <= TRUST_SHAPE_ABOVE:
        from .act import detect_verb
        if detect_verb(question):
            log.info("rb.answer.plan: ép '%s' → 'action' theo động từ câu lệnh", shape)
            shape = "action"

    limit = as_int(raw.get("so_luong"), 0) or DEFAULT_LIMIT
    queries = [str(q).strip() for q in as_list(raw.get("search_queries"))
               if str(q or "").strip()][:MAX_QUERIES]
    need = str(raw.get("information_need") or question)[:500]
    clarify = str(raw.get("cau_hoi_lam_ro") or "")[:300]

    from talent.answer.plan import clean_proposal_to_need, detect_last_proposal, is_short_affirmation
    if is_short_affirmation(question) and envelope is not None:
        last_proposal = detect_last_proposal(envelope)
        if last_proposal:
            clean_need = clean_proposal_to_need(last_proposal)
            if clarify or confidence < CLARIFY_BELOW:
                clarify = ""
                confidence = max(confidence, 0.9)
                if not reasoning:
                    reasoning = f"RM xác nhận đồng ý với đề xuất của Radar: {last_proposal[:150]}"
            if shape in ("general", ""):
                shape = "followup"
            if not queries or queries == [need or question]:
                queries = [clean_need]
            if not need or need.casefold() == question.casefold():
                need = clean_need

    if not queries:
        # Không có truy vấn thì ② không có gì để chạy. Dùng chính câu hỏi —
        # kém hơn nhiều truy vấn, nhưng khác hẳn với việc trả về rỗng.
        queries = [need or question]

    return ProspectPlan(
        shape=shape,
        information_need=need,
        must_have=[str(x).strip() for x in as_list(raw.get("must_have")) if str(x or "").strip()][:8],
        should_have=[str(x).strip() for x in as_list(raw.get("should_have")) if str(x or "").strip()][:8],
        extract=[str(x).strip() for x in as_list(raw.get("extract")) if str(x or "").strip()][:8],
        search_queries=queries,
        products=_products(raw.get("san_pham")),
        filters=_filters(raw.get("bo_loc")),
        sort_by=_sort_by(raw.get("sap_xep")),
        limit=max(1, min(limit, MAX_LIMIT)),
        reasoning=reasoning,
        confidence=confidence,
        clarifying_question=clarify,
        provider=provider,
        model=model,
    )


def widen(previous: ProspectPlan) -> ProspectPlan:
    """Nới điều kiện khi ② + ③ trả về quá mỏng.

    Hạ `must_have` xuống `should_have` chứ không xoá: điều kiện vẫn tham gia xếp
    hạng, chỉ thôi loại người. Bỏ hẳn thì lượt nới trả về một danh sách không
    liên quan gì tới câu hỏi, còn tệ hơn danh sách ngắn.

    Bộ lọc cứng cũng nới, TRỪ hai thứ: `loai_co_hoi_dang_mo` và mọi thứ liên
    quan tuân thủ. Nới một ràng buộc tuân thủ để có thêm kết quả là đánh đổi
    không ai được phép làm thay RM.
    """
    filters = {k: v for k, v in (previous.filters or {}).items()
               if k in ("loai_co_hoi_dang_mo",)}
    return replace(
        previous,
        must_have=[],
        should_have=list(previous.should_have) + list(previous.must_have),
        filters=filters,
    )
