# Lớp nhà cung cấp LLM

**Master Plan:** mục 7.1, 41
**Vị trí:** `server/ai/`

---

## 1. Phát hiện quyết định thiết kế

**Cả bốn nhà cung cấp đều nói giao thức OpenAI `/chat/completions`** — kể cả GreenNode.

Nghĩa là chỉ cần **một adapter với bốn cấu hình**, không phải bốn lớp riêng. Và quan
trọng hơn: **adapter GreenNode đã viết xong và có test**, dù chưa ai có khoá. Sau
Workshop #1 (28/08) chỉ cần điền ba giá trị là chạy — không phải chờ để viết code.

| Nhà cung cấp | Base URL | Model mặc định |
|---|---|---|
| **GreenNode** | `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1` | *(lấy ở workshop)* |
| OpenAI | `https://api.openai.com/v1` | `gpt-5.5` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-3.5-flash` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-v4-flash` |

Gemini dùng endpoint tương thích OpenAI của Google chứ không phải API gốc — để khỏi
nuôi thêm một adapter chỉ vì một nhà cung cấp.

> **Mã model là cấu hình, không phải code.** Chúng đổi vài tháng một lần: `deepseek-chat`
> và `deepseek-reasoner` đã khai tử ngày 24/07/2026, thay bằng `deepseek-v4-*`. Giá trị
> mặc định ở đây đúng vào tháng 8/2026; đổi bằng biến môi trường.

### Đo thật với khoá Gemini (19/08/2026)

Cùng một prompt — dịch câu hỏi tuyển dụng thành JSON tiêu chí, đúng tác vụ của Phase 7:

| Model | Độ trễ | Kết quả |
|---|---|---|
| `gemini-2.5-flash` | 4,0s | JSON bọc trong ```` ```json ```` |
| **`gemini-3.5-flash`** ← mặc định | 6,8s | **JSON sạch** |
| `gemini-3.6-flash` | **27,3s** | Chậm gấp 4 lần |
| `gemini-3.7-flash`, `gemini-flash-latest` | — | **HTTP 503** |

**Mới hơn không có nghĩa là tốt hơn.** Đây chính là lý do mã model phải đổi được bằng
cấu hình: nếu hardcode "bản mới nhất", hệ thống sẽ tự chọn model chậm gấp bốn hoặc model
đang 503 ngay giữa buổi demo.

`response_format={"type": "json_object"}` **hoạt động** với Gemini và cho JSON sạch
không có hàng rào markdown — Phase 7 nên dùng nó thay vì tự bóc chuỗi ```` ``` ````.

Độ trễ 4–7 giây là đáng kể với thao tác tương tác. Master Plan mục 42 đã yêu cầu hiện
tiến trình agent chứ không để màn hình đứng im — đo này xác nhận yêu cầu đó là cần thật.

Không dùng SDK của từng hãng: bốn SDK là bốn bộ phụ thuộc, bốn lịch phát hành và bốn
kiểu lỗi khác nhau, trong khi thứ cần chỉ là một lời gọi POST JSON.

---

## 2. Cách dùng

```python
from ai.router import complete

result = complete(
    [{"role": "user", "content": "Tóm tắt CV này..."}],
    task="talent_search",
)
print(result.text, result.provider, result.total_tokens)
```

Nghiệp vụ **không bao giờ** biết phía sau là ai. Talent Agent, RB Agent, bộ phân loại
ý định đều gọi qua đây.

---

## 3. Cấu hình

Hai đường, **trang cài đặt thắng biến môi trường**.

### 3.1. Trang cài đặt trên Hub (khuyến nghị)

Đăng nhập Hub → tab **Cài đặt AI**. Ở đó bật/tắt từng nhà cung cấp, nhập khoá, đổi mã
model, đặt thứ tự ưu tiên, bấm **Kiểm tra kết nối**, và xem mức sử dụng token.

Thay đổi **có hiệu lực ngay**, không cần khởi động lại container.

#### Khoá API được bảo vệ thế nào

