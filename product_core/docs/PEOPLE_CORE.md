# Shared People Intelligence Core

**Phase:** 4 — hoàn thành
**Master Plan:** mục 10–18
**Vị trí:** `server/people/`

> "Đây là phần quan trọng nhất của MSB Radar." — Master Plan mục 10

---

## 1. Hai nguyên tắc

**Một Person là một con người.** Không phải một CV, không phải một lượt ứng tuyển.
Một người có thể có nhiều CV, ở nhiều nguồn, qua nhiều năm.

**Một People Database, nhiều nghiệp vụ.** Talent Radar và RB Radar dùng chung Person;
mỗi bên gắn thêm hồ sơ riêng chứ không tạo lại một cơ sở dữ liệu con người thứ hai.

```text
Person
├── Identity        định danh mạnh (email, điện thoại, LinkedIn, mã ứng viên)
├── SourceRecord    bản ghi thô từ Edge (thuộc app core)
├── Document        CV các phiên bản
│   └── DocumentTextLink → ParsedTextVersion (mọi bản parsing, khử trùng theo Person)
├── Signal          thay đổi/sự kiện đáng chú ý
├── Relationship    trạng thái quan hệ, tách riêng theo nghiệp vụ
├── Interaction     việc con người đã làm với hồ sơ
└── Opportunity     cơ hội tuyển dụng hoặc bán lẻ
```

### CV, lượt nộp và phiên bản text là ba khái niệm khác nhau

- `SourceRecord` cho biết một người đã ứng tuyển bao nhiêu lần/vị trí/giai đoạn.
- `Document` là file gốc duy nhất theo SHA-256; cùng file dùng cho nhiều lượt nộp không bị nhân bản.
- `ParsedTextVersion` là nội dung chữ duy nhất theo Person; hai file khác bytes nhưng bóc ra cùng
  text chỉ lưu text một lần. `DocumentTextLink` giữ mọi kết quả Edge, Hub extractor và Hub AI.

Mỗi Document có một `primary_text_version` dùng cho tìm kiếm, nhưng các bản parsing khác không bị
ghi đè. Khi gộp Person, file, liên kết lượt nộp và các text version cũng được hợp nhất/dedupe.

---

## 2. Cân nhắc chi phối mọi thiết kế ở đây

| Kiểu sai | Hậu quả | Gỡ được không |
|---|---|---|
| **Gộp nhầm** hai người thành một Person | Hồ sơ trộn lẫn, CV người này nằm dưới tên người kia, recruiter gọi nhầm người | Gần như không |
| **Tách nhầm** một người thành hai Person | Mất bối cảnh lịch sử | Gộp lại bất cứ lúc nào |

Vì vậy mọi quy tắc đều nghiêng về **tách**: thà bỏ sót một phép khớp còn hơn khớp nhầm.

---

## 3. Chuẩn hoá định danh (`normalize.py`)

### Điện thoại → E.164

Master Plan mục 12 yêu cầu E.164, còn Edge mới chỉ bỏ ký tự phân cách. Chênh lệch đó
được xử lý ở Hub — nếu không, `0901234567` và `+84901234567` sẽ thành hai định danh
khác nhau của cùng một người.

```text
0901234567 · 090 123 4567 · 090-123-4567 · +84901234567
84901234567 · 0084901234567 · (090) 123.4567
                    ↓
              +84901234567
```

Cũng quy đổi **đầu số 11 số cũ trước 2018** (`0162…` → `0322…`): CV cũ trong kho còn
đầy số theo định dạng đó.

**Số cố định bị loại** (`024 3999 8888`). Cố ý: số tổng đài công ty dùng chung cho cả
phòng — lấy nó làm định danh sẽ gộp nhầm hàng chục người thành một.

> ⚠️ Danh sách đầu số phải **đủ**. Bản đầu tiên thiếu nhóm `09x` — chính là nhóm phổ
> biến nhất — khiến mọi số 090/091/096/097/098 mất định danh điện thoại. 12 test đỏ
> cùng lúc vì đúng một dòng đó. Sửa đầu số thì chạy lại toàn bộ `resolve_pending()`.

