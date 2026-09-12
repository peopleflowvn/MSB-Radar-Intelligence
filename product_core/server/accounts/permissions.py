# -*- coding: utf-8 -*-
"""Permission class theo module cho DRF."""
from rest_framework import permissions

from . import roles


class ModulePermission(permissions.BasePermission):
    """Chặn theo module. Dùng bằng cách đặt thuộc tính `required_module` lên view.

    Viết dạng nhà máy (`for_module`) thay vì đọc thuộc tính của view, vì các
    endpoint ở đây là hàm `@api_view` — chúng không có class để gắn thuộc tính.
    """

    module = None
    message = "Bạn không có quyền vào module này."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if self.module is None:
            return True
        return roles.can_access(user, self.module)


def for_module(module):
    """Tạo permission class cho một module cụ thể."""
    label = roles.MODULE_LABELS.get(module, module)
    return type(
        f"Requires{module.title().replace('_', '')}",
        (ModulePermission,),
        {"module": module,
         "message": f"Vai trò của bạn không được vào {label}."},
    )


RequiresTalent = for_module(roles.MODULE_TALENT)
RequiresRB = for_module(roles.MODULE_RB)
RequiresSocial = for_module(roles.MODULE_SOCIAL)
RequiresEdgeOps = for_module(roles.MODULE_EDGE)
RequiresPeopleIntake = for_module(roles.MODULE_INTAKE)
RequiresAiSettings = for_module(roles.MODULE_AI_SETTINGS)
RequiresReports = for_module(roles.MODULE_REPORTS)
RequiresAdmin = for_module(roles.MODULE_ADMIN)


class RequiresRecruiting(permissions.BasePermission):
    """Nghiệp vụ tuyển dụng chuyên sâu, không mở cho tài khoản RM thuần."""

    message = "Vai trò của bạn không được thay đổi nghiệp vụ tuyển dụng."

    def has_permission(self, request, view):
        allowed = {roles.RECRUITER, roles.MANAGER, roles.ADMIN}
        return bool(roles.roles_of(getattr(request, "user", None)) & allowed)


class RequiresCandidateWork(permissions.BasePermission):
    """Worklist/quan hệ ứng viên dùng chung cho Recruiter và RM."""

    message = "Vai trò của bạn không được xử lý danh sách ứng viên."

    def has_permission(self, request, view):
        allowed = {roles.RECRUITER, roles.RB_SALES, roles.MANAGER, roles.ADMIN}
        return bool(roles.roles_of(getattr(request, "user", None)) & allowed)
