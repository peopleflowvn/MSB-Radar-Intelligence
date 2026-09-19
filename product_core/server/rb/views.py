# -*- coding: utf-8 -*-
"""API RB Radar (Master Plan mục 25, 32 — PHASE 12).

Màn hình chính là **Hộp thư cơ hội**: việc RM cần làm hôm nay, xếp theo mức tin
cậy. Cùng khuôn với hộp thư yêu cầu săn bên tuyển dụng, và cố ý giống nhau —
hai vai trò khác nhau nhưng cùng một nhịp làm việc: nhận → liên hệ → chốt hoặc
bỏ **kèm lý do**.
"""
import csv
import logging
from datetime import datetime, time, timedelta

from accounts import privacy
from accounts.models import UserWorkProfile
from accounts.permissions import RequiresRB
from accounts import roles
from ai.conversation import answer_if_conversation, sanitize_history
from ai import conversation_state, events, intent as intent_router
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from people.models import Interaction, Person, Relationship
from core.workflows import validate_stage
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import agent as agent_module
from . import metrics as metrics_module
from . import outreach as outreach_module
from . import routing
from . import prospects as prospects_module
from . import suggestions as suggestions_module
from .models import (PRODUCT_CHOICES, PRODUCT_LABELS, OpportunityOutcome,
                     OpportunitySuggestion, RBOpportunity,
                     RBOpportunityStatusEvent, RBProfile)
from .serializers import (OpportunityOutcomeSerializer,
                          OpportunitySuggestionSerializer,
                          ProductInterestSerializer, RBCustomerSerializer,
                          RBOpportunitySerializer, RBProfileSerializer,
                          UserWorkProfileSerializer)

log = logging.getLogger(__name__)


def _can_manage_all_work(user):
    return bool(roles.roles_of(user) & {roles.MANAGER, roles.ADMIN})


def _can_edit_opportunity(opportunity, user):
    return (_can_manage_all_work(user)
            or opportunity.assigned_to_id == getattr(user, "pk", None))


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


def _pagination(params, default=50):
    try:
        limit = max(1, min(int(params.get("limit") or default), 100))
        offset = max(0, int(params.get("offset") or 0))
    except (TypeError, ValueError):
        return None, None, "Phân trang không hợp lệ."
    return limit, offset, None


def _relationship_data(relation):
    if relation is None:
        return {
            "id": None, "state": "cold", "owner": "", "owner_id": None,
            "interest_level": 0, "next_action": "", "next_action_at": None,
            "do_not_contact": False,
        }
    return {
        "id": relation.pk, "state": relation.state, "owner": relation.owner,
        "owner_id": relation.owner_user_id,
        "interest_level": relation.interest_level,
        "next_action": relation.next_action,
        "next_action_at": relation.next_action_at,
        "do_not_contact": relation.do_not_contact,
    }


def _profile_queryset():
    return (RBProfile.objects.select_related("person", "sales_owner")
            .prefetch_related("interests", "person__rb_opportunities",
                              "person__relationships"))


@api_view(["GET"])
@permission_classes([RequiresRB])
def customer_search(request):
    """Tìm khách hàng theo dữ liệu bán lẻ, không mượn bộ lọc tuyển dụng."""
    params = request.query_params
    owner_id, owner_error = _parse_id(params.get("owner"), "Người phụ trách")
    pool_id, pool_error = _parse_id(params.get("pool"), "Nhóm khách hàng")
    if owner_error or pool_error:
        return Response({"detail": owner_error or pool_error}, status=400)
    limit, offset, page_error = _pagination(params)
    if page_error:
        return Response({"detail": page_error}, status=400)
    min_confidence = None
    if params.get("min_confidence") not in (None, ""):
        try:
            min_confidence = float(params["min_confidence"])
        except (TypeError, ValueError):
            return Response({"detail": "Độ tin cậy không hợp lệ."}, status=400)
        if not 0 <= min_confidence <= 1:
            return Response({"detail": "Độ tin cậy phải từ 0 đến 1."}, status=400)
    queryset = (Person.objects.filter(merged_into__isnull=True)
                .select_related("rb_profile", "rb_profile__sales_owner")
                .prefetch_related("rb_profile__interests", "rb_opportunities",
                                  "relationships"))
    text = str(params.get("q") or "").strip()
    if text:
        queryset = queryset.filter(
            Q(display_name__icontains=text) | Q(primary_email__icontains=text)
            | Q(primary_phone__icontains=text) | Q(rb_profile__occupation__icontains=text)
            | Q(rb_profile__employer__icontains=text)
            | Q(rb_profile__interaction_summary__icontains=text)).distinct()
    if params.get("lead_status"):
        queryset = queryset.filter(rb_profile__lead_status=params["lead_status"])
    if params.get("segment"):
        queryset = queryset.filter(rb_profile__segment=params["segment"])
    if owner_id:
        queryset = queryset.filter(rb_profile__sales_owner_id=owner_id)
    if params.get("product"):
        queryset = queryset.filter(rb_profile__interests__product=params["product"])
    if min_confidence is not None:
        queryset = queryset.filter(rb_profile__interests__confidence__gte=min_confidence)
    if params.get("has_phone") == "1":
        queryset = queryset.exclude(primary_phone="")
    if params.get("has_email") == "1":
        queryset = queryset.exclude(primary_email="")
    if params.get("open_opportunity") == "1":
        queryset = queryset.filter(rb_opportunities__status__in=RBOpportunity.OPEN_STATUSES)
    elif params.get("open_opportunity") == "0":
        queryset = queryset.exclude(rb_opportunities__status__in=RBOpportunity.OPEN_STATUSES)
    if params.get("overdue") == "1":
        queryset = queryset.filter(Q(rb_profile__next_action_at__lt=timezone.now())
                                   | Q(rb_opportunities__next_action_at__lt=timezone.now(),
                                       rb_opportunities__status__in=RBOpportunity.OPEN_STATUSES))
    if pool_id:
        queryset = queryset.filter(pool_memberships__pool_id=pool_id,
                                    pool_memberships__pool__domain="rb")
    queryset = queryset.distinct().order_by("-updated_at")
    return Response({"count": queryset.count(),
                     "results": RBCustomerSerializer(queryset[offset:offset + limit], many=True).data})


@api_view(["GET"])
@permission_classes([RequiresRB])
def recently_viewed(request):
    limit, _, page_error = _pagination(request.query_params)
    if page_error:
        return Response({"detail": page_error}, status=400)
    person_ids = []
    for person_id in (Interaction.objects.filter(actor=request.user, action="viewed", domain="rb")
                      .values_list("person_id", flat=True)[:1000]):
        if person_id not in person_ids:
            person_ids.append(person_id)
        if len(person_ids) >= limit:
            break
    profiles = {row.person_id: row for row in _profile_queryset().filter(person_id__in=person_ids)}
    ordered = [profiles[person_id] for person_id in person_ids if person_id in profiles]
    return Response({"count": len(ordered),
                     "results": RBProfileSerializer(ordered, many=True).data})