### Email

Chỉ hạ chữ thường và cắt khoảng trắng. **Không** bỏ dấu chấm hay phần `+tag`: quy tắc
đó chỉ đúng với Gmail, áp cho tên miền doanh nghiệp sẽ gộp nhầm hai hộp thư khác nhau.

### Ô liên hệ chứa NHIỀU giá trị (2026-09-06)

Edge từng nối mọi email/SĐT bóc được từ CV vào một ô: `"a@x.com, b@y.com, c@z.com"`.
`normalize_email` khớp `^[^@\s]+@…$` nên chuỗi có dấu phẩy trả **rỗng**;
`normalize_phone` nối hết chữ số thành 20 số rồi cũng trả **rỗng**. Hậu quả: Hub
**im lặng vứt cả định danh**.

Đo trên 283 hồ sơ thật: **28 mất email, 32 mất SĐT, 5 hồ sơ mất cả hai** → `resolve()`
trả `SKIPPED`, không tạo Person nào.

Và thứ bị vứt chính là mỏ vàng: `thuy.pt@seabank.com.vn`, `phuongntm39@vpbank.com.vn`,
`hadtv@mbv.com.vn` — **người tham chiếu là banker ngân hàng đối thủ**.

Nay có `split_contacts` / `split_emails` / `dedupe_emails` / `choose_primary_email` /
`choose_primary_phone`. Ba quyết định quan trọng:

1. **`normalize_email`/`normalize_phone` giữ nguyên mức chặt.** Chúng là lưới an toàn
   chống gộp nhầm; nới ra là mở đúng cái cửa cần đóng. Việc tách nhiều giá trị nằm ở
   lớp trên.
2. **Chỉ MỘT định danh mạnh mỗi loại.** Gắn cả ba email trong ô cho ứng viên là cách
   chắc chắn nhất để gộp nhầm: hai ứng viên cùng ghi một người tham chiếu sẽ dính vào
   chung một Person. Phần dư đi qua `ContactMention` (mục 8).
