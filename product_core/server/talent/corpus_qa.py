# -*- coding: utf-8 -*-
"""Hỏi đáp có dẫn chứng trên TOÀN kho CV — kiểu NotebookLM (Master Plan §8.2, §24).

Khác `person_qa.py` (neo vào MỘT người đã biết) và `ai_search.py` (trả DANH SÁCH
thẻ ứng viên để lọc). Ở đây người dùng hỏi một câu phân tích/tổng hợp về dữ liệu
("kho mình có bao nhiêu người từng làm ngân hàng và biết Python?", "CV nào nói
đến quản lý đội > 10 người?", "tổng hợp mặt bằng kinh nghiệm nhóm data") và nhận
MỘT câu trả lời ngắn, **chỉ dựa trên các đoạn CV được truy hồi**, kèm trích dẫn
[1][2]… trỏ về đúng người + đúng đoạn.

Nguyên tắc như NotebookLM:
  • Chỉ trả lời từ nguồn được cấp. Không đủ dữ kiện thì nói rõ đang thiếu gì.
  • Mọi khẳng định phải kèm trích dẫn.
  • Không suy diễn thu nhập / khả năng vay / dữ liệu nhạy cảm.

Truy hồi: dense (pgvector) khi đã bật + backfill; luôn có nhánh lexical trên
`CVChunk` và `Document.best_text` để chạy được NGAY cả khi embedding chưa sẵn sàng.
"""
import logging
import re

from django.db.models import Q

from ai.conversation import ConversationReply, extract_thinking
from ai.prompt_guard import GUARD_RULE
from ai.router import complete
from people.models import Document

from . import vector_index
from .models import CVChunk, PersonSearchDocument

log = logging.getLogger(__name__)

TASK = "talent_corpus_qa"

MAX_PASSAGES = 10
PASSAGE_CHARS = 700
WINDOW = 700
ANSWER_MAX_TOKENS = 900

_STOP = {
    "", "và", "hay", "hoặc", "the", "of", "in", "at", "là", "có", "cho", "một",
    "những", "các", "được", "trong", "về", "với", "người", "hồ", "sơ", "cv",
    "ai", "nào", "bao", "nhiêu", "kho", "mình", "chúng", "ta", "tôi", "làm",
    "từng", "biết", "cần", "tìm", "liệt", "kê", "thống", "tổng", "hợp",
}

_CORPUS_HINTS = (
    "cv", "hồ sơ", "ứng viên", "kho", "kỹ năng", "kinh nghiệm", "công ty",
    "ngành", "bao nhiêu", "liệt kê", "thống kê", "tổng hợp", "phân bố",
    "những người", "ai từng", "ai có", "ai đang", "người nào", "có bao nhiêu",
    "trung bình", "phổ biến", "nhiều nhất", "danh sách",
)


def _plain(text):
    """Bỏ dấu + hạ chữ thường — PHẢI giống hệt cách `*_norm` được lập chỉ mục,
    nếu không thì chấm điểm lại lệch với thứ full-text đã khớp."""
    return vector_index.fold_text(text)


