# Kế hoạch: nhanh hơn, hiện bước, không rớt khi chuyển tab

Ngày 05/09/2026. Ba yêu cầu độc lập, làm được song song.

---

## 1. Song song hoá — "làm nhiều bước cùng lúc rồi tổng hợp"

### Đã song song sẵn (không phải làm lại)

| Chặng | Trạng thái |
|---|---|
| ② truy hồi — nhánh vector | **đã song song** (`ThreadPoolExecutor`, 4 worker) |
| ③ đọc CV — các lô | **đã song song** (`ThreadPoolExecutor`, `WORKERS`) |
| ⑤ viết | **đã stream** — người dùng đọc dần, không chờ hết |
| nhiều nhánh truy hồi → RRF | **đây đã là "làm nhiều rồi tổng hợp"** |

Chuỗi còn tuần tự là ① → ② → ③ → ⑤, và đó là phụ thuộc dữ liệu thật: ② cần
`search_queries` của ①, ③ cần người của ②, ⑤ cần danh sách cuối của ④.

### Bốn chỗ chèn được song song

**1a. Truy hồi ĐOÁN TRƯỚC trong lúc ① chạy.** Ngay khi nhận request, chạy FTS +
một nhánh vector trên *nguyên văn câu hỏi* trong một luồng, song song với ①
(LLM, ~2-4s). Khi ① trả `search_queries`, chỉ chạy thêm nhánh vector cho truy
vấn MỚI chưa phủ, rồi RRF gộp tất cả. Với câu tìm người, nguyên văn câu hỏi
thường đã chứa từ khoá chính → đường tới hạn của ② co lại còn "phần bù".
*Tiết kiệm ~3-5s. Rủi ro: vài lời gọi embedding thừa khi ① đổi hướng hoàn toàn
(hiếm với find_people) — có trần.*

**1b. Đường tắt khi đã biết người (compare / followup + tên đã giải định
danh).** "So sánh A và B", "trong số đó ai trẻ nhất" — nếu `resolve.pinned_for`
ra 2-3 người và không có tiêu chí lọc nào khác thì **bỏ hẳn ② vector**: lấy
thẳng đoạn CV của họ → ③ → ⑤. *Câu "so sánh 2 người" từ ~30s xuống ~10s. Đúng
mấy câu trong ảnh test.*

**1c. Nạp trước số liệu kho trong lúc ① chạy** (cho `count`/`analyze`).
`corpus.overview()` + `fts_estimate()` là truy vấn CSDL thuần, độc lập với ①.
*Tiết kiệm ~0.5-2s.*

**1d. Ghép ② → ③.** ② hiện lấy TOÀN BỘ đoạn CV rồi mới trả; đổi để ③ lấy đoạn
theo từng lô trong worker — lô 1 gọi LLM trong khi lô 2 còn đang lấy đoạn.
*Tiết kiệm ~1-3s. Phức tạp hơn 1a-1c, làm sau nếu cần.*

**Tổng thực tế: ~5-10s trên một câu ~35s (nhanh hơn ~20-25%), và 1b cắt hơn nửa
thời gian cho câu so sánh.**

---

## 2. Hiện các bước đang làm, KHÔNG đổ ra suy nghĩ

### Hiện trạng

SSE phát cả `stage` (tên chặng) LẪN `thinking` (token suy nghĩ của model).
Giao diện (`ThinkingProcess.tsx`) tự bung khối "Quá trình suy nghĩ & lập luận"
kèm badge đếm token — đúng thứ người dùng nói là không cần và gây sốt ruột.

### Sửa

**2a. Backend** — `stream_answer` phát chuỗi bước có thứ tự, nhãn ổn định:

    {"type":"step","i":1,"of":4,"label":"Hiểu yêu cầu","state":"done"}
    {"type":"step","i":2,"of":4,"label":"Tìm trong kho","state":"active"}
    {"type":"step","i":3,"of":4,"label":"Đọc 16 hồ sơ, 4 phù hợp","state":"done"}
    {"type":"step","i":4,"of":4,"label":"Viết câu trả lời","state":"active"}

Ngừng phát `thinking` (token suy nghĩ) trên đường `/talent/ask/` — vẫn giữ
trong `trace` để soi lỗi, chỉ không đẩy ra client.

**2b. Frontend** — thay khối reasoning tự-bung bằng một **dòng thời gian bước**:
danh sách tick dần (Hiểu yêu cầu ✓ → Tìm trong kho ✓ → Đọc hồ sơ ✓ → Đang
viết…). Khối "Quá trình suy nghĩ" chuyển thành tuỳ chọn bấm mới xem (hoặc bỏ
hẳn ở bề mặt này).

---

## 3. Mobile: chuyển app / tab khác → mất kết nối

### Nguyên nhân

Trình duyệt mobile treo tab khi chuyển đi → thân `fetch` stream bị OS huỷ →
`for await` ở client ném lỗi → "Mất kết nối khi đang trả lời". Máy chủ hiện
**bỏ dở** generator khi client rớt (`GeneratorExit`), chỉ lưu phần dang dở.

### Sửa — ba phần

