# -*- coding: utf-8 -*-
"""MSB Radar Prospect Agent — chạy trên GreenNode AgentBase.

Hợp đồng Runtime của AgentBase (`skills/agentbase/references/runtime-contract.md`)
quy định **cứng** đúng hai điều, và cả hai đều được đáp ứng ở đây:

    1. lắng nghe cổng 8080
    2. GET /health trả HTTP 200 khi sẵn sàng

`POST /invocations` là quy ước của SDK GreenNode, không phải yêu cầu của nền
tảng — nhưng theo nó để agent hoạt động đúng như các agent khác trên cùng hạ
tầng, và để công cụ quan sát của AgentBase hiểu được lưu lượng.

## Agent này làm gì, và cố ý KHÔNG làm gì

Nó làm phần LLM thực sự giỏi:

    parse_query      câu hỏi bằng lời của RM → tiêu chí có cấu trúc
    explain          kết quả Hub đã xếp hạng → lời giải thích cho từng người
    chat             lượt gọi chat OpenAI-style bất kỳ (Hub uỷ quyền qua đây để
                     tới GreenNode MaaS NHANH hơn — agent nằm trong datacenter
                     GreenNode, Hub thì gọi ra ngoài internet). Không fallback:
                     lỗi thì Hub tự chuyển nhà cung cấp — xem `server/ai/router.py`.

Nó **không** chấm điểm, không xếp hạng, không chọn hành động. Những việc đó
nằm ở `server/rb/scoring.py` và ở nguyên đó — vì hai lý do:

  • *AI hiểu, CODE quyết* là nguyên tắc xuyên suốt dự án. Một điểm số do LLM
    sinh ra là điểm số không kiểm toán được, và ngân hàng không dùng được nó.
  • Nhân đôi logic chấm điểm ra hai nơi là cách chắc chắn để hai nơi lệch nhau,
    và lúc đó không ai trả lời được *"vì sao đề xuất này 82 điểm"*.

## Vì sao mọi hành động đều có nhánh dự phòng

Một demo sập vì mạng chập là một demo hỏng. Một demo nói rõ *"đang chạy chế độ
dự phòng"* vẫn là một demo chạy — và còn chứng minh được kiến trúc có tính đến
việc nhà cung cấp AI có thể hỏng. Cùng nguyên tắc với `server/ai/router.py`.
"""
import json
import logging
import os
import re
import time
import unicodedata

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

log = logging.getLogger("prospect-agent")
logging.basicConfig(level=logging.INFO)

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "z-ai/glm-5.2-hackathon")

#: Ngắn hơn ngưỡng của Hub (25s) một cách có chủ đích: agent nằm sau một lớp
#: mạng nữa, và một yêu cầu treo 25 giây trên sân khấu là một demo đã hỏng.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "18"))

#: `chat` mang cả lượt nặng (vd rerank hồ sơ ~6k token) nên cần ngưỡng rộng hơn
#: parse/explain. Vẫn có trần vì Hub còn ngân sách tổng của riêng nó.
CHAT_TIMEOUT = float(os.getenv("CHAT_TIMEOUT", "75"))

app = FastAPI(title="MSB Radar Prospect Agent")


# ----------------------------------------------------------- từ vựng nghiệp vụ

#: Danh mục sản phẩm bán lẻ — **giữ đồng bộ với `server/rb/models.py`**.
#:
#: Vì sao chép sang đây thay vì gọi Hub để lấy: agent phải chạy được khi Hub
#: chưa sẵn sàng, và danh mục sản phẩm ngân hàng đổi vài năm một lần chứ không
#: phải vài ngày. Cái giá là phải sửa hai chỗ khi thêm sản phẩm — chấp nhận
#: được, và `tests/test_agent.py` canh cho hai danh sách không lệch nhau.
PRODUCTS = {
    "mortgage": ["mua nhà", "mua căn hộ", "chung cư", "vay mua đất", "xây nhà",
                 "sửa nhà", "bất động sản"],
    "auto_loan": ["mua ô tô", "mua xe", "trả góp xe", "vay mua xe"],
    "consumer_loan": ["vay tiêu dùng", "vay tín chấp", "vay nóng", "vay tiền"],
    "credit_card": ["thẻ tín dụng", "mở thẻ", "thẻ premium", "hoàn tiền",
                    "trả góp 0%", "cashback"],
    "savings": ["gửi tiết kiệm", "sổ tiết kiệm", "lãi suất", "đáo hạn"],
    "investment": ["đầu tư", "chứng chỉ quỹ", "trái phiếu", "quản lý gia sản"],
    "insurance": ["bảo hiểm", "nhân thọ", "bảo hiểm sức khoẻ"],
    "fx": ["ngoại tệ", "đổi tiền", "chuyển tiền quốc tế", "du học",
           "đi nước ngoài", "du lịch nước ngoài"],
    "payroll": ["tài khoản lương", "chi lương", "trả lương"],
}

