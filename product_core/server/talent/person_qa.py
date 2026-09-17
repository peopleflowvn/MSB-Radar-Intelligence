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

from accounts import privacy
from ai.router import complete
from people.models import Document
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

Trường "trich_cv_moi_nhat" (nếu có) là NGUYÊN VĂN CV mới nhất của người này —
dùng nó để trả lời những câu hỏi về chi tiết cụ thể (dự án, mốc thời gian, kỹ
năng nêu trong CV...) mà các trường tóm tắt phía trên không có sẵn.

"quan_he" là quan hệ chăm sóc (ghi chú, lần liên hệ gần nhất, việc cần làm
tiếp) — dùng để trả lời "đã liên hệ chưa", "ghi chú gì", "bước tiếp theo là
gì". "tin_hieu_gan_day" là hành vi/thay đổi hệ thống phát hiện được.
"dong_thoi_gian_gan_day" là các sự kiện gần đây nhất liên quan tới người này —
dùng cho câu hỏi kiểu "gần đây có gì mới".

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


#: Đủ cho gần trọn một CV thường (~1-2 trang chữ); dài hơn thì cắt — Q&A trả lời
#: TỰ DO trên một CV, không phải xếp hạng nhiều CV như `answer/retrieve.py`
#: (nơi đoạn trích chỉ cần 700 ký tự vì có nhiều ứng viên cùng lúc).
CV_EXCERPT_CHARS = 6000


def _cv_excerpt(person):
    """Nguyên văn CV MỚI NHẤT đã che liên hệ — cùng chính sách với AiSearch.

    Đây là khác biệt chính giữa Q&A theo người và trước đây: trước chỉ có vài
    trường đã curate (`current_title`, `skills`...), nên hỏi thứ chỉ nằm trong
    câu chữ CV (một dự án cụ thể, một chi tiết học vấn...) thì không trả lời
    được, dù AiSearch đọc thẳng CV nên trả lời được. Chỉ lấy MỘT bản mới nhất:
    Q&A trả lời "hiện tại", không đối chiếu nhiều phiên bản như trang tài liệu.
    """
    doc = (Document.objects.filter(person=person, parse_status=Document.PARSE_DONE)
           .order_by("-observed_at", "-created_at").first())
    body = doc.best_text if doc else ""
    if not body:
        return ""
    return privacy.redact_contacts(" ".join(body.split())[:CV_EXCERPT_CHARS])


#: Trang Person 360 không lọc `relationships`/`signals` cho RM thuần (chỉ
#: `documents`, `sources`, `timeline`, `pools` — xem `views.py::person_detail`),
#: nên Q&A cũng KHÔNG lọc hai mục này theo `include_recruiting`, giữ đúng những
#: gì màn hình đang cho xem.
RELATIONSHIP_LIMIT = 5
SIGNAL_LIMIT = 5


def _relationship_facts(person):
    """Quan hệ chăm sóc (ghi chú, lần liên hệ gần nhất, việc cần làm tiếp).

    `ghi_chu`/`ly_do` là văn bản tự do người dùng gõ tay — có thể lẫn số điện
    thoại/email, nên che như mọi đoạn bằng chứng khác (`accounts.privacy`).
    """
    rows = list(person.relationships.all()[:RELATIONSHIP_LIMIT])
    return [{
        "linh_vuc": r.domain,
        "trang_thai": r.state,
        "ghi_chu": privacy.redact_contacts(r.notes) if r.notes else "",
        "ly_do": privacy.redact_contacts(r.reason) if r.reason else "",
        "lan_lien_he_cuoi": r.last_contact_at.isoformat() if r.last_contact_at else None,
        "viec_can_lam_tiep": r.next_action,
        "han_viec_tiep": r.next_action_at.isoformat() if r.next_action_at else None,
        "muc_do_quan_tam": r.interest_level,
        "khong_duoc_lien_he": r.do_not_contact,
    } for r in rows]


def _signal_facts(person):
    """Vài tín hiệu (hành vi/thay đổi hệ thống phát hiện) gần nhất."""
    rows = list(person.signals.all()[:SIGNAL_LIMIT])
    return [{
        "loai": s.signal_type,
        "linh_vuc": s.domain,
        "do_tin_cay": round(s.confidence, 2) if s.confidence is not None else None,
        "trang_thai": s.status,
        "thoi_diem": s.observed_at.isoformat() if s.observed_at else None,
    } for s in rows]


#: Đủ để trả lời "gần đây có gì mới" mà không đốt token mỗi câu hỏi — khác
#: `PersonDetailSerializer.get_timeline` (100 dòng) vốn là dữ liệu cho MẮT
#: người đọc lướt, không phải trả tiền LLM đọc lại mỗi lượt hỏi.
TIMELINE_FACTS_EVENTS = 10


def _timeline_events(person):
    """Y HỆT `PersonDetailSerializer.get_timeline` (talent/serializers.py):
    tương tác + tín hiệu gộp, mới nhất trước. Không import từ đó để tránh vòng
    phụ thuộc serializer→person_qa; hai bản phải sửa CÙNG NHAU nếu đổi luật gộp.
    """
    events = []
    for row in person.interactions.all()[:100]:
        events.append({"kind": "interaction", "at": row.occurred_at,
                       "action": row.action, "actor": row.actor_name,
                       "detail": row.detail})
    for row in person.signals.all()[:100]:
        events.append({"kind": "signal", "at": row.observed_at,
                       "action": row.signal_type, "actor": row.source,
                       "detail": {"confidence": row.confidence}})
    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return events[:100]


def _timeline_facts(person, include_recruiting=True):
    """Vài sự kiện gần nhất, lọc theo `include_recruiting` — luật lọc Y HỆT
    nhánh `rm_only` của `views.py::person_detail`, chép tay vì đó là code trong
    view chứ không phải hàm dùng chung được.
    """
    events = _timeline_events(person)
    if not include_recruiting:
        events = [e for e in events
                 if (e.get("detail") or {}).get("domain") == "rb"
                 or str(e.get("action", "")).startswith("rb_")]
    out = []
    for e in events[:TIMELINE_FACTS_EVENTS]:
        at = e.get("at")
        out.append({"luc": at.isoformat() if at else None,
                    "hanh_dong": e.get("action", ""),
                    "nguoi_thuc_hien": e.get("actor", "")})
    return out


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
            "trich_cv_moi_nhat": _cv_excerpt(person) or None,
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

    relationships = _relationship_facts(person)
    if relationships:
        facts["quan_he"] = relationships

    signals = _signal_facts(person)
    if signals:
        facts["tin_hieu_gan_day"] = signals

    timeline = _timeline_facts(person, include_recruiting=include_recruiting)
    if timeline:
        facts["dong_thoi_gian_gan_day"] = timeline

    return facts
