# -*- coding: utf-8 -*-
"""API tự phục vụ cho trang "Tri thức nội bộ" (web/src/Knowledge.tsx).

Cùng ranh giới với `core/edge_admin.py`: Django Admin (`knowledge/admin.py`)
vẫn còn cho thao tác nhanh bằng tay, nhưng bộ endpoint ở đây là con đường
chính thức cho giao diện nghiệp vụ — không đòi `is_staff`, chỉ đòi module
`knowledge` (accounts/permissions.py::RequiresKnowledge).
"""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from accounts.permissions import RequiresKnowledge
from talent.attachment_text import AttachmentError, extract_file

from .models import KnowledgeDocument

MAX_EXTRACTED_CHARS = 100_000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    parse_status_label = serializers.CharField(source="get_parse_status_display", read_only=True)
    uploaded_by_name = serializers.CharField(
        source="uploaded_by.get_full_name", read_only=True, default="")
    text_length = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeDocument
        fields = ["id", "title", "category", "category_label", "filename", "mime_type",
                  "file_size", "parse_status", "parse_status_label", "is_active",
                  "uploaded_by_name", "text_length", "created_at", "updated_at"]
        read_only_fields = ["filename", "mime_type", "file_size", "parse_status",
                           "uploaded_by_name", "text_length", "created_at", "updated_at"]

    def get_text_length(self, obj):
        return len(obj.parsed_text or "")


class KnowledgeDocumentDetailSerializer(KnowledgeDocumentSerializer):
    class Meta(KnowledgeDocumentSerializer.Meta):
        fields = KnowledgeDocumentSerializer.Meta.fields + ["parsed_text"]


class KnowledgeDocumentWriteSerializer(serializers.ModelSerializer):
    # DRF's auto-generated BooleanField does not carry the model's
    # `default=True` into a create() call the way a CharField's `default`
    # does — an omitted field on POST silently became `False` without this.
    is_active = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = KnowledgeDocument
        fields = ["title", "category", "parsed_text", "is_active"]

    def validate_title(self, value):
        value = str(value or "").strip()
        if not value:
            raise serializers.ValidationError("Cần đặt tiêu đề cho tài liệu.")
        return value[:300]


@extend_schema(
    methods=["GET"],
    responses=KnowledgeDocumentSerializer(many=True),
    description="Danh sách tài liệu tri thức nội bộ, mới cập nhật trước.",
)
@extend_schema(
    methods=["POST"],
    request=KnowledgeDocumentWriteSerializer,
    responses={201: KnowledgeDocumentDetailSerializer},
    description=(
        "Tạo tài liệu tri thức nội bộ mới bằng văn bản nhập tay. Muốn tải file "
        "lên (PDF/DOCX/XLSX/PPTX/ảnh...), gọi `POST /upload/` thay vào đây."
    ),
)
@api_view(["GET", "POST"])
@permission_classes([RequiresKnowledge])
def document_collection(request):
    if request.method == "GET":
        documents = KnowledgeDocument.objects.all().select_related("uploaded_by")
        category = request.GET.get("category")
        if category:
            documents = documents.filter(category=category)
        return Response({
            "results": KnowledgeDocumentSerializer(documents, many=True).data,
            "categories": [{"value": value, "label": label}
                           for value, label in KnowledgeDocument.CATEGORY_CHOICES],
        })

    serializer = KnowledgeDocumentWriteSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    if not str(serializer.validated_data.get("parsed_text") or "").strip():
        return Response(
            {"detail": "Cần nhập nội dung, hoặc dùng /upload/ để tải file lên."},
            status=status.HTTP_400_BAD_REQUEST)
    document = serializer.save(uploaded_by=request.user)
    return Response(
        KnowledgeDocumentDetailSerializer(document).data, status=status.HTTP_201_CREATED)


@extend_schema(
    methods=["PATCH"],
    request=KnowledgeDocumentWriteSerializer,
    responses={200: KnowledgeDocumentDetailSerializer},
    description="Sửa tiêu đề/danh mục/nội dung, hoặc tắt (`is_active=false`) để rút khỏi Radar.",
)
@extend_schema(
    methods=["DELETE"], request=None, responses={200: None},
    description="Xoá hẳn tài liệu. Radar vẫn nhận được sự kiện xoá (outbox độc lập với hàng đã mất).",
)
@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([RequiresKnowledge])
def document_detail(request, document_id):
    document = get_object_or_404(KnowledgeDocument, pk=document_id)

    if request.method == "GET":
        return Response(KnowledgeDocumentDetailSerializer(document).data)

    if request.method == "DELETE":
        document.delete()
        return Response({"deleted": True})

    serializer = KnowledgeDocumentWriteSerializer(document, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    serializer.save()
    return Response(KnowledgeDocumentDetailSerializer(document).data)


@extend_schema(
    request={"multipart/form-data": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "category": {"type": "string"},
            "file": {"type": "string", "format": "binary"},
        },
        "required": ["title", "file"],
    }},
    responses={201: KnowledgeDocumentDetailSerializer},
    description=(
        "Tải file lên (PDF, DOCX, XLSX, PPTX, TXT/MD/CSV/JSON, hoặc ảnh) — Radar "
        "tự trích nội dung bằng đúng bộ trích xuất dùng cho CV "
        "(`talent/attachment_text.py`). Trích hỏng vẫn lưu tài liệu với "
        "`parse_status=failed`; sửa lại nội dung thủ công qua `PATCH` sau."
    ),
)
@api_view(["POST"])
@permission_classes([RequiresKnowledge])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def document_upload(request):
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "Thiếu file để tải lên."}, status=status.HTTP_400_BAD_REQUEST)
    if upload.size > MAX_UPLOAD_BYTES:
        return Response(
            {"detail": f"Tệp vượt quá giới hạn {MAX_UPLOAD_BYTES // 1024 // 1024} MB."},
            status=status.HTTP_400_BAD_REQUEST)

    title = str(request.data.get("title") or "").strip()[:300] or upload.name
    category = str(request.data.get("category") or KnowledgeDocument.CATEGORY_OTHER)
    if category not in dict(KnowledgeDocument.CATEGORY_CHOICES):
        category = KnowledgeDocument.CATEGORY_OTHER

    document = KnowledgeDocument(title=title, category=category, uploaded_by=request.user)
    data = upload.read()
    document.store_file(data, filename=upload.name)
    document.mime_type = upload.content_type or document.mime_type

    warning = ""
    try:
        upload.seek(0)
        text = (extract_file(upload) or "").strip()
    except AttachmentError as exc:
        document.parse_status = KnowledgeDocument.PARSE_FAILED
        warning = str(exc)
        text = ""
    except Exception:                          # noqa: BLE001
        document.parse_status = KnowledgeDocument.PARSE_FAILED
        warning = "Chưa trích được nội dung tệp này. Bạn có thể sửa nội dung sau."
        text = ""
    if text:
        truncated = len(text) > MAX_EXTRACTED_CHARS
        document.parsed_text = text[:MAX_EXTRACTED_CHARS]
        document.parse_status = KnowledgeDocument.PARSE_DONE
        if truncated:
            warning = "Tài liệu dài hơn giới hạn trích tự động — nội dung đã bị cắt bớt."
    elif not warning:
        document.parse_status = KnowledgeDocument.PARSE_FAILED
        warning = "Tệp không có nội dung chữ đọc được."

    document.save()
    payload = KnowledgeDocumentDetailSerializer(document).data
    if warning:
        payload["warning"] = warning
    return Response(payload, status=status.HTTP_201_CREATED)
