# Runbook — bật People Intelligence (Giai đoạn 2–6) trên production

Trạng thái code: **xong, có test, chạy trên dev**. Việc còn lại là hạ tầng + dữ liệu +
phê duyệt. Master Plan §15 bước 6–10, §19.

---

## 0. Tiền đề

| Cần | Ai làm | Ghi chú |
|---|---|---|
| PostgreSQL 15+ cho môi trường vận hành | DevOps | `docker-compose.yml` đã có service `db` (postgres:16-alpine) |
| Backup CSDL hiện tại | DevOps | repo có job backup 2×/ngày lên R2 (`f38ee7b`) — xác nhận có bản gần nhất |
| Phê duyệt bật pipeline trên dữ liệu thật | Chủ dự án | §19: không backfill dữ liệu thật chỉ vì code merge |
| Mẫu payload Edge thật (3–5/nguồn) | Người rành dữ liệu | để duyệt `docs/DATA_DICTIONARY.md §4` |

---

## 1. Chuyển sang PostgreSQL

```bash
# a. Trên VPS: dựng Postgres (hoặc dùng service `db` trong docker-compose.yml)
#    Tạo DB + user, ghi mật khẩu vào POSTGRES_PASSWORD trong .env

# b. Bật pgvector (1 lần, quyền superuser) — chỉ cần khi làm semantic pgvector ở bước 6
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# c. Thêm vào .env (gốc repo hoặc server/.env):
#    DATABASE_URL=postgres://<user>:<pass>@<host>:5432/<db>
#    (settings.py tự chuyển sang Postgres khi biến này có mặt)

# d. Chạy migration trên Postgres:
python manage.py migrate

# e. Nếu ĐÃ có dữ liệu thật trên SQLite cần giữ:
python manage.py dumpdata --natural-foreign --natural-primary \
    -e contenttypes -e auth.permission -e sessions -e admin.logentry \
    --indent 2 -o /tmp/dump.json          # trên cấu hình SQLite cũ
DATABASE_URL=postgres://... python manage.py loaddata /tmp/dump.json
#    (nếu chưa launch / dữ liệu chỉ là test — bỏ qua, migrate là đủ)

# f. Kiểm tra: chạy test suite trên Postgres
DATABASE_URL=postgres://... python manage.py test
```

**Rủi ro:** mất dữ liệu nếu `loaddata` lỗi giữa chừng → luôn có backup trước, và
làm trên bản sao trước khi làm production.

## 2. Chọn model embedding (chỉ cho semantic pgvector — KHÔNG chặn các bước khác)

Hiện `talent.semantic_index` dùng khoá song ngữ, đủ dùng. Khi muốn nâng lên vector thật:

- Chọn 1 endpoint `/embeddings` từ provider đã có key (`.env`: GreenNode / OpenAI / Gemini đều có).
- Gợi ý: `text-embedding-3-small` (1536 chiều) hoặc Gemini `text-embedding-004` (768).
- Đo chi phí trên 1.000 CV (`~ số_ký_tự / 4 tokens × giá`) trước khi bật toàn kho.
- Việc code: thêm `pgvector` vào `requirements.txt`, đổi `TalentSemanticIndex.vector`
  từ `JSONField` sang `pgvector.django.VectorField(dimensions=N)`, viết command
  reindex. Lưu `embedding_model` + `embedding_version` mỗi vector (§3.1).

## 3. Hàng đợi

`intel.ExtractionJob` là hàng đợi DB-backed — **chạy được ngay trên Postgres**,
không cần Celery/Redis. Chỉ thêm Celery khi cần nhiều worker song song / lịch chạy.
Bản tối thiểu: cron gọi `run_extraction_worker --once` (xem bước 5).

---

## 4. Batch D — dữ liệu & nhãn (nghiệp vụ)

### 4a. Lấy payload Edge thật
```bash
python manage.py shell -c "
from core.models import SourceRecord; import json
for r in SourceRecord.objects.order_by('?')[:5]:
    print(json.dumps(r.payload, ensure_ascii=False, indent=2)); print('---')
"
```
Mở `docs/DATA_DICTIONARY.md §4`. Với mỗi khoá payload thật chưa có trong
`server/intel/edge_mapper.py:PAYLOAD_KEYS` → thêm vào. Xác nhận `applied_position`
vs `current_title` khi provider dùng chung khoá `position`.

### 4b. Đo baseline search (làm TRƯỚC khi bất kỳ ai sửa search)
```bash
python manage.py baseline_search --queries docs/benchmark/search_queries.sample.jsonl --mode structured
python manage.py baseline_search --queries docs/benchmark/search_queries.sample.jsonl --mode ai
git add docs/benchmark/baseline/ && git commit -m "baseline: production search snapshot"
```

