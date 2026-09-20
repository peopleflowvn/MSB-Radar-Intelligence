# Radar AI Agent — Hiện trạng hệ thống tìm kiếm ứng viên (Answer Engine)

> **Phạm vi search/retrieval/evidence/answer:** nguồn thực thi chi tiết là `RADAR_AI_SEARCH_EXECUTION_BACKLOG.md` (ticket `SEARCH-*`). Khi hai tài liệu nói khác nhau về retrieval, evidence, completeness hay coverage, backlog đó thắng; tài liệu này giữ phần ngoài phạm vi ấy.

**Trạng thái:** Tài liệu HIỆN TRẠNG — mô tả đúng những gì code đang chạy trên production, không phải
kế hoạch dự định. Nơi nào còn là dự định thì ghi rõ "CHƯA LÀM"/"ĐỀ XUẤT", không lẫn vào phần mô tả
thực tế.
**Cập nhật:** 05/09/2026 — viết lại toàn bộ theo code thật trong `server/talent/answer/` và
`server/intel/`, thay cho bản kế hoạch kiến trúc tổng thể (đa bề mặt, đa giai đoạn) trước đây.
**Phạm vi:** CHỈ hệ thống AI Agent xử lý câu hỏi tìm kiếm/phân tích ứng viên — thư mục
`server/talent/answer/` (5 chặng ①→⑤ + các nhánh rẽ), tầng chỉ mục/truy hồi nuôi nó
(`talent/vector_index.py`, `PersonSearchDocument`/`CVChunk`), và tầng nuôi dữ liệu có cấu trúc
(`server/intel/`, `server/intake/`). Persona hội thoại đa bề mặt, memory dài hạn, RB Radar,
People Intelligence tổng quát và các bài học kiến trúc từ DeepSeek/Hermes **không** thuộc phạm vi bản
này — những phần đó cần tài liệu riêng nếu muốn có hiện trạng tương tự.

---

## 0. Tóm tắt cho người bận

Radar trả lời câu hỏi về "Kho con người" (ứng viên + CV) qua một pipeline 5 chặng
**①lập kế hoạch → ②truy hồi → ③đọc bằng chứng → ④sắp xếp → ⑤viết câu trả lời**, cộng thêm
nhiều đường tắt (fast path) cho các dạng câu hỏi không cần đi hết 5 chặng đó. Không có RAG-toàn-kho
kiểu "nhét hết CV vào context" — mọi thứ đi qua truy hồi có xếp hạng rồi mới tới LLM.

**Đã xác minh hoạt động đúng trên production** (không phải chỉ chạy được ở local): cực trị toàn kho,
ghim theo cấu trúc cho ngưỡng số năm KN, tra web cho câu hỏi ngoài kho, preamble + hiển thị bước,
luồng nền sống sót khi mất kết nối di động, export/backfill dữ liệu. Chi tiết bằng chứng ở §8.

**Còn hạn chế, chưa xử lý** (không che giấu): trần ghim cấu trúc 40 người, ước lượng năm bằng regex
khi thiếu dữ liệu cấu trúc, việc ghim-dù-LLM-phân-loại-sai mới vá cho đúng MỘT loại tiêu chí (số năm
KN) chứ chưa tổng quát, hai chỗ quét toàn bảng `Person` trong bộ nhớ mỗi lượt hỏi, export dựng cả
file trong RAM, ba trường mới trong template nhập liệu chưa có nguồn tự động nào. Danh sách đầy đủ
kèm mức ưu tiên ở §9.

---

## 1. Kiến trúc pipeline — toàn cảnh

```text
POST /api/v1/talent/ask/          (server/talent/answer_views.py)
        │
        ▼
runner.stream()                    (answer/runner.py) — chạy engine trong LUỒNG RIÊNG,
        │                          tách khỏi kết nối HTTP; xem §5.
        ▼
engine.stream_answer() / engine.answer()      (answer/engine.py — nhạc trưởng)
        │
        ├─ có tệp đính kèm + câu hỏi kiểu "đánh giá CV này"
        │       → _stream_assess_doc()  — đọc THẲNG tài liệu, KHÔNG tra kho
        │
        ├─ ①plan.plan() thấy đây là MỆNH LỆNH ("soạn thư cho 3 người đầu")
        │       → act_stage.stream_action()  — vòng lặp tool của ai/agent.py (8 tool, chỉ đọc/đề xuất)
        │
        ├─ ①plan.plan() thấy KHÔNG liên quan Kho con người
        │       → chat_stage.stream_chat()  — câu có sẵn → tra web → hội thoại thường (xem §2.10)
        │
        ├─ shape == "count"                  → trả lời bằng SỐ LIỆU TOÀN KHO (corpus.py), bỏ ②③
        │
        ├─ superlative.wants_whole_store()   → CỰC TRỊ TOÀN KHO bằng luật (regex/cột), bỏ ②③, không LLM
        │
        ├─ câu neo HOÀN TOÀN vào tên đã ghim (compare/followup, không tiêu chí khác)
        │       → bỏ ②, đọc thẳng người đã ghim
        │
        ├─ cache_stage.load() trúng (câu hỏi này + kho này đã trả lời trong 6 giờ qua)
        │       → dùng lại kết quả ③, chạy lại ④ với limit/sort_by của lượt này, viết ⑤ mới
        │
        └─ đường đầy đủ:
             ①plan  → ②retrieve (+ pinned_ids từ resolve.py + structured_match.py)
                     → ③judge (đọc bằng chứng, song song 4 lô)
                     → ④aggregate (sắp xếp/cắt — CODE thuần)
                     → [chưa đủ? plan.widen() MỘT lần rồi chạy lại ②③④]
                     → ⑤compose (viết văn) → verify.check() → sửa MỘT lần nếu có lỗi
                     → next_steps (nếu câu hỏi có nhiều việc nối nhau)
```

Nguyên tắc xuyên suốt cả pipeline, giữ nguyên từ thiết kế gốc và **đúng với code hiện tại**:

- **AI không tự chọn ai lọt danh sách bằng cách "cảm nhận".** ③ đọc bằng chứng cụ thể và trích dẫn
  nguyên văn; CODE (`judge._verify_quote`) đối chiếu lại từng trích dẫn với văn bản gốc, không khớp
  thì loại trích dẫn đó.
- **AI không sắp xếp/đếm.** ④ (`aggregate.py`) là code thuần, tất định — lý do: LLM sắp sai thứ tự và
  sai số lượng trong các lần thử trước (ghi lại trong docstring của chính file).
- **⑤ chỉ viết, không chọn lại.** System prompt của `compose.py` cấm thêm/bớt/đổi thứ tự người so với
  `chosen` đã chốt ở ④.
- **Mọi khẳng định về một người phải có `[n]` trỏ tới trích dẫn đã kiểm chứng** — `verify.py` kiểm lại
  sau khi ⑤ viết xong, sửa đúng một lần nếu phát hiện thiếu nguồn/sai thứ tự/sai số lượng.

---

## 2. Từng chặng — hành vi thật, không phải mô tả lý tưởng

### 2.1. ① Lập kế hoạch — `answer/plan.py`

