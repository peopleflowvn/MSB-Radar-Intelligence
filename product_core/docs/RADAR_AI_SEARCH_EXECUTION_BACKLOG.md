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
**Đã đóng trên prod 20/09:** cột và HNSW là `vector(1024)`, model `baai/bge-m3`
sinh 1024, nhưng `EmbeddingConfig.dimensions` để 768 nên fail-closed **tắt nhánh
ngữ nghĩa ở mọi lượt** (log 13:02 và 13:04). Đã pin `dimensions = 1024` lúc 07:43
UTC; hub đọc `configured=1024 stored=1024` và một lượt truy hồi thật trả về 5 hồ
sơ. Còn lại: quan sát 24 giờ để chắc log không còn `semantic_degraded`.  
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
| P1-02B — Canonical expansion | Vocabulary versioned cho title/skill/company/location/application; phrase, Anh–Việt, dấu/không dấu, abbreviation; IDF/stopword/query budget | không giant-OR; mỗi expansion có source/version; gold exact/alias đạt gate | `PARTIAL + PROD VERIFIED` — `SearchVocabulary`, migration 0017–0018 và vocabulary version đã chạy; corpus mới có 6 canonical rows, chưa đủ gold/IDF/query-budget gate |
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
| P1-03C — Field-aware FTS | weighted tsvector, phrase/Boolean, per-field hits | gold FTS recall; GIN path; broad-term guard | P1-02B | `IMPLEMENTED + PROD VERIFIED` — generated `search_tsv`, GIN/trigram và branch FTS chạy thật; gold semantic/broad-term gate còn mở |
| P1-03D — Filtered vector | exact distance trên tập nhỏ, ANN thích nghi trên tập lớn | dimension fail-closed; recall/latency theo hard-filter population | P0-02, P1-02C | `IMPLEMENTED + PROD VERIFIED, RECALL GATE OPEN` — pgvector/HNSW 1024 chiều và `prefilter_exact` chạy thật; top-N 500 đang capped trên 611 applicant |
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

### 17.1b. Quy tắc ghi nhật ký (bắt buộc sau mỗi phiên làm việc)

Mỗi phiên làm việc — dù chỉ sửa một dòng — phải để lại bốn thứ, nếu không thì
lần sau không ai biết cái gì đã xong:

1. **Mức độ** của từng ticket bị ảnh hưởng trong bảng 17.2b, kèm việc còn lại
   gần nhất. Không nâng mức khi chưa có bằng chứng tương ứng ở 17.2.
2. **Một dòng changelog** ở 17.7: commit, ticket, nội dung chính, bằng chứng test.
3. **Bằng chứng**: số test đạt, hoặc truy vấn/log trên production, hoặc run id
   của workflow. Không có bằng chứng thì ghi rõ "chưa xác minh".
4. **Việc còn lại** ở 17.11, theo đúng thứ tự dependency.

Ghi cả thứ chưa làm được và lý do (thiếu quyền, thiếu hạ tầng, chờ phê duyệt).
Một tài liệu chỉ ghi thành công sẽ khiến lần sau lặp lại đúng chỗ đã vướng.

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
| H1 bỏ fallback không dùng được | **L2** | H5 đã chặn phần lớn lãng phí; theo dõi 24h xem 402 còn không rồi mới quyết có cần `MSB_AI_DISABLED_PROVIDERS` hay không |
| H2 chặn lệch chiều vector | **L3** | đã pin `dimensions = 1024` trên prod 20/09 07:43 UTC; contract trong container đọc `configured=1024 stored=1024`; truy hồi vector thật trả 5 hồ sơ. Còn **duy nhất**: cửa sổ quan sát 24 giờ chưa chạy hết nên chưa được ghi L4 |
| H3 FTS giữ phép giao cho must | **L3** | EXPLAIN trên prod: GIN `search_tsv` cho Bitmap Index Scan, khớp 44 hồ sơ với `ke & toan`. Còn: case hồi quy 12/12 trên dữ liệu thật |
| H4 unknown ≠ not matched | **L2** | audit câu trả lời thật, chốt ngưỡng unknown |
| H5 fallback không mang model hub khác | **L2** | đã deploy (run 35497650837); đối chiếu 404 về 0 trong 24 giờ |
| P0-00 baseline/manifest/ADR | **L3** | manifest hai revision + ADR SLO/cost được duyệt |
| P0-01 provider capacity | **L3** | chuỗi model dự phòng theo tác vụ đã deploy (17.10i); 0 lỗi 404 sau H5; hạn mức embedding và chat đã đo trên prod; token bucket theo provider đã deploy; nguyên nhân thật là **một khoá GreenNode** (17.10f). Còn: đặt `MSB_AI_RATE_PER_MINUTE_GREENNODE` và hiệu chỉnh, thêm khoá, fallback drill, quan sát 24h |
| P0-02 dimension + ADR vector | **L3** | chiều đã pin 1024 và xác minh. ADR còn thiếu, và nay có thêm một câu bắt buộc phải trả lời: ở hạn mức embedding đo được, embed lại 500k qua GreenNode là không khả thi — chốt tự host hay đường khác |
| P0-03 đo truncation | **L1** | đo trên corpus thật theo constraint/section |
| P0-04 coverage contract | **L2** | `AnswerRun.coverage` + schema OpenAPI đã deploy; lỗi treo claim do chính đợt này gây ra đã sửa và deploy (17.10d). Còn: xác nhận có dòng coverage thật sau vài lượt tìm, kiểm nhánh chat/attachment |
| P0-05 gold set | **L3** | silver 28 case chạy trên prod hai lần, tìm ra 2 lỗi thật (17.10c). Còn: nâng lên gold ≥60 câu, hai người gán nhãn, và gán nhãn 10 case semantic đang bị bỏ qua |
| P0-06 scale fixture | **L1** | bị chặn bởi đĩa/RAM host — cần quyết (a) hay (b) ở P0-06 |
| P1-00 typed plan | **L1** | planner V2 thật sinh `where`, clarification flow |
| P1-01 SearchProjection | **L3** | backfill xong 20/09: **611/611** projection + dossier, mọi dòng có `search_tsv`. Còn: scope/RBAC thành predicate SQL, vocabulary ID hoá |
| P1-02 query compiler | **L3** | 02B đã deploy, gieo 6 dòng từ điển trên prod, `vocabulary_version` xuất hiện trong mọi lượt đo; 02C chọn nhánh theo query type đã deploy; alias vào cả tsquery đưa recall FTS từ 0,989 lên 1,000. Còn: adaptive expansion có telemetry |
| P1-03 CandidateSet hybrid | **L3** | 03C và 03D đã deploy và **đo trên prod**: field_fts **1,000** / vector **0,960** / hybrid **1,000** (xem 17.10c–d). Còn 03E union một câu SQL, 03B taxonomy/application thành nhánh riêng |
| P1-04 BaseDossier | **L3** | ExtractedFact/conflict ledger, mọi application thành record |
| P1-05 EvidenceView | **L1** | multi-round fetch, benchmark token |
| P1-06 judgement schema | **L1** | Answer Engine live dùng verdict V2 |
| P1-07 cache + cost guard | **L2** | bản đầu là cache chỉ ghi (0 lần dùng lại, xem 17.10j) — đã đổi khoá sang người + nội dung + tiêu chí, **chờ đo lại trên prod**; cache kết luận đã đọc nối vào **đường live** (`judge_cache`, khoá là `dossier_key` nên CV/câu hỏi đổi là khoá đổi; còn `UNKNOWN` thì không lưu; phạm vi theo người hỏi). Còn: mở phạm vi dùng chung sau khi rà RBAC, đo cache hit trên prod, chốt lại token limit |
| P1-08 rank/reduce | **L1** | `preference_score` bằng code đã có (prefer chỉ đổi thứ tự, xếp sau nhóm, có giải thích từng thành phần). Còn: nối vào đường live, gate pháp chế cho nhân khẩu học |
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
| SEARCH-P0-05 | `PARTIAL / EXTERNAL GATE` | Bộ **silver** `product_core/server/talent/eval_data/search_silver_v1.jsonl` 23 case: 14 case deterministic có truth suy được bằng SQL nên chấm được ngay, 9 case semantic mang `status=needs_review`; lệnh `search_ablation` chấm và **bỏ qua** case chưa gán nhãn, in rõ số bị bỏ qua | Nâng lên gold ≥60 câu: nhãn Person × constraint, evidence span, hard negative, hai người gán nhãn/review, đo agreement, chốt ngưỡng `unknown` |
| SEARCH-P0-06 | `PARTIAL` | Có command `search_scale_fixture` với xác nhận rõ ràng, dữ liệu seed và benchmark/EXPLAIN trên PostgreSQL | Chạy thật fixture 500k trên staging tương đương production, concurrency/load report và lưu query plans |
| SEARCH-P0-01 | `PARTIAL / EXTERNAL GATE` | Có provider kill switch và thống kê provider/token | Capacity/billing/quota test thật, fallback drill, circuit behavior và quan sát ≥24 giờ |
| SEARCH-P0-02 | `PARTIAL` | Dimension contract fail-closed; CandidateSet trace ghi model/configured/stored dimension; migration thêm index PostgreSQL | ADR HNSW/halfvec/filtered ANN, dung lượng 5–10 triệu vector và benchmark production-like |
| SEARCH-P0-03 | `PARTIAL` | `BaseDossier` giữ section/full text/offset; `evidence_view` báo available/selected sections và chars, không còn cắt mù 700 ký tự | Đo corpus thật theo constraint/section/source và so sánh baseline cũ; xác nhận late-CV recall trên gold |
| SEARCH-P0-04 | `PARTIAL` | `ai_answerrun.coverage` đã deploy và một run mới đã lưu coverage; bảy lớp completeness có trong `explain.completeness`/API. 243 run lịch sử chưa có coverage nên không thể audit hồi tố đầy đủ | Đưa schema vào OpenAPI/contract chính thức, bảo đảm mọi exit path mới lưu coverage, kiểm tra chat/attachment và production acceptance |
| SEARCH-P1-00 | `PARTIAL` | Có `RadarTurnPlan`, `Constraint`, domain/query type, must/prefer/exclude/where, range/temporal/geo, phân lớp `HARD_DETERMINISTIC/HARD_SEMANTIC/PREFERENCE`, Boolean AST lồng `AND/OR/NOT` và bridge từ legacy plan; legacy free-text must/prefer được phân thành semantic/preference | Planner V2 đa miền thật, schema validation từ model output, clarification flow và provenance từ câu người dùng vào từng node |
| SEARCH-P1-01 | `PARTIAL` | Có `SearchProjection`, canonical fields, searchable text, JSON arrays, indexes cơ bản và PostgreSQL GIN migration | Vocabulary/ID canonical quản trị được, field tsvector materialized/setweight, scope/RBAC SQL predicate và production query plans |
| SEARCH-P1-02 | `PARTIAL + PROD VERIFIED` | Như trên, cộng vocabulary quản trị được và field-aware FTS: `search_tsv @@ to_tsquery`, alias version trong explain, Boolean must và PostgreSQL GIN chạy thật | Mở rộng vocabulary, prefer scoring, adaptive expansion, budget theo query type và EXPLAIN/recall gate |
| SEARCH-P1-03 | `PARTIAL + PROD SHADOW` | `BranchHit`, structured/FTS/vector, union/dedupe/provenance, snapshot guard và `verify_members`; production có 6 hybrid CandidateSet 500–509 người, không degraded | Taxonomy/application thành nhánh riêng, SQL union (khi mở lại scale gate), RBAC predicate, nối T2/T3/grounded compose; vector top-N 500 còn capped |
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
| `02415df` | P1-02B, P1-03D | Bảng `SearchVocabulary` + lệnh `search_vocabulary`; nhánh dense ANN pre-filter bằng subquery, `hnsw.iterative_scan` khi tập lớn; ablation phân biệt "không áp dụng" với recall 0 | backend 1933; đã deploy |
| `db97c42` | P1-02C, P1-03C/D, P0-04 | Alias vào cả tsquery (sửa bỏ sót 14/319 mà ablation tìm ra); `VectorBranchUnavailable` có mã lý do; chọn nhánh theo query type; schema OpenAPI cho CandidateSet | backend 1939; deploy `35499630280`; ablation lần 3 cho FTS 1,000 |
| `762c94c` | P0-01, P1-03D | Một lần thử lại sau 1,2 giây khi embedding bị 429; tách `embedding_rate_limited` khỏi `embedding_failed` | backend 1939; deploy `35500253243` |
| `fcee1e4` | P0-05 | Ablation tự giãn nhịp (`--pace-seconds`); sửa các câu "chưa deploy" đã cũ trong ledger | backend 1939; deploy `35510159525` |
| `a871aa4` | P0-04 | `_coverage_of` đọc được dataclass; đọc coverage tách khỏi `try` của `finish` — sửa lỗi treo claim ở 17.10d | backend 1940; deploy `35510876422` |
| `2e5b106` | P0-05 | Ablation chỉ gọi embedding một lần mỗi case (trước đó hai lần nên tự chạm hạn mức) | backend 1940; deploy `35511413523` |
| `53cf9b0` | H5, P0-01 | Điều kiện chặn dùng model thật sự sẽ gửi (lỗi trong chính H5); token bucket theo provider tự xếp hàng thay vì nhận 429 | backend 1943; deploy `35514345840` |
| `8a739b7` | P1-07 | `judge_cache`: nhớ kết luận đã đọc giữa các lượt, khoá gói cả nội dung dossier; `stats.judge_cache_hits` | backend 1947; deploy `35514898531` |
| `65723be` | H5, P0-04, P0-00/P0-02 (bằng chứng prod) | Router lọc chuỗi provider theo model đã ghim + nhớ cặp bị từ chối 404/402; `AnswerRun.coverage` lưu coverage để audit hồi tố (migration `ai/0027`, chỉ các khoá đã biết, không nội dung nghiệp vụ); baseline mục 2 đo lại trên prod; bảng tiến độ 17.2b | `ai.tests.RouterTest` 23; `ai.tests_answer_runs + core` 236 |
| `a0d8e7d` | H5, P0-05, P1-03C | Migration `0016` chuyển sang `atomic = False` và bọc riêng `CREATE EXTENSION` — trước đó thiếu quyền `pg_trgm` sẽ abort transaction, migrate chết, container crash-loop khi khởi động; dataset silver chuyển vào `talent/eval_data` vì image chỉ copy `product_core/server` nên `search_ablation` không thể chạy trên prod | toàn bộ backend **1925/1925**; đã deploy trong run `35497650837` |

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