| | |
|---|---|
| Trong CSDL | **Mã hoá** bằng Fernet (`ai/crypto.py`). Bản dump/backup lọt ra ngoài không lộ khoá. |
| Qua API | **Chỉ dạng che** (`sk-day••••••••`). Không có endpoint nào trả khoá đầy đủ. |
| Trang quản trị Django | Không có ô nhập khoá — chỉ đặt được qua API, nơi khoá được mã hoá trước khi ghi. |

Khác với khoá API của Edge: chỗ đó Hub chỉ cần *kiểm tra* nên lưu hash là đủ. Ở đây Hub
phải *dùng lại* khoá để gọi nhà cung cấp, nên bắt buộc mã hoá hai chiều.

Khoá mã hoá lấy từ `MSB_AI_CONFIG_KEY`, không có thì dẫn xuất từ `SECRET_KEY`.

> ⚠️ **Đổi `SECRET_KEY` mà không đặt `MSB_AI_CONFIG_KEY` thì các khoá đã lưu không giải
> mã được nữa.** Hệ thống không sập — nó hiện *"khoá hỏng — nhập lại"* trên trang cài
> đặt. Đặt `MSB_AI_CONFIG_KEY` riêng để tách hai vòng đời đó ra.

Một chi tiết quan trọng trong biểu mẫu: **ô khoá luôn để trống**. Gõ vào = đặt khoá
mới; để trống = giữ nguyên khoá đang dùng. Nếu không làm vậy thì một lần lưu form để
sửa mã model sẽ xoá mất khoá.

### 3.2. Biến môi trường

Dùng cho lần triển khai đầu, hoặc chạy script ngoài Django. Chỉ cần đặt khoá; phần còn
lại có mặc định.

File `.env` đặt ở **gốc repo** hoặc trong `server/`. Django đọc cả hai (file trong
`server/` thắng); Docker Compose chỉ đọc file ở gốc. Hỗ trợ cả hai vì nếu chỉ nhận một
chỗ thì sẽ có người sửa đúng biến ở sai file rồi mất cả buổi tìm hiểu.

> ⚠️ **Trên Windows, ghi `.env` bằng `Set-Content -Encoding utf8` sẽ thêm BOM** và
> django-environ báo `Invalid line: ﻿DEBUG=True`. Dùng
> `[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))`
> hoặc soạn bằng trình soạn thảo. Cùng cái bẫy với file `.ps1` (xem HUB.md §7).

```powershell
# Bắt đầu ngay bây giờ — chưa cần GreenNode
$env:MSB_AI_DEEPSEEK_API_KEY = "sk-..."
$env:MSB_AI_OPENAI_API_KEY   = "sk-..."
$env:MSB_AI_GEMINI_API_KEY   = "AIza..."
```

Sau Workshop #1:

```powershell
$env:MSB_AI_GREENNODE_API_KEY = "..."       # khoá phải ở trạng thái ACTIVE
$env:MSB_AI_GREENNODE_MODEL   = "..."       # xem mục 6 để lấy danh sách
```

### Xoay vòng nhiều khoá cho cùng một nhà cung cấp

**Hạn mức tốc độ tính theo TỪNG KHOÁ, không theo tài khoản.** Ba khoá Gemini là hạn mức
gấp ba, không phải đổi gì trong nghiệp vụ.

Nhập nhiều khoá cách nhau bởi dấu phẩy, chấm phẩy hoặc xuống dòng — cả ở trang cài đặt
lẫn biến môi trường:

```bash
MSB_AI_GEMINI_API_KEY=AIza-khoa-1,AIza-khoa-2,AIza-khoa-3
```

Hai cơ chế **khác nhau và bổ sung cho nhau**:

| | Đổi cái gì | Chữa được gì |
|---|---|---|
| **Xoay khoá** | Cùng nhà cung cấp, đổi khoá | Hết hạn mức |
| **Chuyển provider** | Đổi hẳn nhà cung cấp | Nhà cung cấp sập |