Một lượt gọi LLM (`task="talent_answer_plan"`, `temperature=0`, `reasoning_effort="none"`) đọc câu
hỏi + ngữ cảnh hội thoại, trả về `QueryPlan`:

| Trường | Ý nghĩa | Ghi chú thật |
|---|---|---|
| `shape` | `find_people / analyze / count / compare / followup / action / general` | Có "chốt chặn" cứng: câu nhắc tới CV/hồ sơ/kho mà LLM chọn `general` thì code ép về `analyze` (`mentions_store()`) — vì đây là lỗi tệ nhất có thể mắc (Radar nói "không có dữ liệu" trong khi kho có hàng trăm hồ sơ) |
| `must_have` | Điều kiện BẮT BUỘC | Prompt dặn "**Rất ít**" — hệ quả trực tiếp: LLM đôi khi xếp một tiêu chí cứng thật sự (ví dụ ngưỡng số năm KN) vào `should_have` thay vì đây (xem §7.2, §8.2) |
| `should_have` | Tiêu chí ưu tiên, thiếu vẫn được xét | |
| `extract` | Tên thuộc tính cần ③ bóc từ CV (năm sinh, trường, GPA…) | Không cần cột riêng trong DB — đây là lý do "học cao đẳng của NEU" trả lời được mà không cần thêm schema |
| `sort_by` | `{key, dir}` | ④ tự chuẩn hoá "ít tuổi nhất"/"nhiều tuổi nhất" về cùng thang năm sinh dù ① viết `asc` hay `desc` |
| `search_queries` | 3–6 truy vấn ngữ nghĩa, đa dạng cách nói VN/EN | Phần ① được nhấn mạnh nhất trong prompt |
| `next_steps` | Việc còn lại khi một câu có nhiều việc nối nhau (tối đa 2 bước) | "Tìm Java rồi soạn thư cho người đầu" → 1 câu, 2 việc |

`plan.widen(previous)` — nới đúng MỘT lần khi ②③④ đầu tiên không ra ai: hạ `must_have` xuống
`should_have`, thêm chính `information_need` làm truy vấn. **Hệ quả cần biết**: sau khi nới,
`must_have` rỗng — nhờ bản vá §8.2, tiêu chí ngưỡng số năm KN vẫn được `structured_match` bắt lại (vì
giờ nó đọc cả `should_have`), nhưng các tiêu chí cấu trúc khác (thành phố, kỹ năng cụ thể) thì KHÔNG
còn được ghim bảo đảm ở lượt nới.

### 2.2. ② Truy hồi — `answer/retrieve.py`

CODE thuần, không LLM. Chạy **mọi** `search_queries` qua ba nhánh song song rồi hợp nhất bằng
**Reciprocal Rank Fusion (RRF)**, gộp theo NGƯỜI:

- **dense vector** trên `PersonSearchDocument.embedding` (hồ sơ tổng hợp) — pgvector HNSW
- **dense vector** trên `CVChunk.embedding` (đoạn CV) — pgvector HNSW
- **full-text** GIN `to_tsvector('simple', *_norm)` (SQLite dev thì lùi về `icontains`)

Hằng số hiện tại (nâng từ 40 lên 05/09/2026 vì "kho sẽ lớn hơn nhiều, 40 là quá hẹp" — nguyên văn góp
ý chủ dự án):

```
POOL = 60           # số người mang sang ③ (ngân sách đọc-kỹ)
PER_QUERY = 90       # trần mỗi nhánh cho mỗi truy vấn
MIN_POOL = 16
pool_for(): limit × 6, chặn ở POOL — riêng shape="analyze" lấy MIN_POOL (câu tổng hợp không cần đọc kỹ)
```

**Không có bộ lọc so-chuỗi nào phủ quyết kết quả truy hồi** — điểm RRF chỉ để xếp thứ tự đưa vào ③,
③ mới là nơi quyết định ai thoả. Đây là điểm khác biệt cố ý so với bộ chấm điểm cũ (`talent/scoring.py`,
đã thay thế cho đường trả lời chính, xem §6): bộ cũ so chuỗi trên `current_title`/`skills` — các cột
này để trống ở phần lớn hồ sơ thật nên mọi người bị chấm 0 và loại, dù nội dung CV thực sự khớp.

`pinned_ids` (từ `resolve.py` + `structured_match.py`) được ghép lên ĐẦU danh sách trước khi cắt theo
`pool`, với điểm giả cao hơn mọi người truy hồi được — đảm bảo họ luôn được ③ đọc bất kể điểm RRF.

**Che liên hệ tại nguồn**: `clean_passage()` gọi `accounts.privacy.redact_contacts()` trên MỌI đoạn
trước khi đưa vào bằng chứng — đo trên kho thật, 33% đoạn CV chứa email và 25% chứa số điện thoại.
③/⑤ không bao giờ nhìn thấy liên hệ thật, nên "model chép lại số điện thoại từ đoạn nguồn" là một lớp
lỗi không tồn tại được, thay vì phải chặn bằng lời dặn prompt (vốn không đáng tin).

### 2.3. ② phụ — ghim tất định (`resolve.py` + `structured_match.py`)

Hai module riêng, đều tồn tại vì lý do giống nhau: **truy hồi ngữ nghĩa không tất định**, và với hai
loại câu hỏi sau, "lần này ra lần sau rớt" là lỗi chứ không phải nhiễu chấp nhận được.

**`resolve.py`** — ghim theo TÊN RIÊNG. Bóc cụm 2–5 từ trông giống tên người (bắt đầu bằng họ Việt phổ
biến, hoặc mọi từ viết hoa) từ `search_queries`/`information_need`, cộng với người của lượt trước khi
câu hỏi là `compare`/`followup`. Khớp tên đã bỏ dấu, **không** dùng làm định danh mạnh — chỉ để đảm bảo
có mặt trong pool, ③ vẫn là nơi phán đoán.

⚠️ **Hạn chế đã biết**: `named_people()` quét TOÀN BỘ bảng `Person` vào bộ nhớ Python
(`for pid, name in Person.objects.values_list(...)`) mỗi khi câu hỏi có khả năng chứa tên. Ở ~800
người là rẻ; ở quy mô hàng chục nghìn sẽ cần đổi sang truy vấn có điều kiện thay vì tải hết vào RAM.

**`structured_match.py`** — ghim theo `must_have` khớp được TRƯỜNG CÓ CẤU TRÚC (skills, industries,
languages, certifications, city, current_title, current_company, seniority, education_level,
university, major, years_experience). Đây là lớp **lọc tất định trên TOÀN kho** (không chỉ pool 60
người), chạy vài chục mili-giây bằng SQL, KHÔNG LLM. Trần `MAX_STRUCTURED_PINS = 40`.

Nguồn dữ liệu cho ngưỡng số năm KN hợp nhất TỪ HAI NGUỒN (`TalentProfile.years_experience` — cột
Edge/derive — VÀ `ExtractedFact` field="years_experience" — AI mới bóc): bug thật bắt được 05/09,
dùng một nguồn thì "trên 3 năm KN" ra 0 người dù dữ liệu đã có ở nguồn kia.