@api_view(["GET"])
@permission_classes([RequiresRB])
def relationship_followups(request):
    """Quan hệ khách hàng đến hạn nhưng chưa nhất thiết có một cơ hội bán hàng."""
    rows = (Relationship.objects.filter(
        domain="rb", owner_user=request.user, do_not_contact=False,
        next_action_at__lte=timezone.now(), person__merged_into__isnull=True)
        .select_related("person", "person__rb_profile")
        .prefetch_related("person__relationships", "person__rb_profile__interests",
                          "person__rb_opportunities")
        .order_by("next_action_at")[:100])
    people = [row.person for row in rows]
    return Response({"count": len(people),
                     "results": RBCustomerSerializer(people, many=True).data})


def _task_due(opportunity, now):
    data = RBOpportunitySerializer(opportunity).data
    due_values = [value for value in (
        opportunity.next_action_at,
        parse_datetime(str(data.get("sla_due_at") or "")) if data.get("sla_due_at") else None,
    ) if value]
    due_at = min(due_values) if due_values else None
    return data, due_at, any(value <= now for value in due_values)


@api_view(["GET"])
@permission_classes([RequiresRB])
def customer_tasks(request):
    """Inbox phẳng theo khách hàng; cơ hội và lịch chăm sóc chỉ tạo một dòng/người."""
    now = timezone.now()
    tomorrow = timezone.localdate() + timedelta(days=1)
    day_end = timezone.make_aware(datetime.combine(tomorrow, time.min))
    scope = str(request.query_params.get("scope") or "all")
    if scope not in {"all", "overdue", "today", "unassigned", "completed"}:
        return Response({"detail": "Phạm vi công việc không hợp lệ."}, status=400)
    pool_id, pool_error = _parse_id(request.query_params.get("pool"), "Nhóm khách hàng")
    if pool_error:
        return Response({"detail": pool_error}, status=400)
    limit, offset, page_error = _pagination(request.query_params, default=30)
    if page_error:
        return Response({"detail": page_error}, status=400)
    query = str(request.query_params.get("q") or "").strip()

    opportunities = (RBOpportunity.objects.select_related("person", "assigned_to")
                     .prefetch_related(
                         "status_events",
                         Prefetch("person__relationships",
                                  queryset=Relationship.objects.filter(domain="rb"),
                                  to_attr="_rb_relationships"))
                     .filter(person__merged_into__isnull=True))
    if scope == "unassigned":
        opportunities = opportunities.filter(
            status__in=RBOpportunity.OPEN_STATUSES, assigned_to__isnull=True)
    elif scope == "completed":
        opportunities = opportunities.filter(
            status__in=(RBOpportunity.STATUS_WON, RBOpportunity.STATUS_LOST),
            assigned_to=request.user)
    else:
        opportunities = opportunities.filter(
            status__in=RBOpportunity.OPEN_STATUSES, assigned_to=request.user)
    if query:
        opportunities = opportunities.filter(
            Q(person__display_name__icontains=query)
            | Q(person__headline__icontains=query)
            | Q(need__icontains=query)
            | Q(product__icontains=query))
    if pool_id:
        opportunities = opportunities.filter(
            person__pool_memberships__pool_id=pool_id,
            person__pool_memberships__pool__domain="rb")

    by_person = {}
    for opportunity in opportunities.distinct():
        serialized, due_at, is_overdue = _task_due(opportunity, now)
        if scope == "overdue" and not is_overdue:
            continue
        if scope == "today" and (is_overdue or not due_at or due_at >= day_end):
            continue
        relation = next(iter(getattr(opportunity.person, "_rb_relationships", [])), None)
        candidate = {
            "opportunity": serialized, "due_at": due_at,
            "is_overdue": is_overdue, "relation": relation,
        }
        by_person.setdefault(opportunity.person_id, []).append(candidate)

    if scope in {"all", "overdue", "today"}:
        relations = (Relationship.objects.filter(
            domain="rb", owner_user=request.user, do_not_contact=False,
            person__merged_into__isnull=True, next_action_at__isnull=False,
            next_action_at__lt=day_end).select_related("person"))
        if scope == "overdue":
            relations = relations.filter(next_action_at__lte=now)
        elif scope == "today":
            relations = relations.filter(next_action_at__gt=now)
        if query:
            relations = relations.filter(
                Q(person__display_name__icontains=query)
                | Q(person__headline__icontains=query)
                | Q(next_action__icontains=query))
        if pool_id:
            relations = relations.filter(
                person__pool_memberships__pool_id=pool_id,
                person__pool_memberships__pool__domain="rb")
        for relation in relations.distinct():
            by_person.setdefault(relation.person_id, [])
            # Gắn lịch quan hệ vào cùng khách, không tạo thêm một dòng công việc.
            if by_person[relation.person_id]:
                for row in by_person[relation.person_id]:
                    row["relation"] = relation
            else:
                by_person[relation.person_id].append({
                    "opportunity": None, "due_at": relation.next_action_at,
                    "is_overdue": relation.next_action_at <= now,
                    "relation": relation, "person": relation.person,
                })

    items = []
    far_future = now + timedelta(days=36500)
    priority_rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    for person_id, candidates in by_person.items():
        candidates.sort(key=lambda row: (
            0 if row["is_overdue"] else 1,
            row["due_at"] or far_future,
            priority_rank.get((row["opportunity"] or {}).get("priority", "normal"), 2)))
        primary = candidates[0]
        opportunity = primary["opportunity"]
        person = (next((row.person for row in opportunities
                        if row.person_id == person_id), None)
                  or primary.get("person"))
        relation = primary.get("relation")
        relation_due = bool(relation and relation.next_action_at
                            and relation.next_action_at < day_end)
        due_values = [value for value in (
            primary["due_at"], relation.next_action_at if relation_due else None) if value]
        due_at = min(due_values) if due_values else None
        items.append({
            "kind": "work" if opportunity else "relationship",
            "key": f"customer:{person_id}", "person_id": person_id,
            "display_name": person.display_name, "headline": person.headline,
            "primary_phone": person.primary_phone,
            "primary_email": person.primary_email,
            "opportunity": opportunity,
            "other_opportunities": [row["opportunity"] for row in candidates[1:]
                                    if row["opportunity"]],
            "relationship": _relationship_data(relation),
            "due_at": due_at,
            "is_overdue": bool(due_at and due_at <= now),
            "relationship_due": relation_due,
        })
    items.sort(key=lambda item: (
        0 if item["is_overdue"] else 1, item["due_at"] or far_future,
        item["display_name"].casefold()))

    active = RBOpportunity.objects.filter(
        assigned_to=request.user, status__in=RBOpportunity.OPEN_STATUSES)
    unassigned = RBOpportunity.objects.filter(
        assigned_to__isnull=True, status__in=RBOpportunity.OPEN_STATUSES)
    if query:
        work_search = (Q(person__display_name__icontains=query)
                       | Q(person__headline__icontains=query)
                       | Q(need__icontains=query))
        active = active.filter(work_search)
        unassigned = unassigned.filter(work_search)
    if pool_id:
        active = active.filter(person__pool_memberships__pool_id=pool_id,
                               person__pool_memberships__pool__domain="rb")
        unassigned = unassigned.filter(person__pool_memberships__pool_id=pool_id,
                                       person__pool_memberships__pool__domain="rb")
    all_due = []
    for opportunity in active.distinct():
        _, due_at, _ = _task_due(opportunity, now)
        if due_at:
            all_due.append((opportunity.person_id, due_at))
    relation_due = Relationship.objects.filter(
        domain="rb", owner_user=request.user, do_not_contact=False,
        next_action_at__lt=day_end)
    if query:
        relation_due = relation_due.filter(
            Q(person__display_name__icontains=query) | Q(next_action__icontains=query))
    if pool_id:
        relation_due = relation_due.filter(
            person__pool_memberships__pool_id=pool_id,
            person__pool_memberships__pool__domain="rb")
    all_due.extend(relation_due.values_list("person_id", "next_action_at"))
    overdue_people = {person_id for person_id, due_at in all_due if due_at <= now}
    today_people = {person_id for person_id, due_at in all_due
                    if now < due_at < day_end} - overdue_people
    summary = {
        "active": active.values("person_id").distinct().count(),
        "overdue": len(overdue_people), "today": len(today_people),
        "unassigned": unassigned.values("person_id").distinct().count(),
    }
    return Response({"count": len(items), "summary": summary,
                     "results": items[offset:offset + limit]})


