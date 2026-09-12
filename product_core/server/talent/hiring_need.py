# -*- coding: utf-8 -*-
"""Dịch câu hỏi tuyển dụng tiếng Việt thành bộ tiêu chí có cấu trúc.

Đây là một trong hai chỗ duy nhất LLM tham gia ở Phase 7 (chỗ kia là diễn giải
kết quả). Nó KHÔNG chấm điểm, KHÔNG chọn ai — chỉ đọc câu hỏi rồi điền vào đúng
những tham số mà `search()` đã nhận từ Phase 6.

Nhờ vậy mọi thứ AI làm đều **giải thích được bằng bộ lọc cụ thể**, và người dùng
sửa được bộ lọc thay vì phải viết lại câu hỏi. Không có đường tìm kiếm thứ hai
song song chỉ dành cho AI.

Đầu ra của LLM luôn được kiểm tra lại: nó có thể bịa khoá, trả kiểu sai, hoặc trả
số vô lý. Tiêu chí sai không làm hỏng gì to tát nhưng cho kết quả khó hiểu, và
người dùng sẽ không biết vì sao.
"""
import json
import logging
import re

from ai.router import complete
from core.vn_locations import canonical_province
from talent import keywords

log = logging.getLogger(__name__)

TASK = "talent_search"

# Chỉ những khoá này được đi tiếp vào search(). Khoá lạ bị bỏ.
ALLOWED_KEYS = {"skills", "title", "location", "company", "min_years", "max_years",
                "has_email", "has_phone", "text", "product", "lead_status"}
PRODUCTS = {"credit_card", "mortgage", "auto_loan", "consumer_loan", "savings",
            "investment", "insurance", "fx", "payroll"}
LEAD_STATUSES = {"cold", "warm", "interested", "converted", "dormant"}

MAX_SKILLS = 12
MAX_YEARS = 60

SYSTEM_PROMPT = """Bạn chuyển câu hỏi tìm người của Recruiter hoặc RM thành tiêu chí tìm kiếm dạng JSON.

Chỉ trả về JSON, không giải thích. Các khoá được phép:
- skills: mảng chuỗi, kỹ năng/công nghệ cụ thể (ví dụ "SQL", "Python", "Power BI")
- title: chuỗi, chức danh công việc (ví dụ "Data Analyst")
- location: chuỗi, tỉnh/thành phố (ví dụ "Hà Nội")
- company: chuỗi, lĩnh vực hoặc tên công ty từng làm (ví dụ "ngân hàng")
- min_years: số, số năm kinh nghiệm tối thiểu
- max_years: số, số năm kinh nghiệm tối đa
- has_email: true nếu yêu cầu phải có email
- has_phone: true nếu yêu cầu phải có số điện thoại
- product: nhóm sản phẩm khách đã có tín hiệu quan tâm; chỉ một trong credit_card,
  mortgage, auto_loan, consumer_loan, savings, investment, insurance, fx, payroll
- lead_status: trạng thái khách hàng; chỉ một trong cold, warm, interested, converted, dormant

Quy tắc:
- BỎ QUA khoá nào không suy ra được từ câu hỏi. Đừng đoán.
- Lĩnh vực (ngân hàng, tài chính, bán lẻ) là "company", KHÔNG phải "skills".
- Chức danh là "title", KHÔNG đưa vào "skills".
- "trên 3 năm" -> min_years 3. "dưới 5 năm" -> max_years 5. "3-5 năm" -> cả hai.
- Cấp bậc (senior, junior, trưởng nhóm) là một phần của "title".
- Chỉ điền product khi người hỏi nói rõ nhóm sản phẩm; không suy sản phẩm từ chức danh.

QUAN TRỌNG — "title" và "skills" không được ép về MỘT chức danh tiếng Anh duy nhất.
Hãy giữ cách diễn đạt nghiệp vụ rộng nhất có trong câu hỏi; retrieval đa ngôn ngữ/canonical sẽ mở rộng alias.
Ví dụ "quan hệ khách hàng cá nhân" KHÔNG được tự đổi thành chỉ "Customer Relationship Manager".
"title" và "skills" phải viết bằng THUẬT NGỮ NHƯ TRONG CV khi điều đó không làm mất nghĩa:
CV ứng viên Việt Nam hầu hết ghi chức danh và kỹ năng bằng tiếng Anh. Người hỏi
thì hỏi bằng tiếng Việt. Hãy chuyển sang đúng từ mà CV dùng.
- "làm về dữ liệu" -> title "Data"
- "phân tích dữ liệu" -> title "Data Analyst"
- "lập trình viên backend" -> title "Backend"
- "kế toán" -> title "Accountant"
- "nhân sự" -> title "HR"
Chỉ giữ tiếng Việt khi đó thật sự là từ hay xuất hiện trong CV (ví dụ
"Chuyên viên Phân tích Tín dụng").
Với "title", hãy dùng phần LÕI ngắn gọn để khớp được nhiều biến thể:
"Data Analyst" khớp cả "Senior Data Analyst" và "Data Analyst Intern".

"company" và "location" thì giữ nguyên tiếng Việt như người hỏi viết.

Nếu có "TIÊU CHÍ TRƯỚC ĐÓ" đi kèm: đây là câu hỏi HỎI TIẾP trong cùng cuộc
trò chuyện, không phải một câu hỏi độc lập. Chỉ trả về những khoá câu hỏi mới
THAY ĐỔI hoặc THÊM MỚI — khoá nào câu hỏi mới không nhắc tới thì bỏ qua để
tiêu chí trước đó được giữ nguyên. Nếu câu mới bảo bỏ/không cần/reset, trả thêm
"operations": [{"op":"REMOVE|RESET|REPLACE|ADD", "field":"tên_khoá", "value":giá_trị}]."""


