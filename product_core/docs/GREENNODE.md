# GreenNode AI Platform trong MSB Radar

**Master Plan:** mục 22, 54 · **Vị trí:** `server/ai/`
**Điều kiện giải:** *"Sản phẩm được xây dựng trên GreenNode AI Platform"* (Hacker Guide BTC)

---

## 1. Ba thành phần theo đúng khung của BTC

Hacker Guide định nghĩa một AI Agent gồm ba phần. Tài liệu này trình bày MSB
Radar theo đúng khung đó, bằng đúng từ vựng đó — để hội đồng không phải tự dịch
kiến trúc của chúng tôi sang tiêu chí của họ.

```text
01 INTELLIGENCE      GreenNode MaaS — z-ai/glm-5.2-hackathon
                     Hiểu ngôn ngữ, bóc tách nhu cầu, diễn giải.

02 CAPABILITIES      Bộ công cụ nghiệp vụ của MSB Radar
                     search_people · parse_hiring_need · detect_intent ·
                     suggest_products · score_opportunity · recommend_action

03 RUNTIME           GreenNode AgentBase — container có endpoint công khai
                     (xem mục 4: trạng thái triển khai)
```

---

## 2. Ranh giới kiến trúc — ai chạy ở đâu

MSB Radar **tách compute khỏi dữ liệu**. Đây là quyết định có chủ đích, không
phải chắp vá:

```text
┌────────────────────────────┐
│  GreenNode AgentBase       │  Agent / backend compute
│  + GreenNode MaaS          │  Toàn bộ lời gọi LLM
└──────────┬─────────────────┘
           │  TLS, IP allow-list
    ┌──────┴───────┬──────────────────┐
    ▼              ▼                  ▼
┌─────────┐  ┌──────────────┐  ┌──────────────┐
│ Oracle  │  │ Cloudflare   │  │  Người dùng  │
│  VPS    │  │     R2       │  │   (trình     │
│Postgres │  │  File CV     │  │   duyệt)     │
└─────────┘  └──────────────┘  └──────────────┘
```

**Vì sao tách:**

| Lý do | Chi tiết |
|---|---|
| Tách rủi ro | Ví Tổng GreenNode cạn = container sập. Dữ liệu ở Oracle/R2 không mất theo, container mới nối lại được ngay. |
| Container gọn | Runtime tính phí liên tục; không cõng thêm Postgres và kho file thì rẻ và ổn định hơn. |
| Giống pilot thật | Một pilot MSB thật sẽ không chấp nhận PII ứng viên nằm trong filesystem tạm của container hackathon. |

**Ranh giới này phải được nói rõ trên slide.** Một kiến trúc tách mà không giải
thích sẽ mời giám khảo đoán nhầm *"đội này chỉ gọi API thôi"* — đúng cái ấn
tượng cần tránh nhất.

---

## 3. GreenNode làm gì trong sản phẩm

### 3.1. Mặc định trong code, không phải trong cấu hình

`server/ai/router.py`:

```python
DEFAULT_ORDER = ["greennode", "openai", "gemini", "deepseek"]
```

Thứ tự ưu tiên khi chọn nhà cung cấp:

```text
1. Provider riêng cho từng tác vụ    MSB_AI_PROVIDER_<TASK>       (env)
2. Cấu hình trong CSDL               trang Cài đặt AI              ← thắng env
3. Provider mặc định                 MSB_AI_PROVIDER_DEFAULT      (env)
4. Chuỗi dự phòng                    MSB_AI_PROVIDER_FALLBACK     (env)
```

Có một cơ chế bảo vệ đáng nói: đổi `MSB_AI_PROVIDER_DEFAULT` sang nhà cung cấp
khác mà **không** đặt `FALLBACK` sẽ **không** làm GreenNode biến mất khỏi chuỗi
— router tự thêm lại phần còn thiếu của `DEFAULT_ORDER` vào cuối. Người vận
hành không thể vô tình loại GreenNode ra chỉ bằng một biến môi trường đặt sai.

### 3.2. Bốn luồng người dùng đi qua GreenNode

