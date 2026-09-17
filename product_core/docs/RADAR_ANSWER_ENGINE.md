# Radar Answer Engine — đập đi xây lại tầng sinh phản hồi

**Trạng thái:** kế hoạch, chưa code
**Ngày:** 03/09/2026
**Phạm vi:** toàn bộ đường đi từ *câu hỏi của người dùng* → *câu trả lời*. KHÔNG đụng
hạ tầng retrieval/embedding/bộ nhớ đã xây xong.

---

## 1. Chẩn đoán — ba lỗi trong ảnh, một nguyên nhân gốc

| Câu hỏi | Tiêu chí AI bóc ra | Sai ở đâu |
|---|---|---|
| "tìm **5** ứng viên **học cao đẳng** **ít tuổi nhất**" | `chức danh: Cao đẳng` | Trình độ học vấn bị nhét vào ô *chức danh*. "5" (giới hạn) và "ít tuổi nhất" (sắp xếp) **không có ô nào để chứa** → biến mất. Trả 20 hồ sơ, không sắp theo tuổi. |
| "tìm ứng viên **quan hệ khách hàng**" | `chức danh: Customer Relationship` | Dịch sang tiếng Anh, vứt nguyên văn tiếng Việt → không CV nào chứa chuỗi đó → **0 hồ sơ**. |
| "tìm ứng viên **học tài chính ngân hàng của NEU**" | `chức danh: Tài chính ngân hàng`<br>`lĩnh vực/công ty: NEU` | Ngành học nhét vào *chức danh*, **trường đại học** nhét vào *công ty*. Top 1 là "CVCC Tài chính - SBSI" — không liên quan NEU. |

### Trace thật (chạy trên prod, câu số 2)

```
hiring_need.parse("tìm ứng viên quan hệ khách hàng")
  → {'title': 'Customer Relationship'}
search(title="Customer Relationship", ai_mode=True)
  → pool 30   # _recall_terms khớp 0 dòng; 30 này chỉ là "hồ sơ mới nhất" độn cho đủ
scoring.score_person(...)  → 0.0 cho TẤT CẢ
  # _title() so chuỗi profile.current_title (rỗng/tiếng Việt) với "Customer Relationship"
floor 0.15 → 0 người vượt → "0 hồ sơ phù hợp"
```

Cùng lúc đó, `corpus_qa` (dense + full-text) hỏi *"ứng viên có kinh nghiệm quan hệ
khách hàng"* trả về ngay Nguyễn Ngọc Diệp (CV #19), Nguyễn Thị Khánh Băng (CV #69)…
kèm trích dẫn nguyên văn.

### Nguyên nhân gốc — chỉ một

> Tầng sinh phản hồi bị đóng khung quanh **một schema 11 khoá cố định**
> (`skills, title, location, company, min_years, max_years, has_email, has_phone,
> text, product, lead_status`), rồi **một bộ chấm điểm so-chuỗi** quyết định ai
> được hiện.

Hệ quả dây chuyền:

1. **Schema không diễn đạt nổi câu hỏi thật.** Trình độ, trường, ngành học, tuổi,
   thứ tự sắp xếp, số lượng, phủ định, so sánh — không khoá nào chứa được. Câu hỏi
   bị ép méo hoặc mất vế.
2. **Dịch thuật huỷ ngữ nghĩa.** Prompt bắt LLM viết "thuật ngữ như trong CV" → nó
   dịch sang tiếng Anh, mất nguyên văn, mất mọi biến thể đồng nghĩa.
3. **Chấm điểm so chuỗi phủ quyết retrieval.** Dù pgvector/HNSW/Gemini đã tìm đúng
   người, `scoring.score_person` cho 0.0 vì `current_title` rỗng hoặc khác chữ, rồi
   `_SCORE_FLOOR` loại sạch. **Retrieval tốt bị tầng sau ném đi.**
4. **Câu trả lời không phải câu trả lời.** Đầu ra là một danh sách thẻ + con số %
   không giải thích được, không trả lời thẳng câu hỏi, không trích nguồn.

