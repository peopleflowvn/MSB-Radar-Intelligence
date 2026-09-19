# -*- coding: utf-8 -*-
"""Cache lượt hỏi của Growth — khung nằm ở `core/answer/cache.py`.

Chỉ phần PHỤ THUỘC KHO KHÁCH HÀNG ở đây. Hai điểm khác Talent đáng ghi:

**Vân tay kho gồm `Relationship`.** Bên Talent, vân tay chỉ cần biết hồ sơ và
đoạn CV đổi. Ở đây một khách bật cờ `do_not_contact` là một thay đổi làm SAI mọi
phán đoán đã lưu về người đó — dù không một dòng bằng chứng nào đổi. Không đưa
`Relationship` vào vân tay thì cache phục vụ tên một người vừa xin không liên hệ
thêm sáu tiếng nữa. (`aggregate.py` vẫn có lưới thứ hai; đây là lưới thứ nhất.)

**Vân tay kho gồm `OpportunityOutcome`.** Kết quả tiếp cận mới ("khách vừa nói
không quan tâm") đổi thẳng kết luận của ③. Nó phải làm cache hết hiệu lực.

**Shape `portfolio` KHÔNG dùng chung mục giữa các RM** — đã được bảo đảm vì khoá
có người hỏi. Ghi ra vì đây là shape duy nhất mà việc đó là bắt buộc về đúng/sai,
chứ không chỉ là lưới đỡ phòng xa như bên Talent.
"""
from __future__ import annotations

import logging

from core.answer.cache import TurnCache, digest

from .judge import from_row

log = logging.getLogger(__name__)

PREFIX = "answer:prospect:v1"


def corpus_fingerprint():
    from django.db.models import Count, Max

    from people.models import Relationship, Signal
    from social.models import SocialPost
    from ..models import (OpportunityOutcome, ProductInterest, ProspectEvidenceChunk,
                          RBOpportunity, RBProfile)

    try:
        parts = {
            "profiles": RBProfile.objects.aggregate(n=Count("id"), at=Max("updated_at")),
            "interests": ProductInterest.objects.aggregate(n=Count("id"), at=Max("created_at")),
            "signals": Signal.objects.filter(domain=Signal.DOMAIN_RB).aggregate(
                n=Count("id"), at=Max("created_at")),
            "posts": SocialPost.objects.exclude(person__isnull=True).aggregate(
                n=Count("id"), at=Max("updated_at")),
            "outcomes": OpportunityOutcome.objects.aggregate(n=Count("id"), at=Max("created_at")),
            "opportunities": RBOpportunity.objects.aggregate(n=Count("id"), at=Max("updated_at")),
            # Lập chỉ mục lại / có vector mới đổi thứ ② tìm thấy.
            "evidence_index": ProspectEvidenceChunk.objects.aggregate(
                n=Count("id"), at=Max("updated_at")),
            # Xem docstring: cờ DNC đổi thì mọi phán đoán về người đó phải chết.
            "relationships": Relationship.objects.filter(domain=Signal.DOMAIN_RB).aggregate(
                n=Count("id"), at=Max("updated_at")),
        }
    except Exception:                              # noqa: BLE001
        log.warning("rb.answer.cache: không lấy được vân tay kho, bỏ qua cache",
                    exc_info=True)
        return ""
    return digest(parts)


def _prompts():
    from . import judge, plan
    return {"plan": plan.SYSTEM, "judge": judge.SYSTEM}


def _extra_plan_marker(query_plan):
    """Trường riêng của `ProspectPlan` mà `core` không biết tới."""
    return {"products": sorted(getattr(query_plan, "products", None) or []),
            "filters": dict(sorted((getattr(query_plan, "filters", None) or {}).items()))}


_CACHE = TurnCache(
    prefix=PREFIX,
    prompts=_prompts,
    tasks=("rb_prospect_search", "rb_answer_judge"),
    corpus_fingerprint=corpus_fingerprint,
    row_to_judgement=from_row,
    extra_plan_marker=_extra_plan_marker,
)


def key_for(question, *, envelope=None, user=None, query_plan=None):
    return _CACHE.key_for(question, envelope=envelope, user=user, query_plan=query_plan)


def load(key):
    return _CACHE.load(key)


def save(key, judgements, retrieved):
    return _CACHE.save(key, judgements, retrieved)