**Bản chất "ghim", không phải "lọc loại trừ"** — nhắc lại vì dễ hiểu lầm: không khớp được field nào thì
trả về `None`, nhường lại cho truy hồi ngữ nghĩa, KHÔNG loại người ra khỏi kết quả. Lý do: coverage
extraction chưa 100% (§4), dùng làm bộ lọc cứng sẽ đồng nhất "chưa được bóc tách" với "không có thuộc
tính đó" — sai gần hết kho.

⚠️ **Ngoại lệ đã vá 05/09** (xem §8.2 để biết vì sao cần): ngưỡng số năm KN được soi ở CẢ
`should_have`, không chỉ `must_have` — vì đây là phép so sánh số học tất định, không phải "ưu tiên
mềm" như kỹ năng/thành phố nên an toàn để mở rộng. Các trường còn lại (kỹ năng, thành phố, ngành...)
**chưa** có ngoại lệ tương tự — nếu LLM lỡ xếp chúng vào `should_have`, chúng vẫn không được ghim đảm
bảo (xem §8.2).

### 2.4. Hai đường tắt "toàn kho" không qua LLM

**Câu ĐẾM/THỐNG KÊ** (`shape == "count"`) — bỏ hẳn ②③, trả lời bằng `corpus.facts_for_prompt()`:
truy vấn tổng hợp trực tiếp trên `TalentProfile`/`Person` (đếm theo `industries`, `skills`,
`current_title`, phân bố năm kinh nghiệm...), MỖI SỐ LIỆU ĐỀU KÈM ĐỘ PHỦ (`filled/total`). Trường
FACT phủ dưới 5% (`MEANINGFUL_COVERAGE`) thì báo thẳng "chưa đủ để thống kê" thay vì bịa một bảng xếp
hạng gây hiểu nhầm. Có thêm `fts_estimate()` — đếm theo TỪ KHOÁ xuất hiện trong CV text khi trường cấu
trúc rỗng, luôn ghi rõ đây là đếm theo chữ, không phải trường đã bóc tách.

**Cực trị toàn kho** (`superlative.py`, `wants_whole_store()`) — "ứng viên nhiều KN nhất", "lớn tuổi
nhất trong kho". Quét MỌI Person (chưa gộp), bóc thuộc tính bằng LUẬT (không LLM):

- `years_exp`: cột `TalentProfile.years_experience`, thiếu thì ước từ khoảng cách năm sớm nhất tìm
  được trong 4000 ký tự đầu CV tới hiện tại (`_fill_years_from_cv`, chặn ở 45 năm).
- `birth_year` / `age` / `grad_year`: regex trên `Document.best_text` (1500 ký tự đầu CV) —
  **KHÔNG** đọc `ExtractedFact` field `date_of_birth`, vì trường đó trong `intel/field_rules.py` có
  `sensitive=True, auto_accept=False, gate=1.01` — tức KHÔNG BAO GIỜ tự động trở thành fact hiện hành,
  luôn cần người duyệt tay. Đây là lý do kiến trúc, không phải thiếu sót: dữ liệu ngày sinh nhạy cảm
  hơn số năm kinh nghiệm.

Trả về kèm ĐỘ PHỦ (`coverage_have/coverage_total`) và ⑤ được yêu cầu nói đúng kiểu "đã xét K/N hồ sơ
có dữ liệu", không giả vờ đã xét hết N người nếu chỉ K người có giá trị đọc được.

⚠️ **Rủi ro đã biết, tự nhận trong docstring**: đường ước lượng năm KN từ CV text là "lưới đỡ" khi
thiếu dữ liệu cấu trúc, không phải nguồn chính xác — một CV ghi năm không phải mốc bắt đầu sự nghiệp
(ví dụ năm trong địa chỉ, mã số) có thể bị hiểu nhầm. ⑤ luôn ghi "ước tính từ mốc X trong CV" nên
người dùng biết đây là suy luận, không phải dữ kiện chắc chắn — nhưng bản thân con số vẫn có thể sai.

### 2.5. ③ Đọc bằng chứng — `answer/judge.py`

Thay thế hoàn toàn `talent/scoring.py` (so chuỗi trên cột — đã lỗi thời vì cột để trống) cho đường trả
lời chính. Một lượt LLM đọc TỪNG lô 8 hồ sơ (`BATCH = 8`, giữ nhỏ có chủ ý — lô 20 hồ sơ từng khiến
model vượt trần token và trả JSON cụt), 4 lô chạy song song (`WORKERS = 4`). Với mỗi hồ sơ: có thoả
không, trích dẫn nguyên văn đoạn chứng minh, bóc thuộc tính câu hỏi cần.

**Chống bịa hai lớp**:
1. `_verify_quote()` — CODE đối chiếu từng trích dẫn với văn bản gốc đã gửi, cắt dần từ cuối câu để
   giữ "tiền tố dài nhất thật sự có trong nguồn" (bản trước chỉ khớp nửa đầu rồi lưu cả chuỗi — để lọt
   4/18 trích dẫn có phần đuôi bịa, đã đo trên kho thật).
2. `_is_estimate()` — giá trị bóc được có dấu hiệu phỏng đoán ("ước tính", "khoảng", dấu `~`/`?`, hoặc
   dạng khoảng năm "1993-1995") thì bị loại khỏi `extracted`, KHÔNG đưa vào ④ để sắp xếp — vì ④ sắp
   xếp trên đúng con số đó, một ước lượng lọt vào là để phỏng đoán quyết định thứ hạng người dùng thấy.

`JudgeReport.broken` phân biệt "đọc xong, không ai thoả" (kho thật sự không có) với "không đọc được"
(lỗi kỹ thuật — tất cả các lô đều hỏng) — nhầm hai cái là nguồn gốc của lỗi "kho không có ai" giả trong
khi ② đã tìm được 40-60 hồ sơ.

### 2.6. ④ Sắp xếp — `answer/aggregate.py`

CODE thuần, tất định — không LLM. Lọc theo `CONFIDENCE_FLOOR = 0.35`, sắp theo `sort_by` nếu có (tuổi
quy về năm sinh để so sánh cùng thang với "sinh năm mấy"), cắt theo `limit`. Người thiếu giá trị để
sắp bị đẩy XUỐNG CUỐI chứ không lẫn vào giữa — và `stats["missing_sort_value"]` để ⑤ nói rõ bao nhiêu
người không xác định được.

`enough()` quyết định có cần `plan.widen()` rồi chạy lại ②③④ không: không ai thoả nhưng ĐÃ đọc ≥15 hồ
sơ thì coi là kho thật sự không có, không nới thêm (nới nữa chỉ moi thêm hồ sơ lạc đề).

### 2.7. Cache — `answer/cache.py`

Cache ở ranh giới ②③④ (không cache ⑤, vì ⑤ phụ thuộc lịch sử hội thoại). Lý do: đo trên kho thật, ③
chiếm 75% trong ~38.700 token một lượt — hỏi lại đúng câu là trả toàn bộ số đó. Khoá gồm câu hỏi gốc
(không phải `QueryPlan` — các trường đó do LLM viết lại, đổi câu chữ giữa hai lượt hỏi giống hệt
nhau), người hỏi, **vân tay kho** (đếm + mốc thời gian mới nhất của `PersonSearchDocument`/`CVChunk`
— thêm hồ sơ mới là mọi mục cache cũ tự hết hiệu lực), và dấu ngữ cảnh (danh sách người lượt trước).
TTL 6 giờ.