class HiringNeed:
    """Kết quả dịch: tiêu chí đã kiểm, cộng thông tin để giải thích cho người dùng."""

    def __init__(self, question, criteria, raw="", provider="", model="",
                 dropped=None, error="", fallback=False, operations=None):
        self.question = question
        self.criteria = criteria
        self.raw = raw
        self.provider = provider
        self.model = model
        self.dropped = dropped or []
        self.error = error
        #: True = tiêu chí do dò từ khoá, không phải LLM đọc câu hỏi.
        self.fallback = fallback
        self.operations = operations or []

    @property
    def is_empty(self):
        return not any(v not in (None, "", [], False) for v in self.criteria.values())

    def as_dict(self):
        return {"question": self.question, "criteria": self.criteria,
                "provider": self.provider, "model": self.model,
                "dropped": self.dropped, "error": self.error,
                "fallback": self.fallback, "operations": self.operations}


# Dấu hiệu câu HỎI TIẾP: người dùng đang tinh chỉnh lượt trước, không nêu lại
# toàn bộ nhu cầu. Chỉ khi khớp mới kế thừa tiêu chí lượt trước — nếu không,
# "tìm ứng viên quan hệ khách hàng" (câu độc lập) sẽ bị dính "Hà Nội" từ lượt cũ.
_FOLLOWUP_MARKERS = (
    "còn", "vậy", "thế thì", "thì sao", "thêm", "bớt", "bỏ", "loại", "không cần",
    "ngoài ra", "nữa", "ở trên", "vừa rồi", "lúc nãy", "danh sách này",
    "người này", "người đó", "họ", "kết quả trên", "lọc thêm", "chỉ giữ",
    "narrow", "also", "instead", "without", "remove", "add ",
)


def _is_followup(question):
    q = " " + str(question or "").strip().casefold() + " "
    if len(q.split()) <= 4:
        return True
    return any(f" {m} " in q or q.startswith(m + " ") for m in _FOLLOWUP_MARKERS)


