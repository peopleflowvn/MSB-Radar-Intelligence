# -*- coding: utf-8 -*-
from rest_framework import permissions

from .auth import EdgeAuth


class IsAuthenticatedEdge(permissions.BasePermission):
    """Chỉ cho Edge đã xác thực bằng khoá API đi qua.

    Cần lớp riêng vì IsAuthenticated mặc định của DRF xét request.user, mà Edge
    cố ý không có user — nó là máy, không phải người.
    """

    message = "Cần xác thực bằng khoá API của Edge."

    def has_permission(self, request, view):
        return isinstance(getattr(request, "auth", None), EdgeAuth)
