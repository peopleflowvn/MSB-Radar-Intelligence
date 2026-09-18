# -*- coding: utf-8 -*-
"""Tìm prospect bằng ngôn ngữ tự nhiên (Master Plan mục 16, Task 6).

    "Tìm 20 người làm quản lý ở Hà Nội, có contact và có tín hiệu đi nước ngoài."
        ↓
    câu hỏi → tiêu chí → tìm người → chấm điểm → giải thích

Khác với `rb/suggestions.py` — nơi Radar **chủ động đẩy** cơ hội tới RM — module
này phục vụ lúc RM **chủ động hỏi**. Hai luồng bổ sung nhau chứ không thay thế:
"hôm nay tôi nên gọi ai" và "tìm cho tôi nhóm người thế này" là hai câu hỏi
khác nhau, và một sản phẩm bán hàng nghiêm túc phải trả lời được cả hai.

## Tiêu chí luôn hiện ra và sửa được

Đây là ràng buộc cứng, không phải tuỳ chọn giao diện. RM phải nhìn thấy hệ
thống hiểu câu hỏi của mình thế nào **trước khi** tin vào danh sách trả về —
và sửa được tiêu chí thay vì phải đoán cách viết lại câu hỏi cho AI hiểu.

Không có đường tìm kiếm thứ hai chỉ dành cho AI: `search()` ở đây dùng đúng
những bộ lọc mà giao diện lọc tay đang dùng.

## Uỷ quyền bóc tách cho agent trên AgentBase

Nếu `MSB_AGENT_ENDPOINT` được đặt, bước bóc tách câu hỏi gọi sang Prospect Agent
đang chạy trên GreenNode AgentBase (`agent/`). Không đặt thì Hub tự bóc tách
bằng chính `ai/router` — cùng một mô hình GreenNode, chỉ khác chỗ chạy.

Vì sao làm được cả hai đường: agent có thể chưa deploy, có thể đang restart, và
một sản phẩm phụ thuộc cứng vào một endpoint bên ngoài là sản phẩm không demo
được khi endpoint đó chập. Đường nào chạy cũng được ghi lại trong `criteria_from`
để người vận hành biết đường nào đang phục vụ.
"""
import json
import logging
import os
import re

from ai.router import complete
from core.vn_locations import canonical_province, location_query_variants
from django.db.models import Q
from people.models import Person, Signal
from django.utils import timezone

from . import scoring
from .models import PRODUCT_CHOICES, RBOpportunity, RBProfile

log = logging.getLogger(__name__)

TASK = "rb_prospect_search"

#: Endpoint của Prospect Agent trên AgentBase. Trống = Hub tự bóc tách.
AGENT_ENDPOINT = os.getenv("MSB_AGENT_ENDPOINT", "").strip()
AGENT_TIMEOUT = float(os.getenv("MSB_AGENT_TIMEOUT", "3"))

VALID_PRODUCTS = {code for code, _label in PRODUCT_CHOICES}
VALID_SEGMENTS = {code for code, _label in RBProfile.SEGMENT_CHOICES}
VALID_SENIORITY = {"manager", "executive"}

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

#: Trần số khách hàng được CHẤM ĐIỂM trong một lượt tìm. `_score` đọc profile,
#: interests, relationships và signals đã prefetch nên chi phí là CPU chứ không
#: phải truy vấn; 500 người đo được vài chục mili-giây. Đặt ở đây thay vì nhân
#: với `limit` vì ngân sách này thuộc về máy chủ, không thuộc về việc RM xin 5
#: hay 50 người.
SCORING_BUDGET = int(os.getenv("RB_PROSPECT_SCORING_BUDGET", "500"))

