# Quản trị model AI bằng UI + CSDL

> Ngày 04/09/2026. **A–D và F đã làm và xác minh trên production. E chờ quyết.**
> Kế hoạch không phải hợp đồng — đo được gì khác thì sửa kế hoạch, đừng sửa số đo.

## 0. Kết quả (đo trên production sau khi triển khai)

| Kiểm | Trước | Sau |
|---|---|---|
| Tác vụ lấy model từ CSDL | 4/22 | **22/22**, không cái nào rơi xuống đáy |
| `cv_ocr` | `glm-5.2` — **HTTP 400 với ảnh**, không có thị giác | `qwen3.6-flash`, đo được là đọc đúng chữ trong ảnh |
| `cv_parsing` — số lượt gọi LLM | 420/420 hồ sơ | **8/420** (98% bỏ qua); 8 cái còn lại là CV 82–90 ký tự, trích hỏng thật |
| Tác vụ mới, chưa có migration | rơi xuống model mặc định nhà cung cấp | nhận mặc định sổ đăng ký (`registry_default`) |

Hai đính chính so với bản nháp đầu, cả hai vì kiểm lại trên đường thật:

- **`cv_ocr` là mìn, không phải đám cháy.** Tôi suýt báo thành sự cố đang diễn
  ra. `LLMCall` cho thấy `cv_ocr`, `cv_parsing`, `candidate_extraction` đều có
  **0 lượt gọi**, và 420/420 tài liệu đều `done` — Edge bóc hết trước khi tới
  Hub, nên đường dự phòng này chưa từng chạy. Nó chỉ hỏng khi cần đến nó.
- **Ngưỡng `cv_parsing` phải đo hai vòng.** Vòng đầu đo "từ dài" và một nửa số
  ca nó bắt là báo động giả: URL LinkedIn 54 ký tự, Facebook 50 ký tự, dấu chấm
  kẻ dòng 141 ký tự, gạch chân tiêu đề 109 ký tự. Đổi sang đo **chuỗi chữ cái
  liền** thì cả ba tự loại — URL bị dấu chấm ngắt, dấu chấm không có chữ nào.

Còn một phát hiện chưa xử lý: `industries` rỗng **0/786 hồ sơ**, và
`candidate_extraction` — tác vụ điền chính field ấy — có **0 lượt gọi**. Không
phải AI bóc sai; nó chưa bao giờ chạy. Việc riêng, xem §7.

## 1. Đề bài, tách thành 5 đòi hỏi

1. Quản toàn bộ bằng UI `/settings` + CSDL, **không đi theo `.env` nữa**.
2. GreenNode là **hub nhiều model** — cần cách quản phù hợp, đứng cạnh được các
   nhà cung cấp một-model.
3. Tương lai thêm nhóm/tác vụ dùng AI thì **phải tự hiện ra** trong `/settings`.
4. Mặc định là model tôi cho là hợp nhất; người vận hành **chọn trong list hoặc
   gõ tay** (vì tên model đổi liên tục, list sẽ không kịp cập nhật).
5. Mỗi tác vụ đã liệt kê phải **thực sự dùng AI một cách thông minh**, không
   phải cho có.

## 2. Hiện trạng đo được

### 2.1 Định tuyến: thứ tự đã đúng, độ phủ thì không

Thứ tự ưu tiên trong `ai/router.py::_model_for` hiện là:

```
MSB_AI_EMERGENCY_*_MODEL_<TASK>   (env, phá kính khi cháy)
  → TaskModelRoute trong CSDL      (UI đặt ở đây)
    → MSB_AI_MODEL_<TASK>          (env bootstrap, CHỈ khi CSDL chưa có route)
      → model mặc định của nhà cung cấp
```

CSDL **đã** thắng env thường. Nên vấn đề không nằm ở thứ tự — nằm ở chỗ **đa số
tác vụ không có route nào cả**, và tầng đáy nuốt hết:

| Nguồn quyết định model | Số tác vụ | Gồm những gì |
|---|---|---|
| `TaskModelRoute` (CSDL/UI) | 4 | `talent_answer_plan`, `judge`, `compose`, `talent_embedding` |
| `MSB_AI_MODEL_*` (env) | 4 sống + **1 chết** | `talent_search`, `assistant_intent`, `assistant_agent`, `assistant_web`, và `talent_explain` — module đã bị xoá |
| **`MSB_AI_GREENNODE_MODEL` (đáy)** | **13** | `cv_parsing`, `cv_ocr`, `title_similarity`, `jd_parse`, `social_intent`, `rb_*`, … |

