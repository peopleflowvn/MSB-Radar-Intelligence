from datetime import timedelta

from django.db import transaction
import hashlib

from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone
from people.models import Document, Person

from .models import IntelligenceDocumentTombstone, TalentProfile
from .semantic_index import index_person


def _index_on_save():
    """Nhập liệu HÀNG LOẠT nên tắt cờ này rồi chạy `rebuild_talent_vector_index`.

    Lập chỉ mục theo từng lượt save là đúng cho luồng thường (dữ liệu mới tìm được
    ngay), nhưng khi nạp một triệu bản ghi thì nó nhân số lần ghi lên nhiều lần.
    """
    from django.conf import settings
    return bool(getattr(settings, "TALENT_INDEX_ON_SAVE", True))


def _after_commit(person_id):
    if not _index_on_save():
        return

    def rebuild():
        index_person(person_id)
        # KHÔNG gọi embedding trong request: tốn token, phụ thuộc mạng, và một
        # provider lỗi sẽ làm hỏng lượt upload. Ở đây chỉ dựng text/chunk; vector
        # do worker nền `embed_talent_index` bù theo `embedding_fingerprint`.
        from .vector_index import index_person as index_vector_person
        index_vector_person(person_id, with_embeddings=False)
    transaction.on_commit(rebuild)


@receiver(post_save, sender=TalentProfile)
def profile_index_changed(sender, instance, **kwargs):
    _after_commit(instance.person_id)


@receiver(post_save, sender=Document)
def document_index_changed(sender, instance, **kwargs):
    _after_commit(instance.person_id)
    if instance.person.merged_into_id or not instance.person.is_applicant:
        _record_tombstone(instance)


def _record_tombstone(document):
    text = document.best_text or ""
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    IntelligenceDocumentTombstone.objects.create(
        document_id=document.pk,
        person_id=document.person_id,
        version=content_hash,
        content_hash=content_hash,
        source=document.source or "radar",
        document_type=document.document_type,
        deleted_at=timezone.now(),
    )


@receiver(pre_delete, sender=Document)
def document_deleted(sender, instance, **kwargs):
    _record_tombstone(instance)


@receiver(pre_save, sender=Person)
def remember_intelligence_visibility(sender, instance, **kwargs):
    if instance.pk:
        previous = Person.objects.filter(pk=instance.pk).values(
            "is_applicant", "merged_into_id").first()
        instance._intelligence_was_visible = bool(
            previous and previous["is_applicant"] and previous["merged_into_id"] is None)


@receiver(post_save, sender=Person)
def person_intelligence_visibility_changed(sender, instance, created, **kwargs):
    if created:
        return
    was_visible = getattr(instance, "_intelligence_was_visible", None)
    is_visible = instance.is_applicant and instance.merged_into_id is None
    if was_visible is None or was_visible == is_visible:
        return
    documents = list(instance.documents.select_related("primary_text_version"))
    if not is_visible:
        for document in documents:
            _record_tombstone(document)
    else:
        # Reactivation must appear after the tombstone in the ordered feed.
        # `timezone.now()` can equal the tombstone timestamp on a fast database.
        # Advance past the newest tombstone deterministically so a cursor that has
        # consumed the delete cannot skip the reactivated document.
        document_ids = [row.pk for row in documents]
        latest_tombstone = (IntelligenceDocumentTombstone.objects
                            .filter(document_id__in=document_ids)
                            .order_by("-deleted_at", "-pk")
                            .values_list("deleted_at", flat=True)
                            .first())
        reactivated_at = timezone.now()
        if latest_tombstone is not None:
            reactivated_at = max(reactivated_at, latest_tombstone + timedelta(microseconds=1))
        Document.objects.filter(pk__in=document_ids).update(updated_at=reactivated_at)