SYSTEM_PROMPT = """Bạn chuyển câu hỏi tìm khách hàng của RM ngân hàng thành tiêu chí JSON.

Chỉ trả về JSON, không giải thích. Các khoá được phép:
- location: chuỗi, tỉnh/thành phố
- seniority: chỉ "manager" hoặc "executive"
- products: mảng, chỉ chọn trong credit_card, mortgage, auto_loan, consumer_loan,
  savings, investment, insurance, fx, payroll
- segment: chỉ "mass", "affluent" hoặc "priority"
- require_contact: true nếu yêu cầu phải có số điện thoại hoặc email
- exclude_open_opportunity: true nếu người hỏi muốn loại người đã có cơ hội đang mở
- limit: số người cần tìm
- signal_recency_days: chỉ lấy người có tín hiệu trong bao nhiêu ngày gần đây

Quy tắc:
- BỎ QUA khoá nào không suy ra được từ câu hỏi. Đừng đoán.
- "chưa có cơ hội đang mở" -> exclude_open_opportunity true.
- "gần đây" không kèm số -> signal_recency_days 90.

Nếu có "TIÊU CHÍ TRƯỚC ĐÓ" đi kèm: đây là câu hỏi HỎI TIẾP trong cùng cuộc
trò chuyện, không phải một câu hỏi độc lập. Chỉ trả về những khoá câu hỏi mới
THAY ĐỔI hoặc THÊM MỚI — khoá nào câu hỏi mới không nhắc tới thì bỏ qua để
tiêu chí trước đó được giữ nguyên. Chỉ trả khoá muốn XOÁ nếu câu hỏi mới nói
rõ ràng (ví dụ "bỏ điều kiện có contact") — kèm giá trị rỗng/false/mảng rỗng.
"""


class ProspectQuery:
    """Kết quả bóc tách. Luôn kèm nguồn để người vận hành truy được.

    `provider`/`model` rỗng ở đường `keyword` — đúng thực tế, không có mô
    hình nào tham gia thì không có gì để ghi. Người dùng cần thấy đang chạy
    mô hình nào TRƯỚC khi tin vào tiêu chí, cùng nguyên tắc với
    `talent/hiring_need.py::HiringNeed`.
    """

    def __init__(self, question, criteria, source="keyword", error="",
                 provider="", model=""):
        self.question = question
        self.criteria = criteria
        self.source = source            # agent · llm · keyword
        self.error = error
        self.provider = provider
        self.model = model

    def as_dict(self):
        return {"question": self.question, "criteria": self.criteria,
                "criteria_from": self.source, "error": self.error,
                "provider": self.provider, "model": self.model}


# ------------------------------------------------------------- bóc tách

def parse(question, complete_fn=None, history=None):
    """Câu hỏi tự nhiên → tiêu chí. Không bao giờ ném lỗi lên trên.

    Ba đường, thử theo thứ tự, mỗi đường hỏng thì rơi xuống đường dưới:

        1. Prospect Agent trên AgentBase   (nếu đã cấu hình endpoint)
        2. LLM qua `ai/router`             (cùng mô hình, chạy tại Hub)
        3. Dò từ khoá tất định             (luôn chạy được)

    Mất AI không được biến ô tìm kiếm thành ô hỏng — cùng nguyên tắc với
    `talent/hiring_need.py`.

    `history`: danh sách tiêu chí các lượt hỏi TRƯỚC ĐÓ trong cùng cuộc trò
    chuyện (mới nhất ở cuối), dạng `[{"criteria": {...}}, ...]`. Có history
    thì đây là câu hỏi HỎI TIẾP — tiêu chí lượt trước làm nền, LLM chỉ cần nói
    THAY ĐỔI gì, không phải nhắc lại từ đầu. Không có (hoặc rỗng) thì hỏi độc
    lập, giống hệt hành vi trước khi có tính năng này.
    """
    question = str(question or "").strip()
    if not question:
        return ProspectQuery(question, _empty())

    prior = (history or [])[-1].get("criteria") if history else None
    # Tiêu chí lượt trước là nền; từ khoá dò được ở câu hỏi MỚI đè lên trên —
    # dùng lại đúng _merge() (nó vốn sinh ra để "đè có chọn lọc lên một nền").
    keyword_now = _keyword_criteria(question)
    if prior:
        # `_keyword_criteria` LUÔN có `limit` = DEFAULT_LIMIT dù câu hỏi
        # không nói số nào (nó phải vậy khi tự đứng làm kết quả cuối). Ở đây
        # nó chỉ là một LỚP ĐÈ lên tiêu chí trước — giá trị mặc định không
        # phải tín hiệu thật, không được phép ghi đè con số RM đã chốt trước
        # đó chỉ vì câu hỏi tiếp theo tình cờ không nhắc lại số lượng.
        if not re.search(r"\b\d{1,3}\b", question):
            keyword_now["limit"] = 0
        baseline = _merge(keyword_now, prior)
    else:
        baseline = keyword_now

    history_note = None
    if prior:
        history_note = {"role": "system",
                        "content": f"TIÊU CHÍ TRƯỚC ĐÓ: {json.dumps(prior, ensure_ascii=False)}"}

    if AGENT_ENDPOINT:
        parsed, agent_model, error = _ask_agent(question, prior)
        if parsed is not None:
            # Agent gọi đúng GreenNode MaaS (agent/app.py) — biết trước nhà
            # cung cấp ở đây, model thì lấy đúng cái agent báo về.
            return ProspectQuery(question, _merge(parsed, baseline), source="agent",
                                 provider="greennode", model=agent_model)
        log.warning("Agent không bóc tách được, thử LLM tại Hub: %s", error)

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
    if history_note:
        messages.append(history_note)
    messages.append({"role": "user", "content": question})

    caller = complete_fn or complete
    try:
        result = caller(messages, task=TASK, temperature=0, max_tokens=800,
                        response_format={"type": "json_object"})
    except Exception as exc:                   # noqa: BLE001 — xem docstring
        log.warning("Không bóc tách được bằng LLM, dò từ khoá thay thế: %s", exc)
        return ProspectQuery(question, baseline, error=str(exc)[:200])

    parsed = _extract_json(getattr(result, "text", ""))
    if not isinstance(parsed, dict):
        return ProspectQuery(question, baseline)
    return ProspectQuery(question, _merge(parsed, baseline), source="llm",
                         provider=result.provider, model=result.model)


