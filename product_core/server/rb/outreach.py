# -*- coding: utf-8 -*-
"""Soạn lời chào theo ngữ cảnh cho một cơ hội bán lẻ (Master Plan mục 33, PHASE 13).

Bản song sinh của `hiring/outreach.py`, và giữ đúng nguyên tắc gốc: **AI chỉ
được nhắc lại thứ đã có trong hồ sơ.**

Ở đây "hồ sơ" hẹp hơn bên tuyển dụng — không có CV, chỉ có `RBOpportunity`
(sản phẩm, nhu cầu nói bằng lời khách, trích nguyên văn bài viết) và `RBProfile`
(nghề nghiệp, đơn vị công tác). Càng ít dữ kiện thì càng dễ bịa, nên quy tắc
"chỉ nói FACT" ở đây còn quan trọng hơn: một RM nhắc tới khoản vay khách chưa hề
đề cập là mất lòng tin ngay lập tức, và tệ hơn nhiều so với một tin nhắn tuyển
dụng chung chung.

Cùng ranh giới đạo đức với bên tuyển dụng: **AI soạn, người bấm gửi.** Không có
trạng thái nào ở đây khiến hệ thống tự nhắn khách hàng.
"""
import logging

from ai.router import complete

from . import routing
from .models import PRODUCT_LABELS

log = logging.getLogger(__name__)

TASK = "rb_outreach_draft"

CHANNEL_CALL_SCRIPT = "call_script"
CHANNEL_MESSAGE = "message"
CHANNELS = (CHANNEL_CALL_SCRIPT, CHANNEL_MESSAGE)

SYSTEM_PROMPT = """Bạn là chuyên viên quan hệ khách hàng cá nhân (RM) của Ngân hàng MSB, soạn nội dung tiếp cận khách hàng bằng tiếng Việt.

Quy tắc TUYỆT ĐỐI:
- CHỈ dùng những dữ kiện được liệt kê trong phần "Dữ kiện". Không suy đoán số
  tiền, mục đích cụ thể, hay hoàn cảnh tài chính nào ngoài danh sách đó.
- KHÔNG hứa lãi suất, hạn mức, hay điều khoản cụ thể — RM chốt việc đó trực tiếp.
- KHÔNG nhắc rằng thông tin đến từ việc "theo dõi mạng xã hội" hay "đọc CV" —
  nói tự nhiên như thể RM chủ động liên hệ vì MSB có chính sách/gói tài chính
  chuyên biệt dành riêng cho vị trí/ngành nghề hoặc đặc thù của khách hàng.
- Xưng hô lịch sự, gọi bằng "anh/chị" kèm tên nếu có.

Văn phong & Kỹ năng bán hàng (Sales Acumen):
- Tận dụng tinh tế chức danh, đơn vị công tác, ngoại ngữ, kỹ năng hoặc đặc thù công việc
  từ dữ kiện để mở đầu thân tình (ice-breaker) và tạo lý do tiếp cận thuyết phục.
  Ví dụ: cán bộ quản lý -> gói an cư/thẻ hạn mức cao; nhân sự công nghệ/remote -> thẻ hoàn tiền dịch vụ số/nhận lương ngoại tệ;
  người thường xuyên đi lại/công tác -> thẻ dặm bay/phí ngoại tệ ưu đãi.
- Ngắn, đi thẳng vào ĐÚNG nhu cầu hoặc cơ hội phù hợp, không giới thiệu lan man về ngân hàng.
- Kết bằng một câu hỏi dễ trả lời (xin phép gửi thông tin qua Zalo, hẹn trao đổi 2 phút hoặc giờ gọi thuận tiện).
- Không dùng sáo ngữ ("ưu đãi cực khủng", "giải pháp tối ưu đỉnh cao").

Chỉ trả về nội dung, không giải thích, không thêm tiêu đề mục."""

CALL_SCRIPT_HINT = ("Viết kịch bản mở đầu cuộc gọi: 2-3 câu để RM đọc khi khách "
                    "bắt máy. Không phải văn bản để gửi.")
MESSAGE_HINT = "Viết một tin nhắn ngắn (Zalo/SMS). Tối đa 60 từ."

#: Cùng lý do với `hiring/outreach.py`: hạn mức tính cả token suy nghĩ ở một số
#: model, và một câu bị cắt còn tệ hơn nhiều so với vài token thừa.
MAX_TOKENS = 800
MIN_CHARS = 40