### 17.9. Increment `8d5d0a1` — đã deploy (run `35497650837`)

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
  `product_core/server/talent/eval_data/search_silver_v1.jsonl` 23 case; lệnh
  `python manage.py search_ablation` chấm recall theo ba cấu hình
  (`structured`, `field_fts`, `structured+field_fts`), đếm unique hit từng nhánh,
  và bỏ qua case semantic chưa gán nhãn kèm cảnh báo "recall semantic chưa được đo".

**Bằng chứng local:** `tests_search_v2` **30/30**; regression `ai + talent`
**935/935**; `makemigrations --check`, Django system check và `git diff --check`
passed.

**Đã xác minh trên production sau đó (xem 17.10b):** cột generated `search_tsv`,
index trigram, nhánh lexical và `ts_rank_cd` đều chạy đúng; `EXPLAIN` chứng minh
cả hai chỉ mục dùng được. Trên SQLite các đường này vẫn báo `vendor_unsupported`
và điều kiện mảng JSONB fail-closed thành `unresolved` — đó là hành vi mong muốn
cho máy lập trình, không phải thiếu sót.

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

### 17.10b. Đợt thực thi trên production 20/09 chiều

Bốn việc ghi đã được người dùng duyệt quyền và chạy xong, theo đúng thứ tự ở
17.10:

| Việc | Kết quả |
|---|---|
| Pin `EmbeddingConfig.dimensions = 1024` | contract trong hub đọc `configured=1024 stored=1024`; một lượt truy hồi vector thật trả về 5 hồ sơ. **Nhánh ngữ nghĩa đã sống lại** sau nhiều ngày tắt |
| Deploy `a0d8e7d` (run `35497650837`) | validate + deploy-production đều success; health check đạt |
| Migration `talent/0016` + `ai/0027` | cột generated `search_tsv` (`is_generated=ALWAYS`), GIN `talent_searchprojection_tsv_gin`, `pg_trgm 1.6` và 4 chỉ mục trigram đều đã tạo |
| `rebuild_search_v2` | **611/611** Person có projection và dossier (trước đó 61), `failed=0`, mọi dòng có `search_tsv`; bảng projection 3,1 MB, dossier 3,8 MB |

Bằng chứng chỉ mục (ép `enable_seqscan = off` vì ở 611 hàng planner luôn chọn
seq scan — đây là giới hạn của kho hiện tại, không phải của chỉ mục):

- `search_tsv @@ to_tsquery('simple','ke & toan')` → **Bitmap Index Scan** trên
  `talent_searchprojection_tsv_gin`, khớp 44 hồ sơ, 0,26 ms.
- `title_norm LIKE '%ke toan%'` → **Bitmap Index Scan** trên
  `talent_searchprojection_title_norm_trgm`, 0,10 ms. Trước 0016 đường này là
  Seq Scan không có cách nào dùng chỉ mục.

Ablation đầu tiên trên dữ liệu thật (`search_ablation`, 24 case silver):

| Cấu hình | Case chấm được | Mean recall |
|---|---:|---:|
| structured | 9 | 1,0 |
| field_fts | 9 | không áp dụng (xem dưới) |
| structured+field_fts | 9 | 1,0 |

