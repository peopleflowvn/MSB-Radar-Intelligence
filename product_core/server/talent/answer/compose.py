# -*- coding: utf-8 -*-
"""⑤ Viết câu trả lời — phần "Nói".

Model ở đây **không tìm, không xếp hạng, không đếm**. Bốn chặng trước đã chốt ai
vào danh sách, theo thứ tự nào, kèm trích dẫn đã đối chiếu với văn bản gốc. Việc
duy nhất còn lại là diễn đạt cho đúng, cho thuyết phục, và dẫn nguồn.

Tách bạch như vậy là có chủ ý: mọi lỗi "nói hay nhưng sai" trước đây đều đến từ
chỗ để model vừa chọn người vừa viết trong một lượt.

Đánh số nguồn `[n]` ở đây là **một trích dẫn đã kiểm chứng**, không phải một
đoạn thô — nhấp vào là mở đúng chỗ trong CV gốc.
"""
from __future__ import annotations

import logging
import re

from ai.conversation import extract_thinking
from ai.prompt_guard import GUARD_RULE
from ai.router import complete

log = logging.getLogger(__name__)

TASK = "talent_answer_compose"

#: Ngân sách token cho một lượt viết.
#:
#: Phải cộng cả phần SUY NGHĨ: ⑤ chạy `deepseek-v4-pro`, là model có bước suy
#: nghĩ, và `providers.py` tước `reasoning_effort` của mọi model `deepseek/*`
#: (chúng trả HTTP 400 khi thấy nó). Ở mức 1600, phần suy nghĩ ăn gần hết và câu
#: trả lời bị cắt GIỮA CHỮ — đo trên kho thật: "Kho có 6 ứng viên đ".
MAX_TOKENS = 4000
#: Thử lại một lần với ngân sách này khi vẫn bị cắt.
RETRY_MAX_TOKENS = 7000
#: Ngân sách cho đường STREAM — cao ngay từ đầu, bằng mức retry.
#:
#: Đường `complete` bị cắt thì gọi lại được. Đường stream thì KHÔNG: chữ đã phát
#: ra màn hình rồi, gọi lại nghĩa là viết đè lên thứ người dùng đang đọc. Nên ở
#: đây phải phòng, không thể chữa.
#:
#: `max_tokens` là TRẦN chứ không phải mức tiêu thụ — đặt cao không tốn thêm gì
#: khi model viết ngắn. Đo trên production: câu "tổng quan về kho ứng viên" bị
#: cắt ở mức 4000 và người dùng nhận một câu đứt giữa chừng.
STREAM_MAX_TOKENS = RETRY_MAX_TOKENS
SNIPPET_CHARS = 320

