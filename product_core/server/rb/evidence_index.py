# -*- coding: utf-8 -*-
"""Chỉ mục bằng chứng khách hàng — tìm theo NGHĨA cho Growth Answer Engine.

Trước file này, mọi nhánh truy hồi của Growth là `icontains`: "mua chung cư"
không tìm ra "mua căn hộ", "xoay vốn kinh doanh" không khớp "vay tiêu dùng". Đây
là đúng con đường Talent đã đi (`talent/vector_index.py`), làm lại cho bằng
chứng bán lẻ:

    lập chỉ mục   `index_person` — gom bằng chứng qua CHÍNH `evidence.gather` mà
                  ③ đọc (đã che liên hệ), mỗi mẩu một dòng `ProspectEvidenceChunk`
    full-text     GIN `to_tsvector('simple', text_norm)` — khớp không dấu, là
                  index scan chứ không quét bảng
    vector        cột `embedding`, tính NỀN bởi `embed_prospect_evidence`;
                  bảng là hàng đợi của chính nó (`embedding_fingerprint`)
    HNSW          `pin_vector_dimensions --apply` chốt chiều + tạo chỉ mục

## Cùng model embedding với Talent — cố ý

Dùng lại `talent.vector_index.embed`, tức cùng cấu hình `/settings`. Vector truy
vấn và vector tài liệu BẮT BUỘC cùng model mới so sánh được; hai cấu hình tách
rời thì chỉ cần một người đổi một bên là nhánh này im lặng trả toàn rác. Truy
vấn luôn lọc `embedding_model = model của vector truy vấn`, nên giai đoạn chuyển
model trả ít kết quả hơn chứ không trả sai.

## Không bao giờ làm hỏng lượt hỏi

Chưa lập chỉ mục, chưa có vector, nhà cung cấp embedding chết, không phải
PostgreSQL — mọi trường hợp đều trả danh sách rỗng, và các nhánh có cấu trúc
của `rb/answer/retrieve.py` vẫn chạy như trước.
"""
from __future__ import annotations

import hashlib
import logging

from django.db import connection
from django.db.models import Q

log = logging.getLogger(__name__)

#: Hệ số độ sâu khi gom bằng chứng để lập chỉ mục — xem `evidence.gather`.
INDEX_DEPTH = 8
#: Ký tự tối đa đưa vào embedding cho một mẩu.
EMBED_CHARS = 2000


def _fold(text):
    from talent.vector_index import fold_text
    return fold_text(text)


def index_person(person_id):
    """Dựng lại các mẩu bằng chứng của MỘT khách. Không gọi mạng.

    Mẩu nào nội dung không đổi thì giữ nguyên vector đã tính — ghi đè mù là huỷ
    sạch tiền embedding mỗi lần có ai sửa hồ sơ. Mẩu không còn trong nguồn (bài
    đã xoá, người đã gộp) bị xoá khỏi chỉ mục.
    """
    from people.models import Person

    from .answer import evidence
    from .models import ProspectEvidenceChunk

    person = Person.objects.filter(pk=person_id, merged_into__isnull=True).first()
    if person is None:
        ProspectEvidenceChunk.objects.filter(person_id=person_id).delete()
        return 0

    passages = evidence.gather([person.pk], depth=INDEX_DEPTH).get(person.pk, [])
    existing = {row.ref: row for row in ProspectEvidenceChunk.objects.filter(person=person)}
    seen = set()
    written = 0
    for passage in passages:
        ref = passage.ref or ""
        if not ref or ref in seen:
            continue
        seen.add(ref)
        digest = hashlib.sha256(
            f"{passage.source}|{passage.text}".encode("utf-8")).hexdigest()
        current = existing.get(ref)
        if (current is not None and current.fingerprint == digest
                and current.observed_at == passage.observed_at):
            continue
        ProspectEvidenceChunk.objects.update_or_create(ref=ref, defaults={
            "person": person, "source": passage.source, "text": passage.text,
            "text_norm": _fold(passage.text), "observed_at": passage.observed_at,
            "fingerprint": digest,
        })
        written += 1
    stale = [ref for ref in existing if ref not in seen]
    if stale:
        ProspectEvidenceChunk.objects.filter(person=person, ref__in=stale).delete()
    return written


def stale_chunks(limit=500):
    """Mẩu chưa có vector hoặc vector đã cũ — hàng đợi embedding."""
    from django.db.models import F

    from .models import ProspectEvidenceChunk
    return (ProspectEvidenceChunk.objects
            .exclude(embedding_fingerprint=F("fingerprint"))
            .order_by("pk")[:limit])


def embed_chunk(row):
    """Tính vector cho một mẩu. Trả True nếu thành công."""
    from talent.vector_index import embed

    vector, model = embed(row.text[:EMBED_CHARS], task_type="RETRIEVAL_DOCUMENT")
    if not vector:
        return False
    row.embedding = vector
    row.embedding_model = model
    row.embedding_fingerprint = row.fingerprint
    row.save(update_fields=["embedding", "embedding_model", "embedding_fingerprint",
                            "updated_at"])
    return True