def parse(question, complete_fn=None, history=None, envelope=None):
    """Câu hỏi tự nhiên -> HiringNeed.

    Không gọi được LLM thì lùi về tìm chữ tự do thay vì báo lỗi: người dùng vẫn
    nhận được kết quả, chỉ kém tinh hơn. Mất AI không được biến ô tìm kiếm thành
    ô hỏng.

    `history`: tiêu chí các lượt hỏi TRƯỚC ĐÓ trong cùng cuộc trò chuyện (mới
    nhất ở cuối), dạng `[{"criteria": {...}}, ...]`. Có thì đây là câu hỏi HỎI
    TIẾP — tiêu chí lượt trước làm nền, LLM chỉ cần nói THAY ĐỔI gì. Merge đơn
    giản `{**prior, **moi}` dùng được vì cả `_validate()` lẫn `_keyword_criteria()`
    đều trả dict THƯA — chỉ có khoá thật sự nhận ra được, không tự điền mặc định.
    """
    question = str(question or "").strip()
    if not question:
        return HiringNeed(question, {})

    prior = ((getattr(envelope, "projection", None).active_criteria if envelope else None)
             or ((history or [])[-1].get("criteria") if history else None))
    # Câu nêu lại đầy đủ nhu cầu (không anaphoric) => tìm MỚI, không kế thừa tiêu
    # chí lượt trước. Vẫn đưa ngữ cảnh hội thoại cho LLM để nó hiểu, chỉ không merge.
    inherit_prior = bool(prior) and _is_followup(question)
    if not inherit_prior:
        prior = None

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    conversation = [
        {"question": str(item.get("question") or "")[:500],
         "answer": str(item.get("answer") or "")[:800],
         "criteria": item.get("criteria") or {}}
        for item in (history or [])[-8:]
        if item.get("question") or item.get("answer")
    ]
    if conversation:
        messages.append({"role": "system", "content":
                         "NGỮ CẢNH 8 LƯỢT GẦN NHẤT: "
                         + json.dumps(conversation, ensure_ascii=False)})
    if prior:
        messages.append({"role": "system",
                         "content": f"TIÊU CHÍ TRƯỚC ĐÓ: {json.dumps(prior, ensure_ascii=False)}"})
    messages.append({"role": "user", "content": question})

    caller = complete_fn or complete
    try:
        result = caller(messages, task=TASK, temperature=0, max_tokens=2000,
                        reasoning_effort="none", budget_seconds=30,
                        response_format={"type": "json_object"})
    except Exception as exc:                   # noqa: BLE001 — xem docstring
        log.warning("Không dịch được câu hỏi bằng LLM, dò từ khoá thay thế: %s", exc)
        keyword_now = _keyword_criteria(question)
        operations = _heuristic_operations(question, prior)
        criteria = _apply_operations({**prior, **keyword_now} if prior else keyword_now, operations)
        return HiringNeed(question, criteria, error=str(exc)[:200], fallback=True,
                          operations=operations)

    payload = _extract_json(result.text)
    criteria, dropped = _validate(payload.get("criteria", payload) if isinstance(payload, dict) else payload)
    operations = _validate_operations(payload.get("operations") if isinstance(payload, dict) else None)
    if not operations:
        operations = _heuristic_operations(question, prior)
    if not criteria:
        # Dịch ra rỗng thì vẫn phải tìm được gì đó.
        criteria = _keyword_criteria(question)
    if prior:
        criteria = _apply_operations({**prior, **criteria}, operations)
    return HiringNeed(question, criteria, raw=result.text,
                      provider=result.provider, model=result.model, dropped=dropped,
                      operations=operations)


def _validate_operations(value):
    out = []
    for item in (value or []):
        if not isinstance(item, dict):
            continue
        op, field = str(item.get("op") or "").upper(), str(item.get("field") or "")
        if op in {"ADD", "REPLACE", "REMOVE", "RESET"} and field in ALLOWED_KEYS:
            out.append({"op": op, "field": field, "value": item.get("value")})
    return out[:12]


def _heuristic_operations(question, prior):
    """Fallback an toàn cho các follow-up phủ định, không cần đoán model."""
    q = str(question or "").casefold()
    if not prior or not any(term in q for term in ("bỏ", "không cần", "loại", "tìm lại từ đầu", "reset")):
        return []
    operations = []
    if "từ đầu" in q or "reset" in q:
        return [{"op": "RESET", "field": field, "value": None} for field in prior]
    for field, value in prior.items():
        values = value if isinstance(value, list) else [value]
        if any(str(v).casefold() in q for v in values if v not in (None, "")):
            operations.append({"op": "REMOVE", "field": field, "value": value})
    return operations