Xoay khoá diễn ra **trước**: còn khoá khác của cùng nhà cung cấp thì dùng nốt, hết mới
chuyển. Chuyển provider ngay khi một khoá hết hạn mức là bỏ phí hạn mức của các khoá còn lại.

Ba loại lỗi, ba cách xử lý khác hẳn:

| Lỗi | Xử lý | Vì sao |
|---|---|---|
| **429** hết hạn mức | Cho khoá nghỉ 60s rồi dùng lại | Hạn mức sẽ hồi; tắt là vứt đi một khoá còn tốt |
| **401/403** khoá sai | **Tắt hẳn** | Thử lại chỉ tổ phí và làm rác nhật ký |
| **5xx** | Không phạt khoá | Lỗi của nhà cung cấp; đổi khoá vô ích |

Xoay vòng **đều** thay vì luôn lấy khoá đầu: dùng cạn khoá đầu rồi mới sang khoá hai
nghĩa là khoá đầu lúc nào cũng sắp hết hạn mức còn các khoá kia nhàn rỗi.

> **Một chi tiết dễ bỏ sót:** nếu *mọi* khoá đều đang nghỉ, pool vẫn trả về khoá hết
> nghỉ sớm nhất chứ không trả rỗng. Thời gian nghỉ chỉ là phỏng đoán — cửa sổ hạn mức
> có thể đã trôi qua. Không có lối này thì với nhà cung cấp **một khoá**, vòng thử lại
> 3 giây của router không bao giờ thành công vì khoá còn nghỉ 60 giây. Hai cơ chế đánh
> nhau, và test đã bắt được.

Khoá trùng nhau bị gộp làm một — đã kiểm chứng với khoá thật.

Trang cài đặt hiện trạng thái từng khoá: sẵn sàng / đang nghỉ bao nhiêu giây / đã tắt,
kèm số lượt dùng và số lần bị chặn. Không hiện thì người vận hành thấy "có 3 khoá" mà
không biết 2 trong số đó đã hỏng.

### Chọn nhà cung cấp

| Biến | Tác dụng |
|---|---|
| `MSB_AI_PROVIDER_DEFAULT` | Ưu tiên chung. Không đặt → `greennode` |
| `MSB_AI_PROVIDER_FALLBACK` | Chuỗi dự phòng, phân cách bằng dấu phẩy |
| `MSB_AI_PROVIDER_<TAC_VU>` | Ghi đè cho một tác vụ, vd `MSB_AI_PROVIDER_TALENT_SEARCH` |
| `MSB_AI_<NHA_CC>_MODEL` | Đổi mã model mặc định của nhà cung cấp |
| `MSB_AI_<NHA_CC>_BASE_URL` | Đổi endpoint |
| `MSB_AI_<NHA_CC>_TIMEOUT` | Giây |
| `MSB_AI_<NHA_CC>_MODEL_<TAC_VU>` | **Model theo từng đề bài** — vd `MSB_AI_GREENNODE_MODEL_TALENT_SEARCH=qwen/qwen3.6-flash` |
| `MSB_AI_MODEL_<TAC_VU>` | Như trên nhưng dùng chung mọi nhà cung cấp GreenNode-MaaS (greennode + agentbase) |

Tác vụ `assistant_intent` (intent router — xem `docs/RADAR_AI_MASTER_PLAN.md §17`)
dùng chung chuỗi provider; đặt `MSB_AI_PROVIDER_ASSISTANT_INTENT` nếu muốn ép một
model nhanh riêng cho bước phân loại.

#### Chọn model theo đề bài (GreenNode MaaS phục vụ nhiều model)

