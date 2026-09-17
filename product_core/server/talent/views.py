# -*- coding: utf-8 -*-
"""API Talent Radar: tìm kiếm, Person 360, pool, nhãn.

Mọi endpoint yêu cầu vai trò vào được module Talent (Master Plan mục 38). Khoá API
của Edge không mở được — Edge thu thập dữ liệu, không đọc kho talent.

Mọi lượt ĐỌC ở đây được `accounts.middleware.AccessLogMiddleware` ghi nhật ký tự
động, kể cả lượt của RB Sales (đánh cờ `cross_domain`).
"""
import csv
from urllib.parse import quote

from accounts.permissions import (RequiresAiSettings, RequiresCandidateWork,
                                  RequiresRecruiting, RequiresTalent)
from accounts import privacy, roles
from core.storage import StorageError, get_storage
from core.document_preview import is_safe_inline
from django.db.models import Prefetch
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils.html import escape
from django.utils import timezone
from people.models import Document, Interaction, Person, Relationship
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import derive as derive_module
from . import person_qa
from . import search as search_module
from .models import EmbeddingConfig, Pool, PoolMembership, Tag, TalentProfile
from .serializers import (PersonDetailSerializer, PoolSerializer, TalentCardSerializer,
                          TalentProfileUpdateSerializer, TagSerializer)


def _search_kwargs(params):
    """Đổi query param -> tham số của `search.search()`.

    Tách riêng vì có HAI nơi cần đúng một ánh xạ này: tìm kiếm bình thường và
    xuất CSV (mục 15 — Exports). Viết hai lần thì sớm muộn cũng lệch nhau — một
    bên thêm bộ lọc mới, bên kia quên, và người dùng xuất ra một file khác với
    thứ họ đang nhìn trên màn hình mà không ai nhận ra.
    """
    return {
        "text": params.get("q", ""),
        "skills": params.get("skills"),
        "location": params.get("location", ""),
        "title": params.get("title", ""),
        "company": params.get("company", ""),
        "desired_location": params.get("desired_location", ""),
        "seniority": params.get("seniority", ""),
        "education": params.get("education", ""),
        "job_type": params.get("job_type", ""),
        "foreign_language": params.get("foreign_language", ""),
        "tags": params.get("tags"),
        "owner": _number(params.get("owner")),
        "pool": _number(params.get("pool")),
        "min_years": _number(params.get("min_years")),
        "max_years": _number(params.get("max_years")),
        "source": params.get("source", ""),
        "relationship_state": params.get("relationship", ""),
        "product_interest": params.get("product", ""),
        "lead_status": params.get("lead_status", ""),
        "has_open_opportunity": (True if params.get("open_opportunity") == "1"
                                 else False if params.get("open_opportunity") == "0"
                                 else None),
        "has_email": params.get("has_email") == "1",
        "has_phone": params.get("has_phone") == "1",
        "order": params.get("order", "relevance"),
    }


@api_view(["GET"])
@permission_classes([RequiresTalent])
def talent_search(request):
    """Tìm kiếm theo bộ lọc truyền thống (Master Plan mục 19.3).

    Tìm bằng ngôn ngữ tự nhiên là Phase 7 và sẽ gọi lại chính hàm này sau khi LLM
    dịch câu hỏi thành bộ tiêu chí có cấu trúc — nên các tham số ở đây chính là hợp
    đồng mà Phase 7 phải sinh ra.
    """
    params = request.query_params
    kwargs = _search_kwargs(params)
    if (kwargs["min_years"] is not None and kwargs["max_years"] is not None
            and kwargs["min_years"] > kwargs["max_years"]):
        return Response({"detail": "Số năm tối thiểu không được lớn hơn tối đa."},
                        status=status.HTTP_400_BAD_REQUEST)
    total, people = search_module.search(
        **kwargs,
        limit=_number(params.get("limit"), 50),
        offset=_number(params.get("offset"), 0),
    )
    return Response({
        "count": total,
        "results": TalentCardSerializer(people, many=True).data,
    })


@api_view(["GET"])
@permission_classes([RequiresTalent])
def recently_viewed(request):
    """Hồ sơ người dùng hiện tại đã mở, mỗi người một dòng, mới nhất trước."""
    limit = max(1, min(_number(request.query_params.get("limit"), 50), 100))
    seen = set()
    person_ids = []
    for person_id in (Interaction.objects
                      .filter(actor=request.user, action="viewed")
                      .values_list("person_id", flat=True)[:1000]):
        if person_id and person_id not in seen:
            seen.add(person_id)
            person_ids.append(person_id)
            if len(person_ids) >= limit:
                break
    people_by_id = {person.id: person for person in (
        Person.objects.filter(pk__in=person_ids, merged_into__isnull=True)
        .select_related("talent_profile")
        .prefetch_related("talent_profile__tags", "hunt_candidates__assigned_to",
                          "hunt_candidates__hunt_request__hiring_need"))}
    people = [people_by_id[pk] for pk in person_ids if pk in people_by_id]
    return Response({"count": len(people),
                     "results": TalentCardSerializer(people, many=True).data})


