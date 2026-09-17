# Phân tích lỗi hỏi–đáp — ảnh test production 04/09/2026

## 0. Chẩn đoán gốc — một câu

**Mọi câu hỏi đều bị ép qua đúng một đường: "truy hồi ngữ nghĩa lấy top-N ngẫu
nhiên → đọc → viết".** Sáu kiểu hỏi trong ảnh test cần một đường khác, hoặc cần
dùng bối cảnh đã có sẵn trong tay (tệp đính kèm, danh sách người của lượt trước)
— nhưng pipeline không có nhánh nào cho chúng, nên tất cả rơi vào đường chung và
trả lời sai theo sáu kiểu khác nhau.

## 1. Sáu lỗi quan sát được, với nguyên nhân đã xác minh trên production

### A. CV đính kèm bị bỏ qua hoàn toàn *(nặng nhất)*

Ảnh 1–2: người dùng đính kèm `CV - Lê Dung.pdf`, hỏi *"Đánh giá ứng viên này"*.
Radar trả lời *"Kho không có hồ sơ nào tên Lê Thị Thùy Dung"*.

Xác minh (`plan.plan()` trên production, câu = "Đánh giá ứng viên này" + text CV):

    shape = analyze
    search_queries = ['đánh giá ứng viên Lê Thị Thùy Dung',
                      'review candidate Le Thi Thuy Dung', ...]

`talent_ask` bóc text CV rồi ghép vào câu hỏi dưới nhãn `TÀI LIỆU ĐÍNH KÈM:`.
① đọc, thấy một cái tên, và **đi tìm cái tên đó trong kho** — trong khi nội dung
CV cần đánh giá đang nằm ngay trong prompt. Không có `shape` nào cho *"đây là
một tài liệu, hãy đánh giá nó"*. Người dùng đính kèm CV chính vì người này CHƯA
có trong kho.

Đây là quy trình lõi của nhà tuyển dụng ("đánh giá CV này giúp tôi") và nó hỏng
từ bước đầu.

### B. Con số "đã rà N hồ sơ" sai và đổi mỗi lượt

Ảnh: "16 hồ sơ", "40 hồ sơ", "12 hồ sơ", "786". Cùng một kho, con số nhảy mỗi
câu. Người dùng đọc thành *"kho chỉ có 16 hồ sơ"* hoặc *"Radar chỉ xem 16/786"*.

Nguyên nhân: `compose` quy tắc 6 bảo model *"cho biết đã rà bao nhiêu hồ sơ"*,
lấy từ `stats["judged"]` — số hồ sơ ③ đọc trong lượt đó, phụ thuộc `pool_for()`
(`analyze`→16, `find_people`→`limit×4`, cache hit→khác). Con số nội bộ này bị
đưa ra ngoài như thể là kích thước kho.

### C. So sánh / hỏi tiếp truy hồi lại từ đầu, mất người của lượt trước

Ảnh 8→9: lượt trước Radar tìm thấy **cả hai** ứng viên và so sánh xong. Lượt sau
*"So sánh 2 ứng viên này cho vị trí X"* → *"chỉ tìm thấy Nguyễn Thị Huyền, Vũ
Thị Khánh Huyền không xuất hiện"*. Ảnh 10: người dùng phải nói *"vừa tìm được
bên trên mà"* thì Radar mới xin lỗi và sửa.

Xác minh: `compare` và `followup` **là `shape` hợp lệ nhưng không có mã nào xử
lý riêng** — chúng rơi vào đúng đường `retrieve → judge → aggregate`. `retrieve`
là ngữ nghĩa + FTS, top-N cắt cứng, **không tất định**: lần này lọt cả hai, lần
sau rớt một. `last_result` (người của lượt trước) chỉ được `⑥ action` và
`_run_next_steps` dùng — đường hỏi–đáp chính bỏ qua.

### D. Câu "lớn tuổi nhất / nhiều kinh nghiệm nhất" quét top-N ngẫu nhiên

Ảnh 4: *"ứng viên lớn tuổi nhất"* → *"trên 16 hồ sơ đã rà soát là Riêu Hải Nam,
38 tuổi"*, và tự nêu có Nguyễn Thị Huyền sinh 1982 (44 tuổi) nhưng "chưa đủ điều
kiện đưa vào".

