# Radar Agent Runtime

**Phase:** 14 — hoàn thành
**Master Plan:** mục 14, 41, 42
**Vị trí:** `server/agents/`

---

## 1. Điều KHÔNG làm ở đây, cố ý

Master Plan mục 41 vẽ ra một "Radar Agent Runtime" với danh sách tool — đọc bề
mặt thì giống một agent tool-calling kiểu function-calling: đưa cho LLM một bộ
công cụ, để nó tự quyết định gọi cái nào, theo thứ tự nào.

**Đây không phải thứ được xây.** Suốt từ Phase 6 tới Phase 13, một ranh giới
được giữ nhất quán và có tài liệu riêng ở mỗi chỗ áp dụng:

| Chỗ | Ranh giới |
|---|---|
| `talent/scoring.py` | LLM không chấm điểm — code tất định làm hết |
| `talent/semantic.py` | LLM chỉ trả một con số cho MỘT CẶP chức danh, không thấy người |
| `hiring/calibration.py` | Học từ phản hồi = chỉnh trọng số, không phải fine-tune |
| `hiring/outreach.py`, `rb/outreach.py` | AI soạn, **người bấm gửi** |
| `rb/routing.py` | Gợi ý sản phẩm dò từ khoá — không gọi LLM, không bịa sản phẩm |
| `social/intent.py` | LLM chấm ý định; ngưỡng quyết định hành động nằm ở code |

Một agent runtime để mô hình tự lập kế hoạch rồi gọi tool sẽ phá đúng ranh giới
đó ở chỗ hại nhất: **hành động có hậu quả thật** (tạo cơ hội, đổi trạng thái,
soạn thư gửi đi). Runtime này không làm việc đó.

---

## 2. Vậy "agent" ở đây nghĩa là gì

**Một chuỗi bước đã biết trước, viết bằng code — có quan sát được.**

```text
Trước Phase 14:
    talent/ai_search.py tự xây trace = [{"label":..., "detail":...}, ...]
    → chỉ tồn tại trong bộ nhớ một lượt gọi API, mất ngay sau khi trả response.
    → không ai trả lời được "tuần trước hệ thống chạy bao nhiêu lượt tìm,
      mất trung bình bao lâu, tỉ lệ lỗi bao nhiêu".

Sau Phase 14:
    Cùng đoạn code đó, cùng trình tự đó — chỉ thêm:
        with agent_runtime.run(AGENT_TALENT, goal=question, user=user) as run:
            ... y hệt logic cũ ...
            run.record(label, detail=detail)   # ghi lại, không quyết định
        run.finish(result_summary)
```

`agents/runtime.py` chỉ **bọc quanh** một đoạn code đã có sẵn để đo thời gian và
ghi lại. Nó không thay code đó làm việc, và không có nhánh rẽ nào phụ thuộc vào
việc ghi lại có thành công hay không — quan sát hỏng thì im lặng bỏ qua, nghiệp
vụ vẫn chạy tiếp (có test canh: giả lập CSDL sập giữa lúc chạy agent, nghiệp vụ
vẫn trả kết quả bình thường).

---

## 3. Hai domain agent

### Talent Radar Agent (`talent/ai_search.py`)

Không đổi logic — chỉ bọc thêm `agent_runtime.run()` quanh hàm `ai_search()` đã
có từ Phase 7, và ghi lại `trace` đã có sẵn thành `AgentStep`. 33 bài test cũ
của Phase 7 chạy qua không sửa gì, xác nhận hành vi không đổi.

### RB Radar Agent (`rb/agent.py`) — mới

Trước Phase 14, biết một đoạn văn bản có đáng chú ý cho bán lẻ không phải tự
ghép hai lời gọi (`/social/analyze/` rồi `/rb/suggest/`), và không có nơi nào
nói *"khách này đã có cơ hội đang mở chưa"* trước khi tạo thêm một cái trùng.

`POST /api/v1/rb/agent/analyze/` gộp bốn bước cố định thành một lượt có vết:

```text
1. detect_financial_need   social.intent.detect
2. resolve_person          khớp định danh mạnh — KHÔNG tự tạo người mới
3. match_product           rb.routing.suggest_products
4. prioritize_lead         có cơ hội nào đang mở rồi không
```

Và trả về đúng khuôn Agent UI (mục 42):

