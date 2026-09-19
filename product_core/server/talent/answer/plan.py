# -*- coding: utf-8 -*-
"""① Hiểu câu hỏi → `QueryPlan`.

Khác hẳn `talent/hiring_need.py` cũ ở ba điểm quyết định:

1. **`search_queries` do LLM tự viết** — nhiều cách nói, cả tiếng Việt lẫn tiếng
   Anh. Bộ cũ dịch một lần sang tiếng Anh rồi mất nguyên văn, nên "quan hệ khách
   hàng" → "Customer Relationship" → không CV nào chứa → 0 kết quả.
2. **`sort_by` + `limit` được giữ.** Bộ cũ không có ô nào chứa "5 người ít tuổi
   nhất" nên vế đó biến mất im lặng.
3. **`extract` mở.** Trình độ, trường, ngành học, năm sinh không cần cột trong
   CSDL — chặng ③ bóc thẳng từ text CV. Hỏi gì bóc nấy.

Không có schema tiêu chí cứng: `must_have`/`should_have` là câu chữ tự nhiên, do
chặng ③ (LLM đọc bằng chứng) phán đoán, không phải do SQL `LIKE` quyết định.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace

from ai.jsonx import as_int, as_list, extract_json
from ai.router import complete
from people.normalize import normalize_name

log = logging.getLogger(__name__)

TASK = "talent_answer_plan"

SHAPES = ("find_people", "analyze", "count", "compare", "followup", "general",
          "action")
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
MAX_QUERIES = 6

#: Trên mức này thì TIN phán đoán của ① và tắt chốt chặn từ khoá bên dưới.
#: Đặt cao có chủ đích: chốt chặn `mentions_store` chặn đúng lỗi tệ nhất Radar
#: từng mắc ("thế bạn có cv những ngành nào" → "tôi không có dữ liệu"), nên chỉ
#: nhường đường khi ① vừa rất chắc vừa đã thật sự suy luận.
TRUST_SHAPE_ABOVE = 0.85

#: Dưới mức này, có câu hỏi làm rõ thì HỎI LẠI thay vì đoán rồi chạy ①→⑤.
CLARIFY_BELOW = 0.4

SYSTEM = """Bạn là bộ lập kế hoạch truy vấn cho Radar — trợ lý tra cứu Kho con người
của MSB (hồ sơ ứng viên + CV đã bóc tách text).

Nhiệm vụ: đọc câu hỏi (kèm ngữ cảnh hội thoại nếu có) và trả về MỘT kế hoạch tìm
kiếm dạng JSON. Bạn KHÔNG trả lời câu hỏi, KHÔNG bịa dữ liệu.

Chỉ trả JSON, các khoá viết THEO ĐÚNG THỨ TỰ dưới đây:

- "suy_luan": 2–4 câu NGẮN, và phải là khoá ĐẦU TIÊN bạn viết ra. Đây là chỗ
  bạn NGHĨ để chọn nhánh, không phải chỗ giải thích sau khi đã chọn. Lần lượt:
  (a) Người dùng thực sự đang muốn gì? Nói lại bằng lời của bạn.
  (b) Câu này có dính tới kho hồ sơ/CV/ứng viên không — kể cả khi họ hỏi theo
      lối "bạn có…"? Nếu có thì KHÔNG BAO GIỜ là "general".
  (c) Họ muốn TRA CỨU thông tin, hay đang BẢO LÀM một việc trên nhóm người đã
      nhắc ở lượt trước (→ "action")?
  (d) Nếu chỉ là chào hỏi / cảm ơn / kiến thức chung ngoài kho → "general".
  Viết "shape" TRƯỚC rồi bịa "suy_luan" cho khớp là hỏng đúng cơ chế này.
