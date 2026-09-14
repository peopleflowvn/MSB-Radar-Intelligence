# -*- coding: utf-8 -*-
"""Danh mục model theo nhà cung cấp — để `/settings` gợi ý thay vì bắt gõ mò.

Ô model trước đây là ô chữ trống. Gõ sai một ký tự thì không có gì báo: router
cứ gửi đi, nhà cung cấp trả 404, và tác vụ đó im lặng rơi sang provider sau.

Danh mục này có ba tầng, cố ý:

1. **`STATIC`** — model đã biết, kèm cờ năng lực và một câu nói nó hợp việc gì.
   Tầng này là thứ duy nhất biết model nào đọc được ảnh, model nào là embedding.
2. **Làm mới từ nhà cung cấp** (`merge_discovered`) — gọi `GET {base_url}/models`
   rồi nhập thêm mã model mới. Tầng này cần thiết chứ không phải cho vui: lúc
   viết file này hub GreenNode trả về 7 model, trong đó `qwen3.6-plus` và
   `qwen3.7-plus` chưa từng có trong `STATIC`. Danh sách tay thiếu ngay từ ngày
   viết ra.
3. **Gõ tay** — luôn được. Danh mục là gợi ý, không phải hàng rào.

Điều tầng 2 KHÔNG cho: năng lực. `/models` chỉ trả mã, không nói model nào có
thị giác. Nên model tự dò về mang `capabilities=()` — "chưa rõ" — và
`usable_for()` sẽ không cho nó nhận `cv_ocr`/`talent_embedding` cho tới khi có
người xác nhận. Thà chặn còn hơn để một lô CV scan vào kho thành rỗng.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import tasks as tasks_registry

CAP_CHAT = "chat"
CAP_VISION = "vision"
CAP_EMBEDDING = "embedding"

#: `kind` của tác vụ → năng lực model bắt buộc phải có. Các `kind` không nằm ở
#: đây (json/viet/doc) chỉ cần model sinh văn bản bình thường.
KIND_CAN_NANG_LUC = {
    tasks_registry.KIND_EMBEDDING: CAP_EMBEDDING,
    tasks_registry.KIND_VISION: CAP_VISION,
}


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str = ""
    note: str = ""
    capabilities: tuple = field(default_factory=tuple)
    #: True khi mã này do dò từ nhà cung cấp, chưa ai xác nhận năng lực.
    discovered: bool = False

    @property
    def display(self):
        return self.label or self.id


def _m(mid, label, note, caps=(CAP_CHAT,)):
    return ModelInfo(id=mid, label=label, note=note, capabilities=tuple(caps))


#: Model đã biết, theo nhà cung cấp. Cố ý ngắn — tầng 2 lo phần đuôi.
STATIC = {
    "greennode": [
        _m("qwen/qwen3.6-flash", "Qwen3.6 Flash",
           "Nhanh và rẻ, lại đọc được ảnh. Đo được: nhanh hơn glm-5.2 khoảng "
           "36% ở việc chấm chức danh với chất lượng bằng hoặc hơn, và đọc "
           "đúng chữ trong ảnh JPEG. Mặc định cho hầu hết tác vụ.",
           caps=(CAP_CHAT, CAP_VISION)),
        _m("qwen/qwen3.6-plus", "Qwen3.6 Plus",
           "Bản mạnh hơn Flash, chậm hơn. Cũng đọc được ảnh. Dùng khi Flash "
           "bóc sai.", caps=(CAP_CHAT, CAP_VISION)),
        _m("qwen/qwen3.7-plus", "Qwen3.7 Plus",
           "Đời mới nhất họ Qwen trên hub, đọc được ảnh. Chưa đo tốc độ trong "
           "hệ này.", caps=(CAP_CHAT, CAP_VISION)),
        _m("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro",
           "Hành văn và suy luận tốt nhất trong hub. Dành cho chặng người dùng "
           "đọc thấy. KHÔNG đọc được ảnh (tự nói là không xem được). LƯU Ý: "
           "provider cắt bỏ `reasoning_effort` cho mọi model deepseek/* vì "
           "chúng trả HTTP 400 — nên không tắt được phần nghĩ."),
        _m("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash",
           "Viết khá mà nhanh hơn Pro. Hợp tổng hợp kết quả web, hội thoại."),
        _m("z-ai/glm-5.2-hackathon", "GLM 5.2 (hackathon)",
           "Model rơi-xuống cũ của hub, và ba lần đo đều kém: timeout khi "
           "chuẩn hoá một CV 3KB; chậm hơn Qwen3.6 Flash ~36% khi chấm chức "
           "danh; TRẢ HTTP 400 KHI GỬI ẢNH — không có thị giác. Đừng đặt lại "
           "làm mặc định."),
        _m("google/gemma-4-31b-it", "Gemma 4 31B IT",
           "Model mở, cỡ trung, đọc được ảnh. Dự phòng khi các model trên nghẽn.",
           caps=(CAP_CHAT, CAP_VISION)),
    ],
    "gemini": [
        _m("gemini-3.5-flash", "Gemini 3.5 Flash",
           "Model chat độ trễ thấp. Benchmark ngay trên pipeline Radar cho thấy "
           "phù hợp với lập kế hoạch và chấm hồ sơ có cấu trúc."),
        _m("models/gemini-embedding-2", "Gemini Embedding 2",
           "Sinh vector cho hồ sơ và đoạn CV. Đang dùng cho cả kho.",
           caps=(CAP_EMBEDDING,)),
    ],
}


def for_provider(provider, extra=()):
    """Model của một nhà cung cấp: tầng tĩnh trước, tầng dò về sau."""
    rows = list(STATIC.get(provider, []))
    biet = {row.id for row in rows}
    rows.extend(row for row in extra if row.id not in biet)
    return rows


def merge_discovered(provider, model_ids):
    """Mã model dò từ `/models` mà `STATIC` chưa có → ModelInfo 'chưa rõ'."""
    biet = {row.id for row in STATIC.get(provider, [])}
    return [ModelInfo(id=mid, note="Dò được từ nhà cung cấp, chưa xác nhận "
                                   "năng lực.", discovered=True)
            for mid in sorted(set(model_ids) - biet) if mid]


def usable_for(model_info, task_name):
    """(dùng được?, lý do). Chỉ chặn khi tác vụ đòi năng lực đặc biệt."""
    task = tasks_registry.TASKS.get(task_name)
    if task is None:
        return True, ""
    can = KIND_CAN_NANG_LUC.get(task.kind)
    if can is None:
        return True, ""
    if can in model_info.capabilities:
        return True, ""
    if model_info.discovered:
        return False, (f"Chưa biết model này có {can} hay không. Tác vụ "
                       f"“{task.label}” chọn sai sẽ không báo lỗi, chỉ trả rác.")
    return False, (f"Model này không có năng lực {can}, mà “{task.label}” bắt "
                   f"buộc phải có.")


def payload(discovered=None):
    """Cho `/settings`: danh mục + bảng năng lực để UI tự chặn được.

    `discovered` là {provider: [model_id]} lấy từ CSDL (kết quả lần làm mới
    gần nhất), để UI không phải gọi nhà cung cấp mỗi lần mở trang.
    """
    discovered = discovered or {}
    out = {}
    for provider in sorted(set(STATIC) | set(discovered)):
        rows = for_provider(provider,
                            merge_discovered(provider, discovered.get(provider, [])))
        out[provider] = [{"id": r.id, "label": r.display, "note": r.note,
                          "capabilities": list(r.capabilities),
                          "discovered": r.discovered} for r in rows]
    return {"models": out,
            "kind_requires": dict(KIND_CAN_NANG_LUC)}
