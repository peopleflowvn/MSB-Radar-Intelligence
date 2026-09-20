# Radar AI Search — Smart Retrieval & Deep Evidence Execution Backlog

**Cập nhật:** 20/09/2026  
**Phiên bản:** v3 — scale-ready, vertical slice  
**Trạng thái:** Wave 0 `READY`; các ticket còn lại `PLANNED` cho tới khi có owner là người cụ thể  
**Phạm vi:** Talent, Growth/RB, Intelligence V2, Product Core retrieval, evidence, ranking và answer composition  
**Quan hệ:** backlog này là delivery slice chuyên sâu của `RADAR_AI_AGENT_BACKLOG.md`; khi trùng phạm vi, ticket `SEARCH-*` là nguồn thực thi chi tiết, backlog tổng chỉ giữ liên kết/trạng thái. Xem mục 15 về các tài liệu kế hoạch chồng chéo.

### Trạng thái đọc ở đâu

Tài liệu này là **đề bài**: mục 1–16 là yêu cầu, acceptance và gate, và một
increment implementation không được hạ chúng xuống cho khớp với những gì đã làm.

- Trạng thái **ticket**: bảng 17.3.
- Trạng thái **slice** của P1-02 và P1-03: hai bảng trong mục 9.
- Lịch sử thay đổi: mục 17.7 (changelog) và git log.
- Việc tiếp theo: mục 17.10.

Tóm tắt ngày 20/09/2026: Wave 0 (H1–H4) và nền Search V2 đã có code + test local;
release production gần nhất là `aba4e2b` với `SEARCH_PLAN_V2_MODE=off`, nên chưa
có ticket nào `PRODUCTION ACCEPTED`. Các gate còn ở ngoài local: gold set hai
người gán nhãn, fixture 500k trên staging, ADR vector và cost, capacity provider,
phê duyệt pháp chế, deploy/canary và cửa sổ quan sát 24 giờ.

### Thay đổi so với v2

1. Thêm **Wave 0 hotfix** (SEARCH-H-*) chạy ngay, không chờ baseline: lỗi đang làm hỏng production được sửa trước khi đo.
2. **Thiết kế cho quy mô 500.000 ứng viên** (mục 1.2, 3.4): mọi thiết kế phải đẩy lọc xuống database, không quét Python toàn kho, không nhét danh sách ID vào `IN (...)`, và giới hạn chi phí LLM theo dạng phễu.
3. **Gold set và scale fixture chuyển lên P0** (P0-05, P0-06) vì các release gate P0/P1 phụ thuộc chúng. P2-02 v2 chỉ còn phần mở rộng.
4. **Judgement cache lên P1** (từ P2-00) và **cost budget** là gate bắt buộc: ở quy mô trăm nghìn hồ sơ, không có cache và trần chi phí thì exhaustive mode không khả thi.
5. Mỗi ticket có dòng **Hiện có → Delta** để tái dùng code đã có thay vì viết lại.
6. Giao theo **vertical slice Talent** trước (Wave 2), sau đó mới mở rộng quy mô (Wave 3) và RB (Wave 4).
7. Xếp hạng theo giới tính/tuổi/hôn nhân tách thành **gate pháp chế** riêng, mặc định tắt.

---

## 1. Mục tiêu và định nghĩa đúng

Radar phải tìm kiếm thông minh bằng code trước, dùng AI đúng chỗ và chứng minh được đã làm gì:

1. Hiểu câu hỏi theo góc nhìn `TALENT`, `CUSTOMER`, `BOTH`, `GENERAL` hoặc `NEEDS_CLARIFICATION`.
2. Biên dịch yêu cầu thành cây điều kiện có kiểu (`must`, `prefer`, `exclude`, range, temporal, geo), giữ đúng `AND/OR/NOT`.
3. Chạy structured SQL, field-aware full-text/Boolean, alias Anh–Việt/có dấu–không dấu và dense vector song song.
4. Hợp nhất/dedupe theo Person; không dùng top 60 như ranh giới đúng/sai.
5. Dùng code xác định chắc chắn mọi điều có thể xác định; AI chỉ đọc và phán đoán phần ngữ nghĩa/không cấu trúc.
6. Cho AI đủ bối cảnh từ CV, Edge, fact và lịch sử nghiệp vụ mà không nhét toàn bộ kho vào một prompt.
7. Phân nhóm/xếp hạng có evidence; `unknown` không được biến thành `not matched`.
8. Trả kết quả nhanh ở interactive mode và xử lý đủ ở exhaustive mode, trong trần chi phí đã duyệt.
9. Radar chỉ phân tích/khuyến nghị; người dùng quyết định cuối cùng.

### 1.1. “Đúng, đủ, không bỏ sót” nghĩa là gì

- **Deterministic completeness:** 100% Person trong phạm vi quyền thỏa điều kiện cấu trúc/Boolean đã biên dịch phải có trong CandidateSet. Có thể kiểm chứng bằng SQL/gold fixture.
- **Retrieval coverage:** mọi nhánh đã khai báo đều chạy hoặc mang trạng thái degraded; union count, cursor và query expansion được ghi lại.
- **Semantic recall:** không thể tuyên bố tuyệt đối. Đo trên gold set có nhãn bằng Recall@CandidateSet và missed-case audit.
- **Judgement completeness:** exhaustive chỉ hoàn tất khi mọi candidate có verdict (bằng code hoặc AI), hoặc lỗi/unknown/chưa đọc được liệt kê rõ.
- **Evidence completeness:** mọi constraint được đối chiếu với các section/source liên quan; không đồng nhất “không thấy trong vài đoạn đầu” với “không có”.

Không được dùng cụm “đã rà soát toàn bộ” nếu chỉ đạt một phần các điều trên.

### 1.2. Mục tiêu quy mô

Kho hiện có khoảng 1.000 Person, nhưng mọi thiết kế trong backlog này phải đúng và đạt SLO ở quy mô sau (xác nhận lại bằng ADR ở P0-00):

| Chiều | Mục tiêu thiết kế | Headroom |
|---|---:|---:|
| Person / TalentProfile | 500.000 | 1.000.000 |
| CV/document mỗi Person | ~1,5 | — |
| CV chunk | ~5.000.000 | 10.000.000 |
| Tăng mới/cập nhật mỗi ngày | 5.000 Person | 20.000 |
| Người dùng đồng thời | 30 | 100 |
| CandidateSet sau lọc cứng | tới 100.000 Person | — |

Hệ quả bắt buộc:

- **Không lượt nào được đọc sâu toàn kho bằng LLM.** 500.000 hồ sơ × ~3.000 token là ~1,5 tỉ token mỗi lượt. Phạm vi đọc sâu luôn bị giới hạn bởi phễu (mục 3.4) và trần chi phí.
- **Mọi thống kê/đếm** (“bao nhiêu người ở Hà Nội”) chạy bằng SQL aggregate, không qua LLM, không qua tập đọc sâu.
- **Không lọc trong Python trên toàn kho.** Mọi lọc cứng phải là predicate SQL dùng index.
- **Scope/RBAC là predicate SQL** (join/EXISTS), không phải danh sách ID nạp vào bộ nhớ rồi truyền vào `IN (...)`.
- Bộ nhớ/ổ đĩa vector phải được tính trước (P0-02): 5 triệu vector `float32` 1024 chiều là ~20 GB dữ liệu thô, chưa tính HNSW.

---

## 2. Baseline production đã xác minh

Đo trực tiếp trên PostgreSQL production (Oracle VPS Core, container
`msbradar-db`) lúc 20/09/2026 14:00 bằng truy vấn read-only. Số liệu cũ của bản
v2 (1.075 Person) đã lạc hậu vì 462 ứng viên không có CV đã bị xoá ngày 19/09.

| Hạng mục | Hiện trạng | Ghi chú |
|---|---:|---|
| Person applicant / TalentProfile | 611 / 611 | |
| Document | 679 | |
| CV chunk / đã embed | 2.221 / 2.221 | 100% |
| **SearchProjection / BaseDossier** | **61 / 61** | **chỉ phủ 10% ứng viên — xem 17.11** |
| CandidateSetRun / Member / JudgementCache | 0 / 0 / 0 | V2 chưa chạy trên prod (`SEARCH_PLAN_V2_MODE` chưa đặt) |
| RB evidence chunk / vector | 26 / 0 | cột `vector` chưa chốt chiều, chưa có HNSW |
| PostgreSQL / pgvector | 16.15 / 0.8.6 | 0.8.6 có iterative scan cho filtered ANN |
| `pg_trgm` | có sẵn, **chưa cài** | migration 0016 sẽ cài (role hiện tại là superuser) |
| Đĩa / RAM của host | 41 GB đã dùng trên 49 GB; 5,9 GB RAM | **không đủ cho fixture 500k — xem P0-06** |

Chiều vector thật trong DB:

| Cột | Kiểu | HNSW |
|---|---|---|
| `talent_cvchunk.embedding` | `vector(1024)` | có, cosine |
| `talent_personsearchdocument.embedding` | `vector(1024)` | có, cosine |
| `rb_prospectevidencechunk.embedding` | `vector` (chưa chốt chiều) | không |

- **Lệch chiều đang làm hỏng production:** `EmbeddingConfig.dimensions = 768`
  nhưng model đang dùng là greennode `baai/bge-m3` sinh vector 1024 và cột/HNSW
  cũng là 1024. Log `msbradar-hub` ngày 20/09 (13:02, 13:04): *"tắt nhánh vector
  cho lượt này: semantic_degraded: vector dimension mismatch configured=768
  query=1024 stored=1024"* — 12 lần trong 48 giờ, tức **mọi lượt tìm kiếm hiện
  chạy không có nhánh ngữ nghĩa**. Chỉ cần sửa một giá trị (768 → 1024).
- **Provider 48 giờ** (`ai_llmcall`): 254 lượt thất bại HTTP 404 vì gửi model
  của hub khác sang Gemini (`deepseek/deepseek-v4-pro` 85, `z-ai/glm-5.2` 85,
  `deepseek-v4-flash` 84); 46 lượt HTTP 402 (Gemini hết billing); 66 lượt
  greennode bị giới hạn tốc độ; 77 lượt timeout ở `rb_prospect_search`.
  `MSB_AI_DISABLED_PROVIDERS` **chưa được đặt trên prod**, nên acceptance của
  H1 chưa đạt.
- **Token 48 giờ:** judge `qwen3.7-plus` 1,13 triệu token; `rb_prospect_search`
  794 nghìn; compose `deepseek-v4-pro` 149 nghìn. Đây là mốc cho trần chi phí ở
  P0-00.
- **AnswerRun 48 giờ:** 27 done, 3 timeout.
- Kế hoạch truy vấn đo thật trên prod: `title_norm LIKE '%…%'` cho **Seq Scan**
  (61 hàng, không index nào phục vụ được), còn `to_tsvector(...) @@ to_tsquery`
  dùng đúng `talent_searchprojection_fts_gin` (Bitmap Index Scan). Đây là lý do
  của migration 0016.

### 2.1. Baseline mất bằng chứng

- Talent: nhóm đầu tối đa 4 CV passage, đuôi 2; mỗi passage 700 ký tự (`talent/answer/retrieve.py`: `PASSAGES_PER_PERSON`, `TAIL_PASSAGES`, `PASSAGE_CHARS`; `POOL=60`).
- Talent profile/Edge projection cũng bị cắt 700 ký tự.
- RB: nhóm đầu 5 passage, đuôi 2; mỗi passage 700 ký tự; `summary` bị cắt 350 (`rb/answer/evidence.py`).
- Compose source snippet bị cắt 320 ký tự (`talent/answer/compose.py: SNIPPET_CHARS`). Đây là vấn đề compose/explainability, tách khỏi lượng evidence judge đã đọc.

Tỷ lệ nội dung thực sự được phủ phải được đo theo section/constraint/corpus. Con số 40–60% chỉ là giả thuyết cần kiểm chứng, không dùng làm release gate.

### 2.2. Code hiện có cần tái dùng hoặc thay thế

