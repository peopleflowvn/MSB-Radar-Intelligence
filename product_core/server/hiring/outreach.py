# -*- coding: utf-8 -*-
"""Soạn thư tiếp cận ứng viên (Master Plan mục 23, PHASE 9).

Nguyên tắc chi phối cả file này: **AI chỉ được nhắc lại thứ đã có trong hồ sơ.**

Thư tiếp cận là thứ đi ra ngoài, tới một người thật, mang tên MSB. Một câu bịa
("thấy anh vừa hoàn thành dự án migration ở ngân hàng X") không chỉ sai — nó làm
người nhận biết ngay là thư máy, và làm hỏng luôn thiện cảm với những lần sau.

Nên prompt được dựng từ một danh sách dữ kiện *đã kiểm chứng*, và nói thẳng với
mô hình rằng ngoài danh sách đó thì không được thêm gì. Cùng khuôn với
`talent/ai_search.py` mục 19.3: FACT thì nói, UNKNOWN thì im.
"""
import logging

from ai.router import complete

log = logging.getLogger(__name__)

TASK = "outreach_draft"

CHANNEL_EMAIL = "email"
CHANNEL_MESSAGE = "message"
CHANNELS = (CHANNEL_EMAIL, CHANNEL_MESSAGE)

SYSTEM_PROMPT = """Bạn là chuyên viên tuyển dụng của Ngân hàng MSB, viết thư tiếp cận ứng viên bằng tiếng Việt.

Quy tắc TUYỆT ĐỐI:
- CHỈ dùng những dữ kiện được liệt kê trong phần "Dữ kiện". Không thêm bất kỳ chi
  tiết nào khác về ứng viên: không đoán dự án họ làm, không đoán lý do họ muốn
  đổi việc, không khen thành tích không có trong danh sách.
- Không hứa mức lương, chức danh hay quyền lợi cụ thể nếu không được cung cấp.
- Xưng hô lịch sự, gọi bằng "anh/chị" kèm tên.

Văn phong:
- Ngắn. Người nhận đọc trên điện thoại, giữa giờ làm.
- Nói rõ NGAY vì sao liên hệ họ (dựa trên dữ kiện), rồi mới tới vị trí.
- Kết bằng một câu hỏi dễ trả lời, không phải một lời kêu gọi hành động dài dòng.
- Không dùng sáo ngữ tuyển dụng ("cơ hội không thể bỏ lỡ", "môi trường năng động").

Chỉ trả về nội dung thư, không giải thích, không thêm tiêu đề mục."""

EMAIL_HINT = ("Viết một email: dòng đầu là 'Tiêu đề: ...', "
              "sau đó là nội dung. Tối đa 150 từ.")
MESSAGE_HINT = ("Viết một tin nhắn ngắn (Zalo/LinkedIn). Không có tiêu đề. "
                "Tối đa 80 từ.")

#: Thoáng tay: hạn mức này tính cả token suy nghĩ ở một số model, và một bức thư
#: bị cắt còn tệ hơn nhiều so với vài token thừa.
MAX_TOKENS = 1200

#: Ngắn hơn mức này thì gần như chắc chắn là câu cụt, không phải thư.
MIN_CHARS = 60