### 4c. Ba bộ nhãn
```bash
# Extraction (150–200 CV) — 2 recruiter điền cột gold trong worksheet.csv (~2–3 phút/CV)
python manage.py export_label_batch --count 150 --seed 42
#   schema: docs/benchmark/extraction_gold.schema.json ; KHÔNG commit (chứa CV thật)

# Search (30–50 truy vấn) — lấy truy vấn thật:
python manage.py shell -c "
from talent.models import TalentAIAnalysis
for a in TalentAIAnalysis.objects.order_by('-analyzed_at')[:50]: print(a.question)
"
#   -> docs/benchmark/search_queries.jsonl ; recruiter chấm relevant/không cho từng ứng viên

# Hội thoại (≥12) — viết tay, phủ 4 nhóm (nhận diện · ngoài phạm vi · đổi/bỏ tiêu chí · quay lại đối tượng)
```

Gate Giai đoạn 0: ≥ 50 CV field + 15 truy vấn có phán quyết + 12 câu hội thoại + baseline đã đo.

---

## 5. Bật pipeline trích xuất (cần bước 1 + phê duyệt §19)

> **Đã chạy trên production 01/09/2026** (Claude, theo uỷ quyền chủ dự án): backup
> `~/msbradar/pre-intel-20260901T054828Z.sql.gz` → `seed_canonical` → `extract_person
> --limit 20 --no-ai` (14 Person, 90 fact edge-only, tất cả accepted, 0 conflict,
> 0 token) → `rebuild_search_projection` (14 profile). 13 alias job_title/source ở
> hàng chờ. **Chưa** chạy AI-fill / `backfill_extraction` / auto-accept / auto-enqueue.
> Các bước dưới đây là phần tiếp theo, cần phê duyệt riêng.

```bash
python manage.py seed_canonical                       # 1 lần, idempotent
python manage.py extract_person --limit 50 --no-ai    # Edge-only, 0 token — đọc coverage
python manage.py extract_person --limit 50            # + AI (cần provider key trong .env)

# -> Admin mở Web /admin → tab "🧠 People Intelligence":
#    - "Hàng chờ duyệt": chấp nhận/từ chối giá trị nhạy cảm & confidence thấp
#    - "Alias chưa nhận diện": nối alias lạ vào mã canonical, hoặc bỏ

python manage.py backfill_extraction --limit 500      # có safe-stop; đọc dòng "GATE OK" / "GATE FAIL"
#    Cổng dừng: error rate > 5%  |  fact AI accepted đè lên field curated > 0

# Benchmark: so đầu ra với 50 nhãn gold (precision/recall theo field).
# Chỉ bật auto-accept cho field đạt ngưỡng precision đã duyệt (chỉnh gate trong
# server/intel/field_rules.py).
```

### Bật liên tục
```bash
# .env:
INTEL_AUTO_ENQUEUE_EXTRACTION=1

# cron (hoặc systemd service chạy vòng lặp):
*/10 * * * *  cd /app && python manage.py run_extraction_worker --once
0 2 * * *     cd /app && python manage.py rebuild_search_projection
0 3 * * 1     cd /app && python manage.py prune_reasoning_traces --commit
0 3 * * 1     cd /app && python manage.py run_assistant_review --commit   # đề xuất memory từ 👎
```

### Rollback tức thì
```bash
# .env:
INTEL_AUTO_ENQUEUE_EXTRACTION=0
INTEL_CANONICAL_SEARCH=0
```
→ về đúng hành vi trước intel. Fact nằm im trong DB, không dùng.

---

## 5b. Intent router + Web search (Google)

`ai/intent.py` phân loại mỗi câu hỏi (search / hội thoại / web) bằng một lượt gọi
model nhỏ trước khi chọn nhánh — thay heuristic cũ. Mặc định **bật**, model lỗi thì
tự lùi heuristic.

```bash
# .env — tắt intent router (quay lại heuristic thuần):
ASSISTANT_INTENT_ROUTER=0
```

Web search cho Radar tra web khi câu hỏi cần dữ kiện ngoài kho. **Mặc định TẮT.**
**Độc lập bộ não** — backend trả snippet, bộ não đang dùng (GreenNode / DeepSeek /
… ) tự tổng hợp.

```bash
# .env — bật (chấp nhận rằng câu hỏi người dùng gõ sẽ được gửi ra ngoài):
ASSISTANT_WEB_SEARCH=1
```
**Chỉ vậy là chạy** — backend `duckduckgo` bật sẵn, không cần khoá/container.

