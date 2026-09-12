# -*- coding: utf-8 -*-
"""Hàng đợi trích xuất — DB-backed, tách khỏi Download/Parsing (Master Plan §21.3).

Signal chỉ `enqueue()`. Worker `claim_batch()` theo batch nhỏ, có lease, retry,
idempotency, safe-stop. Chưa dùng Celery/Redis; có thể chuyển sau mà không đụng
`intel.extraction`.
"""
import logging
import os
import socket
import time

from django.db import IntegrityError
from django.utils import timezone

from people.models import Person

from .extraction import run_for_person
from .models import ExtractionJob

log = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 900


def enqueue(person, *, use_ai=True, batch=""):
    """Đảm bảo Person có một job chưa hoàn tất. Trả (job, created)."""
    person_id = getattr(person, "pk", person)
    existing = ExtractionJob.objects.filter(
        person_id=person_id,
        status__in=[ExtractionJob.STATUS_QUEUED, ExtractionJob.STATUS_LEASED]).first()
    if existing:
        return existing, False
    try:
        return ExtractionJob.objects.create(
            person_id=person_id, use_ai=use_ai, batch=batch[:64]), True
    except IntegrityError:
        return ExtractionJob.objects.filter(
            person_id=person_id,
            status__in=[ExtractionJob.STATUS_QUEUED, ExtractionJob.STATUS_LEASED]).first(), False


def enqueue_many(person_ids, *, use_ai=True, batch=""):
    created = 0
    for pid in person_ids:
        _, was_created = enqueue(pid, use_ai=use_ai, batch=batch)
        created += int(was_created)
    return created


def _worker_name():
    return f"{socket.gethostname()}:{os.getpid()}"[:80]


def _claimable_q(now):
    from django.db.models import Q
    return Q(status=ExtractionJob.STATUS_QUEUED) | Q(
        status=ExtractionJob.STATUS_LEASED, lease_until__lt=now)


def claim_batch(limit, *, worker="", lease_seconds=DEFAULT_LEASE_SECONDS):
    """Lấy tối đa `limit` job: queued, hoặc leased nhưng hết hạn lease.

    Compare-and-set (`filter(pk, status).update(...)`) đảm bảo hai worker không
    claim trùng một job kể cả khi không có `SELECT ... FOR UPDATE SKIP LOCKED`.
    """
    worker = worker or _worker_name()
    now = timezone.now()
    deadline = now + timezone.timedelta(seconds=lease_seconds)
    candidates = list(
        ExtractionJob.objects.filter(_claimable_q(now))
        .order_by("enqueued_at", "pk")[:limit])
    claimed = []
    for job in candidates:
        updated = ExtractionJob.objects.filter(pk=job.pk, status=job.status).update(
            status=ExtractionJob.STATUS_LEASED, worker=worker,
            lease_until=deadline, attempts=job.attempts + 1)
        if updated:
            job.refresh_from_db()
            claimed.append(job)
    return claimed


def process_job(job, *, adapter=None):
    """Chạy extraction cho một job đã claim. Cập nhật trạng thái."""
    try:
        person = Person.objects.get(pk=job.person_id)
    except Person.DoesNotExist:
        job.status = ExtractionJob.STATUS_FAILED
        job.error = "Person đã bị xoá"
        job.save(update_fields=["status", "error", "updated_at"])
        return job

    run = run_for_person(person, use_ai=job.use_ai, adapter=adapter, job=job)
    job.last_run = run
    if run.status == run.STATUS_DONE:
        job.status = ExtractionJob.STATUS_DONE
        job.error = ""
    elif job.attempts >= job.max_attempts:
        job.status = ExtractionJob.STATUS_FAILED
        job.error = run.error[:500]
    else:
        job.status = ExtractionJob.STATUS_QUEUED   # thử lại lượt sau
        job.lease_until = None
        job.error = run.error[:500]
    job.save(update_fields=["status", "error", "last_run", "lease_until", "updated_at"])
    return job


def run_worker(*, batch_size=10, once=False, worker="", stop_file="", adapter=None,
               idle_sleep=5.0, on_progress=None):
    """Vòng lặp worker. `stop_file` tồn tại ⇒ dừng an toàn sau job hiện tại."""
    worker = worker or _worker_name()
    processed = {"done": 0, "failed": 0, "requeued": 0}
    while True:
        if stop_file and os.path.exists(stop_file):
            log.info("Thấy stop-file %s — dừng an toàn.", stop_file)
            break
        jobs = claim_batch(batch_size, worker=worker)
        if not jobs:
            if once:
                break
            time.sleep(idle_sleep)
            continue
        for job in jobs:
            result = process_job(job, adapter=adapter)
            key = {"done": "done", "failed": "failed"}.get(result.status, "requeued")
            processed[key] += 1
            if on_progress:
                on_progress(result, processed)
        if once:
            break
    return processed