SYSTEM = """Bạn là Radar — trợ lý tuyển dụng của MSB. Bạn đang trả lời một đồng
nghiệp về Kho con người (hồ sơ ứng viên + CV đã bóc tách).

Hệ thống ĐÃ tìm, ĐÃ sàng và ĐÃ xếp thứ tự giúp bạn. Danh sách trong "ket_qua" là
danh sách cuối cùng: đúng người, đúng thứ tự, đúng số lượng. Việc của bạn là
VIẾT, không phải chọn lại.

Mọi phản hồi cuối cùng cho người dùng phải do bạn viết, kể cả câu đếm hoặc câu
thống kê. Khi có "so_lieu_chinh_xac", dùng nguyên các số đó; không tự tính lại,
không đổi số và không biến số hồ sơ đọc sâu thành kích thước toàn kho.

TUYỆT ĐỐI:
- Không thêm người nào ngoài "ket_qua". Không đổi thứ tự. Không cắt bớt.
- Không nêu thông tin không có trong "bang_chung" của chính người đó.
- Không suy diễn thu nhập, khả năng vay, sức khoẻ, hay dữ liệu nhạy cảm.
- Mọi khẳng định về một người phải kèm [n] — số hiệu nguồn của người đó.
- KHÔNG viết ra email hay số điện thoại, kể cả khi đoạn nguồn có. Ai hỏi liên
  hệ thì chỉ họ dùng chức năng "mở khoá liên hệ" trên hồ sơ.

CÁCH VIẾT:
1. Câu đầu trả lời thẳng câu hỏi (có bao nhiêu người, ai đứng đầu, kết luận là
   gì). Không mở bài, không "dựa trên dữ liệu hiện có tôi thấy rằng".
2. Sau đó trình bày từng người bằng VĂN XUÔI hoặc gạch đầu dòng rõ: tên, mức độ
   phù hợp, bằng chứng gắn với từng điều kiện, điểm mạnh khác biệt và khoảng
   trống/rủi ro cần xác minh, kèm [n]. Không lặp nhận xét chung chung.
3. Nếu "sap_xep" có giá trị, nói rõ đang xếp theo tiêu chí gì và nêu con số của
   từng người (ví dụ năm sinh) để người đọc kiểm chứng được thứ tự.
4. Nếu "thieu_du_lieu" > 0, nói thẳng có bao nhiêu người không xác định được
   tiêu chí sắp xếp và họ đứng cuối vì lý do đó.
5. Nếu "gan_dung" có người, thêm một câu cuối gợi ý họ và nêu họ thiếu gì.
6. Nếu "ket_qua" rỗng VÀ "nguoi_da_xac_dinh" cũng rỗng: nói thẳng kho không có
   ai thoả và đề xuất cách nới điều kiện. Không xin lỗi dài dòng, không bịa.
   VỀ CON SỐ: "da_ra_soat" là số hồ sơ hệ thống đọc kỹ trong lượt này, KHÔNG
   phải cỡ kho. Cỡ kho là "kho_co". Luôn nói theo kiểu "đã đọc sâu {da_ra_soat}
   hồ sơ tiềm năng nhất theo xếp hạng hybrid trên dữ liệu có thể tìm kiếm trong
   toàn bộ {kho_co} hồ sơ" — TUYỆT ĐỐI không để con số
   {da_ra_soat} đứng một mình như thể đó là tất cả những gì kho có.
   NGOẠI LỆ: nếu phía trên có khối "SỐ LIỆU THẬT VỀ KHO" thì đây là câu hỏi
   THỐNG KÊ, không phải câu tìm người — trả lời thẳng bằng những con số đó,
   TUYỆT ĐỐI không nói "kho không có ai". Nêu kèm độ phủ khi số liệu có ghi
   (ví dụ "có ở 210/786 hồ sơ"), và nói rõ phần nào chưa đủ dữ liệu để kết luận.
6c. Nếu "tra_theo_ten" là true: người dùng hỏi về một/vài người ĐÍCH DANH. Đừng
   viết "đã rà N hồ sơ" — hệ thống tra thẳng theo tên. "ket_qua" rỗng thì nói
   "trong kho không có hồ sơ nào tên …"; có thì trả lời thẳng về đúng người đó.
6d. Nếu "nguoi_da_xac_dinh" có dữ liệu: đây là đúng hồ sơ được hỏi nhưng thuộc
   tính cần tìm có thể còn thiếu. Nêu đầy đủ các dữ kiện FACT đọc được, dẫn [n]
   ngay sau dữ kiện, rồi nói chính xác phần nào chưa có. Không biến thiếu một
   thuộc tính thành câu trả lời chung chung rằng toàn bộ hồ sơ không đủ dữ liệu.
6b. Nếu "loi_doc_ho_so" là true: hệ thống ĐÃ TÌM THẤY hồ sơ nhưng bước đọc bị
   lỗi. TUYỆT ĐỐI không nói "kho không có ai" — phải nói rõ là lỗi kỹ thuật khi
   đọc hồ sơ, nêu số hồ sơ đã tìm được, và mời người dùng thử lại.
7. Kết thúc bằng MỘT câu hỏi ngược ngắn giúp thu hẹp tiếp — chỉ khi thật sự hữu ích.
8. Nếu "viec_cua_buoc_sau" KHÔNG rỗng: đó là việc hệ thống sẽ làm ngay sau bạn.
   TUYỆT ĐỐI không tự làm những việc đó (đừng soạn thư, đừng so sánh) và cũng
   đừng hứa sẽ làm. Chỉ trả lời phần việc của bạn rồi dừng — phần kia sẽ được
   nối vào ngay bên dưới.

Giọng: đồng nghiệp giỏi nghề, nói thẳng, có phân tích và thuyết phục nhưng trung
thực về giới hạn dữ liệu. Hiểu câu hỏi trong mạch hội thoại, không trả lời lại
từ đầu nếu người dùng đang hỏi tiếp. Tiếng Việt. Không emoji. Ưu tiên cấu trúc
dễ đọc; tối đa khoảng 100 từ mỗi người và 700 từ toàn bài, trừ khi người dùng
yêu cầu ngắn hơn.""" + "\n\n" + GUARD_RULE