```json
{
  "intent": {"scores": {"rb": 1.0, "talent": 0.0}, "reason": "..."},
  "matched_person_name": "",
  "products": [{"product": "mortgage", "product_label": "Vay mua nhà", ...}],
  "existing_opportunities": [],
  "suggested_actions": ["Chưa khớp được khách hàng trong kho — cần thêm liên hệ..."],
  "trace": [...]
}
```

Chạy thật với Gemini (bài *"cần vay 500 triệu mua nhà"*): `rb=1.0`, gợi ý đúng
`Vay mua nhà`, và nói thẳng lý do chưa tạo được cơ hội — không giả vờ đã làm
xong việc mà thực ra chưa đủ dữ kiện.

**Không lưu gì**, cùng lý do với `social.views.analyze`: đây là công cụ xem
trước bằng văn bản của người thật. Muốn lưu thật thì đi qua
`POST /api/v1/social/ingest/`, nơi `rb.routing.route_signal()` có kiểm tra
trùng lặp trước khi tạo `RBOpportunity`.

---

## 4. `agents/tools.py` — siêu dữ liệu, không phải bảng điều phối

Cố ý **không có** `Tool.run(**kwargs)` để gọi động. Nếu có, bước tự nhiên tiếp
theo sẽ là "đưa registry cho LLM, để nó chọn gọi gì" — đúng ranh giới không
vượt qua.

`TOOLS` chỉ trả lời: tool tên X (theo đúng danh sách Master Plan mục 41) thật
ra là hàm nào trong code, nhãn tiếng Việt của nó là gì, có gọi LLM không. 16
tool — 7 dùng chung, 5 của Talent, 4 của RB — mỗi tool trỏ tới một hàm **đã tồn
tại từ trước** Phase 14 (`talent.scoring.score_person`, `rb.routing.suggest_products`,
`hiring.outreach.draft`...). Dùng để:

* Domain code ghi `AgentStep` với nhãn thống nhất, không mỗi nơi viết một câu
  khác nhau cho cùng một việc.
* Trang vận hành (Phase 15) liệt kê "hệ thống có những năng lực gì".
* Sinh tài liệu — bảng trên chính là `agents.tools.TOOLS`, không viết tay hai lần.

---

## 5. Quan hệ với `ai.models.LLMCall`

Hai tầng quan sát khác nhau, không thay thế nhau:

| | Tầng | Ví dụ |
|---|---|---|
| `LLMCall` | mỗi lượt gọi LLM riêng lẻ | 1 lượt dịch câu hỏi, 1 lượt giải thích |
| `AgentRun` + `AgentStep` | một lượt chạy trọn vẹn | 1 lượt tìm kiếm = 2 `LLMCall` + nhiều bước không gọi LLM |

Không có tầng `AgentRun` thì không trả lời được câu *"một lượt tìm kiếm mất bao
lâu tổng cộng, qua bao nhiêu bước"* — chỉ thấy từng mảnh `LLMCall` rời rạc.

---

## 6. GreenNode

Runtime không hardcode provider ở bất cứ đâu — mọi lượt gọi LLM bên trong các
bước agent đều đi qua `ai.router.complete()`, đúng lớp trừu tượng đã có từ
Phase 4. Khi có khoá GreenNode (Workshop #1, 28/08), agent chạy qua nó mà không
đổi một dòng code nào ở `agents/` hay `talent/ai_search.py` hay `rb/agent.py` —
chỉ đổi cấu hình ở trang Cài đặt AI.

---

## 7. API quan sát

Chưa có UI riêng (để dành cho Phase 15 — trang vận hành sẽ đọc trực tiếp từ
`AgentRun`/`AgentStep` qua Django ORM, không cần endpoint JSON riêng cho việc
này vì đối tượng xem là quản trị viên/vận hành, không phải người dùng cuối).

---

## 8. Test

* `agents/tests.py` — 13 bài, canh đúng thứ quan trọng: runtime không quyết
  định gì, lỗi bên trong vẫn nổ ra ngoài bình thường, quan sát hỏng không lan
  sang nghiệp vụ thật.
* `rb/tests.py::AgentTest` — 7 bài cho RB Radar Agent.
* `talent/tests_ai.py` — 33 bài cũ của Phase 7, không sửa gì, xác nhận Talent
  Radar Agent không đổi hành vi khi thêm quan sát.