def _opportunity_queryset(request, person_id=None, pool_id=None):
    """Cùng lý do với `talent._search_kwargs`: một bộ lọc dùng chung cho xem
    và xuất, để file tải về khớp đúng những gì đang hiện trên màn hình."""
    queryset = RBOpportunity.objects.select_related("person")
    if request.query_params.get("open") == "1":
        queryset = queryset.filter(status__in=RBOpportunity.OPEN_STATUSES)
    if request.query_params.get("mine") == "1":
        queryset = queryset.filter(assigned_to=request.user)
    if request.query_params.get("product"):
        queryset = queryset.filter(product=request.query_params["product"])
    if person_id:
        queryset = queryset.filter(person_id=person_id)
    if pool_id:
        queryset = queryset.filter(
            person__pool_memberships__pool_id=pool_id,
            person__pool_memberships__pool__domain="rb")
    scope = request.query_params.get("scope")
    if scope == "mine":
        queryset = queryset.filter(assigned_to=request.user,
                                   status__in=RBOpportunity.OPEN_STATUSES)
    elif scope == "followup":
        queryset = queryset.filter(assigned_to=request.user,
                                   status__in=RBOpportunity.OPEN_STATUSES,
                                   next_action_at__lte=timezone.now())
    elif scope == "unassigned":
        queryset = queryset.filter(assigned_to__isnull=True,
                                   status__in=RBOpportunity.OPEN_STATUSES)
    elif scope == "completed":
        queryset = queryset.filter(status__in=(RBOpportunity.STATUS_WON,
                                               RBOpportunity.STATUS_LOST))
        if not _can_manage_all_work(request.user):
            queryset = queryset.filter(assigned_to=request.user)
    elif scope == "team":
        # Tương thích client cũ nhưng không còn mở góc nhìn theo dõi toàn đội.
        queryset = queryset.filter(assigned_to=request.user,
                                   status__in=RBOpportunity.OPEN_STATUSES)
    return queryset.prefetch_related("status_events")