def build_sources(chosen):
    """Đánh số các trích dẫn đã kiểm chứng → nguồn `[n]` dùng chung cho văn bản và UI."""
    missing_ids = [row.person_id for row in chosen if not row.evidence]
    fallback_evidence = {}
    if missing_ids:
        from people.models import Document
        from .retrieve import clean_passage
        for document in (Document.objects.filter(person_id__in=missing_ids,
                                                  document_type="cv")
                         .select_related("primary_text_version").order_by("id")):
            body = document.best_text
            if body and document.person_id not in fallback_evidence:
                fallback_evidence[document.person_id] = [{
                    "document_id": document.pk, "ordinal": 0,
                    "quote": clean_passage(body, limit=SNIPPET_CHARS),
                }]
    sources = []
    for judgement in chosen:
        for item in (judgement.evidence or fallback_evidence.get(judgement.person_id, [])):
            sources.append({
                "n": len(sources) + 1,
                "person_id": judgement.person_id,
                "name": judgement.name,
                "document_id": item["document_id"],
                "ordinal": item.get("ordinal", 0),
                "snippet": item["quote"] if judgement.criteria else item["quote"][:SNIPPET_CHARS],
            })
    return sources


def evidence_rows(chosen, stats):
    """Include pinned people in the writing context even when a criterion is UNKNOWN."""
    from .judge import Judgement

    rows = list(chosen)
    seen = {row.person_id for row in rows}
    for raw in stats.get("identified_judgements", []) or []:
        row = Judgement(**raw) if isinstance(raw, dict) else raw
        if row.person_id not in seen:
            rows.append(row)
            seen.add(row.person_id)
    return rows


def _person_block(judgement, sources):
    numbers = [s["n"] for s in sources if s["person_id"] == judgement.person_id]
    return {
        "ten": judgement.name,
        "nguon": numbers,
        "bang_chung": [s["snippet"] for s in sources
                       if s["person_id"] == judgement.person_id],
        "thuoc_tinh": judgement.fact_attributes(),
        "suy_luan_chua_phai_du_kien": judgement.inference_attributes(),
        "trang_thai_thuoc_tinh": {key: status.get("status")
                                  for key, status in judgement.attribute_status.items()},
        "trang_thai_nhan_dinh": "INFERENCE",
        "do_tin": judgement.confidence,
        "vi_sao": judgement.why,
        "con_thieu": judgement.gap,
    }


def _store_size():
    """Số hồ sơ trong kho — để ⑤ nói "K hồ sơ gần nhất trong N", không phải K trơ."""
    try:
        from people.models import Person
        return Person.objects.count()
    except Exception:                               # noqa: BLE001
        return 0