| Luồng | Việc GreenNode làm | Việc CODE làm |
|---|---|---|
| **Talent — bóc tách JD** | Câu hỏi/JD tự do → tiêu chí có cấu trúc | Tìm kiếm, chấm điểm, xếp hạng |
| **Talent — giải thích kết quả** | Diễn giải vì sao hồ sơ này khớp | Gán nhãn FACT / INFERENCE / UNKNOWN |
| **Social — nhận diện ý định** | Bài đăng → nhãn ý định đa chiều | Khớp Person, ngưỡng, định tuyến |
| **RB — hiểu cơ hội** | Tóm tắt nhu cầu, soạn lời chào | Chấm 5 chiều, chọn Next Best Action |

### 3.3. Ranh giới không đổi: **AI hiểu, CODE quyết**

Đây là điều quan trọng nhất trong tài liệu này.

```text
LLM ĐƯỢC làm            LLM KHÔNG ĐƯỢC làm
─────────────────       ──────────────────────────────
hiểu ngôn ngữ           tạo ra điểm số
tóm tắt                 quyết định ngưỡng
diễn giải               chọn mã hành động
soạn bản nháp           gộp định danh khi có xung đột
                        tự gửi bất cứ thứ gì ra ngoài
```

Cụ thể: `rb/scoring.py` tính điểm ưu tiên bằng công thức cố định, và
`OpportunitySuggestion.priority_score` **không bao giờ** đến từ một lượt gọi
LLM. Nếu GreenNode hỏng, mọi luồng vẫn chạy bằng nhánh dò từ khoá tất định và
giao diện nói rõ đang ở chế độ dự phòng.

Đây không phải hạn chế kỹ thuật — đây là điều làm sản phẩm dùng được trong ngân
hàng. Một điểm số do LLM sinh ra là điểm số không kiểm toán được.

---

## 4. Trạng thái triển khai AgentBase

| Hạng mục | Trạng thái |
|---|---|
| Gọi MaaS qua provider abstraction | ✅ Đã chạy (`ai/providers.py`) |
| GreenNode là mặc định, có cơ chế chống tuột | ✅ Đã chạy (`ai/router.py`) |
| Quan sát theo từng nhà cung cấp | ✅ Đã chạy — xem mục 5 |
| Bộ skill AgentBase trong repo | ✅ Đã có (`skills/agentbase*`) |
| Agent service đúng hợp đồng Runtime | ✅ **Đã có** — `agent/`, cổng 8080 + `GET /health`, 18 test |
| Container chạy thật, có endpoint công khai | ⬜ Cần tài khoản + ví của đội |

**Việc cần người thật làm** (không tự động hoá được, và không nên):
triển khai lên AgentBase tiêu tiền từ Ví Tổng của đội và cần IAM credentials.
Quy trình nằm ở `greennode_hackathon_rules.md` mục 9 và bộ skill
`skills/agentbase-deploy/`.

---

## 5. Bằng chứng đo được

`GET /api/v1/ai/usage/` trả về, **tách theo từng nhà cung cấp**:

```json
{
  "primary_provider": "greennode",
  "fallback_calls": 3,
  "total_calls": 142,
  "failed_calls": 4,
  "by_provider": [
    { "provider": "greennode", "calls": 139, "failed": 2,
      "success_rate": 0.986, "avg_latency_ms": 1840,
      "total_tokens": 214503 }
  ]
}
```

Ba chi tiết trong cách đo:

**Độ trễ chỉ tính lượt thành công.** Lượt timeout luôn bằng đúng ngưỡng chờ
(25 giây), gộp vào sẽ làm một nhà cung cấp *hay hỏng* trông như *chậm đều đặn* —
hai vấn đề cần hai cách xử lý khác nhau.

**`fallback_calls` là con số nói lên độ tin cậy.** Thiếu nó thì "GreenNode là
mặc định" chỉ là một dòng cấu hình, không phải một tuyên bố kiểm chứng được.

**Tỷ lệ thành công tính trên lượt của chính nhà cung cấp đó**, không phải trên
tổng — để so sánh được giữa các nhà cung cấp.

---

## 6. Hợp đồng Runtime — việc cần làm trước khi deploy

`skills/agentbase/references/runtime-contract.md` quy định **cứng** hai điều:

