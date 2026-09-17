# Radar AI Agent — Product & Engineering Backlog

**Cập nhật:** 05/09/2026  
**Trạng thái:** Backlog v2 — epic map + delivery backlog, được đối chiếu với code và tài liệu hiện có  
**Phạm vi:** tìm ứng viên, tìm khách hàng, trợ lý tổng quát, tìm kiếm web và năng lực agent dùng chung

---

## 1. Mục tiêu

Radar dùng model qua API làm bộ não, còn sản phẩm sở hữu dữ liệu, trí nhớ, công cụ, quyền hạn,
kiểm chứng và trải nghiệm. Đích đến không phải một LLM biết nói mọi thứ, mà là một agent có thể:

1. Hiểu đúng người dùng đang hỏi, tìm, phân tích hay yêu cầu hành động.
2. Chọn đúng miền dữ liệu: ứng viên, khách hàng, dữ liệu nội bộ, web hoặc kết hợp nhiều nguồn.
3. Tìm đủ rộng nhưng xếp hạng đủ chính xác; mọi kết luận quan trọng có bằng chứng.
4. Nhớ mạch hội thoại, người/vật đang được nhắc tới và sở thích đã được người dùng cho phép nhớ.
5. Lập kế hoạch nhiều bước, dùng tool đúng quyền, dừng xin xác nhận trước hành động có hậu quả.
6. Trả lời tự nhiên như trợ lý đa năng, không ép câu hỏi phổ thông thành tìm kiếm con người.
7. Nhanh, quan sát được, có fallback và được đánh giá bằng bộ câu hỏi thật.

## 2. Hiện trạng đã có — không làm lại

### 2.1. Nền tảng dùng chung

- Router nhiều provider/model; cấu hình task route và API key qua DB/Settings.
- Streaming, tách reasoning khỏi câu trả lời, key rotation, timeout và fallback provider.
- `AssistantThread`, `AssistantMessage`, event log, lịch sử nhiều cuộc trò chuyện, resume lượt đang chạy.
- Conversation projection có recent turns, summary, memory, mentioned IDs, active criteria và last result.
- Long-term memory theo người dùng, trạng thái chờ duyệt, quota, sửa/xóa và chống prompt injection.
- Persona Radar, xưng hô theo hồ sơ người dùng; prompt guard, PII scan và contact redaction.
- Tool registry, RBAC, tool loop tuần tự, giới hạn bước và hai implementation agent/graph có parity test.
- Web search có nhiều backend và fallback; model hiện tại tổng hợp kết quả kèm nguồn.
- Lưu usage/latency/error của LLM; feedback model/API; retention và audit xóa hội thoại.

### 2.2. Talent Answer Engine

- Pipeline ① plan → ② hybrid retrieval → ③ evidence judge → ④ deterministic aggregate → ⑤ compose/verify.
- Dense vector trên profile và CV chunks, full-text, RRF, query expansion đa ngôn ngữ.
- Structured pin, name resolution, follow-up theo người ở lượt trước, count/superlative fast paths.
- Trích dẫn được đối chiếu với nguồn; thông tin liên hệ bị che trước khi tới model/client.
- Đọc CV đính kèm, action branch, cache, widen một lần, progress events và chạy nền khi client rớt.
- Edge-first extraction, canonical aliases, fact provenance, conflict/review queue và materialized profile.

### 2.3. Growth/RB và trợ lý tổng quát

- Prospect search bằng ngôn ngữ tự nhiên, RB scoring, suggestions, next-best-action và outreach draft.
- RB agent có trace bốn bước cho social signal → person → product → open opportunity.
- Common assistant nhận diện hội thoại, câu hỏi danh tính, câu hỏi web và đường tool khi được bật.

Các mục trên chỉ được refactor khi có bằng chứng lỗi hoặc để hợp nhất hợp đồng; không xây lại song song.

## 3. Quy tắc quản lý backlog

- **P0:** sai, rò dữ liệu, mất ngữ cảnh, bỏ sót nghiêm trọng hoặc không thể vận hành an toàn.
- **P1:** năng lực cốt lõi để Radar trở thành agent đa bề mặt hoàn chỉnh.
- **P2:** tối ưu chất lượng, tốc độ, chi phí và mở rộng nghiệp vụ.
- **P3:** thử nghiệm nâng cao; chỉ làm sau khi P0/P1 có benchmark ổn định.
- Mỗi item chỉ được đóng khi có test tự động, telemetry cần thiết và kiểm chứng trên dữ liệu clone/production
  phù hợp. “Model trả lời nghe hay” không phải tiêu chí nghiệm thu.
- Không dùng dữ liệu chat để tự training. Feedback/memory chỉ được dùng theo mục đích đã công bố, có
  consent, retention, ẩn danh và tập đánh giá tách biệt trước khi cân nhắc fine-tune.
- Trạng thái chuẩn: `DONE` (đã xác minh production), `PARTIAL` (đã có một phần), `READY` (đủ điều kiện
  làm), `BLOCKED` (thiếu dependency/quyết định), `DISCOVERY` (phải đo trước), `DEFERRED`.
- Mỗi ticket thi công phải có: parent epic, trạng thái, code pointer, deliverable, dependency, effort,
  acceptance, telemetry, feature flag, rollout và rollback. Epic không được đưa thẳng vào sprint.

---

## 4. P0 — Độ đúng, an toàn và nền móng vận hành

### P0-00 — Baseline và eval harness tối thiểu trước mọi thay đổi