Sửa vá từng chỗ (thêm khoá `education`, thêm `school`, nới floor…) chỉ đẩy lỗi sang
câu hỏi tiếp theo. **Phải bỏ hẳn mô hình "câu hỏi → tiêu chí cứng → lọc → chấm điểm".**

---

## 2. Giữ gì — hạ tầng đã trả giá, còn tốt

Không đụng vào:

| Thành phần | Vì sao giữ |
|---|---|
| `ai/router.py`, `providers.py`, `adapter.py` | Đa nhà cung cấp, streaming, fallback, xoay khoá, model theo task. Chạy tốt. |
| `ai/conversation_state.py`, `projection.py`, `thread_state.py` | Bộ nhớ hội thoại, envelope, snapshot kết quả. |
| `ai/events.py` | Event log append-only theo lượt. |
| `ai/prompt_guard.py`, `ai/pii.py` | Chống injection, chặn PII ra ngoài. |
| `ai/intent.py` | Phân nhánh search / hội thoại / web. |
| `ai/toolset.py`, `agent.py`, `tool_handlers.py` | **Vòng lặp tool có RBAC — đã xây, đã test, đang bật ở prod nhưng gần như chưa dùng.** Đây là tài sản lớn nhất chưa khai thác. |
| `talent/vector_index.py` + `PersonSearchDocument` + `CVChunk` + pgvector HNSW | Dense retrieval **phủ 100%** bằng Gemini. Vừa verify. |
| Chỉ mục GIN full-text (`content_norm`, `text_norm`) | Khớp tiếng Việt không dấu, index scan. |
| `talent/corpus_qa.py` | Truy hồi + trả lời có dẫn chứng. **Là hạt giống của engine mới.** |
| `talent/search.py` | Bộ lọc SQL — giữ làm **công cụ**, không còn là đường chính. |
| `intel/` (canonical registry, ExtractedFact) | Alias, chuẩn hoá, provenance. |

---

## 3. Đập gì — và audit phụ thuộc (không `rm` thẳng được)

| Xoá khỏi đường trả lời | Ghi chú audit |
|---|---|
| `talent/hiring_need.py` — bộ bóc tiêu chí | ⚠️ `hiring/jd.py` đang import `_extract_json`, `_validate` → **tách sang `ai/jsonx.py` trước**. `agents/tools.py` tham chiếu label → sửa. |
| `talent/scoring.py` — chấm điểm 7 chiều | ⚠️ `hiring/calibration.py` dùng để hiệu chỉnh trọng số từ phản hồi recruiter → **giữ module cho `hiring/`, gỡ khỏi đường trả lời**. |
| `talent/ai_rank.py` | Chỉ đường trả lời dùng → xoá được. |
| `talent/ai_search.py` — orchestrator | ⚠️ `core/tests_hero_flow.py` mock `ai_search.complete` → viết lại test theo engine mới. |
| `talent/analysis_cache.py` | Cache sai thứ (danh sách thẻ, khoá theo tiêu chí) → xoá, thay bằng cache tầng retrieval. |
| `talent/semantic.py` + model `TitleSimilarity` | Bộ nhớ độ-gần-chức-danh, sinh ra để vá lỗi so chuỗi. Dense làm tốt hơn → xoá. |
| `talent/semantic_index.py` + `TalentSemanticIndex` | Feature-hashing fallback thời chưa có dense. Dense phủ 100% → xoá. |
| Frontend: `ResultCard`, `CriteriaChips`, bảng 7 chiều, badge `%`, giao thức quick/deep | **Bỏ hết thẻ ứng viên** như yêu cầu. |
| Tham số API `quick`, `criteria`, `force`; hợp đồng `AiTalentCard.match` | Thay bằng hợp đồng mới ở §5. |

> Thứ tự bắt buộc: **tách helper dùng chung → dựng engine mới song song → chuyển
> đổi sau cổng eval → mới xoá code cũ.** Không xoá trước.

---

## 4. Kiến trúc mới — "Radar Answer Engine"

Nguyên tắc: **LLM lập kế hoạch và viết câu trả lời; CODE truy hồi, tổng hợp và
kiểm chứng.** Không có schema tiêu chí cứng, không có điểm % vô nghĩa.