10 case semantic bị bỏ qua đúng như thiết kế vì chưa gán nhãn, và lệnh in rõ
"recall semantic chưa được đo". Lần chạy này lộ một lỗi **trong chính báo cáo**:
nhánh `field_fts` bị ghi recall 0,0 trong khi nó **không được yêu cầu chạy** cho
case deterministic — đọc thành "FTS chẳng tìm được ai". Đã sửa: cấu hình nào mà
mọi nhánh đều `not_required`/`no_hard_filter` thì recall là `null`, và bộ silver
thêm 4 case `lex-*` có `truth_plan` (truth lấy từ điều kiện cứng, plan dùng thuật
ngữ semantic) để đo đúng phần đóng góp của FTS. Cần chạy lại sau lần deploy tới.

### 17.10c. Ablation lần 2 và hai lỗi nó tìm ra

Sau khi deploy nhánh vector + từ điển (`02415df`), ablation chạy lại trên 611 hồ
sơ thật với 28 case silver (10 case semantic vẫn bị bỏ qua vì chưa gán nhãn):

| Cấu hình | Case chấm được | Mean recall | Ghi chú |
|---|---:|---:|---|
| structured | 9 | 1,000 | truth chính là tập SQL |
| field_fts | 4 | 0,989 | 3/4 case đạt 1,0 |
| vector | 4 | 0,709 | bị `top_n = 500` cắt trên case 319 người |
| structured+field_fts | 13 | 0,9966 | |
| full (thêm vector) | 13 | 0,9966 | **vector không thêm recall riêng nào** |

Đây đúng là loại số mà mục 3.7 đòi trước khi tăng trọng số hay thêm nhánh: trên
bộ case này nhánh vector tốn một lời gọi embedding mỗi lượt mà không kéo thêm ai
vào tập. Chưa đủ để bỏ nhánh (chỉ 4 case, kho 611 người, và case semantic chưa
gán nhãn là đúng chỗ vector có giá trị) nhưng đủ để **không** ưu tiên tối ưu nó.

Hai lỗi lộ ra, cả hai đã sửa trong lần deploy tiếp theo:

1. **Alias chỉ đi vào filter SQL, không vào tsquery.** Case `lex-003` ("ha noi")
   bỏ sót 14/319 người vì hồ sơ của họ ghi "hanoi" hoặc "hn" — trong tsvector đó
   là token khác hẳn, nên `to_tsquery('ha & noi')` không khớp. Nhánh lexical nay
   mở rộng theo từ điển và ghi lại `vocabulary_version`.
2. **Lỗi gọi embedding bị báo thành "không có vector trong phạm vi".** Case
   `lex-004` ghi `no_vectors_in_scope`, hoá ra là `embed()` trả rỗng. Nay
   `vector_index` ném `VectorBranchUnavailable` với mã lý do riêng
   (`vendor_unsupported`, `no_vectors_for_model`, `embedding_failed`), và "đã
   chạy nhưng không thấy ai" là `ran=true, reason=no_match_in_scope`. Gộp hai
   thứ đó vào một danh sách rỗng là đúng kiểu lỗi mà backlog này tồn tại để chặn.

Ngoài ra, `top_n_capped` trên case 319 người cho thấy `SEARCH_V2_VECTOR_TOP_N =
500` là trần thật chứ không phải con số trang trí; ở kho 500k nó phải được chốt
cùng ADR cost ở P0-00.

**Ablation lần 3, sau khi vá (deploy `35499630280`, commit `db97c42`):**

| Cấu hình | Case | Mean recall | So với lần 2 |
|---|---:|---:|---|
| structured | 9 | 1,000 | không đổi |
| field_fts | 4 | **1,000** | từ 0,989 — bản vá alias vào tsquery ăn thật |
| vector | 4 | 0,709 | không đổi (trần `top_n` chưa sửa) |
| structured+field_fts | 13 | **1,000** | từ 0,9966 |
| full | 13 | **1,000** | từ 0,9966 |

Cả 4 case lexical đạt recall 1,0 và đều ghi `vocabulary_version = 1`, tức kết quả
khớp nhờ alias và giải thích được nhờ đâu. Case `lex-003` (319 người) trước đó
bỏ sót 14 người, nay không sót ai.

Lý do của nhánh vector nay cũng nói đúng: `lex-004` báo **`embedding_failed`**
thay cho `no_vectors_in_scope`, và đó là một phát hiện thật — lời gọi embedding
thứ tư trong vài giây bị giới hạn tốc độ. Commit `762c94c` thêm **một** lần thử
lại sau 1,2 giây và tách mã lý do `embedding_rate_limited` khỏi
`embedding_failed`, để dashboard capacity của P0-01 đếm được đúng loại. Chờ
deploy `35500253243` để đo lại.

### 17.10d. Ba phát hiện nữa từ việc chạy thật trên production

**1. Một lỗi do chính đợt này gây ra: claim không bao giờ được đóng.**
Commit `65723be` đọc coverage bằng `result.get("trace")`, nhưng `result` là
`AnswerResult` (dataclass) nên `.get` ném `AttributeError` — và vì nó nằm cùng
`try` với `run_state.finish()`, **mọi lượt hoàn tất từ deploy đầu tiên đều không
đóng được claim**: `AnswerRun` treo ở `running` rồi báo `timeout` khi người dùng
mở lại cùng `client_turn_id`. Câu trả lời vẫn được `persist()` trước đó nên không
mất dữ liệu. Bằng chứng trên prod: đúng 1 `AnswerRun` sau 07:00 và nó ở trạng
thái `running`; bảng `coverage` rỗng hoàn toàn.

Sửa trong commit `a871aa4`: `_coverage_of` đọc được cả dataclass
và dict, và việc đọc coverage **tách khỏi** `try` của `finish`. Bài học đáng ghi
vào chuẩn ticket: *một dòng telemetry không được phép chặn một chuyển trạng thái*.
Bộ test cũ chỉ gọi `finish()` trực tiếp với dict nên không thể bắt được lỗi này;
test hồi quy mới dùng `AnswerResult` thật.

**2. Hạn mức endpoint embedding là một giới hạn thật, đã đo.**
Probe trên prod: 3 lời gọi liên tiếp đều được, lời gọi thứ 6–7 bị `429` **dù đã
nghỉ 8 giây**; nhưng một phút sau, 4 lời gọi liên tiếp lại được. Tức GreenNode
`baai/bge-m3` chặn theo tổng số lời gọi trong một cửa sổ, không phải theo khoảng
cách giữa hai lời gọi, và nhánh query dùng **chung** hạn mức đó với
`msbradar-embedding-worker`. Hệ quả cho kế hoạch:

- P0-01 phải có **token bucket dùng chung, ưu tiên online** — không phải thêm
  số lần thử lại. Một lượt hỏi chỉ cần 1 lời gọi nên vẫn ổn; mọi việc chạy lô
  thì không.
- P0-02 phải trả lời: đổi model embedding nghĩa là embed lại toàn kho. Ở hạn mức
  này, 500.000 hồ sơ là **không khả thi** qua GreenNode. Cấu hình đã có sẵn chế
  độ tự host (`ollama` + `nomic-embed-text`); ADR vector phải chốt đường nào.

**3. `embedding_rate_limited` trong ablation là lỗi của chính công cụ đo.**
`ablation()` gọi `vector_branch` lại cho từng cấu hình nên mỗi case tốn **hai**
lời gọi embedding; tới case thứ tư là chạm hạn mức. Giãn nhịp 2 giây rồi 6 giây
đều không cứu được, vì nguyên nhân là *số* lời gọi chứ không phải khoảng cách.
Nay mỗi nhánh chạy một lần cho cả lượt rồi dùng lại.

**Số thật sau khi sửa (deploy `35511413523`):**

| Cấu hình | Case | Mean recall | Ghi chú |
|---|---:|---:|---|
| structured | 9 | 1,000 | |
| field_fts | 4 | 1,000 | 4/4 hoàn hảo |
| vector | 4 | **0,960** | 3/4 hoàn hảo; chỉ `lex-003` còn 0,840 vì trần `top_n = 500` trên tập 319 người |
| structured+field_fts | 13 | 1,000 | |
| full | 13 | 1,000 | |

Vậy con số 0,709 và 0,71 ở các lần trước **là sai, và sai vì công cụ đo tự chạm
hạn mức của mình** — nhánh vector thực ra đạt 0,96. Kết luận "vector không thêm
recall riêng nào" vẫn đúng trên bộ case này (hybrid bằng 1,000 dù có hay không có
vector), nhưng lý do đã khác: vector gần bằng FTS chứ không yếu, và phần thiếu
của nó là **trần ngân sách**, không phải chất lượng. Đây là lý do mục 3.7 bắt
phải chạy ablation trước khi kết luận về một nhánh: lần đầu chúng tôi gần như đã
kết luận sai về nhánh vector dựa trên số của một lỗi hạ tầng.

### 17.10e. Quyết định phạm vi 20/09: 500k là tương lai

Người dùng quyết định **hoãn** phần chuẩn bị cho quy mô 500.000 hồ sơ. Mục 1.2
vẫn giữ nguyên làm nguyên tắc thiết kế (không quét Python toàn kho, không nhét ID
vào `IN`, lọc đẩy xuống SQL) vì những thứ đó không tốn gì thêm khi viết đúng từ
đầu. Nhưng các ticket **chỉ tồn tại để chứng minh ở 500k** được chuyển sang
`DEFERRED`, không tính vào việc "xong kế hoạch":