SENIORITY = {
    "manager": ["quản lý", "trưởng phòng", "manager", "giám đốc", "director",
                "trưởng nhóm", "team lead", "cấp trung"],
    "executive": ["ceo", "cfo", "cto", "founder", "chủ tịch", "tổng giám đốc",
                  "c-level", "phó tổng"],
}

SEGMENTS = {
    "priority": ["ưu tiên", "vip", "priority"],
    "affluent": ["khá giả", "affluent", "thu nhập cao"],
    "mass": ["phổ thông", "mass", "đại chúng"],
}

#: Tỉnh/thành hay gặp -> mọi cách viết thường thấy. Không cần đủ 63 — thiếu thì
#: rơi vào nhánh LLM, và nếu LLM cũng hỏng thì tiêu chí địa điểm để trống, RM
#: tự điền. Trống và sửa được thì tốt hơn nhiều so với đoán sai mà người dùng
#: không biết. Gộp theo dạng chuẩn (khoá dict) để "Sài Gòn" và "Hồ Chí Minh"
#: ra CÙNG một giá trị — khác giá trị nghĩa là Hub lọc bỏ sót người thật đang
#: có, chỉ vì khác cách viết (đồng bộ với server/core/vn_locations.py, nhưng
#: khai lại ở đây vì agent là dịch vụ tách rời, không import chéo qua Django).
CITY_ALIASES = {
    "Hồ Chí Minh": ["hồ chí minh", "tp hcm", "tphcm", "tp.hcm", "sài gòn", "sg"],
    "Hà Nội": ["hà nội", "hn"],
    "Đà Nẵng": ["đà nẵng"],
    "Hải Phòng": ["hải phòng"],
    "Cần Thơ": ["cần thơ"],
    "Bình Dương": ["bình dương"],
    "Đồng Nai": ["đồng nai"],
    "Bắc Ninh": ["bắc ninh"],
    "Quảng Ninh": ["quảng ninh"],
    "Khánh Hoà": ["khánh hoà", "nha trang"],
    "Huế": ["huế"],
    "Vũng Tàu": ["vũng tàu"],
}