`GET {base_url}/models` trên khoá hiện tại trả: `z-ai/glm-5.2-hackathon`,
`qwen/qwen3.6-flash`, `deepseek/deepseek-v4-flash`, `deepseek/deepseek-v4-pro`,
`google/gemma-4-31b-it`. Đo thực tế lượt parse ngắn: **qwen-flash 0.7s** vs glm 4.6s.
Router nhận `model` theo `MSB_AI_[<NHÀ_CC>_]MODEL_<TÁC_VỤ>` và truyền xuống provider
(người gọi chỉ định `model=` thì thắng pin). `reasoning_effort` **tự bị bỏ** cho
model `deepseek/*` (chúng trả HTTP 400 khi thấy tham số này).

Gợi ý theo đề bài:

| Tác vụ | Model | Vì sao |
|---|---|---|
| `talent_search` (parse), `assistant_intent`, `assistant_agent` | `qwen/qwen3.6-flash` | trích xuất có cấu trúc, cần nhanh, gọi nhiều lượt |
| `talent_explain` (rerank hồ sơ), `assistant_web` | `deepseek/deepseek-v4-flash` | lý luận trên dossier / kết quả web |
| `assistant_conversation` | `z-ai/glm-5.2-hackathon` (mặc định) | chất lượng hội thoại tiếng Việt; là model tranh giải |

**GreenNode đứng đầu mặc định** — vừa là hạ tầng ban tổ chức, vừa là điều kiện tranh
giải *Best Use of Green Node AI Platform*. Chưa có khoá thì nó **tự bị bỏ qua**, nên
phát triển ngay bây giờ với GPT/Gemini/DeepSeek vẫn chạy bình thường.

### `agentbase` — đường tới GreenNode qua AgentBase (nhanh hơn)

`DEFAULT_ORDER` có `agentbase` **ngay sau** `greennode`. Đây KHÔNG phải nhà cung cấp
mới — là lối gọi GreenNode MaaS **đi qua Prospect Agent trên GreenNode AgentBase**
(`agent/app.py`, action `chat`). Vì agent nằm TRONG datacenter GreenNode, cạnh
endpoint MaaS, nên khi Hub gọi MaaS trực tiếp qua internet bị chậm/treo (đo thực
tế: 45s vs 10s), lượt gọi rơi sang `agentbase` thay vì nhảy sang OpenAI.

| Biến | Tác dụng |
|---|---|
| `MSB_AGENT_ENDPOINT` | URL runtime AgentBase. Có → `agentbase` khả dụng; không → tự bỏ qua |
| `MSB_AI_AGENTBASE_TIMEOUT` (hoặc `MSB_AGENT_TIMEOUT`) | Ngưỡng chờ, mặc định 60 |
| `MSB_AI_PROVIDER_<TASK>=agentbase,greennode` | Ép tác vụ nặng (`talent_search`, `talent_explain`) ưu tiên đường AgentBase |

`agentbase` không stream (router tự bỏ qua nó ở luồng SSE hội thoại) và không có
khoá phía Hub (agent tự giữ khoá GreenNode). Circuit breaker của router áp cho nó
như mọi nhà cung cấp khác.

### Radar assistant (intent router + web search)

Cả hai tầng này **độc lập nhà cung cấp LLM** — chúng đi qua `ai/router.py` /
`ai/adapter.py` nên bộ não nào (GreenNode/OpenAI/Gemini/DeepSeek) cũng chạy.

| Biến | Mặc định | Tác dụng |
|---|---|---|
| `ASSISTANT_INTENT_ROUTER` | `1` | Gọi model nhỏ phân loại câu hỏi (search / hội thoại / web) qua router. `0` → heuristic thuần |
| `ASSISTANT_WEB_SEARCH` | `0` | Cho Radar tra web khi câu hỏi cần dữ kiện ngoài kho |
| `ASSISTANT_WEBSEARCH_BACKENDS` | *(rỗng)* | Thứ tự thử backend, vd `brave,gemini_grounding`. Rỗng → `tavily,brave,google_cse,gemini_grounding` |
| `MSB_AI_WEBSEARCH_MODEL` | `MSB_AI_GEMINI_MODEL` → `gemini-3.5-flash` | Model cho backend `gemini_grounding` |
| `ASSISTANT_TOOLS` | `0` | Bật vòng lặp gọi tool (kỹ năng) trong lượt hội thoại — `ai/agent.py` + `ai/toolset.py`. Tool đều chỉ-đọc/đề-xuất, lọc RBAC. `0` → trả lời một lượt như cũ |
| `ASSISTANT_TOOL_MAX_STEPS` | `4` | Trần số vòng model↔tool trong một lượt |
| `ASSISTANT_TOOLS_TIER3` | `0` | Bật riêng tool tier 3 (`draft_outreach` trả bản nháp, `enrich_company_from_web`). Chỉ hiệu lực khi `ASSISTANT_TOOLS=1` |
| `ASSISTANT_GRAPH` | `0` | Dùng `ai/graph_agent.py` (engine `ai/graph.py` tự viết, 0 dep) thay vòng lặp tay `ai/agent.py`. Cùng hợp đồng, thay được nhau |

