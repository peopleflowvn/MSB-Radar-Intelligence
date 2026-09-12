# -*- coding: utf-8 -*-
"""Ghi nhật ký mọi lượt đọc dữ liệu cá nhân.

**Middleware chứ không phải gọi tay trong từng view.** Gọi tay nghĩa là mỗi
endpoint mới lại có thể quên, và endpoint bị quên chính là endpoint không ai
biết là đang bị dùng. Nhật ký tuân thủ phải là mặc định, không phải tuỳ chọn.

Dùng `process_view` chứ không `__call__`: ở thời điểm đó Django đã phân giải URL
xong nên biết chính xác `person_id`/`document_id` là gì. Đọc từ chuỗi đường dẫn
thô sẽ vỡ ngay khi ai đó đổi định dạng URL.
"""
import logging

from django.utils.deprecation import MiddlewareMixin

from . import roles

log = logging.getLogger(__name__)

# Chỉ ghi nhật ký các đường dẫn thật sự phục vụ dữ liệu cá nhân. Ghi cả
# /health/ hay file tĩnh chỉ làm loãng bảng và khó tìm thứ cần tìm.
#
# Từng chỉ có talent/ và hub/ — audit Phase 15 phát hiện rb/, social/,
# hiring/ đều đọc dữ liệu Person (qua People Core dùng chung) nhưng không hề
# được theo dõi, trong khi docs/ACCESS_CONTROL.md lại khẳng định "mọi lượt
# đọc hồ sơ đều có AccessLog". Thêm ba tiền tố này để lời khẳng định đó đúng
# thật, không chỉ đúng cho riêng Talent Radar.
WATCHED_PREFIXES = (
    "/api/v1/talent/",
    "/api/v1/hub/",
    "/api/v1/rb/",
    "/api/v1/social/",
    "/api/v1/hiring/",
    "/api/v1/intel/",
)

# Tiền tố -> module mặc định khi URL name không có trong ACTION_BY_URL_NAME.
# hiring/ nằm chung MODULE_TALENT (không có module riêng): HM/Recruiter vốn
# đã được cấp quyền theo module Talent, hiring chỉ là một luồng nghiệp vụ bên
# trong đó, không phải một mảng dữ liệu tách biệt.
_MODULE_BY_PREFIX = (
    ("/api/v1/rb/", roles.MODULE_RB),
    ("/api/v1/social/", roles.MODULE_SOCIAL),
    ("/api/v1/hiring/", roles.MODULE_TALENT),
    ("/api/v1/hub/", roles.MODULE_EDGE),
    ("/api/v1/talent/", roles.MODULE_TALENT),
    # People Intelligence: soi fact/provenance của Person — cùng nhóm dữ liệu Talent.
    ("/api/v1/intel/", roles.MODULE_TALENT),
)


def _default_module(path):
    for prefix, module in _MODULE_BY_PREFIX:
        if path.startswith(prefix):
            return module
    return roles.MODULE_TALENT


# Đường dẫn -> (action, module). Khớp theo tên URL để đổi đường dẫn không làm
# hỏng phân loại.
ACTION_BY_URL_NAME = {
    "talent-search": ("search", roles.MODULE_TALENT),
    "talent-search-export": ("export", roles.MODULE_TALENT),
    "talent-person": ("view", roles.MODULE_TALENT),
    "talent-document-download": ("download", roles.MODULE_TALENT),
    # Ba màn hình dưới đây là VẬN HÀNH, không phải Talent: chúng nhìn theo góc
    # hạ tầng (Edge nào, bao nhiêu bản ghi, phân giải tới đâu). Gán nhầm sang
    # Talent sẽ khiến mọi lượt xem của Edge Operator bị đánh cờ liên nghiệp vụ,
    # và cờ đó mất hết ý nghĩa vì lúc nào cũng bật.
    "hub-source-records": ("list", roles.MODULE_EDGE),
    "hub-edges": ("list", roles.MODULE_EDGE),
    "hub-summary": ("list", roles.MODULE_EDGE),
    "rb-opportunities": ("list", roles.MODULE_RB),
    "rb-opportunities-export": ("export", roles.MODULE_RB),
    "rb-opportunity": ("view", roles.MODULE_RB),
    "rb-profile": ("view", roles.MODULE_RB),
    "rb-interests": ("view", roles.MODULE_RB),
    "rb-metrics": ("list", roles.MODULE_RB),
    "social-posts": ("list", roles.MODULE_SOCIAL),
    "social-accounts": ("list", roles.MODULE_SOCIAL),
    "social-communities": ("list", roles.MODULE_SOCIAL),
    "social-actions": ("list", roles.MODULE_SOCIAL),
    "hiring-needs": ("list", roles.MODULE_TALENT),
    "hiring-need": ("view", roles.MODULE_TALENT),
    "hiring-suggestions": ("list", roles.MODULE_TALENT),
    "hiring-metrics": ("list", roles.MODULE_TALENT),
    "hiring-hunts": ("list", roles.MODULE_TALENT),
    "hiring-hunt": ("view", roles.MODULE_TALENT),
}


class AccessLogMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        try:
            self._record(request, view_kwargs)
        except Exception:                      # noqa: BLE001
            # Nhật ký hỏng KHÔNG được chặn người dùng làm việc. Nhưng phải để
            # lại vết trong log hệ thống, vì "không ghi được nhật ký truy cập"
            # tự nó là một sự cố cần biết.
            log.exception("Không ghi được AccessLog")
        return None

    @staticmethod
    def _record(request, view_kwargs):
        path = request.path
        if not path.startswith(WATCHED_PREFIXES):
            return
        if request.method not in ("GET", "HEAD"):
            # Ghi/sửa đã được `Interaction` ghi lại kèm ngữ cảnh nghiệp vụ.
            # AccessLog tồn tại để trả lời "ai đã ĐỌC dữ liệu này".
            return

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return

        from .models import AccessLog

        match = getattr(request, "resolver_match", None)
        url_name = match.url_name if match else ""
        action, module = ACTION_BY_URL_NAME.get(
            url_name, (AccessLog.ACTION_LIST, _default_module(path)))

        person_id = view_kwargs.get("person_id")
        person_name = ""
        object_type, object_id = "", ""

        if "document_id" in view_kwargs:
            object_type, object_id = "document", str(view_kwargs["document_id"])
            person_id = _person_of_document(view_kwargs["document_id"]) or person_id
        elif person_id:
            object_type, object_id = "person", str(person_id)

        if person_id:
            from people.models import Person
            person_name = (Person.objects.filter(pk=person_id)
                           .values_list("display_name", flat=True).first() or "")

        user_roles = sorted(roles.roles_of(user))
        # Tự kiểm quyền ở đây vì process_view chạy TRƯỚC khi permission class
        # của view chạy. Không có cờ này thì lượt bị chặn trông y hệt lượt đọc
        # được dữ liệu.
        allowed = roles.can_access(user, module)
        AccessLog.objects.create(
            user=user,
            user_name=str(user)[:150],
            roles=",".join(user_roles)[:200],
            action=action,
            module=module,
            allowed=allowed,
            person_id=person_id,
            person_name=person_name[:200],
            object_type=object_type,
            object_id=object_id[:64],
            # Bị chặn thì không tính là truy cập liên nghiệp vụ — họ có đọc được
            # gì đâu. Để cờ bật ở đây sẽ làm báo cáo "RB đọc dữ liệu tuyển dụng
            # bao nhiêu lần" đếm cả những lần không đọc được.
            cross_domain=allowed and roles.is_cross_domain(user, module),
            path=path[:300],
            method=request.method,
            ip=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
            extra=_query_snapshot(request),
        )


def _person_of_document(document_id):
    from people.models import Document
    return (Document.objects.filter(pk=document_id)
            .values_list("person_id", flat=True).first())


def _client_ip(request):
    """IP thật của người dùng khi chạy sau Caddy.

    Lấy phần tử ĐẦU của X-Forwarded-For: đó là client gốc; các phần tử sau là
    các proxy trung gian.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return str(request.META.get("REMOTE_ADDR") or "")[:64]


def _query_snapshot(request):
    """Lưu lại điều kiện tìm kiếm.

    "Ai đã tìm gì" quan trọng ngang "ai đã xem hồ sơ nào": một lượt tìm kiếm trả
    về 500 hồ sơ là 500 lần dữ liệu cá nhân được nhìn thấy.
    """
    if not request.GET:
        return {}
    return {key: value[:200] for key, value in request.GET.items()
            if key not in ("limit", "offset")}
