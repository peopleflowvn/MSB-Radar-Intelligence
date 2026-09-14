# -*- coding: utf-8 -*-
"""Sổ đăng ký MỌI tác vụ dùng tới não AI — nguồn sự thật cho `/settings`.

Trước đây danh sách này là một mảng chuỗi viết tay trong `ai/views.py`, và nó đã
lệch đúng như mọi danh sách viết tay đều lệch:

* **8 tác vụ không hiện ra** nên người vận hành không đổi model được — trong đó
  có `cv_parsing` (bóc tách CV, chạy cho mọi hồ sơ nhập vào) và
  `candidate_intake_extraction`. Chúng âm thầm dùng model mặc định của nhà cung
  cấp, thường là model hội thoại — đắt và chậm cho việc bóc JSON.
* **`talent_explain` vẫn còn trong danh sách** dù `talent/ai_search.py` đã bị gỡ.
  Một ô cấu hình không nối vào đâu cả.

Nay mỗi tác vụ khai ở ĐÂY, kèm nhãn tiếng Việt và một câu nói rõ nó làm gì —
người vận hành không phải đoán `rb_prospect_search` nghĩa là gì rồi gõ tay đúng
từng ký tự.

`kind` vừa gợi ý vừa RÀNG BUỘC. Hai giá trị đầu chỉ là gợi ý — chọn khác thì
chậm hoặc tốn, chứ vẫn chạy:

* `json` cần nhanh và ra JSON chuẩn;
* `viet` cần hành văn tốt; `doc` cần đọc dài mà rẻ.

Hai giá trị sau là **yêu cầu năng lực**, chọn sai thì hỏng lặng — model vẫn trả
lời, chỉ là trả lời rác, và log chỉ nói "không đủ dữ liệu":

* `embedding` phải là model embedding. Đặt model chat vào đây là chết vector hoá.
* `vision` phải là model đọc được ảnh. Đặt model chỉ-đọc-chữ vào đây thì CV
  scan/ảnh không vào được kho.

`/settings` phải chặn hai loại này kèm lý do, đừng để người vận hành phát hiện
ra bằng cách mất một lô hồ sơ.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Nhóm hiển thị trong `/settings`, theo bề mặt nghiệp vụ.
GROUP_ANSWER = "Trả lời câu hỏi (Talent)"
GROUP_ASSISTANT = "Trợ lý chung"
GROUP_INTAKE = "Nhập liệu & bóc tách"
GROUP_HIRING = "Tuyển dụng"
GROUP_RB = "Khách hàng (RB)"
GROUP_OTHER = "Khác"


#: Loại model hợp với tác vụ. `KINDS_BAT_BUOC` là các loại mà chọn sai không
#: báo lỗi — chỉ trả rác — nên `/settings` phải chặn thay vì cảnh báo suông.
KIND_JSON = "json"
KIND_VIET = "viet"
KIND_DOC = "doc"
KIND_EMBEDDING = "embedding"
KIND_VISION = "vision"
KINDS = (KIND_JSON, KIND_VIET, KIND_DOC, KIND_EMBEDDING, KIND_VISION)
KINDS_BAT_BUOC = (KIND_EMBEDDING, KIND_VISION)


@dataclass(frozen=True)
class AiTask:
    name: str
    label: str
    description: str
    group: str
    kind: str = "json"

    @property
    def capability(self):
        if self.kind == KIND_VISION:
            return "VISION"
        if self.kind == KIND_EMBEDDING:
            return "EMBEDDING"
        if self.name in {"talent_answer_compose", "person_qa", "talent_corpus_qa",
                         "assistant_agent", "assistant_web"}:
            return "DEEP"
        return "FAST"


_ROWS = [
    # --- Answer Engine: ba chặng, ba đòi hỏi khác nhau ------------------------
    AiTask("talent_answer_plan", "① Hiểu câu hỏi",
           "Đọc câu hỏi rồi lập kế hoạch tìm kiếm. Gọi mỗi lượt, chỉ trả JSON "
           "ngắn — cần NHANH hơn là giỏi.", GROUP_ANSWER, "json"),
    AiTask("talent_answer_judge", "③ Đọc CV & phán đoán",
           "Đọc nguyên văn đoạn CV, quyết định ai thoả và bóc thuộc tính. Nuốt "
           "nhiều chữ nhất trong cả luồng — cần RẺ mà đọc dài.", GROUP_ANSWER, "doc"),
    AiTask("talent_answer_compose", "⑤ Viết câu trả lời",
           "Chặng duy nhất người dùng ĐỌC THẤY. Cần hành văn và suy luận tốt "
           "nhất; đây là chỗ đáng trả tiền.", GROUP_ANSWER, "viet"),
    AiTask("talent_corpus_qa", "Hỏi đáp có dẫn chứng (bản cũ)",
           "Đường hỏi đáp CV cũ, còn dùng ở bề mặt trợ lý chat.", GROUP_ANSWER, "viet"),
    AiTask("talent_search", "Bóc tiêu chí tuyển dụng",
           "Câu hỏi tự nhiên hoặc JD → tiêu chí có cấu trúc.", GROUP_ANSWER, "json"),
    AiTask("talent_embedding", "Vector hoá kho CV",
           "Sinh vector cho hồ sơ và đoạn CV để tìm theo ngữ nghĩa. KHÔNG sinh "
           "văn — phải là model embedding.", GROUP_ANSWER, "embedding"),
    AiTask("person_qa", "Hỏi đáp một hồ sơ",
           "Trả lời câu hỏi neo vào MỘT người đã biết.", GROUP_ANSWER, "viet"),

    # --- Trợ lý chung --------------------------------------------------------
    AiTask("assistant_conversation", "Hội thoại thường",
           "Câu hỏi không về kho người. Cần giọng văn tự nhiên.",
           GROUP_ASSISTANT, "viet"),
    AiTask("assistant_intent", "Phân loại ý định",
           "Quyết định câu hỏi nên đi nhánh nào. Rất ngắn, cần nhanh.",
           GROUP_ASSISTANT, "json"),
    AiTask("assistant_web", "Tổng hợp kết quả tra web",
           "Đọc kết quả tìm kiếm internet rồi viết câu trả lời có dẫn nguồn.",
           GROUP_ASSISTANT, "viet"),
    AiTask("assistant_agent", "Vòng gọi tool",
           "Chọn và gọi tool trong một lượt. Cần theo đúng khuôn tool-call.",
           GROUP_ASSISTANT, "json"),
    AiTask("assistant_outreach", "Soạn nháp tiếp cận (tool)",
           "Tool `draft_outreach` soạn bản nháp tin nhắn.", GROUP_ASSISTANT, "viet"),

    # --- Nhập liệu & bóc tách ------------------------------------------------
    AiTask("cv_parsing", "Chuẩn hoá văn bản CV",
           "Nhận text CV mà bộ trích cục bộ đã lấy được, viết lại cho sạch. "
           "KHÔNG trả JSON — trả lại nguyên văn CV. Chạy cho mọi hồ sơ chưa có "
           "text nên là tác vụ tốn nhiều lượt gọi nhất.", GROUP_INTAKE, "doc"),
    AiTask("cv_ocr", "OCR CV scan/ảnh",
           "Khi file CV không trích được chữ (bản scan, ảnh chụp), đọc chữ "
           "thẳng từ ảnh. BẮT BUỘC model có thị giác.", GROUP_INTAKE, "vision"),
    AiTask("candidate_extraction", "Bóc field từ text CV",
           "Đọc text CV rồi điền các field còn thiếu — thành phố, chức danh, "
           "kỹ năng, ngành, học vấn — kèm dẫn chứng và độ tin.",
           GROUP_INTAKE, "json"),
    AiTask("candidate_intake_extraction", "Bóc thông tin lô nhập",
           "Rút thông tin ứng viên từ tệp nhập hàng loạt.", GROUP_INTAKE, "json"),
    AiTask("cv_reference_extraction", "Tách liên hệ ứng viên khỏi người tham chiếu",
           "CV thường kèm họ tên/chức danh/công ty/email/SĐT của NGƯỜI THAM "
           "CHIẾU. Đọc text CV có ngữ cảnh để nói rõ liên hệ nào của chính ứng "
           "viên, liên hệ nào của người khác — chỉ chạy khi CV có dấu hiệu mục "
           "tham chiếu, không gọi cho mọi hồ sơ.", GROUP_INTAKE, "json"),

    # --- Tuyển dụng ----------------------------------------------------------
    AiTask("jd_parse", "Bóc tách JD",
           "Đọc mô tả công việc thành tiêu chí tuyển dụng.", GROUP_HIRING, "json"),
    AiTask("outreach_draft", "Soạn thư tiếp cận (Hiring)",
           "Soạn nháp thư mời ứng viên từ shortlist.", GROUP_HIRING, "viet"),

    # --- Khách hàng (RB) -----------------------------------------------------
    AiTask("rb_prospect_search", "Bóc tiêu chí tìm khách",
           "Câu hỏi tự nhiên → bộ lọc khách hàng tiềm năng.", GROUP_RB, "json"),
    AiTask("rb_outreach_draft", "Soạn thư tiếp cận (RB)",
           "Soạn nháp tin nhắn cho khách hàng tiềm năng.", GROUP_RB, "viet"),

    # --- Khác ----------------------------------------------------------------
    AiTask("social_intent", "Phân loại bài đăng mạng xã hội",
           "Đọc bài đăng, đoán nhu cầu tài chính.", GROUP_OTHER, "json"),
    AiTask("title_similarity", "So độ gần chức danh",
           "Chấm độ giống nghĩa giữa hai chức danh. Việc rất nhỏ, gọi nhiều "
           "lượt — model chậm ở đây rất tốn.", GROUP_OTHER, "json"),
]

TASKS = {row.name: row for row in _ROWS}

#: Mặc định (nhà cung cấp, model) cho TỪNG tác vụ — không có ngoại lệ.
#:
#: Tách khỏi `_ROWS` vì đây là *chính sách*, đổi theo số đo; còn nhãn và `kind`
#: là *sự thật* về tác vụ, gần như không đổi.
#:
#: Trước đây chỉ 4 tác vụ có route trong CSDL, 4 cái lấy model từ env, và **13
#: cái còn lại im lặng rơi xuống `MSB_AI_GREENNODE_MODEL`**. Không ai chọn thế —
#: đó chỉ là cái rơi xuống, và nó rơi trúng ba quả mìn:
#:
#: * `cv_parsing` → glm-5.2 **timeout** khi chuẩn hoá một CV 3KB.
#: * `cv_ocr` → glm-5.2 **trả HTTP 400 với ảnh**; nó không có thị giác. Đường
#:   này chưa từng chạy thật (Edge bóc hết trước khi tới Hub) nên chưa ai thấy.
#: * `title_similarity` → glm-5.2 chậm hơn Qwen3.6 Flash ~36%, điểm không hơn.
#:
#: Nay mọi tác vụ có route thật trong CSDL, sinh bằng data migration và sửa được
#: trong `/settings`. Không còn tầng "thừa hưởng" vô hình.
#: Hạn mức token của chỗ gọi quyết định model được phép chọn — không chỉ chất
#: lượng hành văn. Lý do là một cái bẫy chỉ lộ ra khi ĐO:
#:
#: `ai/providers.py` **cắt bỏ `reasoning_effort` cho mọi model `deepseek/*`**
#: (chúng trả HTTP 400 với tham số đó). Nghĩa là lời dặn "đừng nghĩ" không tới
#: được model, nó vẫn nghĩ, và phần nghĩ ăn vào cùng hạn mức token với phần chữ.
#:
#: Đo thật trên production, cùng một đề bài soạn thư:
#:
#:     deepseek-v4-pro    @800  → 0 ký tự, RỖNG HOÀN TOÀN
#:     deepseek-v4-pro    @1200 → cụt giữa câu
#:     deepseek-v4-flash  @800  → cụt giữa chữ ("tham d")
#:     qwen3.6-flash      @800  → 909 ký tự, TRỌN VẸN, 2,9s
#:
#: Nên chỗ nào hạn mức chật thì model tôn trọng `reasoning_effort` thắng model
#: viết hay: một bản nháp đủ ý đọc được hơn hẳn một bản nháp xuất sắc bị cụt, và
#: hơn vô hạn một chuỗi rỗng. Đây đúng là cơ chế đẻ ra lỗi #4 trong sổ
#: `docs/AI_AGENT_ACCEPTANCE_CRITERIA.md` §4 — câu cụt giữa chừng, lặp ba lần.
#: `ai/tests_model_param_fit.py` canh không cho tổ hợp này tái diễn.
_QWEN = ("greennode", "qwen/qwen3.6-flash")        # nhanh, rẻ, có thị giác
_GEMINI_FAST = ("gemini", "gemini-3.5-flash")      # benchmark 2026-09: plan/judge nhanh hơn 5-6x
_VIET_TOT = ("greennode", "deepseek/deepseek-v4-pro")   # CHỈ khi hạn mức ≥ 4000
_VIET_NHANH = ("greennode", "deepseek/deepseek-v4-flash")
_EMBED = ("gemini", "models/gemini-embedding-2")

DEFAULT_ROUTE = {
    # ① và ③ cần nhanh/rẻ; ⑤ là chặng duy nhất người dùng đọc thấy.
    "talent_answer_plan": _QWEN,
    "talent_answer_judge": _GEMINI_FAST,
    "talent_answer_compose": _VIET_TOT,  # hạn mức 7000 — đủ chỗ cho phần nghĩ
    "talent_corpus_qa": _QWEN,           # hạn mức 900
    "talent_search": _QWEN,
    "talent_embedding": _EMBED,
    "person_qa": _VIET_NHANH,

    "assistant_conversation": _QWEN,     # hạn mức 600 — model phải tôn trọng
    #                                      reasoning_effort, nếu không stream đứt
    #                                      giữa chừng ("Mất kết nối" — ảnh 04/09)
    "assistant_intent": _QWEN,
    "assistant_web": _QWEN,              # hạn mức 1200
    "assistant_agent": _QWEN,
    "assistant_outreach": _QWEN,         # hạn mức 700 — chật nhất trong hệ

    "cv_parsing": _QWEN,
    "cv_ocr": _QWEN,                     # đo được: đọc đúng ảnh chữ
    "candidate_extraction": _QWEN,
    "candidate_intake_extraction": _QWEN,
    "cv_reference_extraction": _QWEN,

    "jd_parse": _QWEN,
    "outreach_draft": _QWEN,             # hạn mức 1200

    "rb_prospect_search": _QWEN,
    "rb_outreach_draft": _QWEN,          # hạn mức 800

    "social_intent": _QWEN,
    "title_similarity": _QWEN,
}

# Capability is a workload policy, not a requirement for a particular model.
# Existing measured task overrides remain authoritative; new registered tasks
# can inherit one of these defaults without business code naming a provider.
CAPABILITY_DEFAULT_ROUTE = {"FAST": _QWEN, "DEEP": _VIET_TOT,
                            "VISION": _QWEN, "EMBEDDING": _EMBED}
#: Thứ tự hiển thị nhóm trong `/settings`.
GROUPS = [GROUP_ANSWER, GROUP_ASSISTANT, GROUP_INTAKE, GROUP_HIRING, GROUP_RB,
          GROUP_OTHER]


def names():
    """Mọi tác vụ, theo thứ tự khai báo."""
    return [row.name for row in _ROWS]


def default_route(name):
    """(nhà cung cấp, model) mặc định. Mọi tác vụ đều có — test canh điều đó."""
    task = TASKS.get(name)
    return DEFAULT_ROUTE.get(name, CAPABILITY_DEFAULT_ROUTE.get(
        task.capability if task else "", ("", "")))


def capability_for(name):
    task = TASKS.get(name)
    return task.capability if task else ""


def as_payload():
    """Cho `/settings`: đủ để dựng danh sách chọn có nhãn, không phải gõ tay mã."""
    rows = []
    for row in _ROWS:
        provider, model = default_route(row.name)
        rows.append({"name": row.name, "label": row.label,
                     "description": row.description, "group": row.group,
                     "kind": row.kind, "default_provider": provider,
                     "default_model": model})
    return rows