def _facts(person, hiring_need=None):
    """Những gì ta THẬT SỰ biết về người này. Không có gì thì để trống."""
    profile = getattr(person, "talent_profile", None)
    facts = []

    if profile and profile.current_title:
        line = f"Chức danh hiện tại: {profile.current_title}"
        if profile.current_company:
            line += f" tại {profile.current_company}"
        facts.append(line)
    if profile and profile.years_experience is not None:
        # Bỏ ".0" — "4 năm" là cách người ta nói, "4.0 năm" là cách máy nói, và
        # khung thư này hiện thẳng ra cho recruiter đọc.
        years = profile.years_experience
        pretty = int(years) if float(years).is_integer() else years
        facts.append(f"Số năm kinh nghiệm: {pretty}")
    if profile and profile.location:
        facts.append(f"Nơi ở: {profile.location}")

    criteria = hiring_need.criteria if hiring_need else {}
    wanted = [s.lower() for s in (criteria.get("skills") or [])]
    if profile and profile.skills:
        # Chỉ nêu kỹ năng TRÙNG với yêu cầu: đó là lý do ta gọi họ, và cũng là
        # thứ khiến thư đọc như viết riêng chứ không phải gửi hàng loạt.
        overlap = [s for s in profile.skills if s.lower() in wanted]
        if overlap:
            facts.append("Kỹ năng khớp với vị trí: " + ", ".join(overlap[:6]))
        else:
            facts.append("Kỹ năng trong hồ sơ: " + ", ".join(profile.skills[:6]))

    record = person.source_records.order_by("-last_seen_at").first()
    if record and record.source:
        facts.append(f"Đã từng ứng tuyển qua {record.source}")

    return facts


def draft(person, hiring_need=None, channel=CHANNEL_MESSAGE, extra="", title=""):
    """Soạn thư tiếp cận. Trả (nội dung, lỗi).

    Không gọi được LLM thì trả khung thư điền sẵn dữ kiện — recruiter viết tiếp.
    Ô trống vẫn hơn là chặn họ lại giữa lúc đang làm việc.
    """
    facts = _facts(person, hiring_need)
    name = person.display_name or "anh/chị"
    position = title or (hiring_need.title if hiring_need else "một cơ hội phù hợp")
    department = hiring_need.department if hiring_need else ""
    hint = EMAIL_HINT if channel == CHANNEL_EMAIL else MESSAGE_HINT

    prompt = (
        f"Ứng viên: {name}\n"
        f"Vị trí / mục tiêu tiếp cận: {position}"
        + (f" ({department})" if department else "")
        + "\n\nDữ kiện:\n"
        + ("\n".join(f"- {fact}" for fact in facts) or "- (không có thêm thông tin)")
        + (f"\n\nGhi chú của trưởng bộ phận: {extra}" if extra else "")
        + f"\n\n{hint}"
    )

    try:
        result = complete(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
            task=TASK, temperature=0.7, max_tokens=MAX_TOKENS,
            # Thư tiếp cận không cần model "suy nghĩ", mà bước suy nghĩ lại ăn
            # vào chính hạn mức token của câu trả lời — xem
            # `OpenAICompatibleProvider.complete`.
            reasoning_effort="none")
    except Exception as exc:                   # noqa: BLE001 — xem docstring
        log.warning("Không soạn được thư tiếp cận: %s", exc)
        return _skeleton(name, position, facts), str(exc)[:200]

    text = result.text.strip()
    if result.truncated or len(text) < MIN_CHARS:
        # Một nửa câu tệ hơn hẳn một khung thư để ngỏ: recruiter đang vội rất dễ
        # bấm gửi luôn, và thư cụt giữa chừng gửi đi dưới tên MSB thì không rút
        # lại được.
        log.warning("Thư soạn ra bị cắt hoặc quá ngắn (%d ký tự), dùng khung thư",
                    len(text))
        return _skeleton(name, position, facts), "Thư bị cắt giữa chừng."

    return text, ""


def _skeleton(name, position, facts):
    """Khung thư khi AI bận. Cố ý để ngỏ chỗ cần người viết."""
    lines = [f"Chào anh/chị {name},", ""]
    if facts:
        lines.append("(Tham khảo hồ sơ: " + "; ".join(facts) + ")")
        lines.append("")
    lines += [
        f"Bên em tại MSB muốn trao đổi với anh/chị về {position}.",
        "",
        "[Viết thêm: vì sao anh/chị phù hợp]",
        "",
        "Anh/chị có tiện trao đổi thêm không ạ?",
    ]
    return "\n".join(lines)
