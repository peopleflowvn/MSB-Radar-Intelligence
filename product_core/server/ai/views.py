# -*- coding: utf-8 -*-
"""API trang cài đặt AI trên Hub.

Chỉ người đã đăng nhập mới vào được. Khoá API của Edge **không** mở được các
endpoint này — Edge là máy thu thập dữ liệu, không có việc gì với cấu hình AI.

Quy tắc xuyên suốt: **khoá API không bao giờ rời máy chủ ở dạng đầy đủ.** Chỉ
trả về dạng che (6 ký tự đầu + chấm). Muốn đổi thì gửi khoá mới lên, không có
đường đọc khoá cũ ra.
"""
import logging
import uuid
from datetime import timedelta

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rest_framework import serializers
from accounts.permissions import RequiresAiSettings

from .models import AssistantThread, LLMCall, ProviderConfig, TaskModelRoute
from .providers import (LLMError, OpenAICompatibleProvider, PROVIDER_DEFAULTS,
                        list_models)
from . import catalog
from . import router as router_module
from . import tasks as tasks_registry
from .router import _provider_from_config, get_router, reset_router

log = logging.getLogger(__name__)

# Các task LLM có mặt trong nghiệp vụ — `/settings` hiển thị provider/model đang
# THỰC SỰ có hiệu lực cho từng cái, kể cả khi chưa có TaskModelRoute (đang chạy
# bằng env/bootstrap). Không hiện thì "env vô hình" và người vận hành phải đoán.
#
# Danh sách lấy từ `ai/tasks.py` — nguồn sự thật DUY NHẤT.
#
# Trước đây đây là một mảng chuỗi viết tay và nó đã lệch: 8 tác vụ không hiện ra
# (người vận hành không đổi model được), còn `talent_explain` thì vẫn nằm trong
# danh sách sau khi `talent/ai_search.py` bị gỡ — một ô cấu hình không nối vào
# đâu cả. `tests_task_registry` khoá chặt để không lệch lại.
KNOWN_TASKS = tasks_registry.names()


def _thread_payload(row, include_messages=False):
    from .public_trace import public_metadata
    payload = {
        "id": row.pk, "conversation_id": row.thread_id, "surface": row.surface,
        "title": row.title or "Cuộc trò chuyện mới", "archived": row.archived,
        "summary": row.summary, "state": row.state,
        "created_at": row.created_at, "updated_at": row.updated_at,
        "last_message_at": row.last_message_at,
    }
    if include_messages:
        payload["messages"] = [
            {"id": message.pk, "role": message.role, "content": message.content,
             "metadata": public_metadata(message.metadata), "provider": message.provider,
             "model": message.model, "client_turn_id": message.client_turn_id,
             "created_at": message.created_at}
            for message in row.messages.all()[:200]
        ]
    return payload


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", ""))[:64]


def _audit_conversation_delete(request, row):
    """Ghi AccessLog cho lượt xoá cứng hội thoại (Master Plan §21.5)."""
    try:
        from accounts.models import AccessLog
        AccessLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            user_name=str(request.user)[:150], action=AccessLog.ACTION_DELETE,
            module="ai", object_type="assistant_thread", object_id=str(row.thread_id)[:64],
            path=request.path[:300], method="DELETE", ip=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
            extra={"surface": row.surface,
                   "message_count": row.messages.count(),
                   "event_count": row.events.count(),
                   "had_reasoning_trace": row.messages.filter(
                       metadata__has_key="reasoning_trace").exists()})
    except Exception:                          # noqa: BLE001
        log.exception("Không ghi được AccessLog khi xoá hội thoại %s", row.thread_id)