**3a. Máy chủ chạy XONG dù client rớt.** Tách sinh khỏi stream: một luồng chạy
`engine.stream_answer` tới hết, ghi từng chunk vào `queue`; response stream đọc
từ `queue`. Client rớt → luồng vẫn chạy hết và `_persist` bản ĐẦY ĐỦ. (Django
`StreamingHttpResponse` chạy trong threadpool dưới UvicornWorker nên thêm một
luồng nữa là chấp nhận được; có trần thời gian như `BUDGET`.)

**3b. Endpoint lấy lại kết quả.** `GET /api/v1/talent/ask/turn/<client_turn_id>/`
→ 200 kèm câu trả lời đã lưu nếu xong, 202 nếu đang chạy, 404 nếu không có.

**3c. Frontend nối lại.** Nghe `visibilitychange`: tab ẩn giữa lúc chờ → ghi
nhớ `client_turn_id`, KHÔNG hiện lỗi ngay. Khi quay lại (hoặc khi stream ném
lỗi), gọi endpoint 3b vài lần (giãn dần, ~30s tổng) trước khi kết luận hỏng.
Có kết quả thì thay bong bóng "đang chờ" bằng câu trả lời thật.

---

## Thứ tự

2 (gọn, thắng UX ngay) → 3 (đau nhất với người dùng) → 1 (1b + 1a + 1c; 1d để
sau). Mỗi phần một commit, có test, đo lại trên production.

---

## Đã làm (05/09)

**Phần 2 — hiện bước, không đổ suy nghĩ.** ✅
* `_pipeline` thành generator: `yield` bước, `return` tuple. `stream_answer` dùng
  `yield from`, `answer()` dùng `_drain()`.
* Ngừng đẩy `reasoning` ra client (giữ trong trace). SSE: event `step`.
* `StepTimeline.tsx` tick dần, thu thành một dòng khi chữ bắt đầu chảy. Bỏ
  `ThinkingProcess` khỏi `AiSearch`.

**Phần 3 — mobile mất kết nối.** ✅
* `talent/answer/runner.py`: production (PostgreSQL) chạy engine trong LUỒNG
  NỀN + hàng đợi. Client rớt → luồng vẫn chạy hết, `persist` bản đầy đủ.
  SQLite (test/dev) → chạy inline (SQLite khoá bảng khi hai luồng cùng ghi);
  tắt hẳn được bằng `settings.ANSWER_RUNNER_THREADED = False`.
* `GET /api/v1/talent/ask/turn/<client_turn_id>/` → 200 (đã lưu) / 202 (đang
  chạy) / 404. Sổ `_INFLIGHT` cho biết "đang chạy".
* `AiSearch.tsx`: `recoverTurn()` hỏi lại vài lần giãn dần (~40s) khi stream
  đứt, và khi `visibilitychange` quay lại foreground mà còn lượt "đang chờ".
  Thay "Mất kết nối" bằng "Kết nối gián đoạn — đang lấy lại kết quả…".

**Phần 1 — song song hoá.**
* 1b ✅ — đường tắt khi câu neo HOÀN TOÀN vào tên (`compare`/`followup`, không
  `must_have`, ≤1 `should_have`): `retrieve(search_queries=[])` bỏ hẳn ② vector
  + FTS, đọc thẳng người ghim; không widen. "So sánh A và B" cắt ~5s + mấy lời
  gọi embedding.
* 1a, 1c, 1d — chưa làm (truy hồi đoán trước, nạp trước số liệu, ghép ②→③).

---

## Bổ sung 05/09 (chiều) — phản hồi test tiếp

### Câu kiến thức chung / thời gian thực trả RỖNG
"Tổng giám đốc MSB là ai", "thời tiết hiện tại" → không có nội dung.
* Gốc: `ASSISTANT_WEB_SEARCH` mặc định `0` trong compose → `websearch.enabled()`
  = False → nhánh chat rơi thẳng xuống model hội thoại, model không trả đúng
  câu factual/real-time → rỗng.
* `docker-compose.oracle-core.yml`: `ASSISTANT_WEB_SEARCH` mặc định `0` → `1`.
  Backend `gemini_grounding` chạy sẵn nhờ `MSB_AI_GEMINI_API_KEY` (đang dùng
  cho embedding). `web_answer` vẫn chặn câu có PII.
* `talent/answer/chat.py`: `_do_web()` — đã tới nhánh chat (không phải câu kho,
  không phải câu meta) thì MẶC ĐỊNH tra web khi web bật, không chờ
  `intent.is_web`. Thêm: model hội thoại trả rỗng → thử web lần cuối trước khi
  buông "không có nội dung".

### "chỉ tìm trong 40 ứng viên"
Truy hồi (vector + FTS) vẫn quét TOÀN kho rồi RRF xếp hạng — `POOL` chỉ giới
hạn phần ĐỌC KỸ bằng LLM ở ③. Nhưng 40 là hẹp khi kho lớn dần.
* `POOL` 40 → 60, `PER_QUERY` 60 → 90, `pool_for` hệ số ×4 → ×6. ③ chạy lô
  song song nên thêm ~20 hồ sơ gần như không thêm thời gian tường.
* Câu cực trị toàn kho ("lớn tuổi nhất") vẫn giới hạn trong pool — feature D,
  chưa làm (cần tầng tiền-sắp-xếp theo dữ liệu có cấu trúc).