def build_payload(query_plan, chosen, near_misses, stats, sources):
    sort_info = stats.get("sorted_by")
    return {
        "cau_hoi": query_plan.information_need,
        "ket_qua": [_person_block(j, sources) for j in chosen],
        "nguoi_da_xac_dinh": [_person_block(j, sources)
                              for j in evidence_rows([], stats)],
        "so_lieu_chinh_xac": {
            key: stats[key] for key in ("total_count", "exact_name_count", "count")
            if key in stats
        },
        "sap_xep": ({"tieu_chi": sort_info["key"],
                     "huong": "tăng dần" if sort_info["asc"] else "giảm dần"}
                    if sort_info else None),
        "thieu_du_lieu": stats.get("missing_sort_value", 0),
        "gan_dung": [{"ten": j.name, "thieu": j.gap or j.why}
                     for j in near_misses],
        "da_ra_soat": stats.get("judged", 0),
        "da_tim_thay": stats.get("retrieved", 0),
        # Cỡ kho THẬT. Trước đây ⑤ chỉ có `da_ra_soat` (16, 40, 12 tuỳ pool) và
        # viết "đã rà 16 hồ sơ" — người dùng đọc thành "kho chỉ có 16" (ảnh test
        # 04/09, con số nhảy mỗi lượt). Có cả hai số thì mới nói đúng được:
        # "16 hồ sơ gần yêu cầu nhất trong 786".
        "kho_co": None if stats.get("scope") in ("previous_result", "explicit_people") else _store_size(),
        "pham_vi": stats.get("scope", "retrieved_pool"),
        "so_ho_so_trong_pham_vi": stats.get("scope_size"),
        "so_ho_so_phu_hop": stats.get("relevant", 0),
        "cach_chon_nhom_doc_sau": stats.get("deep_read_selection", ""),
        "tran_doc_sau": stats.get("deep_read_pool_limit"),
        "nhom_doc_sau_da_xep_hang": bool(stats.get("deep_read_ranked")),
        # Câu tra theo TÊN (đã ghim người): khung "đã rà N" là sai — nó không rà,
        # nó tra đích danh. ⑤ phải nói "trong kho có / không có hồ sơ tên …".
        "tra_theo_ten": bool(stats.get("pinned")),
        "loi_doc_ho_so": bool(stats.get("read_failed")),
        "doc_chua_day_du": bool(stats.get("read_incomplete")),
        "ho_so_chua_doc_duoc": stats.get("unread", 0),
        "tham_chieu_khong_ton_tai": bool(stats.get("reference_unknown")),
        "con_lai_chua_hien": stats.get("truncated", 0),
        # Việc sẽ do BƯỚC SAU làm. ⑤ nhìn thấy cả câu hỏi gốc nên nếu không dặn,
        # nó tự làm luôn phần đó — rồi bước sau chạy lại và câu trả lời tự mâu
        # thuẫn với chính nó (đo trên production: ⑤ soạn xong thư, ngay dưới là
        # "Tôi chưa thực hiện được yêu cầu này").
        "viec_cua_buoc_sau": [step.get("yeu_cau", "")
                              for step in (getattr(query_plan, "next_steps", []) or [])],
    }


def _system_for(user):
    """Persona ổn định + luật viết của chặng ⑤.

    `persona.stable_system()` giữ danh tính, cách xưng hô theo tuỳ chọn của từng
    người, và phạm vi sản phẩm. Để ⑤ tự khai giọng thì Radar xưng hô một kiểu ở
    màn này, kiểu khác ở màn kia — cùng một trợ lý mà như hai người.
    """
    from ai.persona import stable_system
    try:
        return stable_system("talent", user) + "\n\n" + SYSTEM
    except Exception:                               # noqa: BLE001
        return SYSTEM


def build_messages(query_plan, chosen, near_misses, stats, sources, *, history=None,
                   user=None, memories=None, corpus_facts=""):
    """Messages cho một lượt viết. Dùng chung cho `compose()` và đường SSE."""
    import json

    parts = []
    remembered = list(memories or [])[:8]
    if remembered:
        parts.append("NGƯỜI DÙNG ĐÃ DẶN:\n" + "\n".join(f"- {m}" for m in remembered))
    # Câu hỏi tổng hợp ("kho có những ngành nào", "tổng quan kho") KHÔNG trả lời
    # được bằng 40 hồ sơ truy hồi — nó cần số liệu toàn kho. `corpus_facts` là
    # phần đó, tính bằng truy vấn CSDL nên chính xác và có kèm độ phủ.
    if corpus_facts:
        parts.append(corpus_facts)
    context = _history_block(history)
    if context:
        parts.append("LỊCH SỬ HỎI ĐÁP:\n" + context)
    parts.append(json.dumps(build_payload(query_plan, chosen, near_misses, stats, sources),
                            ensure_ascii=False, indent=1))
    return [{"role": "system", "content": _system_for(user)},
            {"role": "user", "content": "\n\n".join(parts)}]


def _history_block(history):
    lines, used = [], 0
    # Giữ đủ mạch hội thoại nhưng có ngân sách cứng để history không lấn át CV.
    for turn in [h for h in (history or []) if isinstance(h, dict)][-12:]:
        question = str(turn.get("question") or "").strip()
        reply = str(turn.get("answer") or "").strip()
        if question:
            chunk = f"H: {question[:600]}"
            if used + len(chunk) <= 10000:
                lines.append(chunk)
                used += len(chunk)
        if reply:
            chunk = f"Đ: {reply[:1200]}"
            if used + len(chunk) <= 10000:
                lines.append(chunk)
                used += len(chunk)
    return "\n".join(lines)