def _canonical_city(text):
    """Dạng chuẩn nếu nhận ra được; nguyên văn (đã strip) nếu không."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    normalized = _normalize(cleaned)
    for canonical, aliases in CITY_ALIASES.items():
        if any(_normalize(alias) == normalized for alias in aliases):
            return canonical
    return cleaned


class InvokeRequest(BaseModel):
    action: str = Field(default="parse_query")
    query: str = ""
    #: Dùng cho `action="explain"`: các dòng Hub đã chấm điểm và xếp hạng xong.
    results: list = Field(default_factory=list)
    #: Dùng cho `action="parse_query"` khi đây là câu hỏi HỎI TIẾP trong cùng
    #: cuộc trò chuyện — tiêu chí lượt trước, để LLM chỉ cần nói THAY ĐỔI gì.
    previous_criteria: dict = Field(default_factory=dict)
    #: Dùng cho `action="chat"`: message list kiểu OpenAI + tham số.
    messages: list = Field(default_factory=list)
    temperature: float = 0.2
    max_tokens: int = 0
    response_format: dict = Field(default_factory=dict)
    reasoning_effort: str = ""


@app.get("/health")
def health():
    """Bắt buộc theo hợp đồng Runtime. Phải nhẹ và không phụ thuộc gì bên ngoài.

    Cố ý **không** gọi thử LLM ở đây: healthcheck gọi ra ngoài sẽ làm container
    bị đánh dấu hỏng mỗi khi nhà cung cấp AI chập — trong khi agent vẫn phục vụ
    được bằng nhánh dự phòng.
    """
    return {"status": "healthy", "model": LLM_MODEL, "llm_configured": bool(LLM_API_KEY)}


@app.post("/invocations")
def invocations(request: InvokeRequest):
    """Cửa vào duy nhất, theo quy ước SDK của AgentBase."""
    started = time.time()

    if request.action == "parse_query":
        payload = parse_query(request.query, previous_criteria=request.previous_criteria or None)
    elif request.action == "explain":
        payload = explain(request.query, request.results)
    elif request.action == "chat":
        payload = chat(request)
    else:
        return {"error": f"Hành động không hỗ trợ: {request.action}",
                "supported": ["parse_query", "explain", "chat"]}

    payload["latency_ms"] = int((time.time() - started) * 1000)
    return payload


# --------------------------------------------------------------------- chat

def chat(request):
    """Lượt chat OpenAI-style bất kỳ, uỷ quyền cho GreenNode MaaS.

    KHÔNG có nhánh dò-từ-khoá: `chat` là tác vụ chung, không có "bản tất định"
    hợp lý để lùi về. Lỗi → trả `{"error": ...}` để Hub chuyển nhà cung cấp.
    """
    if not LLM_API_KEY:
        return {"error": "Agent chưa cấu hình khoá GreenNode (LLM_API_KEY)."}
    messages = [m for m in (request.messages or [])
                if isinstance(m, dict) and m.get("role") and m.get("content") is not None]
    if not messages:
        return {"error": "messages rỗng hoặc sai khuôn."}
    try:
        text, usage = _complete_messages(
            messages, temperature=request.temperature,
            max_tokens=request.max_tokens or 1200,
            response_format=request.response_format or None,
            reasoning_effort=request.reasoning_effort or "")
    except Exception as error:                            # noqa: BLE001
        log.warning("chat lỗi: %s", error)
        return {"error": str(error)[:300]}
    if not str(text or "").strip():
        return {"error": "Mô hình trả về nội dung rỗng."}
    return {"text": text, "model": LLM_MODEL, "mode": "llm", "usage": usage}


# --------------------------------------------------------------- parse_query

PARSE_SYSTEM = (
    "Bạn là trợ lý phân tích câu hỏi tìm khách hàng của ngân hàng MSB. "
    "Trả về DUY NHẤT một object JSON, không kèm giải thích, theo khuôn:\n"
    '{"location":"","seniority":"","products":[],"segment":"",'
    '"require_contact":false,"limit":0,"signal_recency_days":0}\n'
    "products chỉ được chọn trong: " + ", ".join(PRODUCTS) + ".\n"
    "seniority chỉ được là một trong: manager, executive, hoặc chuỗi rỗng.\n"
    "Không suy diễn thêm trường nào ngoài khuôn trên.\n\n"
    "Nếu người dùng đưa 'TIÊU CHÍ TRƯỚC ĐÓ': đây là câu hỏi HỎI TIẾP trong "
    "cùng cuộc trò chuyện. Chỉ trả khoá mà 'CÂU HỎI MỚI' THAY ĐỔI hoặc THÊM "
    "MỚI — khoá không nhắc tới thì bỏ qua để tiêu chí trước được giữ nguyên."
)


def parse_query(query, previous_criteria=None):
    """Câu hỏi bằng lời → tiêu chí có cấu trúc.

    Trả về tiêu chí **hiện ra và sửa được**, không phải một hộp đen. Đây là
    nguyên tắc của cả sản phẩm: RM phải nhìn thấy hệ thống hiểu câu hỏi thế nào
    trước khi tin vào kết quả.

    `previous_criteria`: tiêu chí lượt hỏi trước trong cùng cuộc trò chuyện.
    Có thì đây là câu hỏi hỏi tiếp — tiêu chí đó làm nền, cả nhánh dò từ khoá
    lẫn LLM chỉ cần nói THAY ĐỔI gì so với nền đó.
    """
    keyword_now = _parse_by_keyword(query)
    baseline = _validate_criteria(keyword_now, previous_criteria) if previous_criteria else keyword_now

    if not LLM_API_KEY:
        return {"criteria": baseline, "mode": "fallback",
                "note": "Chưa cấu hình khoá GreenNode — dùng dò từ khoá."}

    user_content = query
    if previous_criteria:
        user_content = (f"TIÊU CHÍ TRƯỚC ĐÓ: {json.dumps(previous_criteria, ensure_ascii=False)}\n\n"
                        f"CÂU HỎI MỚI: {query}")

    try:
        raw = _complete(PARSE_SYSTEM, user_content)
        parsed = _extract_json(raw)
    except Exception as error:                        # noqa: BLE001
        log.warning("Không bóc tách được bằng LLM, dùng dò từ khoá: %s", error)
        return {"criteria": baseline, "mode": "fallback", "note": str(error)[:200]}

    if parsed is None:
        return {"criteria": baseline, "mode": "fallback",
                "note": "Mô hình trả về không đúng khuôn JSON."}

    # LLM có thể bịa tên sản phẩm không tồn tại trong danh mục MSB. Lọc lại ở
    # đây là chốt chặn cuối: gợi ý một sản phẩm ngân hàng không bán là lỗi tệ
    # hơn nhiều so với gợi ý thiếu.
    merged = _validate_criteria(parsed, baseline)
    return {"criteria": merged, "mode": "llm", "model": LLM_MODEL}


def _parse_by_keyword(query):
    """Nhánh tất định. Luôn chạy, kể cả khi có LLM — nó là mốc đối chiếu."""
    text = _normalize(query)
    criteria = {"location": "", "seniority": "", "products": [], "segment": "",
                "require_contact": False, "limit": 0, "signal_recency_days": 0}

    for canonical, aliases in CITY_ALIASES.items():
        if any(_normalize(alias) in text for alias in aliases):
            criteria["location"] = canonical
            break

    for level, hints in SENIORITY.items():
        if any(_normalize(hint) in text for hint in hints):
            criteria["seniority"] = level
            break

    for product, hints in PRODUCTS.items():
        if any(_normalize(hint) in text for hint in hints):
            criteria["products"].append(product)

    for segment, hints in SEGMENTS.items():
        if any(_normalize(hint) in text for hint in hints):
            criteria["segment"] = segment
            break

    if any(word in text for word in ("co contact", "co so", "co dien thoai",
                                     "lien he duoc", "co email")):
        criteria["require_contact"] = True

    số = re.search(r"\b(\d{1,4})\b", query)
    if số:
        criteria["limit"] = min(int(số.group(1)), 500)

    ngày = re.search(r"(\d{1,3})\s*(ngày|thang|tháng)", query.lower())
    if ngày:
        value = int(ngày.group(1))
        criteria["signal_recency_days"] = value * 30 if "th" in ngày.group(2) else value

    return criteria


def _validate_criteria(parsed, baseline):
    """Giữ những gì LLM hiểu đúng, vá những gì nó bịa hoặc bỏ sót."""
    result = dict(baseline)

    products = [p for p in (parsed.get("products") or []) if p in PRODUCTS]
    if products:
        result["products"] = products

    seniority = str(parsed.get("seniority") or "")
    if seniority in SENIORITY:
        result["seniority"] = seniority

    segment = str(parsed.get("segment") or "")
    if segment in SEGMENTS:
        result["segment"] = segment

    location = str(parsed.get("location") or "").strip()
    if location:
        result["location"] = _canonical_city(location)[:100]

    if parsed.get("require_contact") is True:
        result["require_contact"] = True

    for field, ceiling in (("limit", 500), ("signal_recency_days", 730)):
        try:
            value = int(parsed.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if 0 < value <= ceiling:
            result[field] = value

    return result


# ------------------------------------------------------------------- explain

EXPLAIN_SYSTEM = (
    "Bạn là trợ lý của chuyên viên quan hệ khách hàng ngân hàng MSB. "
    "Với mỗi khách hàng được cung cấp, viết MỘT câu tiếng Việt ngắn (tối đa 30 "
    "từ) nói vì sao nên tiếp cận họ bây giờ. Chỉ dùng thông tin được cung cấp, "
    "TUYỆT ĐỐI không bịa thêm dữ kiện, không nhắc tới việc theo dõi mạng xã "
    "hội. Trả về JSON: {\"explanations\": [{\"id\": <id>, \"text\": \"...\"}]}"
)


def explain(query, results):
    """Kết quả Hub đã xếp hạng → lời giải thích cho từng người.

    Agent **không** đổi thứ tự và không đổi điểm — nó chỉ diễn đạt lại bằng lời
    những gì Hub đã tính. Nếu LLM hỏng thì ghép từ `why` có sẵn, nên mục
    "vì sao bây giờ" trên thẻ không bao giờ trống.
    """
    rows = [row for row in results if isinstance(row, dict)][:20]
    if not rows:
        return {"explanations": [], "mode": "empty"}

    baseline = [{"id": row.get("id"), "text": _explain_by_rule(row)} for row in rows]
    if not LLM_API_KEY:
        return {"explanations": baseline, "mode": "fallback"}

    compact = [{"id": row.get("id"),
                "name": row.get("person_name", ""),
                "product": row.get("product_label", ""),
                "need": row.get("need_summary", ""),
                "why": (row.get("why") or [])[:4]}
               for row in rows]
    try:
        raw = _complete(EXPLAIN_SYSTEM,
                        json.dumps({"query": query, "people": compact},
                                   ensure_ascii=False))
        parsed = _extract_json(raw) or {}
    except Exception as error:                        # noqa: BLE001
        log.warning("Không diễn giải được bằng LLM: %s", error)
        return {"explanations": baseline, "mode": "fallback",
                "note": str(error)[:200]}

    by_id = {}
    for item in parsed.get("explanations") or []:
        if isinstance(item, dict) and item.get("id") is not None:
            text = str(item.get("text") or "").strip()
            # Câu quá ngắn là câu bị cắt cụt — dùng bản tất định thay vì hiển
            # thị một mẩu chữ dở dang cho RM.
            if len(text) >= 15:
                by_id[item["id"]] = text[:300]

    merged = [{"id": row["id"], "text": by_id.get(row["id"], row["text"])}
              for row in baseline]
    return {"explanations": merged,
            "mode": "llm" if by_id else "fallback"}


def _explain_by_rule(row):
    """Ghép từ `why` Hub đã tính. Không gọi mạng, không bao giờ hỏng."""
    why = [str(item) for item in (row.get("why") or []) if str(item).strip()]
    product = row.get("product_label") or "sản phẩm phù hợp"
    if why:
        return f"{product}: {'; '.join(why[:2])}."
    need = row.get("need_summary") or "có tín hiệu đáng chú ý"
    return f"{product}: {need}."


# ----------------------------------------------------------------- hạ tầng LLM

def _complete(system, user):
    """Một lượt gọi GreenNode MaaS theo chuẩn OpenAI Chat Completions."""
    response = httpx.post(
        f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}",
                 "Content-Type": "application/json"},
        json={"model": LLM_MODEL,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}],
              # Nhiệt độ thấp: đây là tác vụ bóc tách, không phải sáng tác.
              "temperature": 0.1,
              "max_tokens": 1200},
        timeout=LLM_TIMEOUT)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _complete_messages(messages, *, temperature=0.2, max_tokens=1200,
                       response_format=None, reasoning_effort=""):
    """Như `_complete` nhưng nhận message list nguyên vẹn — cho `action="chat"`."""
    body = {"model": LLM_MODEL, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens}
    if response_format:
        body["response_format"] = response_format
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    response = httpx.post(
        f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}",
                 "Content-Type": "application/json"},
        json=body, timeout=CHAT_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"], data.get("usage") or {}


def _extract_json(raw):
    """Lấy object JSON đầu tiên trong phản hồi.

    Mô hình hay bọc JSON trong khối ```json hoặc thêm một câu dẫn nhập, kể cả
    khi đã bảo đừng. Bắt lỗi ở đây rẻ hơn nhiều so với để cả luồng rơi xuống
    nhánh dự phòng chỉ vì thừa ba dấu backtick.
    """
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except (TypeError, ValueError):
        return None


def _normalize(text):
    """Bỏ dấu + chữ thường, để 'Hà Nội' khớp 'ha noi'."""
    stripped = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D").lower()