| Thành phần | Vị trí | Dùng lại | Không mở rộng được ở 500k vì |
|---|---|---|---|
| Ghim exact match vượt top 60 | `talent/answer/structured_match.py` | ý tưởng + test case | nạp `ExtractedFact`/`TalentProfile` vào Python rồi so khớp chuỗi; truyền `universe_ids` vào `IN` |
| Đếm/thống kê toàn kho | `talent/answer/compose.py`, `talent/answer/plan.py` (nhánh count) | giữ, chuẩn hóa thành SQL aggregate | — |
| FTS có index GIN | `talent/answer/retrieve.py: _ranked_fts` | biểu thức khớp index, cột `*_norm` bỏ dấu | nối token bằng `" | "` (luôn OR); `ts_rank_cd` trên toàn tập khớp |
| Hợp nhất RRF | `retrieve.py: fuse_candidates` | giữ làm thứ tự xử lý | pool 60 đang là quyền tồn tại |
| Bỏ dấu không cần `unaccent` | cột `*_norm`, migration `talent/0007` | giữ | — |
| Eval | `ai/brain_eval.py`, lệnh `brain_retrieval_eval`, `brain_workflow_eval`, `core/.../retrieval_eval` và các case hồi quy gần đây | nền cho P0-00/P0-05 | chưa có gold nhãn Person × constraint |
| RB evidence index | `rb/evidence_index.py`, `rb/models.py` | giữ schema | 0 vector |

---

## 3. Nguyên tắc “tìm kiếm thông minh bằng code”

### 3.1. Code làm trước, AI không thay database engine

Code phải xử lý:

- RBAC/scope và tập Person được phép đọc, dưới dạng predicate SQL;
- canonical field, alias, dấu tiếng Việt, viết tắt, địa danh;
- exact/range/date/negation và Boolean AST;
- SQL/GIN/HNSW query, paging, union, intersection, exclusion và dedupe;
- hard-constraint verdict khi dữ liệu có cấu trúc đủ tin cậy;
- mọi phép đếm/thống kê;
- coverage, missing/unknown, sort ổn định và tie-break;
- cache/fingerprint, deadline, retry, backpressure và trần chi phí.

AI xử lý:

- hiểu ý định/câu chữ mơ hồ;
- đề xuất semantic concepts có schema;
- đọc evidence không cấu trúc;
- so khớp kinh nghiệm có thể chuyển đổi;
- giải thích fact/suy luận và khoảng trống cần xác minh;
- viết câu trả lời từ verdict đã kiểm chứng.

### 3.2. Retrieval nhiều tầng

Boolean **không phải** là cơ chế tìm kiếm duy nhất và không được dùng để biến
mọi synonym/khái niệm semantic thành một giant `OR`. Vai trò của Boolean/SQL là
giữ correctness cho điều kiện cứng; vai trò của hybrid retrieval là tăng recall
để tạo CandidateSet; vai trò của T2/T3 là xác minh ứng viên thực sự thỏa gì.

Mỗi constraint trong plan bắt buộc thuộc đúng một lớp:

- **`HARD_DETERMINISTIC`:** bắt buộc và có thể xác minh đáng tin cậy bằng field
  có kiểu/index, ví dụ location, range năm kinh nghiệm, application date,
  source, trạng thái. Lớp này được phép lọc/exclude ở T0.
- **`HARD_SEMANTIC`:** người dùng nói là bắt buộc nhưng dữ liệu cần đọc/ngữ
  nghĩa để kết luận, ví dụ “đã dẫn dắt chuyển đổi số tương tự”. Lớp này **không
  được lọc rơi ở retrieval**; candidate chỉ được pass/fail sau evidence judge.
- **`PREFERENCE`:** “ưu tiên/nếu có thì tốt”; chỉ tạo signal và re-rank, không
  làm ứng viên biến mất khỏi CandidateSet.

Nếu planner không đủ chắc constraint thuộc lớp nào, mặc định là
`HARD_SEMANTIC` hoặc yêu cầu làm rõ; không tự hạ thành filter cứng.

1. **Exact/structured:** trường chuẩn trong bảng search projection có kiểu (mục 3.5), range, ngày, trạng thái, source/application metadata.
2. **Field-aware Boolean/FTS:** phrase, title, skill, company, education và CV section; giữ `AND/OR/NOT`, boost theo field, bỏ stopword/term quá phổ biến.
3. **Dense ANN:** tìm diễn đạt tương đương; không tự pass điều kiện `must`.
4. **Adaptive expansion:** chỉ mở rộng synonym/query khi coverage hoặc gold telemetry cho thấy cần; không tạo giant-OR.
5. **Candidate union:** hợp theo Person trong SQL, ghi nguồn/hit/rank từng nhánh.
6. **Deterministic verification:** áp hard constraint có thể kiểm bằng code trên toàn CandidateSet, trong SQL.
7. **AI evidence judge:** chỉ xử lý semantic/unknown và evidence tự do, trong phễu có giới hạn.

Candidate generation phải tách thành các nhánh độc lập, chạy song song và ghi
provenance thay vì nối tất cả từ khóa vào một truy vấn:

- exact identity và structured fields;
- canonical title/skill/company/location taxonomy;
- field-aware phrase/Boolean FTS;
- application position/source metadata;
- dense semantic Person/section retrieval;
- pinned/reference people từ hội thoại.

CandidateSet là **union theo Person** của các nhánh recall, sau đó mới áp
`HARD_DETERMINISTIC` intersection/exclusion. Mỗi member lưu tối thiểu
`matched_branches`, `matched_constraints`, rank/score từng nhánh và degraded
state. Một hit vector/FTS không tự pass `must`; một miss top-K cũng không làm
Person mất quyền tồn tại nếu họ đã vào từ nhánh khác.

Mỗi truy vấn phải có `explain plan` máy đọc được: AST, alias, nhánh, count trước/sau filter, index path, degraded state và latency.

### 3.3. Song song thông minh

Có thể chạy ngay và song song:

- permission scope;
- deterministic tokenizer/alias lookup;
- load index/projection metadata;
- LLM intent/plan;
- provider health/capacity check.

Sau đó reconcile thành một plan duy nhất rồi chạy song song structured, FTS và vector. Candidate dossiers được materialize nền; request chỉ tạo evidence view theo câu hỏi. Candidate judge chạy map-parallel có giới hạn, không phát request vô hạn.

### 3.4. Phễu chi phí — ai đọc bao nhiêu

| Tầng | Chạy trên | Công cụ | Chi phí/Person |
|---|---|---|---|
| T0 — Lọc cứng | toàn kho trong scope (≤ 500k) | SQL + index | ~0 |
| T1 — Điểm rẻ | toàn CandidateSet (≤ 100k) | feature theo query type: exact/structured, field-FTS, vector, branch agreement, freshness | ~0 |
| T2 — Verdict code | toàn CandidateSet | code trên projection/fact | ~0 |
| T3 — AI judge | interactive: top-K theo T1 (K mặc định 60–100); exhaustive: phần còn `unknown` sau T2, trong trần chi phí | LLM trên EvidenceView | token |
| T4 — Compose | verdict đã kiểm chứng | LLM | cố định mỗi lượt |

Quy tắc:

- Số Person ở T3 luôn được báo cáo tách khỏi tổng CandidateSet. Người chưa qua T3 hiển thị là “chưa đọc sâu”, không bao giờ là “không phù hợp”.
- Exhaustive phải **ước tính chi phí và thời gian trước khi chạy** (số candidate × token trung bình − cache hit). Vượt trần thì cần người dùng xác nhận hoặc thu hẹp điều kiện.
- Kết quả T3 được cache theo fingerprint (P1-07). Chạy lại cùng câu hỏi trên kho không đổi không tốn thêm token.

Interactive T3 **không chỉ lấy top-K thuần túy**. Budget đọc sâu được phân bổ
theo bốn bucket có dedupe:

1. **Top relevance:** nhóm điểm cao nhất để trả kết quả hữu ích sớm.
2. **Decision boundary:** hồ sơ sát ngưỡng hoặc có branch bất đồng, nơi AI có
   khả năng thay đổi verdict/rank nhiều nhất.
3. **Diversity coverage:** đại diện theo title/skill/source/application/section
   cluster để một kiểu hồ sơ hoặc một nhánh retrieval không chiếm toàn bộ K.
4. **Unknown/hard-semantic:** hồ sơ còn constraint bắt buộc chưa xác minh được.

Tỷ lệ mỗi bucket là cấu hình và được hiệu chỉnh bằng gold telemetry. Pinned
people luôn được đọc nhưng không chiếm hết budget của các bucket khác. Với câu
exact/range, structured score áp đảo; với câu semantic-transfer, vector/evidence
có trọng số cao hơn; với count/aggregate, bỏ toàn bộ ranking/LLM và dùng SQL.

Ranking chỉ quyết định **thứ tự xử lý và trình bày**, không quyết định
deterministic completeness. Mọi weight phải được ghi trong explain plan; không
có một bộ trọng số cố định dùng cho mọi query type.

### 3.5. Tầng dữ liệu cho quy mô lớn

- **Search projection có kiểu** (một dòng/Person): location/desired_location chuẩn hóa, years_experience số, title/skill/company/education dạng ID chuẩn (`int[]` + GIN), trạng thái, thời điểm cập nhật, scope keys. Sinh từ `TalentProfile` + `ExtractedFact` (current, not rejected) bằng materializer; không phải Person database thứ hai.
- **FTS theo field:** cột `tsvector` lưu sẵn (generated/materialized) với `setweight` theo field, trên văn bản đã bỏ dấu; GIN. Đếm khớp tách khỏi xếp hạng; `ts_rank` chỉ tính trên tập đã giới hạn.
- **Vector hai tầng:** ANN toàn cục chỉ trên vector cấp Person/section (≤ vài triệu dòng, cân nhắc `halfvec`). Vector cấp chunk dùng để chọn evidence **trong** một Person đã vào CandidateSet (tính khoảng cách chính xác trên tập nhỏ), không cần HNSW toàn cục cho 5–10 triệu chunk. Chốt bằng ADR ở P0-02.
- **Filtered ANN:** khi có lọc cứng, nếu tập sau lọc nhỏ hơn ngưỡng (ví dụ 20.000) thì tính khoảng cách chính xác trên tập đó; nếu lớn hơn thì dùng HNSW với iterative scan (pgvector ≥ 0.8) hoặc `ef_search` tăng, và ghi recall ước tính.
- **CandidateSet lớn** được lưu dưới dạng bảng ID + provenance gắn với run (keyset cursor), không giữ list trong bộ nhớ request.
- Chưa cần partition/replica ở 500k; chỉ mở khi load test ở P0-06/P1-12 chứng minh cần.

### 3.6. Branch budget và chiến lược theo loại câu hỏi

Không dùng cùng một query plan/trọng số cho mọi câu hỏi. Retrieval planner phải
chọn branch và budget theo `query_type`/constraint mix:

| Loại yêu cầu | Branch chủ đạo | Branch không cần hoặc chỉ fallback |
|---|---|---|
| Tên/người/công ty cụ thể | exact identity + structured + pinned | vector chỉ fallback |
| Range/location/date/source | SQL/B-tree/GIN structured | không cần AI để lọc |
| Chức danh/kỹ năng | taxonomy + field-FTS + structured | vector bổ sung recall |
| Kinh nghiệm tương đương/chuyển đổi | vector + section FTS + evidence | exact keyword không được làm hard filter |
| Count/aggregate | SQL aggregate | bỏ ranking/vector/LLM |
| Follow-up/compare | pinned/reference people | không tìm lại toàn kho nếu scope đã rõ |

Budget từng branch:

- structured/exact không cap membership của hard predicate;
- taxonomy/expansion bị giới hạn theo vocabulary version, IDF và query budget;
- FTS được cap phần tính rank, không làm mất exact/phrase hard hit;
- vector dùng exact distance nếu hard-filter population nhỏ, ANN thích nghi nếu
  lớn; `top_n/ef_search` được ghi trong explain;
- chunk retrieval chỉ chạy bên trong Person đã vào CandidateSet;
- T3 bị giới hạn bởi token/cost/deadline và bucket budget mục 3.4.

### 3.7. Completeness nhiều lớp và ablation bắt buộc

Không dùng một cờ `complete` duy nhất. Response/run phải tách tối thiểu:

- `deterministic_complete`: hard deterministic predicate đã được thực thi đủ;
- `branches_complete`: mọi retrieval branch đã khai báo đều chạy thành công;
- `semantic_recall_measured`: recall semantic đã được đo trên gold version cụ thể;
- `verification_complete`: mọi candidate đã qua T2/code verdict;
- `deep_read_complete`: mọi candidate cần T3 đã được đọc hoặc có lỗi liệt kê;
- `evidence_complete`: mỗi constraint có evidence hoặc missing reason;
- `answer_grounded`: claim cuối cùng đã qua citation verifier.

Mỗi benchmark/release gate phải chạy ablation trên cùng corpus/query set:

1. structured only;
2. structured + taxonomy/field-FTS;
3. structured + vector;
4. structured + taxonomy/field-FTS + vector;
5. full hybrid gồm application metadata và pinned/reference.