**Trạng thái hiện tại:** `PARTIAL` — đã có nhiều bộ test/eval riêng nhưng chưa có manifest và báo cáo
đa bề mặt thống nhất.  
**Làm:** đóng băng một baseline có version cho router, Talent retrieval/answer, memory, web, tool và
safety; ghi rõ dataset snapshot, model route, prompt version, corpus fingerprint, latency và cost. Đây là
dependency của P0-01 đến P0-07, không phải công việc làm sau.  
**Nghiệm thu:** chạy một lệnh sinh báo cáo máy đọc được; tách lỗi model/provider khỏi lỗi logic Radar;
so sánh được hai revision và CI đọc được quality budget.

### P0-01 — Bộ router ý định đa bề mặt duy nhất

**Vấn đề:** Talent, Prospect và assistant hiện có các nhánh/rule riêng; cùng một câu có thể đi khác đường
tùy màn hình.  
**Làm:** tạo `RadarTurnPlan` chung với `intent`, `domains`, `information_need`, `needs_web`,
`needs_tools`, `risk`, `clarification`, `subtasks`; giữ domain planner riêng ở tầng sau. Hỗ trợ một câu
nhiều miền và không phụ thuộc route UI.  
**Nghiệm thu:** ý định tường minh của người dùng thắng surface; surface chỉ là prior. Cùng input +
envelope + quyền + cấu hình phải cho cùng kế hoạch, nhưng cùng câu ở context khác được phép đi route khác
có giải thích. Bộ confusion matrix khởi tạo được hiệu chuẩn bằng dữ liệu thật; câu mơ hồ hỏi lại thay vì đoán.

### P0-02 — Hợp đồng context/memory chung cho mọi pipeline

**Vấn đề:** envelope đã giàu dữ liệu nhưng mỗi nhánh dùng một phần khác nhau.  
**Làm:** version hóa `ConversationEnvelope`; bắt buộc plan/compose/tool/web nhận summary, recent turns,
resolved entities, active constraints, last result, approved memories, permissions. Mặc định giữ nguyên
8–12 cặp hỏi–đáp gần nhất trong token budget; phần cũ thành rolling summary có cấu trúc; entity/constraint
đang hoạt động lưu riêng; long-term memory chỉ lấy top-K fact liên quan. Tách scope `global/user`, `talent`,
`prospect`, `conversation`; có TTL, nguồn, consent và giao diện xem/sửa/quên.  
**Nghiệm thu:** bộ test 5–10 lượt gồm đại từ “họ/người thứ hai/công ty đó”, sửa tiêu chí, quay lại chủ đề
cũ và đổi model giữa lượt vẫn giữ đúng mạch; không mang context giữa hai thread.

### P0-03 — Entity resolution bền vững

**Làm:** registry cho Person, Company, Job/Requisition, Opportunity, Document và địa danh; lưu entity
đã resolve theo lượt với confidence/ambiguity; không quét toàn bảng Person vào RAM; hỏi lại khi trùng tên.  
**Nghiệm thu:** tên có/không dấu, tên viết tắt, hai người trùng tên, “ứng viên thứ ba”, “khách vừa nói”
đều có test; latency không tăng tuyến tính theo toàn bộ kho.

### P0-04 — Tổng quát hóa ràng buộc bắt buộc

**Vấn đề:** structured pin còn trần và ngoại lệ `should_have` mới tập trung vào số năm kinh nghiệm.  
**Làm:** typed constraints (`must`, `prefer`, `exclude`, range, temporal, geo, unknown-policy); compiler
deterministic từ plan sang query; không coi “chưa bóc tách” là “không có”; bỏ trần pin làm mất người,
thay bằng paging/batched judge hoặc exact candidate set.  
**Nghiệm thu:** phủ kỹ năng, ngành, chức danh, công ty, seniority, học vấn, ngôn ngữ, chứng chỉ, địa điểm,
lương, thời gian, phủ định và tổ hợp; recall bắt buộc = 100% trên gold set có dữ liệu xác định.

### P0-05 — Chỉ mục và extraction luôn tươi

**Làm:** event-driven enqueue khi SourceRecord/Document/fact đổi; fingerprint/version theo projection,
chunk và embedding; dashboard stale/failed/coverage; retry có backoff/dead-letter; reindex model mới song
song rồi atomic switch. Tận dụng text Edge đã parsing và trường ngoài CV, không parse lại.  
**Nghiệm thu:** hồ sơ mới/sửa xuất hiện trong search theo SLO; không có “command báo thành công nhưng 0
vector”; backfill resumable/idempotent; cảnh báo khi coverage dưới ngưỡng.

### P0-06 — Security boundary trước model, tool và web

**Làm:** row-level authorization contract dùng chung; redact field-aware trước prompt/client/log; kiểm
soát contact unlock; chống injection từ CV, web, memory và tool output; SSRF/domain policy cho web/enrich;
secret chỉ từ DB/secret manager, không log.  
**Nghiệm thu:** adversarial suite cho PII, cross-user/thread, prompt injection, malicious URL, tool
argument tampering; không có raw contact trong answer/citation/trace khi chưa unlock.

### P0-07 — Hành động có hậu quả phải có approval protocol

**Làm:** phân tier tool: read-only, draft/proposal, reversible write, irreversible/external. Mọi write
có preview → explicit confirmation → idempotency key → execute → receipt/audit; quyền kiểm lại tại lúc
thực thi, không chỉ lúc model chọn tool.  
**Nghiệm thu:** model không thể tự gửi email, đổi stage, merge Person hay tạo opportunity; retry không tạo
trùng; approval hết hạn hoặc thay đổi payload phải xin lại.

### P0-08 — Eval regression đa bề mặt làm cổng deploy

**Làm:** hợp nhất answer eval, retrieval eval, agent/tool eval, web eval, memory multi-turn, safety và
latency thành một harness; snapshot dataset/version/model route. Có gold labels do nghiệp vụ duyệt và
hard negatives.  
**Nghiệm thu:** CI chặn khi recall/precision/citation/tool-success/safety tụt quá budget; benchmark trên
DB clone trước rollout; báo riêng lỗi provider và lỗi logic Radar.