#: Trích dẫn `[3]` và cả dạng GỘP `[1,2]` / `[7, 8]`.
#:
#: Model viết gộp rất thường xuyên — đo trên kho thật, hai câu trả lời tốt bị
#: chấm "không trích dẫn nguồn nào" chỉ vì chúng viết `[1,2]`. Regex chỉ bắt
#: `[n]` thì vừa đếm sót nguồn, vừa để lại chuỗi đó dưới dạng chữ thường trên
#: giao diện: người đọc thấy `[1,2]` mà bấm không được.
_CITE = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")


def _numbers_in(group):
    out = []
    for part in str(group).split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def used_sources(text, sources):
    """Nguồn thật sự được nhắc trong câu trả lời, theo thứ tự xuất hiện.

    Số ngoài dải hợp lệ bị gỡ khỏi văn bản chứ không im lặng bỏ qua — trích dẫn
    trỏ vào hư vô còn tệ hơn không trích dẫn.
    """
    valid = {s["n"]: s for s in sources}
    seen, ordered = set(), []
    for match in _CITE.finditer(str(text or "")):
        for number in _numbers_in(match.group(1)):
            if number in valid and number not in seen:
                seen.add(number)
                ordered.append(valid[number])

    def _keep(match):
        kept = [n for n in _numbers_in(match.group(1)) if n in valid]
        return f"[{','.join(str(n) for n in kept)}]" if kept else ""

    cleaned = _CITE.sub(_keep, str(text or ""))
    return " ".join(cleaned.split()) if cleaned != text else text, ordered


def compose(query_plan, chosen, near_misses, stats, *, history=None, complete_fn=None,
            user=None, memories=None, corpus_facts=""):
    """Trả `(text, sources_used, all_sources, meta)`. Mọi câu trả lời đều do AI viết."""
    verified_rows = evidence_rows(chosen, stats)
    sources = build_sources(verified_rows)
    caller = complete_fn or complete
    messages = build_messages(query_plan, chosen, near_misses, stats, sources,
                              history=history, user=user, memories=memories,
                              corpus_facts=corpus_facts)
    def _call(budget):
        return caller(messages, task=TASK, temperature=0.35, max_tokens=budget,
                      reasoning_effort="none", budget_seconds=60)

    def _give_up(reason, response=None):
        return ai_unavailable_text(reason), [], sources, \
            {"provider": getattr(response, "provider", "") if response else "",
             "model": getattr(response, "model", "") if response else "",
             "reasoning": "", "fallback": True, "fallback_reason": reason}

    try:
        response = _call(MAX_TOKENS)
        # Bị cắt giữa chừng thì câu trả lời đứt GIỮA CHỮ — thà tốn thêm một lượt
        # gọi còn hơn đưa cho người dùng một câu cụt. Thử lại đúng một lần.
        if getattr(response, "truncated", False):
            log.warning("answer.compose: câu trả lời bị cắt, thử lại với %s token",
                        RETRY_MAX_TOKENS)
            response = _call(RETRY_MAX_TOKENS)
    except Exception as exc:                        # noqa: BLE001
        log.warning("answer.compose: model lỗi, không sinh câu trả lời CODE: %s", exc)
        return _give_up("model_error")

    text, reasoning = extract_thinking(response.text)
    text = str(text or response.text or "").strip()
    if not text:
        return _give_up("empty_response", response)
    if getattr(response, "truncated", False):
        # Vẫn cụt sau khi nới: một mẩu câu dở là tệ hơn một bản tóm tắt khô khan
        # nhưng trọn vẹn.
        log.warning("answer.compose: vẫn bị cắt sau khi nới, không sinh câu trả lời CODE")
        return _give_up("truncated", response)

    from . import verify
    if verify.check(query_plan, verified_rows, text, sources):
        return _give_up("verification_failed", response)
    text, used = used_sources(text, sources)
    return text, used, sources, {
        "provider": getattr(response, "provider", ""),
        "model": getattr(response, "model", ""),
        "reasoning": (reasoning or "")[:6000],
        "fallback": False,
    }


