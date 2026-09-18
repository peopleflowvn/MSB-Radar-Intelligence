# -*- coding: utf-8 -*-
"""⑤ Viết câu trả lời có trích dẫn [n] + hành động tiếp theo cho từng khách.

## Hành động do CODE chọn, LLM chỉ viết lời

Đây là ranh giới quan trọng nhất của chặng này, và nó lặp lại đúng nguyên tắc
của `rb/scoring.py::recommend_action`: *chọn sai hành động là chuyện nghiệp vụ,
không phải chuyện ngôn ngữ.* Nên:

* `next_action_for()` tính mã hành động (GỌI NGAY / MỜI GẶP / KÍCH HOẠT LẠI /
  XIN THÔNG TIN / CHỜ…) bằng CODE, từ điểm năm chiều + trạng thái liên hệ + cơ
  hội đang mở + kết quả tiếp cận trước.
* Mã đó đi vào payload như một DỮ KIỆN. Prompt cấm model đổi nó.
* Model viết lời giải thích quanh hành động đã chốt.

Để model tự chọn hành động thì một khách không có số điện thoại vẫn có thể được
đề xuất "gọi ngay" — một câu nghe rất hợp lý và hoàn toàn không làm được.

## Vì sao câu trả lời Growth ngắn hơn Talent

RM đọc câu trả lời giữa hai cuộc gọi, trên điện thoại. Mỗi khách: một dòng ai,
một dòng vì sao (có trích dẫn), một dòng làm gì. Không có đoạn phân tích dài —
đoạn phân tích dài là thứ bên Talent cần vì nhà tuyển dụng đang cân nhắc giữa
các hồ sơ; RM thì đang quyết định gọi ai trước.
"""
from __future__ import annotations

import json
import logging
import re

from ai.persona import stable_system
from ai.router import complete

log = logging.getLogger(__name__)

TASK = "rb_prospect_search"

#: Độ dài đoạn trích hiển thị trong thẻ nguồn.
SNIPPET_CHARS = 320

ACTION_LABELS = {
    "CALL_NOW": "Gọi ngay",
    "SEND_MESSAGE": "Nhắn tin",
    "ASK_FOR_INFORMATION": "Xin thêm thông tin liên hệ",
    "FOLLOW_UP": "Theo dõi cơ hội đang mở",
    "WAIT": "Chờ thêm tín hiệu",
    "REACTIVATE": "Kích hoạt lại",
    "INVITE_MEETING": "Mời gặp tư vấn",
    "CLOSE": "Đóng",
}

