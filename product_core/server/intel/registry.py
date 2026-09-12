# -*- coding: utf-8 -*-
"""Canonical Registry — resolve giá trị thô → mã chuẩn (Master Plan §6, §21.2).

Nguyên tắc bất di bất dịch: **AI không tự tạo canonical code mới.** `resolve()`
chỉ tra alias đã `accepted`. Không khớp thì tạo một `CanonicalAlias` `proposed`
(hàng chờ) và trả `None` — code hoặc người quản trị mới nối nó vào entry.
"""
from django.db import IntegrityError

from .models import CanonicalAlias, CanonicalEntry, CanonicalNamespace
from .normalize import normalize_value


def _invalidate_talent_alias_cache():
    try:
        from talent.semantic_index import clear_registry_alias_cache
        clear_registry_alias_cache()
    except Exception:  # Talent may not be installed during migration/bootstrap.
        pass


class ResolveResult:
    __slots__ = ("entry", "alias", "created_candidate", "normalized")

    def __init__(self, entry=None, alias=None, created_candidate=False, normalized=""):
        self.entry = entry
        self.alias = alias
        self.created_candidate = created_candidate
        self.normalized = normalized

    @property
    def code(self):
        return self.entry.code if self.entry is not None else ""

    @property
    def label(self):
        return self.entry.label if self.entry is not None else ""


def get_namespace(key):
    return CanonicalNamespace.objects.filter(key=key, active=True).first()


def resolve(namespace_key, raw_value, *, propose=True, source="radar_ai", created_by=""):
    """Trả `ResolveResult`. Không bao giờ tạo `CanonicalEntry`."""
    ns = get_namespace(namespace_key)
    result = ResolveResult(normalized=str(raw_value or "").strip())
    if ns is None or not str(raw_value or "").strip():
        return result

    norm = normalize_value(raw_value, fold_diacritics=ns.fold_diacritics)
    result.normalized = norm
    if not norm:
        return result

    alias = (CanonicalAlias.objects
             .filter(namespace=ns, alias_norm=norm)
             .select_related("entry").first())
    if alias is not None:
        result.alias = alias
        if alias.status == CanonicalAlias.STATUS_ACCEPTED and alias.entry_id:
            result.entry = alias.entry
        return result

    if not propose:
        return result

    # Không khớp → đưa vào hàng chờ alias (CanonicalAlias status=proposed).
    # KHÔNG tạo CanonicalEntry.
    try:
        alias = CanonicalAlias.objects.create(
            namespace=ns, alias_norm=norm, alias_raw=str(raw_value)[:200],
            status=CanonicalAlias.STATUS_PROPOSED, source=source,
            created_by=str(created_by)[:150])
        result.created_candidate = True
    except IntegrityError:
        alias = CanonicalAlias.objects.filter(namespace=ns, alias_norm=norm).first()
    result.alias = alias
    _invalidate_talent_alias_cache()
    return result


def ensure_namespace(key, label, *, fold_diacritics=True):
    ns, _ = CanonicalNamespace.objects.get_or_create(
        key=key, defaults={"label": label, "fold_diacritics": fold_diacritics})
    return ns


def upsert_entry(namespace, code, label, *, parent_code="", attrs=None):
    ns = namespace if isinstance(namespace, CanonicalNamespace) else ensure_namespace(namespace, namespace)
    parent = None
    if parent_code:
        parent = CanonicalEntry.objects.filter(namespace=ns, code=parent_code).first()
    entry, _ = CanonicalEntry.objects.update_or_create(
        namespace=ns, code=code,
        defaults={"label": label, "parent": parent, "attrs": attrs or {}})
    return entry


def add_alias(namespace, alias_text, entry, *, source="seed", by="", note=""):
    """Nối một alias vào entry ở trạng thái `accepted` (dùng cho seed/admin)."""
    ns = namespace if isinstance(namespace, CanonicalNamespace) else ensure_namespace(namespace, namespace)
    norm = normalize_value(alias_text, fold_diacritics=ns.fold_diacritics)
    if not norm:
        return None
    alias, _ = CanonicalAlias.objects.get_or_create(
        namespace=ns, alias_norm=norm,
        defaults={"alias_raw": str(alias_text)[:200], "source": source,
                  "created_by": str(by)[:150]})
    if alias.entry_id != getattr(entry, "pk", None) or alias.status != CanonicalAlias.STATUS_ACCEPTED:
        alias.accept(entry, by=by or source, note=note)
        _invalidate_talent_alias_cache()
    return alias
