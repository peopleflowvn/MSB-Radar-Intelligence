# -*- coding: utf-8 -*-
"""Sổ đăng ký các "tool" theo Master Plan mục 41 — chỉ là SIÊU DỮ LIỆU.

Đây KHÔNG phải một bảng điều phối để một LLM tự chọn gọi tool nào. Cố ý không
có một `Tool.run(**kwargs)` chung để gọi động — nếu có, bước tiếp theo tự nhiên
sẽ là "đưa registry này cho LLM, để nó quyết định gọi gì" — và đó đúng là ranh
giới dự án này không vượt qua (xem `agents/runtime.py`).

`TOOLS` chỉ trả lời một câu: **tool tên X, theo đúng danh sách Master Plan mục
41, thật ra là hàm nào trong code, và nhãn tiếng Việt của nó là gì.** Dùng để:

  • Domain code (`talent/ai_search.py`, `rb/agent.py`) gọi `label_of("...")` khi
    ghi một `AgentStep`, để nhãn hiện ra thống nhất dù gọi từ đâu.
  • Trang vận hành (Phase 15) liệt kê "hệ thống có những năng lực gì" mà không
    phải đoán từ tên hàm rải rác khắp các app.
  • Tài liệu — `docs/AGENT_RUNTIME.md` sinh bảng này ra, không viết tay hai lần.
"""
from dataclasses import dataclass

DOMAIN_SHARED = "shared"
DOMAIN_TALENT = "talent"
DOMAIN_RB = "rb"
DOMAIN_SOCIAL = "social"


@dataclass(frozen=True)
class Tool:
    name: str
    domain: str
    label: str                 # câu tiếng Việt cho người dùng đọc
    description: str           # câu tiếng Việt, giải thích cho người vận hành
    implemented_by: str        # đường dẫn module.hàm — để tra cứu, không gọi động
    calls_llm: bool = False


_ROWS = [
    # --- Shared tools (mục 41) ---
    Tool("search_person", DOMAIN_SHARED, "Tìm trong kho ứng viên",
        "Truy hồi Person theo bộ lọc có cấu trúc.", "talent.search.search"),
    Tool("resolve_person", DOMAIN_SHARED, "Khớp với người đã có trong kho",
        "Khớp định danh mạnh (email/SĐT) với Person đã có, không tự tạo mới.",
        "people.resolution.find_people"),
    Tool("search_signals", DOMAIN_SHARED, "Tra tín hiệu gần đây",
        "Truy vấn people.Signal theo person/domain.", "people.models.Signal"),
    Tool("get_relationship", DOMAIN_SHARED, "Xem trạng thái quan hệ",
        "Đọc people.Relationship theo nghiệp vụ.", "people.models.Relationship"),
    Tool("get_timeline", DOMAIN_SHARED, "Xem dòng thời gian",
        "Gộp Interaction + Signal theo thời gian cho Person 360.",
        "talent.views.person_detail"),
    Tool("explain_opportunity", DOMAIN_SHARED, "Giải thích vì sao phù hợp",
        "LLM đọc nguyên văn đoạn CV rồi nói vì sao hợp, kèm trích dẫn.",
        "talent.answer.judge.judge", calls_llm=True),
    Tool("recommend_action", DOMAIN_SHARED, "Đề xuất việc nên làm tiếp",
        "Câu hành động cụ thể kèm theo giải thích.",
        "talent.answer.compose.compose", calls_llm=True),

    # --- Talent tools (mục 41) ---
    Tool("parse_hiring_need", DOMAIN_TALENT, "Đọc nhu cầu tuyển dụng",
        "Câu hỏi tự nhiên hoặc JD -> tiêu chí có cấu trúc.",
        "talent.hiring_need.parse", calls_llm=True),
    Tool("match_talent", DOMAIN_TALENT, "Chấm điểm mức phù hợp",
        "Bảy chiều tất định, có trọng số — LLM không tham gia.",
        "talent.scoring.score_person"),
    Tool("find_similar", DOMAIN_TALENT, "Đối chiếu chức danh theo nghề",
        "Độ gần NGHĨA giữa hai chức danh, nhớ lại theo cặp.",
        "talent.semantic.warm", calls_llm=True),
    Tool("create_hunt_request", DOMAIN_TALENT, "Nhờ recruiter săn",
        "HM bàn giao shortlist sang Recruiter.", "hiring.views.request_hunt"),
    Tool("draft_recruiter_message", DOMAIN_TALENT, "Soạn thư tiếp cận",
        "Chỉ dùng dữ kiện đã kiểm chứng; người bấm gửi.",
        "hiring.outreach.draft", calls_llm=True),

    # --- RB tools (mục 41) ---
    Tool("detect_financial_need", DOMAIN_RB, "Nhận diện nhu cầu tài chính",
        "Chấm ý định đa nhãn từ một đoạn văn bản.",
        "social.intent.detect", calls_llm=True),
    Tool("match_product", DOMAIN_RB, "Gợi ý nhóm sản phẩm",
        "Dò từ khoá theo danh mục sản phẩm — không gọi LLM, không bịa sản phẩm.",
        "rb.routing.suggest_products"),
    Tool("prioritize_lead", DOMAIN_RB, "Xếp ưu tiên cơ hội",
        "Xếp theo mức tin cậy; không tạo cơ hội trùng đang mở.",
        "rb.routing.create_opportunities"),
    Tool("draft_sales_response", DOMAIN_RB, "Soạn lời chào theo ngữ cảnh",
        "Chỉ dùng dữ kiện đã kiểm chứng; không hứa lãi suất; người bấm gửi.",
        "rb.outreach.draft", calls_llm=True),
]

TOOLS = {row.name: row for row in _ROWS}


def label_of(tool_name, fallback=""):
    row = TOOLS.get(tool_name)
    return row.label if row else (fallback or tool_name)


def by_domain(domain):
    return [row for row in _ROWS if row.domain in (domain, DOMAIN_SHARED)]