@api_view(["GET", "POST"])
@permission_classes([RequiresRB])
def opportunity_list(request):
    """Hộp thư cơ hội. `?open=1` việc còn phải làm, `?mine=1` việc của tôi."""
    if request.method == "POST":
        person_id, person_error = _parse_id(request.data.get("person_id"), "Khách hàng")
        if person_error:
            return Response({"detail": person_error}, status=400)
        person = get_object_or_404(Person, pk=person_id,
                                   merged_into__isnull=True)
        product = str(request.data.get("product") or "")
        priority = str(request.data.get("priority") or "normal")
        if product not in dict(PRODUCT_CHOICES):
            return Response({"detail": "Nhóm sản phẩm không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        if priority not in {"low", "normal", "high", "urgent"}:
            return Response({"detail": "Mức ưu tiên không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        existing = RBOpportunity.objects.filter(
            person=person, product=product,
            status__in=RBOpportunity.OPEN_STATUSES).first()
        if existing:
            return Response({"detail": "Khách hàng đã có cơ hội đang mở cho sản phẩm này.",
                             "opportunity": RBOpportunitySerializer(existing).data},
                            status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                opportunity = RBOpportunity.objects.create(
                    person=person, product=product,
                    need=str(request.data.get("need") or "")[:300],
                    assigned_to=request.user,
                    priority=priority)
        except IntegrityError:
            existing = RBOpportunity.objects.filter(
                person=person, product=product,
                status__in=RBOpportunity.OPEN_STATUSES).first()
            return Response({
                "detail": "Khách hàng vừa được tạo cơ hội đang mở cho sản phẩm này.",
                "opportunity": (RBOpportunitySerializer(existing).data
                                if existing else None)}, status=409)
        return Response(RBOpportunitySerializer(opportunity).data,
                        status=status.HTTP_201_CREATED)
    scope = str(request.query_params.get("scope") or "")
    if scope not in {"", "mine", "followup", "unassigned", "completed", "team"}:
        return Response({"detail": "Phạm vi công việc không hợp lệ."}, status=400)
    person_id, person_error = _parse_id(request.query_params.get("person"), "Khách hàng")
    pool_id, pool_error = _parse_id(request.query_params.get("pool"), "Nhóm khách hàng")
    if person_error or pool_error:
        return Response({"detail": person_error or pool_error}, status=400)
    limit, offset, page_error = _pagination(request.query_params)
    if page_error:
        return Response({"detail": page_error}, status=400)
    queryset = _opportunity_queryset(request, person_id, pool_id).distinct()
    return Response({"count": queryset.count(),
                     "results": RBOpportunitySerializer(queryset[offset:offset + limit],
                                                         many=True).data})


@api_view(["GET"])
@permission_classes([RequiresRB])
def owner_list(request):
    allowed_roles = {roles.RB_SALES, roles.MANAGER, roles.ADMIN}
    users = (get_user_model().objects.filter(is_active=True,
                                              groups__name__in=allowed_roles)
             .distinct().order_by("first_name", "username"))
    if request.user.is_superuser and not users.filter(pk=request.user.pk).exists():
        users = list(users) + [request.user]
    return Response({"results": [{"id": user.id,
                                   "name": user.get_full_name() or user.username}
                                  for user in users]})


@api_view(["GET"])
@permission_classes([RequiresRB])
def opportunity_export(request):
    """Xuất CSV hộp thư cơ hội (Master Plan mục 15)."""
    person_id, person_error = _parse_id(request.query_params.get("person"), "Khách hàng")
    pool_id, pool_error = _parse_id(request.query_params.get("pool"), "Nhóm khách hàng")
    if person_error or pool_error:
        return Response({"detail": person_error or pool_error}, status=400)
    queryset = _opportunity_queryset(request, person_id, pool_id).distinct()[:5000]

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="co_hoi_ban_le.csv"'
    response.write("﻿")            # BOM — xem talent/views.py cho lý do

    writer = csv.writer(response)
    writer.writerow(["Khách hàng", "Điện thoại", "Email", "Sản phẩm", "Nhu cầu",
                     "Tin cậy", "Trạng thái", "Phụ trách", "Ngày tạo"])
    for opp in queryset:
        writer.writerow([
            # Xuat file la luc du lieu ROI KHOI he thong — day la duong ro ri
            # nguy hiem nhat, nen lien he trong CSV cung bi che. Muon so day du
            # thi mo khoa tung nguoi, co dem va co ghi vet.
            opp.person.display_name,
            privacy.mask_phone(opp.person.primary_phone),
            privacy.mask_email(opp.person.primary_email),
            PRODUCT_LABELS.get(opp.product, opp.product), opp.need,
            f"{opp.confidence:.2f}", opp.get_status_display(),
            opp.assigned_to_name, opp.created_at.strftime("%Y-%m-%d"),
        ])
    return response


@api_view(["GET", "PATCH"])
@permission_classes([RequiresRB])
@transaction.atomic
def opportunity_detail(request, opportunity_id):
    base = (RBOpportunity.objects.select_for_update()
            if request.method == "PATCH" else RBOpportunity.objects)
    opportunity = get_object_or_404(base.select_related("person", "assigned_to"),
                                    pk=opportunity_id)
    user = request.user if request.user.is_authenticated else None

    if request.method == "PATCH":
        wants_claim = request.data.get("claim") is True
        if wants_claim:
            if opportunity.assigned_to_id not in {None, user.pk}:
                return Response({"detail": "Công việc vừa được RM khác nhận."}, status=409)
            opportunity.assigned_to = user
            opportunity.assigned_to_name = str(user)[:150]
        elif opportunity.assigned_to_id is None and not _can_manage_all_work(user):
            opportunity.assigned_to = user
            opportunity.assigned_to_name = str(user)[:150]
        if not _can_edit_opportunity(opportunity, user):
            return Response({"detail": "Hãy nhận công việc trước khi cập nhật."},
                            status=409)
        new_status = request.data.get("status")
        if new_status is not None and new_status not in dict(RBOpportunity.STATUS_CHOICES):
            return Response({"detail": f"Trạng thái không hợp lệ: {new_status}"},
                            status=status.HTTP_400_BAD_REQUEST)

        # Bỏ một cơ hội mà không ghi lý do thì tháng sau hệ thống đề xuất lại,
        # và khách hàng nhận đúng lời chào đã từ chối.
        if new_status == RBOpportunity.STATUS_LOST and not str(
                request.data.get("close_reason") or opportunity.close_reason).strip():
            return Response(
                {"detail": "Đóng cơ hội không thành thì phải ghi lý do."},
                status=status.HTTP_400_BAD_REQUEST)
        if new_status is not None:
            stage_error = validate_stage(
                "rb", new_status,
                request.data.get("close_reason") or request.data.get("note")
                or opportunity.close_reason or opportunity.note,
                from_code=opportunity.status)
            if stage_error:
                return Response({"detail": stage_error},
                                status=status.HTTP_400_BAD_REQUEST)

        if "close_reason" in request.data:
            opportunity.close_reason = str(request.data["close_reason"])[:300]
        if "outreach_draft" in request.data:
            opportunity.outreach_draft = str(request.data["outreach_draft"])[:5000]
        if "note" in request.data:
            opportunity.note = str(request.data["note"])[:500]
        if request.data.get("priority") in {"low", "normal", "high", "urgent"}:
            opportunity.priority = request.data["priority"]
        if "assigned_to_id" in request.data:
            assigned_id, assigned_error = _parse_id(
                request.data.get("assigned_to_id"), "Người phụ trách")
            if assigned_error:
                return Response({"detail": assigned_error}, status=400)
            if (not _can_manage_all_work(user)
                    and assigned_id not in {None, user.pk}):
                return Response({"detail": "Bạn không thể giao công việc cho người khác."},
                                status=403)
            opportunity.assigned_to = (get_user_model().objects.filter(
                pk=assigned_id, is_active=True).first() if assigned_id else None)
            if (assigned_id and (opportunity.assigned_to is None
                    or not roles.roles_of(opportunity.assigned_to).intersection(
                        {roles.RB_SALES, roles.MANAGER, roles.ADMIN}))):
                return Response({"detail": "Người phụ trách không hợp lệ."},
                                status=status.HTTP_400_BAD_REQUEST)
            opportunity.assigned_to_name = (str(opportunity.assigned_to)[:150]
                                            if opportunity.assigned_to else "")
        if "next_action_at" in request.data:
            raw_next = request.data.get("next_action_at")
            opportunity.next_action_at = parse_datetime(raw_next) if raw_next else None
            if raw_next and opportunity.next_action_at is None:
                return Response({"detail": "Lịch follow-up không hợp lệ."},
                                status=status.HTTP_400_BAD_REQUEST)
            if opportunity.next_action_at and timezone.is_naive(opportunity.next_action_at):
                opportunity.next_action_at = timezone.make_aware(opportunity.next_action_at)

        old_status = opportunity.status
        changed = new_status is not None and new_status != old_status
        if new_status is not None:
            opportunity.status = new_status
            # Nhận việc mà chưa ai đứng tên thì người bấm chính là người nhận.
            if (new_status == RBOpportunity.STATUS_ACCEPTED
                    and opportunity.assigned_to_id is None and user is not None):
                opportunity.assigned_to = user
                opportunity.assigned_to_name = str(user)[:150]
            if changed:
                opportunity.stage_entered_at = timezone.now()
        opportunity.save()

        if changed:
            RBOpportunityStatusEvent.objects.create(
                opportunity=opportunity, from_status=old_status, to_status=new_status,
                actor=user, note=opportunity.close_reason or opportunity.note)
            _touch_profile(opportunity, user)
            Interaction.objects.create(
                person=opportunity.person, domain="rb",
                action=f"rb_{new_status}", actor=user,
                detail={"product": opportunity.product,
                        "reason": opportunity.close_reason})

    return Response(RBOpportunitySerializer(opportunity).data)


@api_view(["POST"])
@permission_classes([RequiresRB])
@transaction.atomic
def opportunities_bulk(request):
    """Cập nhật nhiều cơ hội theo kiểu tất cả thành công hoặc không đổi gì."""
    raw_ids = request.data.get("opportunity_ids") or []
    patch = request.data.get("patch") or {}
    if not isinstance(raw_ids, list) or not isinstance(patch, dict):
        return Response({"detail": "Yêu cầu cập nhật hàng loạt không hợp lệ."}, status=400)
    try:
        ids = list(dict.fromkeys(int(value) for value in raw_ids))
    except (TypeError, ValueError):
        return Response({"detail": "Danh sách cơ hội không hợp lệ."}, status=400)
    if not ids or len(ids) > 100 or any(value <= 0 for value in ids):
        return Response({"detail": "Mỗi lần cần chọn từ 1 đến 100 cơ hội."}, status=400)
    new_status = patch.get("status")
    if new_status is not None and new_status not in dict(RBOpportunity.STATUS_CHOICES):
        return Response({"detail": "Trạng thái không hợp lệ."}, status=400)
    assigned_id, assigned_error = _parse_id(patch.get("assigned_to_id"),
                                            "Người phụ trách")
    if "assigned_to_id" in patch and assigned_error:
        return Response({"detail": assigned_error}, status=400)
    if not any(key in patch for key in ("status", "assigned_to_id")):
        return Response({"detail": "Chưa chọn thay đổi cần áp dụng."}, status=400)
    if (not _can_manage_all_work(request.user)
            and "assigned_to_id" in patch
            and assigned_id not in {None, request.user.pk}):
        return Response({"detail": "Bạn không thể giao công việc cho người khác."}, status=403)
    assignee = None
    if assigned_id:
        assignee = get_user_model().objects.filter(pk=assigned_id, is_active=True).first()
        if (assignee is None or not roles.roles_of(assignee).intersection(
                {roles.RB_SALES, roles.MANAGER, roles.ADMIN})):
            return Response({"detail": "Người phụ trách không hợp lệ."}, status=400)

    opportunities = list(RBOpportunity.objects.select_for_update().select_related(
        "person", "assigned_to").filter(pk__in=ids))
    if len(opportunities) != len(ids):
        return Response({"detail": "Có cơ hội không còn tồn tại."}, status=404)
    reason = str(patch.get("close_reason") or "").strip()
    for opportunity in opportunities:
        if opportunity.assigned_to_id is None and not _can_manage_all_work(request.user):
            opportunity.assigned_to = request.user
            opportunity.assigned_to_name = str(request.user)[:150]
        if not _can_edit_opportunity(opportunity, request.user):
            return Response({"detail": f"{opportunity.person} đang do RM khác phụ trách."},
                            status=409)
        if new_status == RBOpportunity.STATUS_LOST and not (reason or opportunity.close_reason):
            return Response({"detail": "Đóng không thành phải có lý do."}, status=400)
        if new_status is not None:
            stage_error = validate_stage("rb", new_status, reason or opportunity.close_reason,
                                         from_code=opportunity.status)
            if stage_error:
                return Response({"detail": f"{opportunity.person}: {stage_error}"}, status=400)

    for opportunity in opportunities:
        old_status = opportunity.status
        if "assigned_to_id" in patch:
            opportunity.assigned_to = assignee
            opportunity.assigned_to_name = str(assignee)[:150] if assignee else ""
        if new_status is not None and new_status != old_status:
            opportunity.status = new_status
            opportunity.stage_entered_at = timezone.now()
            if new_status == RBOpportunity.STATUS_LOST:
                opportunity.close_reason = reason
        opportunity.save()
        if opportunity.status != old_status:
            RBOpportunityStatusEvent.objects.create(
                opportunity=opportunity, from_status=old_status,
                to_status=opportunity.status, actor=request.user,
                note=reason or "Cập nhật hàng loạt")
            _touch_profile(opportunity, request.user)
            Interaction.objects.create(
                person=opportunity.person, domain="rb",
                action=f"rb_{opportunity.status}", actor=request.user,
                detail={"product": opportunity.product, "bulk": True})
    return Response({"updated": len(opportunities)})


def _touch_profile(opportunity, user):
    """Đồng bộ trạng thái khách hàng — cùng lý do với `Relationship` bên tuyển dụng.

    Người khác mở hồ sơ ra phải thấy khách đang ở đâu, không thì hai RM cùng
    gọi một người trong một tuần.
    """
    profile = routing.profile_for(opportunity.person)
    mapping = {
        RBOpportunity.STATUS_NEW: RBProfile.LEAD_COLD,
        RBOpportunity.STATUS_ACCEPTED: RBProfile.LEAD_WARM,
        RBOpportunity.STATUS_CONTACTING: RBProfile.LEAD_INTERESTED,
        RBOpportunity.STATUS_WON: RBProfile.LEAD_CONVERTED,
        RBOpportunity.STATUS_LOST: RBProfile.LEAD_DORMANT,
    }
    # Hồ sơ là trạng thái tổng hợp của khách, không phải bản sao của cơ hội vừa
    # được bấm cuối cùng. Một cơ hội thất bại không được hạ khách đã chuyển đổi.
    rank = {
        RBOpportunity.STATUS_WON: 5,
        RBOpportunity.STATUS_CONTACTING: 4,
        RBOpportunity.STATUS_ACCEPTED: 3,
        RBOpportunity.STATUS_NEW: 2,
        RBOpportunity.STATUS_LOST: 1,
    }
    all_opportunities = list(RBOpportunity.objects.filter(
        person=opportunity.person).select_related("assigned_to"))
    strongest = max(all_opportunities,
                    key=lambda row: (rank.get(row.status, 0), row.updated_at))
    profile.lead_status = mapping.get(strongest.status, profile.lead_status)
    if opportunity.status in (RBOpportunity.STATUS_CONTACTING,
                              RBOpportunity.STATUS_WON):
        profile.last_contact_at = timezone.now()
    if strongest.assigned_to_id:
        profile.sales_owner = strongest.assigned_to
        profile.sales_owner_name = strongest.assigned_to_name
    elif user is not None and profile.sales_owner_id is None:
        profile.sales_owner = user
        profile.sales_owner_name = str(user)[:150]
    profile.save()

    relation, _ = Relationship.objects.get_or_create(
        person=opportunity.person, domain="rb",
        defaults={"state": profile.lead_status})
    # DNC is a compliance flag, not a pipeline stage. Keep it intact while the
    # operational status, owner and last-contact timestamp stay in sync.
    relation.state = profile.lead_status
    relation.owner_user = profile.sales_owner
    relation.owner = profile.sales_owner_name
    relation.last_contact_at = profile.last_contact_at
    relation.save()


@api_view(["GET"])
@permission_classes([RequiresRB])
def profile_detail(request, person_id):
    """Hồ sơ bán lẻ của một người. Tạo sẵn nếu chưa có — hồ sơ rỗng vẫn có ích
    hơn một trang 404, vì RM cần chỗ để ghi ghi chú đầu tiên."""
    person = get_object_or_404(Person, pk=person_id)
    profile = routing.profile_for(person)
    Relationship.objects.get_or_create(person=person, domain="rb",
                                       defaults={"state": profile.lead_status})
    person = Person.objects.prefetch_related("relationships").get(pk=person.pk)
    profile.person = person
    return Response(RBProfileSerializer(profile).data)


@api_view(["PATCH"])
@permission_classes([RequiresRB])
def profile_update(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    profile = routing.profile_for(person)
    relation, _ = Relationship.objects.get_or_create(
        person=person, domain="rb", defaults={"state": profile.lead_status})

    for field in ("occupation", "employer", "next_action", "interaction_summary"):
        if field in request.data:
            profile.__dict__[field] = str(request.data[field])[:1000]
    if request.data.get("lead_status") in dict(RBProfile.LEAD_CHOICES):
        profile.lead_status = request.data["lead_status"]
        relation.state = profile.lead_status
    if request.data.get("segment") in dict(RBProfile.SEGMENT_CHOICES):
        profile.segment = request.data["segment"]
    if "sales_owner_id" in request.data:
        owner_id = request.data.get("sales_owner_id")
        profile.sales_owner = (get_user_model().objects.filter(
            pk=owner_id, is_active=True).first() if owner_id else None)
        if owner_id and profile.sales_owner is None:
            return Response({"detail": "RM phụ trách không hợp lệ."}, status=400)
        profile.sales_owner_name = str(profile.sales_owner)[:150] if profile.sales_owner else ""
        relation.owner_user = profile.sales_owner
        relation.owner = profile.sales_owner_name
    if "next_action_at" in request.data:
        raw_next = request.data.get("next_action_at")
        profile.next_action_at = parse_datetime(raw_next) if raw_next else None
        if raw_next and profile.next_action_at is None:
            return Response({"detail": "Lịch hành động không hợp lệ."}, status=400)
        if profile.next_action_at and timezone.is_naive(profile.next_action_at):
            profile.next_action_at = timezone.make_aware(profile.next_action_at)
        relation.next_action_at = profile.next_action_at
    if "next_action" in request.data:
        relation.next_action = profile.next_action
    if "interest_level" in request.data:
        try:
            relation.interest_level = max(0, min(5, int(request.data["interest_level"] or 0)))
        except (TypeError, ValueError):
            return Response({"detail": "Mức độ quan tâm không hợp lệ."}, status=400)
    for field, target in (("preferred_channel", "preferred_channel"),
                          ("relationship_reason", "reason"),
                          ("relationship_notes", "notes")):
        if field in request.data:
            setattr(relation, target, str(request.data.get(field) or "")[:5000])
    if "do_not_contact" in request.data:
        relation.do_not_contact = bool(request.data["do_not_contact"])
    relation.save()
    profile.save()
    profile.person = Person.objects.prefetch_related("relationships").get(pk=person.pk)
    return Response(RBProfileSerializer(profile).data)


@api_view(["POST"])
@permission_classes([RequiresRB])
def suggest(request):
    """Dán một đoạn khách nói, xem gợi ý sản phẩm nào.

    Không gọi LLM: danh mục sản phẩm hữu hạn và có tên cố định, nên một bảng từ
    khoá đọc được và sửa được ăn đứt — và nó **không bao giờ gợi ý một sản phẩm
    MSB không bán**.
    """
    text = str(request.data.get("text") or "").strip()
    if not text:
        return Response({"detail": "Chưa có nội dung."},
                        status=status.HTTP_400_BAD_REQUEST)

    rows = routing.suggest_products(text)
    labels = dict(PRODUCT_CHOICES)
    return Response({"results": [
        {**row.as_dict(), "product_label": labels.get(row.product, row.product)}
        for row in rows]})


@api_view(["GET"])
@permission_classes([RequiresRB])
def interest_list(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    profile = routing.profile_for(person, create=False)
    rows = profile.interests.all() if profile else []
    return Response({"results": ProductInterestSerializer(rows, many=True).data})


@api_view(["GET"])
@permission_classes([RequiresRB])
def metrics(request):
    """Chỉ số hiệu quả RB Radar (Master Plan mục 50)."""
    return Response({"metrics": metrics_module.collect()})


@api_view(["POST"])
@permission_classes([RequiresRB])
def agent_analyze(request):
    """RB Radar Agent: một đoạn văn bản -> ý định + khớp khách + gợi ý sản phẩm.

    Gộp `social.analyze` (ý định, khớp người) và `rb.suggest` (gợi ý sản phẩm)
    thành một lượt có vết — trước đây không có nơi nào nối hai thứ đó lại, và
    không nơi nào cảnh báo "khách này đã có cơ hội đang mở rồi". Không lưu gì.
    """
    text = str(request.data.get("text") or "").strip()
    if not text:
        return Response({"detail": "Chưa có nội dung."},
                        status=status.HTTP_400_BAD_REQUEST)

    result = agent_module.analyze(
        text, community_id=request.data.get("community"),
        author_name=str(request.data.get("author_name") or "")[:200],
        user=request.user)
    return Response(result.as_dict())


@api_view(["POST"])
@permission_classes([RequiresRB])
@transaction.atomic
def outreach_draft(request, opportunity_id):
    """AI soạn lời chào cho một cơ hội. RM luôn là người bấm gửi, không phải hệ thống."""
    opportunity = get_object_or_404(
        RBOpportunity.objects.select_for_update().select_related("person"),
        pk=opportunity_id)
    claimed = opportunity.assigned_to_id is None and not _can_manage_all_work(request.user)
    if claimed:
        opportunity.assigned_to = request.user
        opportunity.assigned_to_name = str(request.user)[:150]
    if not _can_edit_opportunity(opportunity, request.user):
        return Response({"detail": "Cơ hội đang do RM khác phụ trách."}, status=409)
    if Relationship.objects.filter(
            person=opportunity.person, domain="rb", do_not_contact=True).exists():
        return Response({"detail": "Khách hàng đã được đánh dấu không liên hệ."},
                        status=status.HTTP_409_CONFLICT)
    channel = request.data.get("channel") or outreach_module.CHANNEL_MESSAGE
    if channel not in outreach_module.CHANNELS:
        return Response({"detail": f"Kênh không hợp lệ: {channel}"},
                        status=status.HTTP_400_BAD_REQUEST)

    text, error = outreach_module.draft(
        opportunity, channel=channel, extra=str(request.data.get("extra") or ""))

    opportunity.outreach_draft = text[:5000]
    update_fields = ["outreach_draft", "updated_at"]
    if claimed:
        update_fields.extend(["assigned_to", "assigned_to_name"])
    opportunity.save(update_fields=update_fields)
    return Response({"draft": opportunity.outreach_draft, "channel": channel,
                     "error": error})


@api_view(["POST"])
@permission_classes([RequiresRB])
@transaction.atomic
def outreach_sent(request, opportunity_id):
    """RM xác nhận đã gửi. Hệ thống KHÔNG tự nhắn khách hàng.

    Cùng ranh giới với bên tuyển dụng: nhắn tin nhân danh MSB tới khách hàng
    thật cần quyết định của con người.
    """
    opportunity = get_object_or_404(
        RBOpportunity.objects.select_for_update().select_related("person"),
        pk=opportunity_id)
    if opportunity.assigned_to_id is None and not _can_manage_all_work(request.user):
        opportunity.assigned_to = request.user
        opportunity.assigned_to_name = str(request.user)[:150]
    if not _can_edit_opportunity(opportunity, request.user):
        return Response({"detail": "Cơ hội đang do RM khác phụ trách."}, status=409)
    if Relationship.objects.filter(
            person=opportunity.person, domain="rb", do_not_contact=True).exists():
        return Response({"detail": "Khách hàng đã được đánh dấu không liên hệ."},
                        status=status.HTTP_409_CONFLICT)
    user = request.user if request.user.is_authenticated else None

    old_status = opportunity.status
    if "draft" in request.data:
        opportunity.outreach_draft = str(request.data.get("draft") or "")[:5000]
    opportunity.outreach_sent_at = timezone.now()
    if opportunity.status == RBOpportunity.STATUS_NEW:
        opportunity.status = RBOpportunity.STATUS_CONTACTING
        if opportunity.assigned_to_id is None and user is not None:
            opportunity.assigned_to = user
            opportunity.assigned_to_name = str(user)[:150]
        opportunity.stage_entered_at = timezone.now()
    opportunity.save()

    if opportunity.status != old_status:
        RBOpportunityStatusEvent.objects.create(
            opportunity=opportunity, from_status=old_status,
            to_status=opportunity.status, actor=user,
            note="Đã xác nhận gửi nội dung tiếp cận")

    _touch_profile(opportunity, user)
    Interaction.objects.create(
        person=opportunity.person, domain="rb", action="rb_outreach_sent",
        actor=user,
        detail={"product": opportunity.product,
                "channel": request.data.get("channel") or "",
                "text": opportunity.outreach_draft[:1000]})
    return Response(RBOpportunitySerializer(opportunity).data)


# --------------------------------------------------------- Cơ hội hôm nay

@api_view(["GET"])
@permission_classes([RequiresRB])
def todays_opportunities(request):
    """**CƠ HỘI HÔM NAY** — màn hình quan trọng nhất của RB Radar mới.

    RM không nên phải tự hỏi "hôm nay tôi search gì". Mở lên là thấy việc, xếp
    sẵn theo điểm ưu tiên, mỗi thẻ kèm VÌ SAO BÂY GIỜ.

    `?scope=mine` chỉ lấy việc được gợi ý cho tôi; mặc định lấy cả việc chưa gán
    ai — danh sách trống vì đề xuất nằm ở người khác là cách chắc chắn nhất để
    RM ngừng mở màn hình này.
    """
    # So dong mac dinh lay tu khai bao cua chinh RM: nguoi noi ho xu ly noi 15
    # viec/ngay thi khong nen mo ra thay 50. Van cho phep `?limit=` de xem them —
    # chan RM xem them la quyet dinh cua to chuc, khong phai cua mot truong cau hinh.
    declared = suggestions_module.work_profile_for(request.user)
    default_limit = getattr(declared, "daily_capacity", 0) or 20
    limit, _offset, page_error = _pagination(request.query_params,
                                             default=default_limit)
    if page_error:
        return Response({"detail": page_error}, status=400)

    scope = str(request.query_params.get("scope") or "")
    if scope not in {"", "mine", "all"}:
        return Response({"detail": "Phạm vi không hợp lệ."}, status=400)

    user = request.user if scope == "mine" else None
    if scope == "" and not _can_manage_all_work(request.user):
        user = request.user

    product = str(request.query_params.get("product") or "")
    if product and product not in dict(PRODUCT_CHOICES):
        return Response({"detail": "Nhóm sản phẩm không hợp lệ."}, status=400)

    rows = list(suggestions_module.todays_best(user=user, limit=limit,
                                               product=product))
    return Response({
        "summary": suggestions_module.summarize(rows),
        "results": OpportunitySuggestionSerializer(rows, many=True).data,
    })


@api_view(["POST"])
@permission_classes([RequiresRB])
def suggestion_action(request, suggestion_id):
    """RM xử lý một đề xuất: `accept` · `snooze` · `dismiss`.

    Đây là nơi ranh giới "máy đề xuất, người quyết định" được thực thi ở tầng
    API: chỉ `accept` sinh ra `RBOpportunity`, và nó luôn dùng `request.user`
    làm người nhận — không có tham số nào cho phép nhận hộ người khác.
    """
    suggestion = get_object_or_404(OpportunitySuggestion, pk=suggestion_id)
    action = str(request.data.get("action") or "")

    if suggestion.status in (OpportunitySuggestion.STATUS_CONVERTED,
                             OpportunitySuggestion.STATUS_DISMISSED):
        return Response({"detail": "Đề xuất này đã được xử lý.",
                         "suggestion": OpportunitySuggestionSerializer(suggestion).data},
                        status=status.HTTP_409_CONFLICT)

    if action == "accept":
        priority = str(request.data.get("priority") or "normal")
        if priority not in {"low", "normal", "high", "urgent"}:
            return Response({"detail": "Mức ưu tiên không hợp lệ."}, status=400)
        opportunity, created = suggestions_module.accept(
            suggestion, actor=request.user, priority=priority)
        suggestion.refresh_from_db()
        return Response({"opportunity": RBOpportunitySerializer(opportunity).data,
                         "created": created,
                         "suggestion": OpportunitySuggestionSerializer(suggestion).data},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    if action == "snooze":
        try:
            days = int(request.data.get("days") or 14)
        except (TypeError, ValueError):
            return Response({"detail": "Số ngày không hợp lệ."}, status=400)
        if not 1 <= days <= 365:
            return Response({"detail": "Số ngày phải từ 1 tới 365."}, status=400)
        suggestions_module.snooze(suggestion, actor=request.user, days=days)
        return Response(OpportunitySuggestionSerializer(suggestion).data)

    if action == "dismiss":
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            # Cùng nguyên tắc với `RBOpportunity.close_reason`: một đề xuất bị
            # bỏ im lặng sẽ được sinh lại y hệt vào tháng sau.
            return Response({"detail": "Bỏ qua phải kèm lý do."}, status=400)
        suggestions_module.dismiss(suggestion, actor=request.user, reason=reason)
        return Response(OpportunitySuggestionSerializer(suggestion).data)

    return Response({"detail": "Hành động không hợp lệ."}, status=400)


@api_view(["GET", "POST"])
@permission_classes([RequiresRB])
def opportunity_outcomes(request, opportunity_id):
    """Ghi nhận kết quả sau khi liên hệ (Master Plan mục 35).

    Đây là chỗ khép vòng lặp. `outreach_sent_at` chỉ nói "đã gửi";
    bảng này nói "gửi rồi thì sao" — và đó mới là thứ dùng được cho lần sau.
    """
    opportunity = get_object_or_404(RBOpportunity, pk=opportunity_id)

    if request.method == "GET":
        return Response({"results": OpportunityOutcomeSerializer(
            opportunity.outcomes.all()[:50], many=True).data})

    if not _can_edit_opportunity(opportunity, request.user):
        return Response({"detail": "Bạn không phụ trách cơ hội này."}, status=403)

    outcome = str(request.data.get("outcome") or "")
    if outcome not in dict(OpportunityOutcome.OUTCOME_CHOICES):
        return Response({"detail": "Kết quả không hợp lệ."}, status=400)
    channel = str(request.data.get("channel") or "call")
    if channel not in dict(OpportunityOutcome.CHANNEL_CHOICES):
        return Response({"detail": "Kênh liên hệ không hợp lệ."}, status=400)

    row = OpportunityOutcome.objects.create(
        opportunity=opportunity, person=opportunity.person,
        channel=channel, outcome=outcome,
        action=str(request.data.get("action") or "")[:30],
        note=str(request.data.get("note") or "")[:500],
        created_by=request.user)
    return Response(OpportunityOutcomeSerializer(row).data,
                    status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT"])
@permission_classes([RequiresRB])
def work_profile(request):
    """Hồ sơ công việc của chính người đang đăng nhập.

    Chỉ thao tác trên `request.user` — không có tham số nào cho phép đọc hoặc
    sửa khai báo của người khác. Địa bàn và chỉ tiêu của một RM là chuyện giữa
    họ và quản lý của họ, không phải thứ để RM khác dò.

    Khai báo ở đây **không đổi điểm gốc** của bất kỳ đề xuất nào; nó chỉ đổi thứ
    tự trong danh sách của riêng người khai. Xem `accounts.UserWorkProfile`.
    """
    profile, _created = UserWorkProfile.objects.get_or_create(
        user=request.user, domain=UserWorkProfile.DOMAIN_RB)

    if request.method == "GET":
        # `observed` la thu he thong SUY RA tu viec RM da lam that, de dien san
        # vao form. Rui ro lon nhat cua khai bao thu cong la khong ai khai —
        # mot form trong thi ca tinh nang cha nhan hoa khong giup duoc ai.
        # Tra ve rieng, KHONG tron vao khai bao: nguoi dung phai thay ro dau la
        # thu minh da khai va dau la thu may doan.
        return Response(dict(UserWorkProfileSerializer(profile).data,
                             observed=suggestions_module.observed_work_profile(
                                 request.user)))

    serializer = UserWorkProfileSerializer(profile, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    # `domain` không được đổi qua API: đổi nó biến hồ sơ bán lẻ thành hồ sơ
    # tuyển dụng và phá ràng buộc (user, domain).
    serializer.save(user=request.user, domain=UserWorkProfile.DOMAIN_RB)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([RequiresRB])
def prospect_search(request):
    """Tìm prospect bằng ngôn ngữ tự nhiên (Master Plan mục 16).

    KHÔNG component UI sản phẩm nào còn gọi endpoint này (`/rb/prospects/`) —
    `ProspectSearch.tsx` đã chuyển hẳn sang `api.rbAsk`/`api.rbAskTurn`
    (`/rb/ask/` → `rb/answer/engine.py`, code-driven). Route + `api.rbProspects`
    ở `web/src/api.ts` vẫn còn (chỉ `ProspectSearch.test.tsx` dùng), nên đừng
    tưởng đây là đường đang phục vụ traffic thật khi đọc log/route list — và
    đừng sửa hành vi ở đây mong ảnh hưởng UI, vì nó không chạm tới.

        "Tìm 20 quản lý ở Hà Nội có contact, quan tâm thẻ tín dụng"

    Trả về **cả tiêu chí lẫn kết quả**. Tiêu chí hiện ra và sửa được là ràng
    buộc cứng, không phải tuỳ chọn giao diện: RM phải thấy hệ thống hiểu câu hỏi
    thế nào trước khi tin vào danh sách, và sửa được bộ lọc thay vì phải đoán
    cách viết lại câu hỏi cho AI hiểu.

    `criteria_from` cho biết đường nào đã bóc tách — `agent` (chạy trên GreenNode
    AgentBase), `llm` (tại Hub), hay `keyword` (tất định). Người vận hành cần
    biết đường nào đang phục vụ khi kết quả trông lạ.

    `history`: tiêu chí các lượt hỏi trước trong cùng cuộc trò chuyện (giao
    diện tự gửi lại — Hub không tự lưu hội thoại phía máy chủ). Có history thì
    đây là câu hỏi hỏi tiếp — xem `prospects.parse()`.
    """
    question = str(request.data.get("q") or request.data.get("question") or "").strip()
    if not question:
        return Response({"detail": "Nhập câu hỏi tìm khách hàng."}, status=400)
    if len(question) > 1000:
        return Response({"detail": "Câu hỏi quá dài."}, status=400)

    conversation_id = str(request.data.get("conversation_id") or "")
    client_turn_id = str(request.data.get("client_turn_id") or "")
    parent_turn_id = str(request.data.get("parent_client_turn_id") or "")
    client_history = sanitize_history(request.data.get("history"))
    _thread, history, conversation_summary, _state = conversation_state.load(
        request.user, "prospect", conversation_id, client_history)
    intent = intent_router.classify(
        question, surface="prospect", user=request.user, history=history)
    conversational = answer_if_conversation(
        question, surface="prospect", history=history, user=request.user, intent=intent)
    if conversational:
        reasoning = getattr(conversational, "reasoning", "")
        citations = list(getattr(conversational, "citations", []) or [])
        tool_trace = list(getattr(conversational, "tool_trace", []) or [])
        metadata = {"intent": intent.as_dict()}
        if reasoning:
            metadata["reasoning_trace"] = reasoning
        if citations:
            metadata["web_sources"] = citations
        if tool_trace:
            metadata["tool_trace"] = tool_trace
        thread_row = conversation_state.record(
            request.user, "prospect", conversation_id, question, str(conversational),
            mode="conversation", client_turn_id=client_turn_id,
            provider=getattr(conversational, "provider", ""),
            model=getattr(conversational, "model", ""),
            metadata=metadata)
        events.log_conversation_turn(thread_row, client_turn_id, "prospect",
                                     question, conversational,
                                     parent_turn_id=parent_turn_id)
        return Response({
            "mode": "conversation", "answer": str(conversational),
            "reasoning_content": reasoning,
            "thinking_trace": reasoning,
            "conversation_id": conversation_state.normalize_thread_id(conversation_id),
            "conversation_summary": conversation_summary,
            "question": question, "criteria": prospects_module._empty(),
            "criteria_from": "keyword", "error": "", "count": 0,
            "results": [],
            "provider": getattr(conversational, "provider", ""),
            "model": getattr(conversational, "model", ""),
            "sources": citations, "intent": intent.kind, "tools": tool_trace,
        })

    payload = prospects_module.run(question, user=request.user, history=history)
    coverage = payload.get("coverage") or {}
    if not payload["count"]:
        response_answer = "Chưa tìm thấy khách hàng vượt ngưỡng phù hợp."
    elif coverage.get("truncated"):
        # Nói ra thay vì im lặng: danh sách đã bị cắt vì tiêu chí quá rộng, nên
        # "top 20" ở đây là top của phần đã quét, không phải của toàn kho. RM
        # cần biết để thu hẹp câu hỏi chứ không phải để tin nhầm.
        response_answer = (
            f"Đã tìm thấy {payload['count']} khách hàng tiềm năng, chấm điểm trên "
            f"{coverage.get('scanned', 0)} hồ sơ đầu tiên — tiêu chí còn rộng, "
            "anh/chị thu hẹp thêm để danh sách sát hơn.")
    else:
        response_answer = f"Đã tìm thấy {payload['count']} khách hàng tiềm năng."
    if payload["count"] and coverage.get("product_relaxed"):
        response_answer += (" Chưa ai có dấu hiệu quan tâm đúng sản phẩm đã hỏi — "
                            "danh sách xếp theo mức phù hợp chung, cần xác minh nhu cầu.")
    thread = conversation_state.record(
        request.user, "prospect", conversation_id, question, response_answer,
        criteria=payload.get("criteria"), mode="search",
        provider=payload.get("provider"), model=payload.get("model"),
        metadata={"count": payload.get("count", 0)}, client_turn_id=client_turn_id)
    events.log_search_turn(
        thread, client_turn_id, "prospect", question, criteria=payload.get("criteria"),
        provider=payload.get("provider"), model=payload.get("model"),
        count=payload.get("count", 0), parent_turn_id=parent_turn_id)
    return Response({"mode": "search", "answer": response_answer,
                     "conversation_id": conversation_state.normalize_thread_id(conversation_id),
                     "conversation_summary": thread.summary if thread else conversation_summary,
                     **payload})
