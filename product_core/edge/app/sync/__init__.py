# -*- coding: utf-8 -*-
"""Đồng bộ Edge -> Hub.

Ranh giới cố ý rõ ràng (Nguyên tắc 3: Edge lo trình duyệt, Hub lo trí tuệ):

    app/db.py          giữ hàng đợi outbox — trạng thái bền vững
    app/sync/identity  danh tính của bản cài Edge này
    app/sync/client    gọi HTTP tới Hub, retry, phân loại lỗi
    app/sync/payload   chuyển bản ghi Edge thành payload gửi đi + hash nội dung

Ở Phase 2 chưa có nghiệp vụ Hub nào tại đây: Edge chỉ biết xếp hàng, gửi đi và
ghi nhận kết quả. Việc gộp Person, phân giải định danh đều thuộc về Hub.
"""
from .identity import edge_id, edge_identity
from .client import HubClient, HubError, HubAuthError, HubUnavailable
from .payload import candidate_payload, payload_hash
from .service import SyncService

__all__ = ["edge_id", "edge_identity", "HubClient", "HubError", "HubAuthError",
           "HubUnavailable", "candidate_payload", "payload_hash", "SyncService"]
