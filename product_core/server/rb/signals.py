# -*- coding: utf-8 -*-
"""Giữ chỉ mục bằng chứng khách hàng (`rb/evidence_index.py`) theo kịp dữ liệu.

Chỉ dựng TEXT sau khi giao dịch commit — rẻ, không gọi mạng, không làm chậm hay
hỏng lượt ghi vì nhà cung cấp embedding lỗi. Vector do worker nền
`embed_prospect_evidence` bù sau, cùng cách `talent/signals.py` làm cho CV.

Nhập liệu HÀNG LOẠT thì tắt `RB_EVIDENCE_INDEX_ON_SAVE` rồi chạy
`rebuild_prospect_evidence_index` một lần: lập chỉ mục theo từng lượt save nhân
số lần ghi lên nhiều lần khi nạp hàng trăm nghìn bản ghi.
"""
import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

log = logging.getLogger(__name__)


def _enabled():
    return bool(getattr(settings, "RB_EVIDENCE_INDEX_ON_SAVE", True))


def _schedule(person_id):
    if not person_id or not _enabled():
        return

    def rebuild():
        from .evidence_index import index_person
        try:
            index_person(person_id)
        except Exception:                          # noqa: BLE001
            # Chỉ mục là thứ dựng lại được; một lần lập chỉ mục hỏng không được
            # làm hỏng lượt ghi dữ liệu thật của người dùng.
            log.warning("rb.signals: lập chỉ mục bằng chứng hỏng (person=%s)",
                        person_id, exc_info=True)
    transaction.on_commit(rebuild)


def _connect(model, person_of):
    def handler(sender, instance, **kwargs):
        _schedule(person_of(instance))
    post_save.connect(handler, sender=model, weak=False,
                      dispatch_uid=f"rb-evidence-{model._meta.label}-save")
    post_delete.connect(handler, sender=model, weak=False,
                        dispatch_uid=f"rb-evidence-{model._meta.label}-delete")


def connect():
    from people.models import Person, Signal
    from social.models import SocialComment, SocialPost

    from .models import OpportunityOutcome, ProductInterest, RBProfile

    _connect(SocialPost, lambda row: row.person_id)
    _connect(SocialComment, lambda row: getattr(row.post, "person_id", None))
    _connect(Signal, lambda row: row.person_id if row.domain == Signal.DOMAIN_RB else None)
    _connect(ProductInterest, lambda row: getattr(row.profile, "person_id", None))
    _connect(OpportunityOutcome, lambda row: row.person_id)
    _connect(RBProfile, lambda row: row.person_id)

    @receiver(post_save, sender=Person, weak=False, dispatch_uid="rb-evidence-person-merge")
    def person_changed(sender, instance, **kwargs):
        # Người bị gộp phải rời chỉ mục — `index_person` xoá khi `merged_into` có giá trị.
        if instance.merged_into_id:
            _schedule(instance.pk)
