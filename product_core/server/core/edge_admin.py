# -*- coding: utf-8 -*-
"""Tự phục vụ tạo Edge và cấp/thu hồi khoá API — không cần vào Django Admin.

## Vì sao tách khỏi Django Admin thay vì chỉ dùng nó

Django Admin dùng được cho một đội tự vận hành, nhưng nó đòi người thao tác có
tài khoản `is_staff` và quen giao diện quản trị Django — không phải thứ đưa
được cho IT của một doanh nghiệp khác khi triển khai Hub cho họ. Bộ endpoint ở
đây là để **giao diện quản trị nghiệp vụ** (`web/src/`) có một trang "Kết nối
Edge" tự nhiên như mọi trang khác, và để một doanh nghiệp có thể tự cấp/thu hồi
khoá cho các bản cài Edge của họ mà không cần ai đọc mã nguồn hay vào Django
Admin.

## Ranh giới quyền

Tạo Edge và cấp khoá là hành động **sinh ra thông tin xác thực** — một khoá bị
cấp sai tay có thể ghi dữ liệu ứng viên/khách hàng thật vào Hub. Vì vậy các
hành động ghi (`tạo`, `cấp khoá`, `thu hồi`, `bật/tắt`) đòi `RequiresAdmin`,
trong khi xem danh sách chỉ cần `RequiresEdgeOps` — cùng ranh giới với
`views_ui.edge_list` đã có từ trước, không phát minh ranh giới mới.
"""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import RequiresAdmin, RequiresEdgeOps

from .models import Edge, EdgeApiKey


class EdgeApiKeySerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = EdgeApiKey
        # `key_hash` KHÔNG có trong danh sách trường — đây không phải sơ suất,
        # xem docstring `EdgeApiKey.issue()`. Hub không có cách nào trả lại
        # khoá thô sau lần cấp đầu tiên, kể cả cho chính admin.
        fields = ["id", "name", "prefix", "created_at", "last_used_at",
                  "revoked_at", "is_active"]
        read_only_fields = fields


class EdgeSerializer(serializers.ModelSerializer):
    api_keys = EdgeApiKeySerializer(many=True, read_only=True)
    record_count = serializers.IntegerField(source="source_records.count",
                                            read_only=True)

    class Meta:
        model = Edge
        fields = ["id", "label", "edge_id", "hostname", "app_version",
                  "is_active", "registered_at", "last_seen_at", "created_at",
                  "api_keys", "record_count"]
        read_only_fields = ["edge_id", "hostname", "app_version",
                           "registered_at", "last_seen_at", "created_at",
                           "api_keys", "record_count"]


class EdgeCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Edge
        fields = ["label"]

    def validate_label(self, value):
        value = str(value or "").strip()
        if not value:
            raise serializers.ValidationError("Cần đặt tên gọi cho Edge — ví dụ tên máy hoặc đơn vị.")
        return value[:120]


class EdgeUpdateSerializer(serializers.ModelSerializer):
    """Chỉ cho sửa hai trường — mọi trường khác của `Edge` do chính Edge tự báo
    (`hostname`, `app_version`, `edge_id`...) hoặc do Hub tự tính."""

    class Meta:
        model = Edge
        fields = ["label", "is_active"]
        extra_kwargs = {"label": {"required": False}, "is_active": {"required": False}}


class IssueKeySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, allow_blank=True,
                                 help_text="Ghi chú để nhận diện khoá, ví dụ đợt cấp hoặc máy nào dùng.")


@extend_schema(
    methods=["GET"],
    responses=EdgeSerializer(many=True),
    description=(
        "Danh sách Edge và các khoá của chúng — **không bao giờ** kèm khoá "
        "thô, chỉ `prefix` để nhận diện."
    ),
)
@extend_schema(
    methods=["POST"],
    request=EdgeCreateSerializer,
    responses={201: EdgeSerializer},
    examples=[OpenApiExample(
        "Tạo Edge cho một máy mới", value={"label": "Máy phòng Tuyển dụng — tầng 12"})],
    description=(
        "Tạo một bản ghi Edge mới — đại diện **một bản cài đặt** ứng dụng Edge "
        "(thường là một máy/một nhân viên). Chưa cấp khoá; gọi tiếp "
        "`POST /edges/<id>/keys/` để lấy khoá API."
    ),
)
@api_view(["GET", "POST"])
@permission_classes([RequiresEdgeOps])
def edge_collection(request):
    if request.method == "GET":
        edges = Edge.objects.all().prefetch_related("api_keys")
        return Response({"results": EdgeSerializer(edges, many=True).data})

    if not RequiresAdmin().has_permission(request, None):
        return Response({"detail": "Chỉ quản trị viên được tạo Edge mới."},
                        status=status.HTTP_403_FORBIDDEN)

    serializer = EdgeCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    edge = serializer.save()
    return Response(EdgeSerializer(edge).data, status=status.HTTP_201_CREATED)


