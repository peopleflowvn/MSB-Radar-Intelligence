# -*- coding: utf-8 -*-
"""Cache lượt hỏi của Talent — khung nằm ở `core/answer/cache.py`.

File này chỉ còn phần PHỤ THUỘC KHO CV:

* `corpus_fingerprint()` — vân tay rẻ của kho ứng viên;
* prompt của ① và ③ Talent, cùng các tác vụ định tuyến của Talent;
* cách dựng lại một `Judgement` từ dòng đã lưu.

Mọi thứ khác (bốn vân tay, khuôn khoá, TTL, đọc/ghi) dùng chung với Growth. Các
hàm cấp module bên dưới giữ nguyên tên và chữ ký cũ: `engine.py`, `ai/baseline.py`
và ba tệp test đều gọi qua chúng, và đổi cách gọi chỉ để đi qua một đối tượng là
churn không đổi lấy gì.
"""
from __future__ import annotations

import logging

from core.answer.cache import (   # noqa: F401 - tên cũ vẫn được import từ đây
    TTL_SECONDS,
    TurnCache,
    context_marker as _context_marker,
    digest as _digest,
    permission_fingerprint,
    plan_marker as _plan_marker,
)

from .judge import Judgement

log = logging.getLogger(__name__)

PREFIX = "answer:pipeline:v2"


def corpus_fingerprint():
    """Vân tay rẻ của kho — đổi khi có hồ sơ mới hoặc đoạn CV được lập lại chỉ mục.

    `PersonSearchDocument` mốc thời gian tên là `indexed_at`, `CVChunk` là
    `updated_at` — hai bảng đặt tên khác nhau, và gọi nhầm tên thì `aggregate`
    ném lỗi. Trước đây khối `except` nuốt lỗi đó và trả "", tức **âm thầm tắt
    cache** mà không ai biết: đúng kiểu hỏng khó phát hiện nhất, vì mọi thứ vẫn
    chạy, chỉ là đắt gấp đôi.
    """
    from django.db.models import Count, Max

    from people.models import Document, Person
    from talent.models import CVChunk, PersonSearchDocument
    try:
        people = Person.applicants()
        persons = people.aggregate(n=Count("id"), at=Max("updated_at"))
        raw_documents = Document.objects.filter(person__in=people).aggregate(
            n=Count("id"), at=Max("updated_at"))
        docs = PersonSearchDocument.objects.filter(person__in=people).aggregate(
            n=Count("id"), at=Max("indexed_at"))
        chunks = CVChunk.objects.filter(person__in=people).aggregate(
            n=Count("id"), at=Max("updated_at"))
    except Exception:                              # noqa: BLE001
        log.warning("answer.cache: không lấy được vân tay kho, bỏ qua cache",
                    exc_info=True)
        return ""
    return _digest({"people": persons, "documents": raw_documents,
                    "search_documents": docs, "chunks": chunks})


def _as_judgement(row):
    return Judgement(
        person_id=row["person_id"], name=row.get("name", ""),
        relevant=row.get("relevant", False), confidence=row.get("confidence", 0.0),
        why=row.get("why", ""), evidence=row.get("evidence") or [],
        extracted=row.get("extracted") or {}, gap=row.get("gap", ""),
        attribute_status=row.get("attribute_status") or {}, criteria=row.get("criteria") or [])


def _prompts():
    """Đọc lúc CHẠY, không phải lúc import — vì hai lý do độc lập.

    1. `plan`/`judge` import ngược lên gói này; chốt lúc import là vòng import.
    2. Test thay `plan.SYSTEM`/`judge.SYSTEM` bằng `mock.patch.object` để kiểm
       đúng việc đổi prompt phải làm mục cache cũ hết hiệu lực. Chốt giá trị
       lúc khởi tạo thì phép kiểm ấy luôn xanh một cách giả tạo.
    """
    from talent.answer import judge, plan
    return {"plan": plan.SYSTEM, "judge": judge.SYSTEM}


_CACHE = TurnCache(
    prefix=PREFIX,
    prompts=_prompts,
    tasks=("talent_answer_plan", "talent_answer_judge", "talent_embedding"),
    corpus_fingerprint=corpus_fingerprint,
    row_to_judgement=_as_judgement,
)


def execution_fingerprint():
    return _CACHE.execution_fingerprint()


def key_for(question, *, envelope=None, user=None, query_plan=None):
    return _CACHE.key_for(question, envelope=envelope, user=user,
                          query_plan=query_plan)


def load(key):
    return _CACHE.load(key)


def save(key, judgements, retrieved):
    return _CACHE.save(key, judgements, retrieved)