Báo cáo bắt buộc có Recall@CandidateSet từng cấu hình, unique hit từng branch,
overlap, false positive sau T2, latency, token/cost và missed-case audit. Không
tăng weight/top-N nếu ablation không chứng minh tăng recall hữu ích.

---

## 4. Kiến trúc đích

```text
BACKGROUND
Person/Document/Edge/Fact/Application changes (outbox)
        -> SearchProjection + field tsvector + Person/section vectors
        -> versioned MaterializedBaseDossier (section-aware)

ONLINE REQUEST
Question + context + scope
        -> parallel pre-plan work
        -> typed RadarTurnPlan
             -> HARD_DETERMINISTIC | HARD_SEMANTIC | PREFERENCE
        -> count/aggregate question?  -> SQL aggregate -> answer
        -> recall branches in parallel:
             exact/structured | taxonomy | field-FTS | application | vector | pinned
        -> SQL Person union + hard deterministic intersection/exclusion
        -> CandidateSet (run table) + branch provenance + coverage/explain
        -> T1 adaptive cheap score by query type
        -> T2 deterministic re-verification (whole CandidateSet)
        -> T3 top + boundary + diversity + unknown EvidenceView (+ cache)
        -> deterministic classify/rank/reduce
        -> T4 grounded compose/verify
        -> interactive partial or exhaustive final (cost-approved)
```

---

## 5. Quality budget, SLO và cost budget cần chốt ở P0-00

Các giá trị dưới đây là **mục tiêu khởi tạo**, phải được xác nhận bằng baseline và load test trên scale fixture (P0-06):

| Chỉ số | Mục tiêu khởi tạo |
|---|---:|
| Exact/structured candidate recall | 100% trên gold có dữ liệu xác định |
| Semantic Recall@CandidateSet | ≥ baseline; mục tiêu đề xuất 95% trên gold P0-05 |
| Must-constraint verdict có evidence/status | 100% |
| Tỉ lệ `unknown` trên gold | ≤ ngưỡng chốt ở P0-05 (chặn “an toàn nhưng vô dụng”) |
| Unsupported factual claim | 0 |
| T0+T1 retrieval P95 @ 500k | ≤ 2 giây |
| SQL aggregate/count P95 @ 500k | ≤ 1 giây |
| Interactive time-to-first-useful-result P95 | mốc 1: ≤ 30 giây (từ 95 giây); mốc 2: ≤ 10 giây |
| Interactive final P95 | ≤ 30 giây hoặc chuyển rõ sang background |
| Exhaustive throughput | đo baseline rồi chốt candidate/phút ở T3 |
| Chi phí token mỗi lượt interactive | trần chốt ở P0-00 |
| Chi phí mỗi lượt exhaustive | ước tính trước; vượt trần cần xác nhận |
| Backfill projection/dossier (không LLM) | ≥ 20.000 Person/giờ |
| Online provider success | ≥ 99% hoặc fallback thành công |
| Cross-scope/PII/contact leak | 0 |
| Silent partial answer | 0 |

P0-00 có quyền sửa mục tiêu hiệu năng/chi phí nếu dữ liệu chứng minh không khả thi; không được hạ correctness/safety gate để làm số đẹp.

---

## 6. Chuẩn ticket

Mỗi ticket có `status`, `effort`, `owner`, `dependency`, `flag`, **`hiện có → delta`**, `deliverable`, `acceptance`, **`scale check`**, `telemetry`, `rollout/rollback`.

- **Owner:** ghi tên người, không chỉ ghi vai trò. Ticket chỉ chuyển `READY` khi có owner. Vai trò tham chiếu: `AI/QA`, `Backend`, `Data/Index`, `Platform`, `Frontend`, `Product/Ops`.
- **Effort:** `XS` ≤ 1 ngày; `S` ≤ 3 ngày; `M` 4–7 ngày; `L` 1–2 tuần. Ticket lớn hơn phải tách tiếp trước sprint.
- **Scale check:** ticket đụng tới query/index/job phải có `EXPLAIN (ANALYZE, BUFFERS)` hoặc load test trên scale fixture P0-06, không chỉ trên kho 1.000 người.
- Không tăng hằng số 60/700 hoặc concurrency đơn thuần để đóng ticket.
- **Giới hạn việc dở dang:** tối đa **3** ticket ở trạng thái `PARTIAL` cùng lúc.
  Muốn mở ticket thứ tư thì phải đóng một ticket trước. Mười bảy ticket cùng
  `PARTIAL` nghĩa là không có gì được xác nhận trên production, và đó là cách một
  chương trình trông như đang chạy rất nhanh mà không giao được gì.
- **Nguồn trạng thái duy nhất:** trạng thái *ticket* chỉ ghi ở bảng 17.3; trạng
  thái *slice* chỉ ghi ở hai bảng slice của P1-02 và P1-03. Không ghi trạng thái
  ở chỗ thứ ba — bản v3 đã có lúc để P1-02A là `FOUNDATION IMPLEMENTED` ở mục 9
  trong khi 17.3 ghi `PARTIAL`.

---

## 7. Wave 0 — Hotfix production (chạy ngay, không chờ baseline)

Mỗi hotfix nhỏ, có test hồi quy, deploy độc lập. Số liệu trước/sau lấy từ log production hiện có.

### SEARCH-H1 — Bỏ fallback không dùng được

**Status/Effort/Owner:** `READY / XS / Platform`  
**Dependency:** không  
**Hiện có → Delta:** chuỗi fallback compose đang gồm Gemini trả HTTP 402 → loại khỏi chuỗi; fallback chỉ gồm provider đang có billing.  
**Acceptance:** không còn attempt 402 trong 24 giờ; compose fail thì answer mang trạng thái lỗi, không giả vờ complete.  
**Rollout/Rollback:** config; khôi phục chuỗi cũ bằng config.

### SEARCH-H5 — Fallback không được mang model của hub khác

**Status/Effort/Owner:** `READY / S / Platform`  
**Dependency:** không  
**Hiện có → Delta:** `_complete_once` lấy `model=` của người gọi rồi gửi nguyên
sang MỌI provider trong chuỗi dự phòng. Đo trên prod 48 giờ: 254 lượt gọi HTTP
404 (`deepseek/*`, `z-ai/*` gửi vào Gemini). Nay chuỗi provider được lọc theo mã
model đã ghim (`provider_serves_model`), và cặp (provider, model) bị từ chối
404/402 hai lần thì bị bỏ qua 15 phút thay vì thử lại mỗi lượt.  
**Acceptance:** 404 do sai cặp provider–model về 0 trong 24 giờ; không lượt nào
bị mất đường dự phòng khi vẫn còn provider phục vụ được model; chuỗi chỉ còn một
provider phục vụ được thì vẫn thử (không im lặng bỏ).  
**Telemetry:** số cặp bị bỏ qua, lý do, `skipped` trong thông báo lỗi.  
**Rollout/Rollback:** đi cùng deploy thường; rollback là revert commit.

### SEARCH-H2 — Xác minh và chặn lệch chiều vector

**Status/Effort/Owner:** `READY / S / Data-Index`  
**Dependency:** không  
**Hiện có → Delta:** config 768, cột/HNSW 1024 (migration cũ 1536) → xác định chiều thật của cột, vector đã lưu và vector query; nếu nhánh vector đang lỗi/bị bỏ qua thì đánh dấu `semantic_degraded` thay vì im lặng; thêm kiểm tra khi khởi động và fail closed.  
**Acceptance:** báo cáo chiều thật từng lớp; mismatch làm nhánh vector degraded có cảnh báo, không trả kết quả sai.  
**Đã xác minh trên prod 20/09:** cột và HNSW là `vector(1024)`, model
`baai/bge-m3` sinh 1024, `EmbeddingConfig.dimensions` = 768 → fail-closed đang
chạy đúng như thiết kế, nhưng **hệ quả là nhánh ngữ nghĩa tắt ở mọi lượt**. Phần
còn lại của ticket không phải code: đặt `dimensions = 1024` (qua `/settings` hoặc
một lệnh dữ liệu), rồi xác nhận log không còn `semantic_degraded`.  
**Rollout/Rollback:** validate-only log trước, enforce sau.

### SEARCH-H3 — FTS giữ ngữ nghĩa Boolean cho điều kiện must

**Status/Effort/Owner:** `READY / S / Backend`  
**Dependency:** không  
**Hiện có → Delta:** `_ranked_fts` nối mọi token bằng `" | "` → các token/phrase thuộc `must` nối `&` (phrase dùng `<->`); nhánh OR chỉ giữ cho recall ngữ nghĩa và không được tự pass `must`.  
**Acceptance:** case hồi quy “SQL và Python” trả đúng tập giao; case production 19/09 (4/12 lọt top 60) đạt 12/12 trong CandidateSet.  
**Scale check:** biểu thức vẫn khớp index GIN (xem `EXPLAIN`).  
**Rollout/Rollback:** flag `FTS_BOOLEAN_MUST`.

### SEARCH-H4 — `unknown` không thành `not matched`, answer nói đúng phạm vi đã đọc

**Status/Effort/Owner:** `READY / S / Backend + AI-QA`  
**Dependency:** không  
**Hiện có → Delta:** thêm tối thiểu `candidate_total`, `judged`, `unknown`, `not_read` vào response; judge/aggregate không được gán `NOT_MATCHED` khi evidence được chọn không chứa section liên quan; câu trả lời không dùng “không có ai/đã rà soát toàn bộ” khi `not_read > 0` hoặc `unknown > 0`.  
**Acceptance:** test dữ kiện ở passage thứ 5/cuối CV cho ra `unknown`, không phải `not matched`; test câu trả lời khi còn người chưa đọc.  
**Rollout/Rollback:** field additive; flag `UNKNOWN_SAFETY`. P0-04 mở rộng thành contract đầy đủ.

---

## 8. Wave 1 — P0 đo lường, gold set, nền quy mô

### SEARCH-P0-00 — Baseline, manifest, SLO và cost budget

**Status/Effort/Owner:** `PLANNED / M / AI-QA`  
**Dependency:** H1–H4 đã deploy (để baseline phản ánh hệ thống sau hotfix)  
**Flag:** read-only  
**Hiện có → Delta:** mở rộng `brain_retrieval_eval`/`retrieval_eval` → manifest chứa corpus fingerprint, route/model, dimension thực tế, candidate count từng nhánh, union/filter count, section/constraint evidence coverage, stage latency, token/cost và provider error; tách user/smoke/benchmark traffic.  
**Deliverable:** manifest + ADR chốt bảng mục 5 (kể cả trần chi phí interactive/exhaustive).  
**Acceptance:** sinh/compare được hai revision; ADR được duyệt.  
**Rollout/Rollback:** chỉ đọc; rollback là bỏ job/report mới.

### SEARCH-P0-05 — Gold set có nhãn

**Status/Effort/Owner:** `PLANNED / M / AI-QA + Product-Ops`  
**Dependency:** không (chạy song song P0-00)  
**Hiện có → Delta:** các case hồi quy hiện có là câu hỏi/đáp án → bổ sung nhãn Person × constraint (`supported/contradicted/unknown` + evidence span).  
**Deliverable:** tối thiểu 60 câu hỏi, gồm exact, Boolean AND/OR/NOT, range, địa danh có/không dấu, semantic/chuyển đổi kinh nghiệm, >60 kết quả, dữ kiện cuối CV, Edge/application, RB, câu thống kê; mỗi câu có danh sách Person đúng và hard negatives. Người gán nhãn và người review là hai người khác nhau; chỉ dùng dữ liệu trong phạm vi pháp chế đã duyệt.  
**Acceptance:** độ đồng thuận giữa hai người gán nhãn được đo; ngưỡng `unknown` tối đa được chốt; gold hỗ trợ tính Recall@CandidateSet và unique-hit theo branch cho ablation mục 3.7.
**Telemetry:** kích thước, phân bố loại case, version.

### SEARCH-P0-06 — Scale fixture và load harness

**Status/Effort/Owner:** `PLANNED / M / Data-Index + Platform`  
**Dependency:** không  
**Deliverable:** generator dữ liệu **tổng hợp** 500.000 Person (không có PII thật) với phân bố field/độ dài CV/số chunk mô phỏng theo kho thật; môi trường staging cùng cấu hình DB với production; harness đo P50/P95 cho T0/T1/count và EXPLAIN của từng mẫu query; cài sẵn gold case nhúng vào kho tổng hợp để đo recall ở quy mô lớn.  
**Acceptance:** tạo lại fixture được bằng seed; harness chạy trong CI hàng đêm hoặc theo yêu cầu; báo cáo dung lượng DB/index/RAM.  
**Scale check:** chính deliverable.  
**Chặn bằng hạ tầng (đo 20/09 trên VPS Core):** host chỉ còn 7,5 GB đĩa trống và
5,9 GB RAM, lại đang chạy cả TalentFlow. Fixture 500.000 Person **không chạy được
ở đây**. Hai lựa chọn, phải chốt bằng ADR: (a) fixture 150–200k chỉ gồm
`SearchProjection` + `TalentProfile` (không CV chunk) trong một **database riêng**
trên cùng PostgreSQL — đủ để lấy query plan thật, và ghi rõ là ngoại suy;
(b) thuê host riêng cho staging để chạy đủ 500k. Cho tới khi có (b), mọi phát
biểu về SLO ở 500k là ngoại suy, không phải đo.