SYSTEM = """Bạn viết câu trả lời cho chuyên viên quan hệ khách hàng (RM) của MSB.

Bạn nhận một payload JSON gồm: câu hỏi của RM, danh sách khách hàng ĐÃ CHỐT (đã
sắp theo mức đáng ưu tiên), nguồn [n] đã kiểm chứng, và số liệu phạm vi đã xét.

Viết bằng tiếng Việt, NGẮN — RM đọc giữa hai cuộc gọi, trên điện thoại.

Quy tắc bắt buộc:

1. **Giữ đúng thứ tự** khách hàng trong "khach_hang". Thứ tự đó đã được tính theo
   mức đáng ưu tiên; đảo lại là trả lời sai câu hỏi "gọi ai trước".

2. **Không kể nhiều hơn** số khách trong "khach_hang".

3. Định dạng cho TỪNG khách hàng theo thứ tự 1, 2, 3... tăng dần (TUYỆT ĐỐI không lặp lại số 1 cho mọi khách hàng):
   **<Thứ tự 1, 2, 3...>. [Tên khách hàng] — [Sản phẩm phù hợp / Combo bán chéo]**
   - **Vì sao**: điều CỤ THỂ đọc được trong bằng chứng, kèm trích dẫn [n] ngay
     sau nhận định. Nói rõ bằng chứng cách đây bao lâu nếu nó quan trọng.
   - **Nên làm**: dùng ĐÚNG "hanh_dong" đã cho. TUYỆT ĐỐI không đổi hành động,
     không tự đề xuất hành động khác — hành động đã được tính từ trạng thái liên
     hệ và lịch sử tiếp cận mà bạn không nhìn thấy đầy đủ.

3b. Nếu RM hỏi RIÊNG vì sao MỘT khách được ưu tiên cao/thấp hơn người khác
    (không phải câu hỏi liệt kê cả danh sách): dùng ĐÚNG "ly_do" trong
    "diem_thanh_phan" của khách đó — đây là lý do CSDL đã tính điểm (nghề
    nghiệp, phân khúc, kênh liên hệ, độ mới của tín hiệu…), tách bạch năm
    chiều phu_hop/nhu_cau/thoi_diem/de_tiep_can/gia_tri. Lý do này đến từ hồ
    sơ có cấu trúc, KHÔNG phải trích CV/bài đăng, nên KHÔNG cần [n]. Không tự
    bịa lý do khác ngoài "ly_do" đã cho, và không đổi con số điểm.

4. **Mỗi khẳng định về một khách phải có [n]**, và [n] phải là nguồn CỦA CHÍNH
   khách đó. Không có nguồn thì không khẳng định.

4b. Nếu "can_xac_minh_them" = true: đây là SUY LUẬN có căn cứ từ hồ sơ CV nghề nghiệp
    (vị trí, thâm niên, chuyên môn, thu nhập). Trình bày rõ góc tiếp cận theo cơ hội
    tài chính phù hợp (ví dụ: "Tiềm năng tiếp cận gói an cư dựa trên thâm niên và thu nhập tích luỹ ổn định")
    — không dùng từ ngữ rụt rè gây nghi ngờ cơ hội bán hàng.

5. **Không bịa**: không đoán thu nhập, tài sản, tình trạng hôn nhân, hay bất cứ
   điều gì không có trong bằng chứng. Không viết số điện thoại hay email.

6. Nếu "pham_vi" cho thấy có khách bị loại vì đã từ chối trước đó
   ("da_loai_vi_tu_choi" > 0), nói ngắn gọn một câu ở cuối — RM cần biết danh
   sách ngắn là có lý do.

7. Nếu "khach_hang" rỗng: nói thật là chưa tìm thấy, nói rõ đã xét bao nhiêu hồ
   sơ, và gợi ý MỘT cách hỏi lại cụ thể. Không xin lỗi dài dòng.

8. Nếu có khối "SỐ LIỆU ... (truy vấn CSDL, CHÍNH XÁC)": đây là câu hỏi TỔNG
   HỢP. Mọi con số về quy mô, tỷ lệ, phân bố PHẢI lấy từ khối đó và nói kèm mẫu
   số. Danh sách "khach_hang" chỉ là VÍ DỤ minh hoạ — TUYỆT ĐỐI không đếm nó rồi
   trình bày như số liệu toàn kho.
"""


def next_action_for(judgement, *, person_cache=None):
    """Mã hành động tiếp theo — CODE chọn, qua `rb/scoring.py::recommend_action`.

    Đọc điểm từng chiều mà ④ đã tính và gắn vào `judgement.criteria`; không tính
    lại. Chỉ tra thêm ba sự thật nhị phân mà điểm số không thay được: có kênh
    liên hệ không, có cơ hội đang mở không, và lần tiếp cận trước kết thúc ra
    sao.
    """
    from people.models import Person
    from .. import scoring
    from ..models import OpportunityOutcome, RBOpportunity

    cache = person_cache if person_cache is not None else {}
    person = cache.get(judgement.person_id)
    if person is None:
        person = Person.objects.filter(pk=judgement.person_id).first()
        cache[judgement.person_id] = person
    if person is None:
        return "WAIT"

    detail = (judgement.criteria or [{}])[0]
    dimensions = detail.get("dimensions") or {}
    product = detail.get("product") or ""

    has_contact = bool(person.primary_phone or person.primary_email)
    has_open = RBOpportunity.objects.filter(
        person=person, status__in=RBOpportunity.OPEN_STATUSES).exists()
    outcomes = OpportunityOutcome.objects.filter(person=person)
    if product:
        outcomes = outcomes.filter(opportunity__product=product)
    last = outcomes.order_by("-created_at").values_list("outcome", flat=True).first()

    return scoring.recommend_action(
        {"reachability": dimensions.get("reachability", 0),
         "need": dimensions.get("need", 0),
         "timing": dimensions.get("timing", 0),
         "priority": detail.get("priority_score", 0)},
        has_contact=has_contact, has_open_opportunity=has_open,
        previous_outcome=last or "")