```
Câu hỏi + ConversationEnvelope
        │
  ①  HIỂU & LẬP KẾ HOẠCH   (1 lượt LLM nhanh)
        │   → QueryPlan (JSON linh hoạt, §4.1)
        │
  ②  TRUY HỒI              (CODE, song song, đa truy vấn)
        │   dense hồ sơ · dense đoạn CV · full-text · lọc cứng (nếu có)
        │   → RRF fusion → 100–200 người + đoạn khớp
        │
  ③  ĐỌC & PHÁN ĐOÁN       (LLM, theo lô ~40 dossier)
        │   → ai thực sự thoả · trích dẫn nguyên văn · TRÍCH XUẤT thuộc tính
        │      câu hỏi cần (tuổi, trường, bằng cấp…) NGAY TỪ BẰNG CHỨNG
        │
  ④  TỔNG HỢP              (CODE)
        │   → áp sort_by + limit trên thuộc tính LLM vừa trích. Tất định.
        │
  ⑤  VIẾT CÂU TRẢ LỜI      (LLM mạnh, streaming) ← phần "Nói"
            → markdown có trích dẫn [n], FACT/suy luận/chưa rõ, NEXT ACTION
```

**Vòng lặp tự nới (bounded):** nếu ③ báo "bằng chứng mỏng" hoặc pool < ngưỡng →
quay lại ① **đúng một lần** với `search_queries` mới, ghi rõ vào trace đã nới gì.
Không lặp vô hạn.