### P0-09 — Quản trị tiến trình dài và đồng thời

**Làm:** thay thread-per-request/in-memory inflight bằng durable job/run state và worker pool có quota;
cancel/resume/heartbeat; giới hạn theo user/provider/task; stage event có sequence và reconnect cursor.  
**Nghiệm thu:** restart container không mất lượt; 20 lượt đồng thời không làm cạn thread/DB connection;
client rớt vẫn lấy lại kết quả; deadline tạo trạng thái rõ, không lưu câu trả lời giả hoàn chỉnh.

### P0-10 — Prompt và structured-schema governance

**Trạng thái hiện tại:** `PARTIAL` — task routes có version theo migration, prompt/schema còn nằm rải trong
code.  
**Làm:** prompt registry có ID/version/hash; JSON schema version và compatibility matrix theo model;
snapshot prompt/model/schema trong trace; canary và rollback; test prompt truncation, malformed JSON và
model nuốt tham số.  
**Nghiệm thu:** tái dựng được chính xác request logic của một lượt; đổi prompt có diff/eval; rollback không
cần deploy lại toàn hệ thống nếu chỉ đổi cấu hình được duyệt.

### P0-11 — Data/privacy governance theo miền

**Làm:** inventory field/source/purpose/owner/retention/PII/ACL cho Talent, RB, conversation và web;
quy định dữ liệu nào được gửi model/provider nào, dữ liệu nào chỉ xử lý nội bộ; deletion propagation tới
cache/vector/event log.  
**Nghiệm thu:** data lineage và xóa theo người dùng/person đi hết các bản sao; policy test chặn field cấm
trước network boundary.

### P0-12 — Release, canary và failure recovery

**Làm:** feature flag theo user/team/surface; shadow/canary; DB migration expand-contract; backup đã kiểm
restore; rollback code/model/prompt/index độc lập; kill switch cho web/tool/provider.  
**Nghiệm thu:** runbook diễn tập một lần trên clone/staging; rollback không làm mất thread, fact hoặc index
đang hợp lệ; production verification có evidence chứ không suy từ CI xanh.

---

## 5. P1 — Agent đa bề mặt hoàn chỉnh

### P1-01 — Orchestrator cho nhiệm vụ nhiều bước

Xây state machine dùng chung: understand → plan → retrieve/tools → verify → approval → execute → report.
Cho phép DAG nhỏ, budget bước/token/thời gian, retry theo loại lỗi và checkpoint. Domain engine Talent/RB
là tool/subgraph, không bị viết lại. Nghiệm thu bằng các bài “tìm 5 người → so sánh → soạn thư cho 2
người phù hợp nhất” và “tìm khách → kiểm tra cơ hội → soạn kịch bản”, không đổi đối tượng giữa bước.

### P1-02 — Unified tool protocol

Mỗi tool có schema version, permissions, risk tier, timeout, idempotency, cost hint, audit policy và
structured error. Tool output có provenance và giới hạn kích thước. Thêm tool discovery theo surface,
không bơm toàn bộ schema vào mọi prompt.

### P1-03 — Talent toolset đầy đủ

- Search/compare/explain candidates; inspect fact provenance và CV source.
- Tạo shortlist/pool proposal, draft outreach, draft interview questions, summarize candidate.
- Match candidate ↔ requisition và gap analysis hai chiều.
- Chỉ sau approval: lưu pool/note/task; stage change là workflow riêng có policy.
- Không dùng giới tính, tuổi hoặc thuộc tính nhạy cảm để xếp hạng trừ trường hợp pháp lý được cấu hình.

### P1-04 — Customer/RB Answer Engine ngang cấp Talent

Hiện Prospect search và RB agent chưa có pipeline evidence/verify thống nhất như Talent. Xây customer
projection + chunks/facts, hybrid retrieval, entity pin, deterministic constraints, evidence judge,
compose/citation và follow-up memory. Hỗ trợ tìm khách, phân tích nhu cầu, opportunity, lịch sử tương tác,
next-best-action; tách rõ fact, inference và recommendation. Chỉ bắt đầu implementation sau P1-11.

### P1-05 — Trợ lý tổng quát thực sự

Trả lời kiến thức chung, viết/tóm tắt/dịch/brainstorm, tính toán và phân tích tài liệu mà không bắt buộc
search kho. Có calculator/date utilities và attachment understanding. Câu “bạn là ai/ai tạo ra bạn/bạn
làm được gì” dùng identity ổn định của Radar; không tự nhận là ChatGPT/Gemini/model nền.

### P1-06 — Web research engine

Tách search khỏi synthesis: query planning, multi-query, freshness intent, source fetch/extract,
deduplicate, rank theo authority/recency/relevance, answer với citation URL/title/date. Cho phép kết hợp
web + dữ liệu nội bộ nhưng gắn nhãn nguồn rõ; không gửi PII/nội dung CV lên web search. Có allow/deny
domain, robots/licensing policy, timeout và fallback backend.

### P1-07 — Clarification và uncertainty

Định nghĩa khi nào hỏi lại, khi nào dùng giả định, khi nào mở rộng. Câu trả lời phân biệt `known`,
`inferred`, `unknown`, `conflicting`; hiển thị độ phủ dữ liệu. Không biến confidence model thành xác suất
nghiệp vụ. Mỗi câu hỏi chỉ hỏi lại tối thiểu thông tin có giá trị quyết định cao nhất.

### P1-08 — Citation/provenance thống nhất

Một `SourceRef` dùng chung cho CV, structured fact, Edge payload, database aggregate và web. Citation
phải mở đúng đoạn/record theo quyền; quote verified; nguồn thay đổi thì đánh dấu stale. Các phép đếm,
so sánh và khuyến nghị đều có lineage tái dựng được.