def _resolve_thread(request, thread_id):
    """Tìm thread theo (user, thread_id) + surface nếu client gửi kèm.

    `thread_id` chỉ unique cùng với `surface` (`uq_assistant_thread`). Không lọc
    theo surface thì hai hội thoại talent/prospect cùng id sẽ lẫn nhau.
    """
    rows = AssistantThread.objects.filter(user=request.user, thread_id=thread_id)
    surface = str(request.query_params.get("surface")
                  or (request.data.get("surface") if request.method == "PATCH" else "") or "")
    if surface in dict(AssistantThread.SURFACE_CHOICES):
        rows = rows.filter(surface=surface)
    return rows.order_by("-updated_at").first()


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def conversation_list(request):
    if request.method == "POST":
        surface = str(request.data.get("surface") or "talent")
        if surface not in dict(AssistantThread.SURFACE_CHOICES):
            return Response({"detail": "Màn hình hội thoại không hợp lệ."}, status=400)
        thread_id = str(request.data.get("conversation_id") or uuid.uuid4())[:64]
        row, created = AssistantThread.objects.get_or_create(
            user=request.user, surface=surface, thread_id=thread_id,
            defaults={"title": str(request.data.get("title") or "")[:160]})
        return Response(_thread_payload(row, include_messages=True), status=201 if created else 200)

    surface = str(request.query_params.get("surface") or "")
    rows = AssistantThread.objects.filter(user=request.user, archived=False)
    if surface:
        rows = rows.filter(surface=surface)
    rows = rows.order_by("-last_message_at", "-updated_at")[:100]
    return Response({"results": [_thread_payload(row) for row in rows]})


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def conversation_detail(request, thread_id):
    row = _resolve_thread(request, thread_id)
    if row is None:
        return Response({"detail": "Không tìm thấy cuộc trò chuyện."}, status=404)
    if request.method == "GET":
        return Response(_thread_payload(row, include_messages=True))
    if request.method == "DELETE":
        _audit_conversation_delete(request, row)
        # Xoá cứng: message, event log và derived memory của thread đi cùng
        # (CASCADE). reasoning_trace nằm trong message nên cũng biến mất.
        row.delete()
        return Response(status=204)
    fields = []
    if "title" in request.data:
        row.title = " ".join(str(request.data.get("title") or "").split())[:160]
        fields.append("title")
    if "archived" in request.data:
        row.archived = bool(request.data.get("archived"))
        fields.append("archived")
    if fields:
        row.save(update_fields=fields + ["updated_at"])
    return Response(_thread_payload(row, include_messages=True))


class ProviderUpdateSerializer(serializers.Serializer):
    """Kiểm tra dữ liệu trước khi ghi.

    Mọi trường đều `required=False`: đây là PATCH, client chỉ gửi cái muốn đổi.
    Đặc biệt `api_key` — không gửi nghĩa là giữ nguyên khoá đang dùng, chứ không
    phải xoá nó.

    Dùng serializer chứ không dựa vào Model.full_clean(): trên SQLite,
    PositiveIntegerField âm lọt qua tầng validate của Django rồi mới nổ thành
    IntegrityError lúc ghi — người dùng nhận 500 thay vì một thông báo dễ hiểu.
    """

    enabled = serializers.BooleanField(required=False)
    priority = serializers.IntegerField(required=False, min_value=0, max_value=10_000)
    base_url = serializers.CharField(required=False, allow_blank=True, max_length=300)
    model = serializers.CharField(required=False, allow_blank=True, max_length=120)
    timeout = serializers.IntegerField(required=False, min_value=1, max_value=600)
    api_key = serializers.CharField(required=False, allow_blank=True, max_length=500,
                                    trim_whitespace=True)


class TaskRouteSerializer(serializers.Serializer):
    task = serializers.CharField(max_length=60)
    provider = serializers.ChoiceField(choices=ProviderConfig.PROVIDER_CHOICES)
    model = serializers.CharField(required=False, allow_blank=True, max_length=120)
    enabled = serializers.BooleanField(required=False, default=True)


