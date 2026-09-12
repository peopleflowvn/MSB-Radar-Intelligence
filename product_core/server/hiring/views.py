# -*- coding: utf-8 -*-
"""API tuyển dụng và CRM shortlist.

Luồng:

    Tạo nhu cầu / dán JD → tìm ứng viên → đánh giá Phù hợp / Không phù hợp
    → hiệu chỉnh → shortlist → **Nhờ recruiter săn**

Các endpoint HiringNeed cũ được giữ để tương thích dữ liệu. Giao diện vận hành mới
dùng `/hunts/` như worklist do Recruiter/RM trực tiếp tạo và quản lý.
"""
import logging
from datetime import datetime, time, timedelta

from accounts import roles
from accounts.permissions import RequiresCandidateWork, RequiresRecruiting
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from core.models import WorkflowStage
from people.models import Interaction, Person, Relationship, Signal
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from talent import scoring
from talent import search as search_module
from talent import semantic
from talent.serializers import TalentCardSerializer
from core.workflows import validate_stage

from . import calibration as calibration_module
from . import jd as jd_module
from . import metrics as metrics_module
from . import outreach as outreach_module
from .models import (Candidacy, HiringNeed, HuntCandidate,
                     HuntCandidateStatusEvent, HuntRequest)
from .serializers import (CandidacySerializer, HiringNeedSerializer,
                          HuntCandidateSerializer, HuntRequestSerializer)

log = logging.getLogger(__name__)


def _can_manage_all_work(request_user):
    return bool(roles.roles_of(request_user) & {roles.MANAGER, roles.ADMIN})


def _can_edit_candidate(candidate, request_user):
    return (_can_manage_all_work(request_user)
            or candidate.assigned_to_id == request_user.pk)


def _parse_id(value, label):
    if value in (None, ""):
        return None, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"{label} không hợp lệ."
    if parsed <= 0:
        return None, f"{label} không hợp lệ."
    return parsed, None


# ---------------- Nhu cầu tuyển dụng ----------------

@api_view(["GET", "POST"])
@permission_classes([RequiresRecruiting])
def hiring_need_list(request):
    if request.method == "POST":
        title = str(request.data.get("title") or "").strip()
        jd_text = str(request.data.get("jd_text") or "").strip()
        if not title and not jd_text:
            return Response({"detail": "Cần tên vị trí hoặc nội dung JD."},
                            status=status.HTTP_400_BAD_REQUEST)

        need = HiringNeed(
            title=title[:200] or "(chưa đặt tên)",
            department=str(request.data.get("department") or "")[:150],
            jd_text=jd_text[:20000],
            owner=request.user if request.user.is_authenticated else None,
            status=HiringNeed.STATUS_OPEN)

        # Dán JD thì rút tiêu chí luôn — đó là lý do người ta dán vào.
        parsed = None
        if jd_text:
            parsed = jd_module.parse_jd(jd_text, title=title)
            need.criteria = parsed.criteria
            need.criteria_fallback = parsed.fallback
            if not title and parsed.title:
                need.title = parsed.title[:200]
        need.save()
        return Response(HiringNeedSerializer(need).data,
                        status=status.HTTP_201_CREATED)

    queryset = HiringNeed.objects.all()
    if request.query_params.get("mine") == "1":
        queryset = queryset.filter(owner=request.user)
    if request.query_params.get("status"):
        queryset = queryset.filter(status=request.query_params["status"])
    return Response({"results": HiringNeedSerializer(queryset[:100], many=True).data})


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([RequiresRecruiting])
def hiring_need_detail(request, need_id):
    need = get_object_or_404(HiringNeed, pk=need_id)

    if request.method == "DELETE":
        need.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if request.method == "PATCH":
        for field in ("title", "department", "status"):
            if field in request.data:
                setattr(need, field, str(request.data[field])[:200])
        if "criteria" in request.data and isinstance(request.data["criteria"], dict):
            need.criteria = request.data["criteria"]
        if "jd_text" in request.data:
            need.jd_text = str(request.data["jd_text"])[:20000]
        need.save()

    return Response(HiringNeedSerializer(need).data)


@api_view(["POST"])
@permission_classes([RequiresRecruiting])
def parse_jd(request, need_id):
    """Rút lại tiêu chí từ JD. Dùng khi HM sửa JD rồi muốn cập nhật tiêu chí."""
    need = get_object_or_404(HiringNeed, pk=need_id)
    if not need.jd_text.strip():
        return Response({"detail": "Chưa có nội dung JD."},
                        status=status.HTTP_400_BAD_REQUEST)

    parsed = jd_module.parse_jd(need.jd_text, title=need.title)
    need.criteria = parsed.criteria
    need.criteria_fallback = parsed.fallback
    need.save(update_fields=["criteria", "criteria_fallback", "updated_at"])
    return Response({**HiringNeedSerializer(need).data,
                     "parse_error": parsed.error})


# ---------------- Đề xuất & đánh giá ----------------

@api_view(["GET"])
@permission_classes([RequiresRecruiting])
def suggestions(request, need_id):
    """Ứng viên phù hợp cho vị trí này, đã xếp theo trọng số đã hiệu chỉnh.

    Ghi lại `Candidacy` cho từng người được đề xuất, kèm ảnh chụp điểm và từng
    chiều. Không lưu thì hiệu chỉnh (mục 21) không có gì để học.
    """
    need = get_object_or_404(HiringNeed, pk=need_id)
    limit = min(50, max(1, int(request.query_params.get("limit") or 20)))

    people, strict_count = _recall(need.criteria)

    # Chấm trước độ gần chức danh cho CẢ danh sách, trong một lượt gọi. Không có
    # bước này thì `scoring` lùi về so khớp chuỗi và "BI Developer" xếp bét bảng
    # dù làm gần đúng việc cần tuyển.
    _warm_titles(need.criteria, people)

    scored = [(person, scoring.score_person(person, need.criteria))
              for person in people]

    weights = need.learned_weights or None
    if weights:
        scored = calibration_module.rank(scored, weights)
    else:
        scored.sort(key=lambda item: item[1]["score"], reverse=True)
    scored = scored[:limit]

    existing = {c.person_id: c for c in need.candidacies.all()}
    rows = []
    for person, result in scored:
        candidacy = existing.get(person.pk)
        if candidacy is None:
            candidacy = Candidacy.objects.create(
                hiring_need=need, person=person,
                score_snapshot=result["score"],
                dimensions_snapshot=result["dimensions"])
        rows.append({
            **TalentCardSerializer(person).data,
            "candidacy": CandidacySerializer(candidacy).data,
            "match": {"score": result["score"], "dimensions": result["dimensions"],
                      "facts": result["facts"], "unknowns": result["unknowns"]},
        })

    return Response({
        "hiring_need": HiringNeedSerializer(need).data,
        "count": len(rows),
        # Bao nhiêu người khớp ĐỦ tiêu chí, bao nhiêu người được nới vào. Không
        # nói ra thì con số ở đây lệch với ô tìm kiếm mà không ai hiểu vì sao —
        # và điều đầu tiên người dùng nghĩ là hệ thống đếm sai.
        "strict_count": min(strict_count, len(rows)),
        "results": rows,
    })