### SEARCH-P0-01 — Provider capacity và fallback thực sự dùng được

**Status/Effort/Owner:** `PLANNED / M / Platform + AI-QA`  
**Dependency:** H1, P0-00  
**Flag:** `AI_PROVIDER_CAPACITY_V2`  
**Deliverable:** health/circuit breaker theo task; quota riêng online/background; reserve compose capacity; fallback chỉ dùng model/provider đã health-check/billing; deadline từng stage; rate limit theo token/phút cho backfill embedding.  
**Acceptance:** không retry storm khi 429; canary đạt provider success budget; backfill không làm đói online traffic.  
**Telemetry:** attempt, queue wait, 429/402/timeout, circuit state, fallback result.  
**Rollout/Rollback:** shadow health → 10% canary → tăng dần; flag về router cũ.

### SEARCH-P0-02 — Model–dimension–index contract và ADR lưu trữ vector

**Status/Effort/Owner:** `PLANNED / M / Data-Index`  
**Dependency:** H2, P0-06  
**Flag:** `VECTOR_CONTRACT_V2`  
**Deliverable:** dimension được probe/pin theo model revision; validation giữa config, query vector, document vector, DB column và HNSW; shadow column/index + alias khi đổi model. ADR chọn: chiều/kiểu (`vector` vs `halfvec`), cấp độ ANN toàn cục (Person/section) vs chunk, filtered ANN (mục 3.5), tham số HNSW, dung lượng RAM/đĩa ở 500k và 1M, chi phí/thời gian re-embed toàn kho.  
**Acceptance:** mọi lớp cùng dimension; mismatch fail closed; không xóa index đang phục vụ trước atomic switch; ADR có số đo trên scale fixture.  
**Telemetry:** configured/observed/stored dimension, model revision, coverage/index state, index size.  
**Rollout/Rollback:** validate-only → enforce; rollback validation flag/index alias.

### SEARCH-P0-03 — Đo truncation evidence

**Status/Effort/Owner:** `PLANNED / S / AI-QA + Backend`  
**Dependency:** H4, P0-00, P0-05  
**Flag:** `EVIDENCE_COVERAGE_TRACE`  
**Deliverable:** đo coverage hiện tại của 4/2×700, 5/2×700, profile 700, summary 350 theo chars, sections và constraints trên gold; tách judge evidence khỏi compose snippet 320.  
**Acceptance:** có baseline định lượng làm mốc cho P1-05; tỉ lệ `unknown` do H4 sinh ra được đo so với ngưỡng P0-05.  
**Telemetry:** available/selected chars, sections, constraint evidence, truncation reason.

### SEARCH-P0-04 — Coverage-truth answer contract

**Status/Effort/Owner:** `PLANNED / S / Backend + Frontend`  
**Dependency:** H4, P0-03  
**Flag:** `ANSWER_COVERAGE_V2`  
**Hiện có → Delta:** field tối thiểu của H4 → đủ `population`, `candidate_total`, `scheduled`, `judged`, `unknown`, `not_read`, `pending`, `failed`, `retrieval_degraded`, `semantic_available`, `cost_used`; thay cờ `complete` nhập nhằng bằng `deterministic_complete`, `branches_complete`, `semantic_recall_measured`, `verification_complete`, `deep_read_complete`, `evidence_complete`, `answer_grounded`; citation audit có `NO_CLAIMS/PASS/FAIL`.
**Acceptance:** UI phân biệt partial/final theo từng lớp và hiển thị “đã đọc sâu X / Y ứng viên trong CandidateSet”; không gọi toàn bộ CandidateSet là “phù hợp” trước khi verification hoàn tất.
**Telemetry:** mọi field trên + reason code.  
**Rollout/Rollback:** additive schema trước, UI sau; client cũ bỏ qua field mới.

---

## 9. Wave 2 — Vertical slice Talent (P1 lõi)

Mục tiêu của wave: một luồng Talent chạy trọn từ plan → projection/compiler → CandidateSet → evidence → verdict → rank → compose, đạt gate trên gold, và **đã chạy load test T0/T1 trên fixture 500k**. Mỗi ticket có phần “slice” (bắt buộc cho wave này) và phần “mở rộng” (có thể để wave sau).

### SEARCH-P1-00 — RadarTurnPlan đa miền và typed constraint AST

**Status/Effort/Owner:** `PLANNED / M / Backend + AI-QA`  
**Dependency:** P0-05  
**Flag:** `SEARCH_PLAN_V2`  
**Hiện có → Delta:** plan hiện tại (`talent/answer/plan.py`) → versioned plan cho `TALENT/CUSTOMER/BOTH/GENERAL/CLARIFY`, typed `must/prefer/exclude/range/temporal/geo`, semantic concepts, loại câu (`list/count/aggregate/compare`) và exhaustive intent; provenance từng constraint; mỗi constraint bắt buộc phân lớp `HARD_DETERMINISTIC/HARD_SEMANTIC/PREFERENCE`.
**Acceptance:** Boolean tree không mất; semantic-hard không bị biên dịch nhầm thành SQL filter; preference không loại Person; câu thống kê được định tuyến sang SQL aggregate; plan schema strict và fallback deterministic.
**Slice:** `TALENT` + `count/list`. **Mở rộng:** `BOTH/CUSTOMER`.  
**Telemetry:** plan version, domain/confidence, constraint source, clarification.  
**Rollout/Rollback:** shadow compare với plan cũ; canary theo user/team.

### SEARCH-P1-01 — SearchProjection và field index

**Status/Effort/Owner:** `PLANNED / L / Data-Index + Backend`  
**Dependency:** P0-02, P0-06  
**Flag:** `SEARCH_PROJECTION_V1`  
**Hiện có → Delta:** `structured_match.py` quét fact trong Python → bảng projection có kiểu (mục 3.5) với B-tree/GIN; field `tsvector` có trọng số trên văn bản bỏ dấu; scope keys để RBAC là predicate SQL; builder idempotent chạy đồng bộ khi dữ liệu đổi (bản slice), materializer nền ở P1-10.  
**Acceptance:** mọi điều kiện `structured_match` hiện xử lý được trả cùng kết quả qua SQL (shadow diff = 0 trên kho thật); không còn quét Python toàn kho.  
**Scale check:** T0 P95 ≤ 2 giây trên fixture 500k; EXPLAIN dùng index cho từng loại điều kiện.  
**Telemetry:** projection version, stale count, build ms.  
**Rollout/Rollback:** dual-read shadow; flag về đường cũ.

### SEARCH-P1-02 — Smart Query Compiler bằng code

**Status/Effort/Owner:** `PLANNED / L / Backend + Data-Index`  
**Dependency:** P1-00, P1-01  
**Flag:** `SMART_QUERY_COMPILER`  
**Hiện có → Delta:** alias thành phố trong `structured_match.py`, `_FTS_STOP`, `_SHORT_OK` → canonical dictionary có version cho title/skill/company/education/location/product; alias Anh–Việt, có dấu–không dấu, viết tắt, phrase; AST compiler chỉ sinh SQL filter cho `HARD_DETERMINISTIC`; `HARD_SEMANTIC` sinh retrieval/evidence requirement; `PREFERENCE` sinh scoring feature; FTS giữ `AND/OR/NOT/range`; stopword/IDF guard (term khớp > X% kho không được dùng một mình); adaptive expansion có telemetry, không giant-OR; explain plan và query budget.
**Acceptance:** gold SQL AND Python, title OR, NOT, experience range, temporal, Hà Nội/Hanoi; deterministic completeness 100%; broad term không làm cả kho lọt; semantic-hard không bị false-negative vì exact keyword; preference bỏ đi không đổi CandidateSet membership.
**Scale check:** EXPLAIN chứng minh GIN/B-tree/HNSW paths theo case trên fixture 500k.  
**Owner từ điển:** Product-Ops sở hữu nội dung alias, có quy trình review + version; Backend sở hữu compiler.  
**Telemetry:** AST/alias version, branch query count, before/after counts, index path, query ms, expansion reason.  
**Rollout/Rollback:** shadow candidate diff; rollback compiler flag.

#### P1-02 delivery slices — phải đóng theo thứ tự

| Slice | Nội dung | Acceptance bắt buộc | Trạng thái 20/09 |
|---|---|---|---|
| P1-02A — Constraint classification | Schema/provenance cho `HARD_DETERMINISTIC/HARD_SEMANTIC/PREFERENCE`; fallback không chắc → semantic/clarify | semantic-hard không thành SQL filter; preference không đổi membership | `IMPLEMENTED + LOCAL VERIFIED` |
| P1-02B — Canonical expansion | Vocabulary versioned cho title/skill/company/location/application; phrase, Anh–Việt, dấu/không dấu, abbreviation; IDF/stopword/query budget | không giant-OR; mỗi expansion có source/version; gold exact/alias đạt gate | `NOT STARTED` — alias vẫn là hằng số trong `search_v2.py` |
| P1-02C — Retrieval strategy planner | Chọn branch/budget theo query type và population sau hard filter; exact-distance vs ANN | count bỏ LLM/vector; exact/range ưu tiên SQL; semantic-transfer không bị exact keyword loại | `PARTIAL` — nhánh lexical đã chạy trong phạm vi filter cứng; chưa chọn budget theo query type |
| P1-02D — Explain/query guard | AST, branch plan, expansion reason, before/after count, index path, timeout/degraded | mọi query tái dựng được và broad query không quét/rank toàn bảng ngoài budget | `PARTIAL` — có `t0`, `branches`, `snapshot`, `fts_index_used`; thiếu EXPLAIN thật và timeout theo branch |

Không bắt đầu learned weight/reranker trước khi P1-02B/C có ablation trên gold.

### SEARCH-P1-03 — CandidateSet, paging, union và completeness contract

**Status/Effort/Owner:** `PLANNED / M / Backend`  
**Dependency:** P1-02  
**Flag:** `CANDIDATE_SET_V2`  
**Hiện có → Delta:** `fuse_candidates` với `POOL=60` → exact/structured, taxonomy, field-FTS, application metadata, vector và pinned chạy song song; union/dedupe theo Person trong SQL rồi áp hard-deterministic intersection/exclusion; CandidateSet lưu ID + `matched_branches/matched_constraints` + rank/score từng nhánh với keyset cursor; RRF/adaptive score chỉ quyết định thứ tự xử lý T3.
**Acceptance:** fixture >60 exact match trả đủ; không hard cap ẩn; một branch degraded không làm mất hit từ branch khác; vector/FTS hit không tự pass must; count chính xác tách khỏi rank; provenance tái dựng được vì sao Person vào tập.
**Scale check:** CandidateSet 100.000 Person tạo trong ≤ 2 giây, bộ nhớ request không tăng theo kích thước tập.  
**Telemetry:** eligible population, count mỗi nhánh, overlap/union, pages, capped/degraded state.  
**Rollout/Rollback:** shadow union diff → interactive canary.

#### P1-03 delivery slices — hybrid CandidateSet

