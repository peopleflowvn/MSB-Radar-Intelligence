# -*- coding: utf-8 -*-
"""RB Radar Agent (Master Plan mục 41) — một lượt "đọc và gợi ý" trọn vẹn.

Trước phase này, để biết một đoạn văn bản có đáng chú ý cho bán lẻ không, người
dùng phải tự ghép hai lời gọi: `/social/analyze/` (ý định + khớp người) rồi
`/rb/suggest/` (gợi ý sản phẩm) — không ai nối chúng lại, và không có nơi nào
nói *"khách này đã có cơ hội đang mở chưa"* trước khi tạo thêm một cơ hội trùng.

Agent này gộp cả ba câu hỏi vào một lượt, có vết (trace) theo đúng khuôn Master
Plan mục 42 — Goal / Activity / Results / Why / Actions gợi ý:

    1. detect_financial_need   — social.intent.detect
    2. resolve_person          — khớp với người đã có (không tự tạo mới)
    3. match_product           — rb.routing.suggest_products
    4. prioritize_lead         — có cơ hội nào đang mở rồi không

Trình tự bốn bước này CỐ ĐỊNH, viết bằng code — không có LLM nào chọn chạy bước
nào. Cùng ranh giới với `talent/ai_search.py`, xem `agents/runtime.py`.

**Không lưu gì.** Đây là công cụ xem trước, giống hệt lý do `social.views.analyze`
mặc định không lưu: người dùng thử bằng văn bản của người thật. Muốn lưu thật
thì đi qua `POST /api/v1/social/ingest/` hoặc `analyze(save=true)` — nơi có
`rb.routing.route_signal()` tạo `ProductInterest`/`RBOpportunity` qua đúng
đường có kiểm tra trùng lặp.
"""
import logging

from accounts import privacy
from agents import runtime as agent_runtime
from agents.models import AGENT_RB
from social import intent as intent_module
from social import pipeline as social_pipeline
from social.models import Community, SocialPost

from . import routing
from .models import PRODUCT_LABELS, RBOpportunity

log = logging.getLogger(__name__)


class AgentResult:
    def __init__(self, intent, matched_person, history_note, products,
                 existing_opportunities, trace):
        self.intent = intent
        self.matched_person = matched_person
        self.history_note = history_note
        self.products = products
        self.existing_opportunities = existing_opportunities
        self.trace = trace

    def as_dict(self):
        return {
            "intent": self.intent.as_dict(),
            "matched_person": self.matched_person.pk if self.matched_person else None,
            "matched_person_name": (self.matched_person.display_name
                                    if self.matched_person else ""),
            "history_note": self.history_note,
            "products": [
                {**p.as_dict(),
                 "product_label": PRODUCT_LABELS.get(p.product, p.product)}
                for p in self.products
            ],
            "existing_opportunities": [
                {"id": o.pk, "product": o.product,
                 "product_label": PRODUCT_LABELS.get(o.product, o.product),
                 "status": o.status, "status_label": o.get_status_display()}
                for o in self.existing_opportunities
            ],
            # "Actions" theo mục 42 — việc RM có thể làm tiếp, suy ra từ chính
            # kết quả phía trên chứ không phải một danh sách cố định.
            "suggested_actions": _suggest_actions(self),
            "trace": self.trace,
        }


def analyze(text, community_id=None, author_name="", user=None):
    """Chạy trọn vẹn Agent cho một đoạn văn bản. Trả `AgentResult`."""
    trace = []

    def step(label, detail=""):
        # `trace` đi thẳng ra client, KHÁC với bản `AgentStep` ghi xuống CSDL —
        # hai đường ra riêng, che một đường là còn đường kia. `detail` ở đây
        # hay là `result.reason`: văn model tự viết, mà prompt của
        # `social/intent.py` dặn nó *"nhắc tới chữ CỤ THỂ trong bài"*, nên bài
        # có số điện thoại thì reason rất dễ chép số ấy vào.
        trace.append({"label": privacy.redact_contacts(label),
                      "detail": privacy.redact_contacts(detail)})

    community = None
    if community_id:
        community = Community.objects.filter(pk=community_id).first()

    with agent_runtime.run(AGENT_RB, goal=text[:200], user=user) as run:
        step("Nhận diện nhu cầu tài chính")
        result = intent_module.detect(text, community=community,
                                      author_name=author_name)
        rb_score = result.score(intent_module.DOMAIN_RB)
        step(f"Điểm nhu cầu tài chính: {round(rb_score * 100)}", result.reason)

        # Dùng lại đúng logic khớp người của social/pipeline.py — không viết lại
        # lần hai, vì hai chỗ khớp khác nhau là hai chỗ có thể lệch nhau.
        step("Tìm người đã có trong kho")
        draft_post = SocialPost(content=text, author_name=author_name,
                                community=community, contacts=result.contacts)
        matched = social_pipeline._resolve_author(draft_post, result)
        person = draft_post.person if matched else None
        history_note = social_pipeline.history_note(person) if person else ""
        step("Đã khớp được người" if matched else "Chưa khớp được ai trong kho",
             history_note)

        step("Gợi ý nhóm sản phẩm")
        products = (routing.suggest_products(text, base_confidence=rb_score)
                   if rb_score > 0 else [])
        step(f"Gợi ý {len(products)} nhóm sản phẩm",
             ", ".join(PRODUCT_LABELS.get(p.product, p.product) for p in products))

        existing = []
        if person is not None and products:
            step("Kiểm tra cơ hội đang mở")
            existing = list(RBOpportunity.objects.filter(
                person=person, status__in=RBOpportunity.OPEN_STATUSES))
            step(f"{len(existing)} cơ hội đang mở cho người này")

        for item in trace:
            run.record(item["label"], detail=item.get("detail") or "")
        run.finish({"rb_score": round(rb_score, 3), "products": len(products),
                    "matched": bool(person)})

    return AgentResult(result, person, history_note, products, existing, trace)


def _suggest_actions(result):
    actions = []
    open_products = {o.product for o in result.existing_opportunities}
    new_products = [p for p in result.products if p.product not in open_products]

    if not result.matched_person:
        actions.append("Chưa khớp được khách hàng trong kho — cần thêm liên hệ "
                       "(SĐT/email) mới tạo được cơ hội.")
    elif new_products:
        names = ", ".join(PRODUCT_LABELS.get(p.product, p.product)
                          for p in new_products)
        actions.append(f"Có thể tạo cơ hội mới: {names}.")
    if result.existing_opportunities:
        names = ", ".join(PRODUCT_LABELS.get(o.product, o.product)
                          for o in result.existing_opportunities)
        actions.append(f"Đã có cơ hội đang mở: {names} — đừng tạo trùng, "
                       "vào hộp thư cơ hội để tiếp tục.")
    if not actions:
        actions.append("Chưa đủ dữ kiện để đề xuất hành động.")
    return actions