@extend_schema(
    methods=["PATCH"],
    request=EdgeUpdateSerializer,
    responses={200: EdgeSerializer},
    description=(
        "Đổi tên gọi hoặc bật/tắt một Edge. Tắt (`is_active=false`) **không** "
        "thu hồi khoá hiện có — Edge vẫn xác thực được nhưng nên tự chặn ở "
        "tầng nghiệp vụ nếu cần dừng hẳn. Muốn chặn chắc chắn thì thu hồi khoá "
        "ở `POST /keys/<id>/revoke/`."
    ),
)
@extend_schema(
    methods=["DELETE"],
    request=None,
    responses={200: None, 409: None},
    description=(
        "Xoá hẳn một Edge **chưa từng nạp dữ liệu** (không có bản ghi nguồn). "
        "Edge đã có bản ghi bị từ chối với `409` — dữ liệu thô là bất biến (xem "
        "`SourceRecord`), không được phép xoá kéo theo. Muốn dừng một Edge đang "
        "hoạt động, hãy dùng `PATCH is_active=false` hoặc thu hồi khoá ở "
        "`POST /keys/<id>/revoke/`."
    ),
)
@api_view(["PATCH", "DELETE"])
@permission_classes([RequiresAdmin])
def edge_detail(request, edge_id):
    edge = get_object_or_404(Edge, pk=edge_id)

    if request.method == "DELETE":
        if edge.source_records.exists():
            return Response(
                {"detail": "Không thể xoá Edge đã có dữ liệu nạp — dữ liệu thô là bất biến."
                 " Hãy tắt Edge hoặc thu hồi khoá để dừng thu thập."},
                status=status.HTTP_409_CONFLICT,
            )
        edge.delete()
        return Response({"deleted": True})

    fields = {}
    if "label" in request.data:
        label = str(request.data.get("label") or "").strip()
        if not label:
            return Response({"detail": "Tên gọi không được để trống."}, status=400)
        fields["label"] = label[:120]
    if "is_active" in request.data:
        fields["is_active"] = bool(request.data.get("is_active"))
    if not fields:
        return Response({"detail": "Không có gì để cập nhật."}, status=400)

    for name, value in fields.items():
        setattr(edge, name, value)
    edge.save(update_fields=list(fields) + ["updated_at"])
    return Response(EdgeSerializer(edge).data)


class IssuedKeySerializer(EdgeApiKeySerializer):
    """Chỉ dùng cho phản hồi CẤP khoá — thêm trường `api_key` (khoá thô).

    Tách khỏi `EdgeApiKeySerializer` dùng cho MỌI phản hồi khác, để không ai
    lỡ tay thêm `api_key` vào một chỗ trả về danh sách và làm lộ khoá lần thứ
    hai qua một đường không ai để ý.
    """

    api_key = serializers.CharField(read_only=True)

    class Meta(EdgeApiKeySerializer.Meta):
        fields = EdgeApiKeySerializer.Meta.fields + ["api_key"]
        read_only_fields = fields


@extend_schema(
    request=IssueKeySerializer,
    responses={201: IssuedKeySerializer},
    examples=[OpenApiExample("Cấp khoá", value={"name": "Máy tầng 12 — đợt tháng 9"})],
    description=(
        "Cấp một khoá API mới cho Edge này. **Khoá thô chỉ xuất hiện đúng một "
        "lần trong chính phản hồi này** (`api_key`) — Hub chỉ lưu bản băm "
        "sha256, không có endpoint nào đọc lại khoá thô sau đó, kể cả cho "
        "quản trị viên. Chép ngay và dán vào ô cấu hình của ứng dụng Edge.\n\n"
        "Một Edge có thể có nhiều khoá cùng lúc — đó là cách xoay khoá không "
        "downtime: cấp khoá mới, cập nhật Edge, rồi thu hồi khoá cũ."
    ),
)
@api_view(["POST"])
@permission_classes([RequiresAdmin])
def issue_key(request, edge_id):
    edge = get_object_or_404(Edge, pk=edge_id)
    name = str(request.data.get("name") or "")[:120]
    record, raw_key = EdgeApiKey.issue(edge, name=name)
    payload = IssuedKeySerializer(record).data
    payload["api_key"] = raw_key
    return Response(payload, status=status.HTTP_201_CREATED)


@extend_schema(
    request=None,
    responses={200: EdgeApiKeySerializer},
    description=(
        "Thu hồi một khoá. Có hiệu lực ngay — mọi yêu cầu tiếp theo dùng khoá "
        "này nhận `401`. Không xoá bản ghi, để còn giữ dấu vết ai đã cấp/dùng "
        "khoá nào (cùng nguyên tắc với `ContactUnlockLog`: xoá là mất bằng "
        "chứng, thu hồi vẫn giữ được lịch sử)."
    ),
)
@api_view(["POST"])
@permission_classes([RequiresAdmin])
def revoke_key(request, key_id):
    key = get_object_or_404(EdgeApiKey, pk=key_id)
    key.revoke()
    return Response(EdgeApiKeySerializer(key).data)