| Slice | Nội dung | Acceptance bắt buộc | Dependency | Trạng thái 20/09 |
|---|---|---|---|---|
| P1-03A — Branch result contract | Chung schema `person_id/branch/matched_constraints/rank/raw_score/normalized_score/evidence_refs/degraded/reason` | branch có thể bật/tắt độc lập; provenance không mất qua union | P1-02A | `IMPLEMENTED + LOCAL VERIFIED` — `BranchHit` + provenance theo nhánh trong member |
| P1-03B — Structured/taxonomy/application | SQL branches cho projection, canonical taxonomy và application metadata | exact recall 100%; không Python full scan | P1-01, P1-02B | `PARTIAL` — structured xong; taxonomy/application chưa thành nhánh riêng |
| P1-03C — Field-aware FTS | weighted tsvector, phrase/Boolean, per-field hits | gold FTS recall; GIN path; broad-term guard | P1-02B | `IMPLEMENTED, CHƯA XÁC MINH POSTGRES` — cột generated `search_tsv` A/B/C/D + GIN, trigram cho 4 cột ngắn; chưa chạy trên PostgreSQL |
| P1-03D — Filtered vector | exact distance trên tập nhỏ, ANN thích nghi trên tập lớn | dimension fail-closed; recall/latency theo hard-filter population | P0-02, P1-02C | `NOT STARTED` — nhánh luôn báo `not_implemented` |
| P1-03E — SQL union/dedupe | Union mọi branch theo Person; lưu score/rank/provenance; keyset cursor | >60 trả đủ; unique branch hit không mất; request memory không tăng theo set | A–D | `PARTIAL` — union + dedupe + provenance đã có nhưng hợp nhất trong Python dưới trần snapshot; union một câu SQL chưa làm |
| P1-03F — Deterministic re-verification | Chạy lại toàn hard-deterministic constraints trên mọi member | FTS/vector hit không tự pass must; false positive có verdict/reason | P1-06 schema | `IMPLEMENTED + LOCAL VERIFIED` — `verify_members` |
| P1-03G — Completeness/degradation | Các lớp completeness mục 3.7 và branch failure semantics | một branch lỗi không xóa hit branch khác; không silent partial | A–F, P0-04 | `IMPLEMENTED + LOCAL VERIFIED` — bảy lớp trong `explain.completeness` và trong API |

**Gate trước T3/exhaustive UI:** P1-03A–G phải đạt gold + ablation; có thể giữ
API/job foundation hiện tại nhưng không mở exhaustive rộng khi CandidateSet mới
chỉ có structured branch.

### SEARCH-P1-04 — BaseDossier contract và tách section CV

**Status/Effort/Owner:** `PLANNED / M / Backend + Data-Index`  
**Dependency:** P0-03  
**Flag:** `DOSSIER_V1`  
**Deliverable:** versioned schema gồm structured profile, application history, Edge allowlist, accepted/conflicting facts, CV section refs, source lineage và missing/parse/conflict status. Tách section CV (`summary`, `experience`, `skills`, `education`, `project`, `certificate`, `language`, `other`) **bằng code/heuristic trước**, LLM chỉ là fallback có đếm chi phí. Chỉ dữ liệu được cấp quyền và phù hợp mục đích; contact redact trước model.  
**Acceptance:** schema validation, fingerprint/idempotency, deletion propagation, permission tests; không nhúng raw binary, không tạo Person database thứ hai; tỉ lệ CV cần LLM fallback được đo.  
**Slice:** build theo yêu cầu cho Person vào T3 + backfill kho hiện tại. **Mở rộng:** materializer nền ở P1-10.  
**Scale check:** chi phí tách section cho 500k CV (thời gian + token fallback) được ước tính.  
**Telemetry:** dossier version/fingerprint, source/section coverage, stale/conflict/missing.  
**Rollout/Rollback:** dual-build shadow; đọc schema cũ khi flag off.

### SEARCH-P1-05 — Query-specific EvidenceView và evidence fetch nhiều vòng

**Status/Effort/Owner:** `PLANNED / L / Backend + AI-QA`  
**Dependency:** P1-00, P1-04  
**Flag:** `EVIDENCE_VIEW_V2`  
**Hiện có → Delta:** 4/2 passage × 700 ký tự → chọn evidence theo từng constraint và section diversity bằng vector chunk tính trong phạm vi một Person; không cắt prefix mù; fetch thêm section/full text khi `unknown`; giới hạn vòng/token/time; evidence ID luôn resolve về nguyên bản.  
**Acceptance:** test passage thứ 5/cuối CV/Edge/application; hết budget là `unknown`; PII redaction giữ nguyên; evidence coverage theo constraint tăng so với P0-03; token trung bình/Person nằm trong trần P0-00.  
**Telemetry:** selected/available sections/chars, fetch rounds/reasons, budget, unresolved constraints.  
**Rollout/Rollback:** shadow evidence diff, canary; về selector cũ nhưng giữ H4.

### SEARCH-P1-06 — ConstraintJudgement schema và deterministic verdict

**Status/Effort/Owner:** `PLANNED / M / Backend + AI-QA`  
**Dependency:** P1-01, P1-05  
**Flag:** `JUDGEMENT_V2`  
**Deliverable:** mỗi constraint có `supported/contradicted/unknown`, value, confidence, evidence IDs, fact/inference, missing reason; strict boolean/numeric schema; T2 re-verify mọi `HARD_DETERMINISTIC` trên toàn CandidateSet, kể cả Person đến từ vector/FTS; T3 AI chỉ quyết `HARD_SEMANTIC`/evidence tự do.
**Acceptance:** unsupported numeric không sort; duplicate/missing ID retry đúng phần thiếu; partial không cache complete; `unknown != fail`; tỉ lệ `unknown` trong ngưỡng P0-05.  
**Telemetry:** verdict distribution, evidence support, parse/retry/partial, tỉ lệ verdict do code vs AI.  
**Rollout/Rollback:** dual judge/scorer shadow; rollback read path.

### SEARCH-P1-07 — Judgement cache và cost guard

**Status/Effort/Owner:** `PLANNED / M / Backend`  
**Dependency:** P1-06  
**Flag:** `SEARCH_CACHE_V2`  
**Hiện có → Delta:** chuyển từ P2-00 v2 → cache EvidenceView và ConstraintJudgement theo (dossier fingerprint, constraint canonical, schema/model/prompt version, scope); invalidation theo section khi dữ liệu đổi; partial/error không lưu là complete. Cost guard: ước tính token trước T3, trần theo lượt/người dùng/ngày, báo khi dừng vì trần.  
**Acceptance:** chạy lại cùng câu trên kho không đổi có cache hit ≥ 90%; không lượt nào vượt trần mà không có xác nhận; dữ liệu đổi thì kết quả cũ không được dùng.  
**Telemetry:** hit/miss/invalidate, token ước tính vs thực, lượt bị chặn vì trần.  
**Rollout/Rollback:** shadow write-only → read; flag tắt đọc cache.

### SEARCH-P1-08 — Deterministic classify, rank và reduce

**Status/Effort/Owner:** `PLANNED / M / Backend + Product-Ops`  
**Dependency:** P1-06  
**Flag:** `SEARCH_RANK_V2`  
**Deliverable:** nhóm `HIGH/MEDIUM/NEAR/UNKNOWN/NOT_READ/NOT_MATCHED`; must trước prefer; adaptive feature weights theo query type; stable sort/tie-break; objective fact bất biến, preference chỉ re-rank; T3 sampler chia budget cho top relevance, decision boundary, diversity coverage và hard-semantic/unknown.
**Acceptance:** cùng verdict/config cho thứ tự ổn định; missing không thành fail; giải thích từng điểm/nhóm; bỏ preference không đổi membership; sampler không để một branch/cluster chiếm toàn bộ K và báo coverage từng bucket.
**Gate pháp chế — thuộc tính nhân khẩu học:** giới tính, tuổi, tình trạng hôn nhân **không** là yếu tố xếp hạng mặc định, sau flag riêng `DEMOGRAPHIC_CONTEXT` mặc định tắt. Chỉ bật sau khi pháp chế duyệt bằng văn bản cho mục đích tuyển dụng (phê duyệt 19/09 chỉ bao gồm dùng dữ liệu ứng viên cho RB). Trước khi có duyệt, rà hành vi hiện có từ commit `b526d25` (dùng các thuộc tính này làm bối cảnh khuyến nghị) và đưa vào sau flag này. Khi bật: chỉ dùng khi người dùng yêu cầu rõ và có nguồn, tách fact/suy luận, ghi telemetry.  
**Telemetry:** group counts, score components, ranking movement/reason, số lượt dùng thuộc tính nhân khẩu học.  
**Rollout/Rollback:** shadow ranking + human compare; rollback flag.

### SEARCH-P1-09 — Grounded compose và source presentation

**Status/Effort/Owner:** `PLANNED / M / Backend + AI-QA + Frontend`  
**Dependency:** P0-04, P1-06, P1-08  
**Flag:** `COMPOSE_VERDICT_V2`  
**Deliverable:** compose nhận structured verdict + evidence refs, không cần toàn CV; snippet 320 chỉ là preview, mở được evidence đầy đủ; common verifier cho JSON/SSE/fallback; số liệu tổng trong câu trả lời lấy từ SQL/CandidateSet, không từ tập đã đọc sâu.  
**Acceptance:** mọi factual claim map evidence đúng Person; fallback không mất coverage; `NO_CLAIMS` không được báo PASS chất lượng.  
**Telemetry:** claims/cited/supported/invalid/missing, fallback reason.  
**Rollout/Rollback:** canary compose, deterministic fallback giữ nguyên contract.

**Gate cuối Wave 2:** gold P0-05 đạt bảng mục 5 (correctness), mốc 1 latency (≤ 30 giây), T0/T1 đạt SLO trên fixture 500k, canary Talent ổn định một tuần.

---

## 10. Wave 3 — Mở rộng quy mô và exhaustive

### SEARCH-P1-10 — Materializer nền và backfill

**Status/Effort/Owner:** `PLANNED / L / Data-Index`  
**Dependency:** P1-01, P1-04, P0-01  
**Flag:** `DOSSIER_MATERIALIZER`  
**Deliverable:** outbox/event khi Document/SourceRecord/Fact/Application đổi; rebuild chỉ phần ảnh hưởng (projection, tsvector, section, vector); backfill resumable có checkpoint; embedding theo batch có rate limit P0-01; dead-letter; reconciliation định kỳ giữa nguồn và projection.  
**Acceptance:** dữ kiện cuối CV, Edge và mọi application xuất hiện trong dossier; stale ≤ 5 phút ở tải bình thường; backfill ≥ 20.000 Person/giờ phần không LLM; ETA embedding toàn kho tính được theo quota.  
**Scale check:** backfill 500k trên fixture; đo tác động lên online P95 trong lúc backfill.  
**Telemetry:** queue lag, section counts/chars, parse confidence, rebuild ms/failure, stale count.  
**Rollout/Rollback:** backfill shadow; atomic projection version switch.

### SEARCH-P1-11 — Bounded parallel judgement và durable exhaustive job

**Status/Effort/Owner:** `PLANNED / L / Platform + Backend`  
**Dependency:** P0-01, P1-03A–G đã qua gold/ablation gate, P1-07, P1-09
**Flag:** `DURABLE_SEARCH_JOBS`  
**Deliverable:** AnswerRun queue; batch theo token/dossier size; pool riêng Talent/RB; quota provider/task/user; backpressure, jitter, circuit breaker, heartbeat, cancel/resume/idempotency; snapshot CandidateSet tại thời điểm bắt đầu; ước tính chi phí/thời gian trước khi chạy và cần xác nhận khi vượt trần.  
**Acceptance:** run 10.000 candidate ở T3 hoàn tất hoặc liệt kê lỗi; restart không mất run; concurrency không vượt cấu hình; DB connection không rò; online traffic được ưu tiên; không vượt trần chi phí đã xác nhận.  
**Telemetry:** queue/worker/batch/token/provider/retry/throughput/cost.  
**Rollout/Rollback:** exhaustive-only canary trước; interactive giữ runner cũ.

### SEARCH-P1-12 — Interactive và Exhaustive modes

**Status/Effort/Owner:** `PLANNED / M / Backend + Frontend + Product-Ops`  
**Dependency:** P0-04, P1-03A–G đã qua gold/ablation gate, P1-09, P1-11
**Flag:** `SEARCH_MODES_V2`  
**Deliverable:** interactive trả progressive, chuyển nền theo deadline; exhaustive có màn hình ước tính chi phí/thời gian, progress/resume/export; cùng plan/dossier/verdict contract.  
**Acceptance:** UI không gọi partial là final; reconnect không nhân đôi; exhaustive chứng minh judged/unknown/not_read/failed bằng eligible total; mốc 2 latency (TTFUR ≤ 10 giây).  
Không được mở exhaustive cho người dùng nếu bất kỳ retrieval branch bắt buộc nào còn `not_implemented`, `failed` hoặc chưa có kết quả ablation đạt gate; trạng thái này phải hiện là degraded/blocked thay vì “đã tìm toàn bộ”.
**Scale check:** load test 30 người dùng đồng thời trên fixture 500k.  
**Telemetry:** mode, TTFUR, final latency, completion/abandon/resume, chi phí/lượt.  
**Rollout/Rollback:** exhaustive opt-in, interactive canary sau.

---

## 11. Wave 4 — RB

### SEARCH-P1-13 — RB evidence population discovery, rebuild và embedding