3. **Thứ tự KHÔNG đủ để chọn.** Giả thiết "giá trị đầu là của ứng viên" đo được chỉ
   đúng **50%** (vị trí #2 còn đúng 61%). Thứ tự ưu tiên thật: **khớp tên → hộp thư cá
   nhân → vị trí đầu**. Chỉ khi cả ba đều không phân định được mới bật `needs_review`.

`dedupe_emails` **chỉ gộp khi một chuỗi là tiền tố của chuỗi kia** — ca thật là bộ
trích PDF trả `bichnguyen16042004@gmail.co` cạnh `…@gmail.com`. Cố ý **không** gộp
theo khoảng cách sửa: `an1@gmail.com` và `an2@gmail.com` chỉ khác một ký tự mà là hai
người thật.

> Cờ `needs_review` chỉ bật theo phần **email**. Bản đầu tính cả điện thoại và
> 36/283 hồ sơ (13% kho) vào hàng đợi soát tay — người dùng sẽ ngừng đọc cờ đó và mất
> luôn tác dụng cảnh báo. Chỉ tính email thì còn 8 ca, và đúng là 8 ca thật sự mập mờ.

### Tên — KHÔNG phải định danh

`normalize_name()` chỉ dùng để gợi ý trùng lặp cho người xem. Ở Việt Nam "Nguyễn Văn A"
có hàng nghìn người trùng tên; gộp Person theo tên là cách chắc chắn nhất để trộn lẫn
hồ sơ hai người.

### Mã ứng viên của nguồn

Luôn kèm tên nguồn: `candidate_id` 12345 của TopCV và của VietnamWorks là hai người
khác nhau.

Dùng `candidate_id`, **không dùng `cv_id`** — `cv_id` là mã một *lượt ứng tuyển*, nên
cùng một người nộp hai lần sẽ ra hai `cv_id`. Lấy nó làm định danh người là sai ngữ nghĩa.

---

## 4. Phân giải (`resolution.py`)

```text
payload → rút định danh mạnh → tra Identity → ?
                                              ├── 0 Person  → tạo mới
                                              ├── 1 Person  → khớp
                                              └── ≥2 Person → XUNG ĐỘT
```

**Không có định danh mạnh → bỏ qua, không tạo Person.** Bản ghi chỉ có mỗi cái tên sẽ
đẻ ra vô số Person rác trùng tên, không ai dùng được. Bản ghi vẫn ở `pending` nên lần
đồng bộ sau Edge gửi thêm email/điện thoại là nó tự phân giải được.

### Xung đột: email → A, điện thoại → B

**Không tự gộp.** Hai người thật có thể dùng chung một số điện thoại (vợ chồng, người
nhà điền hộ), và gộp nhầm hai hồ sơ gần như không gỡ lại được.

Hệ thống tạo `IdentityConflict`, đánh dấu cả hai Person là `needs_review`, và **không
cướp định danh của ai** — email vẫn thuộc A, điện thoại vẫn thuộc B. Đồng bộ lại nhiều
lần cũng chỉ có một phiếu xung đột.

> **AI không quyết định việc gộp định danh** (Master Plan mục 12). `merge()` chỉ được
> gọi từ hành động của người dùng trong trang quản trị.

### Không ghi đè

`_refresh_snapshot()` chỉ điền vào chỗ đang trống. Bản ghi mới không nhất thiết đúng
hơn: một CV cũ tải về sau vẫn là CV cũ.

### Gộp

`merge()` chuyển định danh, tài liệu, tín hiệu, tương tác, cơ hội sang Person chính,
rồi đặt `merged_into` thay vì xoá — mọi liên kết cũ vẫn đi tới được Person đúng, và
việc gộp còn lần ra được về sau. `canonical()` đi theo chuỗi gộp, có chặn vòng lặp.

---

## 5. Phân giải chạy tách khỏi luồng nhận

```text
POST /api/v1/edge/sync/  →  lưu SourceRecord  →  trả kết quả cho Edge
                                              →  _resolve_quietly()  ← lỗi bị nuốt
```

Edge đã hoàn thành phần việc của nó khi dữ liệu nằm an toàn trong bàn nhận. Để lỗi
phân giải làm hỏng phản hồi sẽ khiến Edge gửi lại những bản ghi vốn đã lưu thành công.

Vì bản ghi chưa phân giải được vẫn ở `pending`, `resolve_pending()` chạy lại lúc nào
cũng được — **kể cả sau khi quy tắc phân giải thay đổi**. Đây là lý do bàn nhận tồn tại:
sửa logic rồi chạy lại trên dữ liệu đã có, không phải xin Edge gửi lại 20 nghìn bản ghi.

---

## 6. Đã kiểm chứng đầu cuối

Edge thật → HTTP thật → Hub thật, 5 lượt ứng tuyển của 3 người:

| Tình huống | Kết quả |
|---|---|
| Cùng người, 3 nguồn (TopCV + VNW + CareerViet) | **1 Person**, 3 SourceRecord |
| Cùng người, SĐT viết `0901234567` và `+84 90 123 4567` | Khớp về một Person |
| **Trùng tên hoàn toàn**, khác email/điện thoại | Vẫn là **hai Person** |
| Người khác hẳn | Person riêng |
| Xung đột giả | **0** |

Đúng tiêu chí nghiệm thu Master Plan Phase 5.

---

## 8. Người tham chiếu & quan hệ người–người (2026-09-06)

CV ứng viên thường kèm khối "Người tham chiếu": họ tên, chức danh, công ty, email, SĐT
của một người thứ ba — rất hay là quản lý cũ đang làm ở ngân hàng khác. Vừa là nguồn
ứng viên chất lượng cao, vừa là khách hàng tiềm năng cho RB.

**Phải đọc lại text CV, không xử lý ô liên hệ đã làm phẳng.** Ô liên hệ mất sạch ngữ
cảnh (xem mục 3); text CV thì nói thẳng: `NGƯỜI THAM CHIẾU: Nguyễn Văn A — Trưởng
phòng — SeABank — 0912…`. Vị trí trong văn bản và tiêu đề mục mới là sự thật gốc.

```text
Document.best_text
   │  has_reference_markers()      ← cổng rẻ; CV không có mục này thì KHÔNG gọi AI
   ▼
intel/contacts.extract_contacts()  ← task AI `cv_reference_extraction`
   │  lọc: mọi email/SĐT không có NGUYÊN VĂN trong CV đều bị loại
   ▼
people.ContactMention              ← tầng có bằng chứng, chưa tạo người
   │  promote_confident()  (confidence ≥ 0.80)
   ▼
resolution.resolve()  →  Person(origin="cv_reference", is_applicant=False)
   ├─→ people.PersonLink(subject=ứng_viên, related=người_tham_chiếu, kind="reference")
   └─→ people.Signal(domain="rb", signal_type="cv_reference") → rb.routing.route_signal()
```

**Đường thứ hai — `record_blob_contacts`.** `extract_contacts` chỉ bắt được người
tham chiếu khi text CV có tiêu đề rõ. CV ghi người giới thiệu chen ngang một dòng
thì lọt. Nhưng Edge vẫn vớt email/SĐT họ vào `cv_emails`/`cv_phones`. Phần dư đó
(sau khi trừ liên hệ của chính ứng viên và những gì đường AI đã ghi) được ghi
thành `ContactMention` điểm tin **0.25**, `extractor="edge_blob"`, không tên,
không bằng chứng — dưới `AUTO_PROMOTE_GATE` nên **luôn** phải qua người xem.

**Xem/duyệt:** `GET /api/v1/intel/contacts/` (lọc `?extractor=`), `POST
/api/v1/intel/contacts/<id>/` với `{"decision": "accept"|"reject"}` (admin). Trước
đây chỉ có Django admin.

- **Dùng lại `resolution.resolve()`** thay vì tự tạo Person: được luôn khử trùng theo
  `Identity` và xử lý xung đột. Hệ quả đẹp: nếu người tham chiếu **về sau tự ứng
  tuyển**, trùng email sẽ khớp vào đúng Person đang có — `is_applicant` bật lên, còn
  `origin` giữ nguyên (biết đến qua đâu là chuyện quá khứ), và quan hệ vẫn nguyên vẹn.
- **`PersonLink` ≠ `Relationship`.** `Relationship` là Person ↔ một nghiệp vụ (unique
  `person`+`domain`). `PersonLink` là **người ↔ người**, có hướng, có `CheckConstraint`
  chặn tự trỏ về chính mình.
- **Chống bịa là chốt chặn bắt buộc**: model không được "nhớ hộ" một địa chỉ nào.
  Với SĐT thì so trên chuỗi chỉ-chữ-số của cả CV, vì `0912 345 678` và
  `(+84) 912.345.678` là cùng một số.

### `Person.is_applicant` — vì sao mặc định `True`

Người tham chiếu là Person thật nhưng **chưa từng ứng tuyển**; đếm họ vào "tổng hồ sơ"
sẽ thổi phồng mẫu số và kéo tụt mọi tỷ lệ phủ của Answer Engine. `Person.applicants()`
là vũ trụ mặc định của mọi bề mặt tuyển dụng (`talent/search.py`, `answer/corpus.py`,
`structured_match.py`, `superlative.py`). `rb/prospects.py` **cố ý không lọc** — bán
hàng muốn cả hai nhóm.

> Mặc định là `True` chứ không phải `False`, và đó là lựa chọn có chủ đích. Quên bật
> cờ cho một ứng viên thật → hồ sơ **biến mất im lặng** khỏi tìm kiếm (nặng, khó phát
> hiện). Quên tắt cho một người tham chiếu → họ hiện thêm trong pool ứng viên (nhẹ, mà
> họ vốn cũng là mục tiêu tuyển dụng tốt). Bản đầu để `False` và **16 bài kiểm thử tắt
> ngay** vì mọi Person tạo thẳng bằng ORM đều rơi khỏi kết quả — đúng kiểu hỏng cần tránh.

## 9. AI trên Hub thực sự chạy từ khi nào (2026-09-06)

Trước ngày này Hub **không hề dùng AI với dữ liệu mới**, dù mã đã viết đủ:

- `INTEL_AUTO_ENQUEUE_EXTRACTION` mặc định `False` → ingest không xếp hàng gì.
- `run_extraction_worker` / `parse_missing_cvs` chỉ là lệnh gõ tay, **không cron/systemd
  nào gọi**.
- `store_file()` (pha 2 — đường đi thường của file mới) **không** kích hoạt parsing bù;
  `ingest_metadata` thì gọi được nhưng lúc đó file chưa tồn tại.

Đo trên CSDL thật: **1 `ExtractionRun`, 0 `ExtractionJob`, 0 `ExtractedFact` nào có
`source_kind="ai"`**.

Nay: cờ mặc định `True`, `store_file()` gọi `transaction.on_commit(parse_missing…)`, và
`core/worker.py` chạy một luồng nền trong tiến trình web (bật/tắt bằng
`HUB_BACKGROUND_WORKER`) lặp ba bước theo đúng thứ tự phụ thuộc: `resolve_pending()` →
parsing bù → `run_extraction_worker`. Không thêm Celery/Redis — dự án đã cố ý chọn
"bảng + lệnh" thay vì hàng đợi ngoài.

> `should_start()` dùng danh sách **CHO PHÉP** (chỉ gunicorn/uvicorn/daphne và
> `runserver` với `RUN_MAIN=true`), không phải danh sách chặn. Worker gọi AI thật —
> tiêu tiền, ghi dữ liệu — nên mặc định phải là "không chạy". Danh sách chặn thì mỗi
> lệnh quản trị mới, mỗi script `python -c` có `django.setup()` đều âm thầm lọt qua.

## 9b. Text CV dài → cột tra cứu được (2026-09-06)

Edge gửi lên "một đoạn văn bản dài" (`Document.best_text`). Bóc fact bằng AI
(`intel/extraction.py`, task `candidate_extraction`) chỉ là **nửa việc** — trước hôm
nay `ExtractedFact` bóc xong chỉ nằm trong bảng của nó và giúp đúng **một nhánh hẹp**:
bộ lọc theo mã canonical trong `talent/search.py`, và nhánh đó chỉ chạy khi câu hỏi
được planner nối sang mã. Tìm kiếm cấu trúc mặc định đọc `TalentProfile.*` (do
`derive.py` dựng **chỉ từ payload có cấu trúc của nguồn**, KHÔNG đọc CV) + `Document.
parsed_text` bằng `icontains`. Chỉ mục ngữ nghĩa cũng lấy từ `TalentProfile.*` +
blob thô.

Đo trên CSDL dev: `TalentProfile.summary` rỗng 8/8, `MaterializedProfile` = 1 (chết).

Nay `run_for_person` gọi thêm `_project_to_search(person)` ở nhánh thành công:

```text
run_for_person  →  ExtractedFact (accepted, is_current)
                     │
                     ▼
talent.derive.apply_extracted_facts
  lấp cột TalentProfile còn trống — nguồn của tìm kiếm cấu trúc,
  chỉ mục ngữ nghĩa và Person 360
  (post_save → dựng lại chỉ mục ngữ nghĩa)
```

`apply_extracted_facts` bám đúng "Edge-first, AI fill gaps": payload (qua `derive`)
thắng, fact CV chỉ điền chỗ trống; `curated_fields` miễn nhiễm. Ánh xạ `_FACT_TO_PROFILE`
(`city→location`, `education_level→education`, `experience_summary→summary`,
`skills→skills` merge, `languages→foreign_language`…). Lấy `fact.canonical_label`
nếu có — cột tra cứu nhận luôn cách viết đã chuẩn hoá.

> `experience_summary` từng có `gate=1.01` (không thể đạt) nên kẹt `proposed` mãi,
> `current_facts` bỏ qua, cột `TalentProfile.summary` rỗng toàn kho. Hạ xuống 0.85
> (2026-09-06): cao nhưng đạt được, evidence bắt buộc.

**CỐ Ý KHÔNG gọi `intel.projection.build_for_person` ở đây.** `MaterializedProfile`
là tối ưu cho kịch bản triệu hồ sơ (§21.7) — search đọc một ảnh phẳng thay vì join
hàng nghìn fact. Ở quy mô hiện tại, bộ lọc mã canonical truy `ExtractedFact` qua
index `(person, field, is_current)` là đủ, và `MaterializedProfile` KHÔNG có nơi
nào đọc. Auto-ghi một bảng không ai đọc chỉ là nợ. Khi quy mô đòi hỏi, dựng đường
đọc bằng bảng nối chuẩn hoá `PersonCode(person, bucket, code)` (lọc có index, chạy
được cả SQLite lẫn Postgres) — không dùng JSON-containment. `rebuild_search_projection`
vẫn còn để dựng thủ công.

## 11. Đổi việc → Signal RB (2026-09-06)

Trước đây KHÔNG có gì sinh Signal từ chính luồng đồng bộ Edge → Hub. `derive()`
nay so công ty (`last_company`/`current_company`) của hai lượt ứng tuyển gần nhất
có công ty khác nhau và không phải placeholder → `Signal(domain="rb",
signal_type="job_change", source="edge_sync")` + `rb.routing.route_signal`.

- **Idempotent** theo khoá `get_or_create(person, domain, signal_type, source,
  observed_at)` với `observed_at` = mốc ứng tuyển của bản mới. Chạy lại `derive()`
  không đẻ thêm; chỉ lượt ứng tuyển mới hơn với công ty khác mới tạo Signal mới.
- **`evidence` có `reason`/`role`** — hai key mà `rb.suggestions.from_signal` đọc
  để suy sản phẩm. Câu `reason` khớp hint `PRODUCT_PAYROLL` ("tài khoản lương")
  nên đổi việc → đề xuất chuyển tài khoản lương + mở thẻ. Thiếu hai key này thì
  Signal chỉ hiện ở Person 360 chứ không sinh `OpportunitySuggestion`.
- Bọc try/except quanh cả `_detect_job_change`: suy hồ sơ đã ghi xong, lỗi nhánh
  tín hiệu không được kéo bước đó về `pending`.

## 12. Còn thiếu

- [x] ~~Giao diện Person 360 (Master Plan mục 24)~~ — Phase 6, `web/src/Person360.tsx`
- [ ] Hàng đợi xử lý xung đột/review trên React — `IdentityConflict`, `ReviewItem`,
  `ContactMention` đều đã có API (`/api/v1/intel/review/`, `/api/v1/intel/contacts/`,
  `/api/v1/people/conflicts/`) nhưng chưa có màn hình React; hiện chỉ Django admin
- [x] ~~Document gắn với file thật trên Cloudflare R2~~ — Phase 5, `server/core/storage.py` (`R2Storage`)
  + Edge đồng bộ file CV thật, không chỉ metadata
- [x] ~~Sinh Signal từ luồng đồng bộ Edge → Hub~~ — §11 (đổi việc). Còn "CV mới / đổi
  địa bàn / tăng thâm niên" chưa dò
- [x] ~~TalentProfile / RBProfile gắn lên Person~~ — Phase 6 và 12
- [ ] `MaterializedProfile` (§21.7) — cố ý hoãn tới khi quy mô đòi hỏi; xem §9b