def _serialize(config):
    defaults = PROVIDER_DEFAULTS.get(config.provider, {})
    return {
        "provider": config.provider,
        "label": config.get_provider_display(),
        "enabled": config.enabled,
        "priority": config.priority,
        # Chỉ dạng che. Không có endpoint nào trả khoá đầy đủ.
        "api_key_hint": config.api_key_hint,
        "has_api_key": config.has_api_key,
        "key_readable": config.key_readable,
        "key_count": config.key_count,
        # Trạng thái từng khoá lúc chạy: khoá nào đang nghỉ vì hết hạn mức, khoá
        # nào đã bị tắt vì sai. Không hiện thì người vận hành thấy "có 3 khoá" mà
        # không biết 2 trong số đó đã hỏng.
        "keys": _key_status(config),
        "base_url": config.base_url,
        "base_url_default": defaults.get("base_url", ""),
        "model": config.model,
        "model_default": defaults.get("model", ""),
        "timeout": config.timeout,
        "ready": bool(config.get_api_key() and (config.model or defaults.get("model"))),
        "last_checked_at": config.last_checked_at,
        "last_check_ok": config.last_check_ok,
        "last_check_detail": config.last_check_detail,
        "updated_at": config.updated_at,
        "updated_by": config.updated_by,
    }


def _key_status(config):
    """Trạng thái xoay khoá đang chạy, lấy từ provider mà router đang giữ.

    Đọc từ instance router đang dùng chứ không dựng mới: trạng thái nghỉ/tắt nằm
    trong bộ nhớ của KeyPool, dựng lại sẽ ra một pool trắng tinh và luôn báo
    "mọi khoá đều khoẻ".
    """
    provider = get_router().get_provider(config.provider)
    if provider is None or not hasattr(provider, "keys"):
        return []
    return provider.keys.status()


def _ensure_rows():
    """Tạo sẵn một hàng cho mỗi nhà cung cấp được hỗ trợ.

    Trang cài đặt luôn hiển thị đủ bốn ô, kể cả nhà cung cấp chưa ai đụng tới —
    người dùng thấy được những gì có thể bật, không phải đoán.
    """
    priorities = {"greennode": 10, "openai": 20, "gemini": 30, "deepseek": 40}
    for name, _label in ProviderConfig.PROVIDER_CHOICES:
        ProviderConfig.objects.get_or_create(
            provider=name,
            defaults={"priority": priorities.get(name, 100),
                      "enabled": False})


@api_view(["GET"])
@permission_classes([RequiresAiSettings])
def provider_list(request):
    _ensure_rows()
    rows = [_serialize(c) for c in ProviderConfig.objects.all()]
    router = get_router()
    return Response({
        "results": rows,
        # Thứ tự thực tế router sẽ thử — quan trọng vì nó là kết quả của cả
        # cấu hình CSDL lẫn biến môi trường, không phải chỉ bảng trên màn hình.
        "active_order": router.provider_order(),
        "available": router.available(),
        "task_routes": [{
            "task": route.task, "provider": route.provider, "model": route.model,
            "enabled": route.enabled, "updated_at": route.updated_at,
            "updated_by": route.updated_by,
            "effective": router.effective_config(route.task),
        } for route in TaskModelRoute.objects.all()],
        # Provider/model đang thực thi cho MỌI task quan trọng (union KNOWN_TASKS
        # với các route đang có), kèm nguồn cấu hình và tên biến env đang override.
        "effective_tasks": [
            router.effective_config(task) for task in
            dict.fromkeys(KNOWN_TASKS + list(
                TaskModelRoute.objects.values_list("task", flat=True)))
        ],
        # Nhãn tiếng Việt + mô tả cho từng tác vụ, để `/settings` cho CHỌN thay
        # vì bắt gõ tay mã. Gõ tay nghĩa là chỉ đổi được thứ mình đã biết tên —
        # và người vận hành không có cách nào biết `rb_prospect_search` là gì.
        "task_catalog": tasks_registry.as_payload(),
        "task_groups": tasks_registry.GROUPS,
        # Danh mục model theo nhà cung cấp, kèm cờ năng lực — để ô model là
        # danh sách chọn có chú thích chứ không phải ô chữ trống. Ô trống thì
        # gõ sai một ký tự cũng không ai báo: router cứ gửi, nhà cung cấp trả
        # 404, và tác vụ im lặng rơi sang provider sau.
        **catalog.payload(),
    })


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([RequiresAiSettings])
def task_route(request, task):
    """Route DB theo task; GET luôn cho biết cấu hình runtime thực tế."""
    task = str(task or "").strip().lower()
    if not task or len(task) > 60:
        return Response({"detail": "Tên tác vụ không hợp lệ."}, status=400)
    row = TaskModelRoute.objects.filter(task=task).first()
    if request.method == "GET":
        return Response({"route": ({"task": row.task, "provider": row.provider,
                                    "model": row.model, "enabled": row.enabled}
                                   if row else None),
                         "effective": get_router().effective_config(task)})
    if request.method == "DELETE":
        if row:
            row.delete()
        reset_router()
        return Response(status=204)
    form = TaskRouteSerializer(data={**request.data, "task": task})
    form.is_valid(raise_exception=True)
    data = form.validated_data
    row, _created = TaskModelRoute.objects.update_or_create(
        task=task,
        defaults={"provider": data["provider"], "model": data.get("model", ""),
                  "enabled": data.get("enabled", True),
                  "updated_by": str(request.user)[:150]},
    )
    reset_router()
    return Response({"route": {"task": row.task, "provider": row.provider,
                                "model": row.model, "enabled": row.enabled},
                     "effective": get_router().effective_config(task)})