**Status/Effort/Owner:** `DISCOVERY → PLANNED / M / Data-Index + Product-Ops`  
**Dependency:** P0-01, P0-02, P1-10  
**Flag:** `RB_EVIDENCE_INDEX_V2`  
**Deliverable:** xác định denominator customer/source và expected chunks; chỉ kết luận thiếu sau reconciliation. Sau đó rebuild idempotent qua materializer P1-10, embed, index và event refresh; tái dùng plan/compiler/evidence/judgement của slice Talent cho `CUSTOMER/BOTH`.  
**Acceptance:** 100% eligible source có indexed/embedded/error status; DNC hard block; benchmark lexical/vector; không coi 21 chunk tự thân là lỗi.  
**Telemetry:** customers/sources/chunks/vectors/stale/errors/index lag.  
**Rollout/Rollback:** shadow index, query canary; rollback alias/flag.

---

## 12. P2 — Tối ưu sau khi correctness đạt gate

Các mục P2 là optimization candidates, chưa được kéo vào sprint trực tiếp. Khi được ưu tiên, mỗi mục phải tách thành ticket delivery đầy đủ theo chuẩn mục 6.

- **SEARCH-P2-01 — Observability và capacity model** (`M / Platform`): dashboard candidate/coverage/dossier/batch/provider/token/cost/P50/P95; tách benchmark/user; dự báo exhaustive ETA, quota và dung lượng DB theo tốc độ tăng kho. Không log CV/contact/chain-of-thought.
- **SEARCH-P2-02 — Mở rộng evaluation và canary gate** (`L / AI-QA + Product-Ops`): mở rộng gold P0-05 lên vài trăm câu; NDCG, judgement accuracy, evidence recall, grounded claims, human acceptance; CI/canary budget.
- **SEARCH-P2-03 — Learned reranker/cross-encoder** (`DISCOVERY / AI-QA`): chỉ shadow sau P2-02; có thể thay một phần T3 bằng mô hình rẻ hơn để giảm chi phí ở quy mô lớn; không thay hard constraints.
- **SEARCH-P2-04 — Verified section summarization** (`M / Data-Index + AI-QA`): summary cache cho section dài, mỗi câu map về source span; không resolve được thì không dùng làm evidence cuối.
- **SEARCH-P2-05 — Explainable comparison workspace** (`M / Frontend + Product-Ops`): ma trận Person × constraint, evidence/unknown/conflict, preference re-rank; không sửa objective facts.
- **SEARCH-P2-06 — Mở rộng hạ tầng DB** (`DISCOVERY / Platform`): read replica, partition, tách vector store — chỉ khi load test hoặc tăng trưởng thật vượt headroom mục 1.2.

---

## 13. Thứ tự thực hiện và mốc

| Wave | Nội dung | Ước lượng | Giá trị người dùng thấy |
|---|---|---|---|
| 0 | H1–H4 | ~1 tuần | compose ổn định hơn, không bỏ sót AND, không nói sai “không có ai” |
| 1 | P0-00, P0-05, P0-06 song song; rồi P0-01, P0-02, P0-03, P0-04 | ~3–4 tuần | coverage hiển thị đúng; provider ổn định |
| 2A | Plan/projection: P1-00 + P1-01 + P1-02A/B/C/D; song song P1-04 | ~3–4 tuần | constraint đúng bản chất, vocabulary/branch plan giải thích được |
| 2B | Hybrid CandidateSet: P1-03A→B/C/D→E→F/G; P0-05/P0-06 ablation gate | ~3–4 tuần | SQL + FTS + vector union đủ recall, không top-60 membership |
| 2C | Evidence/verdict/rank/compose: P1-05→P1-06→P1-07→P1-08→P1-09 | ~3–4 tuần | đọc đúng phần cần, unknown trung thực, answer có evidence |
| 3 | P1-10; chỉ sau gate 2B/2C mới mở P1-11 và P1-12 | ~5–6 tuần | exhaustive có tập đầu vào đáng tin, ước tính chi phí; sẵn sàng 500k |
| 4 | P1-13 | ~2 tuần | RB dùng cùng pipeline |
| 5 | P2-* khi gate đạt | — | tối ưu |

Ước lượng tính theo người-tuần của một người, chưa tính song song; cần hiệu chỉnh khi đã gán owner. P1-04 có thể chạy song song với 2A. P1-03B/C/D có thể chạy song song sau khi P1-03A và contract P1-02 được chốt; P1-03E/F/G phải hội tụ các branch trước. API/job exhaustive foundation có thể tồn tại sớm nhưng UI/rollout exhaustive bị chặn cho tới khi Wave 2B đạt gold + ablation + scale gate.

Không có vòng dependency: H → P0 → P1-00/01/02/04 → P1-03 hybrid gate → P1-05..09 → P1-10..12 → P1-13 → P2.

---

## 14. Release gates

- Exact/structured completeness đạt gate trên gold và SQL reconciliation, ở cả kho thật và fixture 500k.
- P1-03A–G phải hoàn thành trước rollout exhaustive: structured, taxonomy, field-FTS, application, filtered vector và pinned được union/dedupe trong DB; hard constraints được re-verify sau union.
- Ablation bắt buộc so sánh structured-only, structured + taxonomy/FTS, structured + vector, full hybrid và full hybrid + application/pinned; báo cáo Recall@CandidateSet, unique hit/branch, overlap, false positive sau T2, latency và chi phí.
- Semantic recall không tụt baseline; mỗi branch phải chứng minh giá trị bổ sung hoặc được loại khỏi plan bằng số liệu, mọi miss có audit.
- Bảy lớp trạng thái `deterministic_complete`, `branches_complete`, `semantic_recall_measured`, `verification_complete`, `deep_read_complete`, `evidence_complete`, `answer_grounded` phải được ghi riêng; không suy diễn một lớp từ lớp khác.
- `branches_complete=false` hoặc branch bắt buộc degraded chặn tuyên bố “đã tìm toàn bộ”; `deep_read_complete=false` chặn tuyên bố “đã đọc toàn bộ”.
- Evidence coverage tăng theo section/constraint so với P0-03, không dùng giả thuyết 40–60% làm bằng chứng.
- `unknown` không biến thành `not matched`; tỉ lệ `unknown` trong ngưỡng; partial nói đúng coverage và số người chưa đọc sâu.
- Factual claims có evidence hợp lệ; PII/cross-scope leak bằng 0.
- P95/throughput/provider success/chi phí đạt budget đã chốt ở P0-00.
- T0/T1/count đạt SLO trên fixture 500k; EXPLAIN không có sequential scan trên bảng lớn ở đường nóng.
- Talent/RB index, vector dimension, feed/tombstone reconcile.
- Thuộc tính nhân khẩu học chỉ bật khi có duyệt pháp chế bằng văn bản.
- Mỗi flag có canary và rollback đã thử.
- Không rollout big-bang; schema additive/dual-read hoặc shadow index trước switch.

---

## 15. Quan hệ với các tài liệu kế hoạch khác

`product_core/docs` có nhiều kế hoạch chồng phạm vi: `RADAR_AI_MASTER_PLAN.md`, `RADAR_AI_AGENT_BACKLOG.md`, `RADAR_AI_UX_RELIABILITY_PLAN.md`, `RADAR_AGENT_GAP_ANALYSIS.md`, `QA_SPEED_RESILIENCE_PLAN.md`, `AI_TALENT_SEARCH.md`, `RADAR_ANSWER_ENGINE.md`.

**Đã làm (20/09/2026):** bảy tài liệu trên được thêm một dòng ở đầu, ghi rằng với phần search/retrieval/evidence/answer thì ticket `SEARCH-*` ở đây là nguồn thực thi và thắng khi có xung đột.

**Còn lại (`XS / Product-Ops`):** đọc từng tài liệu để đánh dấu cụ thể mục nào đã lỗi thời, mục nào còn đúng ngoài phạm vi search. Dòng ở đầu chỉ giải quyết xung đột về thứ tự ưu tiên, không phải một lần rà nội dung.

---

## 16. Definition of Done chương trình

Một lượt phải chứng minh được bằng trace máy đọc được:

1. Domain và constraint được hiểu thế nào, nguồn từ đâu.
2. Code đã tạo query/alias/AST nào và dùng index nào.
3. Mỗi nhánh tìm được bao nhiêu Person, union/filter còn bao nhiêu.
4. Trạng thái riêng của đủ bảy lớp completeness; phần nào deterministic, phần nào mới là semantic estimate và số liệu ablation nào chứng minh recall.
5. Dossier/evidence đã phủ source/section/constraint nào, thiếu gì.
6. Bao nhiêu candidate đã có verdict bằng code, bao nhiêu đã đọc sâu bằng AI, unknown, chưa đọc, pending, failed.
7. Vì sao mỗi Person thuộc nhóm nào, fact hay inference, evidence nào.
8. Chi phí token của lượt và có chạm trần hay không.
9. Câu trả lời cuối nói đúng coverage và trạng thái degraded.
10. Người dùng — không phải Radar — quyết định cuối cùng.

---

## 17. Implementation ledger — hiện trạng bàn giao 20/09/2026

> Phần này chỉ ghi nhận kết quả thực thi; **không thay thế hoặc hạ thấp đề bài,
> acceptance, scale check và release gate ở các mục 1–16**. `IMPLEMENTED` bên
> dưới có nghĩa là code đã tồn tại và có test local; chỉ được ghi
> `PRODUCTION ACCEPTED` khi toàn bộ acceptance tương ứng đã có bằng chứng.

### 17.1. Release đã thực hiện

- Commit: `aba4e2bff7318ea27e0ca6a68eaa644e2de6e35d` trên `main`, đã khớp
  `origin/main`.
- GitHub Actions: `Deploy MSB Radar Platform to Oracle` run `35490274865`, đúng
  `headSha` trên; job `validate` và `deploy-production` đều thành công.
- Bước `Verify exact release and live production` thành công; public health trả
  HTTP 200 với `{"ok": true, "service": "msb-radar-hub"}`.
- Search V2 đã được deploy dưới dạng code/schema additive. Cấu hình
  `SEARCH_PLAN_V2_MODE` mặc định vẫn là `off`; chưa được coi là đã canary hoặc
  đã thay đường tìm kiếm production hiện hành.

### 17.2. Thang mức độ hoàn thành

Một ticket đi qua năm mức. Mức chỉ được nâng khi có bằng chứng, và bằng chứng
phải ghi ngay trong bảng 17.3 — không nâng mức bằng cảm giác "đã làm xong rồi".

| Mức | Nghĩa | Bằng chứng cần có |
|---|---|---|
| **L0** | Chưa làm | — |
| **L1** | Có code + test local | tên test và số test đạt |
| **L2** | Đã deploy lên production | commit + run id của workflow |
| **L3** | Đã xác minh trên dữ liệu thật | truy vấn/log/EXPLAIN trên prod |
| **L4** | Đạt acceptance của ticket | đủ mọi dòng acceptance + cửa sổ quan sát |

Một ticket ở L1 nghĩa là **chưa ai được nói nó xong**. Wave chỉ được coi là đóng
khi mọi ticket của nó ở L4.

### 17.2b. Tiến độ tổng quan 20/09/2026

| Ticket | Mức | Việc còn lại gần nhất |
|---|:---:|---|
| H1 bỏ fallback không dùng được | **L2** | đặt `MSB_AI_DISABLED_PROVIDERS=gemini` trên prod; prod vẫn còn 46 lượt 402/48h |
| H2 chặn lệch chiều vector | **L3** | sửa `EmbeddingConfig.dimensions` 768 → 1024; hiện nhánh ngữ nghĩa tắt mọi lượt |
| H3 FTS giữ phép giao cho must | **L2** | chạy case 12/12 và EXPLAIN trên prod |
| H4 unknown ≠ not matched | **L2** | audit câu trả lời thật, chốt ngưỡng unknown |
| H5 fallback không mang model hub khác | **L1** | deploy rồi đối chiếu 404 về 0 trong 24h |
| P0-00 baseline/manifest/ADR | **L3** | manifest hai revision + ADR SLO/cost được duyệt |
| P0-01 provider capacity | **L1** | quota/billing thật, fallback drill, quan sát 24h |
| P0-02 dimension + ADR vector | **L3** | ADR halfvec/HNSW/filtered ANN + dung lượng ở 500k |
| P0-03 đo truncation | **L1** | đo trên corpus thật theo constraint/section |
| P0-04 coverage contract | **L1** | ~~lưu coverage vào `ai_answerrun`~~ đã làm (chưa deploy); còn: đưa vào OpenAPI, kiểm nhánh chat/attachment |
| P0-05 gold set | **L1** | nâng silver 23 case thành gold ≥60 câu, hai người gán nhãn |
| P0-06 scale fixture | **L1** | bị chặn bởi đĩa/RAM host — cần quyết (a) hay (b) ở P0-06 |
| P1-00 typed plan | **L1** | planner V2 thật sinh `where`, clarification flow |
| P1-01 SearchProjection | **L3** | **projection chỉ phủ 61/611 trên prod** — chạy backfill |
| P1-02 query compiler | **L1** | vocabulary quản trị được (02B), budget theo query type (02C) |
| P1-03 CandidateSet hybrid | **L1** | nhánh ANN (03D), union một câu SQL (03E) |
| P1-04 BaseDossier | **L3** | ExtractedFact/conflict ledger, mọi application thành record |
| P1-05 EvidenceView | **L1** | multi-round fetch, benchmark token |
| P1-06 judgement schema | **L1** | Answer Engine live dùng verdict V2 |
| P1-07 cache + cost guard | **L1** | nối cache vào T3, chốt lại token limit |
| P1-08 rank/reduce | **L1** | preference scoring, gate pháp chế cho nhân khẩu học |
| P1-09 grounded compose | **L1** | compose từ verdict/evidence ID V2 |
| P1-10 materializer/backfill | **L1** | outbox/dead-letter, stale ≤ 5 phút, benchmark |
| P1-11 durable T3 worker | **L1** | worker queue thật, test 10k candidate |
| P1-12 interactive/exhaustive | **L1** | background transition, export, load test |
| P1-13 RB | **L0** | discovery denominator; prod đang 26 chunk / 0 vector |
| P2-01..06 | **L0** | mở sau khi correctness gate đạt |