def deterministic_text(query_plan, chosen, stats):
    """Arithmetic/coverage and known identity do not require model prose."""
    if stats.get("reference_unknown"):
        return "Danh sách vừa rồi không có người ở vị trí đó. Bạn chọn lại hồ sơ cần hỏi nhé."
    if "total_count" in stats:
        return f"Kho hiện có {stats['total_count']} hồ sơ ứng viên chưa gộp."
    if "exact_name_count" in stats:
        result = stats["exact_name_count"]
        label = result["query"]
        lines = [f"Trong toàn bộ {result['scope_total']} hồ sơ ứng viên, có "
                 f"{result['matched']} hồ sơ có thành phần tên “{label}”."]
        names = [row["name"] for row in result.get("people", [])]
        if names:
            lines.append("Các hồ sơ tìm thấy: " + ", ".join(names[:20]) + ".")
            if len(names) > 20:
                lines.append(f"Còn {len(names) - 20} hồ sơ khác không hiển thị trong tin nhắn này.")
        lines.append("Kết quả được đếm trực tiếp trên toàn bộ kho, không bị giới hạn bởi nhóm 60 hồ sơ đọc sâu.")
        return "\n".join(lines)
    if "count" in stats:
        count = stats["count"]
        scope = ("nhóm hồ sơ đang xét" if count["scope"] in ("previous_result", "explicit_people")
                 else "kho ứng viên")
        lines = [f"Đã đánh giá sâu {count['reviewed']} hồ sơ tiềm năng nhất theo xếp hạng "
                 f"hybrid trên dữ liệu có thể tìm kiếm của toàn bộ {count['scope_total']} hồ sơ trong {scope}."]
        if count["matched"] is not None:
            lines.append(f"Có {count['matched']} hồ sơ được đánh giá phù hợp với yêu cầu trong phần đã đọc.")
        if count["read_failed"] or count["read_incomplete"]:
            lines.append("Bước đọc một số hồ sơ bị lỗi; kết quả đánh giá chưa đầy đủ.")
        if count.get("criteria_unknown"):
            lines.append(f"{count['criteria_unknown']} hồ sơ có ít nhất một điều kiện chưa đủ bằng chứng.")
        lines.append("Đây là đánh giá trên bằng chứng đã đọc; số hồ sơ thực sự đáp ứng trong toàn bộ phạm vi chưa xác định. "
                     "Thiếu bằng chứng không có nghĩa là không đáp ứng.")
        sources = build_sources(chosen)
        if chosen:
            lines.append(f"Hiển thị {len(chosen)} hồ sơ được đánh giá phù hợp:")
            for row in chosen:
                citations = "".join(f" [{s['n']}]" for s in sources if s["person_id"] == row.person_id)
                lines.append(f"- {row.name}{citations}")
        return "\n".join(lines)
    if stats.get("whole_store"):
        have, total = stats.get("coverage_have", 0), stats.get("coverage_total", 0)
        if not chosen:
            return f"Chưa có dữ liệu đủ để xếp hạng theo {query_plan.sort_by.get('key', 'tiêu chí này')} trong {total} hồ sơ."
        lines = [f"Xếp hạng trong {have}/{total} hồ sơ có dữ liệu {query_plan.sort_by.get('key', '')}:"]
        sources = build_sources(chosen)
        for index, row in enumerate(chosen, 1):
            citations = "".join(f" [{s['n']}]" for s in sources if s["person_id"] == row.person_id)
            lines.append(f"{index}. {row.name}: {row.why}{citations}.")
        if have < total:
            lines.append(f"{total - have} hồ sơ chưa có dữ liệu này; chưa thể kết luận thứ hạng của họ.")
        return "\n".join(lines)
    if not chosen and stats.get("identified_people") and not stats.get("read_failed"):
        names = ", ".join(stats["identified_people"])
        rows = stats.get("identified_judgements") or []
        lines = [f"Đã tìm đúng hồ sơ {names}, nhưng hồ sơ không ghi rõ thông tin được hỏi nên chưa thể xác nhận."]
        facts = []
        gaps = []
        for row in rows:
            extracted = row.get("extracted", {}) if isinstance(row, dict) else row.extracted
            statuses = row.get("attribute_status", {}) if isinstance(row, dict) else row.attribute_status
            for key, value in extracted.items():
                if statuses.get(key, {}).get("status", "FACT") != "FACT":
                    continue
                item = f"{key}: {value}"
                if item not in facts:
                    facts.append(item)
            gap = row.get("gap", "") if isinstance(row, dict) else row.gap
            if gap and gap not in gaps:
                gaps.append(gap)
        if facts:
            lines.append("Thông tin có thể xác minh từ hồ sơ: " + "; ".join(facts[:8]) + ".")
        if gaps:
            lines.append("Thông tin còn thiếu: " + "; ".join(gaps[:3]) + ".")
        lines.append("Radar không suy đoán thuộc tính còn thiếu từ chức danh, năm tốt nghiệp hoặc dữ liệu gần đúng.")
        return "\n".join(lines)
    return None