#: Tập người cho phép nhỏ hơn mức này thì lọc NGAY trong truy vấn vector (quét
#: chính xác trên tập nhỏ là rẻ). Lớn hơn thì lấy top-K toàn cục qua HNSW rồi
#: giao với tập cho phép — lọc trong truy vấn khiến PostgreSQL bỏ chỉ mục HNSW.
EXACT_SCAN_BELOW = 2000


def dense_person_ids(query, allowed_ids, *, limit=120):
    """`[person_id]` xếp theo độ gần nghĩa. Rỗng khi không dùng được — KHÔNG ném lỗi.

    Người gọi (`retrieve._DenseBranch`) vẫn bọc thêm một lớp tắt-khi-lỗi; hàm này
    trả rỗng cho các trường hợp BIẾT TRƯỚC (không phải PostgreSQL, chưa có vector)
    để không tốn một lời gọi embedding vô ích.
    """
    from .models import ProspectEvidenceChunk

    if connection.vendor != "postgresql" or not allowed_ids:
        return []
    if not ProspectEvidenceChunk.objects.exclude(embedding__isnull=True).exists():
        return []
    from pgvector.django import CosineDistance
    from talent.vector_index import embed

    vector, model = embed(query, task_type="RETRIEVAL_QUERY")
    if not vector:
        return []
    allowed = set(allowed_ids)
    queryset = (ProspectEvidenceChunk.objects.exclude(embedding__isnull=True)
                .filter(embedding_model=model, person__merged_into__isnull=True))
    small = len(allowed) < EXACT_SCAN_BELOW
    if small:
        queryset = queryset.filter(person_id__in=list(allowed))
    rows = (queryset.annotate(distance=CosineDistance("embedding", vector))
            .order_by("distance")
            .values_list("person_id", flat=True)[:limit if small else limit * 4])
    out = []
    for person_id in rows:
        if person_id in allowed and person_id not in out:
            out.append(person_id)
        if len(out) >= limit:
            break
    return out


def fts_person_ids(query, allowed_ids, *, limit=120, sources=None):
    """`[person_id]` khớp full-text không dấu, mới nhất trước.

    PostgreSQL: GIN index. Nơi khác (SQLite dev/test): lùi về `icontains` trên
    `text_norm` — vẫn không dấu, chỉ chậm hơn.
    """
    from talent.vector_index import fts_filter

    from .models import ProspectEvidenceChunk

    if not allowed_ids:
        return []
    base = ProspectEvidenceChunk.objects.filter(person_id__in=list(allowed_ids))
    if sources:
        base = base.filter(source__in=list(sources))
    matched = fts_filter(base, "text_norm", query)
    if matched is None:
        terms = [t for t in _fold(query).split() if len(t) >= 3][:8]
        if not terms:
            return []
        where = Q()
        for term in terms:
            where |= Q(text_norm__icontains=term)
        matched = base.filter(where)
    out = []
    for person_id in (matched.order_by("-observed_at")
                      .values_list("person_id", flat=True)[:limit * 4]):
        if person_id not in out:
            out.append(person_id)
        if len(out) >= limit:
            break
    return out


def coverage():
    from django.db.models import F

    from .models import ProspectEvidenceChunk
    total = ProspectEvidenceChunk.objects.count()
    embedded = ProspectEvidenceChunk.objects.filter(
        embedding_fingerprint=F("fingerprint")).count()
    return {"chunks": total, "chunks_embedded": embedded,
            "people_indexed": (ProspectEvidenceChunk.objects
                               .values("person_id").distinct().count())}


#: Cờ bền (cache DB) đặt bởi MỘT lần `rebuild_prospect_evidence_index` chạy hết.
BACKFILL_MARKER = "rb:evidence_index:backfilled:v1"


def populated():
    """② được dùng chỉ mục thay cho `icontains` chưa?

    KHÔNG phải `ProspectEvidenceChunk.objects.exists()`. Ngay sau deploy bảng
    rỗng; lần lưu đầu tiên lập chỉ mục cho MỘT khách, `exists()` thành True, và
    từ lúc đó nhánh social/signal chỉ còn nhìn thấy đúng người đó cho tới khi ai
    nhớ chạy rebuild. Nên chỉ bật khi một lần backfill ĐẦY ĐỦ đã chạy xong — sau
    đó signal giữ chỉ mục theo kịp từng lượt ghi.
    """
    from django.core.cache import cache
    try:
        return bool(cache.get(BACKFILL_MARKER))
    except Exception:                              # noqa: BLE001
        return False


def mark_backfilled(value=True):
    from django.core.cache import cache
    if value:
        cache.set(BACKFILL_MARKER, True, timeout=None)
    else:
        cache.delete(BACKFILL_MARKER)