| Ticket | Phần bị hoãn | Lý do |
|---|---|---|
| P0-06 | fixture 500k, load test 30 user | host không đủ đĩa/RAM; kho thật 611 hồ sơ |
| P0-02 | ADR halfvec, dung lượng ở 500k/1M, kế hoạch embed lại toàn kho | chỉ cần khi kho lớn hoặc đổi model |
| P1-03E | union bằng một câu SQL | union trong Python dưới trần snapshot đủ cho 611–50.000 |
| P1-11 | test 10.000 candidate, throughput | chưa có nhu cầu exhaustive thật |
| P1-12 | load test đồng thời | như trên |
| P2-06 | replica/partition | như trên |

Phần **vẫn phải làm** của các ticket đó không bị hoãn: dimension contract (đã
xong), trần snapshot (đã xong), cost guard (đã xong), và mọi acceptance về tính
trung thực. Khi kho thật vượt ~50.000 hồ sơ thì mở lại bảng này trước khi bật
exhaustive rộng.

### 17.10f. Tôi đã chẩn đoán sai "hết quota" — nguyên nhân thật là một khoá

Người dùng nói quota GreenNode vẫn còn nhiều. Kiểm tra lại: **họ đúng, tôi sai.**
Bằng chứng trong `ai_llmcall`:

| Phút | Số lời gọi | Thất bại |
|---|---:|---:|
| 13:10 | 44 | 42 |
| 13:11 | 1 | 0 |
| 12:49 | 44 | 42 |
| 12:47 | 1 | 0 |

Khi lưu lượng là 1–2 lời gọi/phút thì không lỗi nào. Các phút 42 lỗi đều là lúc
**tôi chạy `answer_eval`**: judge chia lô 8 hồ sơ và bắn 4 lô song song, mỗi lô
có retry và đổi provider, thành ~44 lời gọi trong một phút. Không phải hết quota
— là **hạn mức tốc độ**, và GreenNode production chỉ có **một khoá** (hạn mức
tính theo khoá, xem `ai/keypool.py`).

Probe 12 lời gọi tuần tự cách nhau 1 giây cũng lộ thêm một lỗi trong H5: hai lời
gọi đầu qua GreenNode, **mười lời gọi sau đều là Gemini 402** — tức cặp
(gemini, gemini-3.5-flash) vẫn được gọi lại mãi dù đã bị từ chối. Dòng log "Bỏ
qua gemini/gemini-3.5-flash trong 900s" mà tôi từng dẫn làm bằng chứng H5 hoạt
động là log lúc **ghi nhận**, không phải lúc bỏ qua: điều kiện chặn dùng
`picked_model`, mà với provider dự phòng `_model_for` trả `None`, nên nó không
bao giờ đúng.

Hai việc đã sửa và deploy (`35514345840`):

1. Điều kiện chặn dùng **model thật sự sẽ được gửi**, kể cả model mặc định của
   provider.
2. Token bucket theo provider (`MSB_AI_RATE_PER_MINUTE[_<PROVIDER>]`, 0 = tắt):
   tự xếp hàng trong ngân sách thời gian còn lại, hết ngân sách thì bỏ qua
   provider đó thay vì tiêu một lời gọi để nhận 429. Không đặt biến thì hành vi
   không đổi.

**Việc bạn có thể làm để tăng hẳn năng lực:** thêm khoá GreenNode. Hạn mức tính
theo khoá nên hai khoá là gấp đôi, và `keypool` đã hỗ trợ sẵn danh sách khoá —
không cần sửa code.

### 17.10g. Bật Search V2 trên production, từng bước

Người dùng yêu cầu bật dần để kiểm tra trên prod. Cấu hình đặt trong
`~/msbradar/.env` (đã backup `.env.bak-20260920`), có hiệu lực sau khi container
được dựng lại:

| Biến | Giá trị | Vì sao |
|---|---|---|
| `SEARCH_PLAN_V2_MODE` | `shadow` | tạo CandidateSet bền + trace để so sánh, **không đổi** kết quả trả về |
| `MSB_AI_RATE_PER_MINUTE_GREENNODE` | `8` | một khoá, hạn mức theo khoá; tự xếp hàng thay vì bắn 4 lô rồi nhận 429. Con số này là **điểm khởi đầu cần hiệu chỉnh**: còn 429 thì giảm, sạch thì tăng |

Thứ tự tiếp theo: shadow chạy vài lượt thật → đối chiếu diff giữa đường cũ và
CandidateSet V2 → nếu không mất hồ sơ nào thì đổi sang `on`. Ở `on`, V2 chỉ
**thêm** recall vào pipeline hiện có và lỗi thì fail-open, nên đường cũ vẫn là
lưới an toàn.

### 17.10h. Hạn mức GreenNode tính theo MODEL, không theo khoá

Người dùng cấp thêm hai khoá GreenNode. Khoá **không** nằm trong `.env` mà trong
`ai_providerconfig.api_key_encrypted` (mã hoá bằng `SECRET_KEY`), nên đã thêm vào
đúng chỗ đó — pool hiện có 3 khoá (`vn-_l-…`, `vn-aIp…`, `vn-KYj…`).

Đo ngay sau khi thêm, 4 lời gọi liên tiếp mỗi model:

| Model | Kết quả |
|---|---|
| `qwen/qwen3.7-plus` | ok, ok, **429**, **429** |
| `qwen/qwen3.6-flash` | ok, ok, **429**, **429** |
| `z-ai/glm-5.2-hackathon` | ok, ok, ok, ok (chậm hơn: ~12 giây/lượt) |

Ba khoá **không** làm tăng thông lượng của hai model qwen, nhưng `glm-5.2-hackathon`
thì không bị chặn. Kết luận: **hạn mức là của từng model**, không phải của khoá
hay của nhà cung cấp. Vì vậy gáo token đã đổi sang cặp `(provider, model)` —
gáo theo provider vừa chặn oan model còn dư, vừa không chặn đủ model đã hết.