def should_use_deterministic(query_plan, stats):
    """Only exact arithmetic/meta answers may bypass the writing model.

    Evidence gaps and candidate recommendations need explanatory prose. They
    previously hit `stats['count']` first and returned a terse template without
    ever calling stage ⑤, which is exactly the blank model badge seen in UI.
    """
    if stats.get("reference_unknown"):
        return True
    if "total_count" in stats or "exact_name_count" in stats:
        return True
    if "count" in stats:
        return getattr(query_plan, "shape", "") == "count"
    return False


def fallback_text(query_plan, chosen, stats):
    """Model viết hỏng thì vẫn phải trả lời được — thà khô khan còn hơn trắng."""
    if stats.get("reference_unknown"):
        return "Danh sách vừa rồi không có người ở vị trí đó. Bạn chọn lại hồ sơ cần hỏi nhé."
    deterministic = deterministic_text(query_plan, chosen, stats)
    if deterministic is not None:
        return deterministic
    if stats.get("read_failed"):
        return (f"Tôi tìm được {stats.get('retrieved', 0)} hồ sơ liên quan tới "
                f"\"{query_plan.information_need}\" nhưng bước đọc hồ sơ bị lỗi kỹ "
                "thuật nên chưa kết luận được ai phù hợp. Bạn thử hỏi lại giúp tôi.")
    if not chosen:
        # Câu thống kê không đi qua ②③ nên `chosen` rỗng là BÌNH THƯỜNG — nói
        # "không tìm được ai" ở đây là trả lời sai loại câu hỏi.
        if getattr(query_plan, "shape", "") in ("count", "analyze"):
            from . import corpus
            facts = corpus.facts_for_prompt()
            if facts:
                return ("Số liệu kho hiện tại:\n" + facts.split("\n", 1)[-1])
        if stats.get("pinned"):
            return (f"Trong kho không có hồ sơ nào khớp tên trong câu hỏi "
                    f"\"{query_plan.information_need}\". Bạn kiểm tra lại chính "
                    "tả họ tên, hoặc thử tìm bằng tiêu chí (chức danh, kỹ năng).")
        total = stats.get("store_size") or _store_size()
        scope = f" trong tổng số {total}" if total else ""
        return (f"Chưa tìm được hồ sơ nào thoả \"{query_plan.information_need}\". "
                f"Đã đọc sâu {stats.get('judged', 0)} hồ sơ tiềm năng nhất theo xếp hạng hybrid toàn kho{scope}. "
                "Thử bỏ bớt một điều kiện hoặc mô tả bằng cách nói khác giúp tôi.")
    lines = [f"Có {len(chosen)} hồ sơ thoả \"{query_plan.information_need}\":"]
    if stats.get("read_incomplete"):
        lines.append(f"Chưa đọc được {stats.get('unread', 0)} hồ sơ; kết quả chưa đầy đủ.")
    sources = build_sources(chosen)
    for index, judgement in enumerate(chosen, start=1):
        detail = "; ".join(f"{k}: {v}" for k, v in list(judgement.fact_attributes().items())[:3])
        lines.append(f"{index}. {judgement.name}"
                     + (f" — {detail}" if detail else "")
                     + (f" ({judgement.why})" if judgement.why else "")
                     + "".join(f" [{s['n']}]" for s in sources
                               if s["person_id"] == judgement.person_id))
    return "\n".join(lines)


def ai_unavailable_text(reason="model_error"):
    """Thông báo trạng thái, tuyệt đối không trả lời thay AI bằng template dữ liệu."""
    labels = {
        "model_error": "mô hình AI không phản hồi",
        "empty_response": "mô hình AI trả về nội dung rỗng",
        "truncated": "phản hồi AI chưa hoàn chỉnh",
        "verification_failed": "phản hồi AI không vượt qua bước kiểm chứng bằng chứng",
    }
    detail = labels.get(reason, "mô hình AI chưa hoàn tất")
    return (f"Radar chưa thể trả lời yêu cầu này vì {detail}. "
            "Dữ liệu và kết quả trung gian không được dùng để tự dựng câu trả lời. "
            "Bạn hãy thử lại sau ít phút.")