@api_view(["PATCH"])
@permission_classes([RequiresAiSettings])
def provider_update(request, provider):
    _ensure_rows()
    config = ProviderConfig.objects.filter(provider=provider).first()
    if config is None:
        return Response({"detail": f"Nhà cung cấp không hỗ trợ: {provider}"},
                        status=status.HTTP_404_NOT_FOUND)

    form = ProviderUpdateSerializer(data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    data = form.validated_data

    for field in ("enabled", "priority", "base_url", "model", "timeout"):
        if field in data:
            setattr(config, field, data[field])

    # Khoá xử lý riêng: chỉ ghi khi client THẬT SỰ gửi lên. Nếu không, một lần
    # lưu form bình thường sẽ xoá mất khoá đang dùng.
    if "api_key" in data:
        config.set_api_key(data["api_key"])
        # Kết quả kiểm tra của khoá cũ không nói gì về khoá mới.
        config.last_checked_at = None
        config.last_check_ok = None
        config.last_check_detail = ""

    config.updated_by = str(request.user)[:150]
    config.save()

    # Router nhớ nhà cung cấp đã dựng; không xoá thì thay đổi chưa có hiệu lực.
    reset_router()
    return Response(_serialize(config))


@api_view(["POST"])
@permission_classes([RequiresAiSettings])
def provider_test(request, provider):
    """Gọi thật nhà cung cấp để xác nhận khoá và mã model dùng được.

    Thử **từng khoá một**, không phải gọi một lượt rồi kết luận cho cả nhà cung
    cấp. Với sáu khoá, một khoá hỏng sẽ vô hình cho tới lúc nó tình cờ được xoay
    tới — thường là giữa buổi demo. Người vận hành cần biết khoá NÀO hỏng, chứ
    không phải biết rằng "có gì đó hỏng".

    Prompt cực ngắn: mục đích là chứng minh đường đi thông, không phải đánh giá
    chất lượng model.
    """
    config = ProviderConfig.objects.filter(provider=provider).first()
    if config is None:
        return Response({"detail": "Chưa có cấu hình cho nhà cung cấp này."},
                        status=status.HTTP_404_NOT_FOUND)

    keys = config.get_api_keys()
    if not keys:
        detail = ("Khoá đã lưu nhưng không giải mã được — hãy nhập lại."
                  if config.has_api_key else "Chưa nhập khoá API.")
        return _save_check(config, False, detail)

    defaults = PROVIDER_DEFAULTS.get(config.provider, {})
    base_url = config.base_url or defaults.get("base_url", "")
    model = config.model or defaults.get("model", "")

    rows, ok_count = [], 0
    for index, key in enumerate(keys, 1):
        single = OpenAICompatibleProvider(
            name=config.provider, base_url=base_url, api_key=key,
            model=model, timeout=config.timeout or 60)
        label = f"{key[:8]}…{key[-4:]}"
        try:
            # `reasoning_effort` để model không tiêu hết hạn mức vào bước
            # suy nghĩ rồi trả về chuỗi rỗng — chỗ này chỉ cần chứng minh
            # đường đi thông.
            result = single.complete([{"role": "user", "content": "ping"}],
                                     max_tokens=20, reasoning_effort="none")
        except LLMError as exc:
            rows.append({"index": index, "label": label, "ok": False,
                         "detail": str(exc)[:200]})
            continue
        ok_count += 1
        rows.append({"index": index, "label": label, "ok": True,
                     "detail": f"{result.latency_ms} ms"})

    if ok_count == len(keys):
        detail = (f"OK — {model}, cả {len(keys)} khoá đều dùng được."
                  if len(keys) > 1 else f"OK — {model}.")
    elif ok_count:
        hong = ", ".join(r["label"] for r in rows if not r["ok"])
        detail = f"{ok_count}/{len(keys)} khoá dùng được. Hỏng: {hong}."
    else:
        detail = f"Không khoá nào dùng được. {rows[0]['detail']}"

    # Còn ít nhất một khoá chạy được thì nhà cung cấp vẫn dùng được. Đánh dấu
    # hỏng cả cụm chỉ vì một khoá lỗi sẽ khiến người vận hành tắt nhầm nó đi.
    return _save_check(config, ok_count > 0, detail, keys=rows)


@api_view(["GET"])
@permission_classes([RequiresAiSettings])
def provider_models(request, provider):
    """Liệt kê model nhà cung cấp đang phục vụ, hợp nhất với danh mục tĩnh.

    Đây là cách lấy mã model của GreenNode sau Workshop #1 thay vì đoán — và là
    tầng giữ cho `/settings` không bao giờ bị khoá vào một danh sách viết tay.
    Lúc viết danh mục tĩnh, hub trả về 7 model mà 2 cái (`qwen3.6-plus`,
    `qwen3.7-plus`) chưa có trong đó. Danh sách tay thiếu ngay từ ngày viết.

    Cái endpoint này KHÔNG cho biết: năng lực. `/models` chỉ trả mã, không nói
    model nào đọc được ảnh hay model nào là embedding. Nên mã dò về mang
    `discovered: true` và UI phải chặn nó ở các tác vụ đòi năng lực đặc biệt,
    cho tới khi có người đo và ghi vào `ai/catalog.py`.
    """
    config = ProviderConfig.objects.filter(provider=provider).first()
    if config is None:
        return Response({"detail": "Chưa có cấu hình."}, status=status.HTTP_404_NOT_FOUND)

    built = _provider_from_config(config)
    if built is None:
        return Response({"detail": "Chưa có khoá API dùng được."},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        discovered = list_models(built)
    except LLMError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    rows = catalog.for_provider(provider,
                                catalog.merge_discovered(provider, discovered))
    return Response({
        "models": [{"id": r.id, "label": r.display, "note": r.note,
                    "capabilities": list(r.capabilities),
                    "discovered": r.discovered} for r in rows],
        # Mã hub trả về mà danh mục tĩnh chưa có — cái đáng để người vận hành
        # nhìn, vì đó là thứ vừa mới xuất hiện.
        "moi": [r.id for r in rows if r.discovered],
    })


@api_view(["GET"])
@permission_classes([RequiresAiSettings])
def usage_summary(request):
    """Thống kê sử dụng theo nhà cung cấp và từng mô hình AI cụ thể."""
    try:
        hours = max(1, min(720, int(request.query_params.get("hours", 24))))
    except (TypeError, ValueError):
        hours = 24
    since = timezone.now() - timedelta(hours=hours)
    calls_qs = LLMCall.objects.filter(created_at__gte=since)
    # Độ trễ và tỷ lệ thành công tách theo TỪNG nhà cung cấp và mô hình.
    model_rows = (calls_qs
                  .values("provider", "model")
                  .annotate(calls=Count("id"),
                            prompt_tokens=Sum("prompt_tokens"),
                            completion_tokens=Sum("completion_tokens"),
                            failed=Count("id", filter=Q(ok=False)),
                            avg_latency_ms=Avg("latency_ms", filter=Q(ok=True)))
                  .order_by("provider", "-calls"))

    models_by_provider = {}
    by_model = []
    for row in model_rows:
        prompt = row["prompt_tokens"] or 0
        completion = row["completion_tokens"] or 0
        calls = row["calls"]
        failed = row["failed"] or 0
        m_item = {
            "provider": row["provider"],
            "model": row["model"] or "(mặc định)",
            "calls": calls,
            "failed": failed,
            "success_rate": round((calls - failed) / calls, 3) if calls else None,
            "avg_latency_ms": (round(row["avg_latency_ms"])
                               if row["avg_latency_ms"] else None),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }
        by_model.append(m_item)
        models_by_provider.setdefault(row["provider"], []).append(m_item)

    rows = (calls_qs
            .values("provider")
            .annotate(calls=Count("id"),
                      prompt_tokens=Sum("prompt_tokens"),
                      completion_tokens=Sum("completion_tokens"),
                      failed=Count("id", filter=Q(ok=False)),
                      avg_latency_ms=Avg("latency_ms", filter=Q(ok=True)))
            .order_by("-calls"))
    per_provider = []
    total_prompt = 0
    total_completion = 0
    for row in rows:
        prompt = row["prompt_tokens"] or 0
        completion = row["completion_tokens"] or 0
        calls = row["calls"]
        failed = row["failed"] or 0
        provider_name = row["provider"]
        total_prompt += prompt
        total_completion += completion
        per_provider.append({
            "provider": provider_name,
            "calls": calls,
            "failed": failed,
            # Tỷ lệ thành công tính trên số lượt của CHÍNH nhà cung cấp đó.
            "success_rate": round((calls - failed) / calls, 3) if calls else None,
            # Chỉ tính độ trễ của lượt THÀNH CÔNG: lượt timeout luôn bằng đúng
            # ngưỡng chờ, gộp vào sẽ làm nhà cung cấp hay hỏng trông như chậm
            # đều đặn thay vì hỏng.
            "avg_latency_ms": (round(row["avg_latency_ms"])
                               if row["avg_latency_ms"] else None),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "models": models_by_provider.get(provider_name, []),
        })

    # Đếm lượt phải chuyển sang nhà cung cấp dự phòng.
    primary = router_module.DEFAULT_ORDER[0]
    fallback_calls = calls_qs.exclude(provider=primary).count()
    total_calls = calls_qs.count()
    successful_latency = list(calls_qs.filter(ok=True)
                              .values_list("latency_ms", flat=True))
    failure_queries = {
        "timeout": (
            Q(error__icontains="timeout") | Q(error__icontains="timed out")
            | Q(error__icontains="quá thời gian")),
        "rate_limit": (
            Q(error__icontains="429") | Q(error__icontains="rate limit")
            | Q(error__icontains="quota")),
        "authentication": (
            Q(error__icontains="401") | Q(error__icontains="403")
            | Q(error__icontains="auth") | Q(error__icontains="api key")),
    }
    remaining_failures = calls_qs.filter(ok=False)
    failure_causes = {}
    for cause, predicate in failure_queries.items():
        failure_causes[cause] = remaining_failures.filter(predicate).count()
        remaining_failures = remaining_failures.exclude(predicate)
    failed_calls = calls_qs.filter(ok=False).count()
    failure_causes["other"] = remaining_failures.count()

    return Response({
        "total_calls": total_calls,
        "failed_calls": failed_calls,
        "success_rate": round((total_calls - failed_calls) / total_calls, 3)
                        if total_calls else None,
        "window_hours": hours,
        "window_started_at": since.isoformat(),
        "p50_latency_ms": _percentile(successful_latency, .50),
        "p95_latency_ms": _percentile(successful_latency, .95),
        "failure_causes": failure_causes,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "primary_provider": primary,
        "fallback_calls": fallback_calls,
        "by_provider": per_provider,
        "by_model": by_model,
        "by_task": _usage_by_task(calls_qs),
    })


def _percentile(values, fraction):
    values = sorted(int(value) for value in values if value is not None)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return round(values[lower] + (values[upper] - values[lower]) * (position - lower))


def _usage_by_task(calls_qs=None):
    """Chi phí và độ trễ tách theo TÁC VỤ — tức theo từng chặng.

    `by_provider`/`by_model` chỉ trả lời "nhà cung cấp nào tốn", không trả lời
    "chặng nào tốn". Mà câu thứ hai mới là câu dẫn tới hành động: biết ③ nuốt
    80% token thì mới biết nên đi tối ưu ③ chứ không phải ⑤.
    `docs/AI_AGENT_ACCEPTANCE_CRITERIA.md` §2.F dòng 2 và §2.J dòng 1 đều hỏi
    đúng câu đó, và ghi dấu hiệu không đạt là *"chỉ có 'trung bình mỗi câu hỏi
    X giây' — không biết chặng nào đáng tối ưu"*.

    Dữ liệu vốn đã có: `LLMCall.task` tồn tại và có index. Chỉ là chưa ai gộp
    theo nó. Kèm nhãn tiếng Việt từ sổ đăng ký để người vận hành không phải
    đoán `talent_answer_judge` là chặng nào.
    """
    calls_qs = calls_qs if calls_qs is not None else LLMCall.objects.all()
    rows = (calls_qs.exclude(task="")
            .values("task")
            .annotate(calls=Count("id"),
                      prompt_tokens=Sum("prompt_tokens"),
                      completion_tokens=Sum("completion_tokens"),
                      failed=Count("id", filter=Q(ok=False)),
                      avg_latency_ms=Avg("latency_ms", filter=Q(ok=True)))
            .order_by("-calls"))
    tong_token = sum((r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)
                     for r in rows) or 1
    ra = []
    for row in rows:
        token = (row["prompt_tokens"] or 0) + (row["completion_tokens"] or 0)
        spec = tasks_registry.TASKS.get(row["task"])
        ra.append({
            "task": row["task"],
            "label": spec.label if spec else row["task"],
            "group": spec.group if spec else "",
            "calls": row["calls"],
            "failed": row["failed"] or 0,
            "tokens": token,
            # Phần trăm token là con số dẫn tới hành động — chặng chiếm phần lớn
            # là chặng đáng đi tối ưu, không phải chặng chạy nhiều lượt nhất.
            "token_share": round(token / tong_token, 4),
            "avg_latency_ms": (round(row["avg_latency_ms"])
                               if row["avg_latency_ms"] else None),
        })
    return ra


def _save_check(config, ok, detail, keys=None):
    config.last_checked_at = timezone.now()
    config.last_check_ok = ok
    config.last_check_detail = str(detail)[:400]
    config.save(update_fields=["last_checked_at", "last_check_ok",
                               "last_check_detail", "updated_at"])
    return Response({"ok": ok, "detail": config.last_check_detail,
                     "keys": keys or []},
                    status=status.HTTP_200_OK if ok else status.HTTP_400_BAD_REQUEST)