def _facts(opportunity):
    """Những gì ta THẬT SỰ biết — từ cơ hội, hồ sơ bán lẻ và hồ sơ CV, không hơn."""
    facts = [f"Nhu cầu: {opportunity.need}"] if opportunity.need else []

    evidence = opportunity.evidence or {}
    excerpt = str(evidence.get("excerpt") or "").strip()
    if excerpt:
        # Trích nguyên văn, không diễn giải lại — mô hình dễ "làm rõ thêm" một
        # câu diễn giải hơn là một câu trích dẫn.
        facts.append(f"Khách từng nói: “{excerpt[:200]}”")

    profile = routing.profile_for(opportunity.person, create=False)
    if profile:
        if profile.occupation:
            line = f"Nghề nghiệp: {profile.occupation}"
            if profile.employer:
                line += f" tại {profile.employer}"
            facts.append(line)
        elif profile.employer:
            facts.append(f"Đơn vị công tác: {profile.employer}")

    # Khai thác dữ kiện phong phú từ hồ sơ nghề nghiệp & CV
    tp = getattr(opportunity.person, "talent_profile", None)
    if tp:
        title = getattr(tp, "current_title", "") or getattr(opportunity.person, "headline", "")
        company = getattr(tp, "current_company", "")
        if title and company:
            facts.append(f"Chức danh & công ty: {title} tại {company}")
        elif title:
            facts.append(f"Chức danh: {title}")
        elif company:
            facts.append(f"Đơn vị công tác: {company}")

        if tp.years_experience:
            facts.append(f"Thâm niên: {tp.years_experience} năm kinh nghiệm")
        if tp.foreign_language:
            facts.append(f"Ngoại ngữ: {tp.foreign_language}")
        if tp.job_type:
            facts.append(f"Hình thức làm việc: {tp.job_type}")
        if tp.skills and isinstance(tp.skills, list):
            skills = [str(s) for s in tp.skills[:5] if str(s).strip()]
            if skills:
                facts.append(f"Chuyên môn/kỹ năng: {', '.join(skills)}")
        if tp.marital_status:
            facts.append(f"Tình trạng hôn nhân: {tp.marital_status}")
        if tp.summary:
            facts.append(f"Đặc thù công việc & sở thích từ CV: {tp.summary[:200]}")

    return facts


def draft(opportunity, channel=CHANNEL_MESSAGE, extra=""):
    """Soạn nội dung tiếp cận cho một cơ hội. Trả (nội dung, lỗi).

    Không gọi được LLM thì trả khung để ngỏ — RM viết tiếp. Ô trống vẫn hơn là
    chặn họ lại giữa lúc đang làm việc.
    """
    facts = _facts(opportunity)
    name = opportunity.person.display_name or "anh/chị"
    product_label = PRODUCT_LABELS.get(opportunity.product, opportunity.product)
    hint = CALL_SCRIPT_HINT if channel == CHANNEL_CALL_SCRIPT else MESSAGE_HINT

    prompt = (
        f"Khách hàng: {name}\n"
        f"Sản phẩm phù hợp: {product_label}\n\nDữ kiện:\n"
        + ("\n".join(f"- {fact}" for fact in facts) or "- (không có thêm thông tin)")
        + (f"\n\nGhi chú: {extra}" if extra else "")
        + f"\n\n{hint}"
    )

    try:
        result = complete(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            task=TASK, temperature=0.7, max_tokens=MAX_TOKENS,
            reasoning_effort="none")
    except Exception as exc:                   # noqa: BLE001 — xem docstring
        log.warning("Không soạn được lời chào bán lẻ: %s", exc)
        return _skeleton(name, product_label, facts), str(exc)[:200]

    text = result.text.strip()
    if result.truncated or len(text) < MIN_CHARS:
        # Cùng lý do với bên tuyển dụng: một nửa câu gửi đi dưới tên MSB tới
        # khách hàng thì không rút lại được, và RM đang bận rất dễ bấm gửi luôn.
        log.warning("Nội dung soạn ra bị cắt hoặc quá ngắn (%d ký tự), dùng khung",
                    len(text))
        return _skeleton(name, product_label, facts), "Nội dung bị cắt giữa chừng."

    return text, ""


def _skeleton(name, product_label, facts):
    """Khung nội dung khi AI bận. Cố ý để ngỏ chỗ cần người viết."""
    lines = [f"Chào anh/chị {name},", ""]
    if facts:
        lines.append("(Tham khảo: " + "; ".join(facts) + ")")
        lines.append("")
    lines += [
        f"Em bên MSB, thấy anh/chị có thể quan tâm tới {product_label.lower()}.",
        "",
        "[Viết thêm: lý do cụ thể liên hệ]",
        "",
        "Anh/chị có tiện trao đổi thêm không ạ?",
    ]
    return "\n".join(lines)