**Lối thoát agentic:** câu hỏi nhiều bước ("so sánh A với B rồi tìm thêm người
giống A") đi qua `ai/agent.py` + `toolset` sẵn có, với trần `ASSISTANT_TOOL_MAX_STEPS`.

### 4.1. QueryPlan — thay cho 11 khoá cứng

```jsonc
{
  "shape": "find_people | analyze | count | compare | followup | general",
  "information_need": "câu hỏi độc lập, đã ghép ngữ cảnh hội thoại",
  "must_have":  ["đang ở Hà Nội"],        // ràng buộc THẬT SỰ cứng — rất ít
  "should_have":["kinh nghiệm quan hệ khách hàng cá nhân", "ngành ngân hàng"],
  "extract":    ["năm sinh", "trường tốt nghiệp", "trình độ"], // ③ sẽ bóc từ CV
  "sort_by":    {"key": "năm sinh", "dir": "desc"},            // "ít tuổi nhất"
  "limit": 5,
  "search_queries": [                     // LLM tự viết, đa ngữ, đa cách nói
    "quan hệ khách hàng cá nhân",
    "chuyên viên khách hàng ưu tiên priority banking",
    "customer relationship manager RM",
    "chăm sóc và tư vấn khách hàng ngân hàng"
  ]
}
```

Ba thay đổi quyết định so với `hiring_need`:

1. **`search_queries` do LLM viết** — nó tự sinh mọi cách nói, cả tiếng Việt lẫn
   tiếng Anh. Không còn "dịch một lần rồi mất nguyên văn".
2. **`sort_by` + `limit` được giữ** — "5 người ít tuổi nhất" hoạt động.
3. **`extract` mở** — trường/ngành/tuổi/bằng cấp không cần cột trong DB; ③ bóc
   thẳng từ text CV. Hỏi gì bóc nấy, không giới hạn schema.

### 4.2. Vì sao cách này sửa đúng ba lỗi trong ảnh

| Ảnh | Cách engine mới xử lý |
|---|---|
| 5 người học cao đẳng ít tuổi nhất | `should_have: ["trình độ cao đẳng"]`, `extract: ["năm sinh","trình độ"]`, `sort_by: năm sinh desc`, `limit: 5`. ③ đọc CV bóc năm sinh + bằng cấp, ④ sắp xếp và cắt 5. |
| quan hệ khách hàng | `search_queries` gồm cả 4 biến thể → dense + full-text đều trúng. Không có bộ chấm điểm so chuỗi để phủ quyết. |
| tài chính ngân hàng của NEU | `should_have: ["ngành tài chính ngân hàng"]`, `must_have: ["tốt nghiệp NEU / Kinh tế Quốc dân"]`, `extract: ["trường"]`. ③ xác nhận trường từ nguyên văn CV, ai không có bằng chứng thì loại. |

---

## 5. Hợp đồng đầu ra mới — bỏ thẻ

`POST /api/v1/talent/ask/` (SSE streaming):

```jsonc
{
  "answer_markdown": "…câu trả lời có [1][2]…",
  "citations": [ {"n":1,"person_id":19,"name":"…","document_id":19,"snippet":"…"} ],
  "people":    [ {"id":19,"name":"…","headline":"…","why":"1 câu"} ],  // chip gọn để điều hướng
  "unknowns":  ["Chưa rõ năm sinh của 2 hồ sơ — CV không ghi"],
  "next_actions": ["Mở CV #19 xác minh…"],
  "trace": { "plan": {...}, "retrieval": {...}, "expanded": bool, "model": "…" }
}
```

Giao diện:

- Câu trả lời là **một bài viết** (markdown), không phải danh sách thẻ.
- Trích dẫn `[n]` bấm được → `SourcePreview` (đã có, tô sáng đoạn CV gốc).
- Dưới cùng: dải **chip người** gọn (tên · 1 dòng · link Hồ sơ 360° · nút thêm vào
  đợt tuyển). Không thẻ 300px.
- Khối "Chưa chắc / cần xác minh" hiển thị riêng, không trộn vào câu khẳng định.

---

## 6. Phần "Nói" — hạng mục riêng, không phải phụ phẩm

Đây là thứ người dùng thực sự đánh giá. Tách thành công việc độc lập với tiêu chí rõ:

**Luật viết (đưa vào system prompt của ⑤):**

1. **Câu đầu tiên trả lời thẳng câu hỏi.** Không "Dựa trên dữ liệu được cung cấp…".
2. **Cấu trúc theo dạng câu hỏi:** hỏi ai → danh sách đánh số; hỏi bao nhiêu → con
   số trước, cách đếm sau; hỏi so sánh → bảng; hỏi tổng hợp → đoạn văn có luận điểm.
3. **Mọi khẳng định về người phải có `[n]`.** Không trích dẫn được thì không được viết.
4. **Tách bạch** điều CV nói (FACT) · điều suy ra (INFERENCE) · điều không biết (UNKNOWN).
5. **Nói rõ giới hạn**: "3/5 hồ sơ không ghi năm sinh nên không xếp hạng được" —
   thành thật hơn là bịa thứ tự.
6. **Không nhồi cho đủ số.** Hỏi 5 mà chỉ 2 người có bằng chứng → trả 2 và nói vì sao.
7. Tiếng Việt nghiệp vụ, gọn, không hoa mỹ, không lặp lại câu hỏi.

**Cách làm:** viết 8–10 **câu trả lời mẫu vàng** cho các dạng câu hỏi, dùng làm
few-shot + làm chuẩn chấm. Lặp prompt cho tới khi đầu ra sánh được với mẫu.

**Chọn model theo chặng** (qua `/settings` → route theo task):

| Chặng | Yêu cầu | Gợi ý |
|---|---|---|
| ① Lập kế hoạch | nhanh, JSON chuẩn | `qwen3.6-flash` / `deepseek-v4-flash` |
| ③ Đọc & phán đoán | đọc dài, chính xác, rẻ theo lô | `deepseek-v4-flash` |
| ⑤ Viết câu trả lời | **suy luận + hành văn tốt nhất** | `deepseek-v4-pro` / `glm-5.2` |

---

## 7. Giai đoạn

| GĐ | Việc | Ước lượng |
|---|---|---|
| **0. Đóng băng & đo** | Bộ 30 câu hỏi thật (gồm 3 câu trong ảnh) + phán quyết mong đợi. Chạy qua hệ hiện tại, lưu làm mốc. Tách `_extract_json/_validate` → `ai/jsonx.py` cho `hiring/jd.py`. | 0.5 ngày |
| **1. Engine lõi** | Package `talent/answer/`: `plan.py` ① · `retrieve.py` ② · `judge.py` ③ · `aggregate.py` ④ · `compose.py` ⑤ · `engine.py`. Endpoint `/talent/ask/` SSE. Chạy **song song** endpoint cũ sau cờ `TALENT_ANSWER_ENGINE`. | 2–3 ngày |
| **2. Phần "Nói"** | Prompt ⑤, câu trả lời mẫu vàng, lặp tinh chỉnh. Chọn model từng chặng. | 1–2 ngày |
| **3. Giao diện mới** | Bỏ thẻ. Bài trả lời + trích dẫn bấm được + chip người. Streaming. | 1–2 ngày |
| **4. Cổng eval & bật** | `answer_eval` chạy 30 câu; đạt ngưỡng mới bật mặc định. | 1 ngày |
| **5. Dọn** | Xoá `hiring_need`/`ai_rank`/`ai_search`/`analysis_cache`/`semantic*`/`TitleSimilarity`; gỡ `scoring` khỏi đường trả lời (giữ cho `hiring/`); viết lại `tests_hero_flow`. Port sang RB/Prospect. | 1 ngày |

Tổng ~7–10 ngày công. GĐ 1–2 là phần quyết định chất lượng.

---

## 8. Cổng nghiệm thu — không bật khi chưa qua

Bộ 30 câu phủ đúng các kiểu đang hỏng:

- trình độ / bằng cấp ("cao đẳng", "thạc sĩ")
- trường & ngành học ("NEU", "Bách khoa", "học tài chính ngân hàng")
- tuổi & sắp xếp & giới hạn ("5 người ít tuổi nhất", "người nhiều kinh nghiệm nhất")
- đồng nghĩa / song ngữ ("quan hệ khách hàng" = RM = customer relationship)
- đếm & thống kê ("bao nhiêu người biết SQL")
- phủ định ("không cần biết tiếng Nhật")
- hỏi tiếp có tham chiếu ("so sánh 2 người đầu")
- **câu phải trả rỗng** ("tìm phi hành gia") — không được bịa

Chấm mỗi câu theo 4 tiêu chí:

| Tiêu chí | Đạt khi |
|---|---|
| **Đúng người** | Người đúng có mặt, người sai không có |
| **Đúng ràng buộc** | Tôn trọng `limit`, `sort_by`, phủ định |
| **Có nguồn** | Mọi khẳng định có `[n]` truy được về đoạn CV thật |
| **Thành thật** | Nói rõ chưa biết gì; không nhồi cho đủ số |

**Ngưỡng bật mặc định: ≥ 24/30 (80%) và 0 câu bịa nguồn.**

---

## 9. Rủi ro & cách chặn

| Rủi ro | Chặn bằng |
|---|---|
| Chậm hơn (3 lượt LLM thay vì 2) | ① và ③ dùng model flash; ② song song; stream ⑤ ngay từ token đầu → *cảm giác* nhanh hơn. Ngân sách thời gian tổng như `Router.BUDGET_SECONDS`. |
| Đắt hơn | Cache tầng ② theo (truy vấn chuẩn hoá + phiên bản kho). Không cache ⑤ (phụ thuộc ngữ cảnh). Đo token/lượt trong trace. |
| LLM bịa trích dẫn | ③ chỉ được trả `document_id` + **nguyên văn** trích từ đoạn đã gửi; CODE verify chuỗi trích có thật trong `CVChunk` trước khi cho vào `citations`. Không khớp → loại. |
| Xoá nhầm code `hiring/` đang dùng | Audit §3 đã chỉ ra; tách helper trước, xoá sau cổng eval. |
| Regression trong lúc chuyển | Engine mới chạy song song sau cờ; endpoint cũ còn nguyên tới khi qua cổng. |

---

## 10. Quyết định cần chốt trước khi code

1. **Bỏ hẳn thẻ ứng viên** trong câu trả lời AI — đồng ý? (màn `/talent` lọc truyền
   thống vẫn giữ thẻ như cũ, không đụng)
2. **Ngân sách độ trễ** chấp nhận được cho một câu trả lời sâu: 8s? 15s?
3. **Model cho chặng ⑤** — thử `deepseek-v4-pro` và `glm-5.2` rồi chọn theo mẫu vàng?
4. Ai soạn **30 câu hỏi + phán quyết**? (đây là hạng mục nghiệp vụ, nằm trên đường găng)

> **Đã chốt (02/09/2026)** — người dùng giao quyết định lại: (1) bỏ hẳn thẻ;
> (2) ngân sách 15s, bù bằng streaming có tiến độ từng chặng; (3) ⑤ dùng
> `deepseek-v4-pro`; (4) bộ 30 câu do Claude soạn, nằm trong
> `talent/management/commands/answer_eval.py`.

---

## 11. Nhật ký thi công — những gì kho thật dạy lại

Phần này ghi **những điều chỉ lộ ra khi chạy trên 786 hồ sơ thật**, không có
trong bản kế hoạch. Đây là lý do `answer_eval` tồn tại: test đơn vị luôn xanh vì
LLM bị giả lập, còn hai lỗi dưới đây đều nằm ngoài tầm nhìn của chúng.

### 11.1. ③ tràn token → hệ thống nói dối "kho không có ai"

Lần chạy đầu trên prod: ① đúng, ② tìm được **40 hồ sơ**, ③ trả về **0**, và ⑤ đi
nói với người dùng *"Kho không có ứng viên nào... Đã rà soát 0 hồ sơ"*. Sai mà
nghe rất thuyết phục — đúng kiểu sai tệ nhất.

Gốc: route ③ trỏ vào `deepseek-v4-flash`. Đó là model có bước suy nghĩ, mà
`providers.py` **cố tình bỏ** `reasoning_effort` cho mọi model `deepseek/*`
(chúng trả HTTP 400 khi thấy tham số này — xem `ai/providers.py`). Nó nghĩ hết
sạch 3500 token trước khi kịp mở ngoặc JSON, `finish_reason="length"`, parse ra
rỗng.

Bài học rút thành quy tắc: **chặng nào phải trả JSON thì không được dùng model bị
tước `reasoning_effort`.** Ghi lại ở migration `ai/0013`.

Sửa ở ba tầng, vì một tầng thôi thì lỗi tương tự sẽ lại im lặng:

1. Route ③ → `qwen/qwen3.6-flash` (tôn trọng `reasoning_effort="none"`).
2. `judge` đọc `Completion.truncated` thay vì cố parse JSON cụt; lô 20 → 8; lô
   hỏng thì chia đôi thử lại.
3. `JudgeReport.broken`: mọi lô hỏng = **chặng đọc gãy**, khác hẳn kho rỗng.
   `engine` truyền cờ xuống, ⑤ bị cấm nói "kho không có ai" ở tình huống đó.

### 11.2. Trích dẫn "đúng nửa đầu" vẫn được lưu nguyên

`answer_eval` bắt được: 4/18 trích dẫn không đối chiếu lại được với `CVChunk`,
dù ③ đã có bước verify.

Gốc: `_verify_quote` khớp được **nửa đầu** là chấp nhận, rồi lưu **nguyên** chuỗi
model viết. Model hay chép đúng đầu câu rồi tự diễn đạt phần đuôi — nên phần đuôi
bịa vẫn hiện ra cho người dùng dưới dạng trích dẫn nguyên văn.

Sửa: cắt dần từ cuối, chỉ giữ **tiền tố dài nhất thật sự có trong nguồn**. Quy
tắc chung: *bước kiểm chứng không được nới lỏng rồi vẫn lưu bản chưa kiểm.*

### 11.3. Tốc độ

Đo lần đầu: ~94–116s/câu. Phân rã: ① 2.2s · ② 5.4s · ③ ~48s · ⑤ phần còn lại.

③ chiếm phần lớn vì 5 lô chạy tuần tự. Các lô độc lập và chỉ gọi mạng nên cho
chạy song song (4 luồng — giữ vừa phải vì VPS 1 vCPU và bắn quá nhiều lượt cùng
lúc vào một khoá thì dính 429).

⑤ dùng `deepseek-v4-pro` (có bước suy nghĩ) nên chậm, nhưng ở đây **suy nghĩ là
thứ ta muốn** — và streaming khiến người dùng thấy chữ ngay, nên độ trễ cảm nhận
khác hẳn độ trễ đo được.