⚠️ Vân tay kho tính hỏng (tên cột sai, lỗi DB) thì rơi vào `except` và tắt cache **im lặng** — mọi thứ
vẫn chạy đúng, chỉ đắt gấp đôi, không có cảnh báo chủ động nào ngoài log. Đã từng xảy ra thật (ghi lại
trong chính docstring của file).

### 2.8. ⑤ Viết câu trả lời — `answer/compose.py`

Model **không tìm, không xếp hạng, không đếm** — nhận `chosen` đã chốt và CHỈ diễn đạt. `MAX_TOKENS`
lịch sử đã bị cắt giữa chữ vì phần suy nghĩ nội bộ của model chiếm hết ngân sách token (bug đã sửa:
`reasoning_effort="none"` + nâng trần); đường stream dùng `STREAM_MAX_TOKENS = 7000` ngay từ đầu vì
không gọi lại được khi đã phát ra màn hình.

Đánh số nguồn `[n]` là trích dẫn ĐÃ KIỂM CHỨNG (từ ③), không phải đoạn thô. `used_sources()` gỡ mọi số
`[n]` không hợp lệ khỏi văn bản thay vì để trích dẫn trỏ vào hư vô.

Có bản dự phòng CODE thuần (`fallback_text()`) khi model lỗi hoàn toàn hoặc trả rỗng — phân biệt rõ
các tình huống: đọc lỗi kỹ thuật / câu đếm-thống kê / tra theo tên không có / không tìm được ai.

### 2.9. Vòng tự sửa — `answer/verify.py`

Ba phép kiểm TẤT ĐỊNH (không LLM chấm LLM) đối chiếu văn bản với `chosen`: thứ tự trình bày có khớp
thứ tự đã sắp không, số người được nhắc có vượt `limit` không, nêu tên mà không có `[n]` nào không.
Có lỗi thì sửa **đúng một lần** (`_repair`) — không lặp vòng, vì lỗi thứ hai model có thể không sửa
nổi và bản cũ dù lệch vẫn còn dùng được hơn là trắng.

### 2.10. Nhánh không cần tìm kho

- **`chat.py`** — câu không liên quan Kho con người: câu có sẵn (`common_answer`, không tốn token) →
  tra web (`websearch.web_answer`, chạy trên **SearXNG tự host** — `msbradar-searxng` trong
  docker-compose, không phải API trả phí theo lượt) → hội thoại thường. `_do_web()` mặc định thử tra
  web cho MỌI câu ≥2 từ khi đã rơi vào nhánh này và websearch đang bật — theo yêu cầu cụ thể 05/09
  ("Tổng giám đốc MSB là ai" phải tra được, không trả lời rỗng). Có bơm số liệu thật về kho
  (`corpus.facts_for_prompt()`) khi câu hỏi có dính từ khoá về kho, để tránh Radar nói "tôi không có
  dữ liệu" trong khi kho có hàng trăm hồ sơ.
- **`act.py`** — mệnh lệnh ("soạn thư cho 3 người đầu", "nhớ giúp tôi..."): nối vào vòng lặp tool có
  sẵn của `ai/agent.py` (8 tool, đã bật production, lọc RBAC qua `ai/toolset.py`). Tool ở đây CHỈ ĐỌC
  hoặc CHỈ ĐỀ XUẤT — không gửi thư, không đăng gì, không sửa hồ sơ thật.
- **`_stream_assess_doc`** (trong `engine.py`) — có tệp đính kèm + câu hỏi kiểu "đánh giá CV này": đọc
  THẲNG nội dung đính kèm, KHÔNG tra kho. Có kiểm trùng tên với kho (`_name_twin_in_store`) để nhắc
  người dùng đối chiếu, không tự động gộp.

---

## 3. Trải nghiệm hỏi–đáp (những gì người dùng thấy)

- **Preamble tức thì** (`engine._preamble`) — ngay sau ① (trước ②③ tốn thời gian nhất), một câu ghép
  từ chính `QueryPlan` (không gọi thêm LLM): "Mình hiểu bạn cần: X. Cách làm: ...". Xác nhận hoạt động
  đúng trên production §8.
- **Các bước hiển thị** (`_step()`) thay vì đổ token suy nghĩ ra màn hình — SSE `event: step` với nhãn
  tiếng Việt ngắn ("Tìm trong kho", "Đọc hồ sơ", "Viết câu trả lời"...). Suy nghĩ nội bộ của model vẫn
  được GOM vào `trace` để soi lỗi, nhưng không phát ra client.
- **Sống sót khi mất kết nối di động** (`runner.py`) — engine chạy trong luồng nền riêng, client rớt
  kết nối (chuyển tab/app trên mobile → OS huỷ `fetch`) không dừng luồng sinh; kết quả đầy đủ vẫn được
  lưu. `GET /api/v1/talent/ask/turn/<client_turn_id>/` để lấy lại khi mở lại tab. **Chỉ hoạt động trên
  PostgreSQL** (`_threaded_ok()` kiểm `connection.vendor != "sqlite"`) — SQLite (dev nhỏ) lùi về chạy
  trực tiếp trong luồng request.

---

## 4. Tầng nuôi dữ liệu — dữ liệu vào kho phải được gán nhãn tự động

### 4.1. Kiến trúc "fact có nguồn" — `intel/models.py`, `intel/field_rules.py`

AI không ghi trực tiếp vào trường chính. Mỗi giá trị là một `ExtractedFact`: `field`, `raw_value`,
`normalized_value`, `canonical_code`, `confidence`, `source_kind` (edge/cv_text/ai/manual),
`status` (proposed/accepted/rejected/conflict), `is_current`. `FIELD_RULES` định nghĩa theo TỪNG
trường: `mode` (latest — bản mới nhất thắng; merge — mọi giá trị accepted đều hiện hành, dùng cho
skills/industries/languages/certifications/achievements), `sensitive`, `auto_accept`, `gate`
(ngưỡng confidence).

24 trường hiện có (05/09/2026): định danh (full_name, email, phone, gender, date_of_birth), địa lý
(city, current_address, location_interest), kinh nghiệm (current_title, current_company, seniority,
years_experience, experience_summary), học vấn (education_level, university, major, graduation_year,
**gpa** — mới thêm 05/09), năng lực (skills, industries, languages, certifications, **achievements** —
mới thêm 05/09), nhu cầu (expected_salary, notice_period), tuyển dụng (applied_position, applied_date,
source).

### 4.2. Pipeline Edge-first + AI-fill-gaps — `intel/extraction.py`

```
1. Đọc SourceRecord mới nhất trước → ánh xạ field Edge → fact (source_kind=edge), KHÔNG gọi AI
2. Đọc Document.best_text (KHÔNG parsing lại)
3. Field còn thiếu = (KNOWN_FIELDS ∩ AI_FILLABLE) − (đã có từ Edge/fact hiện có)
4. MỘT lượt gọi AI (nếu có text + có field thiếu): chỉ gửi phần thiếu, không hỏi lại field đã có
5. Validate → chuẩn hoá (Canonical Registry) → ghi fact
6. Auto-accept theo gate/auto_accept; còn lại vào ReviewItem
```