def _apply_operations(criteria, operations):
    out = dict(criteria or {})
    for item in operations:
        op, field, value = item["op"], item["field"], item.get("value")
        if op in {"REMOVE", "RESET"}:
            out.pop(field, None)
        elif op == "REPLACE":
            out[field] = value
        elif op == "ADD":
            current = out.get(field)
            if isinstance(current, list):
                additions = value if isinstance(value, list) else [value]
                out[field] = list(dict.fromkeys(current + additions))
            else:
                out[field] = value
    return out


def _keyword_criteria(question):
    """Dò từ khoá, và chỉ khi không dò được gì mới ném cả câu vào `text`.

    Ném cả câu vào tìm-chữ-tự-do nghe có vẻ an toàn nhưng thực tế trả về **0 kết
    quả**: không hồ sơ nào chứa nguyên văn "Tôi cần Data Analyst ở Hà Nội biết
    SQL và Python". Đó là kiểu hỏng im lặng tệ nhất — hệ thống trông như đang
    chạy, chỉ là không tìm thấy ai.
    """
    criteria = keywords.criteria_from_text(question)
    return criteria or {"text": question}


def _extract_json(text):
    """Lấy JSON ra khỏi câu trả lời.

    Có `response_format=json_object` thì phần lớn model trả JSON trần, nhưng
    không phải model nào cũng tôn trọng nó — đo thực tế cho thấy gemini-2.5-flash
    và 3.6-flash vẫn bọc trong hàng rào markdown. Bóc cả hai dạng.
    """
    text = str(text or "").strip()
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        # Vớt vát: lấy khối {...} đầu tiên.
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if not brace:
            return {}
        try:
            payload = json.loads(brace.group(0))
        except (ValueError, TypeError):
            return {}
    return payload if isinstance(payload, dict) else {}


def _validate(payload):
    """Kiểm và chuẩn hoá đầu ra của LLM. Trả (tiêu_chí, danh_sách_khoá_bị_bỏ).

    Không tin LLM: nó bịa khoá, trả chuỗi khi cần số, hoặc trả số vô lý. Tiêu chí
    sai không làm sập gì nhưng cho kết quả khó hiểu mà người dùng không biết vì sao.
    """
    criteria, dropped = {}, []

    for key, value in (payload or {}).items():
        if key not in ALLOWED_KEYS:
            dropped.append(key)
            continue

        if key == "skills":
            items = value if isinstance(value, (list, tuple)) else [value]
            skills = []
            for item in items:
                name = " ".join(str(item or "").split())[:60]
                if name and name.lower() not in {s.lower() for s in skills}:
                    skills.append(name)
            if skills:
                criteria["skills"] = skills[:MAX_SKILLS]

        elif key in ("min_years", "max_years"):
            years = _number(value)
            if years is not None and 0 <= years <= MAX_YEARS:
                criteria[key] = years
            elif value not in (None, ""):
                dropped.append(f"{key}={value!r}")

        elif key in ("has_email", "has_phone"):
            if value is True:
                criteria[key] = True

        elif key == "product":
            product = str(value or "").strip().lower()
            if product in PRODUCTS:
                criteria[key] = product
            elif product:
                dropped.append(f"product={product!r}")

        elif key == "lead_status":
            lead_status = str(value or "").strip().lower()
            if lead_status in LEAD_STATUSES:
                criteria[key] = lead_status
            elif lead_status:
                dropped.append(f"lead_status={lead_status!r}")

        elif key == "location":
            # "Sài Gòn"/"TP.HCM"/"tphcm" đều là cùng một nơi — chuẩn hoá để
            # tìm kiếm không bỏ sót người thật chỉ vì khác cách viết (xem
            # core/vn_locations.py). Không nhận ra được thì giữ nguyên văn.
            text = " ".join(str(value or "").split())[:200]
            if text:
                criteria[key] = canonical_province(text)

        else:
            text = " ".join(str(value or "").split())[:200]
            if text:
                criteria[key] = text

    # min > max là vô nghĩa; giữ lại sẽ không bao giờ trả kết quả nào.
    if (criteria.get("min_years") is not None
            and criteria.get("max_years") is not None
            and criteria["min_years"] > criteria["max_years"]):
        dropped.append("max_years<min_years")
        criteria.pop("max_years")

    return criteria, dropped


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:[.,]\d+)?", str(value or ""))
    return float(match.group(0).replace(",", ".")) if match else None