@api_view(["GET"])
@permission_classes([RequiresRecruiting])
def relationship_followups(request):
    """Quan hệ ứng viên dài hạn đến hạn chăm sóc, không trộn với hunt pipeline."""
    rows = (Relationship.objects.filter(
        domain="talent", owner_user=request.user, do_not_contact=False,
        next_action_at__lte=timezone.now())
        .select_related("person", "person__talent_profile")
        .prefetch_related("person__talent_profile__tags",
                          "person__hunt_candidates__assigned_to",
                          "person__hunt_candidates__hunt_request__hiring_need")
        .order_by("next_action_at")[:100])
    people = [row.person for row in rows if row.person.merged_into_id is None]
    relation_by_person = {row.person_id: row for row in rows}
    cards = TalentCardSerializer(people, many=True).data
    for card in cards:
        relation = relation_by_person[card["id"]]
        card["relationship_followup"] = {
            "state": relation.state, "next_action": relation.next_action,
            "next_action_at": relation.next_action_at, "interest_level": relation.interest_level,
        }
    return Response({"count": len(cards), "results": cards})


#: Trần một lượt xuất — đủ rộng cho quy mô demo, đủ hẹp để không khoá CSDL vì
#: một cú bấm nhầm "xuất hết".
EXPORT_LIMIT = 5000


@api_view(["GET"])
@permission_classes([RequiresTalent])
def talent_search_export(request):
    """Xuất CSV đúng những gì đang hiện trên màn hình (Master Plan mục 15).

    Dùng lại NGUYÊN VẸN `_search_kwargs` — không viết một bộ lọc "để xuất" khác
    với bộ lọc "để xem". File tải về phải khớp đúng những gì recruiter đang
    nhìn, không phải một phiên bản gần giống.
    """
    params = request.query_params
    _total, people = search_module.search(
        **_search_kwargs(params), limit=EXPORT_LIMIT, offset=0,
        max_limit=EXPORT_LIMIT)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="talent.csv"'
    # BOM để Excel trên Windows nhận đúng UTF-8 thay vì đọc nhầm bảng mã —
    # cùng nguyên nhân từng gây lỗi `.env`/`.ps1`, giờ chặn trước ở đầu ra.
    response.write("﻿")

    writer = csv.writer(response)
    writer.writerow(["Họ tên", "Chức danh", "Công ty", "Số năm KN", "Nơi ở",
                     "Email", "Điện thoại", "Kỹ năng", "Phụ trách"])
    for person in people:
        talent = getattr(person, "talent_profile", None)
        writer.writerow([
            person.display_name,
            talent.current_title if talent else "",
            talent.current_company if talent else "",
            talent.years_experience if talent else "",
            talent.location if talent else "",
            # Xuat file la luc du lieu ROI KHOI he thong — xem rb/views.py.
            privacy.mask_email(person.primary_email),
            privacy.mask_phone(person.primary_phone),
            ", ".join(talent.skills) if talent and talent.skills else "",
            talent.owner_name if talent else "",
        ])
    return response


@api_view(["GET"])
@permission_classes([RequiresTalent])
def person_detail(request, person_id):
    """Person 360 (Master Plan mục 24) — màn hình trung tâm của sản phẩm."""
    person = get_object_or_404(
        Person.objects.select_related("talent_profile")
        .prefetch_related("identities", "documents__source_records",
                          "documents__primary_text_version",
                          "documents__text_links__text_version", "signals",
                          "relationships", "links_out__related", "links_in__subject",
                          "interactions", "talent_profile__tags",
                          "hunt_candidates__assigned_to",
                          "hunt_candidates__hunt_request__hiring_need",
                          Prefetch("source_records"),
                          Prefetch("pool_memberships",
                                   queryset=PoolMembership.objects.select_related("pool"))),
        pk=person_id)

    # Person đã gộp: chuyển sang bản còn hiệu lực thay vì hiện hồ sơ rỗng.
    canonical = person.canonical()
    if canonical.pk != person.pk:
        response = Response({"redirect_to": canonical.pk},
                            status=status.HTTP_301_MOVED_PERMANENTLY)
        response["Location"] = request.build_absolute_uri(
            f"/api/v1/talent/people/{canonical.pk}/")
        return response

    _record_view(request, person)
    data = PersonDetailSerializer(person).data
    rm_only = _rm_only(request.user)
    if rm_only:
        # RM dùng chung định danh và dữ liệu nghề nghiệp cơ bản, không đọc CV,
        # lịch sử ứng tuyển hay pipeline nội bộ của tuyển dụng.
        data["documents"] = []
        data["document_stats"] = {key: 0 for key in (
            "submission_count", "file_version_count", "distinct_text_count",
            "duplicate_text_count", "unparsed_count", "ai_retry_count",
            "preview_pending_count", "text_variant_count")}
        data["sources"] = []
        data["timeline"] = [row for row in data["timeline"]
                            if row.get("detail", {}).get("domain") == "rb"
                            or str(row.get("action", "")).startswith("rb_")]
        data["pools"] = [row for row in data["pools"]
                         if Pool.objects.filter(
                             pk=row["id"], domain=Pool.DOMAIN_TALENT).exists()]
    else:
        data["pools"] = [row for row in data["pools"]
                         if Pool.objects.filter(pk=row["id"], domain=Pool.DOMAIN_TALENT).exists()]
    return Response(data)