Bằng chứng bản vá H5 chạy đúng trên production: trong probe 12 lời gọi, sau hai
lần Gemini trả 402 thì **các lời gọi sau không còn gọi Gemini nữa** ("bỏ qua
gemini…"), chỉ còn thử GreenNode. Trước bản vá thì mười lời gọi liên tiếp đều
nướng vào Gemini.

**Quyết định cần người:** judge đang chạy `qwen/qwen3.7-plus` — model bị chặn
nặng nhất. Ba đường: (a) chuyển judge sang `glm-5.2-hackathon` (còn hạn mức
nhưng chậm gấp ~3), (b) giữ qwen và để gáo token xếp hàng (đúng nhưng lượt hỏi
dài hơn), (c) xin GreenNode nâng hạn mức cho qwen. Chất lượng judge đã được chốt
bằng benchmark 19/09 nên không tự đổi model mà không có người quyết.

### 17.10i. Shadow đã chạy trên production, và chuỗi model dự phòng

**Shadow sống.** Sau deploy `35516067601`, hub đọc `SEARCH_PLAN_V2_MODE=shadow`
và một lượt tìm thật đã tạo `CandidateSetRun` đầu tiên trên production:

| Thuộc tính | Giá trị |
|---|---|
| `candidate_total` | 505 (trên 611 ứng viên) |
| nhánh đã chạy | `field_fts` ✔, `vector` ✔, `structured` ✗ (`no_hard_filter` — plan legacy không có filter cứng) |
| `strategy` | `hybrid` |
| `retrieval_degraded` | `false` |
| `judged` | 0 — đúng: còn ràng buộc semantic nên mọi member là `unknown`, shadow không đọc sâu |

Đây là lần đầu CandidateSet hybrid chạy trên dữ liệu thật, và nó **không đổi kết
quả trả về** cho người dùng.

**Chuỗi model dự phòng (theo yêu cầu người dùng: chỉ đổi khi lỗi).** Trước đây
hết hạn mức là mất cả chặng đọc sâu, vì chuỗi dự phòng chỉ đổi *provider* chứ
không đổi *model* — mà hạn mức lại tính theo model. Nay `ai/tasks.py` khai chuỗi
model theo thứ tự chất lượng lấy từ benchmark 19/09:

| Tác vụ | Chính | Kế tiếp |
|---|---|---|
| `talent_answer_judge`, `rb_answer_judge` | `qwen3.7-plus` | `qwen3.6-flash` → `glm-5.2-hackathon` |
| `talent_answer_plan`, `rb_prospect_search` | `qwen3.7-plus` | `qwen3.6-flash` → `glm-5.2-hackathon` |
| `talent_answer_compose` | `deepseek-v4-pro` | `glm-5.2-hackathon` → `deepseek-v4-flash` |
| `cv_ocr`, `talent_embedding` | — | **rỗng**: đổi năng lực là hỏng lặng |

Ba luật: model chính được thử trên mọi provider **trước**; người gọi ghim model
thì không tự đổi; và model chính lỗi cấu hình (402/404) vẫn nổ ngay như cũ —
chỉ model **dự phòng** bị từ chối mới thử tiếp cái sau.

**Hai lần deploy hỏng ở tầng Docker, không phải code.** Deploy `35514898531` hỏng
khi pull `python:3.11-slim` (containerd ingest), `35516067601` hỏng khi khởi động
`msbradar-intelligence-indexer` ("No such container"). Cả hai lần production vẫn
khoẻ (health 200) vì container cũ chỉ bị thay sau khi image mới dựng xong. Nguyên
nhân gần như chắc là **đĩa chật**: 87% đầy, build cache 2,7 GB. Đã dọn build cache
và image mồ côi (679 MB) và dựng lại indexer bằng tay. Đĩa là một rủi ro vận hành
thật, cần theo dõi.

### 17.10j. Chuỗi model dự phòng chạy thật, và một cache chỉ ghi

**Chuỗi dự phòng có tác dụng** (đo sau deploy `35517505428`, một lượt tìm thật):

| Model | ok | lỗi |
|---|---:|---:|
| `qwen/qwen3.7-plus` (chính) | 4 | 9 |
| `qwen/qwen3.6-flash` (kế tiếp) | 4 | 2 |
| `z-ai/glm-5.2-hackathon` (cuối) | 2 | 0 |

Trước bản vá, `qwen3.7-plus` bị chặn là **mất cả lô** vì dự phòng duy nhất là
Gemini 402. Nay 10 lượt gọi thành công nhờ hạ model. Chặng judge vẫn 61% lỗi ở
lần gọi đầu, nhưng mỗi lô cuối cùng đều có model chạy được.

**Cache judgement bản đầu là một cache chỉ ghi.** Đo trên prod: ba lượt hỏi
**cùng một câu** tạo ba tập khoá mới hoàn toàn (8, 16, 40 bản), **0 lần được dùng
lại**. Khoá lấy từ `judge.dossier_key`, trong đó có `information_need`/`extract`
do LLM sinh và danh sách đoạn CV đã chọn — cả hai đổi mỗi lượt. Nếu chỉ nhìn "bảng
cache có 64 bản" thì rất dễ tưởng nó đang chạy; chỉ khi đếm số bản **được ghi lại**
(0) mới thấy sự thật.

Đã đổi khoá thành đúng ba thứ quyết định một kết luận: người + dấu nội dung hồ sơ
(`BaseDossier.fingerprint`) + bộ tiêu chí đã chuẩn hoá. Bài học ghi vào chuẩn
ticket: **một cache phải được đo bằng số lần ĐỌC được, không phải số bản đã ghi.**

### 17.11. Việc tiếp theo theo đúng dependency

Bốn việc ghi trên production của mục 17.10 đã làm xong. Còn lại:

1. **Quan sát 24 giờ** (không cần ai làm gì, chỉ chờ): log không còn
   `semantic_degraded` (H2), và `ai_llmcall` không còn 404 sai cặp provider–model
   (H5). Đạt thì H2 và H5 lên L4 — hai ticket đầu tiên đóng được.
2. **Chạy lại ablation** sau lần deploy thứ ba để xác nhận `lex-003` lên 1,0 và
   nhánh vector báo đúng lý do. Ghi số vào 17.10c.
3. **Chốt P0-06**: fixture 150–200k trong một database riêng cùng host, hay thuê
   host staging để chạy đủ 500k. Host hiện tại còn 7,5 GB đĩa nên không thể làm
   đủ 500k. **Cần người quyết.**
4. **Gán nhãn 10 case semantic** của bộ silver rồi nâng lên gold ≥60 câu, hai
   người gán nhãn và review. Đây là đường găng: mọi gate recall semantic phụ
   thuộc nó. **Cần người làm.**
5. **P1-03E** union bằng một câu SQL, và **03B** tách taxonomy/application thành
   nhánh riêng — phần còn lại của Wave 2B.
6. **Bật `SEARCH_PLAN_V2_MODE=shadow`** trên canary để thu diff legacy/V2 trên
   lưu lượng thật. Việc này đổi hành vi production (thêm ghi CandidateSet và một
   lời gọi embedding mỗi lượt) nên **cần người duyệt**, kèm rollback drill.
7. **Legal gate** cho thuộc tính nhân khẩu học trước khi bật
   `DEMOGRAPHIC_CONTEXT`. **Cần pháp chế.**
8. Sau khi 2B đóng: nối EvidenceView/cache vào T3 worker (P1-11), rồi exhaustive
   UI (P1-12), rồi RB (P1-13).

### 17.12. Audit đường demo production và bản ổn định kế tiếp

Audit read-only qua SSH sau deploy `2b25af5` xác nhận Hub/DB/Intelligence khỏe;
611/611 applicant có projection, dossier và person embedding; 2.229/2.229 CV
chunk có vector 1024 chiều; GIN và HNSW tồn tại. Sáu CandidateSet shadow đã chạy
FTS + vector thật, 500–509 member/run và không degraded. Tuy nhiên toàn bộ 3.029
member vẫn `unknown/not_read`: shadow mới chứng minh retrieval, chưa nối T2/T3.

Hội thoại demo gần nhất cho thấy nguyên nhân bất ổn không nằm ở DB/index mà ở
capacity của model:

- một câu hỏi tạo bốn lô judge song song, gây burst 429 ở qwen;
- Gemini fallback trả 402;
- compose bắt đầu bằng DeepSeek, timeout khoảng 36 giây; GLM/DeepSeek Flash chỉ
  còn 10–15 giây nên tiếp tục timeout;
- có AnswerRun hết deadline còn mang trạng thái bền `running` sau container
  restart;
- cache judgement production có 152 row nhưng chưa có hit counter và lần đo lặp
  lại không đọc được row cũ, nên mặc định phải tắt.

Increment ổn định demo thực hiện các thay đổi sau:

1. `TALENT_JUDGE_WORKERS` mặc định 1; production đặt deep-read pool 16 để vẫn
   tìm toàn kho nhưng chỉ đọc sâu hai lô xếp hạng cao nhất trong deadline.
2. Judge và compose chính chuyển sang `z-ai/glm-5.2-hackathon`: qwen chính xác
   nhưng plan + judge tự chạm rate limit; DeepSeek compose timeout. Qwen/DeepSeek
   vẫn là fallback, còn GLM được nhận trọn budget thay vì phần thời gian còn thừa.
3. `TALENT_JUDGE_CACHE` mặc định tắt cho tới khi typed constraint ID ổn định và
   có cache-hit telemetry.
4. Khi đọc trạng thái một AnswerRun `running` đã quá deadline, code compare-and-
   set nó thành `timeout`, không để UI thấy “đang chạy” vô hạn.
5. Sau deploy mới chuyển `SEARCH_PLAN_V2_MODE=on`; V2 chỉ tham gia membership
   khi có hard filter thật, các câu semantic vẫn giữ retrieval legacy làm lưới
   an toàn cho tới khi T2/T3 được nối.

**Bằng chứng local trước deploy:** 135/135 test `ai + answer runs + Search V2`
passed; Django check và migration check passed. Production probe và trạng thái
deploy phải được ghi bổ sung sau khi workflow hoàn tất; đoạn này không tự coi
local test là production acceptance.

**Kết quả triển khai:** commit ổn định nền `7252f0b` deploy thành công ở workflow
`35521490322`. Điều chỉnh capacity judge `6ca01e9` gặp một lần lỗi containerd
`CreateDiff ... no such file or directory` ở workflow `35522884085`; production
cũ vẫn khỏe. Sau khi prune an toàn build cache/dangling layers, retry workflow
`35523358207` thành công, gồm exact-SHA health verification.

**Cấu hình production sau deploy:** `SEARCH_PLAN_V2_MODE=on`, deep-read pool 16,
judge worker 1, AnswerRunner worker 2, judgement cache tắt. Migration 0028/0029
đặt cả Talent judge và compose vào `z-ai/glm-5.2-hackathon`; qwen/DeepSeek giữ
vai trò fallback.

**Probe production cuối bằng đúng câu demo Tech Lead/Senior Backend Java/Golang
tài chính:** hoàn tất 99,08 giây; retrieval 16, judged 16, unread 0,
`read_failed=false`, `read_incomplete=false`; compose GLM không fallback;
coverage nói đúng `candidate_total=500`, `judged=16`, `not_read=484`. Hai
AnswerRun cũ quá deadline còn `running` đã được chuẩn hóa thành `timeout`.

**VPS:** build cache + dangling layers giải phóng khoảng 2,81 GB; root disk từ
87% xuống 82%, còn khoảng 8,9 GB. Hai image TalentFlow `main` và `develop` đều
đang có container sử dụng nên được giữ lại; không xóa volume/database/image đang
chạy. Đây là đường demo ổn định, chưa biến partial deep-read thành exhaustive.

### 17.13. Nối CandidateSet V2 vào xếp hạng deep-read

Audit `ai_llmcall` sau deploy `6ca01e9` cho thấy hai lượt production cuối đều
chạy sạch: mỗi lượt có một plan Qwen, hai batch judge GLM và một compose GLM;
không có failed attempt. Hai failed attempt từng thấy là dữ liệu của lượt cũ
trước khi đổi route judge, nên không đổi planner theo suy đoán và không tạo thêm
rủi ro capacity.

CandidateSet V2 nay được nối vào đường Answer Engine như **một nguồn xếp hạng
RRF**, không phải danh sách ghim cứng:

- thứ tự `CandidateSetMember.ordinal` là một ranked source có trọng số ngang
  nguồn local;
- hồ sơ xuất hiện ở nhiều nguồn được tăng hạng theo branch agreement;
- hồ sơ chỉ có ở đường legacy vẫn được giữ, nên rollout không làm mất recall;
- CandidateSet `blocked`, `retrieval_degraded`, thiếu member hoặc chưa chạy đủ
  branch bắt buộc sẽ không được dùng và đường legacy tiếp tục fail-open;
- trace tách `used_for_recall` và `used_for_ranking` để audit đúng vai trò.

Việc này thay thế hành vi tạm thời chỉ dùng CandidateSet khi có hard filter.
Nó chưa tuyên bố semantic recall đã đạt chuẩn: gold P0-05 vẫn là gate bắt buộc,
và deep-read vẫn chỉ đọc pool có trần rồi báo coverage partial trung thực.

**Bằng chứng local:** test mới chứng minh candidate chỉ có ở legacy không bị
xóa và candidate được cả V2 + legacy đồng thuận được xếp trước; 270/270 test
liên quan qua. Full `ai + talent` ban đầu lộ một test router còn kỳ vọng judge
Qwen dù production/default đã chuyển GLM; test được sửa sang tác vụ
`candidate_extraction` (vẫn có primary Qwen) để tiếp tục kiểm đúng cơ chế hạ
model. Chạy lại full suite: **978/978 pass**. Bằng chứng deploy/probe exact-SHA
được ghi ngay dưới đây.

**Kết quả production:** commit `cb0b942` được push lên `main`. Workflow đầu
`35525338018` qua validate nhưng lỗi ở bước export Docker layer với
`CreateDiff ... no such file or directory`; cùng thời điểm host đang build
TalentFlow `develop`, production cũ vẫn khỏe và chưa đổi SHA. Sau khi job kia
xong, dọn riêng build cache/dangling image giải phóng khoảng **2,36 GB** (disk
87% → 82%), retry `35525873616` deploy thành công đúng SHA
`cb0b9422becb67fc23d1bd088a7434b04edfd17b`; exact-release và public health đều
qua.

Ba probe production sau deploy tạo **12/12 LLM call thành công, 0 failed**:

1. Câu semantic về backend hệ thống giao dịch/tài chính: CandidateSet 502,
   `used_for_ranking=true`, không degraded; trả 2 hồ sơ gần đúng và không bịa
   citation khi không có verdict đủ mạnh.
2. Câu demo Tech Lead/Senior Backend Java/Golang tài chính: 96,74 giây;
   CandidateSet 501, đọc 16/501, judge đủ 16, không read failure/incomplete;
   không có người đạt đủ hard/semantic criteria nên answer không gắn nguồn giả.
3. Câu rộng “có kinh nghiệm lập trình Java”: 77,20 giây; CandidateSet 500,
   đọc/judge đủ 16; trả 8 hồ sơ, 10 nguồn, compose cited đủ 10 và citation audit
   `PASS` (7 người được nhắc đều có nguồn cục bộ hợp lệ).

Kết luận của increment: bridge ranking chạy thật và fail-open đúng, nhưng đây
vẫn là interactive partial deep-read (16 hồ sơ), chưa đóng gold recall hay
exhaustive gate. Hai câu hẹp không có nguồn là kết quả “không đủ bằng chứng”,
không phải provider/retrieval crash.

## 18. Đường găng Demo Readiness — Tuyển dụng và Khách hàng

Mục tiêu ngắn hạn không phải đóng dàn đều toàn bộ backlog mà là tạo hai đường
demo vàng độc lập, ổn định và có bằng chứng: **Tuyển dụng** và **Khách hàng**.
Các ticket dưới đây được ưu tiên trước exhaustive/scale/P2, nhưng không hạ các
contract về quyền, coverage, evidence hoặc fact/inference đã chốt ở trên.

### 18.1. Thứ tự thực hiện bắt buộc

| Ưu tiên | Ticket | Kết quả phải có | Acceptance cho demo |
|---:|---|---|---|
| 1 | `DEMO-00` — Domain router | Phân luồng `RECRUITMENT/CUSTOMER/AMBIGUOUS` bằng luật chắc chắn trước, AI chỉ xử lý phần còn mơ hồ; không fallback chéo kho | 10 câu tuyển dụng + 10 câu khách hàng phân đúng; 5 câu mơ hồ hỏi lại ngắn; trace có domain, lý do, confidence |
| 2 | `DEMO-01` — RB data readiness | Xác định denominator/quyền; Customer projection, dossier, chunk, embedding, structured/FTS/vector branch và reconciliation | Không demo RB khi còn trạng thái 26 chunk/0 vector; số nguồn → projection → dossier → index đối soát được; 5–10 câu RB thật có kết quả và nguồn |
| 3 | `DEMO-02` — Talent latency | Trả tiến trình ngay, CandidateSet và chuẩn bị dossier song song; deep-read lượt đầu 8–12 hồ sơ ưu tiên, cho phép “đọc thêm”; cache theo fingerprint + constraint ổn định | first progress <1 giây; preliminary <10 giây nếu UI có pha sơ bộ; deep answer mục tiêu 30–45 giây, hard deadline 60 giây; không tăng worker gây burst 429 |
| 4 | `DEMO-03` — Golden demo pack | Bộ câu thật có expected Person/Customer, hard negative, evidence, coverage và latency | Tối thiểu 10 câu Talent + 10 câu RB + 5 câu mơ hồ + 5 follow-up; review thủ công trước khi quay |
| 5 | `DEMO-04` — Domain answer contracts | Hai mẫu trả lời riêng cho tuyển dụng và khách hàng, dùng chung evidence/coverage verifier | Không gọi người chưa đọc là không phù hợp; RB tách fact/inference và chỉ khuyến nghị, người dùng quyết định |
| 6 | `DEMO-05` — RB Answer Engine | Nối RB vào CandidateSet → EvidenceView → judgement → rank → grounded compose, có fail-open/degraded truth | Câu có đáp án trả khách hàng + nguồn; câu thiếu dữ liệu nói thiếu gì; không bịa giao dịch/nhu cầu/sản phẩm |
| 7 | `DEMO-06` — Readiness gate | Một lệnh chạy toàn bộ demo pack nhiều vòng và xuất báo cáo | 100% domain đúng; 0 provider error; 0 AnswerRun treo; 0 citation sai; coverage đúng; expected entities đạt gate; health/disk/DB connection đạt |

### 18.2. Contract đường Tuyển dụng

Câu trả lời demo tuyển dụng phải:

- chia nhóm “phù hợp cao”, “tiềm năng” và “chưa đủ bằng chứng”;
- giải thích theo từng constraint và dẫn nguồn CV/application/Edge;
- hiển thị riêng tổng CandidateSet và số hồ sơ đã đọc sâu;
- không biến `not_read` thành “không phù hợp”;
- với câu không có ai đạt đủ điều kiện, trả kết luận rỗng trung thực và có thể
  đề nghị nới đúng constraint, không đưa hồ sơ gần đúng như kết luận chắc chắn.

### 18.3. Contract đường Khách hàng

Câu trả lời demo khách hàng phải:

- nêu cơ hội/nhu cầu, sản phẩm hoặc hành động gợi ý, tín hiệu và thời điểm;
- dẫn nguồn dữ liệu được phép dùng và mức chắc chắn;
- tách rõ `FACT`, `INFERENCE`, `UNKNOWN`;
- không suy diễn giao dịch, khả năng tài chính hoặc nhu cầu khi không có bằng
  chứng;
- Radar chỉ phân tích và khuyến nghị; người dùng là người quyết định cuối cùng.

### 18.4. Golden demo pack

Talent phải phủ: kỹ năng cụ thể; title + skill + ngành; địa điểm/kinh nghiệm;
semantic transfer (“xây hệ thống giao dịch quy mô lớn”); so sánh/follow-up; và
case không có người phù hợp. RB phải phủ: nhu cầu/sản phẩm; tín hiệu giao dịch
hoặc tương tác gần đây; khách cần chăm sóc lại; so sánh cơ hội; giải thích đề
xuất; và case không đủ dữ liệu.

Mỗi case bắt buộc lưu:

1. câu hỏi và domain kỳ vọng;
2. Person/Customer phải xuất hiện và hard negative không được xuất hiện;
3. evidence span/source kỳ vọng;
4. coverage/completeness kỳ vọng;
5. latency budget;
6. câu trả lời an toàn khi không tìm thấy hoặc provider/branch degraded.

### 18.5. Quyết định tối ưu cho clip demo

Nếu chỉ đủ nguồn lực làm ba việc trước khi quay, thứ tự là:

1. làm RB có dữ liệu thật và vector/reconciliation đầy đủ;
2. giảm latency Talent xuống dưới hard deadline 60 giây mà không tạo burst 429;
3. dựng và chạy lặp bộ golden demo có expected result.

Không bật exhaustive UI chỉ để clip trông “đủ”: đường interactive vẫn được
phép đọc sâu một pool có trần, nhưng UI và câu trả lời phải nói đúng mẫu số,
số đã đọc và số chưa đọc. Gold P0-05, scale P0-06 và exhaustive P1-11/P1-12
vẫn là gate release dài hạn sau Demo Readiness.

### 18.6. Đánh giá mục 18 và phát hiện từ chat thật production (21/09)

Đọc toàn bộ 66 message thật (26 lượt Talent, 7 lượt Growth) trên production
19–21/09 qua `AssistantMessage`, cộng đo trực tiếp trên container đang chạy.
Không đoán — mọi số dưới đây lấy từ dữ liệu/lệnh thật, có script tái tạo được.

**Phê bình DEMO-00 (domain router):** không cần làm. UI đã có "Perspective
Switch" tường minh (`SearchWorkspace.tsx`, `role="tablist"`) và hai endpoint
tách biệt `/api/v1/talent/ask/` vs `/api/v1/rb/ask/` — người dùng chọn góc nhìn
TRƯỚC khi gõ, không có khoảng xám "AMBIGUOUS" nào cần AI phân loại trong sản
phẩm thật. Một bộ phân loại mới thêm nguy cơ (một tầng LLM nữa có thể lỗi/chậm)
mà không giải quyết vấn đề thật nào. Đề xuất: bỏ DEMO-00 khỏi đường găng, chỉ
giữ một việc rẻ — xác nhận Perspective Switch nhớ đúng lựa chọn qua reload.

**DEMO-01/DEMO-05 (RB rebuild) không phải blocker như giả định:** mục 18 viết
"Không demo RB khi còn trạng thái 26 chunk/0 vector". Đúng là `ProspectEvidenceChunk`
vẫn 26/0 (chưa đổi từ 20/09), NHƯNG đó là một pipeline THỬ NGHIỆM khác — đường
`rb_prospect_search` đang thực sự trả lời production KHÔNG đi qua bảng đó, mà
đọc `rb_profile`/`rb_opportunities`/structured signals. Kiểm một câu thật
("Tìm quản lý, giám đốc... thẻ tín dụng hạn mức cao"): `citation_audit.status =
PASS`, 15/15 người được nhắc có nguồn cục bộ hợp lệ, `invalid_source_numbers=[]`,
47 giây. RB **đã đủ để demo ngay bây giờ** theo đúng contract mục 18.3 (có
nguồn, có mức chắc chắn, không bịa). Việc còn lại là dựng golden case (DEMO-03),
không phải xây lại RB.

**Bốn lượt Talent thật bị huỷ giữa chừng, để lại bong bóng "(không có nội
dung)":** `aborted=true, duration_ms=0` — client rớt kết nối (đóng tab/tải lại)
trước khi pipeline sinh được gì, gần như chắc chắn vì đợi câu hỏi mẫu (xem dưới)
quá lâu mà không có tín hiệu tiến triển rõ. Đã sửa (`62a6489`, đã deploy): bỏ
ghi khi `aborted` và hoàn toàn rỗng, để không ai mở lại đúng luồng đó và tưởng
Radar lỗi giữa một buổi demo. 5 test hồi quy, backend 1969/1969.