def _ask_agent(question, prior_criteria=None):
    """Gọi Prospect Agent trên AgentBase. Trả `(criteria|None, model, lỗi)`."""
    import urllib.error
    import urllib.request

    body = {"action": "parse_query", "query": question}
    if prior_criteria:
        body["previous_criteria"] = prior_criteria
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{AGENT_ENDPOINT.rstrip('/')}/invocations", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=AGENT_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return None, "", str(exc)[:200]

    criteria = body.get("criteria")
    model = str(body.get("model") or "")
    if not isinstance(criteria, dict):
        return None, "", "khuôn trả về lạ"
    return criteria, model, ""


def _empty():
    return {"location": "", "seniority": "", "products": [], "segment": "",
            "require_contact": False, "exclude_open_opportunity": False,
            "limit": DEFAULT_LIMIT, "signal_recency_days": 0}


def _keyword_criteria(question):
    """Nhánh tất định. Luôn chạy, kể cả khi có LLM — nó là mốc đối chiếu."""
    text = scoring._normalize(question)
    criteria = _empty()

    for code, label in PRODUCT_CHOICES:
        if scoring._normalize(label) in text:
            criteria["products"].append(code)

    for hint, level in (("quản lý", "manager"), ("trưởng phòng", "manager"),
                        ("giám đốc", "executive"), ("chủ tịch", "executive"),
                        ("founder", "executive")):
        if scoring._normalize(hint) in text:
            criteria["seniority"] = level
            break

    for code, label in RBProfile.SEGMENT_CHOICES:
        if scoring._normalize(label) in text:
            criteria["segment"] = code
            break

    if any(word in text for word in ("co contact", "co so dien thoai", "co email",
                                     "lien he duoc")):
        criteria["require_contact"] = True
    if "chua co co hoi" in text or "chua co opportunity" in text:
        criteria["exclude_open_opportunity"] = True

    số = re.search(r"\b(\d{1,3})\b", question)
    if số:
        criteria["limit"] = min(int(số.group(1)), MAX_LIMIT)
    if "gần đây" in question.lower():
        criteria["signal_recency_days"] = 90

    return criteria