### 17.3. Kết quả theo ticket

| Ticket | Hiện trạng | Đã làm gì | Còn thiếu để đóng ticket |
|---|---|---|---|
| SEARCH-H1 | `IMPLEMENTED + LOCAL VERIFIED`; production observation còn mở | `ai/router.py` hỗ trợ `MSB_AI_DISABLED_PROVIDERS` toàn cục và theo task; có test provider bị loại khỏi routing | Cấu hình danh sách provider theo billing thật và quan sát production 24 giờ, chứng minh không còn HTTP 402 |
| SEARCH-H2 | `IMPLEMENTED + LOCAL VERIFIED`; production contract còn mở | `talent/vector_index.py` kiểm tra config/query/stored dimension, ném `VectorDimensionMismatch`, fail closed và ghi `semantic_degraded` | Xác minh trực tiếp dimension cột/index/vector trên PostgreSQL production và ADR lưu trữ cuối cùng |
| SEARCH-H3 | `IMPLEMENTED + LOCAL VERIFIED` | `talent/answer/retrieve.py` có nhánh `FTS_BOOLEAN_MUST` dùng phép giao cho must; có regression test | Chạy case 12/12 trên dữ liệu thật và `EXPLAIN (ANALYZE, BUFFERS)` chứng minh dùng GIN ở quy mô mục tiêu |
| SEARCH-H4 | `IMPLEMENTED + LOCAL VERIFIED`; production observation còn mở | Coverage có `candidate_total/judged/unknown/not_read`; compose fallback không gọi phần chưa đọc là không phù hợp; UI hiển thị phạm vi đã đọc | Theo dõi câu trả lời thật, audit silent partial/unsupported claim và chốt tỷ lệ unknown |
| SEARCH-P0-00 | `PARTIAL` | `ai/baseline.py` bổ sung số projection/dossier, provider/token 24 giờ và CandidateSet coverage | Manifest hai revision, corpus fingerprint đầy đủ, SLO/cost ADR được duyệt và tách benchmark/user traffic |
| SEARCH-P0-05 | `PARTIAL / EXTERNAL GATE` | Bộ **silver** `evaluation/datasets/search_silver_v1.jsonl` 23 case: 14 case deterministic có truth suy được bằng SQL nên chấm được ngay, 9 case semantic mang `status=needs_review`; lệnh `search_ablation` chấm và **bỏ qua** case chưa gán nhãn, in rõ số bị bỏ qua | Nâng lên gold ≥60 câu: nhãn Person × constraint, evidence span, hard negative, hai người gán nhãn/review, đo agreement, chốt ngưỡng `unknown` |
| SEARCH-P0-06 | `PARTIAL` | Có command `search_scale_fixture` với xác nhận rõ ràng, dữ liệu seed và benchmark/EXPLAIN trên PostgreSQL | Chạy thật fixture 500k trên staging tương đương production, concurrency/load report và lưu query plans |
| SEARCH-P0-01 | `PARTIAL / EXTERNAL GATE` | Có provider kill switch và thống kê provider/token | Capacity/billing/quota test thật, fallback drill, circuit behavior và quan sát ≥24 giờ |
| SEARCH-P0-02 | `PARTIAL` | Dimension contract fail-closed; CandidateSet trace ghi model/configured/stored dimension; migration thêm index PostgreSQL | ADR HNSW/halfvec/filtered ANN, dung lượng 5–10 triệu vector và benchmark production-like |
| SEARCH-P0-03 | `PARTIAL` | `BaseDossier` giữ section/full text/offset; `evidence_view` báo available/selected sections và chars, không còn cắt mù 700 ký tự | Đo corpus thật theo constraint/section/source và so sánh baseline cũ; xác nhận late-CV recall trên gold |
| SEARCH-P0-04 | `PARTIAL` (L1) | Còn thiếu quan trọng: `ai_answerrun` không lưu `answer_coverage`, nên không thể audit hồi tố "câu trả lời nào từng nói sai phạm vi". Như trên, cộng bảy lớp completeness (`deterministic/branches/semantic_recall_measured/verification/deep_read/evidence/answer_grounded`) trong `explain.completeness` và trong payload API | Đưa schema vào OpenAPI/contract chính thức, kiểm tra các nhánh chat/attachment ngoài people pipeline và production acceptance |
| SEARCH-P1-00 | `PARTIAL` | Có `RadarTurnPlan`, `Constraint`, domain/query type, must/prefer/exclude/where, range/temporal/geo, phân lớp `HARD_DETERMINISTIC/HARD_SEMANTIC/PREFERENCE`, Boolean AST lồng `AND/OR/NOT` và bridge từ legacy plan; legacy free-text must/prefer được phân thành semantic/preference | Planner V2 đa miền thật, schema validation từ model output, clarification flow và provenance từ câu người dùng vào từng node |
| SEARCH-P1-01 | `PARTIAL` | Có `SearchProjection`, canonical fields, searchable text, JSON arrays, indexes cơ bản và PostgreSQL GIN migration | Vocabulary/ID canonical quản trị được, field tsvector materialized/setweight, scope/RBAC SQL predicate và production query plans |
| SEARCH-P1-02 | `PARTIAL` | Như trên, cộng field-aware FTS: điều kiện văn bản gộp dùng `search_tsv @@ to_tsquery` (annotation nên ghép được với AND/OR/NOT) thay cho `LIKE '%…%'`; `tsquery()` giữ phép giao cho must và loại bỏ mọi toán tử người dùng chèn vào; mảng JSONB fail-closed trên vendor không phải PostgreSQL | Vocabulary quản trị được (P1-02B), prefer scoring, adaptive expansion, budget theo query type, EXPLAIN trên PostgreSQL |
| SEARCH-P1-03 | `PARTIAL` | Như trên, cộng `BranchHit` chung cho mọi nhánh, nhánh lexical chạy **trong** phạm vi filter cứng, `union_branches` dedupe theo Person giữ rank/score/provenance từng nhánh, trần snapshot `blocked` thay cho cắt im lặng, `INSERT … SELECT` cho đường structured trên PostgreSQL, và `verify_members` chạy lại điều kiện cứng trên từng batch | Nhánh ANN (03D), taxonomy/application thành nhánh riêng (03B), union bằng một câu SQL (03E), RBAC là predicate SQL, snapshot/reconciliation semantics |
| SEARCH-P1-04 | `PARTIAL` | `BaseDossier` chứa profile, application metadata, toàn bộ Edge payload, CV sections, source offsets, lineage, fingerprint; signals rebuild sau commit | ExtractedFact/current-rejected rules, conflict ledger, mọi application dưới dạng từng record, version switch và reconciliation |
| SEARCH-P1-05 | `PARTIAL` | EvidenceView chọn section theo constraint, ưu tiên đa dạng và dùng explicit character budget tới 24k; test dữ kiện cuối CV >700 ký tự | Multi-round fetch theo yêu cầu model, semantic selection trong Person, per-constraint completeness và token packing benchmark |
| SEARCH-P1-06 | `PARTIAL` | Như trên, cộng T2 xác minh thật: `supported` chỉ khi Person khớp predicate cứng và không còn constraint semantic chờ T3; không khớp là `contradicted`; compiler `unresolved` làm mọi member `unknown`; số đếm khi đóng run lấy từ DB | Constraint judgement schema được dùng bởi Answer Engine live, deterministic verdict cho mọi field đáng tin cậy, conflict/inference validation |
| SEARCH-P1-07 | `PARTIAL` | Như trên; preflight nay dùng đúng ngân sách EvidenceView (24.000 ký tự) nên không còn báo rẻ hơn thực tế 2 lần | Nối cache vào T3 live, cache hit metrics, invalidation/rebuild, quota theo user/task/provider, chốt lại `SEARCH_V2_T3_TOKEN_LIMIT` trong ADR cost |
| SEARCH-P1-08 | `PARTIAL` | Có stable grouping/ranking theo group, confidence và person ID; demographic fields không bị hard-code thành score | Preference scoring từ constraint người dùng, explain từng tiêu chí, aggregate/reduce hoàn chỉnh và gold ranking evaluation |
| SEARCH-P1-09 | `PARTIAL` | Compose hiện có coverage truth và source presentation; Answer UI có coverage panel | Compose trực tiếp từ verdict/evidence ID V2, source-offset citations và verifier chặn mọi factual claim không có evidence |
| SEARCH-P1-10 | `PARTIAL` | Signals materialize dossier/projection sau thay đổi Person/Profile/Document/SourceRecord; có resumable rebuild command | Outbox/dead-letter, Fact/Application events đầy đủ, incremental embedding, periodic reconciliation, stale ≤5 phút và benchmark 500k |
| SEARCH-P1-11 | `PARTIAL` | CandidateSet có state/cursor/heartbeat/cancel flag; processor T2 resume theo batch; command resume; cost preflight; API owner-scoped estimate/create/status/cancel/resume chỉ xử lý một batch mỗi request | Worker queue T3 thật, bounded parallel LLM, retry/jitter/circuit breaker, idempotency sau restart và test 10k unknown candidates |
| SEARCH-P1-12 | `PARTIAL` | Model có interactive/exhaustive mode; API estimate/create/status/cancel/resume có confirmation khi vượt token limit; UI Answer không che giấu partial coverage | Background transition theo deadline, estimate-confirm/progress/export UI, reconnect và load test 30 users |
| SEARCH-P1-13 | `NOT STARTED / EXTERNAL GATE` | Chưa thay đổi pipeline RB trong release này | Discovery denominator RB, DNC/RBAC, rebuild dossiers, embeddings, index/reconciliation, benchmark và canary |
| SEARCH-P2-01..06 | `NOT STARTED` | Chưa kéo vào release này | Thực hiện sau khi correctness/release gates P0/P1 đạt như mục 12 |

### 17.4. Các thành phần code đã thêm hoặc thay đổi

- `product_core/server/talent/search_v2.py`: contract plan/constraint, compiler,
  projection/dossier builder, EvidenceView, CandidateSet, judgement cache,
  grouping/ranking, cost guard và resumable T2 processor.
- `product_core/server/talent/models.py` và migrations `0013`–`0015`:
  `SearchProjection`, `CandidateSetRun`, `CandidateSetMember`, `BaseDossier`,
  `ConstraintJudgementCache` và PostgreSQL GIN indexes.
- `product_core/server/talent/signals.py`: materialize projection/dossier sau
  thay đổi dữ liệu liên quan.
- `product_core/server/talent/answer/engine.py`: feature mode
  `off|shadow|on`, durable shadow CandidateSet và normalized answer coverage.
- `product_core/server/talent/answer/retrieve.py`: Boolean must FTS.
- `product_core/server/talent/vector_index.py`: dimension contract fail-closed.
- `product_core/server/talent/answer/compose.py`: coverage-safe payload/fallback.
- `product_core/server/ai/router.py`: provider kill switch.
- `product_core/server/ai/baseline.py`: Search V2/provider/coverage telemetry.
- Management commands: `rebuild_search_v2`, `process_candidate_set`,
  `search_scale_fixture`.