- "shape": một trong "find_people" (tìm/liệt kê người), "analyze" (tổng hợp,
  nhận xét về kho), "count" (đếm/thống kê), "compare" (so sánh), "followup"
  (hỏi tiếp về kết quả vừa rồi), "action" (người dùng bảo LÀM một việc trên
  người đã nhắc tới: soạn thư tiếp cận, ghi nhớ điều gì đó, truy nguồn gốc một
  dữ kiện, hoặc hỏi TRẠNG THÁI QUAN HỆ/LỊCH SỬ của một người đã nhắc tới — ai
  đang phụ trách, liên hệ lần cuối khi nào, có đang cấm liên hệ không, việc cần
  làm tiếp là gì), "general" (không liên quan dữ liệu người).
  Phân biệt "action" với phần còn lại: "action" là câu MỆNH LỆNH làm việc gì
  ("soạn thư cho 3 người đầu", "nhớ giúp tôi là chỉ tuyển ở Hà Nội", "dữ kiện
  này lấy từ đâu ra", "ai đang phụ trách người này", "đã liên hệ lần cuối khi
  nào"), không phải câu hỏi tra cứu HỒ SƠ/CV (những câu đó là analyze/count/
  find_people/compare) — action chỉ dành cho câu cần một CÔNG CỤ đọc dữ liệu
  vận hành (quan hệ, dòng thời gian, nguồn gốc, ghi nhớ) chứ không đọc CV.

  CẢNH BÁO về "compare" vs "action" (TẠO BẢNG / SO SÁNH):
  - Các câu "tạo bảng đánh giá các ứng viên trên", "lập bảng so sánh", "đánh giá dạng bảng",
    "so sánh các ứng viên vừa tìm", "tổng hợp ưu nhược điểm dạng bảng" KHÔNG PHẢI là "action".
    Chúng là shape="compare" (hoặc "followup") — đây là tác vụ phân tích, đối chiếu hồ sơ và
    trình bày dạng bảng của Radar, TUYỆT ĐỐI KHÔNG chọn "action".
  - KHÁC với trên: đối chiếu MỘT ứng viên đã nhắc tới với YÊU CẦU CỦA MỘT VỊ TRÍ
    (JD dán vào, hoặc liệt kê "cần biết X, Y, trên Z năm kinh nghiệm") — không so
    với người khác, mà so với một danh sách yêu cầu — LÀ "action" ("ứng viên này
    có đáp ứng JD sau không: …", "đối chiếu hồ sơ với yêu cầu vị trí: cần Java,
    tiếng Anh, trên 3 năm"). Phân biệt bằng: đối tượng so sánh là NGƯỜI KHÁC
    (→ compare) hay một DANH SÁCH YÊU CẦU không phải người (→ action).

  CÒN MỘT TRƯỜNG HỢP "action" NỮA — ƯỚC TÍNH field còn thiếu của MỘT ứng viên
  đã nhắc tới, khi CV không ghi trực tiếp field đó ("ước tính giúp tôi ứng viên
  này khoảng bao nhiêu năm kinh nghiệm", "đoán năm sinh/năm tốt nghiệp hộ tôi
  người này"). Đây LÀ "action" (tool tính từ mốc thời gian khác đã biết, không
  đọc lại CV) — khác với hỏi con số CV đã ghi rõ (đó vẫn là analyze/find_people,
  đọc thẳng từ CV, không suy đoán).

  CẢNH BÁO về "general" — đây là chỗ hay bị chọn nhầm nhất:
  "general" CHỈ dành cho câu KHÔNG dính gì tới kho hồ sơ — chào hỏi, hỏi Radar
  là gì, kiến thức chung, tin tức, thời tiết, lãi suất.
  Câu hỏi có nhắc tới CV / hồ sơ / ứng viên / kho / dữ liệu thì KHÔNG BAO GIỜ là
  "general", kể cả khi nó hỏi theo lối "bạn có…". Những câu sau đều nói về kho:
    "thế bạn có cv những ngành nào"        → analyze
    "bạn đánh giá tổng quan về kho ứng viên" → analyze
    "kho mình có dữ liệu gì"                → analyze
    "bạn có bao nhiêu hồ sơ"                → count
  Chọn nhầm những câu này thành "general" khiến Radar trả lời "tôi không có dữ
  liệu" trong khi kho có hàng trăm hồ sơ — sai nghiêm trọng nhất có thể mắc.

  NGƯỢC LẠI — "MSB" trong câu hỏi không tự động nghĩa là "kho": MSB vừa là tên
  ngân hàng thật (Ngân hàng TMCP Hàng Hải Việt Nam) vừa là tên kho CV ứng viên
  ứng tuyển vào MSB. Câu hỏi về BẢN THÂN ngân hàng — lãnh đạo, tổ chức, tin tức,
  sản phẩm, lãi suất — là kiến thức thế giới thực, KHÔNG phải một phép tổng hợp
  trên kho CV, dù câu có chữ "MSB":
    "tổng giám đốc msb là ai"          → general (hỏi về ngân hàng, không phải
                                          hồ sơ nào trong kho)
    "msb có bao nhiêu chi nhánh"       → general
    "lãi suất huy động của msb"        → general
  Phân biệt bằng: câu có đang hỏi về NGƯỜI/HỒ SƠ nằm TRONG kho không (ứng viên,
  CV, "chúng ta có ai…"), hay đang hỏi một sự thật về chính ngân hàng MSB như
  một tổ chức ngoài đời? Chỉ vế đầu mới là analyze/find_people/count.
- "do_tin_cay": 0.0–1.0 — bạn CHẮC tới đâu về "shape" vừa chọn, viết NGAY SAU
  nó. Chấm thật thà, đây không phải điểm thi:
    ≥ 0.8  câu hỏi rõ ràng, chỉ có một cách hiểu.
    0.4–0.8 hiểu được nhưng còn một điểm mập mờ, vẫn đoán được ý chính.
    < 0.4  thật sự không biết họ muốn gì — hai cách hiểu trở lên, khác hẳn nhau.
  Cho điểm cao cho mọi câu là làm hỏng công dụng của khoá này.
- "cau_hoi_lam_ro": CHỈ điền khi "do_tin_cay" < 0.4 — MỘT câu hỏi ngắn hỏi lại
  người dùng để gỡ đúng chỗ mập mờ đó, xưng "anh/chị". Không mập mờ thì để "".
  Ví dụ: "Anh/chị muốn tìm ứng viên đang làm ở MSB, hay ứng viên từng làm ở MSB ạ?"
  ĐỪNG hỏi lại chỉ vì câu hỏi khó — hỏi lại khi nó ĐA NGHĨA.

  CẢNH BÁO về CÂU XÁC NHẬN / ĐỒNG Ý NGẮN ("có", "vâng", "ừ", "ok", "đồng ý", "làm đi", "tiếp tục", "lọc đi"...):
  - Khi lượt trước Radar vừa hỏi hoặc đề xuất một hướng tiếp theo (ví dụ: "Anh/chị có muốn Radar ưu tiên lọc sâu hơn các ứng viên đã xác định ở Hà Nội như Giang Lê và Tạ Nguyễn Phương Minh trước không?"):
    + Câu trả lời "có", "vâng", "ok", "đồng ý", "làm đi", "tiếp tục", "lọc đi" là sự XÁC NHẬN ĐỒNG Ý thực hiện đề xuất đó.
    + Đây là câu có mục tiêu rõ ràng từ ngữ cảnh, TUYỆT ĐỐI KHÔNG coi là mơ hồ hay không hiểu được (do_tin_cay >= 0.85, TUYỆT ĐỐI KHÔNG sinh "cau_hoi_lam_ro").
    + "information_need": viết lại thành câu thực thi đầy đủ đề xuất đó (ví dụ: "Ưu tiên lọc sâu hơn các ứng viên đã xác định ở Hà Nội như Giang Lê và Tạ Nguyễn Phương Minh trước").
    + "shape": chọn "followup" hoặc "find_people" (hoặc "action" nếu đề xuất là soạn thư / thao tác công cụ).
    + "should_have" / "must_have": bám sát tiêu chí của đề xuất (ví dụ: "ở Hà Nội", "ưu tiên Giang Lê", "ưu tiên Tạ Nguyễn Phương Minh").
    + "search_queries": tạo các truy vấn tìm kiếm phù hợp với đề xuất đó.
- "information_need": viết lại câu hỏi thành MỘT câu độc lập, đã ghép ngữ cảnh
  hội thoại, đủ nghĩa khi đọc riêng.
- "must_have": mảng câu chữ — điều kiện BẮT BUỘC, không thoả thì loại. Rất ít.
  Chỉ đưa vào khi người hỏi nói rõ là bắt buộc hoặc là bản chất vai trò cốt lõi.
  QUY TẮC CỐT LÕI (TRÁNH LOẠI SẠCH HỒ SƠ VỀ 0):
  - Khi người dùng nêu một câu tìm kiếm tự nhiên nhiều tiêu chí (ví dụ "Tìm Senior Data Analyst ở Hà Nội biết SQL và Python, trên 3 năm kinh nghiệm"):
    + CHỈ đưa vai trò/chuyên môn cốt lõi vào "must_have" (ví dụ "vị trí hoặc kinh nghiệm về Data Analyst / phân tích dữ liệu").
    + TUYỆT ĐỐI KHÔNG đưa tất cả tiêu chí vào "must_have". Hãy đưa các tiêu chí bổ trợ: cấp bậc ("Senior"), số năm kinh nghiệm ("trên 3 năm kinh nghiệm"), công cụ kỹ thuật phụ ("biết SQL", "biết Python"), địa điểm ("ở Hà Nội") vào "should_have" để hệ thống chấm điểm và xếp hạng. Đưa tất cả vào must_have sẽ khiến logic AND loại bỏ 100% ứng viên tiềm năng do CV không ghi đủ từng chữ.
- "should_have": mảng câu chữ — tiêu chí mong muốn, dùng để xếp hạng, thiếu vẫn
  có thể lọt vào danh sách.
  Riêng câu ĐẾM: mọi điều kiện xác định nhóm cần đếm, kể cả phủ định, đều là
  must_have; chỉ tiêu chí người dùng nói rõ là ưu tiên mới là should_have.
  Tách từng điều kiện: "bao nhiêu người biết SQL và không biết Python" →
  shape="count", must_have=["biết SQL", "không biết Python"]. Không suy phủ
  định từ việc CV không nhắc kỹ năng. Câu đếm trong nhóm lượt trước vẫn là
  count; tên của nhóm là phạm vi, không phải điều kiện must_have.
- "extract": mảng tên thuộc tính cần BÓC RA TỪ CV để trả lời được câu hỏi
  (ví dụ "năm sinh", "trường tốt nghiệp", "trình độ", "số năm kinh nghiệm").
  Chỉ liệt kê thứ câu hỏi thực sự cần; rỗng nếu không cần.
- "sort_by": {"key": "<tên thuộc tính trong extract>", "dir": "asc"|"desc"}
  hoặc null. "ít tuổi nhất" = sinh sau = năm sinh "desc".
  "lớn tuổi nhất" = sinh sớm = năm sinh "asc". "nhiều kinh nghiệm
  nhất" = số năm kinh nghiệm "desc".
- "limit": số hồ sơ người hỏi muốn. Không nói rõ thì 10.
- "search_queries": 3–6 truy vấn ngữ nghĩa để tìm trong kho CV. ĐÂY LÀ PHẦN
  QUAN TRỌNG NHẤT.
- "next_steps": mảng các việc CÒN LẠI, khi một câu chứa NHIỀU VIỆC nối nhau.
  Mỗi phần tử: {"shape": "...", "yeu_cau": "câu mô tả việc của bước đó"}.
  Các khoá ở trên mô tả việc THỨ NHẤT; "next_steps" mô tả việc thứ hai trở đi.
  Tối đa 2 bước tiếp theo. Câu chỉ có một việc thì để mảng rỗng.
  Ví dụ "tìm ứng viên Java rồi soạn thư cho người đầu":
    shape = "find_people", search_queries = [...Java...],
    next_steps = [{"shape": "action", "yeu_cau": "soạn thư tiếp cận cho người đầu tiên"}]
  Ví dụ "tìm 5 người quan hệ khách hàng, so sánh 2 người đầu":
    shape = "find_people", limit = 5,
    next_steps = [{"shape": "action", "yeu_cau": "so sánh hai người đầu danh sách"}]
  KHÔNG tách một việc thành nhiều bước. "Tìm ứng viên Java biết Spring" là MỘT
  việc với hai điều kiện, không phải hai bước.

Quy tắc cho "search_queries":
- Viết ĐỦ MỌI CÁCH NÓI của cùng một khái niệm: nguyên văn tiếng Việt người hỏi
  dùng, cách viết nghiệp vụ khác, viết tắt, và bản tiếng Anh.
- CV ứng viên Việt Nam trộn cả tiếng Việt lẫn tiếng Anh — phải phủ cả hai.
- Ví dụ "quan hệ khách hàng" → ["quan hệ khách hàng cá nhân",
  "chuyên viên khách hàng ưu tiên priority banking", "customer relationship
  manager RM", "chăm sóc tư vấn khách hàng ngân hàng"].
- Ví dụ "học cao đẳng" → ["tốt nghiệp cao đẳng", "trình độ cao đẳng college",
  "bằng cao đẳng chính quy"].
- KHÔNG viết cả câu hỏi thành một truy vấn. Tách theo khái niệm.
- KHÔNG thêm điều kiện người hỏi không nêu.

Nếu ngữ cảnh có mục "NGƯỜI DÙNG ĐÃ DẶN": đó là điều họ đã chủ động bảo bạn nhớ.
Áp dụng vào kế hoạch khi có liên quan (thường thành "should_have"). Chỉ đưa lên
"must_have" nếu lời dặn nói rõ là bắt buộc. Câu hỏi lần này mâu thuẫn với lời
dặn thì CÂU HỎI THẮNG — người ta có quyền đổi ý.

Nếu câu hỏi không liên quan tới dữ liệu con người (chào hỏi, hỏi về Radar, kiến
thức chung) thì shape="general" và search_queries=[]."""


@dataclass
class QueryPlan:
    #: Vài câu ① tự nghĩ TRƯỚC khi chốt `shape`. Đứng đầu JSON có chủ đích: model
    #: sinh token trái→phải, nên khoá nào viết trước thì khoá sau được đặt điều
    #: kiện lên nó. Trước đây "shape" là token ĐẦU TIÊN — nhánh bị chốt xong mới
    #: có gì để suy nghĩ, và mọi lỗi định tuyến ("xin chào" ra tài liệu nội bộ,
    #: "thế bạn có cv những ngành nào" ra "tôi không có dữ liệu") đều sinh ra ở
    #: đúng token đó. Cũng được ghi vào trace để xem ① đã nghĩ gì khi chọn sai.
    reasoning: str = ""
    shape: str = "find_people"
    #: ① tự chấm mình chắc tới đâu về `shape`. Dùng để quyết định khi nào TIN ①
    #: và khi nào để chốt chặn cứng bên dưới ra tay — xem `TRUST_SHAPE_ABOVE`.
    confidence: float = 0.0
    #: Câu hỏi lại người dùng, chỉ có khi ① thật sự không biết họ muốn gì. Đoán
    #: bừa rồi chạy hết ①→⑤ mất vài chục giây để ra một câu trả lời lạc đề thì
    #: tệ hơn hẳn việc hỏi lại một câu.
    clarify: str = ""
    information_need: str = ""
    must_have: list = field(default_factory=list)
    should_have: list = field(default_factory=list)
    extract: list = field(default_factory=list)
    sort_by: dict | None = None
    limit: int = DEFAULT_LIMIT
    search_queries: list = field(default_factory=list)
    #: Các việc CÒN LẠI sau bước này, khi một câu chứa nhiều việc.
    #:
    #: "Tìm ứng viên Java rồi soạn thư cho người đầu" là MỘT câu, HAI việc. Một
    #: `shape` không diễn tả được điều đó: nếu chọn `find_people` thì thư không
    #: bao giờ được soạn, nếu chọn `action` thì không có ai để soạn cho.
    #:
    #: Mỗi phần tử: {"shape": "...", "yeu_cau": "câu mô tả việc của bước đó"}.
    #: Bước sau nhận danh sách người của bước trước qua `last_result` — đúng cơ
    #: chế câu hỏi tiếp vẫn dùng, không phải đường dây riêng.
    next_steps: list = field(default_factory=list)
    provider: str = ""
    model: str = ""
    fallback: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def needs_people(self) -> bool:
        """Có phải đi truy hồi kho người không (①→⑤)?

        `action` KHÔNG: người dùng bảo làm việc gì đó trên người đã nhắc ở lượt
        trước, nên đối tượng đã có sẵn trong ngữ cảnh — đi tìm lại từ đầu vừa
        tốn tiền vừa dễ ra một danh sách khác với danh sách họ đang nói tới.
        """
        return self.shape not in ("general", "action") and bool(self.search_queries)

    @property
    def wants_action(self) -> bool:
        return self.shape == "action"

    @property
    def wants_clarification(self) -> bool:
        """Hỏi lại thay vì đoán. Cần CẢ HAI: ① tự nhận là không chắc, VÀ nó viết
        ra được một câu hỏi cụ thể. Thiếu câu hỏi thì hỏi lại cũng vô ích."""
        return bool(self.clarify) and self.confidence < CLARIFY_BELOW

    def as_dict(self):
        return {"reasoning": self.reasoning,
                "shape": self.shape, "confidence": self.confidence,
                "clarify": self.clarify,
                "information_need": self.information_need,
                "must_have": self.must_have, "should_have": self.should_have,
                "extract": self.extract, "sort_by": self.sort_by,
                "limit": self.limit, "search_queries": self.search_queries,
                "next_steps": self.next_steps,
                "provider": self.provider, "model": self.model,
                "fallback": self.fallback}


#: Từ khoá cho thấy câu hỏi nói về KHO của Radar, không phải kiến thức chung.
#: Cả bản có dấu lẫn không dấu — người dùng thật gõ cả hai kiểu.
_STORE_WORDS = ("cv", "hồ sơ", "ho so", "ứng viên", "ung vien", "kho ",
                "trong kho", "dữ liệu", "du lieu", "hồ sơ nào", "ho so nao")


def mentions_store(question):
    """Câu hỏi có nhắc tới kho hồ sơ không (dù hỏi theo lối "bạn có…")."""
    low = " ".join(str(question or "").casefold().split())
    return any(word in low for word in _STORE_WORDS)


def has_recent_candidates(envelope):
    """Lượt trước đã trả về người nào chưa.

    Câu hỏi tiếp ("ai trong số đó nhiều kinh nghiệm nhất") không nhắc CV/kho
    nhưng vẫn là follow-up trên kho — không được coi như lạc đề kiểu
    "MSB là ngân hàng". Xem chỗ gọi ở `engine.py`.
    """
    projection = getattr(envelope, "projection", None)
    if projection is None:
        return False
    return bool(projection.last_result_people(limit=1))


_AFFIRMATIVE_WORDS = frozenset((
    "co", "vang", "da", "uh", "um", "ok", "oke", "okay", "okie",
    "duoc", "duoc chu", "dong y", "nhat tri", "chinh xac", "dung roi",
    "lam di", "tiep tuc", "loc di", "trien khai di", "loc tiep",
    "loc giup toi", "tim giup toi", "loc them", "tien hanh di", "yes", "yep",
))

_AFFIRMATIVE_PREFIXES = (
    "co ", "vang ", "da ", "dong y ", "ok ", "duoc ", "lam di ",
    "tiep tuc ", "loc di ", "loc tiep ", "trien khai ", "nhat tri ",
)


def is_short_affirmation(question):
    """True nếu câu hỏi là phản hồi ngắn đồng ý / xác nhận."""
    text = normalize_name(question)
    if not text:
        return False
    words = text.split()
    if len(words) > 6:
        return False
    return text in _AFFIRMATIVE_WORDS or text.startswith(_AFFIRMATIVE_PREFIXES)


def detect_last_proposal(envelope):
    """Trích xuất câu hỏi/đề xuất ở cuối lượt trả lời gần nhất của Radar (nếu có)."""
    projection = getattr(envelope, "projection", None)
    if projection is None:
        return ""
    turns = list(getattr(projection, "recent_turns", []) or [])
    if not turns:
        return ""
    last_ans = str(turns[-1].get("answer") or "").strip()
    if not last_ans:
        return ""
    paragraphs = [p.strip() for p in last_ans.split("\n") if p.strip()]
    if not paragraphs:
        return ""
    for p in reversed(paragraphs[-4:]):
        p_fold = normalize_name(p)
        if any(p_fold.startswith(prefix) for prefix in ("ho so duoc nhac", "trich dan", "goi y cau hoi", "goi y")):
            continue
        if "?" in p or any(kw in p_fold for kw in ("co muon", "muon radar", "uu tien loc", "loc sau")):
            sentences = re.split(r"(?<=[.?!])\s+", p)
            for s in reversed(sentences):
                s_fold = normalize_name(s)
                if "?" in s or any(kw in s_fold for kw in ("co muon", "muon radar", "uu tien loc", "loc sau")):
                    return s.strip()
            return p.strip()
    return ""


def clean_proposal_to_need(proposal):
    """Chuyển câu hỏi đề xuất của Radar thành câu yêu cầu (information_need)."""
    text = proposal.strip()
    text = re.sub(r"^(?:anh/chị|anh|chị|bạn)?\s*(?:có\s+)?(?:muốn\s+)?(?:radar\s+)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*(?:không\s*\??|ạ\s*\??|\?+)$", "", text, flags=re.IGNORECASE)
    text = text.strip()
    if text:
        return text[0].upper() + text[1:]
    return proposal


def _context_block(envelope):
    """Vài lượt gần nhất + kết quả lượt trước + điều người dùng đã dặn.

    `memories` là những điều người dùng chủ động bảo Radar nhớ ("tôi chỉ tuyển ở
    Hà Nội"). Không đưa vào đây thì panel "Radar nhớ" chỉ là một cuốn sổ không
    ai đọc: người dùng dạy một điều, Radar ghi lại, rồi trả lời như chưa từng
    biết. Chúng đã được `projection` lọc prompt-injection trước khi tới đây.
    """
    projection = getattr(envelope, "projection", None)
    if projection is None:
        return ""
    parts = []

    memories = list(getattr(projection, "memories", []) or [])[:8]
    if memories:
        parts.append("NGƯỜI DÙNG ĐÃ DẶN:\n"
                     + "\n".join(f"- {m}" for m in memories))

    summary = str(getattr(projection, "summary", "") or "").strip()
    if summary:
        parts.append("TÓM TẮT PHẦN HỘI THOẠI CŨ:\n" + summary[:1800])

    criteria = getattr(projection, "active_criteria", None) or {}
    if criteria:
        parts.append("TIÊU CHÍ ĐANG CÓ HIỆU LỰC:\n" + str(criteria)[:1200])

    turns = list(getattr(projection, "recent_turns", []) or [])[-12:]
    for index, turn in enumerate(turns):
        is_last = (index == len(turns) - 1)
        question = str(turn.get("question") or "").strip()[:500]
        raw_answer = str(turn.get("answer") or "").strip()
        if is_last:
            # Lượt gần nhất: giữ tối đa 2500 ký tự. Nếu dài hơn, giữ đoạn đầu và đoạn đuôi
            # (chứa câu hỏi gợi mở / đề xuất tiếp theo của Radar).
            if len(raw_answer) <= 2500:
                answer = raw_answer
            else:
                answer = raw_answer[:1600] + "\n...\n" + raw_answer[-800:]
        else:
            answer = raw_answer[:700]
        if question:
            parts.append(f"H: {question}")
        if answer:
            parts.append(f"Đ: {answer}")
    last = projection.last_result_lines() if hasattr(projection, "last_result_lines") else ""
    if last:
        parts.append(last[:600])
    return "\n\n".join(parts)



def plan(question, *, envelope=None, complete_fn=None) -> QueryPlan:
    """Câu hỏi → `QueryPlan`. LLM lỗi thì lùi về kế hoạch tối thiểu, không ném lỗi."""
    question = " ".join(str(question or "").split())
    if not question:
        return QueryPlan(shape="general", fallback=True)

    context = _context_block(envelope)
    user = (f"NGỮ CẢNH HỘI THOẠI:\n{context}\n\n" if context else "") + f"CÂU HỎI: {question}"

    caller = complete_fn or complete
    try:
        result = caller(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            # `suy_luan` tốn thêm ~80 token. Hạn mức chật thì JSON bị cắt giữa
            # chừng, `extract_json` trượt, và cả lượt rơi về `_fallback` (đi tìm
            # người cho MỌI câu) — đắt hơn nhiều so với phần token nới ở đây.
            task=TASK, temperature=0, max_tokens=1100, reasoning_effort="none",
            budget_seconds=25, response_format={"type": "json_object"})
    except Exception as exc:                       # noqa: BLE001
        log.warning("answer.plan: LLM lỗi, dùng kế hoạch tối thiểu: %s", exc)
        return _fallback(question)

    payload = extract_json(result.text)
    if not isinstance(payload, dict) or not payload:
        return _fallback(question, provider=getattr(result, "provider", ""),
                         model=getattr(result, "model", ""))

    queries = as_list(payload.get("search_queries"), limit=MAX_QUERIES)
    reasoning = " ".join(str(payload.get("suy_luan") or "").split())[:600]
    confidence = _confidence(payload.get("do_tin_cay"))
    shape = str(payload.get("shape") or "").strip().lower()
    if shape not in SHAPES:
        shape = "general" if not queries else "find_people"
    # Chốt chặn: câu có nhắc CV/hồ sơ/ứng viên/kho mà bị xếp "general" thì Radar
    # sẽ đi nhánh hội thoại và trả lời "tôi không có dữ liệu" — trong khi kho có
    # hàng trăm hồ sơ. Đã xảy ra thật trên production ("thế bạn có cv những ngành
    # nào"). Prompt đã dặn kỹ, nhưng đây là lỗi tệ nhất có thể mắc nên không để
    # nó phụ thuộc một mình vào việc model có nghe lời hay không.
    # Nay nó là TRỌNG TÀI chứ không phải luật tuyệt đối: `mentions_store` chỉ dò
    # từ khoá, nên một câu "general" đúng nghĩa mà lỡ có chữ "dữ liệu" vẫn bị nó
    # bẻ sang nhánh tìm người. Nhường đường khi ① vừa rất chắc vừa CÓ suy luận —
    # thiếu `reasoning` nghĩa là model bỏ qua phần nghĩ, không đáng tin.
    if shape == "general" and mentions_store(question):
        if confidence > TRUST_SHAPE_ABOVE and reasoning:
            log.info("answer.plan: giữ 'general' cho %r — ① chắc %.2f (nghĩ: %r)",
                     question[:80], confidence, reasoning[:200])
        else:
            log.info("answer.plan: ép 'general' → 'analyze' vì câu hỏi nhắc tới kho: "
                     "%r (① chắc %.2f, nghĩ: %r)",
                     question[:80], confidence, reasoning[:200])
            shape = "analyze"
    # "Lấy/mở hồ sơ X và phân tích" là yêu cầu ĐỌC hồ sơ, không phải action
    # qua tool. Model đôi khi xếp nó thành action khiến nhánh tool đã biết tên
    # ở preamble nhưng cuối cùng lại hỏi "làm gì với ai".
    normalized = normalize_name(question)
    # Đếm theo tên là phép thống kê xác định trên chỉ mục toàn kho. Không để
    # model phân loại nhầm thành tìm kiếm hồ sơ rồi chỉ đọc top-N.
    if re.fullmatch(
            r"(?:(?:trong kho )?(?:co )?bao nhieu|dem|tim tat ca) "
            r"(?:ung vien|ho so|nguoi|cv) (?:co )?ten .+", normalized):
        shape = "count"
    asks_profile_analysis = (
        any(mark in normalized for mark in ("ho so", "cv"))
        and any(mark in normalized for mark in (
            "phan tich", "danh gia", "xem chi tiet", "doc chi tiet", "lay ho so", "mo ho so"))
    )
    # "Thống kê / phân bố / cơ cấu … theo <trường>" là câu TỔNG HỢP TOÀN KHO.
    # Production 19/09: "Thống kê số lượng ứng viên theo từng khu vực" bị xếp
    # "count", đọc sâu 60 hồ sơ rồi trả "Hà Nội: 5 ứng viên" — trong khi ~500
    # hồ sơ có địa điểm. Đếm theo tên người (count theo tên) giữ nguyên ở trên.
    if shape in ("count", "find_people", "general") and _DISTRIBUTION.search(normalized):
        shape = "analyze"
    if shape == "action" and asks_profile_analysis:
        shape = "analyze"
        if not queries:
            queries = [question]
    # Không có truy vấn nào mà lại đòi tìm người ⇒ ít nhất dùng chính câu hỏi.
    if shape != "general" and not queries:
        queries = [question]

    sort_by = _sort_by(payload.get("sort_by"))
    # Scalar count has no person ordering. Preserve the richer ranking
    # contract when a model emits the contradictory count + sort combination.
    if shape == "count" and sort_by:
        shape = "find_people"

    # Câu hỏi làm rõ chỉ có nghĩa khi ① tự nhận là không chắc. Model hay viết
    # kèm một câu hỏi cho MỌI lượt; giữ nguyên là Radar hoá ra hỏi lại suốt.
    clarify = " ".join(str(payload.get("cau_hoi_lam_ro") or "").split())[:300]
    if confidence >= CLARIFY_BELOW:
        clarify = ""

    info_need = " ".join(str(payload.get("information_need") or question).split())[:500]

    # Bảo vệ câu xác nhận ngắn ("có", "vâng", "đồng ý", "ok"): nếu lượt trước Radar
    # vừa hỏi/đề xuất một hướng đi và người dùng chỉ gõ xác nhận, không để ① rơi vào
    # nhánh hỏi lại (clarify) hoặc general ngô nghê.
    if is_short_affirmation(question) and envelope is not None:
        last_proposal = detect_last_proposal(envelope)
        if last_proposal:
            clean_need = clean_proposal_to_need(last_proposal)
            if clarify or confidence < CLARIFY_BELOW:
                log.info("answer.plan: gỡ clarify cho câu xác nhận %r theo đề xuất %r",
                         question, last_proposal[:100])
                clarify = ""
                confidence = max(confidence, 0.9)
                if not reasoning:
                    reasoning = f"Người dùng xác nhận đồng ý với đề xuất của Radar: {last_proposal[:150]}"
            if shape in ("general", ""):
                shape = "followup"
            if not queries or queries == [question]:
                queries = [clean_need]
            if not info_need or info_need.casefold() == question.casefold():
                info_need = clean_need

    must_have = as_list(payload.get("must_have"), limit=6)
    should_have = as_list(payload.get("should_have"), limit=10)

    # Câu TINH CHỈNH ngay sau một lượt tìm ("Nới lỏng tiêu chí số năm…", "bỏ yêu
    # cầu Python") là một lượt TÌM LẠI, không phải hội thoại. Production 19/09:
    # ① xếp nó "general", model hội thoại tự bịa "đã tìm kiếm lại" + 3 ứng viên.
    if shape == "general" and is_refinement(question):
        previous = previous_search_criteria(envelope)
        if previous:
            prev_need = str(previous.get("information_need") or "").strip()
            shape = "find_people"
            info_need = f"{prev_need} — điều chỉnh: {question}" if prev_need else question
            queries = queries if queries and queries != [question] else (
                list(previous.get("search_queries") or []) or [info_need])
            must_have = must_have or list(previous.get("must_have") or [])
            should_have = should_have or list(previous.get("should_have") or [])
            clarify = ""
            confidence = max(confidence, 0.85)
            log.info("answer.plan: câu tinh chỉnh %r sau lượt tìm → find_people", question[:80])
    if shape == "find_people":
        must_have, should_have = split_seniority(must_have, should_have)
    queries = useful_queries(queries, info_need or question)

    return QueryPlan(
        reasoning=reasoning,
        confidence=confidence,
        clarify=clarify,
        shape=shape,
        information_need=info_need,
        must_have=must_have,
        should_have=should_have,
        extract=as_list(payload.get("extract"), limit=8),
        sort_by=sort_by,
        limit=as_int(payload.get("limit"), default=DEFAULT_LIMIT, low=1, high=MAX_LIMIT),
        search_queries=queries,
        next_steps=_next_steps(payload.get("next_steps")),
        provider=getattr(result, "provider", ""), model=getattr(result, "model", ""),
        raw=payload)


#: Tiền tố cấp bậc đứng trước một chức danh. Đo trên production 19/09:
#: "Tìm Senior Data Analyst…" → ① đặt must_have=["Senior Data Analyst"], dù
#: prompt đã dặn cấp bậc là should_have. ③ đọc đúng chữ "bắt buộc" nên loại cả
#: người làm Data Analyst thật chỉ vì CV không ghi chữ "Senior" — và ở
#: `structured_match` chữ "senior" còn khớp lỏng với MỌI người có cấp bậc
#: senior, ghim 40 chuyên viên ngân hàng vào đọc thay cho người đúng nghề.
_SENIORITY_PREFIX = re.compile(
    r"^\s*(senior|sr\.?|junior|jr\.?|lead|principal|middle|mid-level|mid|"
    r"fresher|intern|entry-level)\s+(?=\S)", re.I)
_SENIORITY_SUFFIX = re.compile(r"\s+(cấp cao|cao cấp|cấp senior)\s*$", re.I)


def split_seniority(must_have, should_have):
    """Tách cấp bậc khỏi chức danh trong must_have: vai trò vẫn là bắt buộc,
    cấp bậc thành tiêu chí xếp hạng. Chỉ áp cho câu tìm người — câu ĐẾM thì
    "đếm Senior Data Analyst" phải giữ nguyên nghĩa hẹp."""
    must, should = [], list(should_have)
    for item in must_have:
        text = str(item)
        level = None
        match = _SENIORITY_PREFIX.match(text) or _SENIORITY_SUFFIX.search(text)
        if match:
            level = match.group(1).strip()
            text = (text[match.end():] if match.start() == 0 else text[:match.start()]).strip()
        if text:
            must.append(text)
        if level:
            label = level if level.casefold().startswith("cấp") or "cao" in level.casefold()                 else f"cấp {level}"
            if not any(label.casefold() in str(s).casefold() for s in should):
                should.append(label)
    return must, should


def useful_queries(queries, information_need):
    """Bỏ truy vấn chỉ là TÊN ĐỊA DANH ("Hà Nội", "hanoi").

    Mỗi truy vấn là một phiếu bầu ngang hàng trong RRF. Truy vấn "Hà Nội" kéo về
    mọi CV ở Hà Nội — 310/1073 hồ sơ trên production — và đẩy chúng lên ngang
    người khớp chuyên môn. Địa điểm là tiêu chí, ③ tự đối chiếu; nó không phải
    một cách diễn đạt câu hỏi. Không còn truy vấn nào thì dùng chính nhu cầu.
    """
    from core.vn_locations import _normalize_key, canonical_province

    kept = []
    for query in queries:
        text = str(query or "").strip()
        if not text:
            continue
        if canonical_province(text) != text or _normalize_key(text) in _LOCATION_KEYS:
            continue
        kept.append(text)
    return kept or ([information_need] if information_need else [])


def _location_keys():
    from core.vn_locations import _HANOI_DISTRICTS, _HCM_DISTRICTS, _LOOKUP
    return set(_LOOKUP) | set(_HANOI_DISTRICTS) | set(_HCM_DISTRICTS)


_LOCATION_KEYS = _location_keys()


_REFINE = re.compile(
    r"^(noi long|mo rong|bo (yeu cau|tieu chi|dieu kien|bot)|khong (can|bat buoc)|"
    r"chap nhan|tim (them|lai|rong)|thu lai|ha (yeu cau|tieu chi)|giam (yeu cau|tieu chi)|"
    r"them (tieu chi|dieu kien)|chi can|loai bo|khong yeu cau)"
    r"|\b(noi long tieu chi|mo rong tim kiem|khong can ca hai|khong bat buoc)\b")


_DISTRIBUTION = re.compile(
    r"\b(thong ke|phan bo|co cau|ty le|ti le|bao nhieu phan tram)\b.*\btheo\b"
    r"|\btheo (tung )?(khu vuc|tinh|thanh pho|dia phuong|nganh|chuc danh|cap bac|ky nang|cong ty|nguon)\b")


def is_refinement(question):
    """Câu điều chỉnh tiêu chí của lượt tìm trước (không phải một câu hỏi mới)."""
    return bool(_REFINE.search(normalize_name(question)))


def previous_search_criteria(envelope):
    """Kế hoạch của lượt TÌM gần nhất trong hội thoại, hoặc {} nếu chưa tìm lần nào."""
    projection = getattr(envelope, "projection", None)
    if projection is None:
        return {}
    for turn in reversed(list(getattr(projection, "recent_turns", []) or [])):
        criteria = turn.get("criteria") if isinstance(turn, dict) else None
        if isinstance(criteria, dict) and (criteria.get("search_queries")
                                           or criteria.get("information_need")):
            return criteria
    active = getattr(projection, "active_criteria", None) or {}
    if isinstance(active, dict) and active.get("information_need"):
        return active
    # Lượt cũ chưa lưu kế hoạch: có snapshot kết quả tìm kiếm là đã có một lượt
    # tìm — lấy câu hỏi gần nhất KHÔNG phải câu tinh chỉnh làm nhu cầu gốc.
    if getattr(projection, "last_result", None):
        for turn in reversed(list(getattr(projection, "recent_turns", []) or [])):
            asked = str((turn or {}).get("question") or "").strip()
            if asked and not is_refinement(asked):
                return {"information_need": asked, "search_queries": [asked]}
    return {}


#: Trần số bước tiếp theo. Mỗi bước là một lượt gọi model nữa, nên chuỗi dài
#: vừa chậm vừa khó nói cho người dùng biết Radar đang làm gì.
MAX_NEXT_STEPS = 2


def _next_steps(value):
    """Chuẩn hoá `next_steps` do ① sinh ra. Sai khuôn thì bỏ, không đoán."""
    out = []
    for item in (value if isinstance(value, list) else [])[:MAX_NEXT_STEPS]:
        if not isinstance(item, dict):
            continue
        shape = str(item.get("shape") or "").strip().lower()
        need = " ".join(str(item.get("yeu_cau") or "").split())[:300]
        if shape not in SHAPES or not need:
            continue
        out.append({"shape": shape, "yeu_cau": need})
    return out


def _confidence(value):
    """0.0–1.0. Không đọc được thì 0.0 — coi như ① không tự chấm, và mọi chốt
    chặn cứng bên dưới giữ nguyên hiệu lực như trước khi có khoá này."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _sort_by(value):
    if not isinstance(value, dict):
        return None
    key = " ".join(str(value.get("key") or "").split())
    if not key:
        return None
    direction = str(value.get("dir") or "desc").strip().lower()
    return {"key": key, "dir": "asc" if direction == "asc" else "desc"}


def _fallback(question, provider="", model=""):
    """Không hiểu được thì vẫn phải tìm — dùng chính câu hỏi làm truy vấn."""
    return QueryPlan(shape="find_people", information_need=question,
                     search_queries=[question], provider=provider, model=model,
                     fallback=True)


def widen(previous: QueryPlan) -> QueryPlan:
    """Expand retrieval vocabulary without changing the user's constraints.

    A wider candidate pool still has to satisfy the original requirements,
    including exclusions. Keep follow-on actions and all planning metadata.
    """
    queries = list(previous.search_queries)
    if previous.information_need and previous.information_need not in queries:
        queries.append(previous.information_need)
    for item in previous.must_have:
        if item not in queries:
            queries.append(item)
    return replace(previous, search_queries=queries[:MAX_QUERIES + 2])