### P1-09 — Feedback và learning loop có kiểm soát

Đưa 👍/👎 + reason + corrected answer/result vào cả Talent/Prospect/general. Tạo review queue, taxonomy
lỗi và weekly eval set từ phản hồi đã ẩn danh. Không tự đổi prompt/alias/weight/model ở production;
mọi proposal qua offline eval, approval và canary.

### P1-10 — UX hội thoại hợp nhất

Một lịch sử thread có thể chuyển giữa Talent/Growth/general mà không mất mạch; hiển thị scope đang dùng,
nguồn, bước công khai (không lộ chain-of-thought), tool/approval cards, stop/retry/edit/regenerate,
branch conversation, upload status và resume. Kết quả dạng card là phần bổ sung, câu trả lời vẫn tự nhiên.

### P1-11 — Discovery và governance riêng cho Customer/RB

**Trạng thái:** `DISCOVERY`. Inventory nguồn khách hàng, social text, interaction, opportunity và dữ liệu
giao dịch; chốt mục đích sử dụng, DNC/consent, quyền theo RM/đơn vị, retention, field được phép đưa model,
gold set và harm model. Không bê schema/prompt Talent sang RB.  
**Nghiệm thu:** có data contract và threat model được chủ nghiệp vụ chấp thuận; xác định rõ fact quan sát
được, inference AI và quyết định chỉ con người được làm.

### P1-12 — ADR: Radar chạy trong Django hay AgentBase Runtime

**Trạng thái:** `DISCOVERY`; mặc định hiện tại là tiếp tục embedded trong Django.  
**Làm:** so sánh latency, network/data boundary, deploy, memory, identity, gateway, scaling, lock-in và chi
phí. Nguồn sự thật luôn ở Radar DB. Chỉ tách runtime/tool khi benchmark chứng minh lợi ích.  
**Nghiệm thu:** ADR có decision, rejected alternatives, migration/rollback; không scaffold thêm agent chỉ
để nhân đôi orchestrator hiện có.

### P1-13 — Accessibility và chất lượng UX agent

Keyboard/screen-reader, trạng thái loading/error/reconnect, reduced motion, mobile, nội dung dài, citation
focus, approval rõ hậu quả; không dùng màu làm tín hiệu duy nhất. Có usability test với Recruiter và RM.

### P1-14 — Operational runbook

Runbook cho provider capacity, key/model lỗi, embedding stale, queue lag, web backend lỗi, tool timeout,
conversation stuck, PII incident và rollback. Mỗi alert chỉ tới dashboard/câu lệnh an toàn tương ứng.

---

## 6. P2 — Chất lượng, hiệu năng và mở rộng

### P2-01 — Retrieval quality engineering

- Gold set theo miền, query khó, bilingual/synonym, typo, negation, temporal và sparse profile.
- Đo recall@K trước judge, precision@K sau judge, nDCG/MRR và zero-result rate.
- Query expansion có cache; hybrid weights và RRF được tune từ eval, không theo cảm giác.
- Hard-negative mining từ hồ sơ gần giống và feedback thật.
- Parent-child retrieval cho CV chunks; diversity để tránh nhiều chunk/người chiếm hết pool.

### P2-02 — Cascaded judging tối ưu chi phí

Cheap deterministic/vector rerank → lightweight evidence screen → deep judge chỉ cho nhóm khó; adaptive
pool theo limit, entropy và coverage. Batch theo token budget, cache evidence judgement theo fingerprint.
Không chấp nhận tối ưu làm tụt recall/safety.

### P2-03 — Chuẩn hóa dữ liệu đa ngôn ngữ toàn miền

Mở rộng canonical registry cho location hierarchy, title/skill/industry/company/university/certification,
product/need và acronym Việt–Anh. Alias học từ truy vấn/feedback chỉ ở trạng thái proposal. City chuẩn
luôn một nhãn canonical nhưng giữ raw value và provenance; suy luận “Quận 1 → TP Hồ Chí Minh” bằng quan
hệ phân cấp, không bằng thay chuỗi tùy tiện.

### P2-04 — Extraction chất lượng cao

Schema version cho education/work/language/certification/achievement/preferences; AI fill gaps, không
ghi đè Edge/manual; evidence span + confidence + conflict. Bổ sung nguồn hợp lệ cho birth date và applied
region; recruiter/external assessment luôn là human-owned. Eval extraction theo field-level precision,
recall và exact/canonical match.

### P2-05 — Model governance tự động

Capability registry cho chat/reasoning/vision/embedding/tool/JSON/context; health/capacity/rate-limit
circuit breaker; route theo task/risk/budget, sticky model trong một turn nhưng memory độc lập model.
Canary/A-B/shadow evaluation, rollback route từ Settings và cost ceiling theo team/user.

### P2-06 — Cache đúng tầng

Cache embedding query, web result, retrieval, evidence judgement và aggregate theo fingerprint/quyền;
không cache nhầm câu trả lời phụ thuộc context. Có invalidation theo source/fact/model/prompt/policy,
hit-rate và stale-rate telemetry.

### P2-07 — Observability và SLO

Trace ID xuyên UI → planner → retrieval → model → tool; dashboard p50/p95/p99, tokens/cost, fallback,
retrieval pool/coverage, citation repair, tool success, queue lag. SLO riêng cho fast/general/search/deep;
alert khi route DB không resolve, embedding stale hoặc zero-result tăng bất thường.

### P2-08 — Web freshness và chuyên sâu

Crawler/fetch cache có TTL theo loại nguồn; date extraction; conflict detection giữa nguồn; nguồn chính
thức ưu tiên cho luật/chính sách/sản phẩm. Chế độ research nhiều bước chỉ bật khi người dùng yêu cầu hoặc
router đánh giá cần thiết, kèm budget và progress.