Xác minh: `shape = find_people`, `search_queries = ['tất cả ứng viên', 'danh
sách hồ sơ', 'người lao động', 'candidate list']` — mấy truy vấn này không khớp
gì rõ ràng, nên ② trả về ~40 người gần như ngẫu nhiên, ④ sắp xếp theo năm sinh
**trong 40 người đó**. Câu hỏi cực trị trên TOÀN kho cần một truy vấn sắp xếp
tất định, không phải truy hồi ngữ nghĩa. (Cùng lớp với lỗi #6 sổ nghiệm thu:
câu ĐẾM chạy hết pipeline tìm–đọc.)

### E. Câu "% ngành X" từ chối thay vì đếm theo full-text

Ảnh 3: *"bao nhiêu % về mảng công nghệ thông tin"* → *"chưa thể trả lời vì
trường 'ngành từng làm' và 'kỹ năng' đều 0/786 hồ sơ có dữ liệu (FACT)"*.

Hai vấn đề: (1) rò thuật ngữ nội bộ "0/786 FACT" ra người dùng; (2) `count`
fast-path chỉ đọc `corpus.facts_for_prompt()`, mà trường `industries` rỗng
(0/786 — đã biết từ hôm qua). Không có bước lùi: đếm số hồ sơ có CV **nhắc tới**
"công nghệ thông tin / IT / lập trình" bằng full-text. Kho có 786 CV text —
đếm được, chỉ là chưa ai nối.

### F. Câu meta làm rơi kết nối

Ảnh 5: *"Bạn tự đánh giá khả năng của mình thế nào"* → *"⚠️ Mất kết nối khi đang
trả lời"*.

