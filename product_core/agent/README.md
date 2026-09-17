# MSB Radar — Prospect Agent

Agent chạy trên **GreenNode AgentBase**, làm phần việc mà LLM thực sự giỏi:
hiểu câu hỏi bằng lời của RM và diễn giải kết quả.

```text
01 INTELLIGENCE   GreenNode MaaS (z-ai/glm-5.2-hackathon)
02 CAPABILITIES   parse_prospect_query · validate_criteria · explain_ranking
03 RUNTIME        GreenNode AgentBase — cổng 8080, GET /health
```

---

## 1. Vì sao là một service riêng, không phải thêm một endpoint vào Hub

Hợp đồng Runtime của AgentBase quy định **cứng**: container phải lắng nghe cổng
`8080` và có `GET /health` trả 200. Hub (`server/`) đang bind `8000` với
healthcheck ở `/api/v1/health/`, và đang phục vụ một mục tiêu triển khai khác
(Oracle VPS qua `docker-compose.yml` + Caddy). Đổi cổng của Hub để chiều
AgentBase sẽ phá cấu hình đang chạy để lấy một thứ không liên quan.

Quan trọng hơn: **một agent nên nhỏ**. Đẩy cả monolith Django lên AgentBase
nghĩa là container phải cõng Postgres driver, ORM, admin, toàn bộ nghiệp vụ —
tốn Ví Tổng liên tục cho thứ 95% thời gian không dùng tới.

## 2. Vì sao agent KHÔNG chấm điểm

Agent này cố ý **không** tính `priority_score`, không xếp hạng, không quyết định
hành động. Những việc đó nằm ở `server/rb/scoring.py` và ở nguyên đó.

Lý do là nguyên tắc xuyên suốt dự án — *AI hiểu, CODE quyết* — cộng một lý do
thực tế: nhân đôi logic chấm điểm ra hai nơi là cách chắc chắn để hai nơi lệch
nhau, và lúc đó không ai trả lời được *"vì sao đề xuất này 82 điểm"*.

Nên ranh giới rất rõ:

```text
Agent  câu hỏi tự do → tiêu chí có cấu trúc      (LLM)
       tiêu chí → tiêu chí đã chuẩn hoá          (code, tất định)
       kết quả đã xếp hạng → lời giải thích      (LLM)

Hub    tìm kiếm · chấm 5 chiều · ngưỡng · Next Best Action
```

## 3. Chạy cục bộ

```bash
cd agent
python -m pip install -r requirements.txt
export LLM_API_KEY=...        # khoá GreenNode MaaS
export LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
export LLM_MODEL=z-ai/glm-5.2-hackathon
python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

Kiểm tra:

```bash
curl -s localhost:8080/health
curl -s -X POST localhost:8080/invocations \
  -H 'Content-Type: application/json' \
  -d '{"action":"parse_query","query":"Tìm 20 quản lý ở Hà Nội có contact, quan tâm thẻ tín dụng"}'
```

## 4. Không có khoá LLM thì vẫn chạy

Mọi hành động đều có nhánh dò từ khoá tất định. Thiếu `LLM_API_KEY`, hoặc
GreenNode timeout, agent vẫn trả kết quả dùng được và đánh dấu
`"mode": "fallback"`. Đây là cùng nguyên tắc với `server/ai/router.py`: một demo
sập vì mạng chập là một demo hỏng, còn một demo nói rõ *"đang chạy chế độ dự
phòng"* vẫn là một demo chạy.

## 5. Triển khai lên AgentBase

Xem `docs/GREENNODE.md` mục 6–7. Tóm tắt:

```bash
docker build --platform linux/amd64 -t <registry>/prospect-agent:<tag> .
bash ../skills/agentbase/scripts/cr.sh credentials docker-login
docker push <registry>/prospect-agent:<tag>
bash ../skills/agentbase/scripts/runtime.sh create \
  --name prospect-agent --image <registry>/prospect-agent:<tag> \
  --flavor 1x1-general --env-file .env --from-cr --poc <true|false>
```

Biến `GREENNODE_CLIENT_ID` / `GREENNODE_CLIENT_SECRET` / `GREENNODE_AGENT_IDENTITY`
do AgentBase **tự tiêm** vào container — không đặt tay trong `.env`.