**Backend web** — `web_answer` thử lần lượt theo thứ tự, backend nào ra kết quả
thì dùng (backend lỗi runtime → lùi tiếp):

| Backend | Cấu hình | Kiểu | Ghi chú |
|---|---|---|---|
| `searxng` | `SEARXNG_URL` | tự chủ, **không khoá** | Instance SearXNG Radar tự dựng (Docker, `--profile searxng`). Ổn định nhất trong nhóm không-khoá |
| `duckduckgo` | *(mặc định bật)* | tự chủ, **không khoá** | Đọc thẳng HTML DuckDuckGo, không gói phụ thuộc. Tắt bằng `ASSISTANT_WEBSEARCH_DDG=0`. Kém ổn định hơn (DDG có thể chặn IP máy chủ) |
| `tavily` | `TAVILY_API_KEY` | generic có khoá | free tier |
| `brave` | `BRAVE_SEARCH_API_KEY` | generic có khoá | |
| `google_cse` | `GOOGLE_CSE_KEY` + `GOOGLE_CSE_CX` | generic có khoá | Google Programmable Search |
| `gemini_grounding` | `MSB_AI_GEMINI_API_KEY` | grounded | Gemini tự tìm + tự trả lời. Fallback cuối |

Nhóm không-khoá + có-khoá chỉ trả *kết quả thô* → **bộ não hiện hành tự tổng hợp**
(mọi nhà cung cấp đều chạy). `gemini_grounding` đứng cuối vì nó tự viết câu trả
lời bằng Gemini. Kết quả web bọc `prompt_guard` trước khi đưa cho bộ não. Nhờ
`duckduckgo` bật sẵn, web search **chạy ngay khi `ASSISTANT_WEB_SEARCH=1`**, không
cần khoá hay container nào.

Câu hỏi có PII (email/điện thoại/số định danh) hoặc prompt-injection **không bao giờ**
đi ra web — bị hạ về hội thoại thường. Chỉ câu người dùng gõ được gửi đi (không kèm
hồ sơ ứng viên, evidence hay memory).

---

## 4. Phân loại lỗi và chuyển dự phòng

| Tình huống | Lớp lỗi | Chuyển provider? |
|---|---|---|
| Mất mạng, timeout | `LLMUnavailable` | ✅ |
| HTTP 429, 5xx | `LLMUnavailable` | ✅ |
| HTTP 401/403 | `LLMAuthError` | ❌ |
| HTTP 400/404 (sai model, sai đường dẫn) | `LLMError` | ❌ |

**Khoá sai không được âm thầm chuyển sang nhà cung cấp khác.** Nếu chuyển, lỗi cấu
hình bị giấu đi và hoá đơn nhảy sang một nhà cung cấp mà không ai biết. Tương tự với
sai tên model: thử lại ở chỗ khác chỉ tốn thời gian và tiền.

### Trần thời gian cho cả lượt gọi

`Router.BUDGET_SECONDS = 25` (đổi bằng `MSB_AI_BUDGET_SECONDS`), tính cho **toàn
bộ** một lượt `complete()` — kể cả chuyển nhà cung cấp và thử lại.