def build_sources(chosen):
    """Đánh số các trích dẫn đã kiểm chứng → nguồn `[n]` dùng chung cho văn bản và UI.

    Khuôn mỗi nguồn giữ các khoá `n`, `person_id`, `name` mà
    `core/answer/verify.py::citation_audit` đọc — đó là hợp đồng dùng chung.
    """
    sources = []
    for judgement in chosen:
        for item in (judgement.evidence or []):
            sources.append({
                "n": len(sources) + 1,
                "person_id": judgement.person_id,
                "name": judgement.name,
                "source": item.get("source", ""),
                "ref": item.get("ref", ""),
                "url": item.get("url", ""),
                "age_days": item.get("age_days"),
                "snippet": str(item.get("quote") or "")[:SNIPPET_CHARS],
            })
    return sources


def build_payload(query_plan, chosen, near_misses, stats, sources, *, actions=None):
    actions = actions or {}
    by_person = {}
    for source in sources:
        by_person.setdefault(source["person_id"], []).append(source["n"])

    customers = []
    for judgement in chosen:
        detail = (judgement.criteria or [{}])[0]
        code = actions.get(judgement.person_id, "WAIT")
        dims = detail.get("dimensions") or {}
        customers.append({
            "ten": judgement.name,
            "san_pham": detail.get("product", ""),
            "diem_uu_tien": detail.get("priority_score", 0.0),
            "vi_sao": judgement.why,
            # "suy_luan" = ③ suy ra từ nghề nghiệp/hồ sơ, KHÔNG phải bằng chứng
            # trực tiếp nói thẳng nhu cầu — ⑤ phải nói rõ để RM tự thẩm định
            # lại trước khi tiếp cận, không trình bày như một sự thật đã chốt.
            "can_xac_minh_them": judgement.evidence_kind == "suy_luan",
            "nhu_cau_hay_trang_thai": judgement.need_kind,
            "bang_chung_moi_nhat_cach_day_ngay": judgement.freshest_days,
            "nguon": by_person.get(judgement.person_id, []),
            "hanh_dong": {"ma": code, "nhan": ACTION_LABELS.get(code, code)},
            # ④ đã tính năm chiều này (`rb/scoring.py`) nhưng trước đây chỉ
            # `diem_uu_tien` (con số gộp) tới được ⑤ — RM hỏi "vì sao ưu tiên
            # khách này" thì model không có gì để trả lời ngoài đoán. Đưa cả
            # điểm từng chiều lẫn lý do bằng chữ (xem quy tắc 3b) sang đây.
            "diem_thanh_phan": {
                "phu_hop": round(dims.get("fit", 0.0), 1),
                "nhu_cau": round(dims.get("need", 0.0), 1),
                "thoi_diem": round(dims.get("timing", 0.0), 1),
                "de_tiep_can": round(dims.get("reachability", 0.0), 1),
                "gia_tri": round(dims.get("value", 0.0), 1),
                "ly_do": list(detail.get("why") or []),
            },
        })
    return {
        "cau_hoi": getattr(query_plan, "information_need", ""),
        "khach_hang": customers,
        "nguon": [{"n": s["n"], "cua": s["name"], "loai": s["source"],
                   "cach_day_ngay": s["age_days"], "noi_dung": s["snippet"]}
                  for s in sources],
        "gan_dung": [{"ten": r.name, "vi_sao": r.why} for r in near_misses[:3]],
        "pham_vi": {
            "da_xet": stats.get("judged", 0),
            "thoa": stats.get("relevant", 0),
            "hien_thi": stats.get("shown", 0),
            "da_loai_vi_tu_choi": stats.get("declined_filtered", 0),
            "sap_theo": (stats.get("sorted_by") or {}).get("key", ""),
            "doc_hong": bool(stats.get("read_failed")),
        },
    }