`ExtractionJob` (`intel/queue.py`) — hàng đợi DB-backed, có lease/claim/retry/idempotency, worker
riêng (`run_extraction_worker`, container `msbradar-extraction-worker`, `restart: unless-stopped`,
độc lập với request HTTP). `INTEL_AUTO_ENQUEUE_EXTRACTION=1` trên production — mọi Person qua
`people/ingest.py::resolve_record` (Edge sync, nhập tay, batch import — MỘT điểm chốt duy nhất) đều
tự động vào hàng đợi.

**Bẫy đã bắt và sửa 05/09** (đã xảy ra thật, không phải giả định): `_ai_extract()` thiếu
`reasoning_effort="none"` khiến model GreenNode/qwen "nghĩ" hết ngân sách token thay vì viết JSON —
đo được 40s/lượt, ~50% JSON hỏng. Sau khi sửa: 6-7s/lượt, JSON hợp lệ ổn định. **Đây là lỗi đã gặp
LẶP LẠI nhiều lần trong cùng một dự án** (cv_parsing, candidate_extraction, assistant_conversation) —
nếu thêm tác vụ LLM mới, kiểm tham số này trước tiên.

### 4.3. Đồng bộ với template CV nền tảng ngoài — `intake/fields.py`

37 cột (từ 33), đối chiếu với template CSV 23 cột của một nền tảng phân tích CV khác (chủ dự án cung
cấp 05/09) để hai bên "ăn khớp" — cùng khái niệm thì import thẳng, không map tay. 19/23 cột khớp qua
alias sẵn có; 4 mapping mới đóng nốt (Tên ứng viên, Kinh nghiệm, Tên file gốc + 3 cột thật sự mới:
`birth_date` khác `birth_year`, `applied_region` khác `city`, `external_assessment` — phán đoán có
sẵn từ nguồn ngoài, KHÔNG nằm trong `field_rules.py` vì đó là nhận định đã thành hình, không phải dữ
kiện quan sát được).

`intake/export.py` (mới 05/09) — `GET /api/v1/intake/export.csv`: xuất CSV toàn kho đúng cột trên,
đọc `ExtractedFact` đã duyệt trước, `TalentProfile` sau. Che `email`/`phone` bằng
`accounts.privacy.mask_email/mask_phone` — theo đúng quy ước export sẵn có
(`talent/views.py::talent_search_export`), không có tham số nào bật lại bản thô.

### 4.4. Backfill 05/09/2026 (số liệu thật, đo trên production)

Sau khi thêm `gpa`/`achievements` vào `_AI_FILLABLE`, enqueue lại toàn bộ 798 người
(`intel.queue.enqueue_many`) để hồ sơ ĐÃ xử lý trước đó cũng được bóc lại hai trường mới (pipeline chỉ
hỏi AI về field CÒN THIẾU nên không tốn token cho field đã có). Kết quả sau khi hàng đợi rút hết
(798/798 `done`, 0 `failed`): **GPA lấp đầy 72/798 người, Thành tích 96/798 người**. Đây là con số
THẬT phản ánh bao nhiêu CV thực sự có ghi các thông tin này — không phải lỗi coverage.

### 4.5. Bức tranh coverage hiện tại (không tô hồng)

| Trường | Nguồn | Coverage đo được | Ghi chú |
|---|---|---|---|
| `years_experience` | `TalentProfile` ∪ `ExtractedFact` | ~378/798 (~47%, đo trước backfill 05/09) | Dùng trong cực trị VÀ ghim cấu trúc |
| `birth_year` (qua CV text, không qua fact) | regex `superlative.py` | ~235/798 (~29%) | KHÔNG đọc `ExtractedFact.date_of_birth` (xem §2.4 — lý do kiến trúc) |
| `gpa` | `ExtractedFact` (mới 05/09) | 72/798 (~9%) | Sau 1 lượt backfill toàn kho |
| `achievements` | `ExtractedFact` (mới 05/09) | 96/798 (~12%) | Sau 1 lượt backfill toàn kho |
| `birth_date`, `applied_region`, `external_assessment` | — | **0%, không có nguồn tự động** | Chỉ vào được qua nhập tay hoặc import từ nền tảng ngoài — xem §8.5 |

Nguyên tắc xử lý coverage thấp trong toàn hệ thống: KHÔNG suy đoán khi thiếu, LUÔN báo độ phủ kèm số
liệu (không có con số trần trụi đứng một mình), và "ghim" (đảm bảo có mặt) thay vì "lọc" (loại trừ) ở
mọi chỗ dữ liệu cấu trúc chưa phủ hết kho.

---

## 5. Hạ tầng phục vụ và chỉ mục tìm kiếm

- ASGI (`gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker`) — không còn sync WSGI
  worker chặn SSE.
- `runner.py` — luồng nền cho mỗi lượt hỏi khi PostgreSQL (§3). **Chưa có trần số luồng đồng thời** —
  mỗi lượt hỏi = một `threading.Thread` mới, không có semaphore/pool giới hạn trong code hiện tại; xem
  rủi ro ở §8.7.
- `HARD_DEADLINE = 150s` cho một luồng sinh; `BUDGET_SECONDS = 15s` (mềm) cho vòng nới trong
  `engine.py` — vượt thì bỏ vòng nới chứ không cắt ngang chặng đang chạy.
- pgvector HNSW cho `PersonSearchDocument.embedding` và `CVChunk.embedding`; GIN full-text
  `to_tsvector('simple', *_norm)` trên `text_norm`/`content_norm` (bỏ dấu ở tầng LƯU TRỮ, không phải
  tầng truy vấn — nhờ vậy "ngan hang" khớp "Ngân Hàng" bằng index scan, không cần extension
  `unaccent`). `corpus_qa.py`/`vector_index.py` dùng chung một hàm `fold_text()`.
- Cột `embedding` để **biến chiều** (không cố định) — đổi model embedding không cần migration; HNSW
  bắt buộc chiều cố định nên sau khi backfill xong bằng một model, chạy `pin_vector_dimensions --apply`
  để chốt.
- `embedding_fingerprint` khác `fingerprint` của bản ghi ⇒ vector cũ/chưa có — hàng đợi embedding
  chính là bảng projection, không cần bảng job riêng, chạy lại an toàn (`embed_talent_index --loop`).

### 5.1. Cấu hình vận hành hiện có

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `TALENT_INDEX_ON_SAVE` | `1` | Lập chỉ mục ngay khi lưu hồ sơ/tài liệu. Đặt `0` khi nạp hàng loạt rồi chạy `rebuild_talent_vector_index` |
| `MSB_AI_CONFIG_TTL_SECONDS` | `5` | Chu kỳ router soi dấu thời gian cấu hình DB để tự làm mới cache xuyên worker gunicorn |