Không có trần này, trường hợp xấu nhất là **4 nhà cung cấp × 60 giây × 2 vòng ≈ 8
phút** màn hình đứng, mà một lượt tìm bằng AI gọi hai lần, thành 16 phút. Trước
ban giám khảo, treo 16 phút tệ hơn hẳn báo lỗi sau 25 giây rồi lùi về dò từ khoá.
Mạng hội trường chập chờn không phải giả định xa vời.

Hai chi tiết dễ bỏ sót khi làm phần này:

* **Thời gian chờ từng lượt bị ép theo ngân sách còn lại.** Đặt trần tổng mà vẫn
  để mỗi lượt chờ 60 giây thì trần tổng không có tác dụng gì.
* **Sắp hết giờ thì không đợi 3 giây để thử lại nữa.** Đợi rồi thử lại chỉ có
  nghĩa nếu còn đủ thời gian cho lượt sau thật sự chạy xong, chứ không phải để
  hết giờ giữa chừng.

---

## 5. Nhật ký và chi phí

Mọi lượt gọi — kể cả lượt thất bại — được ghi vào bảng `LLMCall`: provider, model, tác
vụ, số token, độ trễ, lỗi.

Ba lý do:
1. **Chi phí.** Token là tiền; không đo thì cuối tháng mới biết.
2. **Quan sát.** Agent chậm hoặc trả sai — cần biết provider/model nào.
3. **Giải Best Use of GreenNode.** Giám khảo hỏi hệ thống dùng GreenNode ra sao thì đây
   là câu trả lời có số liệu, không phải lời kể.

Xem tại `/admin/ai/llmcall/`. Ghi nhật ký hỏng **không** làm hỏng lời gọi AI.

---

## 6. Lấy mã model của GreenNode sau workshop

```python
from ai.providers import build_provider, list_models
print(list_models(build_provider("greennode")))
```

Hoặc trực tiếp:

```bash
curl https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1/models \
  -H "Authorization: Bearer $MSB_AI_GREENNODE_API_KEY"
```

Lưu ý từ tài liệu GreenNode: **khoá API mới tạo ở trạng thái `pending`, phải đợi
chuyển sang `ACTIVE` mới dùng được.** Tính phí bằng credit-token (1 credit = 1 VNĐ).

---

## 7. Còn thiếu

- [ ] `embed()` cho vector search — chỉ thêm nếu benchmark chứng minh cần (Master Plan mục 43)
- [ ] Truyền phát (streaming) cho SSE tiến trình agent (Master Plan mục 42) — hiện `talent/ai_search.py`
  trả cả mảng `trace` một lần khi xong, không đẩy dần từng bước
- [x] ~~Gọi công cụ (tool calling)~~ — **cố ý không làm.** Phase 14 (`docs/AGENT_RUNTIME.md`) quyết định
  không xây vòng lặp để LLM tự chọn công cụ: `agents/tools.py` chỉ là bảng tra cứu tên → hàm, không có
  `Tool.run()`, vì đó chính là hạt giống của kiểu LLM-tự-quyết mà nguyên tắc "LLM diễn giải, code quyết
  định" của dự án cấm. Tham số `tools` của lớp provider vẫn tồn tại (một số nhà cung cấp hỗ trợ) nhưng
  không có mã nào trong dự án dùng tới nó, và đó là chủ đích chứ không phải việc còn dang dở.
- [ ] Bảng giá để quy token thành tiền

---

## Nguồn

- [Kết nối OpenAI-compatible với GreenNode MaaS](https://docs.greennode.ai/vn/ai-stack/agent-base/ai-coding/ket-noi-openai-compatible-voi-maas)
- [Model as a Service — GreenNode Docs](https://docs.greennode.ai/vn/ai-stack/ai-platform/model-as-a-service)
- [DeepSeek API Docs](https://api-docs.deepseek.com/)
- [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)
- [OpenAI models](https://developers.openai.com/api/docs/models/all)