def build_messages(query_plan, chosen, near_misses, stats, sources, *,
                   user=None, history=None, actions=None, memories=None, corpus_facts=""):
    payload = build_payload(query_plan, chosen, near_misses, stats, sources,
                            actions=actions)
    messages = [
        {"role": "system", "content": stable_system("prospect", user) + "\n\n" + SYSTEM},
    ]
    remembered = [str(m)[:300] for m in list(memories or [])[:8]]
    if remembered:
        # Điều RM đã chủ động bảo Radar nhớ ("tôi chỉ phụ trách khu Cầu Giấy").
        # `projection` đã lọc prompt-injection trước khi tới đây.
        messages.append({"role": "system", "content":
                         "RM ĐÃ DẶN (tôn trọng khi trình bày, không bịa thêm):\n"
                         + "\n".join(f"- {m}" for m in remembered)})
    if corpus_facts:
        messages.append({"role": "system", "content": corpus_facts})
    if history:
        lines = []
        for turn in list(history)[-4:]:
            question = str((turn or {}).get("question") or "")[:200]
            if question:
                lines.append(f"- {question}")
        if lines:
            messages.append({"role": "system",
                             "content": "CÁC LƯỢT HỎI GẦN ĐÂY:\n" + "\n".join(lines)})
    messages.append({"role": "user",
                     "content": json.dumps(payload, ensure_ascii=False)})
    return messages


def used_sources(text, sources):
    """Chỉ giữ nguồn thật sự được trích trong bài — thẻ nguồn không được thừa."""
    cited = {int(n) for group in re.findall(r"\[([\d,\s]+)\]", str(text or ""))
             for n in re.findall(r"\d+", group)}
    return [s for s in sources if s["n"] in cited]


def deterministic_text(query_plan, chosen, stats, *, actions=None):
    """Câu trả lời KHÔNG cần LLM — khi LLM chết, hoặc khi không có gì để viết.

    Không bao giờ là "tôi không trả lời được": dữ liệu đã có trong tay thì phải
    trình bày được, dù kém trau chuốt hơn.
    """
    actions = actions or {}
    judged = stats.get("judged", 0)

    if stats.get("read_failed"):
        return (f"Đã tìm được {stats.get('retrieved', judged)} hồ sơ liên quan nhưng "
                "chưa đọc được bằng chứng lúc này (dịch vụ AI đang gián đoạn). "
                "Anh/chị thử lại sau ít phút — đây KHÔNG phải kết luận là không có "
                "khách phù hợp.")

    if not chosen:
        declined = stats.get("declined_filtered", 0)
        note = (f" Có {declined} khách phù hợp nhưng đã loại vì từng từ chối sản "
                "phẩm này." if declined else "")
        return (f"Chưa tìm thấy khách hàng phù hợp sau khi xét {judged} hồ sơ.{note} "
                "Anh/chị thử nêu cụ thể hơn nhóm sản phẩm hoặc khu vực.")

    lines = [f"Tìm thấy {len(chosen)} khách hàng, xếp theo mức đáng ưu tiên:"]
    number = 0
    for index, judgement in enumerate(chosen, start=1):
        detail = (judgement.criteria or [{}])[0]
        refs = []
        for _item in judgement.evidence or []:
            number += 1
            refs.append(f"[{number}]")
        code = actions.get(judgement.person_id, "WAIT")
        product = detail.get("product", "")
        lines.append(
            f"\n{index}. **{judgement.name}**"
            f"{' — ' + product if product else ''}\n"
            f"   {judgement.why} {' '.join(refs)}\n"
            f"   → {ACTION_LABELS.get(code, code)}")
    declined = stats.get("declined_filtered", 0)
    if declined:
        lines.append(f"\n({declined} khách phù hợp đã được loại vì từng từ chối.)")
    return "\n".join(lines)


def compose(query_plan, chosen, near_misses, stats, *, user=None, history=None,
            complete_fn=None, actions=None):
    """Trả `(text, sources, provider, model, messages)`."""
    sources = build_sources(chosen)
    if not chosen or stats.get("read_failed"):
        return (deterministic_text(query_plan, chosen, stats, actions=actions),
                sources, "", "", None)

    messages = build_messages(query_plan, chosen, near_misses, stats, sources,
                              user=user, history=history, actions=actions)
    caller = complete_fn or complete
    try:
        result = caller(messages, task=TASK, temperature=0.3, max_tokens=2500)
    except Exception as exc:                       # noqa: BLE001
        log.warning("rb.answer.compose: LLM lỗi, dùng văn bản tất định: %s", exc)
        return (deterministic_text(query_plan, chosen, stats, actions=actions),
                sources, "", "", None)
    text = str(getattr(result, "text", "") or "").strip()
    if not text:
        return (deterministic_text(query_plan, chosen, stats, actions=actions),
                sources, "", "", None)
    return (text, sources, getattr(result, "provider", ""),
            getattr(result, "model", ""), messages)