def _rm_only(user):
    """RM thuần (RB Sales, không kiêm vai trò tuyển dụng) — dùng để lọc dữ liệu
    CV/pipeline tuyển dụng nội bộ khỏi cả trang Person 360 lẫn Q&A của trang đó,
    kẻo Q&A lộ ra nhiều hơn những gì màn hình đã cho phép RM đọc."""
    user_roles = roles.roles_of(user)
    return (roles.RB_SALES in user_roles and not user_roles.intersection(
        {roles.RECRUITER, roles.HIRING_MANAGER, roles.MANAGER, roles.ADMIN}))


@api_view(["POST"])
@permission_classes([RequiresTalent])
def person_ask(request, person_id):
    """Hỏi & đáp AI có phạm vi cho một người cụ thể — xem `talent/person_qa.py`."""
    person = get_object_or_404(
        Person.objects.select_related("talent_profile", "rb_profile")
        .prefetch_related("rb_profile__interests"),
        pk=person_id)

    question = str(request.data.get("question") or "").strip()
    if not question:
        return Response({"detail": "Thiếu câu hỏi."}, status=status.HTTP_400_BAD_REQUEST)

    raw_history = request.data.get("history")
    history = None
    if isinstance(raw_history, list):
        history = [item for item in raw_history[-person_qa.MAX_HISTORY_TURNS:]
                  if isinstance(item, dict) and item.get("question") and item.get("answer")]

    result = person_qa.ask(person, question, history=history,
                           include_recruiting=not _rm_only(request.user))
    return Response(result)