⚠️ **Cấu hình chết, đã xác minh** (05/09/2026): `config/settings.py` còn khai báo
`TALENT_AI_NATIVE_SEARCH`, `TALENT_SCORE_FLOOR`, `TALENT_AI_RERANK_POOL`, `TALENT_AI_RERANK_CV_CHARS`
— nhưng grep toàn bộ `server/` không thấy nơi nào ĐỌC các biến này nữa (không `getattr(settings,
"TALENT_AI_RERANK_POOL"...)` ở đâu cả). Đây là tàn dư của `talent/ai_rank.py` — module đọc chúng —
đã bị xoá khi Answer Engine thay thế hoàn toàn đường tìm kiếm cũ (xem §7). Không gây hại (không ai
đọc = không ảnh hưởng hành vi), nhưng gây nhầm lẫn thật cho người đọc `settings.py` sau này tưởng
chúng vẫn có tác dụng. **Đề xuất**: dọn khỏi `settings.py` trong một commit dọn dẹp riêng.

### 5.2. Lệnh vận hành chỉ mục tìm kiếm

```bash
# Chẩn đoán + chọn model embedding
docker compose exec hub python manage.py setup_corpus_qa
docker compose exec hub python manage.py setup_corpus_qa --list-models
docker compose exec hub python manage.py setup_corpus_qa --provider greennode --model <mã-model> --apply

# Dựng projection + đoạn CV cho toàn kho (không gọi mạng)
docker compose exec hub python manage.py rebuild_talent_vector_index --stale

# Tính vector ở nền (chạy lại an toàn, dừng bằng --stop-file)
docker compose exec hub python manage.py embed_talent_index --loop

# Chốt chiều + tạo HNSW khi đã backfill xong
docker compose exec hub python manage.py pin_vector_dimensions --apply

# Đo chất lượng hỏi-đáp có dẫn chứng trước khi tin
docker compose exec hub python manage.py corpus_qa_eval --file cauhoi.json
```

Nạp hàng loạt (import lớn): đặt `TALENT_INDEX_ON_SAVE=0`, rồi chạy `rebuild_talent_vector_index` +
`embed_talent_index` một lượt sau khi nạp xong — tránh lập chỉ mục lặp lại theo từng lượt lưu.

---

## 6. Lịch sử thay thế — Answer Engine đã XOÁ hẳn đường tìm kiếm cũ, không chạy song song

Trước 03/09/2026, tìm kiếm AI đi qua `talent/ai_search.py` (orchestrator) + `talent/ai_rank.py`
(dossier + một lượt LLM chọn/xếp hạng, không tách bạch đọc-bằng-chứng/sắp-xếp/viết) +
`talent/hiring_need.py` (bóc câu hỏi thành một schema 11 khoá cố định: `skills, title, location,
company, min_years, max_years, has_email, has_phone, text, product, lead_status`) + `talent/scoring.py`
(chấm điểm so chuỗi trên cột cấu trúc). Bản kế hoạch gốc của đợt thay thế này nằm ở
**`docs/RADAR_ANSWER_ENGINE.md`** (03/09/2026) — ghi lại rất cụ thể ba lỗi thật đo trên production
khiến schema cứng này bị bỏ hẳn (ví dụ: "tìm ứng viên quan hệ khách hàng" bị dịch thành
"Customer Relationship" rồi 0 CV nào chứa chuỗi đó → 0 hồ sơ, dù dense retrieval tìm đúng ngay).

**Đã xác minh 05/09/2026, những gì thực sự bị xoá khỏi đường trả lời:**

| Module cũ | Tình trạng hiện tại |
|---|---|
| `talent/ai_search.py` | **Đã xoá khỏi repo.** |
| `talent/analysis_cache.py` | **Đã xoá khỏi repo.** |
| `talent/ai_rank.py` | **Đã xoá khỏi repo.** |
| Endpoint `/talent/ai-search/` | **Đã gỡ** (ghi rõ trong comment `talent/urls.py`) |
| `talent/hiring_need.py` | Còn tồn tại trong repo — theo kế hoạch gốc là vì `hiring/jd.py` còn phụ thuộc, **không** phải vì còn dùng cho đường trả lời tìm kiếm |
| `talent/scoring.py` | Còn tồn tại — dùng cho `hiring/calibration.py` (hiệu chỉnh trọng số từ phản hồi recruiter), **đã gỡ khỏi đường trả lời** (xem §2.2) |
| `talent/search.py` | Còn tồn tại và còn dùng thật — nhưng nay là **công cụ lọc SQL/Boolean search** cho các view danh sách/xuất dữ liệu không dùng AI (ví dụ `talent_search_export`), **không phải** một đường AI-ranking song song với Answer Engine |
| `talent/semantic.py`, `talent/semantic_index.py`, `TitleSimilarity`, `TalentSemanticIndex` | Còn tồn tại trong repo dù kế hoạch gốc ghi "xoá" — dọn dẹp chưa hoàn tất, không nằm trong đường trả lời `answer/` (không có import nào từ `answer/` tới các module này) |

**Kết luận quan trọng cho tài liệu này**: KHÔNG có "hai đường AI tìm kiếm song song" trên production.
`/api/v1/talent/ask/` (Answer Engine, §2) là đường DUY NHẤT xử lý câu hỏi tìm/phân tích ứng viên bằng
AI. `talent/search.py` vẫn sống nhưng phục vụ một việc khác hẳn (lọc/liệt kê/xuất dữ liệu không cần
LLM).

### 6.1. `talent/corpus_qa.py` — còn trong repo nhưng đã mồ côi khỏi đường trả lời sống

Module này (hỏi-đáp có dẫn chứng kiểu NotebookLM: `retrieve()` hybrid dense+lexical, `answer()` chỉ
trả lời từ nguồn đánh số) từng là "hạt giống" cho Answer Engine theo đúng ghi chép ở
`docs/RADAR_AI_MASTER_PLAN.md` bản trước (mục §24.4, nay đã thay bằng tài liệu này). Xác minh
05/09/2026: grep toàn bộ `server/talent/` cho thấy `answer_views.py` (view sống duy nhất còn import
module này) **chỉ dùng đúng một hàm** — `corpus_qa.can_read_cv()` (permission check RM-không-được-đọc-
CV, dùng chung ở §2 nhánh vào của Answer Engine). Các hàm cốt lõi (`answer()`, `retrieve()`,
`as_reply()`, `looks_like_corpus_question()`) **không còn được gọi từ bất kỳ view sống nào** — chỉ còn
xuất hiện trong `tests_corpus_qa.py` và lệnh `corpus_qa_eval`. Chức năng "hỏi-đáp tổng hợp có dẫn
chứng" mà module này từng cung cấp nay do chính nhánh `shape in ("analyze", "count")` của
`answer/engine.py` đảm nhiệm (§2.4, dùng `answer/corpus.py` — khác file, tên dễ nhầm với
`corpus_qa.py`).

**Đề xuất**: hoặc xoá hẳn phần thân `corpus_qa.py` không còn dùng (giữ lại `can_read_cv`, chuyển sang
một module permission dùng chung), hoặc nếu vẫn muốn giữ làm phương án dự phòng thì ghi rõ trong chính
file đó rằng nó đã mồ côi — tránh người đọc sau này tưởng đây vẫn là đường xử lý câu hỏi phân tích kho
đang chạy thật.