Xác minh: `shape = general` → `chat.py` → `build_conversation_request` → model
hội thoại (`assistant_conversation` = `deepseek-v4-flash`, model có bước "nghĩ").
`common_answer` KHÔNG bắt câu này (nó chỉ khớp "bạn làm được gì", "chức năng của
bạn"). Câu "tự đánh giá khả năng" rơi xuống model stream, và stream đứt — cùng
lớp với lỗi #4 sổ nghiệm thu (model nghĩ hết ngân sách). Câu meta kiểu này nên
có câu trả lời cố định, và stream đứt phải trả câu xin lỗi tử tế chứ không phải
"Mất kết nối".

## 2. Kế hoạch sửa — theo mức tác động

| # | Sửa | Lỗi | Cách |
|---|---|---|---|
| A | **Nhánh "đánh giá tài liệu đính kèm"** | A | `talent_ask` báo cho engine biết có đính kèm. `shape` mới `assess_doc`: KHÔNG truy hồi kho; đánh giá thẳng text CV bằng ⑤ (một "ứng viên" = tài liệu đó); có thể đối chiếu kho để nói "người này đã/chưa có trong kho" — nhưng đó là phụ, không phải nội dung chính |
| B | **Con số "đã rà" trung thực** | B | `compose` phân biệt "kho có N hồ sơ" với "đọc kỹ K hồ sơ gần nhất". Không bao giờ để con số K đứng một mình như thể là cỡ kho. Câu tra tên / cực trị thì khung là "đã quét toàn kho" |
| C | **Giải định danh tất định cho compare / followup / tra tên** | C | Trước khi truy hồi ngữ nghĩa: khớp tên (đã bỏ dấu) với `Person`, ghim những người đó vào pool (không bị top-N cắt). `followup`/`compare` lấy người từ `last_result` trước. Kết quả không đổi giữa hai lượt cùng hỏi |
| D | **Cực trị trên toàn kho** | D | `sort_by` có giá trị + không có tiêu chí lọc thật ("lớn tuổi nhất", "trẻ nhất", "nhiều KN nhất") → truy vấn sắp xếp tất định trên mọi người có thuộc tính đó, lấy `limit`. Không truy hồi ngữ nghĩa |
| E | **`count`/`analyze` lùi về full-text** | E | Khi trường FACT rỗng (độ phủ < ngưỡng): đếm theo full-text trên CVChunk, báo "≈ K/786 hồ sơ có nhắc tới … (đếm theo từ khoá trong CV)". Không rò "FACT" ra người dùng |
| F | **Câu meta: trả lời cố định + không rơi kết nối** | F | Thêm mẫu "tự đánh giá / khả năng / năng lực / bạn giỏi gì" vào `common_answer`. `chat.py` stream đứt → trả câu tử tế, không để lỗi nổi lên client thành "Mất kết nối" |

## 3. Thứ tự

A → C → D → B → E → F. (C và D chung một tầng "giải định danh & truy vấn tất
định" trong retrieve nên làm liền nhau; B phụ thuộc C+D vì khung câu chữ đổi
theo đường đi.)

## 4. Kiểm

Mở rộng bộ vàng `answer_eval` với các dạng: CV đính kèm, so sánh 2 tên → hỏi
tiếp "so sánh cho vị trí X", cực trị toàn kho, "% ngành X", câu meta. Chạy lại
trên production, so con số "đã rà" giữa hai lượt cùng câu.

---

## 5. Đã làm (05/09)

| # | Sửa | Chỗ |
|---|---|---|
| A | Nhánh `assess_doc`: đính kèm + câu "đánh giá CV này" → đánh giá THẲNG tài liệu, KHÔNG tra kho. Phân biệt với "tìm người phù hợp + JD" (giữ đường ①). Có nhắc khi trùng tên hồ sơ trong kho | `talent/answer/engine.py::_split_attachment`, `_stream_assess_doc` |
| C | `talent/answer/resolve.py` mới: bóc tên riêng từ kế hoạch + lấy người lượt trước (compare/followup) → **ghim** vào pool, không để top-N cắt. `retrieve()` nhận `pinned_ids` | `resolve.py`, `retrieve.py`, `engine.py::_pipeline` |
| C′ | **Lỗi ngầm tìm ra:** `answer_views._persist` ghi `last_result={"people":[{"id"...}]}` nhưng `Projection` đọc `.get("items")` với shape `{id,name,why}` → `last_result_lines()` LUÔN rỗng. ① không bao giờ biết "2 người này" là ai. Đã sửa cả hai đầu + thêm `last_result_people()` nhận cả hai khoá | `talent/answer_views.py`, `ai/projection.py` |
| B | Payload ⑤ có `kho_co` (cỡ kho thật) + `tra_theo_ten`. Prompt rule 6/6c: không để `da_ra_soat` (16/40/12) đứng một mình như cỡ kho; câu tra tên thì khung "trong kho có/không có hồ sơ tên …" | `talent/answer/compose.py` |
| E | `corpus.fts_estimate()`: trường FACT rỗng thì đếm theo full-text trên CV text, báo "≈ K/N hồ sơ có nhắc tới …". `_corpus_facts` dặn ⑤ đừng dùng chữ "FACT"/"0/786" | `talent/answer/corpus.py`, `engine.py` |
| F | `common_answer` bắt "tự đánh giá / tự nhận xét / bạn giỏi đến đâu…". `build_conversation_request` truyền `reasoning_effort="none"` + `budget_seconds=40`. `_plain` sửa `đ`→`d` (trước đây `đ` bị xoá sạch, mọi mẫu có "đ" trượt). `assistant_conversation` → `qwen3.6-flash` (migration 0016) vì `deepseek-v4-flash` nuốt `reasoning_effort` và hạn mức chỉ 600 token | `ai/conversation.py`, `ai/tasks.py`, migration 0016 |

**Chưa làm — D (cực trị trên TOÀN kho).** "Lớn tuổi nhất" cần năm sinh của MỌI
người, mà năm sinh không phải cột CSDL (③ bóc từ CV theo từng lượt). Làm đúng
cần hoặc ngân sách ③ lớn (đọc ~786 CV ≈ 10 phút) hoặc một tầng tiền-sắp-xếp
theo dữ liệu có cấu trúc (`TalentProfile.years_experience` có cho "nhiều KN
nhất"; "lớn tuổi nhất" thì chưa có gì). Phần B đã làm câu chữ trung thực hơn
("đọc kỹ K trong N"), nhưng câu trả lời cực trị vẫn giới hạn trong pool. Ghi
làm việc riêng.