**Sự cố "msb có những sản phẩm gì" → "Tôi chưa tra được câu này" đã tự hết:**
đúng lúc đó (20/09 04:35 UTC) `assistant_intent/web/conversation` cùng dồn vào
`qwen3.6-flash` và bị 429, Gemini dự phòng thì 402 — tức đúng lỗ hổng hạn mức
theo model mà backlog này đã sửa cùng ngày (mục 17.10f–j). Kiểm lại NGAY BÂY
GIỜ trên production: câu hỏi giống hệt trả lời đúng, có nguồn, 14,9 giây. Không
cần sửa gì thêm.

**Bug 19/09 "60 hồ sơ đọc sâu → suy ra cả kho" đã được xác nhận sửa:** golden
case cũ ghi "'Hà Nội: 5 ứng viên' trong khi thật ~500 hồ sơ có địa điểm". Chạy
lại y nguyên câu hỏi trên production: trả lời dựng từ SQL trên toàn bộ 611 hồ
sơ ("308 Hà Nội, 58 TP HCM... 580/611 có nơi ở") — đúng và nhất quán, dù mất
105 giây (không đi qua fast-path SQL sẵn có, nhưng vẫn đúng số).

**Câu hỏi demo chủ lực đang chọn SAI, không phải hệ thống lỗi:** golden case đã
ghi từ 19/09 rằng "Tìm Senior Data Analyst ở Hà Nội biết SQL và Python, trên 3
năm kinh nghiệm" **không có ai trong kho đạt đủ cả ba điều kiện** — 6 lượt hỏi
thật trong hai ngày đều đúng khi trả lời "chưa có ứng viên nào đáp ứng". Hệ
thống trung thực, nhưng một demo trực tiếp mà câu hỏi mở màn liên tục ra "không
tìm thấy ai" thì không thuyết phục. Cùng bộ tiêu chí nhưng bỏ "Senior"/"Hà Nội"
("ai biết SQL và Python?") có **10 người thật, trích dẫn CV nguyên văn** (đã
kiểm sống: "Bùi Tiến Mạnh — CV ghi rõ 'Python, SQL/MySQL' trong Tech Stack…").
Đề xuất cho DEMO-03: dùng câu rộng làm câu mở màn có kết quả, giữ câu hẹp làm
một khoảnh khắc CÓ CHỦ Ý sau đó để chứng minh đúng contract 18.2 — "không có ai
đạt đủ điều kiện, trả kết luận rỗng trung thực" — biến giới hạn thành điểm bán.