@api_view(["PATCH"])
@permission_classes([RequiresRecruiting])
def talent_profile_update(request, person_id):
    """Sửa hồ sơ talent. Trường nào sửa tay thì miễn nhiễm với việc suy lại."""
    person = get_object_or_404(Person, pk=person_id)
    profile, _ = TalentProfile.objects.get_or_create(person=person)

    serializer = TalentProfileUpdateSerializer(profile, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    changed = list(serializer.validated_data)
    serializer.save()
    if "owner" in changed:
        profile.owner_name = str(profile.owner)[:150] if profile.owner else ""
        profile.save(update_fields=["owner_name"])

    if changed:
        # Ghi lại rằng con người đã chạm vào các trường này — derive() sẽ không
        # ghi đè nữa. Đây là cơ chế giữ kiến thức của recruiter.
        profile.mark_curated(*[f for f in changed if f != "owner"])
        profile.save(update_fields=["curated_fields", "updated_at"])
        _log_interaction(request, person, "profile_edited", {"fields": changed})

    return Response(PersonDetailSerializer(person).data)


@api_view(["GET", "PATCH"])
@permission_classes([RequiresCandidateWork])
def talent_relationship(request, person_id):
    """Quan hệ dài hạn với ứng viên; độc lập với trạng thái trong từng hunt."""
    person = get_object_or_404(Person, pk=person_id, merged_into__isnull=True)
    relation, _ = Relationship.objects.get_or_create(
        person=person, domain="talent", defaults={"state": "new"})
    if request.method == "PATCH":
        state_value = request.data.get("state")
        if state_value is not None:
            if state_value not in Relationship.TALENT_STATES:
                return Response({"detail": "Trạng thái quan hệ ứng viên không hợp lệ."}, status=400)
            relation.state = state_value
        if "owner_id" in request.data:
            owner_id = request.data.get("owner_id")
            owner = get_user_model().objects.filter(pk=owner_id, is_active=True).first() if owner_id else None
            if owner_id and (owner is None or not roles.roles_of(owner).intersection(
                    {roles.RECRUITER, roles.MANAGER, roles.ADMIN})):
                return Response({"detail": "Recruiter phụ trách không hợp lệ."}, status=400)
            relation.owner_user = owner
            relation.owner = str(owner)[:150] if owner else ""
        if "interest_level" in request.data:
            try:
                level = int(request.data.get("interest_level") or 0)
            except (TypeError, ValueError):
                return Response({"detail": "Mức độ quan tâm không hợp lệ."}, status=400)
            if level < 0 or level > 5:
                return Response({"detail": "Mức độ quan tâm phải từ 0 đến 5."}, status=400)
            relation.interest_level = level
        for field, limit in (("next_action", 300), ("preferred_channel", 30),
                             ("reason", 300), ("notes", 5000)):
            if field in request.data:
                setattr(relation, field, str(request.data.get(field) or "")[:limit])
        for field in ("last_contact_at", "next_action_at"):
            if field in request.data:
                raw = request.data.get(field)
                value = parse_datetime(raw) if raw else None
                if raw and value is None:
                    return Response({"detail": "Thời gian không hợp lệ."}, status=400)
                if value and timezone.is_naive(value):
                    value = timezone.make_aware(value)
                setattr(relation, field, value)
        if "do_not_contact" in request.data:
            relation.do_not_contact = bool(request.data["do_not_contact"])
            if relation.do_not_contact:
                relation.state = "do_not_contact"
            elif relation.state == "do_not_contact":
                relation.state = "new"
        if "preferences" in request.data:
            if not isinstance(request.data["preferences"], dict):
                return Response({"detail": "Kỳ vọng nghề nghiệp không hợp lệ."}, status=400)
            relation.preferences = request.data["preferences"]
        relation.save()
        _log_interaction(request, person, "talent_relationship_updated",
                         {"domain": "talent", "state": relation.state})
    person = Person.objects.prefetch_related("relationships").get(pk=person.pk)
    row = next(item for item in PersonDetailSerializer(person).data["relationships"]
               if item["domain"] == "talent")
    return Response(row)


@api_view(["POST"])
@permission_classes([RequiresRecruiting])
def talent_rederive(request, person_id):
    """Suy lại hồ sơ từ dữ liệu nguồn.

    Trường đã sửa tay vẫn được giữ — nút này không phải nút hoàn tác.
    """
    person = get_object_or_404(Person, pk=person_id)
    derive_module.derive(person)
    return Response(PersonDetailSerializer(person).data)


@api_view(["GET"])
@permission_classes([RequiresRecruiting])
def document_download(request, document_id):
    """Tải một phiên bản CV về.

    Ghi Interaction riêng cho việc này chứ không gộp vào `viewed`: mở hồ sơ để
    xem khác với tải file CV về máy. Cái sau là lúc dữ liệu cá nhân rời khỏi hệ
    thống, và đó chính là thứ Compliance quan tâm (xem docs/ACCESS_CONTROL.md).
    """
    document = get_object_or_404(Document, pk=document_id)
    if not document.storage_key:
        return Response({"detail": "Chưa có nội dung file trên Hub."},
                        status=status.HTTP_404_NOT_FOUND)

    try:
        data = get_storage().read(document.storage_key)
    except StorageError:
        return Response({"detail": "Không đọc được file từ kho."},
                        status=status.HTTP_502_BAD_GATEWAY)

    _log_interaction(request, document.person, "document_downloaded",
                     {"document_id": document.pk, "filename": document.filename})

    response = HttpResponse(data, content_type=document.mime_type
                            or "application/octet-stream")
    # `filename*` dạng UTF-8: tên file CV hầu hết có dấu tiếng Việt, và trình
    # duyệt sẽ làm hỏng chúng nếu chỉ có `filename=`.
    encoded = quote(document.filename or f"cv-{document.pk}")
    # File gốc luôn là download. Xem inline phải đi qua endpoint preview, nơi Hub
    # chỉ trả PDF/ảnh allowlist hoặc PDF đã chuyển đổi từ Office.
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded}"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@xframe_options_exempt
@api_view(["GET"])
@permission_classes([RequiresRecruiting])
def document_preview(request, document_id):
    """Chỉ trả PDF/ảnh an toàn hoặc PDF Hub đã chuyển đổi; tự động sinh bản xem trước HTML chuẩn Word nếu chưa có PDF."""
    document = get_object_or_404(Document, pk=document_id)
    key = document.storage_key if is_safe_inline(document) else document.preview_key

    # 1. Nếu có file an toàn hoặc PDF đã tạo trong kho lưu trữ
    if key and get_storage().exists(key):
        try:
            data = get_storage().read(key)
            mime = (document.mime_type or "").lower() if is_safe_inline(document) else "application/pdf"
            response = HttpResponse(data, content_type=mime)
            response["Content-Disposition"] = "inline"
            response["X-Content-Type-Options"] = "nosniff"
            response.xframe_options_exempt = True
            _log_interaction(request, document.person, "document_previewed", {"document_id": document.pk})
            return response
        except StorageError:
            pass

    # 2. Trường hợp là file Word (.docx, .doc), text hoặc chưa có bản convert PDF binary,
    # dựng giao diện HTML xem trước định dạng tài liệu chuẩn A4 rõ nét, cho phép đọc & in ấn ngay lập tức.
    text_content = document.best_text or document.parsed_text
    filename = document.filename or f"Tài liệu CV v{document.version}"
    escaped_filename = escape(filename)

    if text_content:
        paragraphs = text_content.strip().split("\n")
        formatted_html = []
        for p in paragraphs:
            clean_p = p.strip()
            if not clean_p:
                formatted_html.append("<div style='height: 12px;'></div>")
            elif clean_p.startswith(("#", "===", "---")):
                formatted_html.append(f"<h3 style='color:#0f172a; margin:16px 0 8px; border-bottom:1px solid #e2e8f0; padding-bottom:4px;'>{escape(clean_p)}</h3>")
            else:
                formatted_html.append(f"<p style='margin:0 0 8px; line-height:1.65; color:#334155; font-size:14px;'>{escape(clean_p)}</p>")
        body_content = "".join(formatted_html)
    else:
        body_content = f"""
        <div style="text-align:center; padding:48px 20px; color:#64748b;">
            <div style="font-size:42px; margin-bottom:14px;">📄</div>
            <h3 style="color:#1e293b; margin-bottom:8px;">Bản xem trước tệp tài liệu</h3>
            <p style="margin:0 0 20px; font-size:14px;">Tệp đính kèm ({escaped_filename}) có thể được tải về trực tiếp để xem đầy đủ cấu trúc gốc.</p>
            <a href="/api/v1/talent/documents/{document.pk}/download/" 
               style="display:inline-block; background:#FF8A33; color:#fff; padding:9px 20px; border-radius:6px; text-decoration:none; font-weight:600; font-size:14px;">
               ⬇ Tải tệp gốc về máy
            </a>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Xem trước · {escaped_filename}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            padding: 20px;
            background: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            color: #1e293b;
        }}
        .doc-page {{
            max-width: 820px;
            margin: 0 auto;
            background: #ffffff;
            padding: 40px 48px;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.06);
            border: 1px solid #e2e8f0;
            min-height: 90vh;
        }}
        .doc-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 14px;
            margin-bottom: 24px;
        }}
        .doc-title {{
            font-size: 16px;
            font-weight: 700;
            color: #0f172a;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .doc-tag {{
            font-size: 11px;
            background: #e0f2fe;
            color: #0284c7;
            padding: 3px 8px;
            border-radius: 4px;
            font-weight: 600;
        }}
        .btn-download {{
            background: #FF8A33;
            color: white;
            text-decoration: none;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: opacity 0.15s;
        }}
        .btn-download:hover {{
            opacity: 0.9;
        }}
        @media print {{
            body {{ background: white; padding: 0; }}
            .doc-page {{ box-shadow: none; border: none; padding: 0; }}
            .doc-header {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="doc-page">
        <div class="doc-header">
            <div class="doc-title">
                <span>📄</span>
                <span>{escaped_filename}</span>
                <span class="doc-tag">Văn bản CV</span>
            </div>
            <a class="btn-download" href="/api/v1/talent/documents/{document.pk}/download/" target="_blank">
                ⬇ Tải file gốc
            </a>
        </div>
        <div class="doc-content">
            {body_content}
        </div>
    </div>
</body>
</html>"""

    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    response.xframe_options_exempt = True
    _log_interaction(request, document.person, "document_previewed", {"document_id": document.pk})
    return response


