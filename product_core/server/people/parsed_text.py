# -*- coding: utf-8 -*-
"""Lưu phiên bản text CV, khử trùng theo Person mà không làm mất lịch sử parser."""
import hashlib
import re
import unicodedata

from django.db import transaction
from django.utils import timezone

from .models import DocumentTextLink, ParsedTextVersion


def normalize_text(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


@transaction.atomic
def save_parsed_text(document, text, origin, quality_score=0.0, provider="", model=""):
    normalized = normalize_text(text)
    if not normalized:
        return None, False
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    version, created = ParsedTextVersion.objects.get_or_create(
        person_id=document.person_id, text_hash=digest,
        defaults={"text": normalized, "text_length": len(normalized)})
    link, _ = DocumentTextLink.objects.get_or_create(
        document=document, text_version=version,
        defaults={"origins": [origin], "provider": provider[:40], "model": model[:100],
                  "quality_score": quality_score})
    changed = []
    origins = list(link.origins or [])
    if origin not in origins:
        origins.append(origin)
        link.origins = origins
        changed.append("origins")
    if quality_score > link.quality_score:
        link.quality_score = quality_score
        link.provider = provider[:40]
        link.model = model[:100]
        changed += ["quality_score", "provider", "model"]
    if changed:
        link.save(update_fields=list(dict.fromkeys(changed)) + ["updated_at"])

    current = document.primary_text_version
    current_quality = document.quality_score if current else -1
    should_promote = (current is None or quality_score > current_quality or
                      (quality_score == current_quality and len(normalized) > document.text_length))
    if should_promote:
        document.primary_text_version = version
        document.text_length = len(normalized)
        document.quality_score = quality_score
        document.parse_provider = provider[:40]
        document.parse_model = model[:100]
    document.parsed_text = ""  # trường tương thích cũ; text thật chỉ lưu một lần ở version
    document.parse_status = document.PARSE_DONE
    document.parse_error = ""
    document.parsed_at = timezone.now()
    fields = ["parsed_text", "parse_status", "parse_error", "parsed_at", "updated_at"]
    if should_promote:
        fields += ["primary_text_version", "text_length", "quality_score",
                   "parse_provider", "parse_model"]
    document.save(update_fields=fields)
    return version, created