- Talent API: `POST /candidate-sets/estimate/`, `POST /candidate-sets/` và
  `GET|PATCH /candidate-sets/<run_id>/`; run bị giới hạn theo owner, cost guard
  chạy trước khi tạo snapshot, `resume` chỉ xử lý một batch để không khóa request.
- `product_core/web/src/AnswerView.tsx`: coverage UI; không biểu diễn phần chưa
  đọc là kết quả âm.

### 17.5. Bằng chứng kiểm tra của release

- Backend `ai + talent`: **913/913 tests passed**.
- Backend tests mục tiêu Search V2/search quality/baseline: **38/38 passed**.
- Frontend: **141/141 tests passed**.
- TypeScript typecheck và production build: passed.
- `makemigrations --check --dry-run`, Django system check và
  `git diff --check`: passed.
- Test frontend còn in cảnh báo jsdom `window.scrollTo/navigation` đã tồn tại;
  command vẫn exit 0 và toàn bộ test đạt. Đây không phải bằng chứng browser E2E.

### 17.6. Việc tiếp theo theo đúng dependency

1. Bật `SEARCH_PLAN_V2_MODE=shadow` trên phạm vi canary và thu diff legacy/V2;
   chưa bật `on` rộng.
2. Hoàn thành P0-05 gold set và P0-06 fixture 500k; dùng kết quả để chốt P0-00
   SLO/cost và P0-02 vector ADR.
3. Hoàn thiện union structured + field-FTS + ANN và Boolean AST trước khi coi
   CandidateSet là recall boundary mới.
4. Nối EvidenceView/cache vào bounded T3 worker, sau đó mới làm exhaustive
   API/UI và benchmark 10k candidates.
5. Chỉ mở RB sau discovery/reconciliation/DNC/RBAC; không suy diễn từ 21 chunks.
6. Thực hiện legal gate cho thuộc tính nhân khẩu học; Radar chỉ phân tích và
   khuyến nghị có evidence, người dùng giữ quyết định cuối cùng.
7. Sau mỗi bước: canary, rollback drill, health check, production telemetry và
   observation window theo release gates mục 14.

### 17.7. Changelog increment sau release `aba4e2b`

Chi tiết từng lần sửa nằm trong git log; bảng này chỉ để đọc nhanh. Trạng thái
ticket xem 17.3, trạng thái slice xem hai bảng ở mục 9.

| Commit | Ticket | Nội dung chính | Bằng chứng local |
|---|---|---|---|
| `4da3e60` | P0-04, P1-11, P1-12 | Coverage ở mọi exit path của people pipeline; API estimate/create/status/cancel/resume cho CandidateSet; T2 qua API chỉ một batch 500/request; sửa `complete=true` khi còn candidate chưa qua cursor; nhãn UI tách "tính bằng SQL" / "kiểm bằng code" / "đọc sâu" | `ai+talent` 918; frontend 142 |
| `b9266d0` | P1-00, P1-02 | Boolean AST lồng trong `where` + validator depth 8 / 50 leaves; `NOT` đúng một child; unresolved fail-closed và không bị `NOT` đảo thành cho qua toàn kho; `classification` strict vào fingerprint; compiler chỉ đẩy hard-deterministic xuống SQL; branch chưa có báo `not_implemented` | `ai+talent` 923 |
| `8d5d0a1` | P0-05, P1-02C/D, P1-03A/C/E/F/G, P1-06, P1-07 | Mục 17.9 | `ai+talent` 935; `tests_search_v2` 30 |
| chưa commit | H5, P0-04, P0-00/P0-02 (bằng chứng prod) | Router lọc chuỗi provider theo model đã ghim + nhớ cặp bị từ chối 404/402; `AnswerRun.coverage` lưu coverage để audit hồi tố (migration `ai/0027`, chỉ các khoá đã biết, không nội dung nghiệp vụ); baseline mục 2 đo lại trên prod; bảng tiến độ 17.2b | `ai.tests.RouterTest` 23; `ai.tests_answer_runs + core` 236; toàn bộ backend 1921 |

### 17.8. Quyết định chiến thuật retrieval đã đưa vào đề bài

Mục 3, kiến trúc mục 4 và acceptance P1-00/02/03/06/08 được viết theo các quyết
định sau, và chúng không được lùi lại bằng một increment implementation:

- Boolean/SQL là correctness boundary cho `HARD_DETERMINISTIC`, không phải search
  engine duy nhất; `HARD_SEMANTIC` không bị lọc rơi vì thiếu exact keyword;
  `PREFERENCE` không đổi membership.
- CandidateSet là union theo Person của exact/structured, taxonomy, field-FTS,
  application metadata, vector và pinned; mọi member giữ provenance/score.
- Sau union phải re-verify hard deterministic trên toàn tập; hit FTS/vector
  không tự pass must.
- T1 dùng trọng số thích nghi theo query type; interactive T3 chia budget cho
  top relevance + decision boundary + diversity + hard-semantic/unknown.
- Ranking chỉ quyết định thứ tự đọc và trình bày, không phải quyền tồn tại.

### 17.9. Increment `8d5d0a1` — đã commit, chưa push và chưa deploy

**Phạm vi:** P1-03C field-aware FTS, P1-03A/E branch contract và union,
P1-03F/G re-verification và completeness, P1-06 verdict, P1-07 cost guard,
P0-05 silver set. Không mở phạm vi mới, không sửa đề bài.

Năm lỗi được sửa, cả năm thuộc loại "hệ thống nói quá những gì đã làm":

- **T2 báo đã xác minh mà không đối chiếu dữ liệu.** `process_candidate_set` gán
  `supported` cho mọi member chỉ vì compiler không có `unresolved`, nên `judged`
  bằng cả CandidateSet và `complete=true` kể cả khi plan còn ràng buộc semantic
  chưa ai đọc. Nay `verify_members` chạy lại predicate cứng trên từng batch.
- **`complete` bỏ qua nhánh chưa tồn tại.** Nay `complete` đòi cả
  `branches_complete`, và trạng thái nhánh được đọc từ run đã ghi chứ không suy
  lại từ một compile mới.
- **Snapshot có thể đăng ký cả kho.** Trần `SEARCH_V2_SNAPSHOT_MAX_MEMBERS`
  (mặc định 50.000); vượt trần là `blocked` với lý do rõ, không cắt im lặng.
- **`on` mode ghim sai người.** Chỉ dùng CandidateSet làm nguồn recall khi nó đã
  áp filter cứng và không `blocked`; trace ghi `used_for_recall`.
- **Preflight chi phí thấp hơn thực tế 2 lần.** Dùng chung
  `EVIDENCE_CHAR_BUDGET`. Hệ quả: `SEARCH_V2_T3_TOKEN_LIMIT=500000` hiện chỉ đủ
  khoảng 78 candidate trước khi cần xác nhận — trần này phải chốt lại trong ADR
  cost của P0-00.

Thêm mới:

- **Field-aware FTS (P1-03C).** Migration `0016` thêm cột generated `search_tsv`
  gộp title/company/location/education/searchable_text với trọng số A/B/C/D, GIN
  trên cột đó, và trigram cho bốn cột văn bản ngắn. Compiler dùng
  `search_tsv @@ to_tsquery('simple', …)` dạng annotation nên ghép được với
  AND/OR/NOT. `tsquery()` chỉ giữ chữ và số, nên không chèn được toán tử qua dữ
  liệu; `mode="and"` cho must, `mode="or"` cho recall.
- **Branch contract và union (P1-03A/E).** `BranchHit` chung cho mọi nhánh;
  `lexical_branch` chạy trong phạm vi filter cứng và trả lý do khi không chạy
  được (`vendor_unsupported`, `no_indexable_token`, `top_n_capped`);
  `union_branches` dedupe theo Person, giữ rank/score/provenance từng nhánh.
- **Silver set và ablation (P0-05 tạm).**
  `evaluation/datasets/search_silver_v1.jsonl` 23 case; lệnh
  `python manage.py search_ablation` chấm recall theo ba cấu hình
  (`structured`, `field_fts`, `structured+field_fts`), đếm unique hit từng nhánh,
  và bỏ qua case semantic chưa gán nhãn kèm cảnh báo "recall semantic chưa được đo".

**Bằng chứng local:** `tests_search_v2` **30/30**; regression `ai + talent`
**935/935**; `makemigrations --check`, Django system check và `git diff --check`
passed.

**Chưa xác minh được ở local (không có PostgreSQL trên máy):** cột generated
`search_tsv`, index trigram, nhánh lexical, `ts_rank_cd` và đường
`INSERT … SELECT`. Tất cả là gate của staging: cần chạy migration `0016`,
`search_ablation` và `EXPLAIN (ANALYZE, BUFFERS)` ở đó trước khi coi P1-03C là
xong. Trên SQLite các đường này báo `vendor_unsupported` và điều kiện mảng JSONB
fail-closed thành `unresolved`.

### 17.10. Xác minh trên production 20/09/2026

Đợt đầu tiên chạy trực tiếp trên VPS Core thay vì chỉ trên máy lập trình. Tất cả
là **read-only**: `docker ps`, `docker logs`, và `psql` chỉ với `SELECT`/`EXPLAIN`.

Đã kiểm và kết quả:

| Kiểm | Kết quả |
|---|---|
| Container và phiên bản | `msbradar-hub`/`msbradar-db` healthy; PostgreSQL 16.15; pgvector 0.8.6 |
| Chiều vector từng lớp | cột và HNSW 1024; config 768; model `baai/bge-m3` → lệch, xem mục 2 |
| Log nhánh ngữ nghĩa | `semantic_degraded` 12 lần/48 giờ, tức tắt ở mọi lượt tìm |
| Phủ projection/dossier | 61/611 ứng viên (10%) — signals chỉ dựng khi có thay đổi, backfill chưa chạy trên prod |
| Chỉ mục `talent_searchprojection` | 24 chỉ mục; GIN full-text của 0015 chỉ dùng được nếu query viết đúng biểu thức |
| EXPLAIN LIKE vs tsvector | `LIKE '%…%'` → Seq Scan; `@@ to_tsquery` → Bitmap Index Scan |
| Provider 48 giờ | 254 lượt 404 sai cặp provider–model; 46 lượt 402; 66 rate limit; 77 timeout |
| `MSB_AI_DISABLED_PROVIDERS` | chưa đặt → acceptance H1 chưa đạt |
| Lưu vết coverage | `ai_answerrun` chỉ có `state/deadline/user`; **không lưu `answer_coverage`** nên không audit hồi tố được lượt nào từng trả partial |
| RB evidence | 26 chunk, 0 vector, cột chưa chốt chiều |
| Hạ tầng | 41/49 GB đĩa, 5,9 GB RAM, dùng chung với TalentFlow |

Ba việc **ghi** cần thiết nhưng bị chặn trong phiên này (auto-mode chặn ghi trên
máy chủ từ xa), xếp theo mức tác động:

1. `EmbeddingConfig.dimensions = 1024` — trả lại nhánh ngữ nghĩa cho toàn bộ
   tìm kiếm. Làm được qua `/settings` mà không cần ai truy cập máy chủ.
2. `docker exec msbradar-hub python manage.py rebuild_search_v2` — đưa
   projection/dossier từ 61 lên 611. Lệnh idempotent, không sửa dữ liệu nghiệp vụ.
3. Đặt `MSB_AI_DISABLED_PROVIDERS=gemini` (hoặc chỉ cho task còn 402) rồi deploy
   bản mới để lấy H5 + migration 0016.

Fixture 500k **không chạy trên host này** (mục P0-06). Nếu chọn phương án (a),
lệnh `search_scale_fixture` phải trỏ vào một database riêng: nó tạo Person tổng
hợp, chạy trên database production sẽ làm bẩn kho ứng viên thật.

### 17.11. Việc tiếp theo theo đúng dependency

1. Ba việc ghi ở 17.10, theo đúng thứ tự đó.
2. Deploy bản mới (`gh workflow run deploy-oracle.yml`), rồi chạy migration
   `0016`, `search_ablation` và `EXPLAIN (ANALYZE, BUFFERS)` trên prod.
3. Chốt phương án P0-06 (database riêng cùng host, hay host staging riêng).
4. P1-02B vocabulary quản trị được; alias vẫn là hằng số trong `search_v2.py`.
5. P1-03D nhánh ANN sau khi P0-02 chốt ADR vector — nhánh cuối để
   `branches_complete` có thể đúng.
6. Nâng silver set lên gold: người gán nhãn và người review khác nhau.
7. Legal gate cho thuộc tính nhân khẩu học trước khi bật `DEMOGRAPHIC_CONTEXT`.
8. `SEARCH_PLAN_V2_MODE=shadow` trên canary, thu diff legacy/V2, rollback drill.
