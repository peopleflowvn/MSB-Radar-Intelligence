# -*- coding: utf-8 -*-
"""Schema cho `AssistantThread.state` — business state đủ để tiếp tục đúng ngữ
cảnh sau reload (Master Plan §10.5.1).

`state` là **dẫn xuất**: khi event log vào chỗ (§15, Giai đoạn 1) nó sẽ được dựng
lại từ log. Module này chỉ chuẩn hoá hình dạng và giữ tương thích với các khoá cũ
(`criteria`, `last_mode`, `turn_count`) để không phải migrate dữ liệu ngay.
"""
from django.utils import timezone

STATE_SCHEMA_VERSION = 2
MAX_CONSTRAINT_PATCHES = 20


def blank_state(surface="talent"):
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "surface": surface,
        # `active_criteria` giữ nguyên tiêu chí `hiring_need`/`prospects` để lượt
        # `deep` tái dùng thay vì hiểu lại. Các bucket must/nice là overlay tuỳ chọn.
        "active_criteria": {},
        "constraint_patches": [],
        "last_result_ref": None,
        "pending_actions": [],
        "pinned_ids": [],
        "updated_at": None,
        # --- khoá cũ, giữ để tương thích ngược một thời gian ---
        "criteria": {},
        "last_mode": "",
        "turn_count": 0,
    }


def normalize(raw, surface="talent"):
    """Đưa `state` bất kỳ về đúng schema hiện tại, không mất dữ liệu cũ."""
    base = blank_state(surface)
    if isinstance(raw, dict):
        for key, value in raw.items():
            base[key] = value
    base["schema_version"] = STATE_SCHEMA_VERSION
    base["surface"] = raw.get("surface", surface) if isinstance(raw, dict) else surface
    # Nâng khoá cũ `criteria` lên `active_criteria` nếu cái mới còn trống.
    if not base.get("active_criteria") and base.get("criteria"):
        base["active_criteria"] = base["criteria"]
    return base


def apply_turn(raw, *, surface="talent", criteria=None, mode="", last_result=None,
               pending_actions=None, pinned_ids=None, constraint_patches=None):
    """Trả về `state` mới sau một lượt. Không mutate `raw`."""
    state = normalize(raw, surface)
    if criteria is not None:
        state["active_criteria"] = criteria
        state["criteria"] = criteria           # song song cho client cũ
    if constraint_patches:
        patches = list(state.get("constraint_patches") or [])
        patches.extend(item for item in constraint_patches if isinstance(item, dict))
        state["constraint_patches"] = patches[-MAX_CONSTRAINT_PATCHES:]
    if mode:
        state["last_mode"] = mode
    if last_result is not None:
        state["last_result_ref"] = last_result
    if pending_actions is not None:
        state["pending_actions"] = list(pending_actions)
    if pinned_ids is not None:
        state["pinned_ids"] = list(pinned_ids)
    state["turn_count"] = int(state.get("turn_count") or 0) + 1
    state["updated_at"] = timezone.now().isoformat()
    return state