Hai điều đọc ra từ bảng này:

- `MSB_AI_MODEL_TALENT_EXPLAIN=deepseek-v4-flash` vẫn nằm trên máy chủ, trỏ vào
  một module không còn tồn tại. **Env tự trôi, không ai thấy.** Đây đúng là lý
  do phải bỏ env.
- 13 tác vụ im lặng nhận `z-ai/glm-5.2-hackathon`. Không ai chọn thế; đó chỉ là
  cái rơi xuống.

### 2.2 Cái rơi xuống ấy đang hỏng

Đo trên production, GreenNode gọi thẳng, không qua router:

| Tác vụ | `glm-5.2-hackathon` (đang chạy) | `qwen3.6-flash` |
|---|---|---|
| `title_similarity` — 6 cặp chức danh, 3 lượt | 25,4s | **16,3s** (−36%) |
| `cv_parsing` — CV 3.135 ký tự, 2 lượt | **timeout, không trả gì** | **31,3s**, giữ 6/6 năm · 1/1 email · 8/8 số |

Điểm số `title_similarity` gần như trùng nhau, và ở đúng cặp mà docstring của
`talent/semantic.py` nêu là khó — *"Data Analyst" vs "Chuyên viên Phân tích Tín
dụng"* — qwen cho 0.5, glm cho 0.3. qwen **đúng hơn**.

`cv_parsing` chạy cho **mọi hồ sơ nhập vào**. Model của nó vừa chết trên một CV
3KB. Đây là lỗi đang sống, không phải chuyện tối ưu.

### 2.3 Sổ đăng ký thiếu 2 tác vụ, và test canh nó cũng mù

`ai/tasks.py` khai 20 tác vụ. Mã nguồn có **22**. Thiếu:

- `cv_ocr` — `OCR_TASK` trong `core/cv_parsing.py:19`
- `candidate_extraction` — `EXTRACTION_TASK` trong `intel/extraction.py:32`

`ai/tests_task_registry.py` sinh ra để chống đúng loại lệch này, nhưng regex của
nó là `^TASK\s*=\s*"..."` — chỉ bắt biến tên đúng `TASK`, nên **không thấy**
`OCR_TASK` và `EXTRACTION_TASK`. Test xanh trong khi vẫn lệch. Cùng một hình
dạng lỗi với `talent_explain`: cái canh gác có lỗ đúng ở chỗ cần canh.

### 2.4 Chưa có danh mục model ở đâu cả

Không có `KNOWN_MODELS` / catalog / gọi `/v1/models` trong toàn bộ mã nguồn.
Ô model trong `/settings` là ô chữ trống — gõ sai một ký tự là hỏng âm thầm.

## 3. Ràng buộc mà UI phải nói ra được

`kind` trong sổ đăng ký hiện chỉ là *gợi ý*. Hai giá trị trong đó thật ra là
**yêu cầu năng lực**, chọn sai là hỏng lặng:

- `talent_embedding` — phải là model **embedding**. Đặt model chat vào đây thì
  vector hoá kho CV chết.
- `cv_ocr` — phải là model **vision**. Đặt model chỉ-đọc-chữ vào đây thì CV
  scan/ảnh không vào được kho, mà log chỉ nói "không đủ văn bản".

Hiện `cv_ocr` đang rơi vào `glm-5.2-hackathon` mà **chưa ai kiểm model đó có
đọc được ảnh không**. Phải đo trước khi chốt mặc định.

Một cái bẫy nữa cần ghi lại: `ai/providers.py` **cắt bỏ `reasoning_effort` cho
mọi model `deepseek/*`** (chúng HTTP 400 với tham số đó). `_vision_ocr` gọi kèm
`reasoning_effort="none"`. Nên nếu định tuyến `cv_ocr` sang deepseek, tham số bị
cắt và model sẽ "nghĩ" hết ngân sách token thay vì OCR.

## 4. Kế hoạch — 6 phần, làm theo thứ tự

### A. Đóng lỗ sổ đăng ký *(nền móng — mọi phần sau đọc từ đây)*

- Thêm `cv_ocr`, `candidate_extraction` vào `ai/tasks.py` → **22 tác vụ**.
- Nới regex thành `^[A-Z_]*TASK[A-Z_]*\s*=\s*"..."` để bắt mọi biến kết thúc
  bằng `TASK`, và thêm một test canh chính cái regex đó (một fixture chứa
  `OCR_TASK = "x"` phải được bắt).
- Sửa `kind` của `cv_parsing`: nó **không** trả JSON — nó chuẩn hoá văn bản CV
  và trả lại nguyên văn. Đổi `json` → `doc`.
