# -*- coding: utf-8 -*-
"""Tự động xử lý hàng chờ alias `proposed` — không bao giờ tạo canonical mới.

`intel.registry.resolve()` đã tự nối các alias trùng TUYỆT ĐỐI (cùng
`alias_norm`) ngay khi tạo. Alias còn ở `proposed` là alias KHÔNG trùng tuyệt
đối với alias/entry nào đã có — phần lớn là lỗi chính tả, thiếu/thừa từ, hoặc
thật sự là giá trị mới chưa từng gặp.

`auto_resolve` chỉ NỐI vào `CanonicalEntry` đã tồn tại khi độ khớp đủ cao
(xem `intel/matching.py`); dưới ngưỡng thì để nguyên `proposed` cho người xem
— không đoán, không tạo entry mới trong mọi trường hợp (nguyên tắc bất di bất
dịch ở `intel/registry.py`). Mỗi lần nối tự động đều ghi `source`/`note` để
truy vết, và `CanonicalAlias.accept()` tự lưu `previous` nên vẫn lật lại được
qua Django admin nếu một khớp tự động hoá ra sai.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .matching import Candidate, best_match
from .models import CanonicalAlias, CanonicalEntry
from .normalize import normalize_value

DEFAULT_THRESHOLD = 0.90
AUTO_SOURCE = "ai_auto"


@dataclass
class AliasDecision:
    alias_id: int
    namespace: str
    alias_norm: str
    decision: str  # "auto_accepted" | "needs_human" | "no_candidates"
    score: float = 0.0
    entry_code: str = ""
    suggested_entry_code: str = ""


@dataclass
class AutoResolveReport:
    threshold: float
    apply: bool
    decisions: list = field(default_factory=list)

    @property
    def auto_accepted(self):
        return [d for d in self.decisions if d.decision == "auto_accepted"]

    @property
    def needs_human(self):
        return [d for d in self.decisions if d.decision != "auto_accepted"]

    def summary(self) -> dict:
        return {
            "threshold": self.threshold, "apply": self.apply,
            "total_considered": len(self.decisions),
            "auto_accepted": len(self.auto_accepted),
            "needs_human": len(self.needs_human),
        }


def _namespace_candidates(namespace_id) -> list:
    """Ứng viên nối alias `proposed` vào: code/label của entry, alias đã duyệt."""
    candidates = []
    for entry in CanonicalEntry.objects.filter(namespace_id=namespace_id, active=True):
        candidates.append(Candidate(entry.code.strip().lower(), entry.pk, entry.code, "code"))
        norm_label = normalize_value(entry.label)
        if norm_label:
            candidates.append(Candidate(norm_label, entry.pk, entry.code, "label"))
    for alias in (CanonicalAlias.objects
                  .filter(namespace_id=namespace_id, status=CanonicalAlias.STATUS_ACCEPTED,
                          entry__isnull=False)
                  .select_related("entry")):
        candidates.append(Candidate(alias.alias_norm, alias.entry_id, alias.entry.code, "alias"))
    return candidates


def auto_resolve(*, namespace_key: str = "", threshold: float = DEFAULT_THRESHOLD,
                 limit: Optional[int] = None, apply: bool = False,
                 by: str = AUTO_SOURCE) -> AutoResolveReport:
    """Duyệt alias `proposed`, nối vào entry đã có khi đủ tin cậy.

    `apply=False` (mặc định) chỉ tính điểm và báo cáo — không ghi CSDL.
    """
    report = AutoResolveReport(threshold=threshold, apply=apply)

    queryset = (CanonicalAlias.objects
                .filter(status=CanonicalAlias.STATUS_PROPOSED)
                .select_related("namespace").order_by("namespace_id", "pk"))
    if namespace_key:
        queryset = queryset.filter(namespace__key=namespace_key)
    if limit:
        queryset = queryset[:limit]

    candidates_by_namespace: dict = {}
    for alias in queryset:
        ns_id = alias.namespace_id
        if ns_id not in candidates_by_namespace:
            candidates_by_namespace[ns_id] = _namespace_candidates(ns_id)
        candidates = candidates_by_namespace[ns_id]

        match = best_match(alias.alias_norm, candidates)
        if match is None:
            report.decisions.append(AliasDecision(
                alias_id=alias.pk, namespace=alias.namespace.key,
                alias_norm=alias.alias_norm, decision="no_candidates"))
            continue

        if match.score >= threshold:
            decision = AliasDecision(
                alias_id=alias.pk, namespace=alias.namespace.key,
                alias_norm=alias.alias_norm, decision="auto_accepted",
                score=round(match.score, 4), entry_code=match.candidate.entry_code)
            if apply:
                entry = CanonicalEntry.objects.get(pk=match.candidate.entry_id)
                alias.accept(entry, by=by, note=(
                    f"auto: score={match.score:.3f} matched='{match.candidate.text}' "
                    f"({match.candidate.origin})")[:300])
                # Ứng viên vòng sau trong CÙNG namespace nên thấy alias vừa nối,
                # để không tự nối trùng lặp nhiều alias gần giống nhau vào các
                # entry khác nhau chỉ vì được xử lý trước/sau nhau.
                candidates.append(Candidate(alias.alias_norm, entry.pk, entry.code, "alias"))
        else:
            decision = AliasDecision(
                alias_id=alias.pk, namespace=alias.namespace.key,
                alias_norm=alias.alias_norm, decision="needs_human",
                score=round(match.score, 4), suggested_entry_code=match.candidate.entry_code)
        report.decisions.append(decision)

    if apply and report.auto_accepted:
        from talent.semantic_index import clear_registry_alias_cache
        clear_registry_alias_cache()

    return report