@api_view(["GET"])
@permission_classes([RequiresTalent])
def person_avatar(request, person_id):
    """Trích xuất ảnh chân dung đại diện từ trang 1 của CV ứng viên (hoặc tài liệu gần nhất)."""
    person = get_object_or_404(Person, pk=person_id)
    doc = person.documents.filter(storage_key__isnull=False).exclude(storage_key="").order_by("-observed_at", "-created_at").first()
    if not doc or not doc.storage_key:
        return HttpResponse(status=404)

    storage = get_storage()
    if not storage.exists(doc.storage_key):
        return HttpResponse(status=404)

    try:
        import io
        from pathlib import Path
        data = storage.read(doc.storage_key)
        ext = Path(doc.filename or "").suffix.lower()

        # Nếu là ảnh trực tiếp
        if (doc.mime_type or "").lower() in {"image/jpeg", "image/png", "image/webp"} or ext in {".jpg", ".jpeg", ".png", ".webp"}:
            from PIL import Image
            img = Image.open(io.BytesIO(data)).convert("RGB")
            w, h = img.size
            min_dim = min(w, h)
            left = (w - min_dim) // 2
            top = (h - min_dim) // 2
            img = img.crop((left, top, left + min_dim, top + min_dim))
            img.thumbnail((256, 256))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=90)
            return HttpResponse(out.getvalue(), content_type="image/jpeg")

        # Nếu là PDF
        if ext == ".pdf" or (doc.mime_type or "").lower() == "application/pdf":
            import fitz
            from PIL import Image
            pdf = fitz.open(stream=data, filetype="pdf")
            try:
                if len(pdf) == 0:
                    return HttpResponse(status=404)
                page = pdf[0]
                image_list = page.get_images(full=True)

                best_img = None
                best_score = -1

                for img_info in image_list[:10]:
                    xref = img_info[0]
                    base_image = pdf.extract_image(xref)
                    image_bytes = base_image.get("image")
                    if not image_bytes:
                        continue
                    try:
                        pil_img = Image.open(io.BytesIO(image_bytes))
                        w, h = pil_img.size

                        # Avatar chân dung thường có kích thước tối thiểu và tỉ lệ khung hình gần vuông hoặc dọc (0.55 đến 1.5)
                        if w >= 50 and h >= 50 and w <= 1600 and h <= 1600:
                            ratio = w / float(h)
                            if 0.55 <= ratio <= 1.5:
                                score = w * h
                                if 80 <= w <= 800 and 80 <= h <= 800:
                                    score += 50000
                                if score > best_score:
                                    best_score = score
                                    best_img = pil_img
                    except Exception:
                        continue

                if best_img:
                    best_img = best_img.convert("RGB")
                    w, h = best_img.size
                    min_dim = min(w, h)
                    left = (w - min_dim) // 2
                    top = (h - min_dim) // 2
                    best_img = best_img.crop((left, top, left + min_dim, top + min_dim))
                    best_img.thumbnail((256, 256))
                    out = io.BytesIO()
                    best_img.save(out, format="JPEG", quality=90)
                    return HttpResponse(out.getvalue(), content_type="image/jpeg")
            finally:
                pdf.close()
    except Exception:
        pass

    return HttpResponse(status=404)