@api_view(["POST"])
@permission_classes([RequiresRecruiting])
def mark_candidacy(request, need_id):
    """HM đánh dấu Phù hợp / Không phù hợp / Shortlist."""
    need = get_object_or_404(HiringNeed, pk=need_id)
    person = get_object_or_404(Person, pk=request.data.get("person_id"))
    state = str(request.data.get("state") or "")
    if state not in dict(Candidacy.STATE_CHOICES):
        return Response({"detail": f"Trạng thái không hợp lệ: {state}"},
                        status=status.HTTP_400_BAD_REQUEST)

    candidacy, _ = Candidacy.objects.get_or_create(hiring_need=need, person=person)
    candidacy.mark(state, user=request.user if request.user.is_authenticated else None,
                   note=str(request.data.get("note") or ""))

    # Cũng ghi vào timeline của Person: đánh giá của HM là dữ kiện nghiệp vụ về
    # con người đó, không chỉ về vị trí này.
    Interaction.objects.create(
        person=person, action=f"hm_{state}",
        actor=request.user if request.user.is_authenticated else None,
        detail={"hiring_need": need.title, "hiring_need_id": need.pk})

    return Response(CandidacySerializer(candidacy).data)


@api_view(["POST"])
@permission_classes([RequiresRecruiting])
def calibrate(request, need_id):
    """Học trọng số từ đánh giá của HM rồi xếp lại (Master Plan mục 21)."""
    need = get_object_or_404(HiringNeed, pk=need_id)
    result = calibration_module.calibrate(need)

    if result.applied:
        from django.utils import timezone
        need.learned_weights = result.weights
        need.calibrated_at = timezone.now()
        need.save(update_fields=["learned_weights", "calibrated_at", "updated_at"])

    return Response(result.as_dict(),
                    status=status.HTTP_200_OK if result.applied
                    else status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([RequiresRecruiting])
def reset_calibration(request, need_id):
    need = get_object_or_404(HiringNeed, pk=need_id)
    need.learned_weights = {}
    need.calibrated_at = None
    need.save(update_fields=["learned_weights", "calibrated_at", "updated_at"])
    return Response(HiringNeedSerializer(need).data)


# ---------------- Nhờ recruiter săn ----------------

@api_view(["POST"])
@permission_classes([RequiresRecruiting])
@transaction.atomic
def request_hunt(request, need_id):
    """CTA cốt lõi: HM bàn giao shortlist sang Recruiter (Master Plan mục 20)."""
    need = get_object_or_404(HiringNeed, pk=need_id)

    person_ids = request.data.get("person_ids")
    if person_ids:
        people = list(Person.objects.filter(pk__in=person_ids))
    else:
        # Không chỉ định thì lấy toàn bộ shortlist — đó là ý định thông thường.
        people = [c.person for c in
                  need.candidacies.filter(state=Candidacy.STATE_SHORTLISTED)
                  .select_related("person")]

    if not people:
        return Response(
            {"detail": "Chưa có ứng viên nào trong shortlist để nhờ săn."},
            status=status.HTTP_400_BAD_REQUEST)

    hunt = HuntRequest.objects.create(
        hiring_need=need,
        title=need.title,
        requested_by=request.user if request.user.is_authenticated else None,
        message=str(request.data.get("message") or "")[:2000])
    hunt.people.set(people)

    need.status = HiringNeed.STATUS_HUNTING
    need.save(update_fields=["status", "updated_at"])

    for person in people:
        Interaction.objects.create(
            person=person, action="hunt_requested",
            actor=request.user if request.user.is_authenticated else None,
            detail={"hiring_need": need.title, "hunt_request_id": hunt.pk})

    return Response(HuntRequestSerializer(hunt).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([RequiresRecruiting])
def metrics(request):
    """Chỉ số hiệu quả Talent Radar (Master Plan mục 50)."""
    return Response({"metrics": metrics_module.collect(),
                     "stale_days": metrics_module.STALE_DAYS})


@api_view(["GET", "POST"])
@permission_classes([RequiresCandidateWork])
def hunt_list(request):
    """Danh sách là container công việc; inbox phẳng nằm tại ``hunt_tasks``."""
    if request.method == "POST":
        title = str(request.data.get("title") or "").strip()
        raw_ids = request.data.get("person_ids") or []
        priority = str(request.data.get("priority") or "normal")
        if not isinstance(raw_ids, (list, tuple)):
            return Response({"detail": "Danh sách ứng viên không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        if priority not in {"low", "normal", "high", "urgent"}:
            return Response({"detail": "Mức ưu tiên không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            person_ids = list(dict.fromkeys(int(value) for value in raw_ids))
        except (TypeError, ValueError):
            return Response({"detail": "Danh sách ứng viên không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        people = list(Person.objects.filter(pk__in=person_ids, merged_into__isnull=True))
        if not title:
            return Response({"detail": "Cần đặt tên shortlist."},
                            status=status.HTTP_400_BAD_REQUEST)
        user = request.user if request.user.is_authenticated else None
        hunt = HuntRequest.objects.create(
            title=title[:200], requested_by=user, assigned_to=user,
            status=HuntRequest.STATUS_IN_PROGRESS,
            priority=priority,
            message=str(request.data.get("message") or "")[:2000])
        HuntCandidate.objects.bulk_create([
            HuntCandidate(hunt_request=hunt, person=person, assigned_to=user,
                          assigned_to_name=str(user)[:150] if user else "")
            for person in people])
        for person in people:
            Interaction.objects.create(
                person=person, action="shortlist_added", actor=user,
                detail={"shortlist": hunt.title, "hunt_request_id": hunt.pk})
        return Response(HuntRequestSerializer(hunt).data,
                        status=status.HTTP_201_CREATED)

    queryset = HuntRequest.objects.select_related("hiring_need")
    scope = request.query_params.get("scope")
    candidate_rows = (HuntCandidate.objects.select_related("person", "assigned_to")
                      .prefetch_related("status_events"))
    open_candidate = ~Q(state__in=HuntCandidate.CLOSED_STATES)
    active_states = [value for value, _ in HuntCandidate.STATE_CHOICES
                     if value not in HuntCandidate.CLOSED_STATES]

    if scope == "mine":
        candidate_rows = candidate_rows.filter(open_candidate, assigned_to=request.user)
        queryset = queryset.filter(status__in=HuntRequest.OPEN_STATUSES,
                                   candidates__assigned_to=request.user)
    elif scope == "team":
        # Tương thích client cũ nhưng không còn mở góc nhìn theo dõi toàn đội.
        candidate_rows = candidate_rows.filter(open_candidate, assigned_to=request.user)
        queryset = queryset.filter(status__in=HuntRequest.OPEN_STATUSES,
                                   candidates__state__in=active_states,
                                   candidates__assigned_to=request.user)
    elif scope == "followup":
        candidate_rows = candidate_rows.filter(
            open_candidate, assigned_to=request.user, next_action_at__lte=timezone.now())
        queryset = queryset.filter(
            status__in=HuntRequest.OPEN_STATUSES, candidates__assigned_to=request.user,
            candidates__next_action_at__lte=timezone.now(),
            candidates__state__in=active_states)
    elif scope == "unassigned":
        candidate_rows = candidate_rows.filter(open_candidate, assigned_to__isnull=True)
        queryset = queryset.filter(
            status__in=HuntRequest.OPEN_STATUSES,
            candidates__assigned_to__isnull=True,
            candidates__state__in=active_states)
    elif scope == "completed":
        candidate_rows = candidate_rows.filter(
            state__in=HuntCandidate.CLOSED_STATES, assigned_to=request.user)
        queryset = queryset.filter(
            candidates__state__in=HuntCandidate.CLOSED_STATES,
            candidates__assigned_to=request.user)

    pool_id, pool_error = _parse_id(request.query_params.get("pool"), "Nhóm ứng viên")
    if pool_error:
        return Response({"detail": pool_error}, status=status.HTTP_400_BAD_REQUEST)
    if pool_id:
        candidate_rows = candidate_rows.filter(person__pool_memberships__pool_id=pool_id,
                                               person__pool_memberships__pool__domain="talent")
        queryset = queryset.filter(candidates__person__pool_memberships__pool_id=pool_id,
                                   candidates__person__pool_memberships__pool__domain="talent")

    if scope in {"mine", "team", "followup", "unassigned", "completed"} or pool_id:
        queryset = queryset.distinct().prefetch_related(
            Prefetch("candidates", queryset=candidate_rows,
                     to_attr="_visible_candidates"),
            Prefetch("candidates", queryset=HuntCandidate.objects.all(),
                     to_attr="_all_candidates"))
    else:
        queryset = queryset.prefetch_related(
            "candidates__person", "candidates__status_events")

    if request.query_params.get("mine") == "1":
        queryset = queryset.filter(assigned_to=request.user)
    if request.query_params.get("open") == "1":
        queryset = queryset.filter(status__in=HuntRequest.OPEN_STATUSES)
    if request.query_params.get("status"):
        queryset = queryset.filter(status=request.query_params["status"])

    try:
        limit = max(1, min(int(request.query_params.get("limit") or 50), 200))
        offset = max(0, int(request.query_params.get("offset") or 0))
    except (TypeError, ValueError):
        return Response({"detail": "Phân trang không hợp lệ."}, status=400)
    count = queryset.count()
    return Response({"count": count, "limit": limit, "offset": offset,
                     "results": HuntRequestSerializer(
                         queryset[offset:offset + limit], many=True).data})


def _talent_relationship(person):
    rows = getattr(person, "_talent_relationships", None)
    if rows is None:
        rows = person.relationships.filter(domain=Signal.DOMAIN_TALENT)
    return next(iter(rows), None)


def _relationship_data(relation):
    if relation is None:
        return {
            "state": "new", "owner": "", "owner_id": None,
            "interest_level": 0, "next_action": "", "next_action_at": None,
            "do_not_contact": False,
        }
    return {
        "state": relation.state, "owner": relation.owner,
        "owner_id": relation.owner_user_id,
        "interest_level": relation.interest_level,
        "next_action": relation.next_action,
        "next_action_at": relation.next_action_at,
        "do_not_contact": relation.do_not_contact,
    }


def _task_stage(candidate, catalog, now):
    stage = catalog.get(candidate.state)
    due_at = None
    if stage and stage.sla_hours and not stage.is_terminal:
        due_at = candidate.stage_entered_at + timedelta(hours=stage.sla_hours)
    return {
        "label": stage.label if stage else candidate.get_state_display(),
        "color": stage.color if stage else "#64748b",
        "sla_due_at": due_at,
        "is_overdue": bool(due_at and due_at <= now),
    }


def _person_worklists(person, catalog, now, exclude_pk=None):
    rows = getattr(person, "_active_hunt_candidates", [])
    result = []
    for row in rows:
        if row.pk == exclude_pk:
            continue
        stage = _task_stage(row, catalog, now)
        result.append({
            "hunt_id": row.hunt_request_id,
            "title": row.hunt_request.title or "Danh sách ứng viên",
            "state": row.state, "state_label": stage["label"],
            "assigned_to_name": row.assigned_to_name,
        })
    return result


@api_view(["GET"])
@permission_classes([RequiresCandidateWork])
def hunt_tasks(request):
    """Inbox phẳng của Recruiter: công việc pipeline và quan hệ đến hạn cùng một nơi."""
    now = timezone.now()
    tomorrow = timezone.localdate() + timedelta(days=1)
    day_end = timezone.make_aware(datetime.combine(tomorrow, time.min))
    scope = str(request.query_params.get("scope") or "all")
    if scope not in {"all", "overdue", "today", "unassigned", "completed"}:
        return Response({"detail": "Phạm vi công việc không hợp lệ."}, status=400)
    pool_id, pool_error = _parse_id(request.query_params.get("pool"), "Nhóm ứng viên")
    if pool_error:
        return Response({"detail": pool_error}, status=400)

    active = ~Q(state__in=HuntCandidate.CLOSED_STATES)
    work = (HuntCandidate.objects
            .select_related("person", "assigned_to", "hunt_request")
            .prefetch_related(
                "status_events",
                Prefetch("person__relationships",
                         queryset=Relationship.objects.filter(domain=Signal.DOMAIN_TALENT),
                         to_attr="_talent_relationships"),
                Prefetch("person__hunt_candidates",
                         queryset=HuntCandidate.objects.filter(
                             active, hunt_request__status__in=HuntRequest.OPEN_STATUSES)
                         .select_related("hunt_request", "assigned_to"),
                         to_attr="_active_hunt_candidates"))
            .filter(person__merged_into__isnull=True))
    if scope == "unassigned":
        work = work.filter(active, assigned_to__isnull=True,
                           hunt_request__status__in=HuntRequest.OPEN_STATUSES)
    elif scope == "completed":
        work = work.filter(state__in=HuntCandidate.CLOSED_STATES,
                           assigned_to=request.user)
    else:
        work = work.filter(active, assigned_to=request.user,
                           hunt_request__status__in=HuntRequest.OPEN_STATUSES)

    query = str(request.query_params.get("q") or "").strip()
    if query:
        work = work.filter(Q(person__display_name__icontains=query)
                           | Q(person__headline__icontains=query)
                           | Q(hunt_request__title__icontains=query))
    if pool_id:
        work = work.filter(
            person__pool_memberships__pool_id=pool_id,
            person__pool_memberships__pool__domain="talent")

    items = []
    workflow_catalog = {row.code: row for row in WorkflowStage.objects.filter(
        domain="talent", is_active=True)}
    work_by_person = {}
    for candidate in work.distinct():
        candidate._workflow_meta = _task_stage(candidate, workflow_catalog, now)
        candidate_data = HuntCandidateSerializer(candidate).data
        stage_data = candidate._workflow_meta
        due_values = [value for value in (
            candidate.next_action_at, stage_data["sla_due_at"]) if value]
        due_at = min(due_values) if due_values else None
        is_due = any(value <= now for value in due_values)
        is_today = not is_due and any(value < day_end for value in due_values)
        if scope == "overdue" and not is_due:
            continue
        if scope == "today" and not is_today:
            continue
        item = {
            "kind": "work", "key": f"work:{candidate.pk}",
            "person_id": candidate.person_id,
            "display_name": candidate.person.display_name,
            "headline": candidate.person.headline,
            "hunt": {
                "id": candidate.hunt_request_id,
                "title": candidate.hunt_request.title or "Danh sách ứng viên",
                "message": candidate.hunt_request.message,
                "status": candidate.hunt_request.status,
            },
            "candidate": candidate_data,
            "relationship": _relationship_data(_talent_relationship(candidate.person)),
            "other_active_worklists": _person_worklists(
                candidate.person, workflow_catalog, now, candidate.pk),
            "due_at": due_at,
            "is_overdue": is_due,
            "relationship_due": False,
        }
        items.append(item)
        work_by_person.setdefault(candidate.person_id, []).append(item)

    if scope in {"all", "overdue", "today"}:
        relations = (Relationship.objects.filter(
            domain=Signal.DOMAIN_TALENT, owner_user=request.user,
            do_not_contact=False, person__merged_into__isnull=True,
            next_action_at__isnull=False, next_action_at__lt=day_end)
            .select_related("person")
            .prefetch_related(Prefetch(
                "person__hunt_candidates",
                queryset=HuntCandidate.objects.filter(
                    active, hunt_request__status__in=HuntRequest.OPEN_STATUSES)
                .select_related("hunt_request", "assigned_to"),
                to_attr="_active_hunt_candidates"))
            .order_by("next_action_at"))
        if scope == "overdue":
            relations = relations.filter(next_action_at__lte=now)
        elif scope == "today":
            relations = relations.filter(next_action_at__gt=now)
        if query:
            relations = relations.filter(Q(person__display_name__icontains=query)
                                         | Q(person__headline__icontains=query))
        if pool_id:
            relations = relations.filter(
                person__pool_memberships__pool_id=pool_id,
                person__pool_memberships__pool__domain="talent")
        for relation in relations.distinct():
            existing = work_by_person.get(relation.person_id, [])
            if existing:
                primary = min(existing, key=lambda item: item["due_at"] or day_end)
                if primary["due_at"] is None or relation.next_action_at < primary["due_at"]:
                    primary["due_at"] = relation.next_action_at
                primary["is_overdue"] = bool(
                    primary["is_overdue"] or relation.next_action_at <= now)
                primary["relationship_due"] = True
                continue
            items.append({
                "kind": "relationship", "key": f"relationship:{relation.pk}",
                "person_id": relation.person_id,
                "display_name": relation.person.display_name,
                "headline": relation.person.headline,
                "hunt": None, "candidate": None,
                "relationship": _relationship_data(relation),
                "other_active_worklists": _person_worklists(
                    relation.person, workflow_catalog, now),
                "due_at": relation.next_action_at,
                "is_overdue": bool(relation.next_action_at <= now),
                "relationship_due": True,
            })

    priority_rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    far_future = now + timedelta(days=36500)
    items.sort(key=lambda item: (
        0 if item["is_overdue"] else 1,
        item["due_at"] or far_future,
        priority_rank.get((item["candidate"] or {}).get("priority", "normal"), 2),
        item["display_name"].casefold()))

    my_active = HuntCandidate.objects.filter(
        active, assigned_to=request.user,
        hunt_request__status__in=HuntRequest.OPEN_STATUSES)
    relationship_rows = Relationship.objects.filter(
        domain=Signal.DOMAIN_TALENT, owner_user=request.user,
        do_not_contact=False, next_action_at__lt=day_end)
    unassigned_rows = HuntCandidate.objects.filter(
        active, assigned_to__isnull=True,
        hunt_request__status__in=HuntRequest.OPEN_STATUSES)
    if query:
        task_search = (Q(person__display_name__icontains=query)
                       | Q(person__headline__icontains=query)
                       | Q(hunt_request__title__icontains=query))
        my_active = my_active.filter(task_search)
        unassigned_rows = unassigned_rows.filter(task_search)
        relationship_rows = relationship_rows.filter(
            Q(person__display_name__icontains=query)
            | Q(person__headline__icontains=query))
    if pool_id:
        my_active = my_active.filter(
            person__pool_memberships__pool_id=pool_id,
            person__pool_memberships__pool__domain="talent")
        unassigned_rows = unassigned_rows.filter(
            person__pool_memberships__pool_id=pool_id,
            person__pool_memberships__pool__domain="talent")
        relationship_rows = relationship_rows.filter(
            person__pool_memberships__pool_id=pool_id,
            person__pool_memberships__pool__domain="talent")
    relationship_due_people = set(relationship_rows.filter(
        next_action_at__lte=now).values_list("person_id", flat=True))
    relationship_today_people = set(relationship_rows.filter(
        next_action_at__gt=now).values_list("person_id", flat=True))
    sla_by_state = {row.code: row.sla_hours for row in WorkflowStage.objects.filter(
        domain="talent", is_active=True, is_terminal=False,
        sla_hours__isnull=False)}
    overdue_people = set()
    today_people = set()
    for row in my_active.distinct().values(
            "person_id", "state", "stage_entered_at", "next_action_at"):
        followup = row["next_action_at"]
        sla_hours = sla_by_state.get(row["state"])
        sla_due = (row["stage_entered_at"] + timedelta(hours=sla_hours)
                   if sla_hours else None)
        due_values = [value for value in (followup, sla_due) if value]
        if any(value <= now for value in due_values):
            overdue_people.add(row["person_id"])
        elif any(value < day_end for value in due_values):
            today_people.add(row["person_id"])
    summary = {
        "active": my_active.distinct().count(),
        "overdue": len(overdue_people | relationship_due_people),
        "today": len((today_people | relationship_today_people) - overdue_people
                     - relationship_due_people),
        "unassigned": unassigned_rows.distinct().count(),
    }
    try:
        limit = max(1, min(int(request.query_params.get("limit") or 30), 100))
        offset = max(0, int(request.query_params.get("offset") or 0))
    except (TypeError, ValueError):
        return Response({"detail": "Phân trang không hợp lệ."}, status=400)
    return Response({"count": len(items), "summary": summary,
                     "results": items[offset:offset + limit]})


@api_view(["POST"])
@permission_classes([RequiresCandidateWork])
@transaction.atomic
def hunt_candidates_bulk(request):
    """Cập nhật nhiều task theo kiểu tất cả-cùng-thành-công hoặc không đổi gì."""
    raw_items = request.data.get("items") or []
    patch = request.data.get("patch") or {}
    if not isinstance(raw_items, list) or not isinstance(patch, dict):
        return Response({"detail": "Yêu cầu cập nhật hàng loạt không hợp lệ."}, status=400)
    if not raw_items or len(raw_items) > 100:
        return Response({"detail": "Mỗi lần cần chọn từ 1 đến 100 công việc."}, status=400)
    try:
        keys = list(dict.fromkeys(
            (int(item["hunt_id"]), int(item["person_id"])) for item in raw_items))
    except (KeyError, TypeError, ValueError):
        return Response({"detail": "Danh sách công việc không hợp lệ."}, status=400)

    new_state = patch.get("state")
    if new_state is not None and new_state not in dict(HuntCandidate.STATE_CHOICES):
        return Response({"detail": "Trạng thái không hợp lệ."}, status=400)
    assigned_id, assigned_error = _parse_id(patch.get("assigned_to_id"),
                                            "Người phụ trách")
    if "assigned_to_id" in patch and assigned_error:
        return Response({"detail": assigned_error}, status=400)
    if not any(key in patch for key in ("state", "assigned_to_id")):
        return Response({"detail": "Chưa chọn thay đổi cần áp dụng."}, status=400)
    if (not _can_manage_all_work(request.user)
            and "assigned_to_id" in patch
            and assigned_id not in {None, request.user.pk}):
        return Response({"detail": "Bạn không thể giao công việc cho người khác."}, status=403)
    assignee = None
    if assigned_id:
        assignee = get_user_model().objects.filter(pk=assigned_id, is_active=True).first()
        if (assignee is None or not roles.roles_of(assignee).intersection(
                {roles.RECRUITER, roles.RB_SALES, roles.MANAGER, roles.ADMIN})):
            return Response({"detail": "Người phụ trách không hợp lệ."}, status=400)

    candidates = []
    for hunt_id, person_id in keys:
        candidate = get_object_or_404(
            HuntCandidate.objects.select_for_update().select_related(
                "hunt_request", "person", "assigned_to"),
            hunt_request_id=hunt_id, person_id=person_id)
        if candidate.hunt_request.status not in HuntRequest.OPEN_STATUSES:
            return Response({"detail": f"Danh sách '{candidate.hunt_request}' đã đóng."},
                            status=409)
        if candidate.assigned_to_id is None and not _can_manage_all_work(request.user):
            candidate.assigned_to = request.user
            candidate.assigned_to_name = str(request.user)[:150]
        if not _can_edit_candidate(candidate, request.user):
            return Response({"detail": f"{candidate.person} đang do người khác phụ trách."},
                            status=409)
        if new_state is not None:
            stage_error = validate_stage("talent", new_state, "", from_code=candidate.state)
            if stage_error:
                return Response({"detail": f"{candidate.person}: {stage_error}"}, status=400)
        candidates.append(candidate)

    touched_hunts = set()
    for candidate in candidates:
        old_state = candidate.state
        if "assigned_to_id" in patch:
            candidate.assigned_to = assignee
            candidate.assigned_to_name = str(assignee)[:150] if assignee else ""
        if new_state is not None and new_state != old_state:
            candidate.state = new_state
            candidate.stage_entered_at = timezone.now()
        candidate.updated_by = request.user
        candidate.save()
        if candidate.state != old_state:
            HuntCandidateStatusEvent.objects.create(
                candidate=candidate, from_state=old_state, to_state=candidate.state,
                actor=request.user, note="Cập nhật hàng loạt")
            _sync_relationship(candidate, request.user)
            Interaction.objects.create(
                person=candidate.person, action=f"hunt_{candidate.state}",
                actor=request.user,
                detail={"shortlist": candidate.hunt_request.title,
                        "hunt_request_id": candidate.hunt_request_id,
                        "bulk": True})
        touched_hunts.add(candidate.hunt_request_id)
    for hunt in HuntRequest.objects.filter(pk__in=touched_hunts):
        _close_hunt_if_done(hunt)
    return Response({"updated": len(candidates)})


@api_view(["GET", "PATCH"])
@permission_classes([RequiresCandidateWork])
@transaction.atomic
def hunt_detail(request, hunt_id):
    base = HuntRequest.objects.select_for_update() if request.method == "PATCH" else HuntRequest.objects
    hunt = get_object_or_404(base, pk=hunt_id)

    if request.method == "PATCH":
        new_status = request.data.get("status")
        if new_status is not None and new_status not in dict(HuntRequest.STATUS_CHOICES):
            return Response({"detail": "Trạng thái danh sách không hợp lệ."}, status=400)
        may_claim_list = (hunt.assigned_to_id is None
                          and new_status == HuntRequest.STATUS_ACCEPTED)
        if not (_can_manage_all_work(request.user)
                or hunt.assigned_to_id == request.user.pk or may_claim_list):
            return Response({"detail": "Danh sách này đang do người khác phụ trách."},
                            status=status.HTTP_409_CONFLICT)
        if (new_status in {HuntRequest.STATUS_DONE, HuntRequest.STATUS_DECLINED}
                and hunt.candidates.exclude(
                    state__in=HuntCandidate.CLOSED_STATES).exists()):
            return Response(
                {"detail": "Không thể đóng danh sách khi vẫn còn ứng viên chưa xử lý xong."},
                status=status.HTTP_409_CONFLICT)
        if new_status and new_status in dict(HuntRequest.STATUS_CHOICES):
            hunt.status = new_status
            # Nhận việc mà chưa có ai đứng tên thì người bấm chính là người nhận.
            if (new_status == HuntRequest.STATUS_ACCEPTED and hunt.assigned_to_id is None
                    and request.user.is_authenticated):
                hunt.assigned_to = request.user
                hunt.assigned_to_name = str(request.user)[:150]
        if "assigned_to_id" in request.data:
            user_id, user_error = _parse_id(request.data["assigned_to_id"],
                                            "Người phụ trách")
            if user_error:
                return Response({"detail": user_error}, status=400)
            if (not _can_manage_all_work(request.user)
                    and user_id not in {None, request.user.pk}):
                return Response({"detail": "Bạn không thể giao danh sách cho người khác."},
                                status=status.HTTP_403_FORBIDDEN)
            hunt.assigned_to = (get_user_model().objects.filter(
                pk=user_id, is_active=True).first() if user_id else None)
            if user_id and hunt.assigned_to is None:
                return Response({"detail": "Người phụ trách không hợp lệ."}, status=400)
            hunt.assigned_to_name = str(hunt.assigned_to)[:150] if hunt.assigned_to else ""
        if "decline_reason" in request.data:
            hunt.decline_reason = str(request.data["decline_reason"])[:300]
        if "title" in request.data:
            title = str(request.data["title"]).strip()
            if not title:
                return Response({"detail": "Tên danh sách không được để trống."}, status=400)
            hunt.title = title[:200]
        if "message" in request.data:
            hunt.message = str(request.data.get("message") or "")[:2000]
        if request.data.get("priority") in {"low", "normal", "high", "urgent"}:
            hunt.priority = request.data["priority"]
        add_ids = request.data.get("person_ids_add") or []
        if not isinstance(add_ids, (list, tuple)):
            return Response({"detail": "Danh sách ứng viên không hợp lệ."}, status=400)
        try:
            add_ids = list(dict.fromkeys(int(value) for value in add_ids))
        except (TypeError, ValueError):
            return Response({"detail": "Danh sách ứng viên không hợp lệ."}, status=400)
        if add_ids and hunt.status not in HuntRequest.OPEN_STATUSES:
            return Response({"detail": "Không thể thêm ứng viên vào danh sách đã đóng."},
                            status=status.HTTP_409_CONFLICT)
        for person in Person.objects.filter(pk__in=add_ids, merged_into__isnull=True):
            _candidate, created = HuntCandidate.objects.get_or_create(
                hunt_request=hunt, person=person,
                defaults={"assigned_to": hunt.assigned_to,
                          "assigned_to_name": hunt.assigned_to_name})
            if created:
                Interaction.objects.create(
                    person=person, action="shortlist_added", actor=request.user,
                    detail={"shortlist": hunt.title, "hunt_request_id": hunt.pk})
        hunt.save()

    return Response(HuntRequestSerializer(hunt).data)


def _warm_titles(criteria, people):
    """Nạp sẵn bộ nhớ độ gần chức danh cho danh sách sắp chấm."""
    wanted = (criteria or {}).get("title") or ""
    if not wanted:
        return
    titles = {getattr(getattr(p, "talent_profile", None), "current_title", "")
              for p in people}
    semantic.warm(wanted, {t for t in titles if t})


def _hunt_candidate(hunt_id, person_id):
    return get_object_or_404(HuntCandidate, hunt_request_id=hunt_id,
                             person_id=person_id)


@api_view(["PATCH"])
@permission_classes([RequiresCandidateWork])
@transaction.atomic
def hunt_candidate_detail(request, hunt_id, person_id):
    """Recruiter cập nhật tình hình liên hệ một ứng viên cụ thể.

    Đổi trạng thái ở đây kéo theo `Relationship` của Person — đó là thứ NGƯỜI
    KHÁC nhìn thấy khi mở hồ sơ ngoài luồng săn này. Không đồng bộ thì hồ sơ vẫn
    hiện "chưa liên hệ" trong khi thực tế đã bị gọi ba lần.
    """
    candidate = get_object_or_404(
        HuntCandidate.objects.select_for_update().select_related("hunt_request", "person"),
        hunt_request_id=hunt_id, person_id=person_id)
    user = request.user if request.user.is_authenticated else None

    if candidate.hunt_request.status not in HuntRequest.OPEN_STATUSES:
        return Response({"detail": "Danh sách đã đóng; hãy mở lại trước khi cập nhật."},
                        status=status.HTTP_409_CONFLICT)
    wants_claim = request.data.get("claim") is True
    if wants_claim:
        if candidate.assigned_to_id not in {None, user.pk}:
            return Response({"detail": "Công việc vừa được người khác nhận."},
                            status=status.HTTP_409_CONFLICT)
        candidate.assigned_to = user
        candidate.assigned_to_name = str(user)[:150]
    elif candidate.assigned_to_id is None and not _can_manage_all_work(user):
        # Thao tác nghiệp vụ đầu tiên cũng là một claim nguyên tử, tránh bắt người dùng
        # bấm hai lần nhưng vẫn không cho hai người ghi đè nhau.
        candidate.assigned_to = user
        candidate.assigned_to_name = str(user)[:150]
    if not _can_edit_candidate(candidate, user):
        return Response({"detail": "Hãy nhận công việc trước khi cập nhật."},
                        status=status.HTTP_409_CONFLICT)

    new_state = request.data.get("state")
    if new_state is not None and new_state not in dict(HuntCandidate.STATE_CHOICES):
        return Response({"detail": f"Trạng thái không hợp lệ: {new_state}"},
                        status=status.HTTP_400_BAD_REQUEST)

    if new_state == HuntCandidate.STATE_RETURNED and not str(
            request.data.get("return_reason") or candidate.return_reason).strip():
        return Response(
            {"detail": "Trả ứng viên về kho thì phải ghi lý do — lần sau người "
                       "khác mới biết mà không gọi lại từ đầu."},
            status=status.HTTP_400_BAD_REQUEST)
    if new_state is not None:
        stage_error = validate_stage(
            "talent", new_state,
            request.data.get("return_reason") or request.data.get("note")
            or candidate.return_reason or candidate.note,
            from_code=candidate.state)
        if stage_error:
            return Response({"detail": stage_error}, status=status.HTTP_400_BAD_REQUEST)

    if "note" in request.data:
        candidate.note = str(request.data["note"])[:500]
    if "return_reason" in request.data:
        candidate.return_reason = str(request.data["return_reason"])[:300]
    if "outreach_draft" in request.data:
        candidate.outreach_draft = str(request.data["outreach_draft"])[:5000]
    if request.data.get("priority") in {"low", "normal", "high", "urgent"}:
        candidate.priority = request.data["priority"]
    if "assigned_to_id" in request.data:
        assigned_id, assigned_error = _parse_id(request.data.get("assigned_to_id"),
                                                "Người phụ trách")
        if assigned_error:
            return Response({"detail": assigned_error}, status=400)
        if (not _can_manage_all_work(user)
                and assigned_id not in {None, user.pk}):
            return Response({"detail": "Bạn không thể giao công việc cho người khác."},
                            status=status.HTTP_403_FORBIDDEN)
        candidate.assigned_to = (get_user_model().objects.filter(
            pk=assigned_id, is_active=True).first() if assigned_id else None)
        if assigned_id and candidate.assigned_to is None:
            return Response({"detail": "Người phụ trách không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        candidate.assigned_to_name = (str(candidate.assigned_to)[:150]
                                      if candidate.assigned_to else "")
    if "next_action_at" in request.data:
        raw_next = request.data.get("next_action_at")
        candidate.next_action_at = parse_datetime(raw_next) if raw_next else None
        if raw_next and candidate.next_action_at is None:
            return Response({"detail": "Lịch follow-up không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        if candidate.next_action_at and timezone.is_naive(candidate.next_action_at):
            candidate.next_action_at = timezone.make_aware(candidate.next_action_at)

    old_state = candidate.state
    changed = new_state is not None and new_state != old_state
    if new_state is not None:
        candidate.state = new_state
        if changed:
            candidate.stage_entered_at = timezone.now()
    candidate.updated_by = user
    candidate.save()

    if changed:
        HuntCandidateStatusEvent.objects.create(
            candidate=candidate, from_state=old_state, to_state=new_state,
            actor=user, note=candidate.return_reason or candidate.note)
        _sync_relationship(candidate, user)
        Interaction.objects.create(
            person=candidate.person, action=f"hunt_{new_state}", actor=user,
            detail={"shortlist": candidate.hunt_request.title or
                    (candidate.hunt_request.hiring_need.title
                     if candidate.hunt_request.hiring_need else ""),
                    "hunt_request_id": candidate.hunt_request_id,
                    "reason": candidate.return_reason or candidate.note})
        _close_hunt_if_done(candidate.hunt_request)

    return Response(HuntCandidateSerializer(candidate).data)


def _sync_relationship(candidate, user):
    mapped_state = HuntCandidate.RELATIONSHIP_MAP.get(candidate.state)
    if not mapped_state:
        return
    relation, _ = Relationship.objects.get_or_create(
        person=candidate.person, domain=Signal.DOMAIN_TALENT,
        defaults={"state": mapped_state})
    # DNC always wins over an operational transition in one shortlist.
    if relation.do_not_contact:
        return
    rank = {
        "new": 0, "nurturing": 1, "unavailable": 1, "attempted": 2,
        "connected": 3, "interested": 4, "ready": 5, "placed": 6,
    }
    strongest = None
    for row in candidate.person.hunt_candidates.select_related("assigned_to"):
        state = HuntCandidate.RELATIONSHIP_MAP.get(row.state)
        if state and (strongest is None or rank.get(state, 0) > rank.get(strongest[0], 0)):
            strongest = (state, row)
    aggregate_state, aggregate_candidate = strongest or (mapped_state, candidate)
    # "Đã tuyển" là kết luận chỉnh tay cấp con người; các trạng thái worklist không kéo lùi.
    # Các trạng thái còn lại được tổng hợp lại từ mọi worklist để một luồng yếu không ghi đè
    # một luồng mạnh đang tồn tại.
    if relation.state != "placed":
        relation.state = aggregate_state
        owner = aggregate_candidate.assigned_to or user
        if owner is not None:
            relation.owner_user = owner
            relation.owner = str(owner)[:150]
    if candidate.state in (HuntCandidate.STATE_CONTACTING,
                            HuntCandidate.STATE_RESPONDED,
                            HuntCandidate.STATE_INTERESTED):
        relation.last_contact_at = timezone.now()
    if candidate.state == HuntCandidate.STATE_RETURNED:
        relation.reason = candidate.return_reason[:300]
        if relation.next_action_at is None:
            relation.next_action = "Đánh giá lại ứng viên sau thời gian chăm sóc"
            relation.next_action_at = timezone.now() + timedelta(days=30)
    relation.save()


def _close_hunt_if_done(hunt):
    """Xong hết người thì đóng yêu cầu, khỏi bắt recruiter bấm thêm một nút.

    Chỉ tự đóng, không tự mở lại: mở lại một yêu cầu đã đóng là quyết định có
    chủ ý của recruiter, hệ thống không được làm thay.
    """
    if hunt.status in (HuntRequest.STATUS_DONE, HuntRequest.STATUS_DECLINED):
        return
    candidates = list(hunt.candidates.all())
    if candidates and all(c.is_closed for c in candidates):
        hunt.status = HuntRequest.STATUS_DONE
        hunt.save(update_fields=["status", "updated_at"])


@api_view(["POST"])
@permission_classes([RequiresCandidateWork])
@transaction.atomic
def outreach_draft(request, hunt_id, person_id):
    """AI soạn thư tiếp cận. Recruiter luôn là người bấm gửi, không phải hệ thống."""
    candidate = get_object_or_404(
        HuntCandidate.objects.select_for_update().select_related("hunt_request", "person"),
        hunt_request_id=hunt_id, person_id=person_id)
    if candidate.hunt_request.status not in HuntRequest.OPEN_STATUSES:
        return Response({"detail": "Danh sách đã đóng."}, status=409)
    if candidate.assigned_to_id is None:
        candidate.assigned_to = request.user
        candidate.assigned_to_name = str(request.user)[:150]
    elif not _can_edit_candidate(candidate, request.user):
        return Response({"detail": "Công việc đang do người khác phụ trách."}, status=409)
    if Relationship.objects.filter(
            person=candidate.person, domain="talent", do_not_contact=True).exists():
        return Response({"detail": "Ứng viên đã được đánh dấu không liên hệ."},
                        status=status.HTTP_409_CONFLICT)
    channel = request.data.get("channel") or outreach_module.CHANNEL_MESSAGE
    if channel not in outreach_module.CHANNELS:
        return Response({"detail": f"Kênh không hợp lệ: {channel}"},
                        status=status.HTTP_400_BAD_REQUEST)

    text, error = outreach_module.draft(
        candidate.person, candidate.hunt_request.hiring_need,
        title=candidate.hunt_request.title,
        channel=channel, extra=candidate.hunt_request.message)

    candidate.outreach_draft = text[:5000]
    candidate.save(update_fields=["outreach_draft", "assigned_to", "assigned_to_name",
                                  "updated_at"])
    return Response({"draft": candidate.outreach_draft, "channel": channel,
                     "error": error})


@api_view(["POST"])
@permission_classes([RequiresCandidateWork])
@transaction.atomic
def outreach_sent(request, hunt_id, person_id):
    """Recruiter xác nhận ĐÃ gửi. Hệ thống không tự gửi thư đi.

    Gửi hộ nghĩa là tự động nhắn tin nhân danh MSB tới người thật — việc đó cần
    quyết định của con người, và cần một cuộc bàn về tuân thủ mà ta chưa có.
    """
    candidate = get_object_or_404(
        HuntCandidate.objects.select_for_update().select_related("hunt_request", "person"),
        hunt_request_id=hunt_id, person_id=person_id)
    if candidate.hunt_request.status not in HuntRequest.OPEN_STATUSES:
        return Response({"detail": "Danh sách đã đóng."}, status=409)
    if candidate.assigned_to_id is None:
        candidate.assigned_to = request.user
        candidate.assigned_to_name = str(request.user)[:150]
    elif not _can_edit_candidate(candidate, request.user):
        return Response({"detail": "Công việc đang do người khác phụ trách."}, status=409)
    if Relationship.objects.filter(
            person=candidate.person, domain="talent", do_not_contact=True).exists():
        return Response({"detail": "Ứng viên đã được đánh dấu không liên hệ."},
                        status=status.HTTP_409_CONFLICT)
    user = request.user if request.user.is_authenticated else None

    final_draft = str(request.data.get("draft") or candidate.outreach_draft)[:5000]
    candidate.outreach_draft = final_draft
    candidate.outreach_sent_at = timezone.now()
    old_state = candidate.state
    if candidate.state == HuntCandidate.STATE_PENDING:
        candidate.state = HuntCandidate.STATE_CONTACTING
        candidate.stage_entered_at = timezone.now()
    candidate.updated_by = user
    candidate.save()

    if candidate.state != old_state:
        HuntCandidateStatusEvent.objects.create(
            candidate=candidate, from_state=old_state, to_state=candidate.state,
            actor=user, note="Xác nhận đã gửi nội dung tiếp cận")

    _sync_relationship(candidate, user)
    Interaction.objects.create(
        person=candidate.person, action="outreach_sent", actor=user,
        detail={"shortlist": candidate.hunt_request.title or
                (candidate.hunt_request.hiring_need.title
                 if candidate.hunt_request.hiring_need else ""),
                "channel": request.data.get("channel") or "",
                "text": final_draft[:1000]})
    return Response(HuntCandidateSerializer(candidate).data)


# Số người tối thiểu cần đưa vào để chấm. Dưới ngưỡng này thì vòng
# "chấm → học lại" đứng: hiệu chỉnh cần ít nhất 2 người mỗi bên, mà HM chỉ đánh
# dấu "không phù hợp" được nếu danh sách có cả người không phù hợp.
MIN_POOL = 40


def _recall(criteria):
    """Chọn người ĐƯA VÀO XÉT cho một vị trí. Xếp hạng là việc của scoring.

    `search()` lọc AND cứng — đúng cho ô tìm kiếm, sai cho màn hình này. Một JD
    đủ chi tiết (chức danh + 2 kỹ năng + nơi ở + số năm) lọc AND xong thường còn
    0–2 người, và khi ấy:

      • HM không có ai để đánh dấu "không phù hợp" → không học được gì;
      • người lệch một tiêu chí phụ (ở Đà Nẵng, thiếu 1 năm) biến mất hoàn toàn,
        dù chính họ mới là ứng viên đáng gọi.

    Nên ở đây nới dần: bắt đầu bằng toàn bộ tiêu chí, thiếu người thì bỏ bớt
    ràng buộc theo thứ tự từ phụ đến chính. Người tìm được ở vòng chặt vẫn nằm
    trước trong danh sách trả về, nhưng thứ tự cuối cùng do điểm quyết định —
    và điểm đã trừ sẵn những chiều mà họ lệch.
    """
    base = {
        "text": criteria.get("text", ""),
        "skills": criteria.get("skills"),
        "title": criteria.get("title", ""),
        "location": criteria.get("location", ""),
        "company": criteria.get("company", ""),
        "min_years": criteria.get("min_years"),
        "max_years": criteria.get("max_years"),
        "order": "newest",
    }

    skills = [s for s in (base["skills"] or []) if s]
    rounds = [
        base,
        {**base, "min_years": None, "max_years": None},
        {**base, "min_years": None, "max_years": None, "location": ""},
        {**base, "min_years": None, "max_years": None, "location": "",
         "company": "", "skills": skills[:1]},
        {**base, "min_years": None, "max_years": None, "location": "",
         "company": "", "skills": None},
    ]
    # Chức danh cũng bỏ ở vòng cuối: "Data Analyst" không khớp "Data Engineer"
    # về mặt chuỗi, nhưng khớp về mặt người.
    rounds.append({**rounds[-1], "title": "", "text": ""})

    found, seen, strict = [], set(), 0
    for index, args in enumerate(rounds):
        _total, people = search_module.search(**args, limit=MIN_POOL * 3)
        for person in people:
            if person.pk not in seen:
                seen.add(person.pk)
                found.append(person)
        if index == 0:
            strict = len(found)
        if len(found) >= MIN_POOL:
            break
    return found, strict