```text
1. Container lắng nghe cổng 8080
2. GET /health trả HTTP 200 khi sẵn sàng
```

Hub hiện tại **không** khớp: `server/Dockerfile` bind gunicorn ở `0.0.0.0:8000`
và healthcheck ở `/api/v1/health/`.

**Không sửa Hub cho khớp.** Hub đang phục vụ đúng một mục tiêu triển khai khác
(Oracle VPS qua `docker-compose.yml`), và đổi cổng ở đó sẽ phá cấu hình Caddy
đang chạy.

**Đã dựng service riêng: `agent/`** — xem `agent/README.md`.

```text
GET  /health       →  200, không gọi ra ngoài
POST /invocations  →  action = parse_query | explain
```

Ranh giới của agent, và đây là phần quan trọng nhất:

| Agent làm | Hub làm |
|---|---|
| câu hỏi tự do → tiêu chí có cấu trúc (LLM) | tìm kiếm |
| tiêu chí → tiêu chí đã chuẩn hoá (code) | chấm 5 chiều |
| kết quả đã xếp hạng → lời giải thích (LLM) | ngưỡng, Next Best Action |

Agent **không** chấm điểm. Nhân đôi logic chấm điểm ra hai nơi là cách chắc
chắn để hai nơi lệch nhau, và lúc đó không ai trả lời được *"vì sao đề xuất
này 82 điểm"*. `agent/tests/test_agent.py` có một bài canh danh mục sản phẩm
của agent không lệch khỏi `server/rb/models.py`.

Mọi hành động đều có nhánh dò từ khoá tất định: thiếu khoá hoặc GreenNode
timeout thì agent vẫn trả kết quả dùng được và đánh dấu `"mode": "fallback"`.

---

## 7. CI/CD lên AgentBase

Bộ script trong `skills/agentbase/scripts/` là REST thuần, xác thực bằng
client-credentials — chạy được trong GitHub Actions không cần tương tác:

```text
docker build --platform linux/amd64
  → cr.sh credentials docker-login      (CR có sẵn của AgentBase)
  → docker push
  → runtime.sh update $ID --image … --from-cr
  → poll runtime.sh get $ID cho tới ACTIVE
  → curl -f <endpoint>/health
  → lỗi thì runtime.sh update về image trước
```

Bí mật cần đặt trong GitHub Actions: `GREENNODE_CLIENT_ID`,
`GREENNODE_CLIENT_SECRET` (tài khoản dịch vụ gọi API quản trị — **khác** với
credentials mà AgentBase tự tiêm vào container lúc chạy).

Chỉ trigger khi merge vào `main` hoặc gắn tag, **không phải mỗi commit**: mỗi
lần deploy tiêu Ví Tổng, và ví cạn thì container sập — kể cả giữa Hackday.

---

## 8. Quản lý ví — rủi ro vận hành

```text
Ví Tổng (Wallet Credits)   container runtime, registry, log
Ví MaaS                    lời gọi LLM
```

Ba quy tắc, theo đúng khuyến cáo của BTC:

1. **Chuyển tiền Tổng → MaaS là không hoàn lại.** Chuyển từng đợt nhỏ theo nhu
   cầu, không chuyển hết một lần.
2. **Giữ tối thiểu 2.000.000 VNĐ trong Ví Tổng.** Ví Tổng về 0 = agent sập vì
   thiếu tài nguyên runtime.
3. **Ước tính token trước khi diễn tập.** Một lượt demo đầy đủ × 10 lần diễn
   tập + lần thi thật phải nằm trong hạn mức MaaS còn lại.

---

## 9. Câu nói cho pitch

> **GreenNode là lớp trí tuệ biến nhu cầu tuyển dụng và tín hiệu mạng xã hội
> dạng thô thành hành động có cấu trúc, giải thích được — trong khi MSB Radar
> giữ toàn bộ việc chấm điểm và quyết định nghiệp vụ ở mã nguồn tất định.**

Sau khi Task 8.5 hoàn tất, thêm một câu về Runtime:

> **RB Opportunity Agent của MSB Radar chạy native trên GreenNode AgentBase —
> không chỉ được gọi như một API.**