**Độ trễ là rủi ro lớn nhất còn lại cho một buổi demo trực tiếp, và đã đo thật:**

| Câu hỏi | Thời gian đo | Ghi chú |
|---|---:|---|
| Tech Lead/Backend Java-Golang tài chính | 85,2s | judge 2 lô tuần tự ≈ 61,5s |
| ai biết SQL và Python? | 127,5s | trả 10 người có trích dẫn |
| Thống kê theo khu vực | 105,1s | đúng số nhưng lẽ ra phải là SQL tức thời |

`HARD_DEADLINE=150s` — câu 127,5s chỉ còn ~22s dư trước khi bị coi là quá giờ.
Đã thử hai hướng và có bằng chứng RÕ để không đi tiếp:

- `TALENT_JUDGE_WORKERS=2` (chạy 2 lô song song để giảm còn ~1 lô thời gian):
  **chậm hơn** (95,7s) và **chỉ đọc được 8/16** — GreenNode/GLM không chịu được
  2 lô nặng chạy cùng lúc như đã tưởng từ phép đo lượt nhỏ hôm 20/09.
- `TALENT_DEEP_READ_POOL=8`: không có tác dụng vì `MIN_POOL=16` là sàn cứng
  trong code (`max(16, min(200, …))`), cần sửa code mới hạ được — đúng như mục
  18.1 DEMO-02 đã lường trước ("cho phép đọc thêm" thay vì chỉ cắt pool).

Kết luận: **không chỉnh cấu hình concurrency/pool thêm trước demo** — hai lần
thử đều xấu đi. Khuyến nghị còn lại, theo đúng độ phức tạp thấp mà mục 18 yêu
cầu: (1) chấp nhận 80–130 giây nhưng đảm bảo UI luôn hiện tiến triển từng giai
đoạn liên tục (không có khoảng lặng nào >10s không có tín hiệu) để người xem
không tưởng đứng máy; (2) tập dượt với đúng câu hỏi đã đo thời gian, không thử
câu mới chưa đo ngay trên sân khấu; (3) DEMO-02 "8–12 hồ sơ + đọc thêm" vẫn là
hướng đúng cho SAU demo, không phải việc làm gấp trước giờ lên hình.

**Việc còn lại theo đúng ưu tiên "demo trước, phức tạp để sau":**

1. Dựng DEMO-03 (golden pack) từ chính các câu đã đo ở trên — đã có 3 câu
   Talent thật (2 có kết quả + 1 rỗng trung thực) và 1 câu RB thật, chỉ cần
   thêm 5–7 câu nữa và ghi lại theo khuôn mục 18.4.
2. Diễn tập DEMO-06 (chạy cả gói nhiều vòng) bằng `answer_eval --cases` với bộ
   câu đã chốt, xác nhận latency/coverage ổn định qua ít nhất 2–3 lần lặp.
3. Bỏ DEMO-00 khỏi đường găng (lý do ở trên); dồn thời gian đó cho DEMO-03/06.
4. Theo dõi đĩa VPS (83%, còn ~8,3 GB) trước ngày quay — không chạy thêm việc
   nặng đĩa (fixture, build song song) sát giờ demo.

