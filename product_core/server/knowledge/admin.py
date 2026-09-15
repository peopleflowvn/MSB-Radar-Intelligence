# -*- coding: utf-8 -*-
"""Nơi thêm tài liệu tri thức nội bộ (quy trình, quyết định, hướng dẫn) cho
Radar học thêm ngoài dữ liệu CV. Chỉ người có module `knowledge` (xem
accounts/roles.py) mới vào được trang quản trị này — Django admin tự áp dụng
`has_module_permission`/`has_view_permission` theo `has_perm`, và
`KnowledgePermissionMixin` bên dưới nối `has_perm` sang `roles.can_access`.
"""
from django import forms
from django.contrib import admin, messages

from accounts import roles

from .models import KnowledgeDocument


class _KnowledgePermissionMixin:
    """Cổng vào bằng roles.MODULE_KNOWLEDGE thay vì permission Django mặc định."""

    def has_module_permission(self, request):
        return roles.can_access(request.user, roles.MODULE_KNOWLEDGE)

    def has_view_permission(self, request, obj=None):
        return roles.can_access(request.user, roles.MODULE_KNOWLEDGE)

    def has_add_permission(self, request):
        return roles.can_access(request.user, roles.MODULE_KNOWLEDGE)

    def has_change_permission(self, request, obj=None):
        return roles.can_access(request.user, roles.MODULE_KNOWLEDGE)

    def has_delete_permission(self, request, obj=None):
        return roles.can_access(request.user, roles.MODULE_KNOWLEDGE)


#: Trần ký tự trích tự động. Tài liệu càng dài càng nhiều chunk, và mỗi chunk
#: là một lượt gọi embedding có nhịp ở worker index — 100k ký tự đã là một cuốn
#: sổ tay dày, dài hơn nữa thì nên tách tài liệu ra.
MAX_EXTRACTED_CHARS = 100_000


class KnowledgeDocumentForm(forms.ModelForm):
    upload = forms.FileField(
        label="Tải file lên (tuỳ chọn)", required=False,
        help_text="PDF, DOCX, XLSX, PPTX, TXT/MD/CSV/JSON hoặc ảnh. Radar tự trích "
                  "nội dung; để trống ô Nội dung nếu muốn dùng bản trích tự động.")

    class Meta:
        model = KnowledgeDocument
        fields = ("title", "category", "parsed_text", "is_active")


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(_KnowledgePermissionMixin, admin.ModelAdmin):
    form = KnowledgeDocumentForm
    list_display = ("title", "category", "is_active", "filename", "uploaded_by", "updated_at")
    list_filter = ("category", "is_active")
    search_fields = ("title", "parsed_text", "filename")
    readonly_fields = ("filename", "mime_type", "file_size", "sha256", "storage_key",
                       "uploaded_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user
        upload = form.cleaned_data.get("upload")
        if upload is not None:
            upload.seek(0)
            obj.store_file(upload.read(), filename=upload.name)
            obj.mime_type = upload.content_type or obj.mime_type
            if not (obj.parsed_text or "").strip():
                self._extract_text(request, obj, upload)
        super().save_model(request, obj, form, change)

    def _extract_text(self, request, obj, upload):
        """Trích nội dung file bằng đúng bộ trích xuất đã dùng cho CV.

        Dùng lại `talent.attachment_text` thay vì thêm một bộ phân tích thứ hai:
        nó đã xử lý PDF/DOCX/XLSX/PPTX/text/ảnh, có chặn zip-bomb và giới hạn
        kích thước. Trích hỏng KHÔNG chặn việc lưu — người dùng vẫn có thể dán
        nội dung vào ô Nội dung.
        """
        from talent.attachment_text import AttachmentError, extract_file

        try:
            upload.seek(0)
            text = (extract_file(upload) or "").strip()
        except AttachmentError as exc:
            obj.parse_status = KnowledgeDocument.PARSE_FAILED
            self.message_user(request, f"Chưa trích được nội dung: {exc}", level=messages.WARNING)
            return
        except Exception:                          # noqa: BLE001
            obj.parse_status = KnowledgeDocument.PARSE_FAILED
            self.message_user(
                request, "Chưa trích được nội dung tệp này. Bạn có thể dán nội dung vào ô Nội dung.",
                level=messages.WARNING)
            return
        if not text:
            obj.parse_status = KnowledgeDocument.PARSE_FAILED
            self.message_user(
                request, "Tệp không có nội dung chữ đọc được.", level=messages.WARNING)
            return
        truncated = len(text) > MAX_EXTRACTED_CHARS
        obj.parsed_text = text[:MAX_EXTRACTED_CHARS]
        obj.parse_status = KnowledgeDocument.PARSE_DONE
        self.message_user(
            request,
            f"Đã trích {len(obj.parsed_text):,} ký tự từ '{upload.name}'."
            + (" Tài liệu bị cắt bớt — nên tách thành nhiều tài liệu nhỏ." if truncated else ""),
            level=messages.WARNING if truncated else messages.SUCCESS)