def _merge(parsed, baseline):
    """Giữ những gì mô hình hiểu đúng, vá những gì nó bịa hoặc bỏ sót.

    Đây là chốt chặn cuối cho mọi đường bóc tách — kể cả đường qua agent. Agent
    đã lọc một lần rồi, nhưng Hub không được tin một dịch vụ bên ngoài chỉ vì
    nó là dịch vụ của chính mình: một phiên bản agent cũ hơn, hoặc một endpoint
    bị trỏ nhầm, đều trả về thứ Hub không hiểu.
    """
    result = dict(baseline)

    products = [p for p in (parsed.get("products") or []) if p in VALID_PRODUCTS]
    if products:
        result["products"] = products
    if parsed.get("seniority") in VALID_SENIORITY:
        result["seniority"] = parsed["seniority"]
    if parsed.get("segment") in VALID_SEGMENTS:
        result["segment"] = parsed["segment"]

    location = str(parsed.get("location") or "").strip()
    if location:
        # Chuẩn hoá "Sài Gòn"/"TP.HCM"/"tphcm" về cùng một dạng — khác cách
        # viết không được phép làm mất người thật đang có trong kho (xem
        # core/vn_locations.py). Nhận diện được thì hiện dạng chuẩn cho RM
        # thấy hệ thống hiểu đúng chỗ nào; không thì giữ nguyên văn.
        result["location"] = canonical_province(location)[:100]

    for flag in ("require_contact", "exclude_open_opportunity"):
        if parsed.get(flag) is True:
            result[flag] = True

    try:
        limit = int(parsed.get("limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    if 0 < limit <= MAX_LIMIT:
        result["limit"] = limit

    try:
        days = int(parsed.get("signal_recency_days") or 0)
    except (TypeError, ValueError):
        days = 0
    if 0 < days <= 730:
        result["signal_recency_days"] = days

    return result


def _extract_json(raw):
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


# --------------------------------------------------------------- tìm kiếm

class ProspectList(list):
    """Danh sách kết quả, mang theo độ phủ của lần quét.

    Là `list` chứ không phải tuple `(rows, coverage)` để mọi nơi đang dùng
    `search()` như một danh sách vẫn chạy nguyên. Cùng khuôn với
    `talent/answer/judge.py::JudgeReport` — ở đó cũng cần kèm số liệu về chính
    lần chạy mà không ép người gọi phải bóc tuple.
    """

    def __init__(self, rows, *, scanned=0, truncated=False):
        super().__init__(rows)
        self.scanned = scanned
        self.truncated = truncated

    @property
    def coverage(self):
        return {"scanned": self.scanned, "truncated": self.truncated}


def search(criteria, user=None):
    """Tiêu chí → `ProspectList` đã chấm điểm và xếp hạng.

    Dùng đúng những bộ lọc mà giao diện lọc tay đang dùng — không có đường tìm
    kiếm thứ hai song song chỉ dành cho AI.

    `user` KHÔNG giới hạn phạm vi và chưa bao giờ giới hạn: RM bán lẻ nhìn được
    toàn bộ kho khách hàng, việc phân công thể hiện qua `rb_profile.sales_owner`
    chứ không phải bằng cách giấu bản ghi. Giữ tham số vì `rb/answer/` sắp tới
    cần nó thật (câu hỏi về danh mục của chính RM), nhưng ai đọc tới đây phải
    biết hôm nay nó chưa phải một ranh giới quyền.
    """
    queryset = (Person.objects.filter(merged_into__isnull=True)
                .select_related("rb_profile", "talent_profile")
                .prefetch_related("relationships"))

    if criteria.get("location"):
        # Khớp mọi cách viết của cùng một nơi ("Hồ Chí Minh" lẫn "Sài Gòn"),
        # không chỉ đúng dạng chuẩn — dữ liệu trong kho có thể được ghi bằng
        # cách viết khác (xem core/vn_locations.py).
        location_q = Q()
        for variant in location_query_variants(criteria["location"]):
            location_q |= Q(location__icontains=variant)
        queryset = queryset.filter(location_q)
    if criteria.get("segment"):
        queryset = queryset.filter(rb_profile__segment=criteria["segment"])
    if criteria.get("require_contact"):
        queryset = queryset.exclude(primary_phone="", primary_email="")
    if criteria.get("seniority"):
        hints = (scoring.SENIOR_HINTS if criteria["seniority"] == "manager"
                 else ["giám đốc", "ceo", "cfo", "cto", "founder", "chủ tịch",
                       "tổng giám đốc"])
        condition = Q()
        for hint in hints:
            condition |= Q(rb_profile__occupation__icontains=hint)
            condition |= Q(headline__icontains=hint)
            condition |= Q(talent_profile__current_title__icontains=hint)
            condition |= Q(talent_profile__seniority__icontains=hint)
        queryset = queryset.filter(condition)

    products = criteria.get("products") or []
    if products:
        product_matches = queryset.filter(rb_profile__interests__product__in=products)
        if product_matches.exists():
            queryset = product_matches

    days = criteria.get("signal_recency_days") or 0
    if days:
        since = timezone.now() - timezone.timedelta(days=days)
        queryset = queryset.filter(signals__domain=Signal.DOMAIN_RB,
                                   signals__observed_at__gte=since)

    if criteria.get("exclude_open_opportunity"):
        queryset = queryset.exclude(
            rb_opportunities__status__in=RBOpportunity.OPEN_STATUSES)

    # Khách đã bật cờ Không liên hệ không bao giờ được xuất hiện — kể cả khi RM
    # hỏi đích danh nhóm đó. Đây là ràng buộc tuân thủ, không phải bộ lọc.
    queryset = queryset.exclude(relationships__domain=Signal.DOMAIN_RB,
                                relationships__do_not_contact=True)

    limit = min(int(criteria.get("limit") or DEFAULT_LIMIT), MAX_LIMIT)
    # Chấm điểm TOÀN BỘ nhóm đã lọc, tới trần ngân sách, rồi mới cắt.
    #
    # Bản cũ lấy `order_by("-updated_at")[:limit * 3]`. Comment của nó nói lấy
    # rộng hơn `limit` để tránh "trả về nhóm được sửa gần đây nhất" — nhưng
    # `limit * 3` trên một nhóm lọc vài nghìn người vẫn đúng là lỗi đó, chỉ
    # rộng hơn ba lần: `updated_at` đo lần cuối ai đó SỬA hồ sơ, không đo khách
    # hàng đáng gọi tới mức nào. Khách phù hợp nhất mà hồ sơ lâu không ai động
    # vào thì không bao giờ lọt.
    #
    # `-updated_at` vẫn là thứ tự cắt khi chạm trần, nhưng trần nay đủ rộng để
    # phần lớn truy vấn thật không chạm tới, và khi chạm thì `truncated` nói ra
    # thay vì im lặng.
    rows = list(queryset.distinct().order_by("-updated_at")[:SCORING_BUDGET + 1])
    truncated = len(rows) > SCORING_BUDGET
    if truncated:
        rows = rows[:SCORING_BUDGET]
        log.warning("rb.prospects: nhóm lọc vượt %s người, chấm điểm trên phần "
                    "đầu — tiêu chí quá rộng", SCORING_BUDGET)

    scored = [_score(person, products) for person in rows]
    # `-priority_score` rồi `person_id`: điểm bằng nhau là chuyện thường (thang
    # điểm rời rạc), và không có khoá phụ ổn định thì cùng một câu hỏi trả về
    # thứ tự khác nhau giữa hai lần chạy.
    scored.sort(key=lambda item: (-item["priority_score"], item["person_id"]))
    return ProspectList(scored[:limit], scanned=len(rows), truncated=truncated)


def _score(person, products):
    """Chấm 5 chiều, dùng lại đúng `rb/scoring.py` — không có công thức thứ hai."""
    profile = getattr(person, "rb_profile", None)
    relationship = next((row for row in person.relationships.all()
                         if row.domain == Signal.DOMAIN_RB), None)

    product = (products[0] if products
               else _best_interest(profile) or "consumer_loan")

    tp = getattr(person, "talent_profile", None)
    fit, fit_why = scoring.score_fit(person, product, profile=profile)
    interest = _interest_for(profile, product)
    need, need_why = scoring.score_need(interest=interest)
    observed = interest.observed_at if interest is not None else None
    timing, timing_why = scoring.score_timing(observed, talent_profile=tp)
    reach, reach_why = scoring.score_reachability(person, profile=profile,
                                                  relationship=relationship)
    value, value_why, strategic = scoring.score_value(product)
    priority = scoring.priority_score(fit, need, timing, reach, value,
                                      strategic_weight=strategic)

    occupation = (getattr(profile, "occupation", "") or
                  getattr(tp, "current_title", "") or
                  person.headline or "")
    employer = (getattr(profile, "employer", "") or
                getattr(tp, "current_company", "") or "")

    return {
        "person_id": person.pk,
        "display_name": person.display_name,
        "location": person.location,
        "occupation": occupation,
        "employer": employer,
        "product": product,
        "priority_score": priority,
        "scores": {"fit": fit, "need": need, "timing": timing,
                   "reachability": reach, "value": value},
        "why": need_why + fit_why + reach_why + timing_why + value_why,
        "has_open_opportunity": any(
            row.status in RBOpportunity.OPEN_STATUSES
            for row in person.rb_opportunities.all()),
    }


def _best_interest(profile):
    if profile is None:
        return ""
    row = max(profile.interests.all(), key=lambda item: item.confidence,
              default=None)
    return row.product if row else ""


def _interest_for(profile, product):
    if profile is None:
        return None
    return next((row for row in profile.interests.all()
                 if row.product == product), None)


def run(question, user=None, complete_fn=None, history=None):
    """Toàn bộ luồng: câu hỏi → tiêu chí → người → điểm → giải thích."""
    parsed = parse(question, complete_fn=complete_fn, history=history)
    results = search(parsed.criteria, user=user)
    # `coverage` đi thẳng ra client: danh sách bị cắt vì tiêu chí quá rộng là
    # chuyện RM phải biết để thu hẹp câu hỏi, không phải chuyện giấu đi.
    return {**parsed.as_dict(), "count": len(results), "results": list(results),
            "coverage": results.coverage}
