# -*- coding: utf-8 -*-
"""Toolset registry — tool do server sở hữu, chọn theo surface + RBAC (Master Plan §23.1.3).

**Không** có tool tự do / do model tạo. Danh sách cố định ở đây; toolset được lọc
theo surface, và theo quyền module của người dùng, **trước khi** model thấy schema.
Tool mới = code review, không phải plugin.

`toolset_for()` trả schema (OpenAI tool format) để đưa vào request. `dispatch()`
thực thi một tool-call: kiểm RBAC lần nữa (không tin model), gọi handler ở
`ai/tool_handlers.py`, trả `ToolResult` JSON-safe cho vòng lặp `ai/agent.py`.
"""
from dataclasses import dataclass, field

from accounts import roles

# name -> định nghĩa. `module` = module RBAC cần có (None = ai đã đăng nhập cũng được).
# `tier`: 0 định tuyến · 1 chỉ-đọc/đề-xuất · 2 kỹ năng ghép chỉ-đọc · 3 hành động ghi.
TOOLS = {
    "search_people": {
        "module": roles.MODULE_TALENT,
        "surfaces": ("talent", "general"),
        "tier": 0,
        "description": "Tìm ứng viên trong Kho con người theo tiêu chí có cấu trúc.",
        "parameters": {
            "type": "object",
            "properties": {
                "criteria": {"type": "object", "description": "title, skills[], location, "
                             "min_years, max_years, company"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["criteria"],
        },
    },
    "search_prospects": {
        "module": roles.MODULE_RB,
        "surfaces": ("prospect", "general"),
        "tier": 0,
        "description": "Tìm khách hàng tiềm năng theo tín hiệu phù hợp.",
        "parameters": {
            "type": "object",
            "properties": {
                "criteria": {"type": "object"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["criteria"],
        },
    },
    "read_allowed_evidence": {
        "module": roles.MODULE_TALENT,
        "surfaces": ("talent", "prospect", "general"),
        "tier": 1,
        "description": "Đọc trích đoạn bằng chứng (fact + evidence) của một Person "
                       "mà tài khoản được phép xem. Dùng khi cần dẫn chứng cụ thể.",
        "parameters": {
            "type": "object",
            "properties": {"person_id": {"type": "integer"},
                           "fields": {"type": "array", "items": {"type": "string"},
                                      "description": "để trống = mọi field hiện hành"}},
            "required": ["person_id"],
        },
    },
    "remember_proposal": {
        "module": None,
        "surfaces": ("talent", "prospect", "general"),
        "tier": 1,
        "description": "Đề xuất một điều Radar nên ghi nhớ về người dùng; luôn ở "
                       "trạng thái chờ người dùng duyệt.",
        "parameters": {
            "type": "object",
            "properties": {"scope": {"type": "string", "enum": ["profile", "operational"]},
                           "value": {"type": "string"}},
            "required": ["value"],
        },
    },
    "feedback": {
        "module": None,
        "surfaces": ("talent", "prospect", "general"),
        "tier": 1,
        "description": "Ghi nhận đánh giá của người dùng về câu trả lời vừa rồi.",
        "parameters": {
            "type": "object",
            "properties": {"rating": {"type": "string", "enum": ["up", "down"]},
                           "reason": {"type": "string"}},
            "required": ["rating"],
        },
    },
    "compare_candidates": {
        "module": roles.MODULE_TALENT,
        "surfaces": ("talent", "general"),
        "tier": 2,
        "description": "Bảng so sánh 2–3 ứng viên theo các chiều (chức danh, công ty, "
                       "số năm, kỹ năng, địa điểm). Chỉ dùng dữ liệu tài khoản được xem.",
        "parameters": {
            "type": "object",
            "properties": {
                "person_ids": {"type": "array", "items": {"type": "integer"},
                               "minItems": 2, "maxItems": 3},
                "dimensions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["person_ids"],
        },
    },
    "canonical_lookup": {
        "module": roles.MODULE_TALENT,
        "surfaces": ("talent", "prospect", "general"),
        "tier": 2,
        "description": "Chuẩn hoá một giá trị (địa điểm / kỹ năng / chức danh / học vấn / "
                       "ngành) về mã canonical của hệ thống.",
        "parameters": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string",
                              "enum": ["location", "skill", "job_title",
                                       "seniority", "education_level", "industry"]},
                "value": {"type": "string"},
            },
            "required": ["namespace", "value"],
        },
    },
    "fact_provenance": {
        "module": roles.MODULE_TALENT,
        "surfaces": ("talent", "general"),
        "tier": 2,
        "description": "Nguồn gốc một trường dữ liệu của Person: giá trị, nguồn (edge/cv/ai), "
                       "bằng chứng, độ tin, thời điểm quan sát, trạng thái duyệt.",
        "parameters": {
            "type": "object",
            "properties": {"person_id": {"type": "integer"},
                           "field": {"type": "string"}},
            "required": ["person_id", "field"],
        },
    },
    # --- Tier 3: sinh nội dung / tra ngoài. Bật riêng bằng ASSISTANT_TOOLS_TIER3.
    #     KHÔNG gửi / đăng gì — chỉ trả bản nháp để người dùng tự dùng.
    "draft_outreach": {
        "module": roles.MODULE_TALENT,
        "surfaces": ("talent", "prospect", "general"),
        "tier": 3,
        "description": "Soạn BẢN NHÁP tin nhắn tiếp cận một Person (không gửi). "
                       "Dựa trên fact tài khoản được xem + bối cảnh vị trí/sản phẩm.",
        "parameters": {
            "type": "object",
            "properties": {
                "person_id": {"type": "integer"},
                "channel": {"type": "string", "enum": ["email", "linkedin", "call_note", "sms"]},
                "context": {"type": "string", "description": "vị trí đang tuyển / sản phẩm / lý do tiếp cận"},
            },
            "required": ["person_id", "context"],
        },
    },
    "enrich_company_from_web": {
        "module": roles.MODULE_TALENT,
        "surfaces": ("talent", "prospect", "general"),
        "tier": 3,
        "description": "Tra web tóm tắt thông tin công khai về một công ty (quy mô, "
                       "ngành, tin gần đây) kèm nguồn. Cần ASSISTANT_WEB_SEARCH.",
        "parameters": {
            "type": "object",
            "properties": {"company": {"type": "string"},
                           "focus": {"type": "string", "description": "khía cạnh quan tâm"}},
            "required": ["company"],
        },
    },
}


@dataclass
class ToolResult:
    ok: bool = False
    result: dict = field(default_factory=dict)
    error: str = ""

    def payload(self):
        return self.result if self.ok else {"error": self.error or "tool failed"}


def _allowed(user, module):
    if module is None:
        return getattr(user, "is_authenticated", False)
    try:
        return roles.can_access(user, module)
    except Exception:                          # noqa: BLE001
        return False


def toolset_for(surface, user, *, names=None):
    """Schema các tool model được phép thấy cho (surface, user). OpenAI tool format."""
    out = []
    for name, spec in TOOLS.items():
        if names is not None and name not in names:
            continue
        if surface not in spec["surfaces"]:
            continue
        if not _allowed(user, spec["module"]):
            continue
        out.append({"type": "function", "function": {
            "name": name, "description": spec["description"],
            "parameters": spec["parameters"]}})
    return out


def tool_names_for(surface, user):
    return [t["function"]["name"] for t in toolset_for(surface, user)]


#: Nhãn tiếng Việt cho người dùng đọc khi Radar đang chạy một tool.
#:
#: Đặt ở ĐÂY chứ không ở `agents/tools.py`: đó là một sổ đăng ký khác, cho các
#: năng lực theo Master Plan §41, và tên tool trong hai sổ không trùng nhau
#: (`label_of("compare_candidates")` bên đó trả về chính chuỗi id). Cũng không
#: để ở giao diện: hai bề mặt cùng cần, và nhãn lệch nhau thì người dùng thấy
#: hai tên cho cùng một việc.
LABELS = {
    "search_people": "Tìm trong kho ứng viên",
    "search_prospects": "Tìm khách hàng tiềm năng",
    "read_allowed_evidence": "Đọc bằng chứng hồ sơ",
    "remember_proposal": "Đề xuất ghi nhớ",
    "feedback": "Ghi nhận đánh giá",
    "compare_candidates": "So sánh ứng viên",
    "canonical_lookup": "Chuẩn hoá giá trị",
    "fact_provenance": "Truy nguồn gốc dữ liệu",
    "draft_outreach": "Soạn nháp tiếp cận",
    "enrich_company_from_web": "Tra thông tin công ty (web)",
}


def label_of(name, fallback=""):
    return LABELS.get(name) or fallback or name


#: Các tool được vòng lặp agent thực thi. `search_people` / `search_prospects`
#: (tier 0) KHÔNG nằm ở đây — chúng là nhánh định tuyến, không phải tool trong lượt.
_AGENT_TOOLS = {"read_allowed_evidence", "remember_proposal", "feedback",
                "compare_candidates", "canonical_lookup", "fact_provenance",
                "draft_outreach", "enrich_company_from_web"}
_TIER3_TOOLS = {"draft_outreach", "enrich_company_from_web"}


def _tier3_enabled():
    from django.conf import settings
    return bool(getattr(settings, "ASSISTANT_TOOLS_TIER3", False))


def _agent_tool_names():
    if _tier3_enabled():
        return _AGENT_TOOLS
    return _AGENT_TOOLS - _TIER3_TOOLS


def agent_toolset_for(surface, user):
    return toolset_for(surface, user, names=_agent_tool_names())


def dispatch(name, arguments, *, user, surface, context=None):
    """Thực thi một tool-call. Trả `ToolResult` (JSON-safe)."""
    from . import tool_handlers

    spec = TOOLS.get(name)
    if spec is None or name not in _agent_tool_names():
        return ToolResult(error=f"tool không khả dụng: {name}")
    if surface not in spec["surfaces"]:
        return ToolResult(error="tool không khả dụng trên bề mặt này")
    if not _allowed(user, spec["module"]):
        return ToolResult(error="tài khoản không có quyền dùng tool này")
    selected = (context or {}).get("selected_person_ids")
    if selected is not None and name in {
            "draft_outreach", "read_allowed_evidence", "fact_provenance", "compare_candidates"}:
        args = arguments if isinstance(arguments, dict) else {}
        targets = args.get("person_ids") if name == "compare_candidates" else [args.get("person_id")]
        if (not isinstance(targets, list) or not targets
                or any(type(pid) is not int or pid not in selected for pid in targets)):
            return ToolResult(error="tool phải dùng đúng hồ sơ người dùng vừa chọn")
    handler = tool_handlers.HANDLERS.get(name)
    if handler is None:
        return ToolResult(error=f"tool chưa có handler: {name}")
    try:
        data = handler(dict(arguments or {}), user=user, surface=surface,
                       context=dict(context or {}))
    except tool_handlers.ToolError as exc:
        return ToolResult(error=str(exc))
    except Exception:                          # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("tool %s lỗi", name)
        return ToolResult(error="tool gặp lỗi nội bộ")
    return ToolResult(ok=True, result=data if isinstance(data, dict) else {"value": data})