- Thêm hai `kind` mới: `vision` (cho `cv_ocr`) và giữ `embedding`.

### B. Danh mục model theo nhà cung cấp

Ba tầng, để vừa có gợi ý vừa không bao giờ bị list khoá tay — đúng nỗi lo "sợ
trong list không cập nhật hết":

1. **Danh mục tĩnh** `ai/catalog.py` — mỗi nhà cung cấp một danh sách model đã
   biết, mỗi model kèm cờ năng lực (`chat` / `vision` / `embedding`) và một câu
   nói nó hợp việc gì. GreenNode có 5+ model ở đây; Gemini có nhánh embedding.
2. **Làm mới từ nhà cung cấp** — nút trong `/settings` gọi `GET {base_url}/models`
   (GreenNode theo chuẩn OpenAI nên có endpoint này), hợp nhất kết quả vào danh
   mục và lưu CSDL kèm thời điểm. List tự cập nhật, không chờ tôi sửa mã.
3. **Luôn cho gõ tay** — ô chọn là combobox: chọn trong list, hoặc gõ mã model
   bất kỳ. Gõ tay không bị chặn, chỉ cảnh báo nếu mã không có trong danh mục.

Cảnh báo năng lực: chọn model không có cờ `vision` cho `cv_ocr` (hoặc không có
`embedding` cho `talent_embedding`) thì UI chặn kèm lý do — không để hỏng lặng.

### C. Mặc định cho đủ 22 tác vụ, ghi thành route trong CSDL

Không còn tác vụ nào "thừa hưởng" model từ đáy. Mỗi tác vụ có một hàng
`TaskModelRoute` thật, sinh bằng data migration, sửa được trong UI.

Mặc định đề xuất, theo `kind` và theo số đo ở §2.2:

| `kind` | Model mặc định | Vì sao |
|---|---|---|
| `json` (10 tác vụ) | `qwen/qwen3.6-flash` | Đo được: nhanh hơn 36%, chất lượng bằng hoặc hơn |
| `doc` — `judge`, `cv_parsing` | `qwen/qwen3.6-flash` | glm timeout trên chính việc này |
| `viet` — `compose`, `outreach_draft`, `rb_outreach_draft` | `deepseek/deepseek-v4-pro` | Chỗ người dùng đọc thấy, đáng trả tiền |
| `viet` — còn lại | `deepseek/deepseek-v4-flash` | Tổng hợp/hội thoại, cần nhanh hơn cần văn hay |
| `embedding` | `gemini/models/gemini-embedding-2` | Đang chạy, không đổi |
| `vision` — `cv_ocr` | **chờ đo** | Phải xác minh model nào trong hub đọc được ảnh |

### D. UI `/settings`

- Nhóm theo bề mặt nghiệp vụ (sổ đăng ký đã có `GROUPS`), mỗi tác vụ hiện nhãn
  + mô tả tiếng Việt — không ai phải đoán `rb_prospect_search` là gì.
- Mỗi hàng: chọn nhà cung cấp → combobox model của **đúng** nhà cung cấp đó.
- Hiện **nguồn đang có hiệu lực** (`config_source` router đã trả sẵn): CSDL /
  env bootstrap / đáy nhà cung cấp — và **cảnh báo đỏ khi `MSB_AI_EMERGENCY_*`
  đang ghi đè**, vì đó là thứ duy nhất còn thắng được UI.

### E. Gỡ env

Sau khi C xong và xác minh trên production:

- Xoá khỏi `.env`: `MSB_AI_MODEL_TALENT_EXPLAIN` (chết), `MSB_AI_MODEL_*` còn
  lại (đã thành route), `MSB_AI_GREENNODE_MODEL` (không còn ai rơi xuống nó).
- **Giữ** `MSB_AI_EMERGENCY_*` làm đường phá kính khi provider cháy lúc nửa đêm,
  và ghi rõ trong `docs/` rằng nó thắng UI — để lần sau không ai phải đi tìm.
- Giữ `MSB_AI_*_API_KEY`, `BASE_URL` ở env: đó là bí mật, không phải cấu hình.

### F. Audit "AI có thông minh không"

Một phát hiện đã chắc, từ chính số đo §2.2:

