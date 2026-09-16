# -*- coding: utf-8 -*-
"""② Truy hồi — CODE thuần, không LLM.

Chạy **mọi** `search_queries` của kế hoạch qua ba nhánh song song rồi hợp nhất
bằng RRF, gom theo NGƯỜI (không phải theo đoạn) vì chặng ③ phán đoán trên từng
người:

    dense hồ sơ   pgvector trên `PersonSearchDocument.embedding`  (HNSW)
    dense đoạn CV pgvector trên `CVChunk.embedding`               (HNSW)
    full-text     GIN `to_tsvector('simple', *_norm)`             (bỏ dấu)

Khác đường cũ ở chỗ **không có bộ chấm điểm so-chuỗi nào được phủ quyết kết quả
truy hồi**. Điểm ở đây chỉ để xếp thứ tự đưa vào ③; ai lọt vào là do ③ đọc bằng
chứng quyết định.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from accounts import privacy
from django.db import connection
from django.db.models import Q

from people.models import Document
from talent import vector_index
from talent.models import CVChunk, PersonSearchDocument

log = logging.getLogger(__name__)

#: Trần số người ĐỌC KỸ ở ③ (ngân sách token của một lượt). Truy hồi (vector +
#: FTS) vẫn quét TOÀN kho rồi RRF xếp hạng — `POOL` chỉ giới hạn phần đọc sâu
#: bằng LLM. ③ chạy lô song song nên nâng 40→60 gần như không thêm thời gian
#: tường (chủ dự án 05/09: kho sẽ lớn hơn nhiều, 40 là quá hẹp).
POOL = max(16, min(200, int(os.getenv("TALENT_DEEP_READ_POOL", "60"))))
#: Sàn — dưới mức này thì ③ không còn gì để loại, và câu "có ai … không?" cần
#: một mẫu đủ rộng mới trả lời trung thực được.
MIN_POOL = 16
#: Khớp với `plan.DEFAULT_LIMIT`; lặp lại ở đây để `retrieve` không phải import
#: ngược lên ① (vòng import).
DEFAULT_LIMIT = 10
#: Số đoạn bằng chứng cho người xếp ĐẦU — những người ③ thật sự sẽ chọn.
PASSAGES_PER_PERSON = 4
#: Số đoạn cho phần đuôi danh sách. Vẫn đủ để ③ nhận ra ai lạc đề, mà không trả
#: tiền đọc kỹ cho phần lớn hồ sơ sẽ bị loại.
TAIL_PASSAGES = 2
PASSAGE_CHARS = 700
#: Trần mỗi nhánh cho mỗi truy vấn. Nâng cùng `POOL`: RRF cần dư ứng viên để
#: xếp hạng khi kho lớn, nếu không phần đuôi pool toàn người của một truy vấn.
PER_QUERY = 90
RRF_K = 60
#: Số truy vấn vector chạy song song. Mỗi cái là một lời gọi embedding qua mạng.
DENSE_WORKERS = 4


def clean_passage(text, *, limit=PASSAGE_CHARS):
    """Gộp khoảng trắng, cắt độ dài, và **che email/số điện thoại**.

    Che ở ĐÂY chứ không phải trên đường trả về, vì đây là nơi duy nhất mọi đoạn
    bằng chứng đi qua. Che ở đây thì LLM không bao giờ nhìn thấy liên hệ, nên cả
    lớp lỗi "⑤ chép lại số điện thoại từ đoạn nguồn" biến mất thay vì phải rào
    bằng lời dặn trong prompt.

    Đo trên kho thật: 33% đoạn CV chứa email, 25% chứa số điện thoại. Hệ thống
    có hạn mức mở khoá liên hệ (`accounts.privacy.unlock`); trả nguyên văn ở đây
    là mở một đường vòng qua toàn bộ hạn mức đó.
    """
    return privacy.redact_contacts(" ".join(str(text or "").split())[:limit])


@dataclass
class Passage:
    person_id: int
    document_id: int
    ordinal: int
    text: str
    source: str = "cv"          # cv | profile

    def as_dict(self):
        return {"document_id": self.document_id, "ordinal": self.ordinal,
                "snippet": self.text, "source": self.source}


@dataclass
class Candidate:
    person_id: int
    name: str
    score: float = 0.0
    hits: int = 0               # số nhánh/truy vấn chạm tới người này
    passages: list = field(default_factory=list)

    def evidence_text(self, limit=PASSAGES_PER_PERSON):
        return [p.text for p in self.passages[:limit]]


def _fold(text):
    return vector_index.fold_text(text)


def _rrf(ranked_lists, k=RRF_K):
    """Reciprocal Rank Fusion — không nhánh nào chiếm pool nhờ được chạy trước."""
    scores, hits = {}, {}
    for ranked in ranked_lists:
        for rank, person_id in enumerate(ranked, start=1):
            scores[person_id] = scores.get(person_id, 0.0) + 1.0 / (k + rank)
            hits[person_id] = hits.get(person_id, 0) + 1
    # Person id is only a stable tie-breaker after the relevance score. This
    # prevents database/insertion order from changing who enters the deep-read pool.
    order = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return order, hits


class _DenseBranch:
    """Nhánh vector, tắt cho cả lượt ngay khi lỗi lần đầu.

    Mỗi truy vấn là một lời gọi embedding qua mạng. Nhà cung cấp chết mà vẫn thử
    đủ 6 lần thì riêng phần chờ timeout đã ăn hết ngân sách 15 giây, và người
    dùng nhận màn hình đứng thay vì câu trả lời từ nhánh full-text.
    """

    def __init__(self):
        self.disabled = False
        self.error = ""

    def __call__(self, query, limit, *, in_thread=False):
        if self.disabled:
            return []
        try:
            return list(vector_index.search(query, limit=limit) or [])
        except Exception as exc:                    # noqa: BLE001
            self.disabled, self.error = True, str(exc)[:200]
            log.warning("answer.retrieve: tắt nhánh vector cho lượt này: %s", exc)
            return []
        finally:
            if in_thread:
                # `vector_index.search` truy vấn qua ORM, và Django cấp kết nối
                # theo TỪNG luồng. Không đóng ở đây thì mỗi lượt hỏi để lại vài
                # kết nối PostgreSQL treo cho tới khi hết `max_connections`.
                connection.close()


#: Cùng một lưới phạm vi với nhánh vector — định nghĩa ở `vector_index` để hai
#: nhánh của ② không thể trôi khỏi nhau. Nhánh này lọc lúc TRUY VẤN vì chỉ mục
#: có thể còn hàng cũ của người vừa mất quyền xuất hiện.
VISIBLE = vector_index.VISIBLE


def _fts_person_ids(query, limit):
    """Full-text trên đoạn CV và projection hồ sơ; SQLite lùi về icontains."""
    out = []
    chunks = vector_index.fts_filter(
        CVChunk.objects.filter(**VISIBLE), "text_norm", query)
    docs = vector_index.fts_filter(
        PersonSearchDocument.objects.filter(**VISIBLE), "content_norm", query)
    if chunks is None:                              # không phải PostgreSQL
        terms = [t for t in _fold(query).split() if len(t) >= 3][:6]
        if not terms:
            return []
        lexical = Q()
        for term in terms:
            lexical |= Q(text_norm__icontains=term)
        chunks = CVChunk.objects.filter(lexical).filter(**VISIBLE)
        profile_q = Q()
        for term in terms:
            profile_q |= Q(content_norm__icontains=term)
        docs = PersonSearchDocument.objects.filter(profile_q).filter(**VISIBLE)
    for person_id in list(chunks.values_list("person_id", flat=True)[:limit]):
        if person_id not in out:
            out.append(person_id)
    for person_id in list(docs.values_list("person_id", flat=True)[:limit]):
        if person_id not in out:
            out.append(person_id)
    return out


def _passages_for(person_ids, queries, per_person=PASSAGES_PER_PERSON):
    """Đoạn CV khớp nhất của từng người — bằng chứng để ③ đọc và trích dẫn."""
    if not person_ids:
        return {}
    terms = []
    for query in queries:
        terms.extend(t for t in _fold(query).split() if len(t) >= 3)
    terms = list(dict.fromkeys(terms))[:16]

    by_person: dict[int, list[Passage]] = {pid: [] for pid in person_ids}
    rows = (CVChunk.objects.filter(person_id__in=person_ids)
            .values_list("person_id", "document_id", "ordinal", "text", "text_norm"))
    scored: dict[int, list] = {}
    for person_id, document_id, ordinal, text, text_norm in rows.iterator(chunk_size=500):
        folded = text_norm or _fold(text)
        hits = sum(1 for term in terms if term in folded)
        scored.setdefault(person_id, []).append(
            (hits, ordinal, Passage(person_id, document_id, ordinal,
                                    clean_passage(text))))
    for person_id, items in scored.items():
        items.sort(key=lambda row: (-row[0], row[1]))
        by_person[person_id] = [item[2] for item in items[:per_person]]

    # Người chưa có CVChunk (chưa lập chỉ mục) — lấy đầu văn bản CV làm bằng chứng.
    missing = [pid for pid, items in by_person.items() if not items]
    if missing:
        docs = (Document.objects.filter(person_id__in=missing)
                .select_related("primary_text_version")
                .only("id", "person_id", "parsed_text", "primary_text_version"))
        for doc in docs:
            body = doc.best_text
            if body and not by_person.get(doc.person_id):
                by_person[doc.person_id] = [Passage(
                    doc.person_id, doc.pk, 0, clean_passage(body))]
    return by_person


def _profile_passages(person_ids):
    """Projection hồ sơ (trường DB + payload Edge + fact) — dữ liệu ngoài CV."""
    rows = (PersonSearchDocument.objects.filter(person_id__in=person_ids)
            .values_list("person_id", "content"))
    return {pid: Passage(pid, 0, 0, clean_passage(content), source="profile")
            for pid, content in rows}


def pool_for(query_plan, cap=POOL):
    """Số người mang sang ③, theo số hồ sơ người dùng thật sự muốn.

    Trước đây cố định 40 bất kể câu hỏi. Nhưng ③ là chặng tốn nhất (đo trên kho
    thật: 75% tổng token), và hỏi "3 người nhiều kinh nghiệm nhất" thì đọc sâu
    40 hồ sơ để rồi hiển thị 3 là trả tiền cho 37 hồ sơ không ai nhìn.

    Vẫn giữ hệ số rộng tay (×6): ③ loại khá nhiều, nên pool phải dư so với
    `limit` thì mới đủ người lọt.

    Riêng câu TỔNG HỢP (`analyze`) thì lấy pool tối thiểu: câu trả lời thật nằm
    ở số liệu toàn kho (`corpus.facts_for_prompt`), còn mấy hồ sơ truy hồi được
    chỉ là ví dụ minh hoạ. Đo trên production: "tổng quan về kho ứng viên" mất
    90 giây với pool 40 — sát trần `--timeout 120` của gunicorn, và phần lớn
    thời gian đó dùng để đọc kỹ những hồ sơ mà câu trả lời chỉ nhắc thoáng qua.
    """
    if getattr(query_plan, "shape", "") == "analyze":
        return MIN_POOL
    limit = max(1, int(getattr(query_plan, "limit", DEFAULT_LIMIT) or DEFAULT_LIMIT))
    # ×6 (trước ×4): ③ loại nhiều, và câu "liệt kê hết người làm X" (limit lớn)
    # phải đọc đủ rộng mới không bỏ sót. Vẫn chặn ở `cap` cho ngân sách token.
    return max(MIN_POOL, min(cap, limit * 6))


def retrieve(query_plan, *, pool=None, pinned_ids=(), search_queries=None):
    """`QueryPlan` → danh sách `Candidate` xếp theo độ liên quan giảm dần.

    KHÔNG nhận `user`. Tham số đó từng có mặt suốt và không được đọc lần nào —
    một chữ ký hứa việc giới hạn phạm vi theo người dùng mà thân hàm không làm.
    Phân quyền của Talent là theo VAI TRÒ và chặn ở view
    (`corpus_qa.can_read_cv`), không theo từng dòng dữ liệu; còn liên hệ cá nhân
    thì đã che tại `clean_passage`. Ai thêm ACL theo dòng sau này phải sửa ở đây
    một cách tường minh, chứ không được tin vào một tham số trang trí.

    `pinned_ids`: người phải CÓ trong kết quả bất kể điểm truy hồi — tên riêng
    đã giải định danh, hoặc người của lượt trước cho câu so sánh / hỏi tiếp.
    Không có họ thì "so sánh A và B" lần này ra, lần sau rớt một (không tất định).

    `search_queries`: ghi đè `query_plan.search_queries`. Truyền `[]` để BỎ HẲN
    truy hồi ngữ nghĩa — chỉ đọc `pinned_ids` (đường tắt cho câu neo vào tên).
    """
    queries = list(query_plan.search_queries if search_queries is None
                   else search_queries)
    pinned_ids = list(dict.fromkeys(int(p) for p in pinned_ids if p))
    if not queries and not pinned_ids:
        return []
    if pool is None:
        pool = pool_for(query_plan)

    # Nhánh vector chạy song song: mỗi truy vấn là một lời gọi embedding qua
    # mạng, sáu truy vấn tuần tự đo được 5.4 giây. Chúng độc lập nhau hoàn toàn.
    dense_branch = _DenseBranch()
    if not queries:
        # Chỉ có người ghim (so sánh / hỏi tiếp theo tên, không tiêu chí khác) —
        # bỏ hẳn truy hồi ngữ nghĩa, đọc thẳng đúng người đó. Cắt ~5s.
        dense_lists = []
    elif len(queries) > 1:
        with ThreadPoolExecutor(max_workers=min(DENSE_WORKERS, len(queries))) as workers:
            from ai.telemetry import submit
            futures = [submit(workers, lambda q: dense_branch(q, PER_QUERY, in_thread=True), q)
                       for q in queries]
            dense_lists = [future.result() for future in futures]
    else:
        dense_lists = [dense_branch(queries[0], PER_QUERY)]

    ranked_lists = [ids for ids in dense_lists if ids]
    # Full-text chạy tuần tự: đây là truy vấn CSDL, và luồng phụ dùng ORM sẽ mở
    # thêm kết nối PostgreSQL cho mỗi luồng — không đáng cho vài chục mili-giây.
    for query in queries:
        fts = _fts_person_ids(query, PER_QUERY)
        if fts:
            ranked_lists.append(fts)

    order, hits = _rrf(ranked_lists) if ranked_lists else ([], {})
    top_ids = [person_id for person_id, _score in order[:pool]]

    # Ghim tên riêng / người lượt trước lên ĐẦU, không để top-N cắt mất. ③ vẫn
    # là chỗ phán đoán — ở đây chỉ đảm bảo họ được ĐỌC.
    if pinned_ids:
        pin_set = set(pinned_ids)
        top_ids = pinned_ids + [pid for pid in top_ids if pid not in pin_set]
        top_ids = top_ids[:max(pool, len(pinned_ids))]
        for pid in pinned_ids:
            hits.setdefault(pid, 1)
        # Điểm tổng hợp cao hơn mọi người truy hồi được, giữ đúng thứ tự ghim.
        pin_score = {pid: 1_000.0 - i for i, pid in enumerate(pinned_ids)}
        order = ([(pid, pin_score[pid]) for pid in pinned_ids]
                 + [(pid, s) for pid, s in order if pid not in pin_set])

    if not top_ids:
        return []

    names = dict(PersonSearchDocument.objects
                 .filter(person_id__in=top_ids)
                 .values_list("person_id", "person__display_name"))
    # Người ghim có thể chưa có PersonSearchDocument (chưa lập chỉ mục hồ sơ) —
    # vẫn phải hiện đúng tên, không phải "#123".
    missing_name = [pid for pid in top_ids if pid not in names]
    if missing_name:
        from people.models import Person
        names.update(dict(Person.objects.filter(id__in=missing_name)
                          .values_list("id", "display_name")))
    cv_passages = _passages_for(top_ids, queries)
    profile_passages = _profile_passages(top_ids)

    # Độ sâu bằng chứng giảm dần theo thứ hạng. Người đứng đầu RRF là người ③
    # sẽ thật sự chọn, đáng đọc kỹ; đuôi danh sách phần lớn bị loại, đọc kỹ như
    # nhau là trả tiền cho phần không ai nhìn. ③ vẫn thấy MỌI người — chỉ khác
    # độ dày hồ sơ, nên không ai bị loại oan vì thiếu bằng chứng hoàn toàn.
    depth_cut = max(1, pool // 3)

    pinned_set = set(pinned_ids)
    candidates = []
    for rank, (person_id, score) in enumerate(order[:max(pool, len(pinned_ids))]):
        depth = PASSAGES_PER_PERSON if rank < depth_cut else TAIL_PASSAGES
        passages = list(cv_passages.get(person_id) or [])[:depth]
        profile = profile_passages.get(person_id)
        if profile is not None:
            passages.append(profile)
        if not passages:
            # Người ghim (tên riêng / lượt trước) KHÔNG được rơi âm thầm chỉ vì
            # chưa lập chỉ mục CV — ③ phải thấy họ để nói "chưa có CV để đọc".
            if person_id in pinned_set:
                passages = [Passage(person_id, 0, 0,
                                    names.get(person_id) or f"#{person_id}",
                                    source="profile")]
            else:
                continue
        candidates.append(Candidate(
            person_id=person_id, name=names.get(person_id) or f"#{person_id}",
            score=round(score, 6), hits=hits.get(person_id, 0), passages=passages))
    return candidates


def coverage():
    """Số liệu để trace nói thật về độ phủ chỉ mục, không hứa suông (§8.6)."""
    from django.db.models import F
    return {
        "profiles": PersonSearchDocument.objects.count(),
        "profiles_embedded": PersonSearchDocument.objects.filter(
            embedding_fingerprint=F("fingerprint")).count(),
        "chunks": CVChunk.objects.count(),
        "chunks_embedded": CVChunk.objects.filter(
            embedding_fingerprint=F("fingerprint")).count(),
    }