@api_view(["GET"])
@permission_classes([RequiresRecruiting])
def document_text(request, document_id):
    """Nguyên văn CV — dùng cho panel xem nguồn khi bấm một trích dẫn.

    Che email/SĐT khi người dùng CHƯA mở khoá liên hệ hồ sơ này. Đây là toàn bộ
    văn bản CV, và 33% đoạn CV trong kho có email, 25% có số điện thoại: trả
    nguyên văn ở đây là mở một đường vòng qua hạn mức mở khoá mà mọi endpoint
    khác đang tuân thủ. Đã mở khoá rồi thì trả nguyên văn — họ đã trả một lượt.
    """
    document = get_object_or_404(
        Document.objects.select_related("primary_text_version", "person")
        .prefetch_related("text_links__text_version"), pk=document_id)
    unlocked = privacy.is_unlocked(request.user, document.person)
    show = (lambda text: text) if unlocked else privacy.redact_contacts

    versions = [{
        "id": link.text_version_id,
        "text": show(link.text_version.text),
        "text_length": link.text_version.text_length,
        "origins": link.origins,
        "provider": link.provider,
        "model": link.model,
        "quality_score": link.quality_score,
        "created_at": link.created_at,
        "is_primary": link.text_version_id == document.primary_text_version_id,
    } for link in document.text_links.all()]
    if document.parsed_text and not versions:
        versions.append({"id": 0, "text": show(document.parsed_text),
                         "text_length": len(document.parsed_text), "origins": ["legacy"],
                         "provider": "legacy", "model": "", "quality_score": document.quality_score,
                         "created_at": document.updated_at, "is_primary": True})
    return Response({"text": show(document.best_text), "parse_status": document.parse_status,
                     "parse_error": document.parse_error, "versions": versions,
                     "contacts_masked": not unlocked})


@api_view(["GET"])
@permission_classes([RequiresTalent])
def talent_facets(request):
    data = search_module.facets()
    data["pools"] = PoolSerializer(Pool.objects.filter(is_archived=False), many=True).data
    operational_roles = {roles.RECRUITER, roles.RB_SALES, roles.MANAGER, roles.ADMIN}
    data["owners"] = [{"id": user.pk, "name": str(user)} for user in
                      get_user_model().objects.filter(is_active=True)
                      if roles.roles_of(user).intersection(operational_roles)]
    data["relationships"] = [
        {"value": "new", "label": "Mới trong kho"},
        {"value": "attempted", "label": "Đã thử liên hệ"},
        {"value": "connected", "label": "Đã kết nối"},
        {"value": "interested", "label": "Có quan tâm"},
        {"value": "nurturing", "label": "Đang nuôi dưỡng"},
        {"value": "ready", "label": "Sẵn sàng cho cơ hội"},
        {"value": "placed", "label": "Đã tuyển"},
        {"value": "unavailable", "label": "Chưa sẵn sàng"},
        {"value": "do_not_contact", "label": "Không liên hệ"},
    ]
    from rb.models import PRODUCT_CHOICES, RBProfile
    data["products"] = [{"value": value, "label": label}
                        for value, label in PRODUCT_CHOICES]
    data["lead_statuses"] = [{"value": value, "label": label}
                             for value, label in RBProfile.LEAD_CHOICES]
    return Response(data)


# ---------------- Cấu hình embedding (dense retrieval kho CV) ----------------

def _embedding_config_payload(cfg, *, probe=False):
    from django.db.models import F
    from ai.models import ProviderConfig
    from talent import vector_index
    from .models import CVChunk, PersonSearchDocument
    resolved = cfg.resolve()
    gemini_pc = ProviderConfig.objects.filter(provider="gemini").first()
    greennode_pc = ProviderConfig.objects.filter(provider="greennode").first()
    payload = {
        "mode": cfg.mode,
        "mode_choices": [{"value": v, "label": lbl} for v, lbl in EmbeddingConfig.MODE_CHOICES],
        "selfhost_base_url": cfg.selfhost_base_url,
        "selfhost_model": cfg.selfhost_model,
        "gemini_model": cfg.gemini_model,
        "greennode_model": cfg.greennode_model,
        "dimensions": cfg.dimensions,
        "updated_at": cfg.updated_at,
        "updated_by": cfg.updated_by,
        "active": resolved is not None,
        "effective": ({"provider": resolved[0], "model": resolved[3]} if resolved else None),
        "gemini_key_present": bool(gemini_pc and gemini_pc.get_api_key()),
        "greennode_key_present": bool(greennode_pc and greennode_pc.enabled and greennode_pc.get_api_key()),
        "coverage": {
            "projections": PersonSearchDocument.objects.count(),
            "projections_embedded": PersonSearchDocument.objects.filter(
                embedding_fingerprint=F("fingerprint")).count(),
            "chunks": CVChunk.objects.count(),
            "chunks_embedded": CVChunk.objects.filter(
                embedding_fingerprint=F("fingerprint")).count(),
        },
    }
    if probe:
        vec, model = vector_index.embed("chuyên viên quan hệ khách hàng cá nhân",
                                        task_type="RETRIEVAL_QUERY")
        payload["probe"] = {"ok": bool(vec), "model": model,
                            "dims": len(vec) if vec else None}
    return payload