def _term_hits(term, text):
    """Khớp theo BIÊN TỪ, không phải chuỗi con — kẻo 'hành' khớp nhầm 'thành'."""
    needle = _plain(term).strip()
    if not needle:
        return 0
    return len(re.findall(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", _plain(text)))


def looks_like_corpus_question(question):
    """Có nên thử trả lời có dẫn chứng trên kho CV cho câu hỏi hội thoại này không."""
    text = str(question or "").strip()
    if len(text.split()) < 3:
        return False
    low = text.casefold()
    if any(hint in low for hint in _CORPUS_HINTS):
        return True
    # Câu hỏi mở kết thúc bằng "?" và không phải câu meta ("bạn là ai") vẫn thử —
    # retrieval rỗng thì caller tự lùi về hội thoại thường.
    return text.endswith("?")


def _query_terms(question):
    terms = []
    for token in re.split(r"[^\wÀ-ỹ]+", str(question or "")):
        token = token.strip()
        if len(token) >= 3 and _plain(token) not in _STOP:
            terms.append(token)
    # Giữ trật tự, bỏ trùng, ưu tiên token dài (đặc trưng hơn).
    seen, out = set(), []
    for term in sorted(terms, key=len, reverse=True):
        key = _plain(term)
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out[:12]


class Passage:
    __slots__ = ("person_id", "person_name", "document_id", "ordinal", "text", "score")

    def __init__(self, person_id, person_name, document_id, ordinal, text, score):
        self.person_id = person_id
        self.person_name = person_name
        self.document_id = document_id
        self.ordinal = ordinal
        self.text = text
        self.score = score

    def key(self):
        return (self.document_id, self.ordinal, self.text[:60])


def _windows(text, terms, *, window=WINDOW, limit=3):
    """Đoạn văn quanh các lần khớp BIÊN TỪ. Rỗng nếu không term nào khớp."""
    clean = " ".join(str(text or "").split())
    if not clean:
        return []
    low = _plain(clean)
    spans = []
    for term in terms:
        needle = _plain(term).strip()
        if not needle:
            continue
        for match in re.finditer(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", low):
            spans.append((max(0, match.start() - window // 2),
                          min(len(clean), match.end() + window // 2)))
            if len(spans) >= 8:
                break
    if not spans:
        return []
    spans.sort()
    merged = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return [clean[lo:hi] for lo, hi in merged[:limit]]


#: `document_id` của đoạn lấy từ projection hồ sơ (không phải trích từ một file CV).
PROFILE_DOC_ID = 0


def retrieve(question, *, user=None, limit=MAX_PASSAGES):
    """Trả list `Passage` xếp theo độ liên quan giảm dần. Rỗng nếu không có gì."""
    terms = _query_terms(question)
    passages, seen = [], set()

    def _add(person_id, name, doc_id, ordinal, text, score):
        snippet = " ".join(str(text or "").split())[:PASSAGE_CHARS]
        if not snippet:
            return
        item = Passage(person_id, name or f"#{person_id}", doc_id, ordinal, snippet, score)
        if item.key() in seen:
            return
        seen.add(item.key())
        passages.append(item)

    # 1) Dense: person id gợi ý từ pgvector (nếu đã bật + backfill).
    dense_ids = []
    try:
        dense_ids = vector_index.search(question, limit=limit * 4) or []
    except Exception:                              # noqa: BLE001
        dense_ids = []
    dense_rank = {pid: i for i, pid in enumerate(dense_ids)}

    # 2) CVChunk. Trên PostgreSQL dùng full-text index trên `text_norm` (GIN,
    #    migration 0007) — kho triệu CV phải là index scan, không thể `LIKE '%x%'`.
    #    SQLite (máy dev) lùi về icontains.
    base_chunks = CVChunk.objects.filter(person__merged_into__isnull=True)
    chunk_rows = []
    fts = vector_index.fts_filter(base_chunks, "text_norm", question) if terms else None
    if fts is not None:
        chunk_rows = list(fts.values_list("person_id", "person__display_name",
                                          "document_id", "ordinal", "text")[:limit * 6])
        if dense_rank:
            chunk_rows += list(
                base_chunks.filter(person_id__in=list(dense_rank))
                .values_list("person_id", "person__display_name",
                             "document_id", "ordinal", "text")[:limit * 3])
    else:
        chunk_q = Q(person_id__in=list(dense_rank)) if dense_rank else Q()
        if terms:
            lexical = Q()
            for term in terms[:8]:
                lexical |= Q(text__icontains=term)
            chunk_q = (chunk_q | lexical) if dense_rank else lexical
        if chunk_q:
            chunk_rows = list(base_chunks.filter(chunk_q)
                              .values_list("person_id", "person__display_name",
                                            "document_id", "ordinal", "text")[:limit * 6])
    for person_id, name, doc_id, ordinal, text in chunk_rows:
        hits = sum(_term_hits(term, text) for term in terms)
        in_dense = person_id in dense_rank
        if not hits and not in_dense:
            continue
        score = hits + (2.0 if in_dense else 0.0) - 0.001 * dense_rank.get(person_id, 999)
        _add(person_id, name, doc_id, ordinal, text, score)

    # 3) Projection hồ sơ: trường có cấu trúc + dữ liệu Edge KHÔNG nằm trong CV
    #    (vị trí ứng tuyển, nguồn, mức lương…). Người chỉ có bản ghi Edge, chưa có
    #    CV, vẫn phải trả lời được — nếu không thì "hỏi trên toàn kho" là nói quá.
    if terms and len(passages) < limit * 2:
        base_docs = PersonSearchDocument.objects.filter(
            person__merged_into__isnull=True)
        profile_fts = vector_index.fts_filter(base_docs, "content_norm", question)
        if profile_fts is None:
            profile_q = Q()
            for term in terms[:6]:
                profile_q |= Q(content__icontains=term)
            profile_fts = base_docs.filter(profile_q)
        for person_id, name, content in profile_fts.values_list(
                "person_id", "person__display_name", "content")[:limit * 2]:
            for offset, window_text in enumerate(_windows(content, terms, limit=1)):
                hits = sum(_term_hits(term, window_text) for term in terms)
                if hits:
                    _add(person_id, name, PROFILE_DOC_ID, 800 + offset, window_text,
                         hits * 0.8)      # nhẹ hơn trích đoạn CV thật

    # 4) Lexical trực tiếp trên Document — CHỈ khi kho chưa có chunk nào. Còn
    #    chunk thì đây là quét toàn bảng `parsed_text`, không được phép ở quy mô
    #    thật; thiếu chunk là việc của `rebuild_talent_vector_index`.
    doc_fallback = (len([p for p in passages if p.score > 0]) < limit and terms
                    and not CVChunk.objects.exists())
    if doc_fallback:
        doc_q = Q()
        for term in terms[:6]:
            doc_q |= (Q(primary_text_version__text__icontains=term)
                      | Q(parsed_text__icontains=term))
        docs = list(Document.objects.filter(doc_q)
                    .filter(person__merged_into__isnull=True)
                    .select_related("person", "primary_text_version")[:limit * 3])
        for doc in docs:
            body = doc.best_text
            if not body:
                continue
            name = doc.person.display_name if doc.person_id else ""
            for offset, window_text in enumerate(_windows(body, terms)):
                hits = sum(_term_hits(term, window_text) for term in terms)
                if hits:
                    _add(doc.person_id, name, doc.pk, 900 + offset, window_text, float(hits))

    passages.sort(key=lambda p: p.score, reverse=True)
    return passages[:limit]


_SYSTEM = """Bạn là Radar, trợ lý của MSB. Người dùng hỏi một câu về KHO CV nội bộ.

Bạn CHỈ được trả lời dựa trên các đoạn CV được đánh số trong "nguon". Không dùng
kiến thức ngoài. Không suy diễn thu nhập, khả năng vay hay dữ liệu nhạy cảm.

Quy tắc:
- Mỗi khẳng định phải kèm trích dẫn dạng [n] trỏ tới đoạn nguồn dùng để nói điều đó.
- Nếu nguồn KHÔNG đủ để trả lời, nói thẳng đang thiếu gì và chỉ nêu phần trả lời
  được (nếu có). Không đoán, không bịa tên/số liệu.
- Phân biệt rõ FACT (có trong nguồn) với INFERENCE (suy luận hợp lý từ nguồn).
- Trả lời tiếng Việt, ngắn gọn, giọng nghiệp vụ. Tối đa ~180 từ.
- Không liệt kê lại toàn bộ nguồn; chỉ trả lời đúng câu hỏi.""" + "\n\n" + GUARD_RULE


def _history_block(history):
    turns = [h for h in (history or []) if isinstance(h, dict)][-4:]
    lines = []
    for turn in turns:
        question = str(turn.get("question") or "").strip()
        answer = str(turn.get("answer") or "").strip()
        if question:
            lines.append(f"H: {question[:200]}")
        if answer:
            lines.append(f"Đ: {answer[:200]}")
    return "\n".join(lines)


def can_read_cv(user):
    """RM thuần không đọc nội dung CV — giống bộ lọc của `talent.views.person_detail`."""
    try:
        from accounts import roles
    except Exception:                               # noqa: BLE001
        return True
    user_roles = roles.roles_of(user)
    if roles.RB_SALES not in user_roles:
        return True
    return bool(user_roles.intersection(
        {roles.RECRUITER, roles.HIRING_MANAGER, roles.MANAGER, roles.ADMIN}))


def source_label(document_id):
    return "hồ sơ" if not document_id else f"CV #{document_id}"


def build_messages(question, passages, history=None):
    """Messages cho một lượt trả lời có dẫn chứng. Dùng chung cho complete và stream."""
    numbered = "\n\n".join(
        f"[{i}] {p.person_name} ({source_label(p.document_id)}): {p.text}"
        for i, p in enumerate(passages, 1))
    parts = []
    hist = _history_block(history)
    if hist:
        parts.append("LỊCH SỬ HỎI ĐÁP:\n" + hist)
    parts.append("nguon:\n" + numbered)
    parts.append("cau_hoi: " + str(question or "").strip())
    return [{"role": "system", "content": _SYSTEM},
            {"role": "user", "content": "\n\n".join(parts)}]


def citations_from_answer(passages, text):
    """Các đoạn thật sự được trích trong câu trả lời ([n]); không có thì lấy top 5."""
    cited = sorted({int(n) for n in re.findall(r"\[(\d{1,2})\]", str(text or ""))
                    if 1 <= int(n) <= len(passages)})
    used = [passages[n - 1] for n in cited] or list(passages)[:5]
    return [{
        "n": (cited[idx] if idx < len(cited) else idx + 1),
        "person_id": p.person_id,
        "name": p.person_name,
        "document_id": p.document_id,
        "snippet": p.text[:280],
    } for idx, p in enumerate(used)]


def citation_sources(citations):
    """Dạng {title,url} cho khối nguồn dùng chung của giao diện."""
    return [{"title": f"{c['name']} · {source_label(c['document_id'])}",
             "url": f"/person/{c['person_id']}?from=talent"} for c in citations]


def answer(question, *, user=None, history=None, complete_fn=None, limit=MAX_PASSAGES):
    """Trả dict kết quả có dẫn chứng, hoặc None nếu không truy hồi được đoạn nào."""
    question = str(question or "").strip()
    if not question:
        return None

    passages = retrieve(question, user=user, limit=limit)
    if not passages:
        return None

    caller = complete_fn or complete
    try:
        resp = caller(build_messages(question, passages, history),
                      task=TASK, temperature=0.2, max_tokens=ANSWER_MAX_TOKENS,
                      reasoning_effort="none", budget_seconds=60)
    except Exception as exc:                        # noqa: BLE001
        log.warning("corpus_qa lỗi khi gọi model: %s", exc)
        return None

    clean, reasoning = extract_thinking(resp.text)
    text = str(clean or resp.text or "").strip()
    if not text:
        return None

    citations = citations_from_answer(passages, text)

    return {
        "answer": text[:3000],
        "reasoning": reasoning[:6000],
        "citations": citations,
        "retrieved": len(passages),
        "provider": getattr(resp, "provider", ""),
        "model": getattr(resp, "model", ""),
    }


def as_reply(question, *, user=None, history=None, complete_fn=None):
    """`ConversationReply` để dùng chung đường trả lời hội thoại ở view, hoặc None."""
    result = answer(question, user=user, history=history, complete_fn=complete_fn)
    if not result:
        return None
    reply = ConversationReply(
        result["answer"], reasoning=result["reasoning"],
        provider=result["provider"], model=result["model"],
        citations=citation_sources(result["citations"]))
    reply.corpus_citations = result["citations"]
    reply.grounded = True
    reply.retrieved = result["retrieved"]
    return reply
