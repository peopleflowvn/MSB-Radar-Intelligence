# -*- coding: utf-8 -*-
"""Hỏi & đáp AI có phạm vi, neo vào MỘT người cụ thể (Person 360).

Khác với AiSearch (talent) và Prospect (RB) ở chỗ đối tượng đã CHẮC CHẮN —
không cần bước tìm kiếm/xếp hạng của `search.py`/`scoring.py`. Nhưng nguyên
tắc "AI hiểu, CODE quyết" vẫn giữ ở đúng chỗ nhạy cảm nhất: CODE gom sẵn những
FACT đã có trong hồ sơ, LLM CHỈ được trả lời DỰA TRÊN các FACT đó — không đọc
hồ sơ thô, không được suy diễn thêm thu nhập, khả năng vay hay xác suất chốt.

Không có bước "xếp hạng" ở đây thì không cần một `score_person()` thứ hai — Q&A
chỉ là một cách khác để đọc cùng một sự thật đã có, không phải một nguồn sự
thật mới.
"""
import json
import logging

from ai.router import complete
from rb.models import PRODUCT_LABELS

log = logging.getLogger(__name__)

TASK = "person_qa"

MAX_HISTORY_TURNS = 6
MAX_ANSWER_CHARS = 2000

SYSTEM_PROMPT = """Bạn trả lời câu hỏi của Recruiter/RM về MỘT người cụ thể trong
Kho con người (Talent Radar / Growth Radar).

Bạn CHỈ được dùng dữ kiện trong "ho_so" của tin nhắn người dùng. TUYỆT ĐỐI
không suy diễn thêm thu nhập, khả năng vay, xác suất chốt hay bất cứ điều gì
không có trong dữ kiện đó. Dữ kiện không đủ để trả lời thì nói rõ đang thiếu
gì, không đoán.

Nếu có "LỊCH SỬ HỎI ĐÁP TRƯỚC ĐÓ" đi kèm: đây là câu hỏi tiếp theo trong cùng
cuộc trò chuyện về đúng người này — trả lời có tính tới ngữ cảnh đó, không lặp
lại nguyên văn câu trả lời trước.

Trả lời tiếng Việt, ngắn gọn (tối đa khoảng 120 từ), giọng nghiệp vụ, không
hoa mỹ. Không bịa link, số điện thoại hay email ngoài dữ kiện đã cho."""


def ask(person, question, history=None, include_recruiting=True, complete_fn=None):
    """Trả lời một câu hỏi tự do về `person`, chỉ dựa trên FACT sẵn có.

    `include_recruiting`: cổng theo vai trò, ĐÚNG NHƯ
    `talent/views.py::person_detail` đã lọc cho RM thuần (không đọc CV/pipeline
    tuyển dụng nội bộ) — Q&A không được lộ nhiều hơn những gì trang đã cho xem.

    `history`: danh sách các lượt hỏi/đáp TRƯỚC ĐÓ trong cùng cuộc trò chuyện
    về đúng người này, dạng `[{"question": "...", "answer": "..."}, ...]`.
    """
    question = str(question or "").strip()
    if not question:
        return {"answer": "", "error": "Câu hỏi trống.", "provider": "", "model": ""}

    facts = _facts(person, include_recruiting=include_recruiting)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    turns = "\n".join(
        f"H: {h.get('question', '')}\nĐ: {h.get('answer', '')}"
        for h in (history or [])[-MAX_HISTORY_TURNS:]
        if h.get("question") and h.get("answer"))
    if turns:
        messages.append({"role": "system",
                         "content": f"LỊCH SỬ HỎI ĐÁP TRƯỚC ĐÓ:\n{turns}"})
    messages.append({"role": "user", "content": json.dumps(
        {"ho_so": facts, "cau_hoi": question}, ensure_ascii=False)})

    caller = complete_fn or complete
    try:
        result = caller(messages, task=TASK, temperature=0.2, max_tokens=600)
    except Exception as exc:                    # noqa: BLE001
        # Không trả lời được thì báo lỗi rõ ràng — không có gì để lùi về, khác
        # với tìm kiếm (còn kết quả dò từ khoá để hiện).
        log.warning("Không trả lời được câu hỏi về người #%s: %s", person.pk, exc)
        return {"answer": "", "error": str(exc)[:200], "provider": "", "model": ""}

    return {"answer": str(result.text or "").strip()[:MAX_ANSWER_CHARS], "error": "",
            "provider": result.provider, "model": result.model}


def _facts(person, include_recruiting=True):
    """Gom đúng những FACT đã hiện trên Person 360 — không hơn, không kém."""
    talent = getattr(person, "talent_profile", None)
    rb_profile = getattr(person, "rb_profile", None)

    facts = {
        "ten": person.display_name or "(chưa rõ tên)",
        "khu_vuc": (talent.location if talent else "") or person.location,
        "co_email": bool(person.primary_email),
        "co_dien_thoai": bool(person.primary_phone),
    }

    # CV/pipeline tuyển dụng: đúng nhóm dữ liệu `person_detail` đã ẩn khỏi RM
    # thuần — Q&A không được biết nhiều hơn màn hình cho phép RM đọc.
    if include_recruiting and talent:
        facts["nghiep_vu_tuyen_dung"] = {
            "chuc_danh_hien_tai": talent.current_title,
            "cong_ty_hien_tai": talent.current_company,
            "so_nam_kinh_nghiem": talent.years_experience,
            "cap_bac": talent.seniority,
            "ky_nang": list(talent.skills or [])[:20],
            "nganh_da_lam": list(talent.industries or [])[:10],
            "hoc_van": talent.education,
            "muc_luong_ky_vong": talent.expected_salary,
            "tom_tat_nang_luc": talent.summary,
            "lan_cuoi_co_ho_so_moi": (
                talent.last_source_at.isoformat() if talent.last_source_at else None),
        }

    if rb_profile is not None:
        interests = list(rb_profile.interests.all())
        facts["nghiep_vu_khach_hang"] = {
            "nghe_nghiep": rb_profile.occupation,
            "don_vi_cong_tac": rb_profile.employer,
            "phan_khuc": rb_profile.segment,
            "quan_tam_san_pham": [{
                "product": item.product,
                "label": PRODUCT_LABELS.get(item.product, item.product),
                "do_tin_cay": round(item.confidence, 2),
            } for item in interests[:8]],
        }

    return facts
