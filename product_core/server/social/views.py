# -*- coding: utf-8 -*-
"""API Social Radar (Master Plan mục 29–34, PHASE 10–11).

Đường vào của bài đăng có hai lối, cùng đổ về một chỗ:

    POST /api/v1/social/ingest/     Edge gửi lô bài bắt được từ nhóm
    POST /api/v1/social/analyze/    người dùng dán một bài vào để xem thử

Lối thứ hai không phải đồ chơi. Nó cho phép **demo được Social Radar khi chưa có
adapter Facebook ở Edge**, và quan trọng hơn: nó là cách nhanh nhất để một người
nghiệp vụ kiểm chứng xem AI chấm ý định có đúng không, bằng chính những bài họ
đọc hằng ngày.
"""
import logging

from accounts.permissions import RequiresSocial
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import intent as intent_module
from . import pipeline
from .models import (Community, SocialAccount, SocialAction, SocialComment,
                     SocialPost)
from .serializers import (CommunitySerializer, SocialAccountSerializer,
                          SocialActionSerializer, SocialPostSerializer)

log = logging.getLogger(__name__)

MAX_INGEST_BATCH = 100


@api_view(["POST"])
@permission_classes([RequiresSocial])
def analyze(request):
    """Dán một bài vào, xem AI đọc ra gì. Không lưu gì trừ khi `save=true`.

    Mặc định KHÔNG lưu: người dùng thử nghiệm bằng bài viết của người thật, và
    một nút "xem thử" mà âm thầm ghi dữ liệu cá nhân vào CSDL là thứ không nên
    tồn tại trong hệ thống ngân hàng.
    """
    content = str(request.data.get("content") or "").strip()
    if not content:
        return Response({"detail": "Chưa có nội dung bài."},
                        status=status.HTTP_400_BAD_REQUEST)

    community = None
    if request.data.get("community"):
        community = Community.objects.filter(pk=request.data["community"]).first()

    author_name = str(request.data.get("author_name") or "")[:200]
    result = intent_module.detect(content, community=community,
                                  author_name=author_name)

    if not request.data.get("save"):
        # Vẫn thử khớp người để trả lời câu hỏi đáng giá nhất — "ta đã biết
        # người này chưa?" — nhưng không ghi gì lại.
        post = SocialPost(content=content, author_name=author_name,
                          community=community,
                          author_url=str(request.data.get("author_url") or "")[:200],
                          contacts=result.contacts)
        matched = pipeline._resolve_author(post, result)
        return Response({
            "saved": False,
            "intent": result.as_dict(),
            "matched_person": post.person_id,
            "matched_person_name": post.person.display_name if matched else "",
            "history_note": pipeline.history_note(post.person if matched else None),
        })

    post = SocialPost.objects.create(
        provider=str(request.data.get("provider") or "facebook")[:20],
        external_id=str(request.data.get("external_id")
                        or f"paste-{timezone.now().timestamp():.0f}")[:200],
        community=community, content=content, author_name=author_name,
        author_url=str(request.data.get("author_url") or "")[:200],
        posted_at=timezone.now())
    processed = pipeline.process(post)
    return Response({"saved": True, **processed.as_dict(),
                     "post": SocialPostSerializer(processed.post).data},
                    status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([RequiresSocial])
@transaction.atomic
def ingest(request):
    """Edge gửi lô bài bắt được. Idempotent theo (provider, external_id)."""
    rows = request.data.get("posts")
    if not isinstance(rows, list) or not rows:
        return Response({"detail": "Cần danh sách `posts`."},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(rows) > MAX_INGEST_BATCH:
        return Response({"detail": f"Tối đa {MAX_INGEST_BATCH} bài mỗi lô."},
                        status=status.HTTP_400_BAD_REQUEST)

    saved, skipped = [], 0
    for row in rows:
        content = str(row.get("content") or "").strip()
        external_id = str(row.get("external_id") or "").strip()
        if not content or not external_id:
            skipped += 1
            continue

        community = None
        if row.get("community_external_id"):
            community, _ = Community.objects.get_or_create(
                provider=str(row.get("provider") or "facebook")[:20],
                external_id=str(row["community_external_id"])[:200],
                defaults={"name": str(row.get("community_name") or "")[:300]})

        post, created = SocialPost.objects.get_or_create(
            provider=str(row.get("provider") or "facebook")[:20],
            external_id=external_id[:200],
            defaults={
                "community": community,
                "author_name": str(row.get("author_name") or "")[:200],
                "author_handle": str(row.get("author_handle") or "")[:200],
                "author_url": str(row.get("author_url") or "")[:200],
                "content": content,
                "url": str(row.get("url") or "")[:200],
                "posted_at": row.get("posted_at") or timezone.now(),
            })

        for comment in (row.get("comments") or [])[:20]:
            SocialComment.objects.get_or_create(
                post=post, external_id=str(comment.get("external_id") or "")[:200],
                defaults={"author_name": str(comment.get("author_name") or "")[:200],
                          "content": str(comment.get("content") or "")})

        # Chỉ chấm bài mới. Chấm lại cả lô mỗi lần Edge gửi sẽ đốt hạn mức LLM
        # vào những bài đã có câu trả lời.
        if created:
            saved.append(pipeline.process(post).as_dict())
        else:
            skipped += 1

    return Response({"received": len(rows), "processed": len(saved),
                     "skipped": skipped, "results": saved})


@api_view(["GET"])
@permission_classes([RequiresSocial])
def post_list(request):
    queryset = (SocialPost.objects.select_related("community", "person")
                .exclude(status=SocialPost.STATUS_IGNORED))

    if request.query_params.get("domain"):
        # Lọc theo nghiệp vụ bằng ngưỡng của chính nghiệp vụ đó.
        domain = request.query_params["domain"]
        threshold = pipeline.THRESHOLDS.get(domain, 0.5)
        ids = [p.pk for p in queryset if p.score(domain) >= threshold]
        queryset = queryset.filter(pk__in=ids)
    if request.query_params.get("linked") == "1":
        queryset = queryset.filter(person__isnull=False)

    limit = min(100, max(1, int(request.query_params.get("limit") or 50)))
    return Response({"count": queryset.count(),
                     "results": SocialPostSerializer(queryset[:limit], many=True).data})


@api_view(["POST"])
@permission_classes([RequiresSocial])
def rescore(request, post_id):
    """Chấm lại một bài — dùng khi đổi model hoặc khi AI vừa hết bận."""
    post = get_object_or_404(SocialPost, pk=post_id)
    return Response(pipeline.process(post).as_dict())


@api_view(["GET", "POST"])
@permission_classes([RequiresSocial])
def community_list(request):
    if request.method == "POST":
        name = str(request.data.get("name") or "").strip()
        external_id = str(request.data.get("external_id") or "").strip()
        if not name or not external_id:
            return Response({"detail": "Cần tên nhóm và mã nhóm."},
                            status=status.HTTP_400_BAD_REQUEST)
        community, _ = Community.objects.get_or_create(
            provider=str(request.data.get("provider") or "facebook")[:20],
            external_id=external_id[:200],
            defaults={"name": name[:300],
                      "topic": str(request.data.get("topic") or "")[:200],
                      "url": str(request.data.get("url") or "")[:200]})
        return Response(CommunitySerializer(community).data,
                        status=status.HTTP_201_CREATED)

    return Response({"results": CommunitySerializer(
        Community.objects.all()[:100], many=True).data})


@api_view(["GET"])
@permission_classes([RequiresSocial])
def account_list(request):
    return Response({"results": SocialAccountSerializer(
        SocialAccount.objects.all()[:100], many=True).data})


@api_view(["GET", "POST"])
@permission_classes([RequiresSocial])
def action_list(request):
    if request.method == "POST":
        action = SocialAction.objects.create(
            post_id=request.data.get("post") or None,
            community_id=request.data.get("community") or None,
            hiring_need_id=request.data.get("hiring_need") or None,
            kind=str(request.data.get("kind") or SocialAction.KIND_COMMENT)[:20],
            content=str(request.data.get("content") or ""),
            created_by=request.user if request.user.is_authenticated else None)
        return Response(SocialActionSerializer(action).data,
                        status=status.HTTP_201_CREATED)
    return Response({"results": SocialActionSerializer(
        SocialAction.objects.all()[:100], many=True).data})