> **`cv_parsing` đang gọi AI cho có.** Luồng là: bộ trích cục bộ chạy trước và
> lưu text (chất lượng 0.55) → **rồi vẫn luôn** đẩy nguyên text đó qua LLM để
> "chuẩn hoá" (vào 60K ký tự, ra 12K token). Trên CV thật, đầu ra dài
> **3130/3135 ký tự** và giữ **y nguyên** mọi năm, email, số. Tức LLM sửa gần
> như *không gì*, đổi lấy 31 giây và một lượt gọi cho **mọi hồ sơ nhập vào**.
>
> Sửa: chỉ gọi LLM khi bản trích cục bộ **thực sự xấu** — đo bằng heuristic rẻ
> (tỷ lệ ký tự lạ, mất khoảng trắng, tỷ lệ chữ cái). CV sạch thì bỏ qua LLM.

Phần còn lại rà theo cùng một câu hỏi — *"bỏ AI đi thì có làm được bằng luật
không?"*:

- `title_similarity` — **giữ**. Đúng việc AI: chấm nghĩa giữa chức danh mà so
  chuỗi không làm được, lại có cache `TitleSimilarity` nên không gọi lại.
- `cv_ocr` — **giữ**. Đọc ảnh, không có đường nào khác.
- `social_intent`, `assistant_intent`, `talent_corpus_qa` — **chưa rà**, làm ở
  phần này.

### G. Lớp đỡ cho tác vụ tương lai *(thêm sau khi C xong, vì C hở đúng chỗ này)*

Migration 0014 chỉ gieo route cho 22 tác vụ *đang có*. Tác vụ thứ 23 sẽ không có
hàng nào trong CSDL và lại rơi xuống model mặc định của nhà cung cấp — đúng cái
vừa dọn. Nên router lấy mặc định thẳng từ sổ đăng ký, thành **bậc 3** dưới route
CSDL. Thêm tác vụ vào `tasks.py` là chạy đúng ngay, không chờ ai nhớ viết
migration. Nguồn báo là `registry_default` để `/settings` gợi được *"bấm Lưu để
chốt vào CSDL"*.

## 5. Thứ tự triển khai

A → B → C → D → G → F. E chỉ làm sau khi mọi thứ đã chạy thật và xác minh.

**E chưa làm, và cố ý.** Sửa `.env` trên production là việc khó lùi trên một file
chứa secret, mà các biến đó giờ đã **vô hiệu** — 22/22 tác vụ lấy cấu hình từ
CSDL, kiểm bằng chính `effective_config()`. Nên đây là dọn dẹp, không phải sửa
lỗi. Ba dòng đáng gỡ khi thuận tiện:

```
MSB_AI_MODEL_TALENT_EXPLAIN=…    # module đã bị xoá, dead weight
MSB_AI_MODEL_TALENT_SEARCH=…     # đã thành route CSDL
MSB_AI_MODEL_ASSISTANT_{INTENT,AGENT,WEB}=…
```

`MSB_AI_GREENNODE_MODEL` thì **giữ**: nó là lưới an toàn cuối cho thứ không nằm
trong sổ đăng ký. `MSB_AI_EMERGENCY_*` cũng giữ — đường phá kính khi provider
cháy lúc nửa đêm, và nó là thứ **duy nhất còn thắng được UI**, nên `/settings`
hiện cảnh báo đỏ khi nó đang ghi đè.

## 7. Việc còn lại

- **`industries` rỗng 0/786.** `candidate_extraction` điền field này nhưng có 0
  lượt gọi. Cần lần xem nó được kích hoạt ở đâu và vì sao đường đó không chạy.
- **`social_intent`, `assistant_intent`, `talent_corpus_qa`** — chưa rà theo câu
  hỏi *"bỏ AI đi thì có làm được bằng luật không?"*.
- **Registry tool chưa dùng hết**: `trace.tools` rỗng ngay cả khi đã soạn thư.
- **RB/Prospect** — anh đã hoãn tới sau khi luồng HR chạy tốt.

## 6. Đã kiểm thế nào

Không đo trên đường khác với đường người dùng đi:

- `effective_config()` cho **cả 22** tác vụ, chạy trong container production →
  tất cả `db_task_route`. ✅
- Năng lực thị giác đo bằng ảnh JPEG thật gửi qua đúng provider đang chạy, cả 6
  model trong hub → `glm-5.2` HTTP 400, `qwen3.6-*` và `gemma-4` đọc đúng,
  `deepseek-v4-pro` tự nói không xem được ảnh. ✅
- Ngưỡng `cv_parsing` chạy trên **420 CV thật trong kho**, không phải chuỗi bịa
  — đó là cách phát hiện ra vòng đầu có báo động giả. ✅
- Tác vụ thứ 23 dựng bằng `patch.dict` rồi hỏi chính router → `registry_default`
  chứ không rơi xuống đáy. ✅
- 1.343 test backend, xanh hết. ✅