@api_view(["GET", "PUT"])
@permission_classes([RequiresAiSettings])
def embedding_config(request):
    """Chọn nguồn embedding cho hỏi đáp kho CV — Gemini API hay endpoint tự host.

    PUT đổi `mode`/model ⇒ đánh dấu toàn bộ vector "cần tính lại"; worker nền
    `embed_talent_index` sẽ backfill dần bằng nguồn mới.
    """
    cfg = EmbeddingConfig.load()
    if request.method == "GET":
        return Response(_embedding_config_payload(
            cfg, probe=request.query_params.get("probe") in ("1", "true")))

    data = request.data
    before = (cfg.mode, cfg.selfhost_base_url, cfg.selfhost_model, cfg.gemini_model,
              cfg.greennode_model,
              cfg.dimensions)
    if "mode" in data:
        if data["mode"] not in dict(EmbeddingConfig.MODE_CHOICES):
            return Response({"detail": "Chế độ embedding không hợp lệ."}, status=400)
        cfg.mode = data["mode"]
    for field in ("selfhost_base_url", "selfhost_model", "gemini_model", "greennode_model"):
        if field in data:
            setattr(cfg, field, str(data[field] or "")[:300])
    if "dimensions" in data:
        try:
            dims = int(data["dimensions"])
        except (TypeError, ValueError):
            return Response({"detail": "Số chiều không hợp lệ."}, status=400)
        if not (64 <= dims <= 4096):
            return Response({"detail": "Số chiều phải trong khoảng 64–4096."}, status=400)
        cfg.dimensions = dims
    cfg.updated_by = str(request.user)[:150]
    cfg.save()

    from ai.router import reset_router
    reset_router()

    changed = before != (cfg.mode, cfg.selfhost_base_url, cfg.selfhost_model,
                          cfg.gemini_model, cfg.greennode_model, cfg.dimensions)
    rebackfilled = False
    if changed:
        from .models import CVChunk, PersonSearchDocument
        # Vector cũ (nguồn/model khác) không trộn được với nguồn mới — đánh dấu
        # tất cả "cần tính lại". Worker nền tự backfill; không xoá vector ngay để
        # tìm kiếm không rơi về 0 giữa chừng nếu backfill đang chạy.
        PersonSearchDocument.objects.exclude(embedding_fingerprint="").update(
            embedding_fingerprint="pending-reembed")
        CVChunk.objects.exclude(embedding_fingerprint="").update(
            embedding_fingerprint="pending-reembed")
        rebackfilled = True

    payload = _embedding_config_payload(cfg, probe=True)
    payload["needs_rebackfill"] = rebackfilled
    return Response(payload)


# ---------------- Nhãn ----------------

@api_view(["GET", "POST"])
@permission_classes([RequiresTalent])
def tag_list(request):
    if request.method == "POST":
        name = str(request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "Thiếu tên nhãn."},
                            status=status.HTTP_400_BAD_REQUEST)
        tag, _ = Tag.objects.get_or_create(name=name)
        return Response(TagSerializer(tag).data, status=status.HTTP_201_CREATED)
    return Response({"results": TagSerializer(Tag.objects.all(), many=True).data})


@api_view(["POST", "DELETE"])
@permission_classes([RequiresRecruiting])
def person_tags(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    profile, _ = TalentProfile.objects.get_or_create(person=person)
    slug = str(request.data.get("tag") or "").strip()
    tag = Tag.objects.filter(slug=slug).first() or Tag.objects.filter(name=slug).first()
    if tag is None:
        return Response({"detail": f"Không có nhãn: {slug}"},
                        status=status.HTTP_404_NOT_FOUND)

    if request.method == "DELETE":
        profile.tags.remove(tag)
        _log_interaction(request, person, "untagged", {"tag": tag.slug})
    else:
        profile.tags.add(tag)
        _log_interaction(request, person, "tagged", {"tag": tag.slug})
    return Response(PersonDetailSerializer(person).data)


# ---------------- Pool ----------------

@api_view(["GET", "POST"])
@permission_classes([RequiresTalent])
def pool_list(request):
    raw_domain = (request.data.get("domain") if request.method == "POST"
                  else request.query_params.get("domain"))
    domain = str(raw_domain or Pool.DOMAIN_TALENT)
    if domain not in dict(Pool.DOMAIN_CHOICES):
        return Response({"detail": "Loại nhóm không hợp lệ."},
                        status=status.HTTP_400_BAD_REQUEST)
    if domain == Pool.DOMAIN_RB and not roles.can_access(request.user, roles.MODULE_RB):
        return Response({"detail": "Không có quyền với nhóm khách hàng."},
                        status=status.HTTP_403_FORBIDDEN)
    if request.method == "POST":
        name = str(request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "Thiếu tên pool."},
                            status=status.HTTP_400_BAD_REQUEST)
        pool = Pool.objects.create(
            name=name[:150],
            domain=domain,
            description=str(request.data.get("description") or "")[:2000],
            owner=request.user if request.user.is_authenticated else None)
        return Response(PoolSerializer(pool).data, status=status.HTTP_201_CREATED)

    pools = Pool.objects.filter(is_archived=False, domain=domain)
    return Response({"results": PoolSerializer(pools, many=True).data})