---

## 7. Đã xác minh trên production (bằng chứng cụ thể, không phải "chạy được ở local")

Phương pháp kiểm: SSH vào VPS (`ubuntu@161.118.203.171`), `docker exec -i msbradar-hub python
manage.py shell`, dùng `django.test.Client(SERVER_NAME="radar.tunghr.io.vn")` +
`force_login(User.objects.get(pk=1))` để gọi THẲNG `/api/v1/talent/ask/` — đường HTTP thật (middleware,
permission, URL routing thật), dữ liệu thật, không cần mật khẩu. Đây là cách kiểm khuyến nghị cho mọi
thay đổi sau này (xem §9).

| Tính năng | Cách kiểm | Kết quả đo được (05/09/2026) |
|---|---|---|
| Cực trị toàn kho | Hỏi "ai nhiều năm KN nhất trong kho" | `trace.fast_path = "cực trị toàn kho theo 'years_exp'"`; trả lời đúng người, tự nêu "đã xét 378/798 hồ sơ có dữ liệu" |
| Ghim cấu trúc (must_have) | Hỏi "tìm ứng viên trên 3 năm KN ngành ngân hàng" | Trước bản vá §7.2: `structured_pins=None` (lỗi thật, xem dưới). Sau vá: `structured_pins=40` |
| Tra web ngoài kho | Hỏi "Tổng giám đốc MSB hiện tại là ai?" | Trả lời đúng, có FACT/INFERENCE, không còn "không có nội dung" |
| Preamble + step streaming | Gửi `stream=true`, đọc SSE thật (`event:`/`data:`) | Thứ tự event đúng: `step, step, preamble, step, step, answer×N, citations, done` |
| Export CSV + backfill | `GET /api/v1/intake/export.csv` | 798 dòng, cột đúng `fields.py`; GPA/Thành tích tăng dần đúng theo tiến độ hàng đợi (45→72, 55→96) |
| Resume endpoint | `GET /api/v1/talent/ask/turn/<id-không-tồn-tại>/` | 404 đúng như kỳ vọng |

### 7.2. Lỗi thật bắt được VÀ ĐÃ SỬA trong quá trình kiểm (05/09/2026)

Hỏi đúng câu **"tìm ứng viên trên 3 năm kinh nghiệm ngành ngân hàng"** (có dấu, đúng cách một người
dùng thật gõ) — `structured_pins` trả về `None`. Kiểm sâu: `plan.plan()` (LLM, được dặn `must_have`
"Rất ít") có LƯỢT xếp cụm "trên 3 năm kinh nghiệm" vào `should_have` thay vì `must_have`. Vì
`structured_match.must_have_pins()` khi đó CHỈ đọc `must_have`, việc ghim toàn kho bị vô hiệu hoá ÂM
THẦM — quay lại đúng vấn đề gốc mà tính năng này được dựng ra để giải quyết (chỉ đọc trong pool ~60
người truy hồi ngữ nghĩa, không đảm bảo rà toàn kho).

Đã sửa (`structured_match.py`, commit `ba0afd9`): ngưỡng số năm KN được soi thêm ở `should_have`, vì
đây là phép so sánh số học tất định (không phụ thuộc việc LLM coi nó "bắt buộc" hay "ưu tiên" —
kết quả đúng/sai không đổi). Kiểm lại đúng câu hỏi trên production sau khi triển khai:
`structured_pins` từ `None` → **40**. Xem §8.2 để biết phần CHƯA tổng quát hoá của bản vá này.

---

## 8. Chưa tối ưu / rủi ro còn treo (xếp theo mức ưu tiên đề xuất)

### 8.1. [Cao] Trần ghim cấu trúc 40 người không có lối thoát khi vượt trần

`MAX_STRUCTURED_PINS = 40` — câu hỏi khớp cấu trúc với hàng trăm người (ví dụ kho đã backfill xong,
"biết tiếng Anh" khớp đa số) thì vẫn chỉ 40 người đầu (theo `pk`) lọt vào ③. Khác với cực trị
(`superlative.py`, quét thật 100% rồi mới cắt), đường ghim cấu trúc CẮT TRƯỚC khi ③ kịp đọc.
**Đề xuất**: khi số khớp vượt trần rõ rệt (ví dụ >200), coi đây là tín hiệu nên chuyển sang một dạng
"cực trị/liệt kê toàn kho theo điều kiện cấu trúc" tương tự `superlative.py`, thay vì lặng lẽ cắt.

### 8.2. [Cao] Bản vá should_have (§7.2) mới đúng cho MỘT loại tiêu chí