### P2-09 — Tài liệu và knowledge base nội bộ

Ingest tài liệu được cấp quyền, chunk/version/ACL, hybrid retrieval và citation; tách khỏi CV index.
Hỗ trợ policy/manual/FAQ; ưu tiên nguồn nội bộ mới nhất, báo xung đột phiên bản. Có lifecycle xóa/reindex.

### P2-10 — Personalization an toàn

Nhớ ngôn ngữ, cách xưng hô, format, khu vực/phân khúc phụ trách và tiêu chí thường dùng sau consent.
Không học ngầm thuộc tính nhạy cảm; người dùng xem/sửa/quên được; recommendation cá nhân hóa không được
loại người khỏi candidate set nếu policy không cho phép.

### P2-11 — Action ecosystem

Sau khi policy/approval hoàn thiện: calendar/task/CRM/email adapters, draft-first, connector health,
least privilege và receipts. Mọi tích hợp bên ngoài qua credential vault/identity; không hardcode secret.

### P2-12 — Khả năng mở rộng dữ liệu

Keyset pagination/stream export, không load toàn bảng; partition/index review; concurrency-safe workers;
capacity test theo mốc tăng trưởng đã được business/capacity planning xác nhận (khởi tạo 10K/100K, chưa
mặc định yêu cầu 1M); archive và retention cho event/message/vector. Có kế hoạch dimension/model migration
không downtime.

---

## 7. P3 — Năng lực nâng cao sau khi nền tảng ổn định

### P3-01 — Proactive agent

Saved monitors có opt-in: ứng viên mới phù hợp requisition, khách phát sinh tín hiệu, CV/index stale,
opportunity cần follow-up. Chỉ tạo notification/proposal theo lịch; không tự liên hệ hay thay đổi nghiệp vụ.

### P3-02 — Multi-agent/domain delegation

Talent, Growth, Web Research và General là các specialist dưới một coordinator; chỉ áp dụng khi benchmark
chứng minh tốt hơn một orchestrator đơn. Hợp đồng handoff phải mang entity/context/source/budget, chống
vòng lặp và có một agent chịu trách nhiệm câu trả lời cuối.

### P3-03 — Multimodal

Đọc CV scan/image, bảng biểu, biểu đồ và file Office bằng vision/OCR có provenance; audio transcription
cho ghi chú phỏng vấn nếu có consent. Không chạy vision khi parsed text tốt đã có.

### P3-04 — Scenario simulation và decision support

What-if cho shortlist, sourcing và RB pipeline; giải thích giả định, không trình bày dự báo như sự thật.
Fairness audit và human decision vẫn bắt buộc.

### P3-05 — Fine-tuning có điều kiện

Chỉ xem xét cho classification/extraction/style khi prompt + retrieval + tool đã đạt trần, có dataset
được phép, ẩn danh, split chống leakage và chứng minh lợi ích hơn model API mặc định. Không fine-tune bằng
toàn bộ lịch sử chat thô.

---

## 8. Backlog theo bề mặt

| Bề mặt | Đã có | Khoảng trống phải ưu tiên |
|---|---|---|
| Talent | Answer Engine có dẫn chứng, hybrid retrieval, attachment, follow-up | typed constraints tổng quát, exhaustive result, requisition matching, approval actions |
| Growth/RB | prospect parser/search, score, suggestions, opportunity workflow | Answer Engine có evidence/citation, customer projection/vector, multi-turn ngang Talent |
| General | persona, common answers, model chat, memory infrastructure | unified router/context, utility tools, attachment/general workflows, consistent citations |
| Web | nhiều backend, fallback, synthesis, source links | fetch/rank/freshness, multi-query research, safety/ACL, internal+web provenance |
| Agent | tool loop, graph engine, RBAC, traces | durable orchestration, risk tiers, approval/receipt, cross-domain handoff |
| Data | Edge-first, facts, aliases, review, projection/vector | continuous freshness, coverage SLO, schema breadth, scalable backfill/reindex |

## 9. Năng lực tool đích

### Read/search

`search_people`, `search_customers`, `search_documents`, `search_web`, `get_person`, `get_customer`,
`get_requisition`, `get_opportunity`, `get_fact_provenance`, `compare_entities`, `aggregate_corpus`.

### Analyze/draft

`assess_candidate`, `match_candidate_job`, `summarize_profile`, `analyze_customer_need`,
`recommend_next_best_action`, `draft_outreach`, `draft_interview`, `draft_note`, `build_report`.

### Memory/workspace

`remember_proposal`, `forget_memory`, `save_search`, `create_shortlist_proposal`, `create_task_proposal`,
`export_result`; mọi dữ liệu ghi phải theo approval tier.

### External actions — chỉ sau approval

`send_message`, `create_calendar_event`, `update_stage`, `create_opportunity`, `assign_owner`,
`merge_person`. Các tool này chưa được mở chỉ vì đã có schema; phải hoàn tất P0-07 và policy nghiệp vụ.

## 10. Bộ benchmark tối thiểu

Các số dưới đây là **target khởi tạo để ước lượng công sức**, chưa phải quality gate đã chốt. Release A
phải đo baseline, độ đa dạng và chi phí gắn nhãn rồi mới khóa sample size/K/SLO. Với chỉ số an toàn như
rò PII, vượt quyền và action không approval, ngưỡng chấp nhận luôn bằng 0.

| Nhóm | Số case tối thiểu | Chỉ số chính |
|---|---:|---|
| Intent/router đa bề mặt | target khởi tạo 200 | macro F1, wrong-domain critical rate |
| Talent retrieval/ranking | target khởi tạo 150 | recall@K, nDCG@10, must-have recall |
| Customer retrieval/ranking | target khởi tạo 120 | recall@K, precision@10, DNC violations = 0 |
| Evidence/citation | 100 | citation precision/coverage, unsupported claims |
| Multi-turn memory/entity | 80 kịch bản | entity continuity, constraint carryover, isolation |
| Web research | 80 | source quality, freshness, citation correctness |
| Tool/approval | 100 | tool selection, argument validity, unauthorized writes = 0 |
| Safety/adversarial | 120 | PII leaks, injection success, cross-user leaks = 0 |
| General assistant | 100 | task completion + human rubric |