Tuỳ chọn nâng cấp backend:
```bash
# a) Tự dựng SearXNG (ổn định nhất, hoàn toàn tự chủ):
SEARXNG_SECRET=$(openssl rand -hex 32)      # vào .env
sudo docker compose -f docker-compose.oracle-core.yml --profile searxng up -d searxng
#    rồi: SEARXNG_URL=http://searxng:8080 vào .env, recreate hub

# b) hoặc backend có khoá:
TAVILY_API_KEY=tvly-...            # free tier
# BRAVE_SEARCH_API_KEY / GOOGLE_CSE_KEY+GOOGLE_CSE_CX / MSB_AI_GEMINI_API_KEY

# tắt DuckDuckGo (nếu chỉ muốn dùng backend khác):
ASSISTANT_WEBSEARCH_DDG=0
# ép thứ tự:
ASSISTANT_WEBSEARCH_BACKENDS=searxng,gemini_grounding
```

Chặn cứng (không tắt được): câu hỏi có **PII** (email / điện thoại / CCCD / MST) hoặc
dấu hiệu **prompt-injection** không bao giờ ra web — bị hạ về hội thoại thường.
Chỉ câu hỏi người dùng gõ được gửi đi; KHÔNG kèm hồ sơ ứng viên, evidence hay memory.
Kết quả web được bọc `prompt_guard` trước khi đưa cho bộ não.

Kiểm tra sau khi bật:
```bash
docker exec msbradar-hub python manage.py shell -c "
from ai import websearch, intent
b = websearch.pick_backend()
print('web enabled:', websearch.enabled(), '| backend:', b and b.name)
print(intent.classify('lãi suất huy động mới nhất là bao nhiêu').as_dict())
"
```
Trả lời hội thoại có nguồn sẽ kèm `sources[]` (API) / `event: sources` (SSE); event
log ghi `web.searched` (chỉ truy vấn + số nguồn).

### Rollback
```bash
# .env:
ASSISTANT_WEB_SEARCH=0
```
→ nhánh `web` tự hạ về hội thoại thường. Không mất dữ liệu.

### Tool-calling (kỹ năng Radar)

`ai/agent.py` cho model tự gọi tool server-owned trong lượt hội thoại. Tool đều
**chỉ đọc / chỉ đề xuất**, lọc RBAC trước khi model thấy. **Mặc định TẮT.**

```bash
# .env — bật sau khi soát:
ASSISTANT_TOOLS=1
ASSISTANT_TOOL_MAX_STEPS=4      # trần vòng model↔tool
```

Tool hiện có: `read_allowed_evidence`, `remember_proposal`, `feedback` (tier 1);
`compare_candidates`, `canonical_lookup`, `fact_provenance` (tier 2). Xem roadmap
ở `RADAR_AI_MASTER_PLAN.md §17`. `search_people`/`search_prospects` **không** gọi
qua vòng lặp (là nhánh định tuyến).

Tier 3 (`draft_outreach` — trả bản nháp, không gửi; `enrich_company_from_web` —
cần `ASSISTANT_WEB_SEARCH`) có **cờ riêng**:
```bash
ASSISTANT_TOOLS_TIER3=1     # chỉ có tác dụng khi ASSISTANT_TOOLS=1
```

Kiểm tra:
```bash
docker exec msbradar-hub python manage.py shell -c "
from ai import toolset
from django.contrib.auth.models import User
u = User.objects.filter(is_superuser=True).first()
print([t['function']['name'] for t in toolset.agent_toolset_for('talent', u)])
"
```

Rollback: `ASSISTANT_TOOLS=0` → về trả lời một lượt như cũ.

### Agent core dạng đồ thị (tuỳ chọn)

`ai/graph_agent.py` biểu diễn vòng lặp model↔tool thành `StateGraph`, engine là
`ai/graph.py` (**tự viết, 0 dependency**). Cùng hợp đồng với `ai/agent.py`, thay
được nhau qua cờ:
```bash
ASSISTANT_GRAPH=1
```
Rollback: `ASSISTANT_GRAPH=0`.

---

## 6. Giao diện — đã có

| Màn hình | Đường dẫn |
|---|---|
| Tổng quan trích xuất + coverage | `/admin` → 🧠 People Intelligence → Tổng quan |
| Hàng chờ duyệt fact | `/admin` → 🧠 People Intelligence → Hàng chờ duyệt |
| Nối alias chưa nhận diện | `/admin` → 🧠 People Intelligence → Alias chưa nhận diện |
| Fact & nguồn gốc của một Person | `/person/<id>` → tab "Lịch sử & Nguồn" |
| Ghi nhớ dài hạn + tìm hội thoại cũ | `/settings` → 🧠 Radar ghi nhớ |

---

## 7. Không làm tự động (§19)

- Không deploy production, không backfill toàn kho, không bật auto-accept toàn bộ
  field — mỗi cái cần phê duyệt riêng.
- Không tự động dùng chat/CV để fine-tune.
- Không bật `ASSISTANT_WEB_SEARCH` / `ASSISTANT_TOOLS` mặc định — chủ dự án bật
  sau khi soát (web search: chấp nhận gửi câu hỏi ra ngoài; tool-calling: soát
  từng tool). Tier 3 (draft_outreach, enrich_company) chưa làm, mỗi cái phê duyệt riêng.