@api_view(["PATCH", "DELETE"])
@permission_classes([RequiresTalent])
def pool_detail(request, pool_id):
    pool = get_object_or_404(Pool, pk=pool_id)
    if pool.domain == Pool.DOMAIN_RB and not roles.can_access(request.user, roles.MODULE_RB):
        return Response({"detail": "Không có quyền với nhóm khách hàng."},
                        status=status.HTTP_403_FORBIDDEN)
    if request.method == "DELETE":
        pool.is_archived = True
        pool.save(update_fields=["is_archived", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
    if "name" in request.data:
        name = str(request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "Thiếu tên nhóm."}, status=400)
        pool.name = name[:150]
    if "description" in request.data:
        pool.description = str(request.data.get("description") or "")[:2000]
    if "is_archived" in request.data:
        pool.is_archived = bool(request.data["is_archived"])
    pool.save()
    return Response(PoolSerializer(pool).data)


@api_view(["GET", "POST", "DELETE"])
@permission_classes([RequiresTalent])
def pool_members(request, pool_id):
    pool = get_object_or_404(Pool, pk=pool_id)
    if pool.domain == Pool.DOMAIN_RB and not roles.can_access(request.user, roles.MODULE_RB):
        return Response({"detail": "Không có quyền với nhóm khách hàng."},
                        status=status.HTTP_403_FORBIDDEN)
    if request.method == "GET":
        people = list(Person.objects.filter(
            pool_memberships__pool=pool, merged_into__isnull=True)
            .select_related("talent_profile")
            .prefetch_related("talent_profile__tags", "hunt_candidates__assigned_to",
                              "hunt_candidates__hunt_request__hiring_need"))
        return Response({"pool": PoolSerializer(pool).data, "count": len(people),
                         "results": TalentCardSerializer(people, many=True).data})
    person = get_object_or_404(Person, pk=request.data.get("person_id"))

    if request.method == "DELETE":
        PoolMembership.objects.filter(pool=pool, person=person).delete()
        _log_interaction(request, person, "removed_from_pool", {"pool": pool.name})
    else:
        PoolMembership.objects.get_or_create(
            pool=pool, person=person,
            defaults={"added_by": request.user if request.user.is_authenticated else None,
                      "note": str(request.data.get("note") or "")[:300]})
        _log_interaction(request, person, "added_to_pool", {"pool": pool.name})
    return Response(PoolSerializer(pool).data)


# ---------------- Nội bộ ----------------

def _record_view(request, person):
    """Ghi lượt xem hồ sơ, khử trùng lặp trong ngày.

    Không khử trùng lặp thì timeline của Person 360 sẽ toàn dòng "đã xem" và không
    còn đọc được. Nhật ký truy cập đầy đủ phục vụ tuân thủ là việc của AccessLog ở
    Phase 5B — hai thứ khác nhau, xem docs/ACCESS_CONTROL.md mục 3.
    """
    user = request.user if request.user.is_authenticated else None
    if user is None:
        return
    # `occurred_at__date` so Django quy đổi sang TIME_ZONE (Asia/Ho_Chi_Minh)
    # trước khi lấy ngày. So với `timezone.now().date()` (ngày theo UTC) thì
    # lệch nhau suốt khoảng 17:00–23:59 UTC — đúng lúc đó dedup luôn thấy
    # "chưa xem hôm nay" dù vừa tạo dòng cách đó một giây, và timeline ngập
    # dòng "đã xem". Phải quy đổi sang local trước khi lấy `.date()`.
    today = timezone.localtime(timezone.now()).date()
    already = Interaction.objects.filter(
        person=person, actor=user, action="viewed",
        occurred_at__date=today).exists()
    if not already:
        user_roles = roles.roles_of(user)
        domain = ("rb" if roles.RB_SALES in user_roles and not user_roles.intersection(
            {roles.RECRUITER, roles.HIRING_MANAGER}) else "talent")
        Interaction.objects.create(person=person, actor=user, action="viewed",
                                   domain=domain, detail={"domain": domain})


def _log_interaction(request, person, action, detail=None):
    Interaction.objects.create(
        person=person, action=action,
        actor=request.user if request.user.is_authenticated else None,
        detail=detail or {})


def _number(value, default=None):
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return int(number) if number == int(number) else number