Mỗi case lưu: input, conversation history, user role, expected route, expected/forbidden entities,
required facts/sources, allowed tools, latency budget và judge instructions. Không dùng LLM-as-judge đơn
lẻ cho điều code hoặc con người có thể xác nhận tất định.

## 11. Thứ tự triển khai khuyến nghị

### Release 0 — Đóng băng hiện trạng

P0-00 trước mọi thay đổi hành vi. Chụp baseline, corpus/model/prompt version và thống nhất quality budget.

### Release A — Nền móng đúng và đo được

P0-01, P0-02, P0-03, P0-04, P0-05, P0-06, P0-08, P0-10, P0-11, P0-12. Mục tiêu: ý định được hiểu
nhất quán theo context, không bỏ sót do trần/lọc sai, context không mất, prompt/data có governance và
mọi thay đổi có regression/canary/rollback.

### Release B — Agent an toàn

P0-07, P0-09, P1-01, P1-02, P1-07, P1-08. Mục tiêu: chạy nhiệm vụ nhiều bước bền vững, có approval,
provenance và resume.

### Release C — Đủ bốn bề mặt

P1-03, P1-05, P1-06, P1-09, P1-10, P1-11, P1-12, P1-13, P1-14; chỉ làm P1-04 sau khi P1-11 được
duyệt. Mục tiêu: Talent, Growth, general và web dùng chung một trải nghiệm và nền agent, nhưng vẫn có
engine, quyền và data contract chuyên miền.

### Release D — Tối ưu và mở rộng

P2-01 đến P2-12 theo số liệu bottleneck thực tế. P3 chỉ bắt đầu sau khi Release C đạt benchmark và SLO.

## 12. Definition of Done cho mọi backlog item

Một item chỉ được coi là xong khi:

1. Hợp đồng đầu vào/đầu ra, quyền, failure modes và migration đã được ghi rõ.
2. Có unit/integration/adversarial test và case trong eval set nếu ảnh hưởng hành vi AI.
3. Có trace/metric để biết code path thật đã chạy; không suy từ văn phong câu trả lời.
4. Đã thử provider failure, timeout, empty/sparse data và context dài.
5. Đã kiểm tra không rò PII/secret và không vượt quyền.
6. Benchmark trước/sau không tụt quá quality budget; latency/cost nằm trong SLO.
7. Migration/backfill idempotent, resumable, có dry-run/rollback khi liên quan dữ liệu.
8. Tài liệu hiện trạng được cập nhật sau khi production xác minh, không đánh dấu “đã làm” từ code local.

## 13. Những việc không nên làm

- Không gửi toàn bộ kho CV vào context model; retrieval phải thu hẹp nhưng recall phải được đo.
- Không dùng một bộ lọc cứng làm nguồn quyết định duy nhất khi field coverage chưa đầy đủ.
- Không để LLM tự đếm, tự sắp xếp số liệu xác định hoặc tự quyết định tuyển dụng/tín dụng.
- Không xây lại parser/OCR khi Edge đã gửi parsed text và metadata tốt hơn.
- Không lưu chat thô để “training cho thông minh hơn” nếu chưa có consent, governance và mục tiêu đo được.
- Không công khai chain-of-thought; chỉ hiển thị stage, nguồn, tool call và lý do ngắn có thể kiểm toán.
- Không thêm framework/multi-agent/vector database mới chỉ vì phổ biến; chỉ thêm khi benchmark chỉ ra khoảng
  trống mà hạ tầng hiện tại không giải quyết được.
- Không để `.env` âm thầm thắng cấu hình model/API key trong DB; env chỉ là emergency bootstrap được
  hiển thị rõ trong Settings và audit.

---

## 14. Delivery backlog — Release 0 và Release A

Effort chỉ là cỡ tương đối: `S` ≤ 1 ngày, `M` 1–3 ngày, `L` phải tách tiếp trước khi vào sprint. Không
coi effort là cam kết lịch khi chưa đo code/data thật. “Owner” là vai trò, chưa gán tên cá nhân.