Ngoại lệ should_have chỉ áp cho ngưỡng số năm kinh nghiệm. Nếu LLM xếp một tiêu chí cứng khác (ví dụ
"ở Hà Nội", "có chứng chỉ CFA", "ngành ngân hàng" khi đứng riêng không kèm số năm) vào `should_have`
thay vì `must_have`, lỗ hổng y hệt §7.2 vẫn còn — CHƯA kiểm tra được các trường này có bị ảnh hưởng
với tần suất nào trên production thật (chỉ mới bắt được trường hợp số năm KN vì đó là câu hỏi cụ thể
được test). **Đề xuất**: đo tần suất must_have/should_have lệch cho từng loại trường bằng cách log
`trace.plan` của các lượt hỏi thật trong 1-2 tuần, rồi quyết định có cần mở rộng ngoại lệ sang các
trường tất định khác (city, industry — vốn cũng so khớp CHÍNH XÁC một giá trị, không mờ như "kỹ năng
mềm") hay không.

### 8.3. [Trung bình] Hai chỗ quét toàn bảng `Person` vào bộ nhớ mỗi lượt hỏi

`resolve.py::named_people()` và `structured_match.py::must_have_pins()` đều load toàn bộ
`Person.objects.values_list(...)` (id + tên, hoặc chỉ id) vào một `list`/`dict` Python mỗi lần có thể
áp dụng. Ở ~800 người là vài chục mili-giây, không đáng lo. Sẽ cần đổi sang truy vấn có điều kiện
(hoặc cache trong tiến trình, invalidate theo vân tay kho như `cache.py` đã làm) khi kho tăng lên
hàng chục nghìn người — CHƯA có ngưỡng cụ thể nào được đặt ra để biết khi nào cần làm việc này.

### 8.4. [Trung bình] Ước lượng năm KN/năm sinh bằng regex khi thiếu dữ liệu cấu trúc

`superlative._fill_years_from_cv()` lấy năm nhỏ nhất tìm được trong 4000 ký tự đầu CV (khoảng
1980–hiện tại) làm mốc bắt đầu sự nghiệp — có thể trúng nhầm một năm không liên quan (địa chỉ, mã số,
năm sinh của người khác được nhắc trong CV). Tự nhận là "ước tính" trong câu trả lời (trung thực với
người dùng) nhưng bản thân số liệu vẫn có thể sai và ảnh hưởng thứ hạng cực trị. **Đường tốt hơn**:
mở rộng `_AI_FILLABLE` cho một trường "năm bắt đầu đi làm" tường minh, để AI đọc CÓ NGỮ CẢNH thay vì
regex đọc mù — nhưng đây là việc tốn thêm một lượt trích xuất, chưa làm.

### 8.5. [Trung bình] Ba trường mới trong template chưa có nguồn tự động nào

`birth_date`, `applied_region`, `external_assessment` (thêm vào `intake/fields.py` 05/09 để khớp
template ngoài) hiện **luôn rỗng** trong `export.csv` trừ khi nhập tay hoặc nhận từ import CSV của nền
tảng ngoài — không có AI-fill, không có ánh xạ từ Edge. Đây là thiết kế có chủ ý cho
`external_assessment` (là phán đoán, không phải fact — không nên tự động), nhưng với `birth_date` và
`applied_region` thì chỉ đơn giản là CHƯA làm, không phải không nên làm.

### 8.6. [Thấp] `export.csv` dựng cả file trong bộ nhớ trước khi trả

`intake/export.py::export_candidates()` dùng `HttpResponse` thường (không streaming) — ở 798 dòng vô
hại. Sẽ cần đổi sang `StreamingHttpResponse` nếu kho phình lên hàng chục nghìn người, để tránh giữ cả
file CSV trong RAM của tiến trình Django.

### 8.7. [Thấp, cần theo dõi] `runner.py` không có trần số luồng nền đồng thời

Mỗi lượt hỏi (khi PostgreSQL) sinh một `threading.Thread` riêng, không qua pool/semaphore giới hạn.
Ở tải hiện tại (một VPS, số người dùng nội bộ) chưa gây vấn đề quan sát được, nhưng chưa có cơ chế nào
chặn kịch bản nhiều người hỏi câu `deep` cùng lúc làm phình số luồng — đáng đặt một trần mềm (ví dụ
`ThreadPoolExecutor` thay vì `Thread` trần) nếu số người dùng đồng thời tăng.

### 8.8. [Thấp] Vòng tự sửa (`verify.py`) chỉ chạy một lần

Nếu bản viết lại sau `_repair()` vẫn mắc đúng lỗi cũ (thứ tự/số lượng/thiếu nguồn), không có lượt thứ
hai — chấp nhận đánh đổi vì lý do độ trễ, nhưng nghĩa là lưới chống-bịa không phải tuyệt đối. Chưa có
số liệu về tần suất lỗi vẫn còn sau một lần sửa.

### 8.9. [Thấp, dọn dẹp] Tàn dư code/config của đường tìm kiếm đã bị thay thế

Xem §6 — `talent/corpus_qa.py` còn thân hàm mồ côi (`answer()`, `retrieve()`, `as_reply()`,
`looks_like_corpus_question()` không còn view sống nào gọi), và `settings.py` còn 4 biến cấu hình chết
(`TALENT_AI_NATIVE_SEARCH`, `TALENT_SCORE_FLOOR`, `TALENT_AI_RERANK_POOL`,
`TALENT_AI_RERANK_CV_CHARS` — xem §5.1). Không ảnh hưởng hành vi runtime, nhưng làm tài liệu/code khó
đọc đúng cho người tới sau — dễ nhầm "còn dùng" thành "đang dùng thật".

### 8.10. [Ghi nhận, không phải lỗi] Không có lọc quyền theo DÒNG dữ liệu ở tầng truy hồi

`cache.py` tự ghi rõ: "② hôm nay KHÔNG lọc theo quyền... Ai vào được Talent thì thấy cùng một kho."
Phân quyền hiện tại là cấp MODULE (`roles.can_access` — vào được phòng nào), không phải cấp DÒNG (thấy
được hồ sơ nào). Chiều theo-người-dùng duy nhất là hạn mức mở khoá liên hệ
(`accounts.privacy.unlock`). Đây là thiết kế đã biết và chấp nhận, không phải một lỗ hổng mới phát
hiện — ghi lại ở đây để không ai nhầm tưởng đã có row-level security.

---

## 9. Cách tự kiểm chứng trên production (playbook)

Không tin vào "chạy được ở máy dev" hay "test xanh hết" là đủ — nhiều lỗi trong tài liệu này CHỈ lộ ra
khi kiểm bằng dữ liệu thật trên production (ví dụ §7.2, và trước đó là bug `Document.parsed_text`
rỗng toàn bộ mà test cục bộ không bắt được vì fixture vô tình né đúng đường hỏng).

```bash
# 1. SSH vào VPS
ssh -i ~/.ssh/id_oracle_core.key ubuntu@161.118.203.171

# 2. Chạy Django shell BÊN TRONG container hub (dữ liệu thật, code thật đang chạy)
docker exec -i msbradar-hub python manage.py shell
```

```python
import json
from django.contrib.auth.models import User
from django.test import Client

user = User.objects.get(pk=1)                              # tài khoản có quyền đọc CV
client = Client(SERVER_NAME="radar.tunghr.io.vn")           # PHẢI khớp ALLOWED_HOSTS
client.force_login(user)                                    # không cần mật khẩu

resp = client.post("/api/v1/talent/ask/",
                    data=json.dumps({"q": "<câu hỏi thật>", "stream": False}),
                    content_type="application/json")
data = resp.json()
print(data["trace"])          # fast_path / structured_pins / pinned_ids nói ĐÚNG đường nào đã chạy
print(data["answer"][:300])
```

Đọc `trace` để biết SỰ THẬT đã xảy ra, không đoán qua văn bản câu trả lời — câu trả lời có thể vẫn
"nghe hợp lý" ngay cả khi đường đảm bảo toàn kho đã âm thầm không chạy (đúng như §7.2).

Với đường SSE (`stream=true`), đọc `resp.streaming_content`, tách theo block `event: <tên>\ndata:
<json>\n\n` — KHÔNG giả định `type` nằm trong JSON, tên sự kiện nằm ở dòng `event:` riêng.

---

## 10. Việc tiếp theo đề xuất (không phải cam kết, chỉ là gợi ý ưu tiên)

1. Đo tần suất must_have/should_have bị LLM xếp lệch trên câu hỏi thật (§8.2) trước khi quyết định mở
   rộng ngoại lệ should_have sang thêm trường nào.
2. Xử lý trần 40 khi số khớp cấu trúc vượt xa (§8.1) — nguy cơ cao nhất còn lại đối với đúng mục tiêu
   "rà soát toàn kho" mà toàn bộ nỗ lực 04-05/09 hướng tới.
3. Backfill `birth_date`/`applied_region` nếu có nguồn (Edge, hoặc suy từ `date_of_birth`/`city` đã có)
   — hiện đang rỗng 100% một cách không cần thiết cho `applied_region` nếu Edge có dữ liệu tương đương
   chưa được ánh xạ.
4. Đặt ngưỡng cụ thể (số Person) để biết khi nào §8.3 (quét toàn bảng vào RAM) thật sự cần sửa, tránh
   tối ưu sớm một chỗ chưa phải nút thắt.
5. Dọn tàn dư đường tìm kiếm cũ (§8.9) — xoá thân hàm mồ côi trong `corpus_qa.py`, dọn 4 biến cấu hình
   chết trong `settings.py` — việc nhỏ, rủi ro thấp, giúp tài liệu/code khớp nhau cho người đọc sau.