### 18.7. Đọc hết kết quả khớp điều kiện (21/09, commit `a57a33e`, `597d727`)

**Quyết định của chủ dự án:** dữ liệu demo ít nên tập khớp điều kiện nhỏ; cứ đọc hết
những người tìm được để thể hiện hệ thống không bỏ sót ai. Mục này **thay thế**
kết luận "không chỉnh concurrency/pool" ở cuối 18.6 (phép đo `workers=2` hôm đó
nhiễu; đo sạch hơn bên dưới cho kết quả ngược lại).

**Đã làm**
- `retrieve.py`: người khớp *đủ mọi điều kiện bắt buộc* (giao các danh sách AND-FTS
  theo từng `must_have`) được gắn `exact=True`, đứng đầu hàng đọc và **không bị cắt
  bởi pool**, trần `TALENT_READ_ALL_MAX` (mặc định 32, tối đa 96). `engine.py` báo
  `stats.exact_matches_read`.
- `TALENT_JUDGE_WORKERS` mặc định 4 (đo: 4 lô song song đọc 32 hồ sơ trong 31,2 s;
  6 lô chạm hạn mức ~8 lời gọi/phút của GLM).
- `ai/router.py::_attempts`: model dự phòng của **cùng nhà cung cấp** được thử
  ngay sau model chính, trước khi sang nhà cung cấp khác. Nguyên nhân: GLM timeout →
  Gemini 402 → hết ngân sách trước khi tới qwen, làm rơi lô judge.

**Đo trên prod sau khi bật `POOL=32`, `WORKERS=4` (trước bản sửa router)**

| Câu hỏi | Thời gian | Đọc | Kết quả |
|---|---|---|---|
| ai biết SQL và Python? | 64 s (trước 128 s) | 32, gồm 18 người khớp đủ | `incomplete=False` |
| Tech Lead / Senior Backend Java–Golang tài chính | 97 s | 24 | `incomplete=True` (GLM timeout) |
| Chuyên viên QHKH doanh nghiệp >5 năm | 101 s | 16 | `incomplete=True` |

**Đo lại sau bản sửa router `597d727` (đã deploy)**

| Câu hỏi | Thời gian | Đọc | Kết quả |
|---|---|---|---|
| ai biết SQL và Python? | 71 s | 32 (18 người khớp đủ) | `incomplete=False` |
| Tech Lead / Senior Backend Java–Golang tài chính | 86 s | 32 | `incomplete=False` (trước: 24, bị bỏ lô) |
| Chuyên viên QHKH doanh nghiệp >5 năm | 104 s | 16 | `incomplete=True`: 4 lần GLM timeout, mất lô |

Hai câu đầu đã đọc đủ. Câu 3 vẫn mất lô vì GreenNode chậm/timeout; một lần chạy liền
ngay sau đó còn thấy cả 3 khoá báo giới hạn tốc độ. Kế hoạch `must_have` của câu 3
do LLM sinh nên không ổn định giữa các lần (lần thì 32 người khớp đủ, lần thì 0).
Còn một lỗ hổng router: khi breaker ngắt GreenNode 90 s, `order` loại cả provider nên
các model dự phòng qwen cùng nhà cũng bị bỏ theo, chỉ còn Gemini 402.

**Bài học vận hành:** file env thật của prod là
`/home/ubuntu/msb-radar-platform/runtime/product.env`; `~/msbradar/.env` chỉ là
symlink do deploy tạo. Không `sed -i` vào symlink. Deploy chỉ tạo `product.env` khi
chưa có, nên sửa trực tiếp file này thì bền. Đổi env xong phải recreate container hub.

**Giới hạn còn lại (nói thật khi trình bày):** chỉ đảm bảo đọc hết người khớp *nguyên
văn AND* tới 32 người; câu hỏi thuần ngữ nghĩa vẫn đọc theo pool xếp hạng. Chế độ đọc
toàn bộ (P1-11/12) và "đọc thêm" chưa xây.

**Sau khi nạp tiền Gemini (21/09, đã restart hub):** Gemini hết 402 và đọc judge thành
công 2/4 lượt (2 lượt lỗi do timeout khi ngân sách đã cạn). Đo lại: câu 1 đọc 32 trong
68 s, câu 2 đọc 32 trong 60 s (cả hai `incomplete=False`); câu 3 vẫn 16/29 người khớp,
104 s, `incomplete=True`. Nguyên nhân thật của câu 3 là GLM treo ~42 s (timeout) khi 3–4
lô chạy song song, rồi qwen cùng nhà cũng timeout/429 — không phải do lỗ hổng breaker
đã nêu ở trên nên **không sửa router thêm**. Việc còn lại nếu cần: đợt đọc lại lô lỗi
hoặc nới `READ_BUDGET_SECONDS` (80 s → ~100 s, sát trần 150 s nên rủi ro).

**Đọc lại lô lỗi + nới ngân sách (21/09, commit `6c0c488`):** `judge()` chạy tối đa 2
đợt đọc lại (2 luồng) cho hồ sơ của các lô lỗi/bỏ dở khi còn ≥20 s và có hạn chót.
`READ_BUDGET_SECONDS` 80→130 (RB 90→130), `TURN_BUDGET_SECONDS` 135→195,
`HARD_DEADLINE` 150→210. Đo prod sau deploy (dù có 10 lượt timeout/429 từ GreenNode):
câu 1 đọc 32/32 trong 39 s; câu 2 đọc 32 trong 75 s; câu 3 đọc 32 (32 người khớp đủ)
trong 149 s — cả ba `incomplete=False`. Đánh đổi: câu khó có thể chạy tới ~150 s
thay vì cắt ở 100 s; trần tuyệt đối 210 s. Lần deploy đầu tự rollback vì `curl` health
công khai bị ngắt SSL thoáng qua (container đã healthy); chạy lại thì qua.

**Chất lượng đọc hồ sơ theo bối cảnh + chuỗi dự phòng judge (21/09, `c` các commit sau `49b007f`):**
- Đọc chat thật hôm nay (JD Giao dịch viên, 2 lượt): người đã lên Phó phòng/Kiểm soát viên
  nhưng từng làm GDV vẫn lọt danh sách chính vì `must_have` là "ứng tuyển *hoặc có kinh nghiệm* GDV"
  và ③ không có khái niệm cấp bậc hiện tại. Sửa: ③ trả thêm `cap_do` (dung|cao_hon|thap_hon|chua_ro);
  ④ chuyển `cao_hon` xuống "gần đúng" kèm lý do (`stats.over_level`); ① ghi cấp bậc vị trí vào
  `information_need`. `JUDGE_SCHEMA_VERSION` 3 để bỏ cache cũ. Đo lại: người Phó phòng nay ở
  "gần đúng: cấp bậc hiện tại cao hơn vị trí cần tuyển".
- Judge luôn rơi về Gemini: GLM timeout ~60 s / 429, rồi qwen cũng hết hạn mức. Chuỗi mới:
  GLM → qwen3.7-plus → **deepseek-v4-flash** → qwen3.6-flash → Gemini. Đo prod: deepseek-flash 8/8 hồ
  sơ/42 s (ngang GLM); deepseek-v4-pro 0/8 sau 70 s nên không dùng. Ngân sách mỗi lô 70→100 s và
  router bỏ qua lượt dự phòng giữa chuỗi khi chỉ còn <30 s (`min_attempt_seconds`): trước đó deepseek
  chỉ được 9 s, qwen 3 s — chắc chắn timeout — rồi Gemini (4 s) mới chạy.
- Đo lại JD GDV sau deploy: 103 s, `incomplete=False`, 4/4 lô GLM thành công (không cần dự phòng).
  Đánh đổi: bộ lọc cấp bậc chặt hơn nên danh sách chính ngắn hơn (1 người) và nhiều "gần đúng" hơn.

**JD đính kèm bị rẽ sang hội thoại + tra web (21/09 18:27, sửa ở `4a58e06` và commit sau):**
JD `MRRB` chứa câu "cơ cấu danh mục tín dụng … theo …" khớp bộ dò thống kê (`_DISTRIBUTION`)
chạy trên TOÀN BỘ tin nhắn kể cả nội dung JD ⇒ ① `find_people` bị đổi thành `analyze`, rồi ở
engine bị bẻ sang `general` ⇒ nhánh hội thoại + "Tra trên internet", không tìm hồ sơ nào. Sửa:
(1) `plan.user_words()` — các bộ dò từ khoá chỉ nhìn lời người dùng, bỏ khối "TÀI LIỆU ĐÍNH KÈM";
(2) `general` mà có `must_have` hoặc "tài liệu đính kèm + tìm người phù hợp" ⇒ `find_people`;
(3) engine không bẻ sang `general` khi đó là yêu cầu tìm người theo tài liệu. Đo lại trên prod:
các bước "Tìm trong kho → Đã đọc sâu 32 hồ sơ", `shape=find_people`, `incomplete=False`, 118 s,
kết quả trung thực "không ai thoả đầy đủ" kèm 5 người gần đúng (kho demo chưa có nhiều hồ sơ rủi ro tín dụng).