| Ticket | Parent | Status | Effort | Owner | Deliverable chính | Dependency |
|---|---|---|---:|---|---|---|
| R0-01 | P0-00 | DONE | S | AI/QA | `ai/baseline.py` + `manage.py baseline_manifest` (`--out`, `--compare`); nhúng vào `answer_eval --out`. Xác minh trên production 05/09: 798 người, 785/798 profile + 1375/1413 chunk đã embed, 22 route hiệu lực đọc đúng DB, hash prompt/bộ eval ổn định giữa hai lần gọi không đổi gì | — |
| R0-02 | P0-00 | READY | M | AI/QA | Runner chung gọi các eval hiện có và sinh JSON report | R0-01 |
| R0-03 | P0-00 | DISCOVERY | M | Product/QA | Lấy mẫu câu thật đã ẩn danh; taxonomy lỗi và label guide | R0-01 |
| R0-04 | P0-00 | BLOCKED | M | Domain/QA | Gold labels Talent/router vòng đầu | R0-03, người duyệt nghiệp vụ |
| R0-05 | P0-00 | READY | S | DevOps/AI | Lưu baseline revision hiện tại và compare command | R0-02 |
| R0-06 | P0-08 | BLOCKED | M | DevOps/QA | CI quality gate ban đầu; chỉ bật blocking sau calibration | R0-04, R0-05 |
| RA-01 | P0-01 | READY | M | Backend/AI | Dataclass/schema `RadarTurnPlan v1` + JSON validation | R0-01 |
| RA-02 | P0-01 | READY | M | Backend/AI | Adapter từ Talent/general/prospect intent hiện tại sang plan chung | RA-01 |
| RA-03 | P0-01 | BLOCKED | M | AI/QA | Router policy: explicit intent > context > surface prior | RA-02, R0-04 |
| RA-04 | P0-01 | READY | M | Backend/QA | Contract tests cùng input/context/quyền và cross-surface cases | RA-01 |
| RA-05 | P0-02 | READY | M | Backend | `ConversationEnvelope v2` schema + backward adapter | RA-01 |
| RA-06 | P0-02 | READY | M | Backend | Token-budgeted recent turns + structured rolling summary | RA-05 |
| RA-07 | P0-02 | READY | M | Backend/AI | Active entities/constraints/last-result độc lập summary | RA-05 |
| RA-08 | P0-02 | READY | M | Backend | Memory top-K, scope, TTL, consent và injection filtering | RA-05 |
| RA-09 | P0-02 | BLOCKED | L | Backend/AI | Nối envelope v2 vào Talent, Prospect, general, web, tool loop | RA-06–RA-08 |
| RA-10 | P0-03 | READY | M | Backend/Data | `EntityRef` contract và confidence/ambiguity | RA-05 |
| RA-11 | P0-03 | READY | M | Backend/Data | SQL resolution cho Person/Company/Job/Opportunity, bỏ full scan | RA-10 |
| RA-12 | P0-03 | READY | M | Backend/QA | Trùng tên, đại từ, ordinal và hỏi-lại tests | RA-07, RA-11 |
| RA-13 | P0-04 | READY | M | Backend/AI | Typed constraint AST: must/prefer/exclude/range/time/geo/unknown | RA-01 |
| RA-14 | P0-04 | BLOCKED | L | Backend/Data | Compiler deterministic theo coverage/provenance | RA-13, field inventory |
| RA-15 | P0-04 | BLOCKED | M | Backend | Exhaustive paging/batched judge thay structured-pin cap | RA-14 |
| RA-16 | P0-04 | BLOCKED | M | QA/Domain | Gold cases tổ hợp, phủ định và unknown-policy | RA-13, người duyệt nghiệp vụ |
| RA-17 | P0-05 | READY | M | Backend/Data | Freshness event + fingerprint/version state machine | R0-01 |
| RA-18 | P0-05 | READY | M | Backend/DevOps | Retry/dead-letter/resume và zero-vector failure gate | RA-17 |
| RA-19 | P0-05 | BLOCKED | M | Frontend/DevOps | Coverage/stale/failure dashboard và alert | RA-17, RA-18 |
| RA-20 | P0-06 | BLOCKED | M | Security/Backend | Field/source policy tại model/tool/web boundary | RA-24 |
| RA-21 | P0-06 | BLOCKED | M | Security/QA | Adversarial suite: PII, ACL, injection, SSRF, tool tamper | RA-20 |
| RA-22 | P0-10 | READY | M | Backend/AI | Prompt/schema registry, hash và trace snapshot | R0-01 |
| RA-23 | P0-10 | BLOCKED | M | AI/QA | Prompt canary/rollback và compatibility tests | RA-22, R0-05 |
| RA-24 | P0-11 | DISCOVERY | M | Data/Security | Field-purpose-provider-retention-ACL inventory bốn miền | — |
| RA-25 | P0-11 | BLOCKED | M | Backend/Data | Deletion propagation qua cache/vector/event/memory | RA-24 |
| RA-26 | P0-12 | READY | M | DevOps/Backend | Feature flags + kill switches theo surface/task | — |
| RA-27 | P0-12 | BLOCKED | M | DevOps/QA | Canary + rollback drill trên clone/staging | RA-19, RA-23, RA-26 |

### Code-pointer map cho delivery tickets

| Ticket group | Điểm bắt đầu cần đọc/sửa; không phải danh sách file đóng |
|---|---|
| R0-01–R0-06 | `talent/management/commands/answer_eval.py`, `corpus_qa_eval.py`, `ai/tests_*`, `docs/benchmark/`, CI workflows |
| RA-01–RA-04 | `ai/intent.py`, `ai/tasks.py`, `talent/answer/plan.py`, `talent/answer/chat.py`, `ai/stream_views.py`, Prospect endpoints |
| RA-05–RA-09 | `ai/projection.py`, `conversation_state.py`, `thread_state.py`, `models.py`, `talent/answer/engine.py`, `rb`/Prospect conversation path |
| RA-10–RA-12 | `talent/answer/resolve.py`, `ai/projection.py`, `people`, `hiring`, `rb` models |
| RA-13–RA-16 | `talent/answer/structured_match.py`, `plan.py`, `retrieve.py`, `aggregate.py`, `intel/field_rules.py` |
| RA-17–RA-19 | `talent/vector_index.py`, `talent/signals.py`, `intel/queue.py`, `intel/extraction.py`, Settings/operations UI |
| RA-20–RA-21 | `accounts/privacy.py`, `ai/pii.py`, `prompt_guard.py`, `toolset.py`, `tool_handlers.py`, `websearch.py` |
| RA-22–RA-23 | `ai/tasks.py`, `router.py`, `adapter.py`, `providers.py`, `TaskModelRoute`, Settings AI UI |
| RA-24–RA-25 | `people`, `intel`, `rb`, `social`, conversation/cache/vector/event models và retention commands |
| RA-26–RA-27 | Django settings, task routes, deploy/preflight/benchmark workflows, production verification playbook |

### Ticket contract bắt buộc

Khi đưa một dòng trên vào sprint, tạo ticket chi tiết theo mẫu:

```text
ID / parent / owner / status / estimate
Outcome người dùng hoặc vận hành
In scope / out of scope
Code và data contracts bị tác động
Migration/backfill/dry-run/rollback
Acceptance tự động + nghiệm thu nghiệp vụ
Telemetry/SLO/cost budget
Feature flag, rollout %, kill switch
Evidence sau production verification
```

### Vertical slices — cách giao hàng, không làm ngang từng lớp

1. **VS-1 Talent continuity:** hỏi tìm người → hỏi tiếp bằng đại từ → đổi tiêu chí → vẫn đúng người/constraint,
   có citation và trace. Dùng R0 + RA-01–RA-12.
2. **VS-2 Exhaustive Talent:** truy vấn must/exclude/range có hơn 40 người phù hợp → không bỏ do cap, unknown
   được báo riêng. Dùng RA-13–RA-19.
3. **VS-3 Internal + web:** hỏi thông tin kho rồi yêu cầu cập nhật web → không gửi PII/CV ra backend web,
   nguồn nội bộ và web tách rõ. Dùng RA-20–RA-23.
4. **VS-4 Safe proposal:** tìm/so sánh → tạo draft → approval card → receipt; chưa mở external write.
   Dùng P0-07/P1-01/P1-02 sau Release A.
5. **VS-5 RB discovery-to-pilot:** chỉ bắt đầu sau P1-11; một use case khách hàng có data contract, DNC,
   evidence và multi-turn hoàn chỉnh trước khi tổng quát Customer Answer Engine.

### Ready queue đề xuất cho sprint đầu

Không bắt đầu bằng router. Thứ tự thực thi:

1. `R0-01` → `R0-02` → `R0-05`: dựng manifest, runner và chụp baseline hiện tại.
2. Song song `R0-03` và `RA-24`: chuẩn bị dữ liệu gắn nhãn có consent/ẩn danh và inventory governance.
3. `RA-01`, `RA-05`, `RA-10`, `RA-13`, `RA-22`, `RA-26`: chỉ dựng contract/version/flag, chưa đổi
   hành vi production.
4. Khi `R0-04` có nhãn nghiệp vụ, triển khai `RA-02` → `RA-03` → `RA-04` sau feature flag.
5. Chỉ bật CI blocking (`R0-06`) sau khi baseline chạy ổn định và quality budget được phê duyệt.

## 15. Trạng thái epic theo code hiện tại

Đây là ước lượng audit để tránh làm lại, không phải phần trăm nghiệm thu production. Phải cập nhật bằng
evidence mỗi khi đóng ticket.

| Epic | Status | Phần có thể tái sử dụng | Khoảng trống quyết định |
|---|---|---|---|
| P0-00/P0-08 | PARTIAL | `answer_eval`, corpus eval, tests AI/web/memory/tool, `ai/baseline.py` manifest (R0-01 DONE) | runner chung gọi hết các eval hiện có + gate CI (R0-02, R0-06) + gold labels |
| P0-01 | PARTIAL | `ai.intent`, Talent `QueryPlan`, surface heuristics | turn plan và policy chung |
| P0-02 | PARTIAL | threads/messages/projection/memory API | envelope contract được mọi nhánh dùng đủ |
| P0-03 | PARTIAL | named pin, last-result IDs | entity registry đa loại, ambiguity, không full scan |
| P0-04 | PARTIAL | structured match và deterministic aggregate | typed constraints tổng quát, exhaustive paging |
| P0-05 | PARTIAL | fingerprints, embedding state, extraction queue | continuous SLO/dashboard/failure gate đầy đủ |
| P0-06 | PARTIAL | RBAC, prompt guard, PII/contact redaction | row/field policy thống nhất và adversarial coverage |
| P0-07 | PARTIAL | read/proposal tools, RBAC | approval/idempotency/receipt cho write tiers |
| P0-09 | PARTIAL | resume endpoint, event log, background completion | durable worker/checkpoint/concurrency control |
| P0-10 | PARTIAL | task registry/model routing/tests | prompt/schema version, canary và rollback |
| P0-11/P0-12 | PARTIAL | privacy helpers, migrations, deploy workflows | formal data inventory và rollback drills |
| P1-03 | PARTIAL | 8 tool handlers và Talent action branch | requisition/shortlist/workspace actions |
| P1-04/P1-11 | DISCOVERY | Prospect search, RB agent/scoring | governed customer evidence engine |
| P1-05 | PARTIAL | common answers, model chat, attachments một phần | general utilities và contract thống nhất |
| P1-06 | PARTIAL | multi-backend web search + synthesis | fetch/rank/freshness/research/provenance |
| P1-01/P1-02 | PARTIAL | handwritten/graph agent loops, toolset | durable orchestration + unified risk protocol |
| P1-09/P1-10 | PARTIAL | feedback API, histories, SSE/progress | feedback UI mọi surface và unified experience |
| P1-12 | DISCOVERY | AgentBase integration references hiện có | ADR dựa trên benchmark |
| P2/P3 | DEFERRED | nhiều primitive đã tồn tại | chỉ mở khi Release A/C đạt gate |

## 16. Các quyết định cần chủ dự án/nghiệp vụ phê duyệt

1. Các field Customer/RB được phép gửi tới từng provider/model và quyền theo RM/đơn vị.
2. Gold labels và quality budget: bỏ sót nào là critical, precision/latency/cost nào chấp nhận được.
3. Những memory nào Radar được tự đề xuất nhớ; retention mặc định và quyền sử dụng feedback.
4. Tool write nào được mở, ai được approve, approval tồn tại bao lâu và hành động nào cấm tuyệt đối.
5. Có tách runtime sang AgentBase hay tiếp tục embedded Django sau khi ADR có số liệu.
6. Quy mô dữ liệu/đồng thời dự kiến trong 12–24 tháng để chốt capacity target.
